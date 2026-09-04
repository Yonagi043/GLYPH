"""Immutable analysis-plan and input-snapshot services."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from glyph_features.asset_system.catalog import canonical_json, stable_id, validate_record

from .catalog import Catalog, CatalogError


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_valid(value: dict[str, Any], schema_path: Path) -> None:
    errors = validate_record(value, schema_path)
    if errors:
        raise CatalogError("CONTRACT_INVALID:" + " | ".join(errors))


def freeze_analysis_plan(
    catalog: Catalog,
    workspace_root: str | Path,
    plan_path: str = "configs/joint_analysis_plan_v1.json",
) -> dict[str, str]:
    root = Path(workspace_root).resolve()
    path = root / plan_path
    plan = json.loads(path.read_text(encoding="utf-8"))
    _require_valid(plan, root / "schema/analysis_plan.schema.json")
    registered = catalog.register_analysis_plan(plan)
    registered["artifact_id"] = catalog.register_artifact(
        {
            "module_id": "workbench",
            "logical_type": "analysis_plan",
            "path": plan_path,
            "sha256": _sha256(path),
            "schema_version": plan["schema_version"],
            "data_classification": "public_code_or_schema",
            "record_count": 1,
            "validation_schema": "schema/analysis_plan.schema.json",
        }
    )
    return registered


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git_text(root: Path, *arguments: str, error_code: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CatalogError(error_code) from error
    return result.stdout.strip()


def _git_commit_bytes(root: Path, commit: str, relative_path: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{relative_path}"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CatalogError(
            f"SNAPSHOT_INPUT_NOT_IN_GIT_COMMIT:{relative_path}"
        ) from error
    return result.stdout


def _git_provenance(
    root: Path,
    requested_commit: str | None,
    *,
    committed_files: dict[str, str],
    producer_commits: Iterable[str],
) -> dict[str, Any]:
    repository_root = _git_text(
        root, "rev-parse", "--show-toplevel", error_code="SNAPSHOT_GIT_REPOSITORY_INVALID"
    )
    if Path(repository_root).resolve() != root:
        raise CatalogError("SNAPSHOT_GIT_REPOSITORY_MISMATCH")
    head = _git_text(
        root,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
        error_code="SNAPSHOT_GIT_HEAD_INVALID",
    )
    candidate = requested_commit or head
    if not GIT_SHA.fullmatch(candidate):
        raise CatalogError("SNAPSHOT_GIT_COMMIT_INVALID")
    resolved = _git_text(
        root,
        "rev-parse",
        "--verify",
        f"{candidate}^{{commit}}",
        error_code="SNAPSHOT_GIT_COMMIT_INVALID",
    )
    object_type = _git_text(
        root,
        "cat-file",
        "-t",
        candidate,
        error_code="SNAPSHOT_GIT_COMMIT_INVALID",
    )
    if resolved != candidate or object_type != "commit":
        raise CatalogError("SNAPSHOT_GIT_COMMIT_INVALID")
    if candidate != head:
        raise CatalogError("SNAPSHOT_GIT_COMMIT_NOT_HEAD")
    dirty = _git_text(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
        error_code="SNAPSHOT_GIT_STATUS_FAILED",
    )
    if dirty:
        raise CatalogError("SNAPSHOT_GIT_WORKTREE_DIRTY")
    for producer_commit in producer_commits:
        if not GIT_SHA.fullmatch(producer_commit):
            raise CatalogError("SNAPSHOT_HANDOFF_COMMIT_INVALID")
        try:
            ancestry = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "merge-base",
                    "--is-ancestor",
                    producer_commit,
                    candidate,
                ],
                check=False,
                capture_output=True,
            )
        except OSError as error:
            raise CatalogError("SNAPSHOT_HANDOFF_COMMIT_INVALID") from error
        if ancestry.returncode != 0:
            raise CatalogError(
                f"SNAPSHOT_HANDOFF_COMMIT_NOT_ANCESTOR:{producer_commit}"
            )
    for relative_path, expected_sha256 in committed_files.items():
        committed_sha256 = hashlib.sha256(
            _git_commit_bytes(root, candidate, relative_path)
        ).hexdigest()
        if committed_sha256 != expected_sha256:
            raise CatalogError(
                f"SNAPSHOT_INPUT_GIT_HASH_MISMATCH:{relative_path}"
            )
    return {
        "git_commit": candidate,
        "git_head": head,
        "git_object_type": object_type,
        "git_clean": True,
        "repository_scope": "workspace_root",
    }


def _classification_origin(value: str) -> str | None:
    normalized = value.casefold()
    if "synthetic" in normalized or "fixture" in normalized:
        return "synthetic"
    if "real" in normalized or "restricted" in normalized or "private" in normalized:
        return "real"
    return None


def _existing_legacy_snapshot(
    catalog: Catalog,
    root: Path,
    *,
    plan_revision_id: str,
    plan_sha256: str,
    artifact_ids: set[str],
    data_origin: str,
    random_seed: int,
    git_commit: str | None,
) -> dict[str, Any] | None:
    if git_commit is None:
        return None
    if not GIT_SHA.fullmatch(git_commit):
        raise CatalogError("SNAPSHOT_GIT_COMMIT_INVALID")
    resolved = _git_text(
        root,
        "rev-parse",
        "--verify",
        f"{git_commit}^{{commit}}",
        error_code="SNAPSHOT_GIT_COMMIT_INVALID",
    )
    head = _git_text(
        root,
        "rev-parse",
        "--verify",
        "HEAD^{commit}",
        error_code="SNAPSHOT_GIT_HEAD_INVALID",
    )
    if resolved != git_commit:
        raise CatalogError("SNAPSHOT_GIT_COMMIT_INVALID")
    ancestry = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", git_commit, head],
        check=False,
        capture_output=True,
    )
    if ancestry.returncode != 0:
        raise CatalogError("SNAPSHOT_GIT_COMMIT_NOT_ANCESTOR")
    for row in catalog.rows("analysis_runs"):
        snapshot = json.loads(row["snapshot_json"])
        if (
            snapshot.get("schema_version") != "1.0.0"
            or snapshot.get("plan_revision_id") != plan_revision_id
            or snapshot.get("plan_sha256") != plan_sha256
            or snapshot.get("data_origin") != data_origin
            or snapshot.get("random_seed") != random_seed
            or snapshot.get("software_environment", {}).get("git_commit")
            != git_commit
            or {
                item.get("artifact_id")
                for item in snapshot.get("input_artifacts", [])
            }
            != artifact_ids
        ):
            continue
        classifications = {
            item.get("data_classification", "")
            for item in snapshot["input_artifacts"]
        }
        classified_origins = {
            origin
            for classification in classifications
            if (origin := _classification_origin(classification)) is not None
        }
        if classified_origins != {data_origin}:
            raise CatalogError(
                "SNAPSHOT_DATA_ORIGIN_MISMATCH:" + ",".join(sorted(classifications))
            )
        core = {
            key: value
            for key, value in snapshot.items()
            if key not in {"analysis_run_id", "created_at", "snapshot_sha256"}
        }
        expected_sha256 = hashlib.sha256(canonical_json(core)).hexdigest()
        expected_id = stable_id("analysis", core)
        if (
            snapshot.get("snapshot_sha256") != expected_sha256
            or snapshot.get("analysis_run_id") != expected_id
            or row["snapshot_sha256"] != expected_sha256
        ):
            raise CatalogError("SNAPSHOT_LEGACY_INTEGRITY_INVALID")
        _require_valid(snapshot, root / "schema/analysis_run.schema.json")
        return snapshot
    return None


def freeze_analysis_snapshot(
    catalog: Catalog,
    workspace_root: str | Path,
    *,
    plan_revision_id: str,
    artifact_ids: Iterable[str],
    data_origin: str,
    random_seed: int,
    git_commit: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    if data_origin not in {"synthetic", "real"}:
        raise CatalogError("ANALYSIS_DATA_ORIGIN_INVALID")
    plan_row = catalog.analysis_plan(plan_revision_id)
    selected_ids = set(artifact_ids)
    legacy = _existing_legacy_snapshot(
        catalog,
        root,
        plan_revision_id=plan_revision_id,
        plan_sha256=plan_row["plan_sha256"],
        artifact_ids=selected_ids,
        data_origin=data_origin,
        random_seed=random_seed,
        git_commit=git_commit,
    )
    if legacy is not None:
        return legacy
    artifacts = []
    committed_files = {
        relative: _sha256(root / relative)
        for relative in ("pyproject.toml", "uv.lock", "runtime.lock.json")
    }
    for row in catalog.rows("artifacts"):
        if row["artifact_id"] not in selected_ids:
            continue
        pointer = json.loads(row["pointer_json"])
        if "path" not in pointer:
            raise CatalogError(f"SNAPSHOT_ARTIFACT_NOT_REPRODUCIBLE:{row['artifact_id']}")
        path = root / pointer["path"]
        if not path.is_file() or _sha256(path) != row["sha256"]:
            raise CatalogError(f"SNAPSHOT_ARTIFACT_HASH_MISMATCH:{row['artifact_id']}")
        committed_files[pointer["path"]] = row["sha256"]
        artifacts.append(
            {
                "artifact_id": row["artifact_id"],
                "module_id": row["module_id"],
                "logical_type": row["logical_type"],
                "path": row["uri"],
                "sha256": row["sha256"],
                "schema_version": row["schema_version"],
                "data_classification": row["data_classification"],
            }
        )
    if len(artifacts) != len(selected_ids):
        raise CatalogError("SNAPSHOT_ARTIFACT_NOT_REGISTERED")
    classifications = sorted(
        {artifact["data_classification"] for artifact in artifacts}
    )
    classified_origins = {
        origin
        for classification in classifications
        if (origin := _classification_origin(classification)) is not None
    }
    if classified_origins != {data_origin}:
        raise CatalogError(
            "SNAPSHOT_DATA_ORIGIN_MISMATCH:"
            + ",".join(classifications)
        )
    plan = plan_row["plan"]
    handoffs = [
        {
            key: row[key]
            for key in (
                "handoff_import_id",
                "task_id",
                "manifest_path",
                "manifest_sha256",
                "producer_commit",
            )
        }
        for row in catalog.rows("handoff_imports")
    ]
    modules = [
        {"module_id": row["module_id"], "descriptor_sha256": row["descriptor_sha256"]}
        for row in catalog.rows("modules")
    ]
    gate_state = []
    for row in catalog.rows("modules"):
        descriptor = json.loads(row["descriptor_json"])
        gate_state.extend(
            {
                "gate_id": gate_id,
                "module_id": row["module_id"],
                "status": "blocked",
            }
            for gate_id in descriptor["human_gates"]
        )
    provenance = _git_provenance(
        root,
        git_commit,
        committed_files=committed_files,
        producer_commits=(handoff["producer_commit"] for handoff in handoffs),
    )
    core = {
        "schema_version": "1.1.0",
        "plan_revision_id": plan_revision_id,
        "plan_sha256": plan_row["plan_sha256"],
        "input_artifacts": sorted(artifacts, key=lambda item: item["artifact_id"]),
        "handoffs": sorted(handoffs, key=lambda item: item["task_id"]),
        "module_descriptors": sorted(modules, key=lambda item: item["module_id"]),
        "rules": {
            "inclusion": plan["inclusion_rules"],
            "exclusion": plan["exclusion_rules"],
            "missingness": plan["missingness"],
        },
        "software_environment": {
            **provenance,
            "python": platform.python_version(),
            "platform": f"{platform.system()}-{platform.machine()}",
            "pyproject_sha256": _sha256(root / "pyproject.toml"),
            "uv_lock_sha256": _sha256(root / "uv.lock"),
            "runtime_lock_sha256": _sha256(root / "runtime.lock.json"),
        },
        "random_seed": random_seed,
        "data_origin": data_origin,
        "data_classifications": classifications,
        "gate_state": sorted(
            gate_state,
            key=lambda item: (item["gate_id"], item["module_id"]),
        ),
    }
    snapshot_sha256 = hashlib.sha256(canonical_json(core)).hexdigest()
    analysis_run_id = stable_id("analysis", core)
    existing_rows = {
        row["analysis_run_id"]: row for row in catalog.rows("analysis_runs")
    }
    if analysis_run_id in existing_rows:
        return catalog.analysis_run(analysis_run_id)["snapshot"]
    snapshot = {
        **core,
        "analysis_run_id": analysis_run_id,
        "created_at": _utc_now(),
        "snapshot_sha256": snapshot_sha256,
    }
    _require_valid(snapshot, root / "schema/analysis_run.schema.json")
    return catalog.register_analysis_run(snapshot)
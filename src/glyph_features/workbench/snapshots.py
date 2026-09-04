"""Immutable analysis-plan and input-snapshot services."""

from __future__ import annotations

import hashlib
import json
import platform
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


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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
    artifacts = []
    for row in catalog.rows("artifacts"):
        if row["artifact_id"] not in selected_ids:
            continue
        pointer = json.loads(row["pointer_json"])
        if "path" not in pointer:
            raise CatalogError(f"SNAPSHOT_ARTIFACT_NOT_REPRODUCIBLE:{row['artifact_id']}")
        path = root / pointer["path"]
        if not path.is_file() or _sha256(path) != row["sha256"]:
            raise CatalogError(f"SNAPSHOT_ARTIFACT_HASH_MISMATCH:{row['artifact_id']}")
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
    core = {
        "schema_version": "1.0.0",
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
            "git_commit": git_commit or _git_commit(root),
            "python": platform.python_version(),
            "platform": f"{platform.system()}-{platform.machine()}",
            "pyproject_sha256": _sha256(root / "pyproject.toml"),
            "uv_lock_sha256": _sha256(root / "uv.lock"),
            "runtime_lock_sha256": _sha256(root / "runtime.lock.json"),
        },
        "random_seed": random_seed,
        "data_origin": data_origin,
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
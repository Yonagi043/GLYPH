"""Resolve rights evidence only through a strictly validated TASK-01 handoff."""
from __future__ import annotations

import json
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import normalize_repo_path, sha256_file, validate_record
from glyph_features.asset_system.export import validate_handoff as validate_task01_handoff


@dataclass(frozen=True)
class TrustedRightsSnapshot:
    records: tuple[dict[str, Any], ...]
    handoff_sha256: str
    output_sha256: str
    output_path: str
    formal_gate_passed: bool


def load_trusted_rights_snapshot(
    workspace_root: str | Path,
    task01_handoff_path: str | Path,
    rights_evidence_path: str | Path,
) -> TrustedRightsSnapshot:
    root = Path(workspace_root).resolve()
    handoff_path = Path(task01_handoff_path).resolve()
    rights_path = Path(rights_evidence_path).resolve()
    if not handoff_path.is_relative_to(root) or not rights_path.is_relative_to(root):
        raise ValueError("HAN_RIGHTS_TRUST_PATH_OUTSIDE_WORKSPACE")
    errors = validate_task01_handoff(
        handoff_path,
        root,
        schema_root=root,
        input_root=root,
    )
    manifest = json.loads(handoff_path.read_text(encoding="utf-8"))
    snapshot_commit = _committed_snapshot(root, handoff_path)
    remaining_errors = [
        error
        for error in errors
        if not _downstream_producer_change_is_git_bound(root, snapshot_commit, manifest, error)
    ]
    if remaining_errors:
        raise ValueError("HAN_TASK01_HANDOFF_INVALID: " + "; ".join(sorted(set(remaining_errors))))
    rights_outputs = [
        artifact
        for artifact in manifest.get("outputs", [])
        if isinstance(artifact, dict) and artifact.get("logical_type") == "rights_evidence"
    ]
    if len(rights_outputs) != 1:
        raise ValueError("HAN_TASK01_RIGHTS_OUTPUT_COUNT_INVALID")
    artifact = rights_outputs[0]
    declared_path = normalize_repo_path(str(artifact.get("path")))
    if rights_path != (root / declared_path).resolve():
        raise ValueError("HAN_TASK01_RIGHTS_OUTPUT_PATH_MISMATCH")
    output_sha256 = sha256_file(rights_path)
    if output_sha256 != artifact.get("sha256"):
        raise ValueError("HAN_TASK01_RIGHTS_OUTPUT_HASH_MISMATCH")
    if _git_blob_sha256(root, snapshot_commit, declared_path) != output_sha256:
        raise ValueError("HAN_TASK01_RIGHTS_OUTPUT_GIT_MISMATCH")
    records = tuple(
        json.loads(line)
        for line in rights_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    schema_path = root / "schema/rights_evidence.schema.json"
    schema_errors = [
        f"record={index}: {error}"
        for index, record in enumerate(records, start=1)
        for error in validate_record(record, schema_path)
    ]
    if schema_errors:
        raise ValueError("HAN_TASK01_RIGHTS_RECORD_INVALID: " + "; ".join(schema_errors))
    formal_gate_passed = any(
        gate.get("gate_id") == "formal_rights" and gate.get("status") == "passed"
        for gate in manifest.get("quality_gates", [])
        if isinstance(gate, dict)
    ) and not any(
        gate.get("gate_id") == "GATE-RIGHTS" and gate.get("status") == "blocked"
        for gate in manifest.get("blocked_human_gates", [])
        if isinstance(gate, dict)
    )
    return TrustedRightsSnapshot(
        records=records,
        handoff_sha256=sha256_file(handoff_path),
        output_sha256=output_sha256,
        output_path=declared_path,
        formal_gate_passed=formal_gate_passed,
    )


def _committed_snapshot(root: Path, handoff_path: Path) -> str:
    relative = handoff_path.relative_to(root).as_posix()
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", relative],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or len(commit) != 40:
        raise ValueError("HAN_TASK01_HANDOFF_GIT_SNAPSHOT_MISSING")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if ancestor.returncode != 0 or _git_blob_sha256(root, commit, relative) != sha256_file(handoff_path):
        raise ValueError("HAN_TASK01_HANDOFF_GIT_SNAPSHOT_MISMATCH")
    return commit


def _downstream_producer_change_is_git_bound(
    root: Path,
    snapshot_commit: str,
    manifest: dict[str, Any],
    error: str,
) -> bool:
    prefix = "producer hash mismatch: "
    if not error.startswith(prefix):
        return False
    path = error.removeprefix(prefix)
    declared = next(
        (
            record
            for record in manifest.get("producer_provenance", {}).get("files", [])
            if isinstance(record, dict) and record.get("path") == path
        ),
        None,
    )
    return declared is not None and _git_blob_sha256(root, snapshot_commit, path) == declared.get("sha256")


def _git_blob_sha256(root: Path, commit: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None
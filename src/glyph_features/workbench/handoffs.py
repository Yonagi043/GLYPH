"""Strict, read-only adapters for upstream task handoffs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from glyph_features.asset_system.export import validate_handoff as validate_asset_handoff
from glyph_features.experiment_system.handoff import (
    validate_handoff as validate_experiment_handoff,
)
from glyph_features.han_style_system.handoff import validate_handoff as validate_han_handoff
from glyph_features.vision_system.handoff import validate_handoff as validate_vision_handoff


Validator = Callable[[Path, Path], list[str]]


@dataclass(frozen=True)
class HandoffSpec:
    task_id: str
    module_id: str
    relative_path: str
    supported_versions: frozenset[str]
    validator: Validator


def _asset_validator(manifest: Path, root: Path) -> list[str]:
    return validate_asset_handoff(
        manifest,
        root,
        schema_root=root,
        input_root=root,
    )


def _vision_validator(manifest: Path, root: Path) -> list[str]:
    return validate_vision_handoff(manifest, root, schema_root=root / "schema")


def _experiment_validator(manifest: Path, root: Path) -> list[str]:
    return validate_experiment_handoff(manifest, root)


def _han_validator(manifest: Path, root: Path) -> list[str]:
    return validate_han_handoff(manifest, root, schema_root=root / "schema")


UPSTREAM_HANDOFFS = (
    HandoffSpec(
        "TASK-01",
        "assets",
        "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
        frozenset({"2.0.0"}),
        _asset_validator,
    ),
    HandoffSpec(
        "TASK-02",
        "vision",
        "data/fixtures/visual_measurements/reference_handoff_v2/handoff_manifest.json",
        frozenset({"1.1.0"}),
        _vision_validator,
    ),
    HandoffSpec(
        "TASK-03",
        "experiment",
        "data/releases/task03_cross_cultural_experiment_v1/handoff_manifest.json",
        frozenset({"2.0.0"}),
        _experiment_validator,
    ),
    HandoffSpec(
        "TASK-04",
        "han_style",
        "data/fixtures/han_style_system/reference_handoff_v1/handoff_manifest.json",
        frozenset({"1.1.0"}),
        _han_validator,
    ),
)


def _manifest_commit(manifest: dict[str, Any]) -> str | None:
    for key in ("implementation_commit", "git_commit"):
        value = manifest.get(key)
        if isinstance(value, str):
            return value
    provenance = manifest.get("producer_provenance")
    if isinstance(provenance, dict):
        for key in ("implementation_commit", "git_commit", "base_commit"):
            value = provenance.get(key)
            if isinstance(value, str):
                return value
    return None


def _is_ancestor(root: Path, commit: str | None) -> bool:
    if commit is None:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _blocked_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for field in ("quality_gates", "blocked_human_gates", "blocked_gates"):
        values = manifest.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            status = value.get("status", "blocked")
            gate_id = value.get("gate_id")
            if not isinstance(gate_id, str) or status not in {
                "blocked",
                "fixture_only",
                "needs_review",
            }:
                continue
            gates.append(
                {
                    "gate_id": gate_id,
                    "status": status,
                    "packet_path": value.get("packet_path"),
                    "reasons": value.get("reasons") or [],
                    "evidence": value.get("evidence"),
                }
            )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for gate in gates:
        unique[(gate["gate_id"], gate["status"])] = gate
    return sorted(unique.values(), key=lambda item: (item["gate_id"], item["status"]))


def _task05_entrypoint(manifest: dict[str, Any]) -> dict[str, Any] | None:
    entries = manifest.get("next_task_entrypoints")
    if not isinstance(entries, list):
        return None
    return next(
        (
            entry
            for entry in entries
            if isinstance(entry, dict)
            and (entry.get("task_id") or entry.get("target_system")) == "TASK-05"
        ),
        None,
    )


def _inspect(spec: HandoffSpec, root: Path) -> dict[str, Any]:
    manifest_path = (root / spec.relative_path).resolve()
    if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
        return {
            "task_id": spec.task_id,
            "module_id": spec.module_id,
            "manifest_path": spec.relative_path,
            "validation_status": "missing",
            "compatible": False,
            "errors": ["HANDOFF_MISSING"],
        }
    return _inspect_manifest(spec, manifest_path, root)


def _inspect_manifest(
    spec: HandoffSpec,
    manifest_path: Path,
    root: Path,
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors = spec.validator(manifest_path, root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "task_id": spec.task_id,
            "module_id": spec.module_id,
            "manifest_path": spec.relative_path,
            "validation_status": "invalid",
            "compatible": False,
            "errors": [f"HANDOFF_VALIDATION_ERROR:{type(error).__name__}"],
        }

    schema_version = manifest.get("handoff_schema_version")
    version_supported = schema_version in spec.supported_versions
    producer_commit = _manifest_commit(manifest)
    ancestor = _is_ancestor(root, producer_commit)
    if not version_supported:
        errors.append(f"HANDOFF_VERSION_UNSUPPORTED:{schema_version}")
    if not ancestor:
        errors.append("HANDOFF_PRODUCER_NOT_ANCESTOR")
    readiness = manifest.get("readiness")
    if not isinstance(readiness, dict):
        readiness = {
            "engineering_ready": False,
            "pilot_ready": False,
            "research_validated": False,
        }
    entrypoint = _task05_entrypoint(manifest)
    compatible = not errors
    return {
        "task_id": spec.task_id,
        "module_id": spec.module_id,
        "manifest_path": spec.relative_path,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "handoff_schema_version": schema_version,
        "producer_version": manifest.get("producer_version"),
        "producer_commit": producer_commit,
        "producer_is_ancestor": ancestor,
        "validation_status": "valid" if compatible else "invalid",
        "compatible": compatible,
        "readiness": {
            "engineering_ready": readiness.get("engineering_ready") is True,
            "pilot_ready": readiness.get("pilot_ready") is True,
            "research_validated": readiness.get("research_validated") is True,
        },
        "task05_entrypoint": entrypoint,
        "blocked_gates": _blocked_gates(manifest),
        "contract_versions": manifest.get("contract_versions") or {},
        "errors": errors,
    }


def inspect_handoff_manifest(
    manifest_path: str | Path,
    workspace_root: str | Path,
) -> dict[str, Any]:
    """Validate one supplied manifest with its task's native validator."""

    root = Path(workspace_root).resolve()
    path = Path(manifest_path).resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("HANDOFF_MANIFEST_UNREADABLE") from error
    task_id = value.get("task_id") if isinstance(value, dict) else None
    spec = next((item for item in UPSTREAM_HANDOFFS if item.task_id == task_id), None)
    if spec is None:
        raise ValueError(f"HANDOFF_TASK_UNSUPPORTED:{task_id}")
    return _inspect_manifest(spec, path, root)


def inspect_upstream_handoffs(workspace_root: str | Path) -> list[dict[str, Any]]:
    """Return normalized compatibility results without mutating upstream state."""

    root = Path(workspace_root).resolve()
    return [_inspect(spec, root) for spec in UPSTREAM_HANDOFFS]
"""Build and strictly validate the TASK-02 downstream handoff bundle."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .definitions import canonical_sha256
from .extract import VisionSystemError, _git_blob, _read_task01_snapshot, sha256_file
from .qc import verify_checksums


PRODUCER_STATIC_FILES = (
    ("entrypoint", "pyproject.toml"),
    ("dependency_lock", "runtime.lock.json"),
    ("config", "configs/visual_measurements_v2.yaml"),
    ("schema", "schema/visual_feature_definition.schema.json"),
    ("schema", "schema/visual_measurement.schema.json"),
    ("schema", "schema/visual_measurement_handoff.schema.json"),
    ("schema", "schema/visual_expert_gate.schema.json"),
)
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".yaml", ".csv", ".sha256"}


def build_handoff_bundle(
    *,
    workspace_root: str | Path,
    reference_run_dir: str | Path,
    output_dir: str | Path,
    git_commit: str,
    created_at: str,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    run = Path(reference_run_dir).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"handoff output already exists: {output}")
    output_relative = _relative_path(root, output, must_exist=False)
    if verify_checksums(run):
        raise VisionSystemError("REFERENCE_CHECKSUM_INVALID", "; ".join(verify_checksums(run)))
    run_manifest = _read_json(run / "run_manifest.json")
    quality = _read_json(run / "quality_report.json")
    sensitivity = _read_json(run / "sensitivity_report.json")
    registry = _read_json(run / "feature_registry.json")
    measurements = _read_jsonl(run / "measurements.jsonl")
    failures = _read_jsonl(run / "failures.jsonl")
    if quality.get("readiness") != {"engineering_ready": True, "pilot_ready": False, "research_validated": False}:
        raise VisionSystemError("REFERENCE_READINESS_INVALID", str(quality.get("readiness")))
    if failures or run_manifest.get("failure_count") != 0:
        raise VisionSystemError("REFERENCE_FAILURES_PRESENT", str(len(failures)))
    if any(_contains_score_key(record) for record in measurements):
        raise VisionSystemError("UNCALIBRATED_SCORE_PRESENT", "reference measurements contain a score field")
    provenance = _producer_provenance(root, git_commit)

    task01_lineage = run_manifest.get("task01_lineage")
    if not isinstance(task01_lineage, dict):
        raise VisionSystemError("RUN_LINEAGE_MISSING", "run_manifest.task01_lineage")
    inputs = [
        _lineage_artifact(root, "task01_handoff", task01_lineage.get("handoff"), "metadata_only"),
        _lineage_artifact(root, "task01_asset_candidates", task01_lineage.get("asset_candidates"), "open_fixture"),
        _lineage_artifact(root, "task01_stimuli", task01_lineage.get("stimuli"), "open_fixture"),
        _artifact(
            root,
            "feature_registry_config",
            run_manifest["registry_path"],
            "public_code_or_schema",
            registry["registry_version"],
        ),
        *(
            _artifact(root, "fixture_representation", item["path"], "open_fixture", "1.0.0")
            for item in run_manifest["input_representations"]
        ),
        *(
            _artifact(root, "fixture_supporting_representation", item["path"], "open_fixture", "1.0.0")
            for item in run_manifest.get("supporting_representations", [])
        ),
    ]
    run_relative = _relative_path(root, run)
    output_specs = [
        ("feature_registry", f"{run_relative}/feature_registry.json", "public_code_or_schema", registry["registry_version"]),
        ("long_measurements", f"{run_relative}/measurements.jsonl", "open_fixture", "1.0.0"),
        ("extraction_failures", f"{run_relative}/failures.jsonl", "open_fixture", "1.0.0"),
        ("run_manifest", f"{run_relative}/run_manifest.json", "metadata_only", "1.1.0"),
        ("quality_report", f"{run_relative}/quality_report.json", "metadata_only", "1.0.0"),
        ("quality_report_markdown", f"{run_relative}/quality_report.md", "metadata_only", None),
        ("sensitivity_report", f"{run_relative}/sensitivity_report.json", "metadata_only", "1.0.0"),
        ("representation_comparison", f"{run_relative}/representation_comparison.json", "metadata_only", "1.0.0"),
        ("reference_checksums", f"{run_relative}/checksums.sha256", "metadata_only", None),
        ("cross_script_fixture", "data/fixtures/visual_measurements/cross_script_component_cases.json", "open_fixture", "1.0.0"),
        ("feature_definition_schema", "schema/visual_feature_definition.schema.json", "public_code_or_schema", "1.0.0"),
        ("measurement_schema", "schema/visual_measurement.schema.json", "public_code_or_schema", "1.0.0"),
        ("protocol_documentation", "docs/visual_measurement_protocol_zh.md", "public_code_or_schema", None),
        ("migration_documentation", "docs/visual_measurement_migration_zh.md", "public_code_or_schema", None),
    ]
    outputs = [_artifact(root, *specification) for specification in output_specs]
    material_types = {"feature_registry", "long_measurements", "quality_report", "sensitivity_report", "cross_script_fixture", "representation_comparison"}
    materials = [
        {"logical_type": item["logical_type"], "path": item["path"], "sha256": item["sha256"]}
        for item in outputs
        if item["logical_type"] in material_types
    ]
    gate = _expert_gate(materials)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        gate_path = staging / "GATE-EXPERT.json"
        _write_json(gate_path, gate)
        gate_schema_errors = _schema_errors(gate, root / "schema/visual_expert_gate.schema.json")
        if gate_schema_errors:
            raise VisionSystemError("EXPERT_GATE_SCHEMA_INVALID", "; ".join(gate_schema_errors))
        gate_relative = f"{output_relative}/GATE-EXPERT.json"
        outputs.append(_artifact_from_file("expert_gate_packet", gate_relative, gate_path, "metadata_only", "1.0.0"))
        manifest = _handoff_manifest(
            git_commit=git_commit,
            created_at=created_at,
            provenance=provenance,
            run_manifest=run_manifest,
            quality=quality,
            sensitivity=sensitivity,
            registry=registry,
            measurements=measurements,
            inputs=inputs,
            outputs=outputs,
            gate_relative=gate_relative,
            run_relative=run_relative,
        )
        schema_errors = _schema_errors(manifest, root / "schema/visual_measurement_handoff.schema.json")
        if schema_errors:
            raise VisionSystemError("HANDOFF_SCHEMA_INVALID", "; ".join(schema_errors))
        _write_json(staging / "handoff_manifest.json", manifest)
        checksum_lines = [
            f"{sha256_file(staging / name)}  {name}"
            for name in ("GATE-EXPERT.json", "handoff_manifest.json")
        ]
        (staging / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        staging.rename(output)
        errors = validate_handoff(output / "handoff_manifest.json", root)
        if errors:
            shutil.rmtree(output)
            raise VisionSystemError("HANDOFF_VALIDATION_FAILED", "; ".join(errors[:20]))
        return {
            "git_commit": git_commit,
            "measurement_count": len(measurements),
            "output_count": len(outputs),
            "valid": True,
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def validate_handoff(
    manifest_path: str | Path,
    workspace_root: str | Path,
    *,
    schema_root: str | Path | None = None,
) -> list[str]:
    root = Path(workspace_root).resolve()
    contracts = Path(schema_root).resolve() if schema_root else root / "schema"
    manifest_file = Path(manifest_path).resolve()
    try:
        manifest = _read_json(manifest_file)
    except (OSError, json.JSONDecodeError, VisionSystemError) as error:
        return [f"manifest JSON invalid: {error}"]
    errors = _schema_errors(manifest, contracts / "visual_measurement_handoff.schema.json")
    paths: list[str] = []
    for category in ("input_snapshots", "outputs"):
        for artifact in manifest.get(category, []):
            if not isinstance(artifact, dict) or not {"path", "sha256", "record_count"} <= artifact.keys():
                continue
            path = _resolve_artifact(root, artifact["path"], errors, category)
            if path is None:
                continue
            paths.append(artifact["path"])
            if not path.is_file():
                errors.append(f"missing {category}: {artifact['path']}")
                continue
            if sha256_file(path) != artifact["sha256"]:
                errors.append(f"hash mismatch: {artifact['path']}")
            try:
                actual_count = _record_count(path)
            except (OSError, json.JSONDecodeError, VisionSystemError) as error:
                errors.append(f"record parse failed: {artifact['path']}: {error}")
                continue
            if actual_count != artifact["record_count"]:
                errors.append(f"record count mismatch: {artifact['path']}: {actual_count} != {artifact['record_count']}")
            if artifact.get("logical_type") == "long_measurements":
                _validate_measurements(path, contracts, errors)
            if artifact.get("logical_type") == "expert_gate_packet":
                gate = _read_json(path)
                errors.extend(f"expert gate: {error}" for error in _schema_errors(gate, contracts / "visual_expert_gate.schema.json"))
            if path.suffix.lower() in TEXT_SUFFIXES and _contains_absolute_path(path):
                errors.append(f"absolute filesystem path leak: {artifact['path']}")
    if len(paths) != len(set(paths)):
        errors.append("artifact paths are not unique")
    _validate_provenance(manifest, root, errors)
    _validate_semantics(manifest, root, errors)
    _validate_task01_lineage(manifest, root, errors)
    _validate_bundle_checksums(manifest_file.parent, errors)
    return errors


def _handoff_manifest(
    *,
    git_commit: str,
    created_at: str,
    provenance: dict[str, Any],
    run_manifest: dict[str, Any],
    quality: dict[str, Any],
    sensitivity: dict[str, Any],
    registry: dict[str, Any],
    measurements: list[dict[str, Any]],
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    gate_relative: str,
    run_relative: str,
) -> dict[str, Any]:
    valid_count = sum(record["measurement_status"] == "valid" for record in measurements)
    missing_count = sum(record["measurement_status"] == "missing" for record in measurements)
    stimulus_count = len({record["stimulus_id"] for record in measurements})
    representation_count = len({(record["stimulus_id"], record["representation"]) for record in measurements})
    active_count = sum(item["status"] != "deprecated" for item in registry["features"])
    quality_path = f"{run_relative}/quality_report.json"
    sensitivity_path = f"{run_relative}/sensitivity_report.json"
    measurement_path = f"{run_relative}/measurements.jsonl"
    registry_path = f"{run_relative}/feature_registry.json"
    return {
        "handoff_schema_version": "1.1.0",
        "task_id": "TASK-02",
        "producer_version": "visual_measurements_v2.0.1",
        "git_commit": git_commit,
        "created_at": created_at,
        "contract_compatibility": {
            "previous_handoff": "1.0.0",
            "backward_compatible": False,
            "canonical_long_form": "1.0.0",
            "visual_v1_readable": True,
            "visual_v1_roundtrip": True,
            "notes": "Handoff 1.1.0 requires TASK-01 candidate/stimulus snapshots and cross-artifact lineage validation; 1.0.0 bundles must be regenerated. Visual v1.1 tables remain readable and round-trippable.",
        },
        "producer_provenance": provenance,
        "upstream_commits": {"TASK-01": run_manifest["accepted_task01_commit"]},
        "readiness": quality["readiness"],
        "calibration_status": "not_calibrated",
        "contract_versions": {
            "feature_registry": registry["registry_version"],
            "long_measurement": "1.0.0",
            "handoff": "1.1.0",
            "expert_gate": "1.0.0",
            "visual_v1": "1.1.0-compatible",
        },
        "metrics": {
            "stimulus_count": stimulus_count,
            "representation_count": representation_count,
            "active_feature_count": active_count,
            "registry_definition_count": len(registry["features"]),
            "measurement_count": len(measurements),
            "valid_measurement_count": valid_count,
            "missing_measurement_count": missing_count,
            "failure_count": quality["extraction_failure_count"],
            "sensitivity_warning_count": len(sensitivity["warnings"]),
        },
        "input_snapshots": inputs,
        "outputs": outputs,
        "quality_gates": [
            {"gate_id": "schema_validation", "status": "passed", "evidence": quality_path},
            {"gate_id": "input_and_config_integrity", "status": "passed", "evidence": f"{run_relative}/checksums.sha256"},
            {"gate_id": "computational_stability", "status": "passed", "evidence": quality_path},
            {"gate_id": "representation_sensitivity", "status": quality["representation_sensitivity"]["status"], "evidence": sensitivity_path},
            {"gate_id": "surface_validity", "status": "blocked", "evidence": gate_relative},
            {"gate_id": "construct_validity", "status": "blocked", "evidence": quality_path},
            {"gate_id": "predictive_validity", "status": "blocked", "evidence": quality_path},
        ],
        "known_limitations": [
            "The reference run contains one generated open fixture and cannot support population, aesthetic, or script-level claims.",
            "Threshold sensitivity warnings remain visible and have not been tuned away.",
            "Surface validity awaits two independent domain reviewers.",
            "Construct and predictive validity await TASK-03 real human ratings and held-out calibration.",
            "Eight visual v1-only definitions are retained as deprecated compatibility metadata and are not active v2 outputs.",
        ],
        "joint_analysis_exclusions": [
            "total_score",
            "uncalibrated_dimension_scores",
            "unbound_manual_weights",
            "qi_as_direct_observation",
        ],
        "blocked_human_gates": [{
            "gate_id": "GATE-EXPERT",
            "status": "blocked",
            "packet_path": gate_relative,
            "reasons": ["Two independent visual or type-domain reviewers have not reviewed fixture face validity and cross-script failure modes."],
        }],
        "next_task_entrypoints": [
            {"task_id": "TASK-03", "status": "fixture_only", "path": registry_path, "notes": "Use the frozen dictionary for questionnaire stratification only; do not expose proxy values to participants."},
            {"task_id": "TASK-04", "status": "metadata_only", "path": registry_path, "notes": "Use within-script applicability and low-level stroke/ink APIs; expert conclusions remain blocked."},
            {"task_id": "TASK-05", "status": "fixture_only", "path": measurement_path, "notes": "Integrate only for contract and product dry-runs; enforce joint_analysis_exclusions."},
        ],
    }


def _expert_gate(materials: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "gate_id": "GATE-EXPERT",
        "status": "blocked",
        "decision_required": "Two independent domain reviewers must assess fixture face validity, representation boundaries, and cross-script failure risks.",
        "minimum_reviewers": 2,
        "reviewer_requirements": [
            "At least one reviewer with typography, visual design, or glyph-analysis expertise.",
            "At least one reviewer with Chinese calligraphy or cross-script writing-system expertise.",
            "Reviewers record decisions independently before reconciliation.",
        ],
        "materials": materials,
        "review_questions": [
            "Do the raw measurements have the claimed visual interpretation for the supplied fixtures?",
            "Are A_layout, B_shape, and C_ink boundaries represented without information leakage?",
            "Are small marks, separated strokes, jamo, diacritics, ink breaks, and composite elements retained or explicitly rejected?",
            "Are construct mappings phrased as proxies without aesthetic direction or causal claims?",
            "Which features require within-script restrictions, protocol changes, or retirement?",
        ],
        "decision_template": {"reviewer_decisions": [], "final_status": "pending", "notes": None},
        "allowed_now": ["engineering fixture regression", "schema integration", "expert review preparation"],
        "prohibited_without_approval": ["claim surface validity", "claim construct validity", "publish calligraphy expertise conclusions", "unlock research_validated"],
    }


def _producer_specs(root: Path) -> list[tuple[str, Path]]:
    specs = [(role, root / path) for role, path in PRODUCER_STATIC_FILES]
    specs.extend(("producer_source", path) for path in sorted((root / "src/glyph_features/vision_system").glob("*.py")))
    missing = [str(path) for _, path in specs if not path.is_file()]
    if missing:
        raise VisionSystemError("PRODUCER_FILE_MISSING", ", ".join(missing))
    return specs


def _producer_records(root: Path) -> list[dict[str, str]]:
    return sorted(
        ({"role": role, "path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)} for role, path in _producer_specs(root)),
        key=lambda item: item["path"],
    )


def _producer_provenance(root: Path, git_commit: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{40}", git_commit):
        raise VisionSystemError("GIT_COMMIT_INVALID", git_commit)
    if _git(root, ["cat-file", "-e", f"{git_commit}^{{commit}}"], check=False).returncode != 0:
        raise VisionSystemError("GIT_COMMIT_UNAVAILABLE", git_commit)
    status = _git(root, ["status", "--porcelain=v1", "--untracked-files=all"]).stdout
    if status:
        raise VisionSystemError("WORKTREE_NOT_CLEAN", status.decode("utf-8", errors="replace").strip())
    records = _producer_records(root)
    if not _git_records_match(root, git_commit, records):
        raise VisionSystemError("PRODUCER_SNAPSHOT_MISMATCH", git_commit)
    return {
        "git_commit": git_commit,
        "working_tree_state": "clean",
        "producer_snapshot_matches_commit": True,
        "aggregate_sha256": _aggregate_sha256(records),
        "files": records,
    }


def _validate_provenance(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    provenance = manifest.get("producer_provenance")
    if not isinstance(provenance, dict):
        return
    records = provenance.get("files")
    if not isinstance(records, list):
        return
    try:
        expected = _producer_records(root)
    except VisionSystemError as error:
        errors.append(str(error))
        return
    if {(item.get("role"), item.get("path"), item.get("sha256")) for item in records if isinstance(item, dict)} != {
        (item["role"], item["path"], item["sha256"]) for item in expected
    }:
        errors.append("producer snapshot file set or current hashes do not match")
    declared = [item for item in records if isinstance(item, dict) and {"role", "path", "sha256"} <= item.keys()]
    if len(declared) == len(records) and _aggregate_sha256(declared) != provenance.get("aggregate_sha256"):
        errors.append("producer aggregate hash mismatch")
    git_commit = manifest.get("git_commit")
    if git_commit != provenance.get("git_commit"):
        errors.append("manifest git_commit does not match producer provenance")
    if isinstance(git_commit, str) and re.fullmatch(r"[a-f0-9]{40}", git_commit):
        if _git(root, ["cat-file", "-e", f"{git_commit}^{{commit}}"], check=False).returncode != 0:
            errors.append(f"producer commit unavailable: {git_commit}")
        elif len(declared) == len(records) and not _git_records_match(root, git_commit, declared):
            errors.append("producer files do not match producer commit")


def _validate_semantics(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    required_outputs = {
        "feature_registry", "long_measurements", "run_manifest", "quality_report",
        "sensitivity_report", "reference_checksums", "expert_gate_packet",
    }
    logical_types = {item.get("logical_type") for item in manifest.get("outputs", []) if isinstance(item, dict)}
    missing = required_outputs - logical_types
    if missing:
        errors.append(f"required outputs missing: {sorted(missing)}")
    gates = {item.get("gate_id"): item.get("status") for item in manifest.get("quality_gates", []) if isinstance(item, dict)}
    expected_gates = {
        "schema_validation": "passed",
        "input_and_config_integrity": "passed",
        "computational_stability": "passed",
        "surface_validity": "blocked",
        "construct_validity": "blocked",
        "predictive_validity": "blocked",
    }
    for gate_id, expected in expected_gates.items():
        if gates.get(gate_id) != expected:
            errors.append(f"quality gate mismatch: {gate_id}: {gates.get(gate_id)} != {expected}")
    checksum_artifact = next((item for item in manifest.get("outputs", []) if item.get("logical_type") == "reference_checksums"), None)
    if checksum_artifact:
        checksum_path = _resolve_artifact(root, checksum_artifact["path"], errors, "checksums")
        if checksum_path and checksum_path.is_file():
            errors.extend(f"reference checksum: {error}" for error in verify_checksums(checksum_path.parent))


def _validate_task01_lineage(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    task01_input = _single_artifact(manifest, "input_snapshots", "task01_handoff", errors)
    registry_input = _single_artifact(manifest, "input_snapshots", "feature_registry_config", errors)
    registry_output = _single_artifact(manifest, "outputs", "feature_registry", errors)
    run_output = _single_artifact(manifest, "outputs", "run_manifest", errors)
    measurement_output = _single_artifact(manifest, "outputs", "long_measurements", errors)
    if not task01_input or not registry_input or not registry_output or not run_output or not measurement_output:
        return
    task01_path = _resolve_artifact(root, task01_input.get("path"), errors, "input_snapshots")
    registry_config_path = _resolve_artifact(root, registry_input.get("path"), errors, "input_snapshots")
    registry_snapshot_path = _resolve_artifact(root, registry_output.get("path"), errors, "outputs")
    run_path = _resolve_artifact(root, run_output.get("path"), errors, "outputs")
    measurement_path = _resolve_artifact(root, measurement_output.get("path"), errors, "outputs")
    if not all(
        path is not None and path.is_file()
        for path in (task01_path, registry_config_path, registry_snapshot_path, run_path, measurement_path)
    ):
        return
    try:
        task01, candidates, stimuli, actual_lineage = _read_task01_snapshot(root, task01_path)
        registry_config = _read_json(registry_config_path)
        registry_snapshot = _read_json(registry_snapshot_path)
        run = _read_json(run_path)
        measurements = _read_jsonl(measurement_path)
    except (OSError, KeyError, json.JSONDecodeError, VisionSystemError) as error:
        errors.append(f"TASK-01 lineage parse failed: {error}")
        return

    if registry_snapshot != registry_config:
        errors.append("lineage mismatch: feature_registry output does not equal feature_registry_config input")
    _compare_lineage_field(
        "run_manifest.registry_sha256",
        run.get("registry_sha256"),
        registry_input.get("sha256"),
        errors,
    )
    resolved_config = run.get("resolved_algorithm_config")
    _compare_lineage_field(
        "run_manifest.resolved_algorithm_config",
        resolved_config,
        registry_config.get("algorithm_defaults"),
        errors,
    )
    resolved_sha256 = canonical_sha256(resolved_config) if isinstance(resolved_config, dict) else None
    _compare_lineage_field(
        "run_manifest.algorithm_config_sha256(resolved)",
        run.get("algorithm_config_sha256"),
        resolved_sha256,
        errors,
    )
    _compare_lineage_field(
        "feature_registry.algorithm_config_sha256",
        registry_config.get("algorithm_config_sha256"),
        resolved_sha256,
        errors,
    )

    if task01.get("task_id") != "TASK-01":
        errors.append(f"lineage mismatch: task01_handoff.task_id: {task01.get('task_id')!r} != 'TASK-01'")
    actual_contract_sha256 = actual_lineage["handoff"]["sha256"]
    _compare_lineage_field(
        "run_manifest.task01_handoff_path",
        run.get("task01_handoff_path"),
        actual_lineage["handoff"]["path"],
        errors,
    )
    _compare_lineage_field(
        "run_manifest.task01_handoff_sha256",
        run.get("task01_handoff_sha256"),
        actual_contract_sha256,
        errors,
    )
    upstream_commit = manifest.get("upstream_commits", {}).get("TASK-01")
    _compare_lineage_field("run_manifest.accepted_task01_commit", run.get("accepted_task01_commit"), upstream_commit, errors)
    if isinstance(upstream_commit, str):
        checkpoint_blob = _git_blob(root, upstream_commit, actual_lineage["handoff"]["path"])
        checkpoint_sha256 = hashlib.sha256(checkpoint_blob).hexdigest() if checkpoint_blob is not None else None
        _compare_lineage_field(
            "task01_handoff.accepted_checkpoint_sha256",
            actual_contract_sha256,
            checkpoint_sha256,
            errors,
        )
    run_lineage = run.get("task01_lineage")
    if not isinstance(run_lineage, dict):
        errors.append("lineage mismatch: run_manifest.task01_lineage is missing")
    else:
        _compare_lineage_field(
            "run_manifest.task01_lineage.accepted_commit",
            run_lineage.get("accepted_commit"),
            upstream_commit,
            errors,
        )
        for key in ("handoff", "asset_candidates", "stimuli"):
            declared = run_lineage.get(key)
            if not isinstance(declared, dict):
                errors.append(f"lineage mismatch: run_manifest.task01_lineage.{key} is missing")
                continue
            for field in ("path", "sha256", "record_count", "schema_version"):
                _compare_lineage_field(
                    f"run_manifest.task01_lineage.{key}.{field}",
                    declared.get(field),
                    actual_lineage[key].get(field),
                    errors,
                )

    for key, logical_type in (
        ("handoff", "task01_handoff"),
        ("asset_candidates", "task01_asset_candidates"),
        ("stimuli", "task01_stimuli"),
    ):
        snapshot = _single_artifact(manifest, "input_snapshots", logical_type, errors)
        if snapshot:
            for field in ("path", "sha256", "record_count", "schema_version"):
                _compare_lineage_field(
                    f"input_snapshots[{logical_type}].{field}",
                    snapshot.get(field),
                    actual_lineage[key].get(field),
                    errors,
                )

    candidate_by_id = {
        record.get("asset_id"): record
        for record in candidates
        if isinstance(record, dict) and isinstance(record.get("asset_id"), str)
    }
    stimulus_by_id = {
        record.get("stimulus_id"): record
        for record in stimuli
        if isinstance(record, dict) and isinstance(record.get("stimulus_id"), str)
    }
    task01_representations = {
        item.get("path"): item
        for item in task01.get("outputs", [])
        if isinstance(item, dict) and item.get("logical_type") == "fixture_representation"
    }
    task02_representations = {
        item.get("path"): item
        for item in manifest.get("input_snapshots", [])
        if isinstance(item, dict) and item.get("logical_type") in {
            "fixture_representation", "fixture_supporting_representation"
        }
    }
    measured_sources = run.get("input_representations")
    supporting_sources = run.get("supporting_representations")
    if not isinstance(measured_sources, list):
        errors.append("lineage mismatch: run_manifest.input_representations is not an array")
        measured_sources = []
    if not isinstance(supporting_sources, list):
        errors.append("lineage mismatch: run_manifest.supporting_representations is not an array")
        supporting_sources = []
    for category, sources in (
        ("input_representations", measured_sources),
        ("supporting_representations", supporting_sources),
    ):
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                errors.append(f"lineage mismatch: run_manifest.{category}[{index}] is not an object")
                continue
            _validate_run_source(
                source,
                f"run_manifest.{category}[{index}]",
                root,
                stimulus_by_id,
                candidate_by_id,
                task01_representations,
                task02_representations,
                errors,
            )

    expected_measured = {
        (stimulus["stimulus_id"], representation)
        for stimulus in stimuli
        for representation in ("A_layout", "B_shape", "C_ink")
        if stimulus.get("representations", {}).get(representation) is not None
    }
    actual_measured = {
        (source.get("stimulus_id"), source.get("representation"))
        for source in measured_sources
        if isinstance(source, dict)
    }
    if actual_measured != expected_measured:
        errors.append(
            f"lineage mismatch: run_manifest.input_representations keys: "
            f"{sorted(actual_measured, key=str)} != {sorted(expected_measured, key=str)}"
        )
    expected_supporting = {
        (stimulus["stimulus_id"], "B_shape_mask")
        for stimulus in stimuli
        if stimulus.get("representations", {}).get("B_shape_mask") is not None
    }
    actual_supporting = {
        (source.get("stimulus_id"), source.get("representation"))
        for source in supporting_sources
        if isinstance(source, dict)
    }
    if actual_supporting != expected_supporting:
        errors.append(
            f"lineage mismatch: run_manifest.supporting_representations keys: "
            f"{sorted(actual_supporting, key=str)} != {sorted(expected_supporting, key=str)}"
        )

    for index, record in enumerate(measurements):
        if not isinstance(record, dict):
            continue
        _compare_lineage_field(
            f"measurements[{index}].source_contract_sha256",
            record.get("source_contract_sha256"),
            actual_contract_sha256,
            errors,
        )
        _compare_lineage_field(
            f"measurements[{index}].extraction_run_id",
            record.get("extraction_run_id"),
            run.get("extraction_run_id"),
            errors,
        )
        _compare_lineage_field(
            f"measurements[{index}].algorithm_config_sha256",
            record.get("algorithm_config_sha256"),
            run.get("algorithm_config_sha256"),
            errors,
        )
        stimulus = stimulus_by_id.get(record.get("stimulus_id"))
        reference = (
            stimulus.get("representations", {}).get(record.get("representation"))
            if isinstance(stimulus, dict)
            else None
        )
        if not isinstance(reference, dict):
            errors.append(f"lineage mismatch: measurements[{index}].stimulus_id/representation")
            continue
        _compare_lineage_field(
            f"measurements[{index}].asset_id",
            record.get("asset_id"),
            reference.get("asset_id"),
            errors,
        )
        _compare_lineage_field(
            f"measurements[{index}].input_sha256",
            record.get("input_sha256"),
            reference.get("asset_ref", {}).get("sha256"),
            errors,
        )


def _validate_run_source(
    source: dict[str, Any],
    field_path: str,
    root: Path,
    stimulus_by_id: dict[str, dict[str, Any]],
    candidate_by_id: dict[str, dict[str, Any]],
    task01_representations: dict[str, dict[str, Any]],
    task02_representations: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    stimulus = stimulus_by_id.get(source.get("stimulus_id"))
    if not isinstance(stimulus, dict):
        errors.append(f"lineage mismatch: {field_path}.stimulus_id: {source.get('stimulus_id')!r} is absent")
        return
    reference = stimulus.get("representations", {}).get(source.get("representation"))
    if not isinstance(reference, dict):
        errors.append(f"lineage mismatch: {field_path}.representation: {source.get('representation')!r} is absent")
        return
    candidate = candidate_by_id.get(reference.get("asset_id"))
    if not isinstance(candidate, dict):
        errors.append(f"lineage mismatch: {field_path}.asset_id: upstream candidate is absent")
        return
    expected = {
        "stimulus_id": stimulus["stimulus_id"],
        "stimulus_record_sha256": canonical_sha256(stimulus),
        "stimulus_qc_status": stimulus.get("qc", {}).get("status"),
        "stimulus_rights_tier": stimulus.get("rights_tier"),
        "asset_id": reference.get("asset_id"),
        "asset_candidate_record_sha256": canonical_sha256(candidate),
        "asset_qc_status": candidate.get("automated_qc", {}).get("status"),
        "asset_curation_status": candidate.get("curation_status"),
        "asset_rights_tier": candidate.get("rights_tier"),
        "representation": source.get("representation"),
        "asset_role": reference.get("asset_role"),
        "transform_config_sha256": reference.get("transform_config_sha256"),
        "path": reference.get("asset_ref", {}).get("path"),
        "sha256": reference.get("asset_ref", {}).get("sha256"),
    }
    for field, expected_value in expected.items():
        _compare_lineage_field(f"{field_path}.{field}", source.get(field), expected_value, errors)
    _compare_lineage_field(
        f"task01.asset_candidates[{candidate.get('asset_id')}].asset_role",
        candidate.get("asset_role"),
        reference.get("asset_role"),
        errors,
    )
    _compare_lineage_field(
        f"task01.asset_candidates[{candidate.get('asset_id')}].asset_ref",
        candidate.get("asset_ref"),
        reference.get("asset_ref"),
        errors,
    )
    _compare_lineage_field(
        f"task01.asset_candidates[{candidate.get('asset_id')}].transform.config_sha256",
        candidate.get("transform", {}).get("config_sha256"),
        reference.get("transform_config_sha256"),
        errors,
    )
    parent = candidate_by_id.get(stimulus.get("original_asset_id"))
    if not isinstance(parent, dict):
        errors.append(f"lineage mismatch: task01.stimuli[{stimulus['stimulus_id']}].original_asset_id is absent")
    else:
        _compare_lineage_field(
            f"task01.asset_candidates[{candidate.get('asset_id')}].parent_asset_id",
            candidate.get("parent_asset_id"),
            parent.get("asset_id"),
            errors,
        )
        _compare_lineage_field(
            f"task01.asset_candidates[{candidate.get('asset_id')}].transform.parent_sha256",
            candidate.get("transform", {}).get("parent_sha256"),
            parent.get("asset_ref", {}).get("sha256"),
            errors,
        )
        for field in ("source_id", "work_id"):
            _compare_lineage_field(
                f"task01.asset_candidates[{candidate.get('asset_id')}].{field}",
                candidate.get(field),
                parent.get(field),
                errors,
            )
    if candidate.get("target_geometry") is None:
        errors.append(f"lineage mismatch: task01.asset_candidates[{candidate.get('asset_id')}].target_geometry is missing")
    for field, expected_value in (
        ("automated_qc.status", "passed"),
        ("curation_status", "passed"),
        ("rights_tier", "open"),
        ("review.decision", "passed"),
    ):
        value: Any = candidate
        for part in field.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        _compare_lineage_field(f"task01.asset_candidates[{candidate.get('asset_id')}].{field}", value, expected_value, errors)
    _compare_lineage_field(
        f"task01.stimuli[{stimulus['stimulus_id']}].qc.status",
        stimulus.get("qc", {}).get("status"),
        "passed",
        errors,
    )
    _compare_lineage_field(
        f"task01.stimuli[{stimulus['stimulus_id']}].rights_tier",
        stimulus.get("rights_tier"),
        "open",
        errors,
    )
    relative = reference.get("asset_ref", {}).get("path")
    if isinstance(relative, str):
        actual_path = _resolve_artifact(root, relative, errors, field_path)
        if actual_path is not None and actual_path.is_file():
            _compare_lineage_field(f"{field_path}.sha256(actual)", sha256_file(actual_path), expected["sha256"], errors)
        for label, artifacts in (
            ("TASK-01 outputs", task01_representations),
            ("TASK-02 input_snapshots", task02_representations),
        ):
            artifact = artifacts.get(relative)
            if not isinstance(artifact, dict):
                errors.append(f"lineage mismatch: {field_path}.path is absent from {label}: {relative}")
            else:
                _compare_lineage_field(f"{label}[{relative}].sha256", artifact.get("sha256"), expected["sha256"], errors)


def _single_artifact(
    manifest: dict[str, Any],
    category: str,
    logical_type: str,
    errors: list[str],
) -> dict[str, Any] | None:
    matches = [
        item
        for item in manifest.get(category, [])
        if isinstance(item, dict) and item.get("logical_type") == logical_type
    ]
    if len(matches) != 1:
        errors.append(f"lineage mismatch: {category} requires exactly one {logical_type}, found {len(matches)}")
        return None
    return matches[0]


def _compare_lineage_field(path: str, actual: Any, expected: Any, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"lineage mismatch: {path}: {actual!r} != {expected!r}")


def _validate_measurements(path: Path, schema_root: Path, errors: list[str]) -> None:
    schema = _read_json(schema_root / "visual_measurement.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    try:
        records = _read_jsonl(path)
    except (json.JSONDecodeError, VisionSystemError) as error:
        errors.append(f"measurement JSON invalid: {error}")
        return
    for index, record in enumerate(records, start=1):
        for error in validator.iter_errors(record):
            errors.append(f"measurement line {index}: {error.message}")
        if _contains_score_key(record):
            errors.append(f"measurement line {index}: uncalibrated score key is forbidden")


def _artifact(root: Path, logical_type: str, relative: str, rights: str, schema_version: str | None) -> dict[str, Any]:
    path = _resolve_required(root, relative)
    return _artifact_from_file(logical_type, relative, path, rights, schema_version)


def _lineage_artifact(
    root: Path,
    logical_type: str,
    declared: Any,
    rights: str,
) -> dict[str, Any]:
    if not isinstance(declared, dict):
        raise VisionSystemError("RUN_LINEAGE_MISSING", f"task01_lineage.{logical_type}")
    artifact = _artifact(root, logical_type, declared["path"], rights, declared.get("schema_version"))
    for field in ("sha256", "record_count"):
        if artifact[field] != declared.get(field):
            raise VisionSystemError("RUN_LINEAGE_MISMATCH", f"{logical_type}.{field}")
    return artifact


def _artifact_from_file(logical_type: str, relative: str, path: Path, rights: str, schema_version: str | None) -> dict[str, Any]:
    return {
        "logical_type": logical_type,
        "path": relative,
        "sha256": sha256_file(path),
        "record_count": _record_count(path),
        "rights_or_privacy_level": rights,
        "schema_version": schema_version,
    }


def _relative_path(root: Path, path: Path, *, must_exist: bool = True) -> str:
    resolved = path.resolve() if must_exist else path.parent.resolve() / path.name
    if not resolved.is_relative_to(root):
        raise VisionSystemError("UNSAFE_PATH", str(path))
    return resolved.relative_to(root).as_posix()


def _resolve_required(root: Path, relative: str) -> Path:
    errors: list[str] = []
    path = _resolve_artifact(root, relative, errors, "artifact")
    if path is None or not path.is_file():
        raise VisionSystemError("ARTIFACT_MISSING", f"{relative}: {'; '.join(errors)}")
    return path


def _resolve_artifact(root: Path, relative: str, errors: list[str], category: str) -> Path | None:
    if not isinstance(relative, str):
        errors.append(f"unsafe {category} path: {relative!r}")
        return None
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts) or "\\" in relative or re.match(r"^[A-Za-z]:", relative):
        errors.append(f"unsafe {category} path: {relative}")
        return None
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root):
        errors.append(f"unsafe {category} path: {relative}")
        return None
    return path


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return len(_read_jsonl(path))
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    if path.name == "checksums.sha256":
        return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())
    return 1


def _schema_errors(payload: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _read_json(schema_path)
    return [
        f"{'/'.join(map(str, error.path))}: {error.message}"
        for error in sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload), key=lambda item: list(item.path))
    ]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line, parse_constant=_reject_nonfinite) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _reject_nonfinite(value: str) -> None:
    raise VisionSystemError("NONFINITE_JSON", value)


def _aggregate_sha256(records: list[dict[str, str]]) -> str:
    normalized = sorted(records, key=lambda item: item["path"])
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_records_match(root: Path, git_commit: str, records: list[dict[str, str]]) -> bool:
    for record in records:
        result = _git(root, ["show", f"{git_commit}:{record['path']}"], check=False)
        if result.returncode != 0 or hashlib.sha256(result.stdout).hexdigest() != record["sha256"]:
            return False
    return True


def _git(root: Path, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *arguments], cwd=root, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _contains_score_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any("score" in str(key).lower() or _contains_score_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_score_key(item) for item in value)
    return False


def _contains_absolute_path(path: Path) -> bool:
    payload = path.read_bytes()
    unix = re.compile(rb"(?<![:/A-Za-z0-9])/(?:Applications|Users|etc|home|opt|private|tmp|usr|var|Volumes)/[^\s\"']+")
    windows = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+")
    return bool(unix.search(payload) or windows.search(payload))


def _validate_bundle_checksums(bundle: Path, errors: list[str]) -> None:
    checksum_path = bundle / "checksums.sha256"
    if not checksum_path.is_file():
        errors.append("handoff bundle checksums.sha256 is missing")
        return
    expected_names = {"GATE-EXPERT.json", "handoff_manifest.json"}
    seen: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        try:
            expected, name = line.split("  ", 1)
        except ValueError:
            errors.append(f"invalid handoff checksum line: {line}")
            continue
        seen.add(name)
        path = bundle / name
        if name not in expected_names or not path.is_file() or sha256_file(path) != expected:
            errors.append(f"handoff checksum mismatch: {name}")
    if seen != expected_names:
        errors.append(f"handoff checksum file set mismatch: {sorted(seen)}")
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

from .extract import VisionSystemError, sha256_file
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

    input_paths = [
        ("task01_handoff", run_manifest["task01_handoff_path"], "metadata_only", run_manifest["task01_handoff_schema_version"]),
        ("feature_registry_config", run_manifest["registry_path"], "public_code_or_schema", registry["registry_version"]),
        *(
            ("fixture_representation", item["path"], "open_fixture", "1.0.0")
            for item in run_manifest["input_representations"]
        ),
    ]
    inputs = [_artifact(root, logical_type, path, rights, schema_version) for logical_type, path, rights, schema_version in input_paths]
    run_relative = _relative_path(root, run)
    output_specs = [
        ("feature_registry", f"{run_relative}/feature_registry.json", "public_code_or_schema", "2.0.0"),
        ("long_measurements", f"{run_relative}/measurements.jsonl", "open_fixture", "1.0.0"),
        ("extraction_failures", f"{run_relative}/failures.jsonl", "open_fixture", "1.0.0"),
        ("run_manifest", f"{run_relative}/run_manifest.json", "metadata_only", "1.0.0"),
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
        "handoff_schema_version": "1.0.0",
        "task_id": "TASK-02",
        "producer_version": "visual_measurements_v2.0.0",
        "git_commit": git_commit,
        "created_at": created_at,
        "contract_compatibility": {
            "canonical_long_form": "1.0.0",
            "visual_v1_readable": True,
            "visual_v1_roundtrip": True,
            "notes": "The v1.1 wide table remains readable and round-trippable; ordinary v2 A/B/C records cannot fabricate v1 sequence metadata.",
        },
        "producer_provenance": provenance,
        "upstream_commits": {"TASK-01": run_manifest["accepted_task01_commit"]},
        "readiness": quality["readiness"],
        "calibration_status": "not_calibrated",
        "contract_versions": {
            "feature_registry": registry["registry_version"],
            "long_measurement": "1.0.0",
            "handoff": "1.0.0",
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
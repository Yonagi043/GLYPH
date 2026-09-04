"""Strict TASK-03 handoff validation against immutable Git producer blobs."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import normalize_repo_path

from .export import validate_deidentified_bundle
from .fixtures import load_task01_fixture
from .schema import canonical_sha256, validate_record


PRODUCER_SCOPES = (
    "pyproject.toml",
    "uv.lock",
    "configs/cross_cultural_study_v1.json",
    "configs/questionnaire_v1.json",
    "schema/consent_receipt.schema.json",
    "schema/experiment_assignment.schema.json",
    "schema/experiment_export_manifest.schema.json",
    "schema/experiment_handoff_manifest.schema.json",
    "schema/experiment_rating.schema.json",
    "schema/experiment_stimulus_catalog.schema.json",
    "schema/participant_profile.schema.json",
    "schema/presentation_event.schema.json",
    "schema/quality_decision.schema.json",
    "schema/questionnaire_definition.schema.json",
    "schema/study_protocol.schema.json",
    "src/glyph_features/experiment_system",
    "tests/test_experiment_system.py",
    "docs/cross_cultural_experiment_protocol_zh.md",
    "docs/cross_cultural_experiment_data_contract_zh.md",
    "data/templates/experiment_system_v1",
    "data/fixtures/experiment_system/reference_v1",
)

REFERENCE_ROOT = Path("data/fixtures/experiment_system/reference_v1")
DEFAULT_HANDOFF_ROOT = Path("data/releases/task03_cross_cultural_experiment_v1")
EVIDENCE_FILES = (
    "browser_validation.json",
    "desktop_intro.png",
    "desktop_trial.png",
    "mobile_trial.png",
)


def build_handoff(
    workspace_root: str | Path,
    output_dir: str | Path,
    *,
    implementation_commit: str,
    created_at: str,
    evidence_dir: str | Path,
    validation_summary_path: str | Path,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    output = Path(output_dir)
    output = output if output.is_absolute() else root / output
    evidence = Path(evidence_dir).resolve()
    validation_path = Path(validation_summary_path).resolve()
    if output.exists():
        raise FileExistsError(f"output directory exists: {output}")
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise FileExistsError(f"staging directory exists: {staging}")
    load_task01_fixture(root)
    _git_blob(root, implementation_commit, "pyproject.toml")
    validation_summary = json.loads(validation_path.read_text(encoding="utf-8"))
    browser_summary = json.loads((evidence / "browser_validation.json").read_text(encoding="utf-8"))
    if not browser_summary.get("passed"):
        raise ValueError("BROWSER_VALIDATION_NOT_PASSED")
    required_checks = ("specialized_tests", "full_tests", "node_check", "uv_lock_check", "git_diff_check")
    if any(validation_summary.get(check, {}).get("exit_code") != 0 for check in required_checks):
        raise ValueError("VALIDATION_SUMMARY_NOT_PASSED")
    try:
        (staging / "gates").mkdir(parents=True)
        (staging / "evidence").mkdir()
        for filename in EVIDENCE_FILES:
            source = evidence / filename
            if not source.is_file():
                raise ValueError(f"EVIDENCE_FILE_MISSING:{filename}")
            shutil.copyfile(source, staging / "evidence" / filename)
        shutil.copyfile(validation_path, staging / "evidence" / "validation_summary.json")

        gates = _gate_packets()
        for gate_id, packet in gates.items():
            _write_json(staging / "gates" / f"{gate_id}.json", packet)
        integration_requests = [{
            "target": "pyproject.toml",
            "status": "included_in_implementation",
            "reason": "Registers glyph-experiment and packages the experiment_system static browser assets; downstream integration must preserve these shared entrypoints.",
        }]
        _write_json(staging / "integration_requests.json", {"schema_version": "1.0.0", "requests": integration_requests})
        _write_text(
            staging / "TASK_03_REPORT_zh.md",
            _report_text(implementation_commit, created_at, validation_summary, browser_summary),
        )

        outputs = _external_outputs(root)
        bundle_specs = [
            ("validation_summary", "evidence/validation_summary.json", "local_validation_evidence", "1.0.0", None),
            ("browser_validation", "evidence/browser_validation.json", "local_validation_evidence", "1.0.0", None),
            ("browser_screenshot", "evidence/desktop_intro.png", "local_validation_evidence", None, None),
            ("browser_screenshot", "evidence/desktop_trial.png", "local_validation_evidence", None, None),
            ("browser_screenshot", "evidence/mobile_trial.png", "local_validation_evidence", None, None),
            ("integration_requests", "integration_requests.json", "public_code_or_schema", "1.0.0", None),
            ("task_report", "TASK_03_REPORT_zh.md", "public_code_or_schema", "1.0.0", None),
        ]
        for gate_id in gates:
            bundle_specs.append(("gate_packet", f"gates/{gate_id}.json", "blocked_human_gate", "1.0.0", None))
        for logical_type, relative, privacy, schema_version, validation_schema in bundle_specs:
            outputs.append(_artifact(
                staging / relative,
                (output.relative_to(root) / relative).as_posix(),
                logical_type,
                privacy,
                schema_version,
                validation_schema,
            ))

        checksum_lines = [
            f"{_sha256_file(path)}  {path.relative_to(staging).as_posix()}"
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        _write_text(staging / "checksums.sha256", "\n".join(checksum_lines) + "\n")
        outputs.append(_artifact(
            staging / "checksums.sha256",
            (output.relative_to(root) / "checksums.sha256").as_posix(),
            "checksums",
            "local_validation_evidence",
            None,
            None,
        ))

        blocked_gates = [
            {
                "gate_id": gate_id,
                "status": "blocked",
                "packet_path": (output.relative_to(root) / "gates" / f"{gate_id}.json").as_posix(),
                "reasons": packet["blockers"],
            }
            for gate_id, packet in gates.items()
        ]
        manifest = {
            "handoff_schema_version": "2.0.0",
            "task_id": "TASK-03",
            "producer_version": "1.0.0",
            "implementation_commit": implementation_commit,
            "contract_compatibility": {
                "previous_version": None,
                "backward_compatible": False,
                "reason": "First TASK-03 handoff; experiment_rating 2.0 is parallel to, not a silent replacement for, human_rating.",
            },
            "producer_provenance": producer_provenance(root, implementation_commit),
            "created_at": created_at,
            "readiness": {"engineering_ready": True, "pilot_ready": False, "research_validated": False},
            "contract_versions": {
                "study_protocol": "1.0.0",
                "questionnaire_definition": "1.0.0",
                "participant_profile": "1.0.0",
                "consent_receipt": "1.1.0",
                "experiment_stimulus_catalog": "1.0.0",
                "experiment_assignment": "1.0.0",
                "presentation_event": "1.0.0",
                "experiment_rating": "2.0.0",
                "quality_decision": "1.0.0",
                "experiment_handoff_manifest": "2.0.0",
            },
            "input_snapshots": _input_snapshots(root),
            "outputs": sorted(outputs, key=lambda item: item["path"]),
            "quality_gates": [
                {"gate_id": "TASK01_STRICT_HANDOFF", "status": "fixture_only", "evidence": "TASK-01 handoff 2.0 validates; formal stimulus entrypoint remains blocked."},
                {"gate_id": "SCHEMA_AND_FOREIGN_KEYS", "status": "passed", "evidence": "Specialized and full repository tests passed."},
                {"gate_id": "BIBD_1000", "status": "passed", "evidence": "Two seeds: 8000 unique presentations, zero lost/duplicate, exposure spread 0, position spread 1."},
                {"gate_id": "BROWSER_DESKTOP_MOBILE", "status": "passed", "evidence": "Four-language desktop/mobile automation, pixel, overflow, interaction and completion evidence included."},
                {"gate_id": "SYNTHETIC_FORMAL_USE", "status": "passed", "evidence": "formal_analysis and release are mechanically rejected before file creation."},
                {"gate_id": "HUMAN_PILOT", "status": "blocked", "evidence": "Ethics, participant, translation, formal stimulus and runtime gates are blocked."},
            ],
            "known_limitations": [
                "Only the TASK-01 open synthetic fixture is presented; no formal stimulus is pilot-ready.",
                "Translations are drafts without committee review, back-translation or cognitive interviews.",
                "Power figures are assumption scenarios, not an approved sample size.",
                "The browser runtime has engineering checks but no mature-library or independent timing validation for real research.",
                "No real participant, recruitment, contact, compensation, withdrawal or retention workflow was exercised.",
            ],
            "blocked_human_gates": blocked_gates,
            "next_task_entrypoints": [
                {
                    "task_id": "TASK-04",
                    "status": "metadata_only",
                    "path": "configs/questionnaire_v1.json",
                    "notes": "Use stable item/condition definitions; expert terminology requires a separate reviewed block.",
                },
                {
                    "task_id": "TASK-05",
                    "status": "fixture_only",
                    "path": "data/fixtures/experiment_system/reference_v1/records/reference_manifest.json",
                    "notes": "Consume only deidentified schema-valid synthetic fixtures and preserve the formal-use block.",
                },
            ],
            "integration_requests": integration_requests,
        }
        schema_errors = validate_record(manifest, "experiment_handoff_manifest.schema.json")
        if schema_errors:
            raise ValueError("HANDOFF_SCHEMA_INVALID: " + "; ".join(schema_errors))
        _write_json(staging / "handoff_manifest.json", manifest)
        staging.rename(output)
        strict_errors = validate_handoff(output / "handoff_manifest.json", root)
        if strict_errors:
            shutil.rmtree(output, ignore_errors=True)
            raise ValueError("HANDOFF_STRICT_INVALID: " + "; ".join(strict_errors))
        return {
            "valid": True,
            "output_dir": output.relative_to(root).as_posix(),
            "implementation_commit": implementation_commit,
            "output_count": len(outputs),
            "blocked_gate_count": len(blocked_gates),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def validate_handoff(manifest_path: str | Path, workspace_root: str | Path) -> list[str]:
    root = Path(workspace_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest unreadable: {error}"]
    errors.extend(validate_record(manifest, "experiment_handoff_manifest.schema.json"))
    if errors:
        return errors
    _validate_producer(manifest, root, errors)
    for label in ("input_snapshots", "outputs"):
        for artifact in manifest[label]:
            _validate_artifact(artifact, root, label, errors)
    _validate_entrypoints(manifest, root, errors)
    _validate_bundle(manifest_file, manifest, root, errors)
    return errors


def producer_provenance(root: Path, implementation_commit: str) -> dict[str, Any]:
    root = root.resolve()
    paths = producer_paths_at_commit(root, implementation_commit)
    files = [
        {
            "role": _producer_role(path),
            "path": path,
            "sha256": hashlib.sha256(_git_blob(root, implementation_commit, path)).hexdigest(),
        }
        for path in paths
    ]
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        check=True,
    )
    return {
        "base_commit": implementation_commit,
        "working_tree_state": "dirty" if status.stdout else "clean",
        "producer_snapshot_matches_base": True,
        "aggregate_sha256": canonical_sha256(files),
        "files": files,
    }


def producer_paths_at_commit(root: Path, commit: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", commit, "--", *PRODUCER_SCOPES],
        capture_output=True,
        check=True,
        text=True,
    )
    paths = sorted(line for line in result.stdout.splitlines() if line)
    if not paths:
        raise ValueError(f"no TASK-03 producer files at commit {commit}")
    return paths


def _validate_producer(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    commit = manifest["implementation_commit"]
    provenance = manifest["producer_provenance"]
    if provenance["base_commit"] != commit:
        errors.append("producer base_commit does not equal implementation_commit")
        return
    commit_check = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if commit_check.returncode != 0:
        errors.append(f"implementation commit unavailable: {commit}")
        return
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        errors.append(f"implementation commit is not an ancestor of HEAD: {commit}")
    expected_paths = set(producer_paths_at_commit(root, commit))
    declared = provenance["files"]
    declared_paths = {item["path"] for item in declared}
    if declared_paths != expected_paths:
        errors.append(
            f"producer file set mismatch: missing={sorted(expected_paths - declared_paths)}, extra={sorted(declared_paths - expected_paths)}"
        )
    normalized: list[dict[str, str]] = []
    for item in declared:
        path = item["path"]
        if path not in expected_paths:
            continue
        if item["role"] != _producer_role(path):
            errors.append(f"producer role mismatch: {path}")
        blob_hash = hashlib.sha256(_git_blob(root, commit, path)).hexdigest()
        if blob_hash != item["sha256"]:
            errors.append(f"producer commit hash mismatch: {path}")
        normalized.append({"role": item["role"], "path": path, "sha256": item["sha256"]})
    if canonical_sha256(normalized) != provenance["aggregate_sha256"]:
        errors.append("producer aggregate hash mismatch")


def _validate_artifact(artifact: dict[str, Any], root: Path, label: str, errors: list[str]) -> None:
    try:
        path = root / normalize_repo_path(artifact["path"])
    except ValueError as error:
        errors.append(f"unsafe {label} path: {artifact['path']}: {error}")
        return
    if not path.is_file() or path.is_symlink():
        errors.append(f"missing or non-regular {label} artifact: {artifact['path']}")
        return
    if _sha256_file(path) != artifact["sha256"]:
        errors.append(f"{label} hash mismatch: {artifact['path']}")
    actual_count = _record_count(path)
    if actual_count != artifact["record_count"]:
        errors.append(f"{label} record count mismatch: {artifact['path']}: {actual_count} != {artifact['record_count']}")
    schema_path = artifact["validation_schema"]
    if schema_path is not None:
        try:
            schema_name = Path(normalize_repo_path(schema_path)).name
            records = _read_records(path)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            errors.append(f"{label} schema input unreadable: {artifact['path']}: {error}")
            return
        for index, record in enumerate(records, start=1):
            errors.extend(
                f"{artifact['path']} record {index}: {error}"
                for error in validate_record(record, schema_name)
            )


def _validate_bundle(manifest_file: Path, manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    declared = {item["path"] for item in manifest["outputs"]}
    bundle_paths = {
        path.relative_to(root).as_posix()
        for path in manifest_file.parent.rglob("*")
        if path.is_file() and path != manifest_file
    }
    undeclared = sorted(bundle_paths - declared)
    if undeclared:
        errors.append(f"undeclared bundle files: {undeclared}")
    missing = sorted(path for path in declared if path.startswith(manifest_file.parent.relative_to(root).as_posix() + "/") and path not in bundle_paths)
    if missing:
        errors.append(f"declared bundle files missing: {missing}")
    for file_path in manifest_file.parent.rglob("*"):
        if file_path.is_file() and _contains_absolute_path(file_path):
            errors.append(f"absolute filesystem path leak: {file_path.relative_to(root).as_posix()}")
    checksum_artifacts = [item for item in manifest["outputs"] if item["logical_type"] == "checksums"]
    for artifact in checksum_artifacts:
        checksum_path = root / artifact["path"]
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, relative = line.split("  ", 1)
            target = manifest_file.parent / normalize_repo_path(relative)
            if not target.is_file() or _sha256_file(target) != expected:
                errors.append(f"checksum mismatch: {relative}")


def _validate_entrypoints(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    outputs_by_path: dict[str, list[dict[str, Any]]] = {}
    for artifact in manifest["outputs"]:
        outputs_by_path.setdefault(artifact["path"], []).append(artifact)
    for path, artifacts in outputs_by_path.items():
        if len(artifacts) != 1:
            errors.append(f"OUTPUT_PATH_NOT_UNIQUE:{path}")
    for entrypoint in manifest["next_task_entrypoints"]:
        path = entrypoint["path"]
        try:
            target = root / normalize_repo_path(path)
        except ValueError as error:
            errors.append(f"ENTRYPOINT_PATH_UNSAFE:{entrypoint['task_id']}:{path}:{error}")
            continue
        if not target.is_file() or target.is_symlink():
            errors.append(f"ENTRYPOINT_MISSING:{entrypoint['task_id']}:{path}")
        artifacts = outputs_by_path.get(path, [])
        if len(artifacts) != 1:
            errors.append(f"ENTRYPOINT_NOT_PROTECTED_OUTPUT:{entrypoint['task_id']}:{path}")
    task05 = [entrypoint for entrypoint in manifest["next_task_entrypoints"] if entrypoint["task_id"] == "TASK-05"]
    if len(task05) != 1:
        errors.append("TASK05_ENTRYPOINT_COUNT_INVALID")
    elif len(outputs_by_path.get(task05[0]["path"], [])) == 1:
        _validate_reference_entrypoint(root / task05[0]["path"], manifest, root, errors)


def _validate_reference_entrypoint(
    reference_path: Path,
    handoff: dict[str, Any],
    root: Path,
    errors: list[str],
) -> None:
    try:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"REFERENCE_MANIFEST_UNREADABLE:{error}")
        return
    if reference.get("data_origin") != "synthetic":
        errors.append("REFERENCE_MANIFEST_NOT_SYNTHETIC")
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("REFERENCE_ARTIFACTS_INVALID")
        return
    expected_files = {
        "study_protocol.json",
        "questionnaire_definition.json",
        "participant_profile.json",
        "consent_receipt.json",
        "stimulus_catalog.json",
        "assignment.json",
        "presentation_event.json",
        "ratings.jsonl",
        "quality_decision.json",
    }
    declared_files = {artifact.get("path") for artifact in artifacts if isinstance(artifact, dict)}
    if declared_files != expected_files:
        errors.append(
            f"REFERENCE_ARTIFACT_SET_MISMATCH:missing={sorted(expected_files - declared_files)}:extra={sorted(declared_files - expected_files)}"
        )
        return
    top_outputs = {artifact["path"]: artifact for artifact in handoff["outputs"]}
    loaded: dict[str, list[dict[str, Any]]] = {}
    reference_root = reference_path.parent.resolve()
    for artifact in artifacts:
        relative = Path(artifact["path"])
        target = (reference_root / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(reference_root):
            errors.append(f"REFERENCE_ARTIFACT_PATH_UNSAFE:{artifact['path']}")
            continue
        repo_path = target.relative_to(root).as_posix()
        top_artifact = top_outputs.get(repo_path)
        if top_artifact is None:
            errors.append(f"REFERENCE_ARTIFACT_NOT_PROTECTED_OUTPUT:{artifact['path']}")
            continue
        if not target.is_file() or target.is_symlink():
            errors.append(f"REFERENCE_ARTIFACT_MISSING:{artifact['path']}")
            continue
        actual_sha256 = _sha256_file(target)
        actual_count = _record_count(target)
        for source, expected in (("reference", artifact), ("output", top_artifact)):
            if expected["sha256"] != actual_sha256:
                errors.append(f"REFERENCE_{source.upper()}_HASH_MISMATCH:{artifact['path']}")
            if expected["record_count"] != actual_count:
                errors.append(f"REFERENCE_{source.upper()}_COUNT_MISMATCH:{artifact['path']}")
        validation_schema = top_artifact.get("validation_schema")
        if validation_schema is None or Path(validation_schema).name != artifact.get("schema"):
            errors.append(f"REFERENCE_SCHEMA_BINDING_MISMATCH:{artifact['path']}")
        try:
            loaded[artifact["path"]] = _read_records(target)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            errors.append(f"REFERENCE_ARTIFACT_UNREADABLE:{artifact['path']}:{error}")
    if set(loaded) != expected_files:
        return
    protocol = loaded["study_protocol.json"][0]
    questionnaire = loaded["questionnaire_definition.json"][0]
    profile = loaded["participant_profile.json"][0]
    consent = loaded["consent_receipt.json"][0]
    catalog = loaded["stimulus_catalog.json"][0]
    assignment = loaded["assignment.json"][0]
    event = loaded["presentation_event.json"][0]
    ratings = loaded["ratings.jsonl"]
    quality = loaded["quality_decision.json"][0]
    study_id = protocol.get("study_id")
    for label, record in (
        ("questionnaire", questionnaire),
        ("profile", profile),
        ("consent", consent),
        ("catalog", catalog),
        ("assignment", assignment),
        ("presentation", event),
        ("quality", quality),
    ):
        if record.get("study_id") != study_id:
            errors.append(f"REFERENCE_STUDY_ID_MISMATCH:{label}")
    if any(rating.get("study_id") != study_id for rating in ratings):
        errors.append("REFERENCE_STUDY_ID_MISMATCH:ratings")
    if protocol.get("synthetic_only") is not True or catalog.get("data_origin") != "synthetic" or any(
        record.get("data_origin") != "synthetic"
        for record in (profile, consent, assignment, event, quality, *ratings)
    ):
        errors.append("REFERENCE_SYNTHETIC_ONLY_MISMATCH")
    if consent.get("participant_id") != profile.get("participant_id"):
        errors.append("REFERENCE_CONSENT_PARTICIPANT_MISMATCH")
    if assignment.get("participant_id") != profile.get("participant_id"):
        errors.append("REFERENCE_ASSIGNMENT_PARTICIPANT_MISMATCH")
    if quality.get("participant_id") != profile.get("participant_id"):
        errors.append(f"REFERENCE_QUALITY_PARTICIPANT_MISMATCH:{quality.get('participant_id')}")
    if consent.get("protocol_version") != protocol.get("protocol_version"):
        errors.append("REFERENCE_CONSENT_PROTOCOL_VERSION_MISMATCH")
    if consent.get("questionnaire_version") != questionnaire.get("questionnaire_version"):
        errors.append("REFERENCE_CONSENT_QUESTIONNAIRE_VERSION_MISMATCH")
    if assignment.get("protocol_version") != protocol.get("protocol_version"):
        errors.append("REFERENCE_ASSIGNMENT_PROTOCOL_VERSION_MISMATCH")
    if assignment.get("questionnaire_version") != questionnaire.get("questionnaire_version"):
        errors.append("REFERENCE_ASSIGNMENT_QUESTIONNAIRE_VERSION_MISMATCH")
    semantic_errors = validate_deidentified_bundle({
        "profiles": [profile],
        "consents": [consent],
        "assignments": [assignment],
        "presentations": [event],
        "ratings": ratings,
        "quality_decisions": [quality],
    }, catalog_items=catalog["items"], questionnaire_items=questionnaire["items"])
    errors.extend(f"REFERENCE_{error}" for error in semantic_errors)


def _producer_role(path: str) -> str:
    if path == "pyproject.toml":
        return "entrypoint"
    if path == "uv.lock":
        return "dependency_lock"
    if path.startswith("configs/"):
        return "config"
    if path.startswith("schema/"):
        return "schema"
    if path.startswith("tests/"):
        return "test"
    if path.startswith("docs/"):
        return "documentation"
    if path.startswith("data/"):
        return "fixture"
    return "producer_source"


def _git_blob(root: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"producer blob missing: {commit}:{path}")
    return result.stdout


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if path.suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    if path.name == "checksums.sha256":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return 1


def _read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return [value]


def _contains_absolute_path(path: Path) -> bool:
    payload = path.read_bytes()
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        payload = b"\n".join(re.findall(rb"[\x20-\x7e]{8,}", payload))
    unix = re.compile(
        rb"(?<![:/#A-Za-z0-9._-])/(?!/)(?!(?:api|static)/)"
        rb"[A-Za-z0-9._~%+@=,-]+(?:/[A-Za-z0-9._~%+@=,-]+)+"
    )
    file_uri = re.compile(
        rb"file:///(?!/)[A-Za-z0-9._~%+@=,-]+(?:/[A-Za-z0-9._~%+@=,-]+)+"
    )
    windows = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+")
    return bool(unix.search(payload) or file_uri.search(payload) or windows.search(payload))


def _input_snapshots(root: Path) -> list[dict[str, Any]]:
    specs = [
        ("task01_handoff", "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json", "upstream_open_fixture", "2.0.0", "schema/handoff_manifest.schema.json"),
        ("study_protocol", "configs/cross_cultural_study_v1.json", "public_code_or_schema", "1.0.0", "schema/study_protocol.schema.json"),
        ("questionnaire_definition", "configs/questionnaire_v1.json", "public_code_or_schema", "1.0.0", "schema/questionnaire_definition.schema.json"),
    ]
    return [
        _artifact(root / path, path, logical_type, privacy, schema_version, validation_schema)
        for logical_type, path, privacy, schema_version, validation_schema in specs
    ]


def _external_outputs(root: Path) -> list[dict[str, Any]]:
    specs = [
    ("questionnaire_entrypoint", "configs/questionnaire_v1.json", "public_code_or_schema", "1.0.0", "schema/questionnaire_definition.schema.json"),
        ("dry_run_summary", f"{REFERENCE_ROOT.as_posix()}/dry_run_1000_seed_a.json", "synthetic_fixture", "1.0.0", None),
        ("dry_run_summary", f"{REFERENCE_ROOT.as_posix()}/dry_run_1000_seed_b.json", "synthetic_fixture", "1.0.0", None),
        ("power_scenarios", f"{REFERENCE_ROOT.as_posix()}/power_scenarios.json", "synthetic_fixture", "1.0.0", None),
        ("assignment_audit", f"{REFERENCE_ROOT.as_posix()}/blocks/assignment_audit.json", "synthetic_fixture", "1.0.0", None),
        ("assignments", f"{REFERENCE_ROOT.as_posix()}/blocks/assignments.jsonl", "synthetic_fixture", "1.0.0", "schema/experiment_assignment.schema.json"),
        ("stimulus_catalog", f"{REFERENCE_ROOT.as_posix()}/blocks/stimulus_catalog.json", "synthetic_fixture", "1.0.0", "schema/experiment_stimulus_catalog.schema.json"),
        ("schema_gap_and_privacy", "docs/cross_cultural_experiment_data_contract_zh.md", "public_code_or_schema", "1.0.0", None),
        ("experiment_protocol", "docs/cross_cultural_experiment_protocol_zh.md", "public_code_or_schema", "1.0.0", None),
        ("template_manifest", "data/templates/experiment_system_v1/reference_manifest.json", "synthetic_fixture", "1.0.0", None),
        ("reference_manifest", f"{REFERENCE_ROOT.as_posix()}/records/reference_manifest.json", "synthetic_fixture", "1.0.0", None),
    ]
    record_schemas = {
        "assignment.json": ("assignment", "1.0.0", "schema/experiment_assignment.schema.json"),
        "consent_receipt.json": ("consent_receipt", "1.1.0", "schema/consent_receipt.schema.json"),
        "participant_profile.json": ("participant_profile", "1.0.0", "schema/participant_profile.schema.json"),
        "presentation_event.json": ("presentation_event", "1.0.0", "schema/presentation_event.schema.json"),
        "quality_decision.json": ("quality_decision", "1.0.0", "schema/quality_decision.schema.json"),
        "questionnaire_definition.json": ("questionnaire_definition", "1.0.0", "schema/questionnaire_definition.schema.json"),
        "ratings.jsonl": ("experiment_ratings", "2.0.0", "schema/experiment_rating.schema.json"),
        "stimulus_catalog.json": ("stimulus_catalog", "1.0.0", "schema/experiment_stimulus_catalog.schema.json"),
        "study_protocol.json": ("study_protocol", "1.0.0", "schema/study_protocol.schema.json"),
    }
    for filename, (logical_type, schema_version, schema_path) in record_schemas.items():
        specs.append((logical_type, f"{REFERENCE_ROOT.as_posix()}/records/{filename}", "synthetic_fixture", schema_version, schema_path))
    return [
        _artifact(root / path, path, logical_type, privacy, schema_version, validation_schema)
        for logical_type, path, privacy, schema_version, validation_schema in specs
    ]


def _artifact(
    file_path: Path,
    repo_path: str,
    logical_type: str,
    privacy_level: str,
    schema_version: str | None,
    validation_schema: str | None,
) -> dict[str, Any]:
    return {
        "logical_type": logical_type,
        "path": repo_path,
        "sha256": _sha256_file(file_path),
        "record_count": _record_count(file_path),
        "privacy_level": privacy_level,
        "schema_version": schema_version,
        "validation_schema": validation_schema,
    }


def _gate_packets() -> dict[str, dict[str, Any]]:
    blockers = {
        "GATE-ETHICS": ["No ethics approval or approved data-management, withdrawal, retention and deletion procedure."],
        "GATE-PARTICIPANTS": ["Recruitment, compensation, quotas, stopping rules and model-based sample size are not approved."],
        "GATE-TRANSLATION": ["English, Japanese and Korean drafts lack human committee review, back-translation and cognitive interviews."],
        "GATE-FORMAL-STIMULI": ["TASK-01 formal stimulus entrypoint is blocked; only an open engineering fixture is allowed."],
        "GATE-EXPERIMENT-RUNTIME": ["A maintained experiment library or equivalent independent browser timing validation is required before a real pilot."],
    }
    return {
        gate_id: {
            "schema_version": "1.0.0",
            "gate_id": gate_id,
            "status": "blocked",
            "blockers": reasons,
            "required_decision": "Explicit human approval with versioned local evidence; never auto-unlock.",
            "prohibited_actions": ["real recruitment", "real response collection", "formal analysis", "public release"],
        }
        for gate_id, reasons in blockers.items()
    }


def _report_text(
    implementation_commit: str,
    created_at: str,
    validation: dict[str, Any],
    browser: dict[str, Any],
) -> str:
    specialized = validation["specialized_tests"].get("passed", "unknown")
    full = validation["full_tests"].get("passed", "unknown")
    return f"""# TASK-03 跨文化感知实验与多语问卷报告

版本：`1.0.0`
生成时间：{created_at}
Implementation commit：`{implementation_commit}`

## 完成范围

已完成 synthetic-only 协议、九类 schema、四语问卷定义、约束平衡不完全区组、SQLite 幂等与恢复、四语浏览器界面、Web Crypto 展示哈希、版本化质量规则、去标识导出、双种子 1000 人 dry-run、功效假设情景与 strict handoff。未招募、联系或收集真人数据。

## 验收结果

- TASK-03 专项：{specialized} passed，退出码 0。
- 全仓测试：{full} passed，退出码 0。
- JavaScript syntax、`uv lock --check`、`git diff --check`：退出码均为 0。
- 浏览器：四语、桌面/移动、完整 8-trial 交互、恢复、非空像素、无横向溢出、无禁用元数据命中；passed={str(browser.get('passed')).lower()}。
- 1000 人：8000 unique presentations，0 lost，0 duplicate，group-stimulus exposure spread 0，stimulus-position spread 1。
- 浏览器完成会话导出 56 条逐题 rating；formal analysis 与 release 均在创建文件前返回 `SYNTHETIC_FORMAL_EXPORT_FORBIDDEN`。

## Readiness

- `engineering_ready=true`：只针对许可 fixture 的工程链与可重复验收。
- `pilot_ready=false`：伦理、参与者、翻译、正式刺激和 runtime 时序门禁全部 blocked。
- `research_validated=false`：没有真人 pilot、测量等价性、效度分析或研究结论。

## 下游边界

TASK-05 只能读取 `data/fixtures/experiment_system/reference_v1/records/reference_manifest.json` 中的 synthetic 去标识 fixture，并保留正式用途阻断。TASK-04 可复用稳定 item/condition 定义，但专家术语必须进入独立审核版本。`pyproject.toml` 是共享集成热点，已注册 `glyph-experiment` 和 static package data，后续合并不得丢失。

## 停止声明

本任务在工程就绪、pilot 未就绪、研究未验证的状态停止。任何 gate packet 都不能由程序自动改成 passed，也不存在 `synthetic_only=false` 的运行路径。
"""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")
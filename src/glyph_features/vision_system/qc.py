"""Integrity, stability, applicability, and sensitivity checks for visual runs."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .definitions import load_registry
from .extract import VisionSystemError, _load_grayscale, _safe_repo_file, measure_array, sha256_file


def qc_run(run_dir: str | Path, workspace_root: str | Path, schema_root: str | Path) -> dict[str, Any]:
    run = Path(run_dir).resolve()
    root = Path(workspace_root).resolve()
    schema_directory = Path(schema_root).resolve()
    output_names = {
        "quality_report.json",
        "quality_report.md",
        "sensitivity_report.json",
        "representation_comparison.json",
        "checksums.sha256",
    }
    existing = sorted(name for name in output_names if (run / name).exists())
    if existing:
        raise FileExistsError(f"QC output already exists: {', '.join(existing)}")

    manifest = _read_json(run / "run_manifest.json")
    registry_path = _safe_repo_file(root, manifest["registry_path"])
    registry = load_registry(registry_path, schema_directory)
    records = _read_jsonl(run / "measurements.jsonl")
    failures = _read_jsonl(run / "failures.jsonl")
    errors: list[dict[str, str]] = []
    manifest_config_sha256 = manifest.get("algorithm_config_sha256")
    if manifest_config_sha256 != registry.payload["algorithm_config_sha256"]:
        errors.append({
            "code": "ALGORITHM_CONFIG_HASH_MISMATCH",
            "detail": "run manifest does not match the validated registry",
        })
    record_config_mismatches = sum(
        record.get("algorithm_config_sha256") != manifest_config_sha256
        for record in records
    )
    if record_config_mismatches:
        errors.append({
            "code": "MEASUREMENT_CONFIG_HASH_MISMATCH",
            "detail": f"{record_config_mismatches} measurement records do not match the run manifest",
        })
    measurement_schema = json.loads((schema_directory / "visual_measurement.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(measurement_schema, format_checker=FormatChecker())
    for index, record in enumerate(records, start=1):
        for error in validator.iter_errors(record):
            errors.append({"code": "MEASUREMENT_SCHEMA_INVALID", "detail": f"record {index}: {error.message}"})
    measurement_ids = [record.get("measurement_id") for record in records]
    if len(measurement_ids) != len(set(measurement_ids)):
        errors.append({"code": "MEASUREMENT_ID_DUPLICATE", "detail": "measurement_id values are not unique"})
    if len(records) != manifest.get("measurement_count"):
        errors.append({"code": "MEASUREMENT_COUNT_MISMATCH", "detail": f"{len(records)} != {manifest.get('measurement_count')}"})
    if len(failures) != manifest.get("failure_count"):
        errors.append({"code": "FAILURE_COUNT_MISMATCH", "detail": f"{len(failures)} != {manifest.get('failure_count')}"})
    if sha256_file(registry_path) != manifest.get("registry_sha256"):
        errors.append({"code": "REGISTRY_HASH_MISMATCH", "detail": manifest["registry_path"]})

    by_key = {
        (record["stimulus_id"], record["asset_id"], record["representation"], record["feature_code"]): record
        for record in records
    }
    stability_mismatches: list[dict[str, Any]] = []
    sensitivity_warnings: list[dict[str, Any]] = []
    quality = registry.payload["quality"]
    for source in manifest["input_representations"]:
        image_path = _safe_repo_file(root, source["path"])
        if sha256_file(image_path) != source["sha256"]:
            errors.append({"code": "INPUT_HASH_MISMATCH", "detail": source["path"]})
            continue
        image = _load_grayscale(image_path)
        repeated = measure_array(image, source["representation"], registry)
        for definition in registry.active_definitions:
            code = definition["feature_code"]
            key = (source["stimulus_id"], source["asset_id"], source["representation"], code)
            record = by_key.get(key)
            if record is None:
                stability_mismatches.append({"key": list(key), "reason": "record_missing"})
                continue
            metric = repeated[code]
            expected_status = "valid" if metric.value is not None else "missing"
            if expected_status != record["measurement_status"] or not _numbers_equal(metric.value, record["value"]):
                stability_mismatches.append(
                    {
                        "key": list(key),
                        "reason": "repeat_mismatch",
                        "stored": record["value"],
                        "repeated": metric.value,
                    }
                )
        for threshold in quality["threshold_sensitivity"]:
            changed = measure_array(image, source["representation"], registry, binary_threshold=int(threshold))
            for definition in registry.active_definitions:
                code = definition["feature_code"]
                key = (source["stimulus_id"], source["asset_id"], source["representation"], code)
                baseline = by_key.get(key)
                current = changed[code]
                if baseline is None or baseline["value"] is None or current.value is None:
                    continue
                absolute_delta = abs(float(current.value) - float(baseline["value"]))
                relative_delta = absolute_delta / abs(float(baseline["value"])) if baseline["value"] else 0.0
                if absolute_delta > quality["absolute_warning"] or relative_delta > quality["relative_warning"]:
                    sensitivity_warnings.append(
                        {
                            "stimulus_id": source["stimulus_id"],
                            "asset_id": source["asset_id"],
                            "representation": source["representation"],
                            "feature_code": code,
                            "threshold": threshold,
                            "baseline": baseline["value"],
                            "changed": current.value,
                            "absolute_delta": absolute_delta,
                            "relative_delta": relative_delta,
                        }
                    )

    if stability_mismatches:
        errors.append({"code": "COMPUTATIONAL_STABILITY_FAILED", "detail": f"{len(stability_mismatches)} repeat mismatches"})
    engineering_ready = not errors and not failures
    report = {
        "schema_version": "1.0.0",
        "extraction_run_id": manifest["extraction_run_id"],
        "input_integrity": {"status": "passed" if not any(error["code"].endswith("HASH_MISMATCH") for error in errors) else "failed"},
        "schema_validation": {"status": "passed" if not any("SCHEMA" in error["code"] for error in errors) else "failed"},
        "computational_stability": {
            "status": "passed" if not stability_mismatches else "failed",
            "repeat_mismatch_count": len(stability_mismatches),
        },
        "representation_sensitivity": {
            "status": "passed" if not sensitivity_warnings else "needs_review",
            "warning_count": len(sensitivity_warnings),
            "policy": "Sensitivity warnings are retained and do not rewrite frozen measurements.",
        },
        "surface_validity": {
            "status": "blocked",
            "gate_id": "GATE-EXPERT",
            "reason": "Two independent visual or type-domain reviewers have not reviewed the fixture package.",
        },
        "construct_validity": {
            "status": "blocked",
            "reason": "No expert construct review or real human rating association has been performed.",
        },
        "predictive_validity": {
            "status": "blocked",
            "reason": "No TASK-03 real participant ratings or held-out calibration run exist.",
        },
        "readiness": {
            "engineering_ready": engineering_ready,
            "pilot_ready": False,
            "research_validated": False,
        },
        "measurement_count": len(records),
        "missing_measurement_count": sum(record["measurement_status"] == "missing" for record in records),
        "extraction_failure_count": len(failures),
        "qc_error_count": len(errors),
        "errors": errors,
    }
    sensitivity = {
        "schema_version": "1.0.0",
        "extraction_run_id": manifest["extraction_run_id"],
        "thresholds": quality["threshold_sensitivity"],
        "absolute_warning": quality["absolute_warning"],
        "relative_warning": quality["relative_warning"],
        "warnings": sensitivity_warnings,
        "stability_mismatches": stability_mismatches,
    }
    comparison = representation_comparison(records)
    markdown = _quality_markdown(report)
    _publish_qc(run, report, sensitivity, comparison, markdown)
    return report


def representation_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, float | int]] = {}
    for record in records:
        if record["measurement_status"] != "valid":
            continue
        grouped.setdefault(record["feature_code"], {})[record["representation"]] = record["value"]
    comparisons = []
    for feature_code, values in sorted(grouped.items()):
        if len(values) < 2:
            continue
        numeric = [float(value) for value in values.values()]
        comparisons.append(
            {
                "feature_code": feature_code,
                "values": dict(sorted(values.items())),
                "range": max(numeric) - min(numeric),
                "interpretation": "representation_sensitive_description_only",
            }
        )
    return {
        "schema_version": "1.0.0",
        "comparisons": comparisons,
        "warning": "A/B/C preserve different information and are not interchangeable cleaned images.",
    }


def verify_checksums(run_dir: str | Path) -> list[str]:
    run = Path(run_dir)
    checksum_file = run / "checksums.sha256"
    errors: list[str] = []
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split("  ", 1)
        path = run / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
        elif sha256_file(path) != expected:
            errors.append(f"hash mismatch: {relative}")
    return errors


def _numbers_equal(left: float | int | None, right: float | int | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line, parse_constant=_reject_nonfinite) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)


def _reject_nonfinite(value: str) -> None:
    raise VisionSystemError("NONFINITE_JSON", f"{value} in QC input")


def _quality_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# TASK-02 visual measurement quality report",
            "",
            f"- Run: `{report['extraction_run_id']}`",
            f"- Measurements: {report['measurement_count']}",
            f"- Explicit missing measurements: {report['missing_measurement_count']}",
            f"- Extraction failures: {report['extraction_failure_count']}",
            f"- Computational stability: `{report['computational_stability']['status']}`",
            f"- Representation/threshold sensitivity: `{report['representation_sensitivity']['status']}`",
            f"- Surface validity: `{report['surface_validity']['status']}` (`GATE-EXPERT`)",
            f"- Construct validity: `{report['construct_validity']['status']}`",
            f"- Predictive validity: `{report['predictive_validity']['status']}`",
            "",
            "Measurements are visual facts under a frozen protocol. They are not aesthetic scores.",
            "",
        ]
    )


def _publish_qc(
    run: Path,
    report: dict[str, Any],
    sensitivity: dict[str, Any],
    comparison: dict[str, Any],
    markdown: str,
) -> None:
    staging = Path(tempfile.mkdtemp(prefix=".qc.staging-", dir=run.parent))
    try:
        _write_json(staging / "quality_report.json", report)
        _write_json(staging / "sensitivity_report.json", sensitivity)
        _write_json(staging / "representation_comparison.json", comparison)
        (staging / "quality_report.md").write_text(markdown, encoding="utf-8")
        checksum_paths = sorted(path for path in run.iterdir() if path.is_file()) + sorted(path for path in staging.iterdir() if path.is_file())
        lines = []
        for path in checksum_paths:
            lines.append(f"{sha256_file(path)}  {path.name}")
        (staging / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for path in sorted(staging.iterdir()):
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(path, run / path.name)
        staging.rmdir()
    except Exception:
        for path in staging.glob("*"):
            path.unlink(missing_ok=True)
        staging.rmdir()
        raise


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
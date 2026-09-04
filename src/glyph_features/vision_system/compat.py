"""Strict semantic adapters for the frozen visual-features v1.1 wide table."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from glyph_features.measure import FEATURES
from glyph_features.validate import validate_visual_csv

from .definitions import canonical_sha256, load_registry
from .extract import VisionSystemError, _safe_repo_file, sha256_file


V1_BASE_FIELDS = [
    "feature_record_id", "stimulus_id", "extraction_run_id", "feature_definition_version",
    "representation", "normalization_profile", "dimensions", "applicability",
    "measurement_status", "missing_reason", "algorithm_config_sha256",
    "feature_numerators_json", "feature_denominators_json", "feature_units_json",
    "feature_applicability_json", "missing_reasons_json",
]
V1_FIELDS = [*V1_BASE_FIELDS, *FEATURES]
V1_JSON_FIELDS = {
    "feature_numerators_json", "feature_denominators_json", "feature_units_json",
    "feature_applicability_json", "missing_reasons_json",
}


def v1_wide_to_long(
    *,
    csv_path: str | Path,
    run_manifest_path: str | Path,
    registry_path: str | Path,
    schema_root: str | Path,
    workspace_root: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    source = Path(csv_path)
    manifest_file = Path(run_manifest_path)
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"adapter output exists: {output}")
    root = Path(workspace_root).resolve()
    registry = load_registry(registry_path, schema_root)
    definitions = {item["feature_code"]: item for item in registry.definitions}
    missing_definitions = sorted(set(FEATURES) - definitions.keys())
    if missing_definitions:
        raise VisionSystemError("V1_DEFINITION_MISSING", ",".join(missing_definitions))
    legacy_errors = validate_visual_csv(source, Path(schema_root) / "visual_features.schema.json")
    if legacy_errors:
        raise VisionSystemError("V1_SCHEMA_INVALID", "; ".join(legacy_errors[:20]))
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != V1_FIELDS:
            extra = sorted(set(reader.fieldnames or []) - set(V1_FIELDS))
            missing = sorted(set(V1_FIELDS) - set(reader.fieldnames or []))
            raise VisionSystemError("V1_COLUMNS_INVALID", f"missing={missing}, extra={extra}")
        rows = list(reader)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    if manifest.get("protocol_version") != "visual_features_v1.2.0":
        raise VisionSystemError("V1_PROTOCOL_INCOMPATIBLE", str(manifest.get("protocol_version")))
    render_by_stimulus = {item["stimulus_id"]: item for item in manifest["results"]}
    software_hash = canonical_sha256(manifest.get("software", {}))
    source_contract_sha256 = sha256_file(manifest_file)
    validator = _validator(Path(schema_root))
    records: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        render = render_by_stimulus.get(row["stimulus_id"])
        if render is None or render.get("status") != "passed":
            raise VisionSystemError("V1_RENDER_RECORD_MISSING", row["stimulus_id"])
        if row["representation"] == "raster_binary":
            input_path, input_sha256 = render["mask_path"], render["mask_sha256"]
        elif row["representation"] == "raster_grayscale":
            input_path, input_sha256 = render["gray_path"], render["gray_sha256"]
        else:
            raise VisionSystemError("V1_REPRESENTATION_UNKNOWN", row["representation"])
        physical_input = _safe_repo_file(root, input_path)
        if sha256_file(physical_input) != input_sha256:
            raise VisionSystemError("V1_INPUT_HASH_MISMATCH", input_path)
        numerators = _json_object(row["feature_numerators_json"])
        denominators = _json_object(row["feature_denominators_json"])
        units = _json_object(row["feature_units_json"])
        feature_applicability = _json_object(row["feature_applicability_json"])
        missing_reasons = _json_object(row["missing_reasons_json"])
        context = {
            "source_row_index": row_index,
            "source_feature_record_id": row["feature_record_id"],
            "dimensions": [item for item in row["dimensions"].split("|") if item],
            "applicability": row["applicability"],
            "measurement_status": row["measurement_status"],
            "missing_reason": row["missing_reason"] or None,
            "feature_numerators": numerators,
            "feature_denominators": denominators,
            "feature_units": units,
            "feature_applicability": feature_applicability,
            "missing_reasons": missing_reasons,
        }
        asset_id = f"asset_v1_{input_sha256[:24]}"
        feature_record_id = _stable_id("feature", row["feature_record_id"], asset_id)
        for code in FEATURES:
            definition = definitions[code]
            value = _number(row[code], units.get(code))
            numerator = _finite_or_none(numerators.get(code))
            denominator = _finite_or_none(denominators.get(code))
            mappings = sorted({item["construct_code"] for item in definition["construct_mappings"]})
            dimensions = sorted({definition["dimensions"]["primary"], *definition["dimensions"]["secondary"]})
            record = {
                "schema_version": "1.0.0",
                "measurement_id": _stable_id("measurement", feature_record_id, code),
                "feature_record_id": feature_record_id,
                "stimulus_id": row["stimulus_id"],
                "asset_id": asset_id,
                "extraction_run_id": row["extraction_run_id"],
                "representation": row["representation"],
                "normalization_profile": row["normalization_profile"],
                "feature_code": code,
                "feature_definition_version": row["feature_definition_version"],
                "value": value,
                "numerator": numerator,
                "denominator": denominator,
                "unit": units[code],
                "applicability": feature_applicability[code],
                "measurement_status": "valid" if value is not None else "missing",
                "missing_code": None if value is not None else missing_reasons.get(code, "LEGACY_V1_MISSING_UNSPECIFIED"),
                "algorithm_config_sha256": row["algorithm_config_sha256"],
                "input_sha256": input_sha256,
                "computed_at": manifest["created_at"],
                "software_environment_sha256": software_hash,
                "source_contract_sha256": source_contract_sha256,
                "dimensions": dimensions,
                "constructs": mappings,
                "fixture_only": True,
                "legacy_v1_context": context,
            }
            errors = list(validator.iter_errors(record))
            if errors:
                raise VisionSystemError("V1_LONG_SCHEMA_INVALID", errors[0].message)
            records.append(record)
    records.sort(key=lambda item: (item["legacy_v1_context"]["source_row_index"], FEATURES.index(item["feature_code"])))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return {"wide_record_count": len(rows), "long_record_count": len(records)}


def long_to_v1_wide(input_path: str | Path, output_path: str | Path, schema_root: str | Path) -> dict[str, int]:
    source = Path(input_path)
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"adapter output exists: {output}")
    validator = _validator(Path(schema_root))
    records = [json.loads(line, parse_constant=_reject_nonfinite) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        errors = list(validator.iter_errors(record))
        if errors:
            raise VisionSystemError("LONG_SCHEMA_INVALID", errors[0].message)
        context = record.get("legacy_v1_context")
        if context is None:
            raise VisionSystemError("V1_CONTEXT_MISSING", record["measurement_id"])
        grouped.setdefault(context["source_row_index"], []).append(record)
    rows: list[dict[str, str]] = []
    for row_index in sorted(grouped):
        group = grouped[row_index]
        context = group[0]["legacy_v1_context"]
        if any(record["legacy_v1_context"] != context for record in group):
            raise VisionSystemError("V1_CONTEXT_CONFLICT", str(row_index))
        by_code = {record["feature_code"]: record for record in group}
        if set(by_code) != set(FEATURES) or len(group) != len(FEATURES):
            raise VisionSystemError("V1_FEATURE_SET_INVALID", str(row_index))
        first = group[0]
        row = {
            "feature_record_id": context["source_feature_record_id"],
            "stimulus_id": first["stimulus_id"],
            "extraction_run_id": first["extraction_run_id"],
            "feature_definition_version": first["feature_definition_version"],
            "representation": first["representation"],
            "normalization_profile": first["normalization_profile"],
            "dimensions": "|".join(context["dimensions"]),
            "applicability": context["applicability"],
            "measurement_status": context["measurement_status"],
            "missing_reason": context["missing_reason"] or "",
            "algorithm_config_sha256": first["algorithm_config_sha256"],
            "feature_numerators_json": json.dumps(context["feature_numerators"], ensure_ascii=False, sort_keys=True),
            "feature_denominators_json": json.dumps(context["feature_denominators"], ensure_ascii=False, sort_keys=True),
            "feature_units_json": json.dumps(context["feature_units"], ensure_ascii=False, sort_keys=True),
            "feature_applicability_json": json.dumps(context["feature_applicability"], ensure_ascii=False, sort_keys=True),
            "missing_reasons_json": json.dumps(context["missing_reasons"], ensure_ascii=False, sort_keys=True),
        }
        row.update({code: _csv_number(by_code[code]["value"]) for code in FEATURES})
        rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=V1_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    legacy_errors = validate_visual_csv(output, Path(schema_root) / "visual_features.schema.json")
    if legacy_errors:
        output.unlink()
        raise VisionSystemError("V1_ROUNDTRIP_SCHEMA_INVALID", "; ".join(legacy_errors[:20]))
    return {"long_record_count": len(records), "wide_record_count": len(rows)}


def _validator(schema_root: Path) -> Draft202012Validator:
    schema = json.loads((schema_root / "visual_measurement.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _json_object(value: str) -> dict[str, Any]:
    parsed = json.loads(value, parse_constant=_reject_nonfinite)
    if not isinstance(parsed, dict):
        raise VisionSystemError("V1_JSON_OBJECT_REQUIRED", value[:40])
    return parsed


def _number(value: str, unit: str | None) -> float | int | None:
    if value == "":
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise VisionSystemError("V1_NONFINITE", value)
    return int(parsed) if unit == "count" and parsed.is_integer() else parsed


def _finite_or_none(value: Any) -> float | int | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise VisionSystemError("V1_NONFINITE", str(value))
    return int(value) if isinstance(value, int) else parsed


def _csv_number(value: float | int | None) -> str:
    if value is None:
        return ""
    return str(value)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _reject_nonfinite(value: str) -> None:
    raise VisionSystemError("NONFINITE_JSON", value)
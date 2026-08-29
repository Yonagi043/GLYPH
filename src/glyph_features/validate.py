"""Validate the published CSV projections against schema 1.1.0."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver

from .measure import FEATURES


def _record(row: dict[str, str]) -> dict[str, Any]:
    def parse(name: str, default: Any) -> Any:
        value = row.get(name, "")
        return default if value == "" else json.loads(value)

    features: dict[str, Any] = {}
    for key in FEATURES:
        value = row.get(key, "")
        features[key] = None if value == "" else (float(value) if "." in value else int(value))
    return {
        "feature_record_id": row["feature_record_id"], "stimulus_id": row["stimulus_id"],
        "extraction_run_id": row["extraction_run_id"], "feature_definition_version": row["feature_definition_version"],
        "representation": row["representation"], "normalization_profile": row["normalization_profile"],
        "dimensions": [v for v in row["dimensions"].split("|") if v], "applicability": row["applicability"],
        "measurement_status": row["measurement_status"], "missing_reason": row.get("missing_reason") or None,
        "algorithm_config_sha256": row.get("algorithm_config_sha256") or None,
        "feature_numerators": parse("feature_numerators_json", {}), "feature_denominators": parse("feature_denominators_json", {}),
        "feature_units": parse("feature_units_json", {}), "feature_applicability": parse("feature_applicability_json", {}),
        "missing_reasons": parse("missing_reasons_json", {}), "features": features,
        "missing_features": [v for v in row.get("missing_features", "").split("|") if v],
    }


def validate_visual_csv(csv_path: str | Path, schema_path: str | Path = "schema/visual_features.schema.json") -> list[str]:
    schema_file = Path(schema_path).resolve()
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, resolver=RefResolver(schema_file.parent.as_uri() + "/", schema))
    errors: list[str] = []
    with Path(csv_path).open(encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle), start=2):
            for error in sorted(validator.iter_errors(_record(row)), key=lambda item: list(item.path)):
                errors.append(f"row {index}: {error.message}")
    return errors

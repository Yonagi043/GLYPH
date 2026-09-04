"""Stable-ID analysis joins with explicit anti-inflation audits."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from glyph_features.asset_system.catalog import stable_id, validate_record


class JoinAuditError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise JoinAuditError("JOIN_INPUT_INVALID", path.name)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise JoinAuditError("JOIN_INPUT_INVALID", path.name)
    return rows


def strict_many_to_one(
    left_rows: Iterable[dict[str, Any]],
    right_rows: Iterable[dict[str, Any]],
    *,
    left_key: str,
    right_key: str,
    step: str,
    right_prefix: str,
    require_all: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join only when every right key is unique and row count cannot inflate."""

    left = list(left_rows)
    right = list(right_rows)
    right_counts = Counter(row.get(right_key) for row in right)
    duplicate_keys = sorted(
        str(key) for key, count in right_counts.items() if key is not None and count > 1
    )
    if duplicate_keys:
        raise JoinAuditError(
            "UNEXPECTED_MANY_TO_MANY",
            f"{step} right key {right_key} repeats: {duplicate_keys[:5]}",
        )
    lookup = {row.get(right_key): row for row in right if row.get(right_key) is not None}
    output: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for row in left:
        key = row.get(left_key)
        match = lookup.get(key)
        if match is None:
            unmatched.append(str(key))
            if require_all:
                continue
            output.append(dict(row))
            continue
        combined = dict(row)
        for field, value in match.items():
            if field == right_key:
                continue
            combined[f"{right_prefix}{field}"] = value
        output.append(combined)
    if require_all and unmatched:
        raise JoinAuditError(
            "JOIN_UNMATCHED_REQUIRED_KEY",
            f"{step} unmatched {left_key}: {sorted(set(unmatched))[:5]}",
        )
    if len(output) > len(left):
        raise JoinAuditError("JOIN_ROW_INFLATION", step)
    audit = {
        "step": step,
        "relationship": "many_to_one",
        "left_key": left_key,
        "right_key": right_key,
        "left_rows": len(left),
        "left_unique_keys": len({row.get(left_key) for row in left}),
        "right_rows": len(right),
        "right_unique_keys": len(lookup),
        "unmatched_left_rows": len(unmatched),
        "max_right_multiplicity": max(right_counts.values(), default=0),
        "output_rows": len(output),
        "inflation_factor": 0.0 if not left else len(output) / len(left),
    }
    return output, audit


def require_narrative_exposure_operationalization(
    narrative_rows: Iterable[dict[str, Any]],
    *,
    randomized_material: bool = False,
    measured_exposure: bool = False,
    aggregate_context: bool = False,
) -> None:
    rows = list(narrative_rows)
    if rows and not (randomized_material or measured_exposure or aggregate_context):
        raise JoinAuditError(
            "NARRATIVE_EXPOSURE_NOT_OPERATIONALIZED",
            "WP2 evidence may remain a hypothesis/context link but cannot enter participant rows",
        )


def _generate_ratings(
    config: dict[str, Any],
    stimuli: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scripts = sorted({stimulus["writing_system"] for stimulus in stimuli})
    if scripts != ["han", "hangul", "kana", "latin"]:
        raise JoinAuditError("FIXTURE_SCRIPT_SET_UNEXPECTED", repr(scripts))
    language_for_script = {
        "han": "zh-Hans",
        "hangul": "ko",
        "kana": "ja",
        "latin": "en",
    }
    model = config["generation_model"]
    noise_values = model["deterministic_noise"]
    ratings: list[dict[str, Any]] = []
    for participant_index in range(config["participant_count"]):
        participant_id = f"synp_task05_{participant_index + 1:03d}"
        native_script = scripts[participant_index % len(scripts)]
        assignment_id = stable_id(
            "assignment", {"fixture": "task05", "participant_id": participant_id}
        )
        block_id = stable_id("block", {"assignment_id": assignment_id})
        for trial_index, stimulus in enumerate(stimuli, start=1):
            stimulus_id = stimulus["stimulus_id"]
            digest = hashlib.sha256(
                f"{config['seed']}|{participant_id}|{stimulus_id}".encode()
            ).digest()
            noise = noise_values[digest[0] % len(noise_values)]
            native_match = native_script == stimulus["writing_system"]
            response = model["baseline"] + noise
            if native_match:
                response += model["native_match_effect"]
            response = max(1, min(7, response))
            presentation_id = stable_id(
                "presentation",
                {"assignment_id": assignment_id, "stimulus_id": stimulus_id},
            )
            rating = {
                "schema_version": "2.0.0",
                "rating_id": stable_id(
                    "rating",
                    {
                        "participant_id": participant_id,
                        "stimulus_id": stimulus_id,
                        "item_id": config["item_id"],
                    },
                ),
                "study_id": "study_cross_cultural_v1",
                "questionnaire_version": "1.0.0",
                "assignment_id": assignment_id,
                "block_id": block_id,
                "presentation_id": presentation_id,
                "stimulus_id": stimulus_id,
                "participant_id": participant_id,
                "data_origin": "synthetic",
                "respondent_language_bcp47": language_for_script[native_script],
                "native_scripts": [native_script],
                "item_id": config["item_id"],
                "construct": config["construct"],
                "rating_scale": config["rating_scale"],
                "response": {"value": response, "missing_reason": None},
                "displayed_asset_sha256": stimulus["asset"]["sha256"],
                "trial_index": trial_index,
                "response_time_ms": 1200 + digest[1] * 5,
                "attention_check": None,
                "quality": {
                    "rule_version": "1.0.0",
                    "exclude_from_analysis": False,
                    "reason_codes": [],
                },
                "collected_at": "2026-09-04T00:00:00Z",
            }
            ratings.append(rating)
    return ratings


def _selected_feature_rows(
    measurements: list[dict[str, Any]],
    selections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_keys = {
        (
            selection["feature_code"],
            selection["representation"],
            selection["normalization_profile"],
        )
        for selection in selections
    }
    rows = [
        row
        for row in measurements
        if (
            row["feature_code"],
            row["representation"],
            row["normalization_profile"],
        )
        in selected_keys
    ]
    observed_keys = {
        (row["feature_code"], row["representation"], row["normalization_profile"])
        for row in rows
    }
    if observed_keys != selected_keys:
        missing = sorted(selected_keys - observed_keys)
        raise JoinAuditError("FROZEN_FEATURE_MISSING", repr(missing))
    return rows


def _pivot_features(
    measurements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_stimulus: dict[str, dict[str, Any]] = defaultdict(dict)
    seen: set[tuple[str, str]] = set()
    missing_counts: Counter[str] = Counter()
    for row in measurements:
        column = f"feature__{row['representation']}__{row['feature_code']}"
        key = (row["stimulus_id"], column)
        if key in seen:
            raise JoinAuditError("UNEXPECTED_MANY_TO_MANY", f"duplicate feature cell {key}")
        seen.add(key)
        value = row["value"]
        if row["measurement_status"] != "valid":
            value = None
            missing_counts[row.get("missing_code") or "UNSPECIFIED"] += 1
        by_stimulus[row["stimulus_id"]][column] = value
    rows = [
        {"source_stimulus_id": stimulus_id, **features}
        for stimulus_id, features in sorted(by_stimulus.items())
    ]
    return rows, {
        "selected_measurement_rows": len(measurements),
        "source_stimulus_count": len(rows),
        "missing_by_code": dict(sorted(missing_counts.items())),
        "nulls_preserved_not_zero_imputed": True,
    }


def build_synthetic_analysis_table(
    workspace_root: str | Path,
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Build the licensed synthetic analysis unit and complete join audit."""

    root = Path(workspace_root).resolve()
    config_path = root / "data/fixtures/system_e2e/generator_config.json"
    config = _read_json(config_path)
    config_errors = validate_record(config, root / "schema/system_fixture.schema.json")
    if config_errors:
        raise JoinAuditError("FIXTURE_CONFIG_INVALID", " | ".join(config_errors))
    stimulus_catalog = _read_json(root / config["task03_catalog_path"])["items"]
    ratings = _generate_ratings(config, stimulus_catalog)
    origins = {row["data_origin"] for row in ratings}
    if origins != {"synthetic"}:
        raise JoinAuditError("MIXED_DATA_ORIGIN", repr(sorted(origins)))
    included = [
        row
        for row in ratings
        if not row["quality"]["exclude_from_analysis"]
        and row["response"]["value"] is not None
    ]
    rows, stimulus_audit = strict_many_to_one(
        included,
        stimulus_catalog,
        left_key="stimulus_id",
        right_key="stimulus_id",
        step="ratings_to_experiment_stimuli",
        right_prefix="stimulus__",
    )
    analysis_rows = []
    for row in rows:
        analysis_rows.append(
            {
                "rating_id": row["rating_id"],
                "participant_id": row["participant_id"],
                "stimulus_id": row["stimulus_id"],
                "source_stimulus_id": row["stimulus__source_stimulus_id"],
                "work_id": row["stimulus__work_id"],
                "item_id": row["item_id"],
                "data_origin": row["data_origin"],
                "rating_scale": row["rating_scale"],
                "response_value": row["response"]["value"],
                "native_script": row["native_scripts"][0],
                "stimulus_script": row["stimulus__writing_system"],
                "native_match": row["native_scripts"][0]
                == row["stimulus__writing_system"],
            }
        )
    measurements = _read_jsonl(root / config["visual_measurements_path"])
    selected_measurements = _selected_feature_rows(
        measurements, plan["features"]["selection"]
    )
    feature_rows, feature_audit = _pivot_features(selected_measurements)
    analysis_rows, feature_join_audit = strict_many_to_one(
        analysis_rows,
        feature_rows,
        left_key="source_stimulus_id",
        right_key="source_stimulus_id",
        step="source_stimuli_to_visual_features",
        right_prefix="",
    )
    unit_keys = [
        (row["participant_id"], row["stimulus_id"], row["item_id"])
        for row in analysis_rows
    ]
    duplicate_units = [key for key, count in Counter(unit_keys).items() if count > 1]
    if duplicate_units:
        raise JoinAuditError("ANALYSIS_UNIT_DUPLICATE", repr(duplicate_units[:5]))
    feature_columns = sorted(
        key for key in analysis_rows[0] if key.startswith("feature__")
    )
    join_audit = {
        "schema_version": "1.0.0",
        "analysis_unit": "participant_x_stimulus_x_item",
        "data_origin": "synthetic",
        "input_rows": {
            "generated_ratings": len(ratings),
            "included_ratings": len(included),
            "stimulus_catalog": len(stimulus_catalog),
            "visual_measurements": len(measurements),
        },
        "filters": {
            "excluded_by_quality": len(ratings) - len(included),
            "missing_response": sum(row["response"]["value"] is None for row in ratings),
        },
        "join_steps": [stimulus_audit, feature_join_audit],
        "feature_audit": feature_audit,
        "feature_columns": feature_columns,
        "final_rows": len(analysis_rows),
        "unique_analysis_units": len(set(unit_keys)),
        "cluster_counts": {
            "participant_id": len({row["participant_id"] for row in analysis_rows}),
            "stimulus_id": len({row["stimulus_id"] for row in analysis_rows}),
            "work_id": len({row["work_id"] for row in analysis_rows}),
            "source_stimulus_id": len(
                {row["source_stimulus_id"] for row in analysis_rows}
            ),
        },
        "narrative_policy": {
            "participant_exposure_attached": False,
            "allowed_role": "hypothesis_context_only",
        },
        "anti_pseudoreplication": {
            "visual_increment_eligible": len(
                {row["source_stimulus_id"] for row in analysis_rows}
            )
            > 1,
            "shared_source_stimulus_not_counted_as_independent": True,
        },
    }
    return analysis_rows, join_audit, ratings
"""Cross-record validation for the Han style concept registry."""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import validate_record


TARGET_STYLE_CODES = frozenset(
    {
        "small_seal",
        "clerical",
        "regular",
        "running",
        "cursive",
        "song",
        "sans",
        "slender_gold",
    }
)


def validate_ontology(
    records: list[dict[str, Any]],
    schema_path: str | Path,
    source_ids: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    records_by_id: dict[str, dict[str, Any]] = {}
    style_ids_by_target: dict[str, str] = {}
    alias_owners: dict[str, str] = {}

    for index, record in enumerate(records, start=1):
        for message in validate_record(record, schema_path):
            errors.append(f"HAN_SCHEMA_INVALID record={index}: {message}")
        style_id = record.get("style_id")
        if not isinstance(style_id, str):
            continue
        if style_id in records_by_id:
            errors.append(f"HAN_STYLE_ID_DUPLICATE style_id={style_id}")
        records_by_id[style_id] = record

        target_code = record.get("target_code")
        if isinstance(target_code, str):
            previous_style_id = style_ids_by_target.get(target_code)
            if previous_style_id is not None:
                errors.append(
                    f"HAN_TARGET_CODE_DUPLICATE target_code={target_code} "
                    f"style_ids={previous_style_id},{style_id}"
                )
            style_ids_by_target[target_code] = style_id

        names = list((record.get("canonical_names") or {}).values())
        names.extend(record.get("historical_names") or [])
        names.extend(alias.get("term") for alias in record.get("aliases") or [] if isinstance(alias, dict))
        for name in names:
            if not isinstance(name, str):
                continue
            alias_key = _normalized_alias(name)
            previous_owner = alias_owners.get(alias_key)
            if previous_owner is not None and previous_owner != style_id:
                errors.append(
                    f"HAN_ALIAS_AMBIGUOUS alias={name!r} style_ids={previous_owner},{style_id}"
                )
            alias_owners[alias_key] = style_id

        period = record.get("historical_period") or {}
        start_year = period.get("start_year")
        end_year = period.get("end_year")
        if isinstance(start_year, int) and isinstance(end_year, int) and start_year > end_year:
            errors.append(f"HAN_PERIOD_INVALID style_id={style_id}")
        if source_ids is not None:
            for source_id in record.get("definition_source_ids") or []:
                if source_id not in source_ids:
                    errors.append(f"HAN_STYLE_SOURCE_UNKNOWN style_id={style_id} source_id={source_id}")

    actual_targets = set(style_ids_by_target)
    if actual_targets != TARGET_STYLE_CODES:
        errors.append(
            "HAN_TARGET_SET_MISMATCH "
            f"missing={sorted(TARGET_STYLE_CODES - actual_targets)} "
            f"unexpected={sorted(actual_targets - TARGET_STYLE_CODES)}"
        )

    for style_id, record in records_by_id.items():
        for parent_id in record.get("broader_style_ids") or []:
            if parent_id not in records_by_id:
                errors.append(f"HAN_STYLE_PARENT_UNKNOWN style_id={style_id} parent_id={parent_id}")

    errors.extend(_cycle_errors(records_by_id))
    return sorted(set(errors))


def _normalized_alias(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _cycle_errors(records_by_id: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(style_id: str, ancestry: tuple[str, ...]) -> None:
        if style_id in visiting:
            cycle = ancestry[ancestry.index(style_id):] + (style_id,)
            errors.append(f"HAN_STYLE_CYCLE path={'->'.join(cycle)}")
            return
        if style_id in visited:
            return
        visiting.add(style_id)
        for parent_id in records_by_id[style_id].get("broader_style_ids") or []:
            if parent_id in records_by_id:
                visit(parent_id, ancestry + (parent_id,))
        visiting.remove(style_id)
        visited.add(style_id)

    for style_id in sorted(records_by_id):
        visit(style_id, (style_id,))
    return errors

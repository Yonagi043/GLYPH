"""Character-mapping and glyph-instance contract validation."""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import resolve_workspace_asset, validate_record


EXPECTED_ASSET_ROLES = {
    "original": "original",
    "A_layout": "A_layout",
    "B_shape": "B_shape",
    "B_shape_mask": "mask",
    "C_ink": "C_ink",
}


def load_content_sets(path: str | Path) -> dict[str, dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["content_set_id"]: dict(row) for row in csv.DictReader(handle)}


def validate_character_mappings(
    records: list[dict[str, Any]],
    schema_path: str | Path,
    content_sets: dict[str, dict[str, str]],
    source_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    mapping_ids: set[str] = set()
    mapped_content_sets: set[str] = set()
    for index, record in enumerate(records, start=1):
        errors.extend(
            f"HAN_MAPPING_SCHEMA_INVALID record={index}: {message}"
            for message in validate_record(record, schema_path)
        )
        mapping_id = record.get("mapping_id")
        if mapping_id in mapping_ids:
            errors.append(f"HAN_MAPPING_ID_DUPLICATE mapping_id={mapping_id}")
        if isinstance(mapping_id, str):
            mapping_ids.add(mapping_id)
        content_set_id = record.get("content_set_id")
        if content_set_id in mapped_content_sets:
            errors.append(f"HAN_CONTENT_MAPPING_DUPLICATE content_set_id={content_set_id}")
        if isinstance(content_set_id, str):
            mapped_content_sets.add(content_set_id)
        content_set = content_sets.get(str(content_set_id))
        if content_set is None or content_set.get("writing_system") != "han":
            errors.append(f"HAN_CONTENT_SET_UNKNOWN content_set_id={content_set_id}")
        else:
            normalized = unicodedata.normalize("NFC", str(record.get("display_text", "")))
            if record.get("normalized_text") != normalized:
                errors.append(f"HAN_UNICODE_NORMALIZATION_MISMATCH mapping_id={mapping_id}")
            if normalized != content_set.get("content"):
                errors.append(f"HAN_CONTENT_TEXT_MISMATCH mapping_id={mapping_id}")
            if record.get("unit_count") != int(content_set["unit_count"]):
                errors.append(f"HAN_CONTENT_UNIT_COUNT_MISMATCH mapping_id={mapping_id}")
            if record.get("unicode_codepoints") != _codepoints(normalized):
                errors.append(f"HAN_UNICODE_CODEPOINT_MISMATCH mapping_id={mapping_id}")
        for source_id in record.get("source_ids") or []:
            if source_id not in source_ids:
                errors.append(f"HAN_MAPPING_SOURCE_UNKNOWN mapping_id={mapping_id} source_id={source_id}")
        for related_form in record.get("related_forms") or []:
            if related_form.get("source_id") not in source_ids:
                errors.append(
                    f"HAN_RELATED_FORM_SOURCE_UNKNOWN mapping_id={mapping_id} "
                    f"source_id={related_form.get('source_id')}"
                )
    return sorted(set(errors))


def validate_glyph_instances(
    records: list[dict[str, Any]],
    schema_path: str | Path,
    *,
    workspace_root: str | Path,
    style_ids: set[str],
    mapping_ids: set[str],
    source_ids: set[str],
    asset_records: list[dict[str, Any]],
    claim_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    glyph_ids: set[str] = set()
    parent_by_id: dict[str, str | None] = {}
    assets_by_id = {
        record.get("asset_id"): record
        for record in asset_records
        if isinstance(record.get("asset_id"), str)
    }
    for index, record in enumerate(records, start=1):
        errors.extend(
            f"HAN_GLYPH_SCHEMA_INVALID record={index}: {message}"
            for message in validate_record(record, schema_path)
        )
        glyph_id = record.get("glyph_instance_id")
        if glyph_id in glyph_ids:
            errors.append(f"HAN_GLYPH_ID_DUPLICATE glyph_instance_id={glyph_id}")
        if isinstance(glyph_id, str):
            glyph_ids.add(glyph_id)
            parent_by_id[glyph_id] = record.get("parent_glyph_instance_id")
        if record.get("style_id") not in style_ids:
            errors.append(f"HAN_GLYPH_STYLE_UNKNOWN glyph_instance_id={glyph_id}")
        if record.get("mapping_id") not in mapping_ids:
            errors.append(f"HAN_GLYPH_MAPPING_UNKNOWN glyph_instance_id={glyph_id}")
        if record.get("source_id") not in source_ids:
            errors.append(f"HAN_GLYPH_SOURCE_UNKNOWN glyph_instance_id={glyph_id}")
        for claim_id in record.get("historical_claim_ids") or []:
            if claim_id not in claim_ids:
                errors.append(f"HAN_GLYPH_CLAIM_UNKNOWN glyph_instance_id={glyph_id} claim_id={claim_id}")
        representation_ids = record.get("representation_asset_ids") or {}
        for key, expected_role in EXPECTED_ASSET_ROLES.items():
            asset_id = representation_ids.get(key)
            if asset_id is None:
                continue
            asset_record = assets_by_id.get(asset_id)
            if asset_record is None:
                errors.append(f"HAN_GLYPH_ASSET_UNKNOWN glyph_instance_id={glyph_id} asset_id={asset_id}")
                continue
            if asset_record.get("asset_role") != expected_role:
                errors.append(
                    f"HAN_GLYPH_ASSET_ROLE_MISMATCH glyph_instance_id={glyph_id} "
                    f"asset_id={asset_id} expected={expected_role}"
                )
            if asset_record.get("source_id") != record.get("source_id"):
                errors.append(
                    f"HAN_GLYPH_ASSET_SOURCE_MISMATCH glyph_instance_id={glyph_id} asset_id={asset_id}"
                )
            if asset_record.get("work_id") != record.get("work_id"):
                errors.append(
                    f"HAN_GLYPH_ASSET_WORK_MISMATCH glyph_instance_id={glyph_id} asset_id={asset_id}"
                )
            if record.get("font_id") is not None:
                font_metadata = asset_record.get("font_metadata")
                if not isinstance(font_metadata, dict) or font_metadata.get("font_id") != record.get("font_id"):
                    errors.append(
                        f"HAN_GLYPH_ASSET_FONT_MISMATCH glyph_instance_id={glyph_id} asset_id={asset_id}"
                    )
            try:
                resolve_workspace_asset(workspace_root, asset_record.get("asset_ref") or {})
            except ValueError as error:
                errors.append(f"HAN_GLYPH_ASSET_INVALID glyph_instance_id={glyph_id} asset_id={asset_id}: {error}")
        if record.get("asset_id") not in set(representation_ids.values()):
            errors.append(f"HAN_GLYPH_PRIMARY_ASSET_UNLINKED glyph_instance_id={glyph_id}")
        parent_id = record.get("parent_glyph_instance_id")
        if parent_id is not None and parent_id == glyph_id:
            errors.append(f"HAN_GLYPH_SELF_PARENT glyph_instance_id={glyph_id}")
    for glyph_id, parent_id in parent_by_id.items():
        if parent_id is not None and parent_id not in glyph_ids:
            errors.append(f"HAN_GLYPH_PARENT_UNKNOWN glyph_instance_id={glyph_id} parent_id={parent_id}")
    errors.extend(_parent_cycle_errors(parent_by_id))
    return sorted(set(errors))


def _codepoints(value: str) -> list[str]:
    return [f"U+{ord(character):04X}" for character in value]


def _parent_cycle_errors(parent_by_id: dict[str, str | None]) -> list[str]:
    errors: list[str] = []
    for start_id in sorted(parent_by_id):
        current: str | None = start_id
        path: list[str] = []
        positions: dict[str, int] = {}
        while current is not None and current in parent_by_id:
            if current in positions:
                cycle = path[positions[current]:]
                errors.append(f"HAN_GLYPH_PARENT_CYCLE glyph_instance_ids={'|'.join(sorted(cycle))}")
                break
            positions[current] = len(path)
            path.append(current)
            current = parent_by_id[current]
    return sorted(set(errors))

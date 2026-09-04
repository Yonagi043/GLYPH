"""Validation for sourced Han knowledge and association claims."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import canonical_json, stable_id, validate_record
from glyph_features.han_style_system.trust import load_trust_root, trusted_human_decisions


RELATION_OBJECT_TYPES = {
    "derived_from_glyph": {"glyph_instance"},
    "derived_from_work": {"work"},
    "attributed_to_style": {"style_concept"},
    "uses_font_instance": {"font_instance"},
    "realized_as_stimulus": {"stimulus_candidate"},
    "evolved_from": {"style_concept", "glyph_instance"},
}


def import_claim_rows(
    rows: list[dict[str, str]],
    schema_path: str | Path,
    *,
    style_ids: set[str],
    glyph_ids: set[str],
    source_ids: set[str],
    work_ids: set[str] | None = None,
    font_ids: set[str] | None = None,
    stimulus_candidate_ids: set[str] | None = None,
    human_decisions: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        try:
            record = _claim_record(row)
            errors = validate_claims(
                [record],
                schema_path,
                style_ids=style_ids,
                glyph_ids=glyph_ids,
                source_ids=source_ids,
                work_ids=work_ids,
                font_ids=font_ids,
                stimulus_candidate_ids=stimulus_candidate_ids,
                human_decisions=human_decisions,
            )
            if errors:
                raise ValueError("; ".join(errors))
            records.append(record)
        except (KeyError, TypeError, ValueError) as error:
            failures.append(
                {
                    "code": "CLAIM_ROW_INVALID",
                    "row_number": row_number,
                    "claim_id": row.get("claim_id") or None,
                    "message": str(error),
                }
            )
    claim_ids = [record["claim_id"] for record in records]
    if len(claim_ids) != len(set(claim_ids)):
        duplicate_ids = sorted({claim_id for claim_id in claim_ids if claim_ids.count(claim_id) > 1})
        failures.extend(
            {
                "code": "CLAIM_ID_DUPLICATE",
                "row_number": None,
                "claim_id": claim_id,
                "message": "duplicate claim identity",
            }
            for claim_id in duplicate_ids
        )
        records = [record for record in records if record["claim_id"] not in duplicate_ids]
    return records, failures


def validate_claims(
    records: list[dict[str, Any]],
    schema_path: str | Path,
    *,
    style_ids: set[str],
    glyph_ids: set[str],
    source_ids: set[str],
    work_ids: set[str] | None = None,
    font_ids: set[str] | None = None,
    stimulus_candidate_ids: set[str] | None = None,
    human_decisions: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    claim_ids: set[str] = set()
    valid_subjects = {
        "style_concept": style_ids,
        "glyph_instance": glyph_ids,
        "work": work_ids or set(),
        "font_instance": font_ids or set(),
        "stimulus_candidate": stimulus_candidate_ids or set(),
    }
    decisions = trusted_human_decisions(load_trust_root())
    if human_decisions is not None:
        errors.append("HAN_CLAIM_HUMAN_DECISION_SOURCE_UNTRUSTED")
    for index, record in enumerate(records, start=1):
        errors.extend(
            f"HAN_CLAIM_SCHEMA_INVALID record={index}: {message}"
            for message in validate_record(record, schema_path)
        )
        claim_id = record.get("claim_id")
        if claim_id in claim_ids:
            errors.append(f"HAN_CLAIM_ID_DUPLICATE claim_id={claim_id}")
        if isinstance(claim_id, str):
            claim_ids.add(claim_id)
        if record.get("source_id") not in source_ids:
            errors.append(f"HAN_CLAIM_SOURCE_UNKNOWN claim_id={claim_id}")
        subject_type = record.get("subject_type")
        if subject_type in valid_subjects and record.get("subject_id") not in valid_subjects[subject_type]:
            errors.append(f"HAN_CLAIM_SUBJECT_UNKNOWN claim_id={claim_id}")
        object_id = record.get("object_id")
        object_type = record.get("object_type")
        if object_id is not None:
            allowed_types = RELATION_OBJECT_TYPES.get(str(record.get("relation")))
            if allowed_types is None or object_type not in allowed_types:
                errors.append(f"HAN_CLAIM_OBJECT_TYPE_INVALID claim_id={claim_id}")
            if object_type not in valid_subjects or object_id not in valid_subjects.get(object_type, set()):
                errors.append(f"HAN_CLAIM_OBJECT_UNKNOWN claim_id={claim_id}")
        if record.get("verification_status") == "human_verified":
            decision = decisions.get(str(record.get("human_decision_id")))
            evidence_hash = hashlib.sha256(
                canonical_json(
                    {
                        "source_id": record.get("source_id"),
                        "source_locator": record.get("source_locator"),
                        "evidence_span": record.get("evidence_span"),
                    }
                )
            ).hexdigest()
            if decision is None:
                errors.append(f"HAN_CLAIM_HUMAN_DECISION_UNKNOWN claim_id={claim_id}")
            elif (
                decision.get("claim_id") != claim_id
                or decision.get("reviewer_id") != record.get("human_reviewer_id")
                or decision.get("evidence_sha256") != evidence_hash
                or decision.get("decision") != "verified"
            ):
                errors.append(f"HAN_CLAIM_HUMAN_DECISION_MISMATCH claim_id={claim_id}")
        if record.get("extraction_method") == "llm_candidate" and record.get("verification_status") == "human_verified":
            translation = record.get("translation")
            if translation is not None and translation.get("review_status") == "machine_candidate":
                errors.append(f"HAN_CLAIM_MACHINE_TRANSLATION_UNREVIEWED claim_id={claim_id}")
        if record.get("claim_domain") == "cultural_association" and record.get("relation") in {
            "historically_is",
            "originated_as",
            "caused_by",
        }:
            errors.append(f"HAN_ASSOCIATION_AS_FACT claim_id={claim_id}")
    return sorted(set(errors))


def _claim_record(row: dict[str, str]) -> dict[str, Any]:
    translation_text = row.get("translation_text", "").strip()
    translation = None
    if translation_text:
        translation = {
            "text": translation_text,
            "language_bcp47": _required(row, "translation_language_bcp47"),
            "review_status": _required(row, "translation_review_status"),
        }
    object_id = row.get("object_id", "").strip() or None
    object_value = row.get("object_value", "").strip() or None
    identity = {
        "subject_type": _required(row, "subject_type"),
        "subject_id": _required(row, "subject_id"),
        "relation": _required(row, "relation"),
        "object_type": row.get("object_type", "").strip() or None,
        "object_id": object_id,
        "object_value": object_value,
        "source_id": _required(row, "source_id"),
        "source_locator": _required(row, "source_locator"),
    }
    return {
        "schema_version": "1.1.0",
        "claim_id": row.get("claim_id", "").strip() or stable_id("claim", identity),
        "claim_domain": _required(row, "claim_domain"),
        "claim_type": _required(row, "claim_type"),
        **identity,
        "evidence_span": _required(row, "evidence_span"),
        "original_language_bcp47": _required(row, "original_language_bcp47"),
        "translation": translation,
        "evidence_grade": _required(row, "evidence_grade"),
        "confidence": _probability(row.get("confidence")),
        "uncertainty": _required(row, "uncertainty"),
        "extraction_method": _required(row, "extraction_method"),
        "verification_status": _required(row, "verification_status"),
        "human_reviewer_id": row.get("human_reviewer_id", "").strip() or None,
        "human_decision_id": row.get("human_decision_id", "").strip() or None,
        "stance": _required(row, "stance"),
    }


def _required(row: dict[str, str], field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"required field is empty: {field}")
    return value


def _probability(value: str | None) -> float:
    try:
        number = float(value or "")
    except ValueError as error:
        raise ValueError("confidence must be a number") from error
    if not 0 <= number <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return number

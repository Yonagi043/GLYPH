"""Schema and cross-record validation for experiment contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[3]
LANGUAGES = {"zh-Hans", "en", "ja", "ko"}
MODULES = {
    "information_consent",
    "eligibility",
    "language_scripts",
    "training_exposure",
    "device_practice",
    "visual_ratings",
    "recognition",
    "quality",
    "optional_feedback",
    "completion_withdrawal",
}


class StudyIdMismatch(ValueError):
    code = "STUDY_ID_MISMATCH"

    def __init__(self, provided: str, expected: str) -> None:
        super().__init__(f"STUDY_ID_MISMATCH: {provided!r} != {expected!r}")


def require_frozen_study_id(provided: str, expected: str) -> None:
    if provided != expected:
        raise StudyIdMismatch(provided, expected)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_record(record: dict[str, Any], schema_name: str) -> list[str]:
    schema_dir = ROOT / "schema"
    schema_path = schema_dir / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = Registry()
    for candidate in schema_dir.glob("*.schema.json"):
        candidate_schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(candidate_schema)
        registry = registry.with_resource(candidate.name, resource).with_resource(candidate.resolve().as_uri(), resource)
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    return [
        f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path))
    ]


def validate_contract_set(
    protocol: dict[str, Any],
    questionnaire: dict[str, Any],
    participant: dict[str, Any],
    consent: dict[str, Any],
) -> list[str]:
    records = [
        (protocol, "study_protocol.schema.json", "protocol"),
        (questionnaire, "questionnaire_definition.schema.json", "questionnaire"),
        (participant, "participant_profile.schema.json", "participant"),
        (consent, "consent_receipt.schema.json", "consent"),
    ]
    errors = [f"{label}: {error}" for record, schema, label in records for error in validate_record(record, schema)]
    study_id = protocol.get("study_id")
    for record, _, label in records[1:]:
        if record.get("study_id") != study_id:
            errors.append(f"{label}: STUDY_ID_MISMATCH")
    participant_id = participant.get("participant_id")
    if consent.get("participant_id") != participant_id:
        errors.append("consent: PARTICIPANT_ID_MISMATCH")
    if set(questionnaire.get("supported_languages", [])) != LANGUAGES:
        errors.append("questionnaire: LANGUAGE_SET_INCOMPLETE")
    if set(questionnaire.get("modules", [])) != MODULES:
        errors.append("questionnaire: MODULE_SET_INCOMPLETE")
    item_ids = [item.get("item_id") for item in questionnaire.get("items", []) if isinstance(item, dict)]
    if len(item_ids) != len(set(item_ids)):
        errors.append("questionnaire: DUPLICATE_ITEM_ID")
    return errors
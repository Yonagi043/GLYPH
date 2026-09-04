"""Export gates for experiment responses."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .schema import ROOT, validate_record
from .quality import build_quality_decision


FORMAL_GATES = {"GATE-ETHICS", "GATE-PARTICIPANTS", "GATE-TRANSLATION"}
FORBIDDEN_KEYS = {
    "name",
    "full_name",
    "email",
    "phone",
    "address",
    "ip",
    "ip_address",
    "contact",
    "compensation",
    "cookie",
    "token",
}
BUNDLE_SPECS = {
    "profiles": ("participant_profiles.jsonl", "participant_profile.schema.json", "1.0.0", "participant_id"),
    "consents": ("consent_receipts.jsonl", "consent_receipt.schema.json", "1.1.0", "participant_id"),
    "assignments": ("assignments.jsonl", "experiment_assignment.schema.json", "1.0.0", "assignment_id"),
    "presentations": ("presentation_events.jsonl", "presentation_event.schema.json", "1.0.0", "presentation_id"),
    "ratings": ("ratings.jsonl", "experiment_rating.schema.json", "2.0.0", "rating_id"),
    "quality_decisions": ("quality_decisions.jsonl", "quality_decision.schema.json", "1.0.0", "decision_id"),
}


class ExportBlocked(ValueError):
    """A stable, machine-readable export failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def require_export_eligible(
    records: Iterable[Mapping[str, Any]],
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> None:
    """Reject synthetic responses from formal analysis and release."""
    if purpose not in {"engineering_fixture", "formal_analysis", "release"}:
        raise ExportBlocked("EXPORT_PURPOSE_INVALID", purpose)
    origins = {record.get("data_origin") for record in records}
    if purpose in {"formal_analysis", "release"} and "synthetic" in origins:
        raise ExportBlocked(
            "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN",
            "synthetic responses are restricted to engineering fixtures",
        )
    if purpose in {"formal_analysis", "release"}:
        statuses = human_gates or {}
        blocked = sorted(gate for gate in FORMAL_GATES if statuses.get(gate) != "passed")
        if blocked:
            raise ExportBlocked("HUMAN_GATES_NOT_PASSED", ",".join(blocked))


def write_deidentified_export(
    records: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    rows = list(records)
    require_export_eligible(rows, purpose=purpose, human_gates=human_gates)
    errors = validate_export_records(rows)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_EXPORT_INVALID", "; ".join(errors))
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"export already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in sorted(rows, key=lambda item: item["rating_id"])
    )
    output.write_text(payload, encoding="utf-8", newline="\n")
    return {
        "path": output.as_posix(),
        "record_count": len(rows),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "data_origins": sorted({row["data_origin"] for row in rows}),
        "purpose": purpose,
    }


def write_deidentified_bundle(
    records: Mapping[str, list[dict[str, Any]]],
    output_path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    rows = {record_type: list(records.get(record_type, [])) for record_type in BUNDLE_SPECS}
    all_records = [record for values in rows.values() for record in values]
    require_export_eligible(all_records, purpose=purpose, human_gates=human_gates)
    errors = validate_deidentified_bundle(rows)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_BUNDLE_INVALID", "; ".join(errors))
    _require_quality_eligible(rows, purpose=purpose)

    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"export already exists: {output}")
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise FileExistsError(f"export staging already exists: {staging}")
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        staging.mkdir()
        artifacts: list[dict[str, Any]] = []
        for record_type, (filename, schema_name, schema_version, id_key) in BUNDLE_SPECS.items():
            ordered = sorted(rows[record_type], key=lambda record: record[id_key])
            payload = "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for record in ordered
            )
            artifact_path = staging / filename
            artifact_path.write_text(payload, encoding="utf-8", newline="\n")
            artifacts.append({
                "record_type": record_type,
                "path": filename,
                "schema": schema_name,
                "schema_version": schema_version,
                "record_count": len(ordered),
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            })
        origins = sorted({record["data_origin"] for record in all_records})
        study_ids = {record["study_id"] for record in all_records}
        manifest = {
            "schema_version": "1.0.0",
            "study_id": next(iter(study_ids)),
            "purpose": purpose,
            "synthetic_only": origins == ["synthetic"],
            "data_origins": origins,
            "quality_rule_version": "1.0.0",
            "artifacts": sorted(artifacts, key=lambda artifact: artifact["record_type"]),
        }
        manifest_errors = validate_record(manifest, "experiment_export_manifest.schema.json")
        if manifest_errors:
            raise ExportBlocked("EXPORT_MANIFEST_INVALID", "; ".join(manifest_errors))
        (staging / "export_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "path": output.as_posix(),
        "purpose": purpose,
        "record_counts": {record_type: len(rows[record_type]) for record_type in sorted(rows)},
        "synthetic_only": origins == ["synthetic"],
    }


def read_and_validate_bundle(
    path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    root = Path(path)
    manifest = json.loads((root / "export_manifest.json").read_text(encoding="utf-8"))
    manifest_errors = validate_record(manifest, "experiment_export_manifest.schema.json")
    if manifest_errors:
        raise ExportBlocked("EXPORT_MANIFEST_INVALID", "; ".join(manifest_errors))
    if manifest["purpose"] != purpose:
        raise ExportBlocked("EXPORT_PURPOSE_MISMATCH", f"{manifest['purpose']} != {purpose}")
    declaration_errors = _manifest_declaration_errors(manifest)
    if declaration_errors:
        raise ExportBlocked("EXPORT_MANIFEST_BINDING_MISMATCH", "; ".join(declaration_errors))
    records: dict[str, list[dict[str, Any]]] = {}
    for artifact in manifest["artifacts"]:
        artifact_path = root / artifact["path"]
        payload = artifact_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != artifact["sha256"]:
            raise ExportBlocked("EXPORT_ARTIFACT_HASH_MISMATCH", artifact["path"])
        rows = [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]
        if len(rows) != artifact["record_count"]:
            raise ExportBlocked("EXPORT_ARTIFACT_COUNT_MISMATCH", artifact["path"])
        records[artifact["record_type"]] = rows
    all_records = [record for values in records.values() for record in values]
    require_export_eligible(all_records, purpose=purpose, human_gates=human_gates)
    errors = validate_deidentified_bundle(records)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_BUNDLE_INVALID", "; ".join(errors))
    content_errors = _manifest_content_errors(manifest, records)
    if content_errors:
        raise ExportBlocked("EXPORT_MANIFEST_CONTENT_MISMATCH", "; ".join(content_errors))
    _require_quality_eligible(records, purpose=purpose)
    return records


def validate_deidentified_bundle(
    records: Mapping[str, list[dict[str, Any]]],
    *,
    catalog_items: Iterable[Mapping[str, Any]] | None = None,
    questionnaire_items: Iterable[Mapping[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    effective_questionnaire_items = list(questionnaire_items) if questionnaire_items is not None else json.loads(
        (ROOT / "configs/questionnaire_v1.json").read_text(encoding="utf-8")
    )["items"]
    required_rating_item_ids = {
        item["item_id"]
        for item in effective_questionnaire_items
        if item["required"] and item["response_type"] in {"likert_1_7", "likert_1_5", "continuous_0_100"}
    }
    missing_types = sorted(set(BUNDLE_SPECS) - set(records))
    if missing_types:
        errors.append(f"RECORD_TYPES_MISSING:{','.join(missing_types)}")
        return errors
    for record_type, (_, schema_name, _, id_key) in BUNDLE_SPECS.items():
        seen: set[str] = set()
        for index, record in enumerate(records[record_type], start=1):
            errors.extend(
                f"{record_type} record {index}: {error}"
                for error in validate_record(record, schema_name)
            )
            errors.extend(
                f"{record_type} record {index}: FORBIDDEN_PII_KEY:{key}"
                for key in sorted(_forbidden_keys(record))
            )
            record_id = record.get(id_key)
            if record_id in seen:
                errors.append(f"DUPLICATE_{record_type.upper()}_ID:{record_id}")
            if isinstance(record_id, str):
                seen.add(record_id)
    if errors:
        return errors
    all_records = [record for values in records.values() for record in values]
    if len({record.get("study_id") for record in all_records}) != 1:
        errors.append("BUNDLE_STUDY_ID_MISMATCH")
    assignment_participants: set[str] = set()
    for assignment in records["assignments"]:
        participant_id = assignment["participant_id"]
        if participant_id in assignment_participants:
            errors.append(f"DUPLICATE_PARTICIPANT_ASSIGNMENT:{participant_id}")
        assignment_participants.add(participant_id)
    profiles = {record["participant_id"]: record for record in records["profiles"]}
    consents = {record["participant_id"]: record for record in records["consents"]}
    assignments = {record["participant_id"]: record for record in records["assignments"]}
    if set(profiles) != set(consents) or set(profiles) != set(assignments):
        errors.append("PARTICIPANT_PROFILE_CONSENT_ASSIGNMENT_SET_MISMATCH")
    for participant_id in set(profiles) & set(consents) & set(assignments):
        profile = profiles[participant_id]
        consent = consents[participant_id]
        assignment = assignments[participant_id]
        expected = {
            "study_id": profile["study_id"],
            "participant_id": participant_id,
            "data_origin": profile["data_origin"],
        }
        if any(consent.get(key) != value or assignment.get(key) != value for key, value in expected.items()):
            errors.append(f"PARTICIPANT_CONTEXT_FOREIGN_KEY_MISMATCH:{participant_id}")
        if consent["protocol_version"] != assignment["protocol_version"]:
            errors.append(f"PARTICIPANT_CONTEXT_PROTOCOL_VERSION_MISMATCH:{participant_id}")
        if consent["questionnaire_version"] != assignment["questionnaire_version"]:
            errors.append(f"PARTICIPANT_CONTEXT_QUESTIONNAIRE_VERSION_MISMATCH:{participant_id}")
    trials = {
        trial["presentation_id"]: (assignment, trial)
        for assignment in assignments.values()
        for trial in assignment["trials"]
    }
    if catalog_items is not None:
        catalog = {item["stimulus_id"]: item for item in catalog_items}
        for presentation_id, (_, trial) in trials.items():
            item = catalog.get(trial["stimulus_id"])
            if item is None:
                errors.append(f"ASSIGNMENT_CATALOG_MISMATCH:{presentation_id}:stimulus_id")
                continue
            expected = {
                "source_stimulus_id": item["source_stimulus_id"],
                "work_id": item["work_id"],
                "writing_system": item["writing_system"],
                "is_anchor": item["is_anchor"],
                "asset_path": item["asset"]["path"],
                "asset_sha256": item["asset"]["sha256"],
            }
            mismatched = sorted(key for key, value in expected.items() if trial.get(key) != value)
            if mismatched:
                errors.append(f"ASSIGNMENT_CATALOG_MISMATCH:{presentation_id}:{','.join(mismatched)}")
    events = {record["presentation_id"]: record for record in records["presentations"]}
    for presentation_id, event in events.items():
        link = trials.get(presentation_id)
        if link is None:
            errors.append(f"PRESENTATION_NOT_ASSIGNED:{presentation_id}")
            continue
        assignment, trial = link
        expected = {
            "study_id": assignment["study_id"],
            "assignment_id": assignment["assignment_id"],
            "participant_id": assignment["participant_id"],
            "data_origin": assignment["data_origin"],
            "stimulus_id": trial["stimulus_id"],
            "trial_index": trial["trial_index"],
            "expected_asset_sha256": trial["asset_sha256"],
        }
        if any(event.get(key) != value for key, value in expected.items()):
            errors.append(f"PRESENTATION_FOREIGN_KEY_MISMATCH:{presentation_id}")
        if event["load_status"] == "loaded" and event["displayed_asset_sha256"] != trial["asset_sha256"]:
            errors.append(f"PRESENTATION_DISPLAY_ASSET_MISMATCH:{presentation_id}")
    for rating in records["ratings"]:
        event = events.get(rating["presentation_id"])
        if event is None:
            errors.append(f"RATING_PRESENTATION_MISSING:{rating['rating_id']}")
            continue
        if any(
            rating.get(key) != event.get(key)
            for key in ("study_id", "assignment_id", "participant_id", "data_origin", "stimulus_id", "trial_index", "displayed_asset_sha256")
        ):
            errors.append(f"RATING_FOREIGN_KEY_MISMATCH:{rating['rating_id']}")
            continue
        profile = profiles.get(rating["participant_id"])
        assignment = assignments.get(rating["participant_id"])
        if profile is None or assignment is None:
            continue
        expected = {
            "questionnaire_version": assignment["questionnaire_version"],
            "block_id": assignment["block_id"],
            "respondent_language_bcp47": profile["questionnaire_language"],
            "native_scripts": profile["native_scripts"],
            "response_time_ms": event["response_ms"],
        }
        if any(rating.get(key) != value for key, value in expected.items()):
            errors.append(f"RATING_CONTEXT_MISMATCH:{rating['rating_id']}")
    ratings_by_presentation: dict[str, set[str]] = defaultdict(set)
    for rating in records["ratings"]:
        ratings_by_presentation[rating["presentation_id"]].add(rating["item_id"])
    for presentation_id in events:
        item_ids = ratings_by_presentation[presentation_id]
        missing_items = sorted(required_rating_item_ids - item_ids)
        unexpected_items = sorted(item_ids - required_rating_item_ids)
        if missing_items or unexpected_items:
            errors.append(
                f"RATING_ITEM_SET_MISMATCH:{presentation_id}:"
                f"missing={','.join(missing_items)};unexpected={','.join(unexpected_items)}"
            )
    definitions = {item["item_id"]: item for item in effective_questionnaire_items}
    for rating in records["ratings"]:
        definition = definitions.get(rating["item_id"])
        if definition is None or (
            rating["construct"] != definition["construct"]
            or rating["rating_scale"] != definition["response_type"]
        ):
            errors.append(f"RATING_QUESTIONNAIRE_MISMATCH:{rating['rating_id']}")
    decision_by_id = {record["decision_id"]: record for record in records["quality_decisions"]}
    for decision in records["quality_decisions"]:
        if decision["participant_id"] not in profiles:
            errors.append(f"QUALITY_PARTICIPANT_MISSING:{decision['decision_id']}")
    for participant_id in profiles:
        history = [record for record in records["quality_decisions"] if record["participant_id"] == participant_id]
        participant_events = {
            record["presentation_id"]: record
            for record in records["presentations"]
            if record["participant_id"] == participant_id
        }
        participant_ratings = [record for record in records["ratings"] if record["participant_id"] == participant_id]
        if participant_events and not history:
            errors.append(f"QUALITY_DECISION_MISSING:{participant_id}")
            continue
        roots = [record for record in history if record["previous_decision_id"] is None]
        if history and len(roots) != 1:
            errors.append(f"QUALITY_HISTORY_ROOT_INVALID:{participant_id}")
        children: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for decision in history:
            expected = {
                "study_id": profiles[participant_id]["study_id"],
                "data_origin": profiles[participant_id]["data_origin"],
            }
            if any(decision.get(key) != value for key, value in expected.items()):
                errors.append(f"QUALITY_CONTEXT_MISMATCH:{decision['decision_id']}")
            previous_id = decision["previous_decision_id"]
            if previous_id is not None and (
                previous_id not in decision_by_id
                or decision_by_id[previous_id]["participant_id"] != participant_id
            ):
                errors.append(f"QUALITY_HISTORY_LINK_INVALID:{decision['decision_id']}")
            elif previous_id is not None:
                children[previous_id].append(decision)
        if not history or len(roots) != 1:
            continue
        chain: list[dict[str, Any]] = []
        current = roots[0]
        visited: set[str] = set()
        while current["decision_id"] not in visited:
            chain.append(current)
            visited.add(current["decision_id"])
            next_decisions = children.get(current["decision_id"], [])
            if len(next_decisions) > 1:
                errors.append(f"QUALITY_HISTORY_BRANCH:{participant_id}:{current['decision_id']}")
                break
            if not next_decisions:
                break
            current = next_decisions[0]
        if len(visited) != len(history):
            errors.append(f"QUALITY_HISTORY_DISCONNECTED:{participant_id}")
        previous_sources: set[str] = set()
        decision_for_presentation: dict[str, dict[str, Any]] = {}
        for decision in chain:
            source_ids = set(decision["source_presentation_ids"])
            if not source_ids <= set(participant_events):
                errors.append(f"QUALITY_SOURCE_PRESENTATION_MISSING:{decision['decision_id']}")
                continue
            added_sources = source_ids - previous_sources
            if len(added_sources) != 1 or not previous_sources <= source_ids:
                errors.append(f"QUALITY_SOURCE_SEQUENCE_INVALID:{decision['decision_id']}")
            for presentation_id in added_sources:
                decision_for_presentation[presentation_id] = decision
            source_events = [participant_events[presentation_id] for presentation_id in source_ids]
            source_ratings = [rating for rating in participant_ratings if rating["presentation_id"] in source_ids]
            recomputed = build_quality_decision(
                profiles[participant_id],
                consents[participant_id],
                source_events,
                source_ratings,
                previous_decision_id=decision["previous_decision_id"],
                decided_at=decision["decided_at"],
            )
            for key in (
                "decision_id",
                "study_id",
                "participant_id",
                "data_origin",
                "rule_version",
                "exclude_from_analysis",
                "reason_codes",
                "source_presentation_ids",
                "previous_decision_id",
                "decided_at",
                "decision_basis",
            ):
                if decision[key] != recomputed[key]:
                    errors.append(f"QUALITY_DECISION_RECOMPUTE_MISMATCH:{participant_id}:{decision['decision_id']}:{key}")
            previous_sources = source_ids
        if previous_sources != set(participant_events):
            errors.append(f"QUALITY_HISTORY_PRESENTATION_SET_MISMATCH:{participant_id}")
        for rating in participant_ratings:
            decision = decision_for_presentation.get(rating["presentation_id"])
            if decision is None:
                errors.append(f"RATING_QUALITY_DECISION_MISSING:{rating['rating_id']}")
                continue
            expected_quality = {
                "rule_version": decision["rule_version"],
                "exclude_from_analysis": decision["exclude_from_analysis"],
                "reason_codes": decision["reason_codes"],
            }
            if rating["quality"] != expected_quality:
                errors.append(f"RATING_QUALITY_MISMATCH:{rating['rating_id']}")
    return errors


def _latest_quality_decisions(decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_participant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for decision in decisions:
        by_participant[decision["participant_id"]].append(decision)
    latest: dict[str, dict[str, Any]] = {}
    for participant_id, history in by_participant.items():
        referenced = {decision["previous_decision_id"] for decision in history if decision["previous_decision_id"] is not None}
        tails = [decision for decision in history if decision["decision_id"] not in referenced]
        if len(tails) == 1:
            latest[participant_id] = tails[0]
    return latest


def _require_quality_eligible(
    records: Mapping[str, list[dict[str, Any]]],
    *,
    purpose: str,
) -> None:
    if purpose not in {"formal_analysis", "release"}:
        return
    latest = _latest_quality_decisions(records["quality_decisions"])
    participant_ids = {profile["participant_id"] for profile in records["profiles"]}
    missing = sorted(participant_ids - set(latest))
    if missing:
        raise ExportBlocked("QUALITY_DECISION_MISSING", ",".join(missing))
    excluded = sorted(
        participant_id
        for participant_id, decision in latest.items()
        if decision["exclude_from_analysis"]
    )
    if excluded:
        raise ExportBlocked("QUALITY_EXCLUSION_PRESENT", ",".join(excluded))


def _manifest_declaration_errors(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    artifacts = manifest["artifacts"]
    record_types = [artifact["record_type"] for artifact in artifacts]
    if set(record_types) != set(BUNDLE_SPECS) or len(record_types) != len(set(record_types)):
        errors.append("ARTIFACT_RECORD_TYPE_SET_MISMATCH")
        return errors
    for artifact in artifacts:
        filename, schema_name, schema_version, _ = BUNDLE_SPECS[artifact["record_type"]]
        expected = {
            "path": filename,
            "schema": schema_name,
            "schema_version": schema_version,
        }
        mismatched = sorted(key for key, value in expected.items() if artifact.get(key) != value)
        if mismatched:
            errors.append(f"ARTIFACT_SPEC_MISMATCH:{artifact['record_type']}:{','.join(mismatched)}")
    return errors


def _manifest_content_errors(
    manifest: Mapping[str, Any],
    records: Mapping[str, list[dict[str, Any]]],
) -> list[str]:
    all_records = [record for rows in records.values() for record in rows]
    origins = sorted({record["data_origin"] for record in all_records})
    study_ids = {record["study_id"] for record in all_records}
    errors: list[str] = []
    if study_ids != {manifest["study_id"]}:
        errors.append("STUDY_ID_MISMATCH")
    if origins != manifest["data_origins"]:
        errors.append("DATA_ORIGINS_MISMATCH")
    if manifest["synthetic_only"] != (origins == ["synthetic"]):
        errors.append("SYNTHETIC_ONLY_MISMATCH")
    return errors


def validate_export_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    rating_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        schema_errors = validate_record(record, "experiment_rating.schema.json")
        errors.extend(f"line {index}: {error}" for error in schema_errors)
        leaked = sorted(_forbidden_keys(record))
        errors.extend(f"line {index}: FORBIDDEN_PII_KEY:{key}" for key in leaked)
        rating_id = record.get("rating_id")
        if rating_id in rating_ids:
            errors.append(f"line {index}: DUPLICATE_RATING_ID:{rating_id}")
        if isinstance(rating_id, str):
            rating_ids.add(rating_id)
    return errors


def read_and_validate_export(
    path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = validate_export_records(rows)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_EXPORT_INVALID", "; ".join(errors))
    require_export_eligible(rows, purpose=purpose, human_gates=human_gates)
    return rows


def _forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).lower() for key in value if str(key).lower() in FORBIDDEN_KEYS}
        return found | set().union(*(_forbidden_keys(child) for child in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_forbidden_keys(child) for child in value), set())
    return set()

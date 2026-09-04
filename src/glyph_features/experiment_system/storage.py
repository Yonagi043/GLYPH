"""Restricted local state for assignments and idempotent trial submissions."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from .assignment import build_assignments
from .quality import build_quality_decision
from .schema import canonical_sha256, require_frozen_study_id, validate_record


class StoreError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class ExperimentStore:
    def __init__(
        self,
        database_path: str | Path,
        *,
        study_id: str | None = None,
        catalog: list[dict[str, Any]] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        questionnaire_path = Path(__file__).resolve().parents[3] / "configs/questionnaire_v1.json"
        questionnaire = json.loads(questionnaire_path.read_text(encoding="utf-8"))
        self.study_id = study_id or questionnaire["study_id"]
        require_frozen_study_id(self.study_id, questionnaire["study_id"])
        self.questionnaire_version = questionnaire["questionnaire_version"]
        self.questionnaire_items = {
            item["item_id"]: item
            for item in questionnaire["items"]
        }
        self.required_rating_item_ids = {
            item["item_id"]
            for item in questionnaire["items"]
            if item["required"] and item["response_type"] in {"likert_1_7", "likert_1_5", "continuous_0_100"}
        }
        catalog_items = catalog if catalog is not None else list(_default_catalog_items(self.study_id))
        self.catalog_items = catalog_items
        self.catalog_by_id = {item["stimulus_id"]: item for item in catalog_items}
        if not catalog_items or len(self.catalog_by_id) != len(catalog_items):
            raise StoreError("STORE_CATALOG_INVALID", "catalog must contain unique stimuli")
        self.catalog_sha256 = canonical_sha256(sorted(catalog_items, key=lambda item: item["stimulus_id"]))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    participant_id TEXT PRIMARY KEY,
                    assignment_id TEXT NOT NULL UNIQUE,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS participant_profiles (
                    participant_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consent_receipts (
                    participant_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (participant_id) REFERENCES participant_profiles(participant_id)
                );
                CREATE TABLE IF NOT EXISTS session_requests (
                    session_nonce TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    participant_id TEXT NOT NULL UNIQUE,
                    assignment_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (participant_id) REFERENCES assignments(participant_id),
                    FOREIGN KEY (assignment_id) REFERENCES assignments(assignment_id)
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    request_id TEXT PRIMARY KEY,
                    presentation_id TEXT NOT NULL UNIQUE,
                    semantic_sha256 TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    rating_id TEXT PRIMARY KEY,
                    presentation_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (presentation_id, item_id)
                );
                CREATE TABLE IF NOT EXISTS quality_decisions (
                    decision_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    decision_sequence INTEGER NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (participant_id, decision_sequence),
                    FOREIGN KEY (participant_id) REFERENCES participant_profiles(participant_id)
                );
                CREATE TABLE IF NOT EXISTS submission_quality (
                    request_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (request_id) REFERENCES submissions(request_id),
                    FOREIGN KEY (decision_id) REFERENCES quality_decisions(decision_id)
                );
                INSERT INTO system_metadata(key, value) VALUES ('synthetic_only', 'true')
                    ON CONFLICT(key) DO NOTHING;
                """
            )
            connection.execute(
                "INSERT INTO system_metadata(key, value) VALUES ('study_id', ?) ON CONFLICT(key) DO NOTHING",
                (self.study_id,),
            )
            connection.execute(
                "INSERT INTO system_metadata(key, value) VALUES ('catalog_sha256', ?) ON CONFLICT(key) DO NOTHING",
                (self.catalog_sha256,),
            )
            mode = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'synthetic_only'"
            ).fetchone()[0]
            if mode != "true":
                raise StoreError("STORE_MODE_CONFLICT", f"synthetic_only={mode}")
            stored_study_id = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'study_id'"
            ).fetchone()[0]
            if stored_study_id != self.study_id:
                raise StoreError("STORE_STUDY_MISMATCH", f"{stored_study_id} != {self.study_id}")
            stored_catalog_sha256 = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'catalog_sha256'"
            ).fetchone()[0]
            if stored_catalog_sha256 != self.catalog_sha256:
                raise StoreError("STORE_CATALOG_MISMATCH", stored_catalog_sha256)

    def _validate_assignment(self, assignment: dict[str, Any]) -> None:
        errors = validate_record(assignment, "experiment_assignment.schema.json")
        if errors:
            raise StoreError("ASSIGNMENT_SCHEMA_INVALID", "; ".join(errors))
        if assignment["data_origin"] != "synthetic":
            raise StoreError("REAL_COLLECTION_LOCKED", "the TASK-03 store accepts synthetic assignments only")
        if assignment["study_id"] != self.study_id:
            raise StoreError("STUDY_ID_MISMATCH", f"{assignment['study_id']} != {self.study_id}")
        if assignment["questionnaire_version"] != self.questionnaire_version:
            raise StoreError(
                "QUESTIONNAIRE_VERSION_MISMATCH",
                f"{assignment['questionnaire_version']} != {self.questionnaire_version}",
            )
        for trial in assignment["trials"]:
            catalog_item = self.catalog_by_id.get(trial["stimulus_id"])
            if catalog_item is None:
                raise StoreError("ASSIGNMENT_STIMULUS_NOT_IN_CATALOG", trial["stimulus_id"])
            expected_metadata = {
                "source_stimulus_id": catalog_item["source_stimulus_id"],
                "work_id": catalog_item["work_id"],
                "writing_system": catalog_item["writing_system"],
                "is_anchor": catalog_item["is_anchor"],
                "asset_path": catalog_item["asset"]["path"],
                "asset_sha256": catalog_item["asset"]["sha256"],
            }
            mismatched = sorted(
                field for field, expected in expected_metadata.items() if trial.get(field) != expected
            )
            if mismatched:
                raise StoreError(
                    "ASSIGNMENT_CATALOG_MISMATCH",
                    f"{trial['stimulus_id']}:{','.join(mismatched)}",
                )

    def allocate_assignment(
        self,
        participant: dict[str, str],
        *,
        profile: dict[str, Any],
        consent: dict[str, Any],
        session_nonce: str,
        request_payload: dict[str, Any],
        seed: str,
        block_size: int,
        required_anchor_count: int,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        self._validate_profile_and_consent(profile, consent, participant)
        request_sha256 = canonical_sha256(request_payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_request = connection.execute(
                "SELECT request_sha256, participant_id FROM session_requests WHERE session_nonce = ?",
                (session_nonce,),
            ).fetchone()
            if existing_request is not None:
                if existing_request["request_sha256"] != request_sha256:
                    raise StoreError("SESSION_NONCE_CONFLICT", session_nonce)
                row = connection.execute(
                    "SELECT payload_json FROM assignments WHERE participant_id = ?",
                    (existing_request["participant_id"],),
                ).fetchone()
                if row is None:
                    raise StoreError("SESSION_ASSIGNMENT_MISSING", session_nonce)
                return json.loads(row["payload_json"]), False
            prior_assignments = [
                json.loads(row["payload_json"])
                for row in connection.execute(
                    "SELECT payload_json FROM assignments ORDER BY rowid"
                ).fetchall()
            ]
            assignment = build_assignments(
                [participant],
                self.catalog_items,
                study_id=self.study_id,
                questionnaire_version=self.questionnaire_version,
                seed=seed,
                block_size=block_size,
                required_anchor_count=required_anchor_count,
                created_at=created_at,
                prior_assignments=prior_assignments,
            )[0]
            self._validate_assignment(assignment)
            connection.execute(
                "INSERT INTO participant_profiles(participant_id, payload_sha256, payload_json) VALUES (?, ?, ?)",
                (profile["participant_id"], canonical_sha256(profile), _canonical_text(profile)),
            )
            connection.execute(
                "INSERT INTO consent_receipts(participant_id, payload_sha256, payload_json) VALUES (?, ?, ?)",
                (consent["participant_id"], canonical_sha256(consent), _canonical_text(consent)),
            )
            payload_json = _canonical_text(assignment)
            connection.execute(
                "INSERT INTO assignments(participant_id, assignment_id, payload_sha256, payload_json) VALUES (?, ?, ?, ?)",
                (
                    assignment["participant_id"],
                    assignment["assignment_id"],
                    canonical_sha256(assignment),
                    payload_json,
                ),
            )
            connection.execute(
                "INSERT INTO session_requests(session_nonce, request_sha256, participant_id, assignment_id) VALUES (?, ?, ?, ?)",
                (session_nonce, request_sha256, assignment["participant_id"], assignment["assignment_id"]),
            )
        return assignment, True

    def _validate_profile_and_consent(
        self,
        profile: dict[str, Any],
        consent: dict[str, Any],
        participant: dict[str, str],
    ) -> None:
        profile_errors = validate_record(profile, "participant_profile.schema.json")
        if profile_errors:
            raise StoreError("PROFILE_SCHEMA_INVALID", "; ".join(profile_errors))
        consent_errors = validate_record(consent, "consent_receipt.schema.json")
        if consent_errors:
            raise StoreError("CONSENT_SCHEMA_INVALID", "; ".join(consent_errors))
        expected = {
            "study_id": self.study_id,
            "participant_id": participant["participant_id"],
            "data_origin": "synthetic",
        }
        for record_name, record in (("profile", profile), ("consent", consent)):
            mismatched = [key for key, value in expected.items() if record.get(key) != value]
            if mismatched:
                raise StoreError("SESSION_FOREIGN_KEY_MISMATCH", f"{record_name}:{','.join(mismatched)}")
        if consent["questionnaire_version"] != self.questionnaire_version:
            raise StoreError("QUESTIONNAIRE_VERSION_MISMATCH", consent["questionnaire_version"])
        proficiency_scripts = [item["script"] for item in profile["script_proficiencies"]]
        if set(proficiency_scripts) != {"latin", "han", "kana", "hangul"} or len(proficiency_scripts) != 4:
            raise StoreError("PROFILE_SCRIPT_PROFICIENCIES_INVALID", repr(proficiency_scripts))
        mother_tongues = [item["bcp47"] for item in profile["mother_tongues"]]
        if len(mother_tongues) != len(set(mother_tongues)):
            raise StoreError("PROFILE_MOTHER_TONGUE_DUPLICATE", repr(mother_tongues))
        if not any(item["dominance"] in {"primary", "co_dominant"} for item in profile["mother_tongues"]):
            raise StoreError("PROFILE_DOMINANT_LANGUAGE_MISSING", profile["participant_id"])

    def save_assignment(self, assignment: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        self._validate_assignment(assignment)
        payload_json = _canonical_text(assignment)
        payload_sha256 = canonical_sha256(assignment)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_sha256, payload_json FROM assignments WHERE participant_id = ?",
                (assignment["participant_id"],),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != payload_sha256:
                    raise StoreError("ASSIGNMENT_CONFLICT", assignment["participant_id"])
                return json.loads(existing["payload_json"]), False
            connection.execute(
                "INSERT INTO assignments(participant_id, assignment_id, payload_sha256, payload_json) VALUES (?, ?, ?, ?)",
                (assignment["participant_id"], assignment["assignment_id"], payload_sha256, payload_json),
            )
        return assignment, True

    def assignment_for(self, participant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM assignments WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
        if row is None:
            raise StoreError("ASSIGNMENT_NOT_FOUND", participant_id)
        assignment = json.loads(row["payload_json"])
        if assignment.get("study_id") != self.study_id:
            raise StoreError("STORE_STUDY_MISMATCH", f"assignment {participant_id}")
        return self._with_resume_state(assignment)

    def profile_for(self, participant_id: str) -> dict[str, Any]:
        return self._participant_record("participant_profiles", participant_id, "PROFILE_NOT_FOUND")

    def consent_for(self, participant_id: str) -> dict[str, Any]:
        return self._participant_record("consent_receipts", participant_id, "CONSENT_NOT_FOUND")

    def _participant_record(self, table: str, participant_id: str, error_code: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE participant_id = ?",
                (participant_id,),
            ).fetchone()
        if row is None:
            raise StoreError(error_code, participant_id)
        return json.loads(row["payload_json"])

    def submit_trial(
        self,
        event: dict[str, Any],
        ratings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        client_ratings = [
            {key: value for key, value in rating.items() if key not in {"attention_check", "quality"}}
            for rating in ratings
        ]
        if event.get("data_origin") != "synthetic" or any(
            rating.get("data_origin") != "synthetic" for rating in client_ratings
        ):
            raise StoreError("REAL_COLLECTION_LOCKED", "the TASK-03 store accepts synthetic submissions only")
        event_errors = validate_record(event, "presentation_event.schema.json")
        attention_passed = event.get("attention_response") == "circle"
        server_ratings = [
            {**rating, "attention_check": attention_passed}
            for rating in client_ratings
        ]
        pending_quality = {"rule_version": "1.0.0", "exclude_from_analysis": True, "reason_codes": ["INCOMPLETE"]}
        rating_errors = [
            f"rating {index}: {error}"
            for index, rating in enumerate(server_ratings, start=1)
            for error in validate_record({**rating, "quality": pending_quality}, "experiment_rating.schema.json")
        ]
        if event_errors or rating_errors:
            raise StoreError("SUBMISSION_SCHEMA_INVALID", "; ".join([*event_errors, *rating_errors]))
        assignment = self.assignment_for(event["participant_id"])
        profile = self.profile_for(event["participant_id"])
        consent = self.consent_for(event["participant_id"])
        trial = next(
            (item for item in assignment["trials"] if item["presentation_id"] == event["presentation_id"]),
            None,
        )
        if trial is None:
            raise StoreError("PRESENTATION_NOT_ASSIGNED", event["presentation_id"])
        expected = {
            "study_id": assignment["study_id"],
            "assignment_id": assignment["assignment_id"],
            "participant_id": assignment["participant_id"],
            "data_origin": assignment["data_origin"],
            "stimulus_id": trial["stimulus_id"],
            "trial_index": trial["trial_index"],
            "expected_asset_sha256": trial["asset_sha256"],
        }
        for key, value in expected.items():
            if event.get(key) != value:
                raise StoreError("SUBMISSION_FOREIGN_KEY_MISMATCH", f"{key}: {event.get(key)!r} != {value!r}")
        if event["load_status"] != "loaded" or event["displayed_asset_sha256"] != trial["asset_sha256"]:
            raise StoreError("DISPLAY_ASSET_NOT_VERIFIED", event["presentation_id"])
        if not ratings:
            raise StoreError("SUBMISSION_RATINGS_EMPTY", event["presentation_id"])
        item_ids = [rating.get("item_id") for rating in server_ratings]
        if len(item_ids) != len(set(item_ids)):
            raise StoreError("DUPLICATE_RATING_ITEM", event["presentation_id"])
        missing_items = sorted(self.required_rating_item_ids - set(item_ids))
        unexpected_items = sorted(set(item_ids) - self.required_rating_item_ids)
        if missing_items or unexpected_items:
            raise StoreError(
                "RATING_ITEM_SET_MISMATCH",
                f"missing={','.join(missing_items)};unexpected={','.join(unexpected_items)}",
            )
        rating_ids = [rating.get("rating_id") for rating in server_ratings]
        if len(rating_ids) != len(set(rating_ids)):
            raise StoreError("DUPLICATE_RATING_ID", event["presentation_id"])
        for rating in server_ratings:
            for key, value in {
                "study_id": assignment["study_id"],
                "questionnaire_version": assignment["questionnaire_version"],
                "assignment_id": assignment["assignment_id"],
                "block_id": assignment["block_id"],
                "participant_id": assignment["participant_id"],
                "presentation_id": trial["presentation_id"],
                "stimulus_id": trial["stimulus_id"],
                "trial_index": trial["trial_index"],
                "displayed_asset_sha256": trial["asset_sha256"],
                "data_origin": assignment["data_origin"],
                "respondent_language_bcp47": profile["questionnaire_language"],
                "native_scripts": profile["native_scripts"],
                "response_time_ms": event["response_ms"],
            }.items():
                if rating.get(key) != value:
                    raise StoreError("RATING_FOREIGN_KEY_MISMATCH", f"{key}: {rating.get(key)!r} != {value!r}")
            definition = self.questionnaire_items.get(rating["item_id"])
            if definition is None:
                raise StoreError("QUESTIONNAIRE_ITEM_NOT_FOUND", rating["item_id"])
            if rating["construct"] != definition["construct"]:
                raise StoreError(
                    "QUESTIONNAIRE_CONSTRUCT_MISMATCH",
                    f"{rating['item_id']}: {rating['construct']} != {definition['construct']}",
                )
            if rating["rating_scale"] != definition["response_type"]:
                raise StoreError(
                    "QUESTIONNAIRE_SCALE_MISMATCH",
                    f"{rating['item_id']}: {rating['rating_scale']} != {definition['response_type']}",
                )
        semantic = {
            "event": {key: value for key, value in event.items() if key not in {"event_id", "request_id"}},
            "ratings": client_ratings,
        }
        semantic_sha256 = canonical_sha256(semantic)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            request_row = connection.execute(
                "SELECT semantic_sha256 FROM submissions WHERE request_id = ?",
                (event["request_id"],),
            ).fetchone()
            if request_row is not None:
                if request_row["semantic_sha256"] != semantic_sha256:
                    raise StoreError("REQUEST_ID_CONFLICT", event["request_id"])
                return self._duplicate_submission_result(connection, event["request_id"], event["presentation_id"])
            presentation_row = connection.execute(
                "SELECT request_id, semantic_sha256 FROM submissions WHERE presentation_id = ?",
                (event["presentation_id"],),
            ).fetchone()
            if presentation_row is not None:
                if presentation_row["semantic_sha256"] != semantic_sha256:
                    raise StoreError("PRESENTATION_SUBMISSION_CONFLICT", event["presentation_id"])
                return self._duplicate_submission_result(
                    connection,
                    presentation_row["request_id"],
                    event["presentation_id"],
                )
            for rating_id in rating_ids:
                if connection.execute(
                    "SELECT 1 FROM ratings WHERE rating_id = ?",
                    (rating_id,),
                ).fetchone() is not None:
                    raise StoreError("RATING_ID_CONFLICT", str(rating_id))
            previous_row = connection.execute(
                "SELECT decision_id, decision_sequence, payload_json FROM quality_decisions WHERE participant_id = ? ORDER BY decision_sequence DESC LIMIT 1",
                (event["participant_id"],),
            ).fetchone()
            prior_events = [
                json.loads(row["event_json"])
                for row in connection.execute("SELECT event_json FROM submissions").fetchall()
                if json.loads(row["event_json"]).get("participant_id") == event["participant_id"]
            ]
            prior_ratings = [
                json.loads(row["payload_json"])
                for row in connection.execute("SELECT payload_json FROM ratings").fetchall()
                if json.loads(row["payload_json"]).get("participant_id") == event["participant_id"]
            ]
            decision = build_quality_decision(
                profile,
                consent,
                [*prior_events, event],
                [*prior_ratings, *server_ratings],
                previous_decision_id=previous_row["decision_id"] if previous_row else None,
                decided_at=event["ended_at"],
            )
            server_quality = {
                "rule_version": decision["rule_version"],
                "exclude_from_analysis": decision["exclude_from_analysis"],
                "reason_codes": decision["reason_codes"],
            }
            canonical_ratings = [{**rating, "quality": server_quality} for rating in server_ratings]
            connection.execute(
                "INSERT INTO submissions(request_id, presentation_id, semantic_sha256, event_json) VALUES (?, ?, ?, ?)",
                (event["request_id"], event["presentation_id"], semantic_sha256, _canonical_text(event)),
            )
            for rating in canonical_ratings:
                connection.execute(
                    "INSERT INTO ratings(rating_id, presentation_id, item_id, payload_json) VALUES (?, ?, ?, ?)",
                    (rating["rating_id"], rating["presentation_id"], rating["item_id"], _canonical_text(rating)),
                )
            decision_sequence = previous_row["decision_sequence"] + 1 if previous_row else 1
            connection.execute(
                "INSERT INTO quality_decisions(decision_id, participant_id, decision_sequence, payload_sha256, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    decision["decision_id"],
                    decision["participant_id"],
                    decision_sequence,
                    canonical_sha256(decision),
                    _canonical_text(decision),
                ),
            )
            connection.execute(
                "INSERT INTO submission_quality(request_id, decision_id) VALUES (?, ?)",
                (event["request_id"], decision["decision_id"]),
            )
        return {"status": "accepted", "presentation_id": event["presentation_id"], "quality_decision": decision}

    def _duplicate_submission_result(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        presentation_id: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT quality_decisions.payload_json FROM submission_quality JOIN quality_decisions USING(decision_id) WHERE submission_quality.request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise StoreError("SUBMISSION_QUALITY_LINK_MISSING", request_id)
        return {
            "status": "duplicate",
            "presentation_id": presentation_id,
            "quality_decision": json.loads(row["payload_json"]),
        }

    def latest_quality_decision(self, participant_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM quality_decisions WHERE participant_id = ? ORDER BY decision_sequence DESC LIMIT 1",
                (participant_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row is not None else None

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "profiles": connection.execute("SELECT COUNT(*) FROM participant_profiles").fetchone()[0],
                "consents": connection.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0],
                "assignments": connection.execute("SELECT COUNT(*) FROM assignments").fetchone()[0],
                "presentations": connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
                "ratings": connection.execute("SELECT COUNT(*) FROM ratings").fetchone()[0],
                "quality_decisions": connection.execute("SELECT COUNT(*) FROM quality_decisions").fetchone()[0],
            }

    def system_status(self) -> dict[str, Any]:
        with self._connect() as connection:
            mode = connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'synthetic_only'"
            ).fetchone()[0]
        return {
            "synthetic_only": mode == "true",
            "study_id": self.study_id,
            "questionnaire_version": self.questionnaire_version,
        }

    def deidentified_ratings(self, *, study_id: str) -> list[dict[str, Any]]:
        return self.deidentified_records(study_id=study_id)["ratings"]

    def deidentified_records(self, *, study_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            sources = {
                "profiles": connection.execute("SELECT payload_json FROM participant_profiles ORDER BY participant_id").fetchall(),
                "consents": connection.execute("SELECT payload_json FROM consent_receipts ORDER BY participant_id").fetchall(),
                "assignments": connection.execute("SELECT payload_json FROM assignments").fetchall(),
                "presentations": connection.execute("SELECT event_json FROM submissions ORDER BY presentation_id").fetchall(),
                "ratings": connection.execute("SELECT payload_json FROM ratings ORDER BY rating_id").fetchall(),
                "quality_decisions": connection.execute(
                    "SELECT payload_json FROM quality_decisions ORDER BY participant_id, decision_sequence"
                ).fetchall(),
            }
        records = {
            source: [json.loads(row[0]) for row in rows]
            for source, rows in sources.items()
        }
        mismatched = sorted(
            source
            for source, rows in records.items()
            if any(row.get("study_id") != study_id for row in rows)
        )
        if mismatched:
            raise StoreError("DATABASE_STUDY_MISMATCH", ",".join(mismatched))
        return records

    def presentation_events(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT event_json FROM submissions ORDER BY presentation_id").fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def _with_resume_state(self, assignment: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            submitted = {
                row[0]
                for row in connection.execute("SELECT presentation_id FROM submissions").fetchall()
            }
        remaining = [trial["trial_index"] for trial in assignment["trials"] if trial["presentation_id"] not in submitted]
        result = dict(assignment)
        if remaining:
            result["resume_next_trial"] = min(remaining)
            result["status"] = "in_progress" if len(remaining) < len(assignment["trials"]) else "assigned"
        else:
            result["resume_next_trial"] = len(assignment["trials"]) + 1
            result["status"] = "completed"
        return result


def _canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=4)
def _default_catalog_items(study_id: str) -> tuple[dict[str, Any], ...]:
    from .fixtures import build_synthetic_catalog

    return tuple(build_synthetic_catalog(study_id=study_id)["items"])
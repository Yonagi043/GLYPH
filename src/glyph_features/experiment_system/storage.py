"""Restricted local state for assignments and idempotent trial submissions."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

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
        catalog_items = catalog if catalog is not None else list(_default_catalog_items(self.study_id))
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

    def save_assignment(self, assignment: dict[str, Any]) -> tuple[dict[str, Any], bool]:
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

    def submit_trial(
        self,
        event: dict[str, Any],
        ratings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if event.get("data_origin") != "synthetic" or any(
            rating.get("data_origin") != "synthetic" for rating in ratings
        ):
            raise StoreError("REAL_COLLECTION_LOCKED", "the TASK-03 store accepts synthetic submissions only")
        event_errors = validate_record(event, "presentation_event.schema.json")
        rating_errors = [
            f"rating {index}: {error}"
            for index, rating in enumerate(ratings, start=1)
            for error in validate_record(rating, "experiment_rating.schema.json")
        ]
        if event_errors or rating_errors:
            raise StoreError("SUBMISSION_SCHEMA_INVALID", "; ".join([*event_errors, *rating_errors]))
        assignment = self.assignment_for(event["participant_id"])
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
        item_ids = [rating.get("item_id") for rating in ratings]
        if len(item_ids) != len(set(item_ids)):
            raise StoreError("DUPLICATE_RATING_ITEM", event["presentation_id"])
        rating_ids = [rating.get("rating_id") for rating in ratings]
        if len(rating_ids) != len(set(rating_ids)):
            raise StoreError("DUPLICATE_RATING_ID", event["presentation_id"])
        for rating in ratings:
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
            "ratings": ratings,
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
                return {"status": "duplicate", "presentation_id": event["presentation_id"]}
            presentation_row = connection.execute(
                "SELECT semantic_sha256 FROM submissions WHERE presentation_id = ?",
                (event["presentation_id"],),
            ).fetchone()
            if presentation_row is not None:
                if presentation_row["semantic_sha256"] != semantic_sha256:
                    raise StoreError("PRESENTATION_SUBMISSION_CONFLICT", event["presentation_id"])
                return {"status": "duplicate", "presentation_id": event["presentation_id"]}
            for rating_id in rating_ids:
                if connection.execute(
                    "SELECT 1 FROM ratings WHERE rating_id = ?",
                    (rating_id,),
                ).fetchone() is not None:
                    raise StoreError("RATING_ID_CONFLICT", str(rating_id))
            connection.execute(
                "INSERT INTO submissions(request_id, presentation_id, semantic_sha256, event_json) VALUES (?, ?, ?, ?)",
                (event["request_id"], event["presentation_id"], semantic_sha256, _canonical_text(event)),
            )
            for rating in ratings:
                connection.execute(
                    "INSERT INTO ratings(rating_id, presentation_id, item_id, payload_json) VALUES (?, ?, ?, ?)",
                    (rating["rating_id"], rating["presentation_id"], rating["item_id"], _canonical_text(rating)),
                )
        return {"status": "accepted", "presentation_id": event["presentation_id"]}

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "assignments": connection.execute("SELECT COUNT(*) FROM assignments").fetchone()[0],
                "presentations": connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0],
                "ratings": connection.execute("SELECT COUNT(*) FROM ratings").fetchone()[0],
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
        with self._connect() as connection:
            sources = {
                "assignments": connection.execute("SELECT payload_json FROM assignments").fetchall(),
                "submissions": connection.execute("SELECT event_json FROM submissions").fetchall(),
                "ratings": connection.execute("SELECT payload_json FROM ratings ORDER BY rating_id").fetchall(),
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
        return records["ratings"]

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
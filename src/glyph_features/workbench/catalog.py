"""Pointer-only SQLite catalog for the composed GLYPH workbench."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from glyph_features.asset_system.catalog import canonical_json, normalize_repo_path, stable_id


CATALOG_SCHEMA_VERSION = "1.0.0"


class CatalogError(ValueError):
    """Base class for catalog contract failures."""


class CatalogRoleError(CatalogError):
    """Raised before migration when the target is not a workbench catalog."""


class CatalogConflict(CatalogError):
    """Raised when an immutable catalog slot is presented with new content."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return canonical_json(value).decode("utf-8")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workbench_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS modules (
    module_id TEXT PRIMARY KEY,
    module_version TEXT NOT NULL,
    descriptor_sha256 TEXT NOT NULL,
    descriptor_json TEXT NOT NULL,
    health TEXT NOT NULL CHECK (health IN ('ready', 'degraded', 'blocked', 'absent')),
    engineering_ready INTEGER NOT NULL CHECK (engineering_ready IN (0, 1)),
    pilot_ready INTEGER NOT NULL CHECK (pilot_ready IN (0, 1)),
    research_validated INTEGER NOT NULL CHECK (research_validated IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS handoff_imports (
    handoff_import_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    module_id TEXT NOT NULL REFERENCES modules(module_id),
    manifest_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL CHECK (length(manifest_sha256) = 64),
    handoff_schema_version TEXT NOT NULL,
    producer_commit TEXT NOT NULL CHECK (length(producer_commit) = 40),
    validation_status TEXT NOT NULL,
    compatible INTEGER NOT NULL CHECK (compatible IN (0, 1)),
    compatibility_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (task_id, manifest_path)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    module_id TEXT NOT NULL REFERENCES modules(module_id),
    logical_type TEXT NOT NULL,
    uri TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    schema_version TEXT,
    data_classification TEXT NOT NULL,
    rights_tier TEXT,
    privacy_level TEXT,
    pointer_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (module_id, logical_type, uri, sha256)
);

CREATE TABLE IF NOT EXISTS entity_links (
    link_id TEXT PRIMARY KEY,
    source_module TEXT NOT NULL REFERENCES modules(module_id),
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    target_module TEXT NOT NULL REFERENCES modules(module_id),
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    evidence_artifact_id TEXT REFERENCES artifacts(artifact_id),
    link_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_module, source_type, source_id, target_module, target_type, target_id, relation)
);

CREATE TABLE IF NOT EXISTS gate_decisions (
    gate_decision_id TEXT PRIMARY KEY,
    gate_id TEXT NOT NULL,
    status TEXT NOT NULL,
    scope TEXT NOT NULL,
    decision_ref TEXT,
    evidence_json TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_plans (
    plan_revision_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_sha256 TEXT NOT NULL CHECK (length(plan_sha256) = 64),
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (plan_id, version)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_run_id TEXT PRIMARY KEY,
    plan_revision_id TEXT NOT NULL REFERENCES analysis_plans(plan_revision_id),
    snapshot_sha256 TEXT NOT NULL CHECK (length(snapshot_sha256) = 64),
    status TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS release_candidates (
    release_candidate_id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(analysis_run_id),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    blockers_json TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
"""


class Catalog:
    """Small catalog that owns metadata, pointers, snapshots, and audit only."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with sqlite3.connect(self.database_path, timeout=10) as connection:
            existing_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if existing_tables and "workbench_metadata" not in existing_tables:
                raise CatalogRoleError(
                    "CATALOG_DATABASE_ROLE_MISMATCH: target contains non-workbench tables"
                )
            if "workbench_metadata" in existing_tables:
                row = connection.execute(
                    "SELECT schema_version FROM workbench_metadata WHERE singleton = 1"
                ).fetchone()
                if row is None or row[0] != CATALOG_SCHEMA_VERSION:
                    actual = None if row is None else row[0]
                    raise CatalogRoleError(
                        f"CATALOG_SCHEMA_UNSUPPORTED: expected {CATALOG_SCHEMA_VERSION}, got {actual}"
                    )
            connection.executescript(SCHEMA_SQL)
            if not existing_tables:
                connection.execute(
                    "INSERT INTO workbench_metadata(singleton, schema_version, created_at) VALUES (1, ?, ?)",
                    (CATALOG_SCHEMA_VERSION, _utc_now()),
                )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        event_type: str,
        object_type: str,
        object_id: str,
        summary: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(event_type, object_type, object_id, summary_json, occurred_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, object_type, object_id, _json(summary), _utc_now()),
        )

    def register_modules(self, descriptors: Iterable[dict[str, Any]]) -> None:
        with self._connect() as connection:
            for descriptor in descriptors:
                required = {"module_id", "module_version", "health", "readiness"}
                missing = required.difference(descriptor)
                if missing:
                    raise CatalogError(f"MODULE_DESCRIPTOR_MISSING:{','.join(sorted(missing))}")
                readiness = descriptor["readiness"]
                descriptor_sha256 = hashlib.sha256(canonical_json(descriptor)).hexdigest()
                existing = connection.execute(
                    "SELECT descriptor_sha256 FROM modules WHERE module_id = ?",
                    (descriptor["module_id"],),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO modules(
                        module_id, module_version, descriptor_sha256, descriptor_json, health,
                        engineering_ready, pilot_ready, research_validated, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(module_id) DO UPDATE SET
                        module_version = excluded.module_version,
                        descriptor_sha256 = excluded.descriptor_sha256,
                        descriptor_json = excluded.descriptor_json,
                        health = excluded.health,
                        engineering_ready = excluded.engineering_ready,
                        pilot_ready = excluded.pilot_ready,
                        research_validated = excluded.research_validated,
                        updated_at = excluded.updated_at
                    """,
                    (
                        descriptor["module_id"],
                        descriptor["module_version"],
                        descriptor_sha256,
                        _json(descriptor),
                        descriptor["health"],
                        int(readiness.get("engineering_ready") is True),
                        int(readiness.get("pilot_ready") is True),
                        int(readiness.get("research_validated") is True),
                        _utc_now(),
                    ),
                )
                if existing is None or existing[0] != descriptor_sha256:
                    self._audit(
                        connection,
                        "module_registered" if existing is None else "module_status_changed",
                        "module",
                        descriptor["module_id"],
                        {"descriptor_sha256": descriptor_sha256, "health": descriptor["health"]},
                    )

    def register_handoff(self, result: dict[str, Any]) -> str:
        required = {
            "task_id",
            "module_id",
            "manifest_path",
            "manifest_sha256",
            "handoff_schema_version",
            "producer_commit",
            "validation_status",
            "compatible",
        }
        missing = required.difference(result)
        if missing:
            raise CatalogError(f"HANDOFF_RESULT_MISSING:{','.join(sorted(missing))}")
        handoff_id = stable_id(
            "handoff",
            {
                "task_id": result["task_id"],
                "manifest_sha256": result["manifest_sha256"],
            },
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT handoff_import_id, manifest_sha256
                FROM handoff_imports WHERE task_id = ? AND manifest_path = ?
                """,
                (result["task_id"], result["manifest_path"]),
            ).fetchone()
            if existing is not None:
                if existing["manifest_sha256"] != result["manifest_sha256"]:
                    raise CatalogConflict(
                        "HANDOFF_IMMUTABLE_CONFLICT: the registered manifest path changed hash"
                    )
                return str(existing["handoff_import_id"])
            connection.execute(
                """
                INSERT INTO handoff_imports(
                    handoff_import_id, task_id, module_id, manifest_path, manifest_sha256,
                    handoff_schema_version, producer_commit, validation_status, compatible,
                    compatibility_json, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handoff_id,
                    result["task_id"],
                    result["module_id"],
                    result["manifest_path"],
                    result["manifest_sha256"],
                    result["handoff_schema_version"],
                    result["producer_commit"],
                    result["validation_status"],
                    int(result["compatible"] is True),
                    _json(result),
                    _utc_now(),
                ),
            )
            self._audit(
                connection,
                "handoff_registered",
                "handoff_import",
                handoff_id,
                {
                    "task_id": result["task_id"],
                    "manifest_path": result["manifest_path"],
                    "manifest_sha256": result["manifest_sha256"],
                },
            )
        return handoff_id

    def register_artifact(self, pointer: dict[str, Any]) -> str:
        """Register a safe artifact pointer, never an artifact payload."""

        required = {"module_id", "logical_type", "sha256", "data_classification"}
        missing = required.difference(pointer)
        if missing:
            raise CatalogError(f"ARTIFACT_POINTER_MISSING:{','.join(sorted(missing))}")
        if ("path" in pointer) == ("uri" in pointer):
            raise CatalogError("ARTIFACT_LOCATION_AMBIGUOUS")
        if "path" in pointer:
            try:
                location = normalize_repo_path(pointer["path"])
            except (TypeError, ValueError) as error:
                raise CatalogError("ARTIFACT_PATH_NOT_CANONICAL") from error
            if location != pointer["path"]:
                raise CatalogError("ARTIFACT_PATH_NOT_CANONICAL")
            location_key = "path"
        else:
            location = str(pointer["uri"])
            if not re.fullmatch(
                r"(?:social-export|workbench-output)://[A-Za-z0-9._/-]+",
                location,
            ) or ".." in location:
                raise CatalogError("ARTIFACT_URI_NOT_ALLOWED")
            location_key = "uri"
        digest = str(pointer["sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise CatalogError("ARTIFACT_SHA256_INVALID")
        safe_pointer = {
            key: pointer.get(key)
            for key in (
                "module_id",
                "logical_type",
                "sha256",
                "schema_version",
                "data_classification",
                "rights_tier",
                "privacy_level",
                "record_count",
                "validation_schema",
                "source_handoff_id",
            )
            if pointer.get(key) is not None
        }
        safe_pointer[location_key] = location
        artifact_id = stable_id(
            "artifact",
            {
                "module_id": pointer["module_id"],
                "logical_type": pointer["logical_type"],
                "location": location,
                "sha256": digest,
            },
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT pointer_json FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            pointer_json = _json(safe_pointer)
            if existing is not None:
                if existing["pointer_json"] != pointer_json:
                    raise CatalogConflict("ARTIFACT_IMMUTABLE_CONFLICT")
                return artifact_id
            connection.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, module_id, logical_type, uri, sha256, schema_version,
                    data_classification, rights_tier, privacy_level, pointer_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    pointer["module_id"],
                    pointer["logical_type"],
                    location,
                    digest,
                    pointer.get("schema_version"),
                    pointer["data_classification"],
                    pointer.get("rights_tier"),
                    pointer.get("privacy_level"),
                    pointer_json,
                    _utc_now(),
                ),
            )
            self._audit(
                connection,
                "artifact_registered",
                "artifact",
                artifact_id,
                {"logical_type": pointer["logical_type"], "uri": location, "sha256": digest},
            )
        return artifact_id

    def register_entity_link(self, link: dict[str, Any]) -> str:
        required = {
            "source_module",
            "source_type",
            "source_id",
            "target_module",
            "target_type",
            "target_id",
            "relation",
        }
        missing = required.difference(link)
        if missing:
            raise CatalogError(f"ENTITY_LINK_MISSING:{','.join(sorted(missing))}")
        if any(not isinstance(link[key], str) or not link[key] for key in required):
            raise CatalogError("ENTITY_LINK_VALUE_INVALID")
        stable_fields = {key: link[key] for key in sorted(required)}
        safe_link = {
            **stable_fields,
            "evidence_artifact_id": link.get("evidence_artifact_id"),
            "analysis_boundary": link.get("analysis_boundary"),
            "cluster_id": link.get("cluster_id"),
        }
        link_id = stable_id("link", stable_fields)
        link_json = _json(safe_link)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT link_json FROM entity_links WHERE link_id = ?",
                (link_id,),
            ).fetchone()
            if existing is not None:
                if existing["link_json"] != link_json:
                    raise CatalogConflict("ENTITY_LINK_IMMUTABLE_CONFLICT")
                return link_id
            connection.execute(
                """
                INSERT INTO entity_links(
                    link_id, source_module, source_type, source_id, target_module,
                    target_type, target_id, relation, evidence_artifact_id, link_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link_id,
                    link["source_module"],
                    link["source_type"],
                    link["source_id"],
                    link["target_module"],
                    link["target_type"],
                    link["target_id"],
                    link["relation"],
                    link.get("evidence_artifact_id"),
                    link_json,
                    _utc_now(),
                ),
            )
            self._audit(
                connection,
                "entity_link_registered",
                "entity_link",
                link_id,
                stable_fields,
            )
        return link_id

    def register_analysis_plan(self, plan: dict[str, Any]) -> dict[str, str]:
        plan_sha256 = hashlib.sha256(canonical_json(plan)).hexdigest()
        revision_id = stable_id(
            "planrev",
            {"plan_id": plan["plan_id"], "version": plan["version"], "sha256": plan_sha256},
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT plan_revision_id, plan_sha256 FROM analysis_plans
                WHERE plan_id = ? AND version = ?
                """,
                (plan["plan_id"], plan["version"]),
            ).fetchone()
            if existing is not None:
                if existing["plan_sha256"] != plan_sha256:
                    raise CatalogConflict("ANALYSIS_PLAN_IMMUTABLE_CONFLICT")
                return {
                    "plan_revision_id": str(existing["plan_revision_id"]),
                    "plan_sha256": plan_sha256,
                }
            connection.execute(
                """
                INSERT INTO analysis_plans(
                    plan_revision_id, plan_id, version, status, plan_sha256, plan_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    plan["plan_id"],
                    plan["version"],
                    plan["status"],
                    plan_sha256,
                    _json(plan),
                    _utc_now(),
                ),
            )
            self._audit(
                connection,
                "analysis_plan_frozen",
                "analysis_plan",
                revision_id,
                {"plan_id": plan["plan_id"], "version": plan["version"], "sha256": plan_sha256},
            )
        return {"plan_revision_id": revision_id, "plan_sha256": plan_sha256}

    def analysis_plan(self, plan_revision_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_plans WHERE plan_revision_id = ?",
                (plan_revision_id,),
            ).fetchone()
        if row is None:
            raise KeyError(plan_revision_id)
        result = dict(row)
        result["plan"] = json.loads(result.pop("plan_json"))
        return result

    def register_analysis_run(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT snapshot_json, snapshot_sha256 FROM analysis_runs WHERE analysis_run_id = ?",
                (snapshot["analysis_run_id"],),
            ).fetchone()
            if existing is not None:
                if existing["snapshot_sha256"] != snapshot["snapshot_sha256"]:
                    raise CatalogConflict("ANALYSIS_SNAPSHOT_IMMUTABLE_CONFLICT")
                return json.loads(existing["snapshot_json"])
            connection.execute(
                """
                INSERT INTO analysis_runs(
                    analysis_run_id, plan_revision_id, snapshot_sha256, status,
                    data_origin, snapshot_json, result_json, created_at, completed_at
                ) VALUES (?, ?, ?, 'snapshot_frozen', ?, ?, NULL, ?, NULL)
                """,
                (
                    snapshot["analysis_run_id"],
                    snapshot["plan_revision_id"],
                    snapshot["snapshot_sha256"],
                    snapshot["data_origin"],
                    _json(snapshot),
                    snapshot["created_at"],
                ),
            )
            self._audit(
                connection,
                "analysis_snapshot_frozen",
                "analysis_run",
                snapshot["analysis_run_id"],
                {"snapshot_sha256": snapshot["snapshot_sha256"], "data_origin": snapshot["data_origin"]},
            )
        return snapshot

    def complete_analysis_run(
        self,
        analysis_run_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> None:
        result_json = _json(result)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT result_json FROM analysis_runs WHERE analysis_run_id = ?",
                (analysis_run_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(analysis_run_id)
            if existing["result_json"] is not None:
                if existing["result_json"] != result_json:
                    raise CatalogConflict("ANALYSIS_RESULT_IMMUTABLE_CONFLICT")
                return
            connection.execute(
                """
                UPDATE analysis_runs SET status = ?, result_json = ?, completed_at = ?
                WHERE analysis_run_id = ?
                """,
                (status, result_json, _utc_now(), analysis_run_id),
            )
            self._audit(
                connection,
                "analysis_run_completed",
                "analysis_run",
                analysis_run_id,
                {"status": status, "result_sha256": hashlib.sha256(result_json.encode()).hexdigest()},
            )

    def analysis_run(self, analysis_run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_runs WHERE analysis_run_id = ?",
                (analysis_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(analysis_run_id)
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        result["result"] = (
            None if result["result_json"] is None else json.loads(result.pop("result_json"))
        )
        if "result_json" in result:
            result.pop("result_json")
        return result

    def register_release_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        candidate_json = _json(candidate)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT manifest_json FROM release_candidates WHERE release_candidate_id = ?",
                (candidate["release_candidate_id"],),
            ).fetchone()
            if existing is not None:
                if existing["manifest_json"] != candidate_json:
                    raise CatalogConflict("RELEASE_CANDIDATE_IMMUTABLE_CONFLICT")
                return json.loads(existing["manifest_json"])
            connection.execute(
                """
                INSERT INTO release_candidates(
                    release_candidate_id, analysis_run_id, purpose, status,
                    blockers_json, manifest_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate["release_candidate_id"],
                    candidate["analysis_run_id"],
                    candidate["purpose"],
                    candidate["status"],
                    _json(candidate["formal_blockers"]),
                    candidate_json,
                    candidate["created_at"],
                ),
            )
            self._audit(
                connection,
                "release_candidate_evaluated",
                "release_candidate",
                candidate["release_candidate_id"],
                {
                    "purpose": candidate["purpose"],
                    "status": candidate["status"],
                    "blocker_codes": [
                        blocker["code"] for blocker in candidate["formal_blockers"]
                    ],
                },
            )
        return candidate

    def table_names(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def rows(self, table: str) -> list[dict[str, Any]]:
        allowed = {
            "modules",
            "handoff_imports",
            "artifacts",
            "entity_links",
            "gate_decisions",
            "analysis_plans",
            "analysis_runs",
            "release_candidates",
            "audit_events",
        }
        if table not in allowed:
            raise CatalogError(f"CATALOG_TABLE_NOT_PUBLIC:{table}")
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]

    def entity_links(self, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM entity_links
                WHERE source_id = ? OR target_id = ?
                ORDER BY source_type, source_id, relation, target_type, target_id
                """,
                (entity_id, entity_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def integrity_check(self) -> str:
        with self._connect() as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
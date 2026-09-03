"""SQLite persistence for the local social-narrative system."""

from __future__ import annotations

import json
import sqlite3
import threading
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 17
MIGRATION_LOCK = threading.Lock()
YOUTUBE_QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
YOUTUBE_QUOTA_POLICY = "youtube_data_api_2026-06-01"
LEGACY_YOUTUBE_QUOTA_POLICY = "legacy_pre_2026-06-01"
TIKTOK_QUOTA_POLICY = "tiktok_research_api_2026-09-01"
X_PRICING_POLICY = "x_pay_per_use_2026-09-02"


class XBillingGateError(ValueError):
    pass


class XBudgetExceeded(ValueError):
    def __init__(self, message: str, *, budget_scope: str):
        super().__init__(message)
        self.budget_scope = budget_scope


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _microusd_text(value: int) -> str:
    dollars, fraction = divmod(value, 1_000_000)
    suffix = f"{fraction:06d}".rstrip("0")
    return f"{dollars}.{suffix}" if suffix else str(dollars)


def _utc_timestamp(value: str, *, field: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} 必须是 ISO-8601 UTC 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} 必须使用 UTC")
    return parsed.astimezone(timezone.utc)


class ResearchStore:
    """Own the local database connection and its forward-only migrations."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        with MIGRATION_LOCK:
            self.connection.execute("PRAGMA journal_mode = WAL")
            self._migrate()

    def __enter__(self) -> ResearchStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
        if version == 0:
            self.connection.executescript(
                """
                CREATE TABLE collection_runs (
                    collection_run_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE observations (
                    observation_id TEXT PRIMARY KEY,
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    platform TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    annotation_status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (collection_run_id, platform, platform_item_id)
                );

                CREATE TABLE raw_events (
                    observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id) ON DELETE CASCADE,
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    platform TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    cursor INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (collection_run_id, platform, platform_item_id)
                );

                CREATE TABLE collector_cursors (
                    platform TEXT PRIMARY KEY,
                    cursor INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX observations_review_queue
                    ON observations(annotation_status, created_at);
                PRAGMA user_version = 1;
                """
            )
            version = 1
        if version == 1:
            self.connection.executescript(
                """
                CREATE TABLE research_scopes (
                    scope_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_label TEXT NOT NULL,
                    keywords_json TEXT NOT NULL,
                    languages_json TEXT NOT NULL,
                    window_start TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    max_items INTEGER NOT NULL CHECK(max_items > 0),
                    query_id TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE queries (
                    query_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL REFERENCES research_scopes(scope_id),
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE sources (
                    source_id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE collection_errors (
                    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT REFERENCES collection_runs(collection_run_id),
                    cursor INTEGER,
                    error_code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_sha256 TEXT,
                    retryable INTEGER NOT NULL CHECK(retryable IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE review_events (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    reviewer_ref TEXT NOT NULL,
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    previous_record_json TEXT NOT NULL,
                    new_record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                ALTER TABLE collection_runs ADD COLUMN scope_id TEXT REFERENCES research_scopes(scope_id);
                ALTER TABLE collection_runs ADD COLUMN received_count INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE collection_runs ADD COLUMN normalized_count INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE collection_runs ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
                PRAGMA user_version = 2;
                """
            )
            version = 2
        if version == 2:
            self.connection.executescript(
                """
                CREATE TABLE ingested_events (
                    event_key TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    cursor INTEGER NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    first_collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    created_at TEXT NOT NULL
                );

                INSERT OR IGNORE INTO ingested_events(
                    event_key, platform, cursor, platform_item_id,
                    first_collection_run_id, created_at
                )
                SELECT
                    platform || char(31) || CAST(cursor AS TEXT) || char(31) || platform_item_id,
                    platform, cursor, platform_item_id, collection_run_id, created_at
                FROM raw_events
                ORDER BY created_at, observation_id;

                PRAGMA user_version = 3;
                """
            )
            version = 3
        if version == 3:
            for row in self.connection.execute(
                "SELECT collection_run_id FROM collection_runs"
            ).fetchall():
                self._sync_run_manifest(row["collection_run_id"])
            self.connection.execute("PRAGMA user_version = 4")
            self.connection.commit()
            version = 4
        if version == 4:
            self.connection.executescript(
                """
                CREATE TABLE schedules (
                    schedule_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL UNIQUE REFERENCES research_scopes(scope_id),
                    interval_minutes INTEGER NOT NULL CHECK(interval_minutes BETWEEN 1 AND 10080),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    next_run_at TEXT,
                    last_run_at TEXT,
                    last_collection_run_id TEXT REFERENCES collection_runs(collection_run_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX schedules_due ON schedules(enabled, next_run_at);
                PRAGMA user_version = 5;
                """
            )
            version = 5
        if version == 5:
            self.connection.executescript(
                """
                CREATE TABLE run_triggers (
                    collection_run_id TEXT PRIMARY KEY REFERENCES collection_runs(collection_run_id),
                    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('manual', 'scheduled', 'retry')),
                    parent_collection_run_id TEXT REFERENCES collection_runs(collection_run_id),
                    schedule_id TEXT REFERENCES schedules(schedule_id),
                    created_at TEXT NOT NULL
                );

                INSERT INTO run_triggers(collection_run_id, trigger_type, created_at)
                SELECT collection_run_id, 'manual', started_at FROM collection_runs;

                CREATE TABLE audit_events (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX audit_events_entity
                    ON audit_events(entity_type, entity_id, created_at);
                PRAGMA user_version = 6;
                """
            )
            version = 6
        if version == 6:
            self.connection.executescript(
                """
                CREATE TABLE youtube_quota_settings (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    daily_budget INTEGER NOT NULL CHECK(daily_budget > 0),
                    updated_at TEXT NOT NULL
                );

                INSERT INTO youtube_quota_settings(singleton, daily_budget, updated_at)
                VALUES (1, 1000, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

                CREATE TABLE youtube_quota_events (
                    quota_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    operation TEXT NOT NULL,
                    units INTEGER NOT NULL CHECK(units > 0),
                    quota_date TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'attempted',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX youtube_quota_events_date
                    ON youtube_quota_events(quota_date, operation);

                CREATE TABLE youtube_run_state (
                    collection_run_id TEXT PRIMARY KEY REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE youtube_scope_state (
                    scope_id TEXT PRIMARY KEY REFERENCES research_scopes(scope_id) ON DELETE CASCADE,
                    published_after TEXT,
                    updated_at TEXT NOT NULL
                );

                PRAGMA user_version = 7;
                """
            )
            version = 7
        if version == 7:
            self.connection.executescript(
                """
                CREATE TRIGGER queries_immutable_update
                BEFORE UPDATE ON queries
                BEGIN
                    SELECT RAISE(ABORT, 'registered queries are immutable');
                END;

                CREATE TRIGGER queries_immutable_delete
                BEFORE DELETE ON queries
                BEGIN
                    SELECT RAISE(ABORT, 'registered queries cannot be deleted');
                END;

                CREATE TABLE run_governance (
                    collection_run_id TEXT PRIMARY KEY REFERENCES collection_runs(collection_run_id),
                    usage_classification TEXT NOT NULL
                        CHECK(usage_classification IN ('research_candidate', 'engineering_only')),
                    analysis_allowed INTEGER NOT NULL CHECK(analysis_allowed IN (0, 1)),
                    release_allowed INTEGER NOT NULL CHECK(release_allowed IN (0, 1)),
                    reason TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );

                INSERT INTO run_governance(
                    collection_run_id, usage_classification, analysis_allowed,
                    release_allowed, reason, decided_by, decided_at
                )
                SELECT collection_run_id, 'research_candidate', 1, 0,
                       'Migrated as a local-analysis candidate; release remains blocked.',
                       'system_migration_v8',
                       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                FROM collection_runs;

                CREATE TRIGGER engineering_only_is_terminal
                BEFORE UPDATE OF usage_classification ON run_governance
                WHEN OLD.usage_classification = 'engineering_only'
                     AND NEW.usage_classification != 'engineering_only'
                BEGIN
                    SELECT RAISE(ABORT, 'engineering-only classification is terminal');
                END;

                PRAGMA user_version = 8;
                """
            )
            version = 8
        if version == 8:
            self.connection.executescript(
                """
                CREATE TABLE run_registry_snapshots (
                    collection_run_id TEXT PRIMARY KEY REFERENCES collection_runs(collection_run_id),
                    binding_status TEXT NOT NULL
                        CHECK(binding_status IN ('bound', 'legacy_unbound')),
                    object_map_version TEXT,
                    object_map_sha256 TEXT,
                    codebook_version TEXT,
                    codebook_sha256 TEXT,
                    snapshot_json TEXT,
                    captured_at TEXT NOT NULL
                );

                INSERT INTO run_registry_snapshots(
                    collection_run_id, binding_status, captured_at
                )
                SELECT collection_run_id, 'legacy_unbound',
                       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                FROM collection_runs;

                CREATE TABLE screening_events (
                    screening_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    decision TEXT NOT NULL CHECK(decision IN ('include', 'exclude', 'uncertain')),
                    rule_version TEXT NOT NULL,
                    signals_json TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_version TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX screening_events_observation
                    ON screening_events(observation_id, screening_id);

                INSERT INTO screening_events(
                    observation_id, collection_run_id, decision, rule_version,
                    signals_json, tool_name, tool_version, decided_by, reason, created_at
                )
                SELECT observation_id, collection_run_id, 'uncertain',
                       'legacy_migration_v9', '{"legacy_unbound":true}',
                       'GLYPH migration', '9', 'machine',
                       'Historical observation migrated without a contemporaneous screening decision.',
                       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                FROM observations;

                PRAGMA user_version = 9;
                """
            )
            version = 9
        if version == 9:
            self.connection.executescript(
                """
                ALTER TABLE youtube_quota_settings
                    ADD COLUMN search_daily_call_budget INTEGER NOT NULL DEFAULT 100
                    CHECK(search_daily_call_budget > 0);

                ALTER TABLE youtube_quota_events
                    ADD COLUMN quota_policy_version TEXT NOT NULL
                    DEFAULT 'legacy_pre_2026-06-01';
                ALTER TABLE youtube_quota_events
                    ADD COLUMN quota_bucket TEXT NOT NULL
                    DEFAULT 'legacy_shared_units';

                CREATE TABLE youtube_run_quota_policies (
                    collection_run_id TEXT PRIMARY KEY REFERENCES collection_runs(collection_run_id),
                    policy_version TEXT NOT NULL,
                    search_call_budget INTEGER CHECK(search_call_budget > 0),
                    shared_unit_budget INTEGER NOT NULL CHECK(shared_unit_budget > 0),
                    reset_timezone TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                );

                INSERT INTO youtube_run_quota_policies(
                    collection_run_id, policy_version, search_call_budget,
                    shared_unit_budget, reset_timezone, captured_at
                )
                SELECT runs.collection_run_id, 'legacy_pre_2026-06-01', NULL,
                       settings.daily_budget, 'America/Los_Angeles', runs.started_at
                FROM collection_runs runs
                CROSS JOIN youtube_quota_settings settings
                WHERE runs.platform = 'youtube' AND settings.singleton = 1;

                PRAGMA user_version = 10;
                """
            )
            version = 10
        if version == 10:
            self.connection.executescript(
                """
                CREATE TABLE independent_annotations (
                    annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    coder_id TEXT NOT NULL,
                    annotation_json TEXT NOT NULL,
                    object_map_sha256 TEXT NOT NULL,
                    codebook_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(observation_id, coder_id)
                );

                CREATE TRIGGER independent_annotations_immutable_update
                BEFORE UPDATE ON independent_annotations
                BEGIN
                    SELECT RAISE(ABORT, 'independent annotations are immutable');
                END;

                CREATE TRIGGER independent_annotations_immutable_delete
                BEFORE DELETE ON independent_annotations
                BEGIN
                    SELECT RAISE(ABORT, 'independent annotations cannot be deleted');
                END;

                CREATE TABLE adjudications (
                    adjudication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL UNIQUE REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    adjudicator_id TEXT NOT NULL,
                    adjudication_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER adjudications_immutable_update
                BEFORE UPDATE ON adjudications
                BEGIN
                    SELECT RAISE(ABORT, 'adjudications are immutable');
                END;

                CREATE TRIGGER adjudications_immutable_delete
                BEFORE DELETE ON adjudications
                BEGIN
                    SELECT RAISE(ABORT, 'adjudications cannot be deleted');
                END;

                CREATE TABLE agreement_reports (
                    agreement_report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE run_quality_reports (
                    quality_report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    status TEXT NOT NULL CHECK(status IN ('passed', 'failed')),
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                PRAGMA user_version = 11;
                """
            )
            version = 11
        if version == 11:
            self.connection.executescript(
                """
                CREATE TABLE observation_query_matches (
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(observation_id, query_id)
                );

                CREATE TRIGGER observation_query_matches_immutable_update
                BEFORE UPDATE ON observation_query_matches
                BEGIN
                    SELECT RAISE(ABORT, 'observation query matches are immutable');
                END;

                CREATE TRIGGER observation_query_matches_immutable_delete
                BEFORE DELETE ON observation_query_matches
                BEGIN
                    SELECT RAISE(ABORT, 'observation query matches cannot be deleted');
                END;

                PRAGMA user_version = 12;
                """
            )
            has_observations = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'observations'"
            ).fetchone()
            has_queries = self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'queries'"
            ).fetchone()
            if has_observations is not None and has_queries is not None:
                with self.connection:
                    self.connection.execute(
                        """
                        INSERT INTO observation_query_matches(
                            observation_id, collection_run_id, query_id,
                            context_json, created_at
                        )
                        SELECT o.observation_id, o.collection_run_id,
                               json_extract(o.record_json, '$.query_id'),
                               '{"migration":"schema_v12"}', o.created_at
                        FROM observations o
                        JOIN queries q
                          ON q.query_id = json_extract(o.record_json, '$.query_id')
                        """
                    )
            version = 12
        if version == 12:
            self.connection.executescript(
                """
                CREATE TABLE run_query_yield_policies (
                    collection_run_id TEXT PRIMARY KEY
                        REFERENCES collection_runs(collection_run_id),
                    assessment_mode TEXT NOT NULL
                        CHECK(assessment_mode IN ('preregistered', 'retrospective')),
                    policy_json TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                );

                CREATE TRIGGER run_query_yield_policies_immutable_update
                BEFORE UPDATE ON run_query_yield_policies
                BEGIN
                    SELECT RAISE(ABORT, 'query yield policies are immutable');
                END;

                CREATE TRIGGER run_query_yield_policies_immutable_delete
                BEFORE DELETE ON run_query_yield_policies
                BEGIN
                    SELECT RAISE(ABORT, 'query yield policies cannot be deleted');
                END;

                CREATE TABLE query_yield_reports (
                    query_yield_report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id),
                    status TEXT NOT NULL
                        CHECK(status IN ('passed', 'failed', 'inconclusive')),
                    report_json TEXT NOT NULL,
                    evidence_revision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER query_yield_reports_immutable_update
                BEFORE UPDATE ON query_yield_reports
                BEGIN
                    SELECT RAISE(ABORT, 'query yield reports are immutable');
                END;

                CREATE TRIGGER query_yield_reports_immutable_delete
                BEFORE DELETE ON query_yield_reports
                BEGIN
                    SELECT RAISE(ABORT, 'query yield reports cannot be deleted');
                END;

                INSERT INTO run_query_yield_policies(
                    collection_run_id, assessment_mode, policy_json, captured_at
                )
                SELECT collection_run_id, 'retrospective',
                       '{"confidence_level":0.95,"evaluation_k":20,"min_included_at_k":5,"min_precision_at_k":0.25,"min_precision_lower_bound":0.1,"policy_version":"query_yield_v0.1.0"}',
                       started_at
                FROM collection_runs;

                PRAGMA user_version = 13;
                """
            )
            version = 13
        if version == 13:
            self.connection.executescript(
                """
                CREATE TABLE mastodon_instance_states (
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    observed_instance TEXT NOT NULL,
                    access_method TEXT NOT NULL,
                    next_page_token TEXT,
                    max_status_id_candidate TEXT,
                    pages_fetched INTEGER NOT NULL DEFAULT 0 CHECK(pages_fetched >= 0),
                    statuses_seen INTEGER NOT NULL DEFAULT 0 CHECK(statuses_seen >= 0),
                    sightings_count INTEGER NOT NULL DEFAULT 0 CHECK(sightings_count >= 0),
                    status TEXT NOT NULL
                        CHECK(status IN ('pending', 'running', 'completed', 'failed')),
                    error_code TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(collection_run_id, query_id, observed_instance)
                );

                CREATE TABLE mastodon_scope_state (
                    scope_id TEXT NOT NULL
                        REFERENCES research_scopes(scope_id) ON DELETE CASCADE,
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    observed_instance TEXT NOT NULL,
                    max_status_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope_id, query_id, observed_instance)
                );

                CREATE TABLE mastodon_sightings (
                    sighting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    observed_instance TEXT NOT NULL,
                    local_status_id TEXT NOT NULL,
                    platform_item_id TEXT NOT NULL,
                    status_uri TEXT,
                    visibility TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(collection_run_id, query_id, observed_instance, local_status_id)
                );

                CREATE INDEX mastodon_sightings_observation
                    ON mastodon_sightings(observation_id, observed_instance);
                PRAGMA user_version = 14;
                """
            )
            version = 14
        if version == 14:
            self.connection.executescript(
                """
                CREATE TABLE api_collection_states (
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    partition_key TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('pending', 'running', 'completed', 'failed')),
                    error_code TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(collection_run_id, query_id, partition_key)
                );

                CREATE INDEX api_collection_states_platform
                    ON api_collection_states(platform, status, updated_at);

                CREATE TABLE api_scope_states (
                    scope_id TEXT NOT NULL
                        REFERENCES research_scopes(scope_id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    query_id TEXT NOT NULL REFERENCES queries(query_id),
                    partition_key TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope_id, query_id, partition_key)
                );

                PRAGMA user_version = 15;
                """
            )
            version = 15
        if version == 15:
            self.connection.executescript(
                f"""
                CREATE TABLE tiktok_quota_settings (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    daily_request_budget INTEGER NOT NULL
                        CHECK(daily_request_budget BETWEEN 1 AND 1000),
                    policy_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                INSERT INTO tiktok_quota_settings(
                    singleton, daily_request_budget, policy_version, updated_at
                ) VALUES (1, 1000, '{TIKTOK_QUOTA_POLICY}', '{_utc_now()}');

                CREATE TABLE tiktok_request_events (
                    request_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    operation TEXT NOT NULL,
                    quota_date TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'reserved'
                        CHECK(outcome IN ('reserved', 'succeeded', 'failed')),
                    error_code TEXT,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX tiktok_request_events_daily
                    ON tiktok_request_events(quota_date, policy_version, operation);

                PRAGMA user_version = 16;
                """
            )
            version = 16
        if version == 16:
            self.connection.executescript(
                f"""
                CREATE TABLE x_price_snapshots (
                    price_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type TEXT NOT NULL CHECK(resource_type = 'post_read'),
                    unit_price_microusd INTEGER NOT NULL CHECK(unit_price_microusd > 0),
                    currency TEXT NOT NULL CHECK(currency = 'USD'),
                    effective_date TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    pricing_policy_version TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0, 1)),
                    recorded_at TEXT NOT NULL,
                    UNIQUE(resource_type, unit_price_microusd, effective_date)
                );

                CREATE UNIQUE INDEX x_price_snapshots_one_active
                    ON x_price_snapshots(resource_type) WHERE active = 1;

                INSERT INTO x_price_snapshots(
                    resource_type, unit_price_microusd, currency,
                    effective_date, source_url, pricing_policy_version,
                    active, recorded_at
                ) VALUES (
                    'post_read', 5000, 'USD', '2026-09-02',
                    'https://docs.x.com/x-api/getting-started/pricing',
                    '{X_PRICING_POLICY}', 1, '{_utc_now()}'
                );

                CREATE TABLE x_billing_settings (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    local_cycle_spending_cap_microusd INTEGER,
                    console_hard_spending_limit_microusd INTEGER,
                    billing_cycle_start TEXT,
                    billing_cycle_end TEXT,
                    console_limit_confirmed INTEGER NOT NULL DEFAULT 0
                        CHECK(console_limit_confirmed IN (0, 1)),
                    confirmed_by TEXT,
                    confirmed_at TEXT,
                    circuit_breaker_open INTEGER NOT NULL DEFAULT 1
                        CHECK(circuit_breaker_open IN (0, 1)),
                    circuit_breaker_reason TEXT,
                    updated_at TEXT NOT NULL
                );

                INSERT INTO x_billing_settings(
                    singleton, console_limit_confirmed,
                    circuit_breaker_open, circuit_breaker_reason, updated_at
                ) VALUES (
                    1, 0, 1, 'console_hard_spending_limit_unconfirmed', '{_utc_now()}'
                );

                CREATE TABLE x_run_billing_snapshots (
                    collection_run_id TEXT PRIMARY KEY
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    price_snapshot_id INTEGER NOT NULL
                        REFERENCES x_price_snapshots(price_snapshot_id),
                    unit_price_microusd INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    pricing_policy_version TEXT NOT NULL,
                    local_run_budget_microusd INTEGER NOT NULL,
                    local_cycle_spending_cap_microusd INTEGER NOT NULL,
                    console_hard_spending_limit_microusd INTEGER NOT NULL,
                    billing_cycle_start TEXT NOT NULL,
                    billing_cycle_end TEXT NOT NULL,
                    bound_at TEXT NOT NULL
                );

                CREATE TABLE x_request_events (
                    request_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_run_id TEXT NOT NULL
                        REFERENCES collection_runs(collection_run_id) ON DELETE CASCADE,
                    operation TEXT NOT NULL CHECK(operation = 'recent.search'),
                    price_snapshot_id INTEGER NOT NULL
                        REFERENCES x_price_snapshots(price_snapshot_id),
                    unit_price_microusd INTEGER NOT NULL,
                    reserved_resources INTEGER NOT NULL CHECK(reserved_resources > 0),
                    reserved_cost_microusd INTEGER NOT NULL CHECK(reserved_cost_microusd > 0),
                    actual_resources INTEGER,
                    actual_cost_microusd INTEGER,
                    outcome TEXT NOT NULL DEFAULT 'reserved'
                        CHECK(outcome IN (
                            'reserved', 'succeeded', 'failed', 'indeterminate'
                        )),
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX x_request_events_run
                    ON x_request_events(collection_run_id, request_event_id);
                CREATE INDEX x_request_events_cycle
                    ON x_request_events(created_at, outcome);

                PRAGMA user_version = 17;
                """
            )

    def create_scope(self, scope: dict[str, Any], query: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO research_scopes(
                    scope_id, name, platform, object_type, object_label,
                    keywords_json, languages_json, window_start, window_end,
                    max_items, query_id, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    name = excluded.name,
                    object_type = excluded.object_type,
                    object_label = excluded.object_label,
                    keywords_json = excluded.keywords_json,
                    languages_json = excluded.languages_json,
                    window_start = excluded.window_start,
                    window_end = excluded.window_end,
                    max_items = excluded.max_items,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    scope["scope_id"], scope["name"], scope["platform"],
                    scope["object_type"], scope["object_label"],
                    _json(scope["keywords"]), _json(scope["languages"]),
                    scope["window_start"], scope["window_end"], scope["max_items"],
                    scope["query_id"], now, now,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO queries(query_id, scope_id, record_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(query_id) DO NOTHING
                """,
                (scope["query_id"], scope["scope_id"], _json(query), now, now),
            )
            stored_query = self.connection.execute(
                "SELECT scope_id, record_json FROM queries WHERE query_id = ?",
                (scope["query_id"],),
            ).fetchone()
            if (
                stored_query is None
                or stored_query["scope_id"] != scope["scope_id"]
                or stored_query["record_json"] != _json(query)
            ):
                raise ValueError("query_id collision with a different immutable query")

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM research_scopes WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        return self._scope_dict(row) if row is not None else None

    def get_query(self, query_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT record_json FROM queries WHERE query_id = ?", (query_id,)
        ).fetchone()
        return json.loads(row["record_json"]) if row is not None else None

    def promoted_source_query_ids(
        self,
        collection_run_id: str,
        query_yield_report_id: int,
    ) -> set[str]:
        rows = self.connection.execute(
            "SELECT record_json FROM queries"
        ).fetchall()
        source_query_ids = set()
        for row in rows:
            query = json.loads(row["record_json"])
            evidence = query.get("promotion_evidence")
            if (
                query.get("phase") == "confirmatory"
                and isinstance(evidence, dict)
                and evidence.get("collection_run_id") == collection_run_id
                and evidence.get("query_yield_report_id") == query_yield_report_id
                and isinstance(evidence.get("source_query_id"), str)
            ):
                source_query_ids.add(evidence["source_query_id"])
        return source_query_ids

    def add_scope_query(self, scope_id: str, query: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            if self.get_scope(scope_id) is None:
                raise KeyError(scope_id)
            self.connection.execute(
                """
                INSERT INTO queries(query_id, scope_id, record_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(query_id) DO NOTHING
                """,
                (query["query_id"], scope_id, _json(query), now, now),
            )
            row = self.connection.execute(
                "SELECT scope_id, record_json FROM queries WHERE query_id = ?",
                (query["query_id"],),
            ).fetchone()
            if (
                row is None
                or row["scope_id"] != scope_id
                or row["record_json"] != _json(query)
            ):
                raise ValueError("query_id collision with a different immutable query")
        return query

    def create_promoted_scope(
        self,
        source_scope_id: str,
        scope: dict[str, Any],
        queries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not queries or scope["query_id"] not in {
            query["query_id"] for query in queries
        }:
            raise ValueError("确认范围必须包含主 query")
        if len({query["query_id"] for query in queries}) != len(queries):
            raise ValueError("确认范围包含重复 query")
        now = _utc_now()
        with self.connection:
            source = self.connection.execute(
                "SELECT scope_id FROM research_scopes WHERE scope_id = ?",
                (source_scope_id,),
            ).fetchone()
            if source is None:
                raise KeyError(source_scope_id)
            if self.connection.execute(
                "SELECT 1 FROM research_scopes WHERE scope_id = ?",
                (scope["scope_id"],),
            ).fetchone() is not None:
                raise ValueError("该校准报告和确认设计已经生成 confirmatory scope")
            existing_query = self.connection.execute(
                f"SELECT query_id FROM queries WHERE query_id IN ({','.join('?' for _ in queries)}) LIMIT 1",
                tuple(query["query_id"] for query in queries),
            ).fetchone()
            if existing_query is not None:
                raise ValueError("该校准报告和确认设计已经生成 confirmatory query")
            self.connection.execute(
                """
                INSERT INTO research_scopes(
                    scope_id, name, platform, object_type, object_label,
                    keywords_json, languages_json, window_start, window_end,
                    max_items, query_id, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    scope["scope_id"], scope["name"], scope["platform"],
                    scope["object_type"], scope["object_label"],
                    _json(scope["keywords"]), _json(scope["languages"]),
                    scope["window_start"], scope["window_end"], scope["max_items"],
                    scope["query_id"], now, now,
                ),
            )
            self.connection.executemany(
                """
                INSERT INTO queries(query_id, scope_id, record_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (query["query_id"], scope["scope_id"], _json(query), now, now)
                    for query in queries
                ],
            )
            self.connection.execute(
                """
                UPDATE research_scopes
                SET active = 0, updated_at = ?
                WHERE scope_id = ?
                """,
                (now, source_scope_id),
            )
            self.connection.execute(
                """
                UPDATE schedules SET enabled = 0, next_run_at = NULL, updated_at = ?
                WHERE scope_id = ?
                """,
                (now, source_scope_id),
            )
        created = self.get_scope(scope["scope_id"])
        if created is None:
            raise RuntimeError("confirmatory scope creation failed")
        return created

    def list_scope_queries(
        self, scope_id: str, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT query_id, record_json, created_at
            FROM queries WHERE scope_id = ? ORDER BY created_at, rowid
            """,
            (scope_id,),
        ).fetchall()
        queries = [json.loads(row["record_json"]) for row in rows]
        if active_only:
            superseded = {
                query["supersedes_query_id"]
                for query in queries
                if isinstance(query.get("supersedes_query_id"), str)
            }
            queries = [
                query for query in queries if query["query_id"] not in superseded
            ]
        return queries

    def list_scopes(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM research_scopes ORDER BY updated_at DESC, scope_id"
        ).fetchall()
        return [self._scope_dict(row) for row in rows]

    def update_scope(
        self,
        scope: dict[str, Any],
        query: dict[str, Any] | None,
        *,
        active: bool,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            if query is not None:
                self.connection.execute(
                    """
                    INSERT INTO queries(query_id, scope_id, record_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(query_id) DO NOTHING
                    """,
                    (scope["query_id"], scope["scope_id"], _json(query), now, now),
                )
                stored_query = self.connection.execute(
                    "SELECT scope_id, record_json FROM queries WHERE query_id = ?",
                    (scope["query_id"],),
                ).fetchone()
                if (
                    stored_query is None
                    or stored_query["scope_id"] != scope["scope_id"]
                    or stored_query["record_json"] != _json(query)
                ):
                    raise ValueError("query_id collision with a different immutable query")
            changed = self.connection.execute(
                """
                UPDATE research_scopes
                SET name = ?, object_type = ?, object_label = ?, keywords_json = ?,
                    languages_json = ?, window_start = ?, window_end = ?,
                    max_items = ?, query_id = ?, active = ?, updated_at = ?
                WHERE scope_id = ?
                """,
                (
                    scope["name"], scope["object_type"], scope["object_label"],
                    _json(scope["keywords"]), _json(scope["languages"]),
                    scope["window_start"], scope["window_end"], scope["max_items"],
                    scope["query_id"], int(active), now, scope["scope_id"],
                ),
            ).rowcount
            if not changed:
                raise KeyError(scope["scope_id"])
            if not active:
                self.connection.execute(
                    """
                    UPDATE schedules SET enabled = 0, next_run_at = NULL, updated_at = ?
                    WHERE scope_id = ?
                    """,
                    (now, scope["scope_id"]),
                )
        updated = self.get_scope(scope["scope_id"])
        if updated is None:
            raise RuntimeError("scope update failed")
        return updated

    def create_schedule(
        self,
        schedule_id: str,
        scope_id: str,
        *,
        interval_minutes: int,
        enabled: bool,
        next_run_at: str | None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO schedules(
                    schedule_id, scope_id, interval_minutes, enabled,
                    next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id, scope_id, interval_minutes, int(enabled),
                    next_run_at, now, now,
                ),
            )
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            raise RuntimeError("schedule insert failed")
        return schedule

    def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
        ).fetchone()
        return self._schedule_dict(row) if row is not None else None

    def list_schedules(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM schedules ORDER BY created_at, schedule_id"
        ).fetchall()
        return [self._schedule_dict(row) for row in rows]

    def update_schedule(
        self,
        schedule_id: str,
        *,
        interval_minutes: int,
        enabled: bool,
        next_run_at: str | None,
    ) -> dict[str, Any]:
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE schedules
                SET interval_minutes = ?, enabled = ?, next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (interval_minutes, int(enabled), next_run_at, _utc_now(), schedule_id),
            ).rowcount
        if not changed:
            raise KeyError(schedule_id)
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            raise RuntimeError("schedule update failed")
        return schedule

    def record_schedule_run(self, schedule_id: str, collection_run_id: str) -> dict[str, Any]:
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            raise KeyError(schedule_id)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        next_run_at = (
            now + timedelta(minutes=schedule["interval_minutes"])
        ).isoformat().replace("+00:00", "Z") if schedule["enabled"] else None
        with self.connection:
            self.connection.execute(
                """
                UPDATE schedules
                SET last_run_at = ?, last_collection_run_id = ?,
                    next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    now.isoformat().replace("+00:00", "Z"), collection_run_id,
                    next_run_at, now.isoformat().replace("+00:00", "Z"), schedule_id,
                ),
            )
        updated = self.get_schedule(schedule_id)
        if updated is None:
            raise RuntimeError("schedule run update failed")
        return updated

    def interrupted_runs(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM collection_runs WHERE status = 'running' ORDER BY started_at"
        ).fetchall()
        return [dict(row) for row in rows]

    def record_audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO audit_events(
                    event_type, entity_type, entity_id, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_type, entity_type, entity_id, _json(details or {}), _utc_now()),
            )

    def set_run_governance(
        self,
        collection_run_id: str,
        *,
        usage_classification: str,
        reason: str,
        decided_by: str,
    ) -> dict[str, Any]:
        if usage_classification not in {"research_candidate", "engineering_only"}:
            raise ValueError("invalid run usage classification")
        if not reason.strip():
            raise ValueError("run governance requires a reason")
        analysis_allowed = usage_classification == "research_candidate"
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE run_governance
                SET usage_classification = ?, analysis_allowed = ?,
                    release_allowed = 0, reason = ?, decided_by = ?, decided_at = ?
                WHERE collection_run_id = ?
                """,
                (
                    usage_classification, int(analysis_allowed), reason.strip(),
                    decided_by, _utc_now(), collection_run_id,
                ),
            ).rowcount
        if not changed:
            raise KeyError(collection_run_id)
        governance = self.get_run_governance(collection_run_id)
        if governance is None:
            raise RuntimeError("run governance update failed")
        return governance

    def get_run_governance(self, collection_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM run_governance WHERE collection_run_id = ?",
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return None
        governance = dict(row)
        governance["analysis_allowed"] = bool(governance["analysis_allowed"])
        governance["release_allowed"] = bool(governance["release_allowed"])
        return governance

    def set_run_release(
        self,
        collection_run_id: str,
        *,
        release_allowed: bool,
        reason: str,
        decided_by: str,
    ) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("release governance requires a reason")
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE run_governance
                SET release_allowed = ?, reason = ?, decided_by = ?, decided_at = ?
                WHERE collection_run_id = ?
                  AND usage_classification = 'research_candidate'
                  AND analysis_allowed = 1
                """,
                (
                    int(release_allowed), reason.strip(), decided_by, _utc_now(),
                    collection_run_id,
                ),
            ).rowcount
        if not changed:
            if self.get_run_governance(collection_run_id) is None:
                raise KeyError(collection_run_id)
            raise ValueError("只有允许研究分析的 candidate run 可以授权发布")
        governance = self.get_run_governance(collection_run_id)
        if governance is None:
            raise RuntimeError("run release governance update failed")
        return governance

    def set_youtube_daily_quota_budget(self, daily_budget: int) -> None:
        current = self.youtube_quota_status()
        self.set_youtube_quota_budgets(
            shared_unit_budget=daily_budget,
            search_call_budget=current["search_daily_call_budget"],
        )

    def set_youtube_quota_budgets(
        self,
        *,
        shared_unit_budget: int,
        search_call_budget: int,
    ) -> None:
        if not 1 <= shared_unit_budget <= 1_000_000_000:
            raise ValueError("YouTube 共享单位预算必须在 1 到 1000000000 之间")
        if not 1 <= search_call_budget <= 100:
            raise ValueError("YouTube 搜索调用预算必须在 1 到 100 之间")
        with self.connection:
            self.connection.execute(
                """
                UPDATE youtube_quota_settings
                SET daily_budget = ?, search_daily_call_budget = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (shared_unit_budget, search_call_budget, _utc_now()),
            )

    def bind_youtube_quota_policy(
        self,
        collection_run_id: str,
        *,
        search_call_budget: int | None = None,
        shared_unit_budget: int | None = None,
    ) -> dict[str, Any]:
        settings = self.connection.execute(
            """
            SELECT daily_budget, search_daily_call_budget
            FROM youtube_quota_settings WHERE singleton = 1
            """
        ).fetchone()
        if settings is None:
            raise RuntimeError("YouTube quota settings are missing")
        effective_search_budget = (
            int(search_call_budget)
            if search_call_budget is not None
            else int(settings["search_daily_call_budget"])
        )
        effective_shared_budget = (
            int(shared_unit_budget)
            if shared_unit_budget is not None
            else int(settings["daily_budget"])
        )
        if not 1 <= effective_search_budget <= 100:
            raise ValueError("YouTube run 搜索调用预算必须在 1 到 100 之间")
        if not 1 <= effective_shared_budget <= 1_000_000_000:
            raise ValueError("YouTube run 共享单位预算必须为正整数")
        captured_at = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO youtube_run_quota_policies(
                    collection_run_id, policy_version, search_call_budget,
                    shared_unit_budget, reset_timezone, captured_at
                ) VALUES (?, ?, ?, ?, 'America/Los_Angeles', ?)
                """,
                (
                    collection_run_id,
                    YOUTUBE_QUOTA_POLICY,
                    effective_search_budget,
                    effective_shared_budget,
                    captured_at,
                ),
            )
        policy = self.get_run_quota_policy(collection_run_id)
        if policy is None:
            raise RuntimeError("YouTube run quota policy binding failed")
        return policy

    def get_run_quota_policy(self, collection_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT collection_run_id, policy_version, search_call_budget,
                   shared_unit_budget, reset_timezone, captured_at
            FROM youtube_run_quota_policies WHERE collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _youtube_quota_date(now: datetime | None = None) -> str:
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(YOUTUBE_QUOTA_TIMEZONE).date().isoformat()

    def consume_youtube_quota(
        self,
        collection_run_id: str,
        operation: str,
        units: int,
        *,
        now: datetime | None = None,
    ) -> int:
        if units <= 0:
            raise ValueError("YouTube 配额单位必须为正整数")
        quota_date = self._youtube_quota_date(now)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self.connection.execute(
                "SELECT platform FROM collection_runs WHERE collection_run_id = ?",
                (collection_run_id,),
            ).fetchone()
            if run is None or run["platform"] != "youtube":
                raise ValueError("YouTube 配额只能记入 YouTube 采集运行")
            policy = self.get_run_quota_policy(collection_run_id)
            if policy is None:
                raise ValueError("YouTube 运行缺少配额政策快照")
            settings = self.connection.execute(
                """
                SELECT daily_budget, search_daily_call_budget
                FROM youtube_quota_settings WHERE singleton = 1
                """
            ).fetchone()
            if policy["policy_version"] == YOUTUBE_QUOTA_POLICY:
                if operation == "search.list":
                    quota_bucket = "search_calls"
                    used = int(self.connection.execute(
                        """
                        SELECT COUNT(*) FROM youtube_quota_events
                        WHERE quota_date = ? AND quota_policy_version = ?
                          AND quota_bucket = 'search_calls'
                        """,
                        (quota_date, YOUTUBE_QUOTA_POLICY),
                    ).fetchone()[0])
                    run_used = int(self.connection.execute(
                        """
                        SELECT COUNT(*) FROM youtube_quota_events
                        WHERE collection_run_id = ? AND quota_date = ?
                          AND quota_policy_version = ?
                          AND quota_bucket = 'search_calls'
                        """,
                        (collection_run_id, quota_date, YOUTUBE_QUOTA_POLICY),
                    ).fetchone()[0])
                    global_budget = int(settings["search_daily_call_budget"])
                    run_budget = int(policy["search_call_budget"])
                    if used + 1 > global_budget:
                        raise ValueError(
                            "YouTube 搜索调用配额不足："
                            f"当日已用 {used}，请求 1，全局预算 {global_budget}"
                        )
                    if run_used + 1 > run_budget:
                        raise ValueError(
                            "YouTube 运行冻结搜索配额不足："
                            f"本 run 已用 {run_used}，请求 1，冻结预算 {run_budget}"
                        )
                else:
                    quota_bucket = "shared_units"
                    used = int(self.connection.execute(
                        """
                        SELECT COALESCE(SUM(units), 0) FROM youtube_quota_events
                        WHERE quota_date = ? AND quota_policy_version = ?
                          AND quota_bucket = 'shared_units'
                        """,
                        (quota_date, YOUTUBE_QUOTA_POLICY),
                    ).fetchone()[0])
                    run_used = int(self.connection.execute(
                        """
                        SELECT COALESCE(SUM(units), 0) FROM youtube_quota_events
                        WHERE collection_run_id = ? AND quota_date = ?
                          AND quota_policy_version = ?
                          AND quota_bucket = 'shared_units'
                        """,
                        (collection_run_id, quota_date, YOUTUBE_QUOTA_POLICY),
                    ).fetchone()[0])
                    global_budget = int(settings["daily_budget"])
                    run_budget = int(policy["shared_unit_budget"])
                    if used + units > global_budget:
                        raise ValueError(
                            "YouTube 共享单位配额不足："
                            f"当日已用 {used}，请求 {units}，全局预算 {global_budget}"
                        )
                    if run_used + units > run_budget:
                        raise ValueError(
                            "YouTube 运行冻结共享配额不足："
                            f"本 run 已用 {run_used}，请求 {units}，冻结预算 {run_budget}"
                        )
            else:
                quota_bucket = "legacy_shared_units"
                used = int(self.connection.execute(
                    """
                    SELECT COALESCE(SUM(units), 0) FROM youtube_quota_events
                    WHERE quota_date = ? AND quota_policy_version = ?
                    """,
                    (quota_date, LEGACY_YOUTUBE_QUOTA_POLICY),
                ).fetchone()[0])
                budget = int(policy["shared_unit_budget"])
                if used + units > budget:
                    raise ValueError(
                        f"YouTube legacy 日配额不足：已用 {used}，请求 {units}，预算 {budget}"
                    )
            cursor = self.connection.execute(
                """
                INSERT INTO youtube_quota_events(
                    collection_run_id, operation, units, quota_date, created_at,
                    quota_policy_version, quota_bucket
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    operation,
                    units,
                    quota_date,
                    _utc_now(),
                    policy["policy_version"],
                    quota_bucket,
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            self.connection.rollback()
            raise

    def finish_youtube_quota_event(self, quota_event_id: int, outcome: str) -> None:
        if outcome not in {"success", "error"}:
            raise ValueError("invalid YouTube quota outcome")
        with self.connection:
            changed = self.connection.execute(
                "UPDATE youtube_quota_events SET outcome = ? WHERE quota_event_id = ?",
                (outcome, quota_event_id),
            ).rowcount
        if not changed:
            raise KeyError(quota_event_id)

    def youtube_quota_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        quota_date = self._youtube_quota_date(now)
        daily_budget = int(self.connection.execute(
            "SELECT daily_budget FROM youtube_quota_settings WHERE singleton = 1"
        ).fetchone()[0])
        search_daily_call_budget = int(self.connection.execute(
            "SELECT search_daily_call_budget FROM youtube_quota_settings WHERE singleton = 1"
        ).fetchone()[0])
        rows = self.connection.execute(
            """
            SELECT operation, SUM(units) AS units
            FROM youtube_quota_events
            WHERE quota_date = ? AND quota_policy_version = ?
            GROUP BY operation ORDER BY operation
            """,
            (quota_date, YOUTUBE_QUOTA_POLICY),
        ).fetchall()
        usage_by_operation = {row["operation"]: int(row["units"]) for row in rows}
        used_units = int(self.connection.execute(
            """
            SELECT COALESCE(SUM(units), 0) FROM youtube_quota_events
            WHERE quota_date = ? AND quota_policy_version = ?
              AND quota_bucket = 'shared_units'
            """,
            (quota_date, YOUTUBE_QUOTA_POLICY),
        ).fetchone()[0])
        used_search_calls = int(self.connection.execute(
            """
            SELECT COUNT(*) FROM youtube_quota_events
            WHERE quota_date = ? AND quota_policy_version = ?
              AND quota_bucket = 'search_calls'
            """,
            (quota_date, YOUTUBE_QUOTA_POLICY),
        ).fetchone()[0])
        return {
            "quota_date": quota_date,
            "reset_timezone": "America/Los_Angeles",
            "policy_version": YOUTUBE_QUOTA_POLICY,
            "daily_budget": daily_budget,
            "used_units": used_units,
            "remaining_units": max(0, daily_budget - used_units),
            "search_daily_call_budget": search_daily_call_budget,
            "used_search_calls": used_search_calls,
            "remaining_search_calls": max(0, search_daily_call_budget - used_search_calls),
            "usage_by_operation": usage_by_operation,
        }

    def set_tiktok_daily_request_budget(self, daily_request_budget: int) -> None:
        if not 1 <= daily_request_budget <= 1000:
            raise ValueError("TikTok 每日请求预算必须在 1 到 1000 之间")
        with self.connection:
            self.connection.execute(
                """
                UPDATE tiktok_quota_settings
                SET daily_request_budget = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (daily_request_budget, _utc_now()),
            )

    @staticmethod
    def _tiktok_quota_date(quota_date: str | None = None) -> str:
        value = quota_date or datetime.now(timezone.utc).date().isoformat()
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("TikTok quota_date 必须是 YYYY-MM-DD") from error
        if parsed.isoformat() != value:
            raise ValueError("TikTok quota_date 必须是 YYYY-MM-DD")
        return value

    def reserve_tiktok_request(
        self,
        collection_run_id: str,
        operation: str,
        *,
        quota_date: str | None = None,
    ) -> int:
        if operation not in {"video.query", "comment.list"}:
            raise ValueError("无效的 TikTok Research API 操作")
        day = self._tiktok_quota_date(quota_date)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self.connection.execute(
                "SELECT platform FROM collection_runs WHERE collection_run_id = ?",
                (collection_run_id,),
            ).fetchone()
            if run is None or run["platform"] != "tiktok":
                raise ValueError("TikTok 请求只能记入 TikTok 采集运行")
            settings = self.connection.execute(
                """
                SELECT daily_request_budget, policy_version
                FROM tiktok_quota_settings WHERE singleton = 1
                """
            ).fetchone()
            if settings is None:
                raise RuntimeError("TikTok quota settings are missing")
            used = int(self.connection.execute(
                """
                SELECT COUNT(*) FROM tiktok_request_events
                WHERE quota_date = ? AND policy_version = ?
                """,
                (day, settings["policy_version"]),
            ).fetchone()[0])
            budget = int(settings["daily_request_budget"])
            if used + 1 > budget:
                raise ValueError(
                    "TikTok daily request budget exceeded: "
                    f"UTC date {day}, used {used}, budget {budget}"
                )
            cursor = self.connection.execute(
                """
                INSERT INTO tiktok_request_events(
                    collection_run_id, operation, quota_date, policy_version,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    operation,
                    day,
                    settings["policy_version"],
                    _utc_now(),
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            self.connection.rollback()
            raise

    def finish_tiktok_request(
        self,
        request_event_id: int,
        *,
        outcome: str,
        error_code: str | None = None,
    ) -> None:
        if outcome not in {"succeeded", "failed"}:
            raise ValueError("无效的 TikTok 请求结果")
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE tiktok_request_events
                SET outcome = ?, error_code = ?, completed_at = ?
                WHERE request_event_id = ? AND outcome = 'reserved'
                """,
                (outcome, error_code, _utc_now(), request_event_id),
            ).rowcount
        if not changed:
            raise KeyError(request_event_id)

    def tiktok_quota_status(self, quota_date: str | None = None) -> dict[str, Any]:
        day = self._tiktok_quota_date(quota_date)
        settings = self.connection.execute(
            """
            SELECT daily_request_budget, policy_version
            FROM tiktok_quota_settings WHERE singleton = 1
            """
        ).fetchone()
        if settings is None:
            raise RuntimeError("TikTok quota settings are missing")
        used = int(self.connection.execute(
            """
            SELECT COUNT(*) FROM tiktok_request_events
            WHERE quota_date = ? AND policy_version = ?
            """,
            (day, settings["policy_version"]),
        ).fetchone()[0])
        budget = int(settings["daily_request_budget"])
        return {
            "quota_date": day,
            "daily_request_budget": budget,
            "used_requests": used,
            "remaining_requests": max(0, budget - used),
            "policy_version": settings["policy_version"],
            "reset_timezone": "UTC",
        }

    def tiktok_request_events(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        if collection_run_id is None:
            rows = self.connection.execute(
                "SELECT * FROM tiktok_request_events ORDER BY request_event_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM tiktok_request_events
                WHERE collection_run_id = ? ORDER BY request_event_id
                """,
                (collection_run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _x_price_snapshot_dict(row: sqlite3.Row) -> dict[str, Any]:
        output = dict(row)
        output["active"] = bool(output["active"])
        output["unit_price_usd"] = _microusd_text(
            int(output["unit_price_microusd"])
        )
        return output

    def active_x_price_snapshot(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM x_price_snapshots
            WHERE resource_type = 'post_read' AND active = 1
            """
        ).fetchone()
        return self._x_price_snapshot_dict(row) if row is not None else None

    def record_x_price_snapshot(
        self,
        *,
        unit_price_microusd: int,
        effective_date: str,
        source_url: str,
        pricing_policy_version: str,
    ) -> dict[str, Any]:
        if isinstance(unit_price_microusd, bool) or unit_price_microusd <= 0:
            raise ValueError("X post_read 单价必须是正整数微美元")
        try:
            parsed_date = datetime.strptime(effective_date, "%Y-%m-%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("X 价格生效日期必须是 YYYY-MM-DD") from error
        if parsed_date.isoformat() != effective_date:
            raise ValueError("X 价格生效日期必须是 YYYY-MM-DD")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise ValueError("X 价格快照必须包含 HTTPS 来源")
        if not isinstance(pricing_policy_version, str) or not pricing_policy_version:
            raise ValueError("X 价格快照必须包含政策版本")
        with self.connection:
            self.connection.execute(
                "UPDATE x_price_snapshots SET active = 0 WHERE resource_type = 'post_read'"
            )
            self.connection.execute(
                """
                INSERT INTO x_price_snapshots(
                    resource_type, unit_price_microusd, currency,
                    effective_date, source_url, pricing_policy_version,
                    active, recorded_at
                ) VALUES ('post_read', ?, 'USD', ?, ?, ?, 1, ?)
                ON CONFLICT(resource_type, unit_price_microusd, effective_date)
                DO UPDATE SET active = 1
                """,
                (
                    unit_price_microusd,
                    effective_date,
                    source_url,
                    pricing_policy_version,
                    _utc_now(),
                ),
            )
        snapshot = self.active_x_price_snapshot()
        if snapshot is None:
            raise RuntimeError("X active price snapshot is missing")
        return snapshot

    def configure_x_billing_guard(
        self,
        *,
        local_cycle_spending_cap_microusd: int,
        console_hard_spending_limit_microusd: int,
        billing_cycle_start: str,
        billing_cycle_end: str,
        console_limit_confirmed: bool,
        confirmed_by: str,
    ) -> dict[str, Any]:
        for value, label in (
            (local_cycle_spending_cap_microusd, "本机 billing-cycle cap"),
            (console_hard_spending_limit_microusd, "Console hard spending limit"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"X {label} 必须是正整数微美元")
        if (
            local_cycle_spending_cap_microusd
            > console_hard_spending_limit_microusd
        ):
            raise ValueError("X 本机 billing-cycle cap 不得高于 Console hard spending limit")
        start = _utc_timestamp(billing_cycle_start, field="X billing_cycle_start")
        end = _utc_timestamp(billing_cycle_end, field="X billing_cycle_end")
        if end <= start:
            raise ValueError("X billing cycle 结束时间必须晚于开始时间")
        if not isinstance(console_limit_confirmed, bool):
            raise ValueError("X Console hard spending limit 确认值必须是布尔值")
        if console_limit_confirmed and (
            not isinstance(confirmed_by, str) or not confirmed_by.strip()
        ):
            raise ValueError("X Console hard spending limit 必须记录确认人")
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE x_billing_settings
                SET local_cycle_spending_cap_microusd = ?,
                    console_hard_spending_limit_microusd = ?,
                    billing_cycle_start = ?, billing_cycle_end = ?,
                    console_limit_confirmed = ?, confirmed_by = ?,
                    confirmed_at = ?, circuit_breaker_open = ?,
                    circuit_breaker_reason = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (
                    local_cycle_spending_cap_microusd,
                    console_hard_spending_limit_microusd,
                    start.isoformat().replace("+00:00", "Z"),
                    end.isoformat().replace("+00:00", "Z"),
                    int(console_limit_confirmed),
                    confirmed_by.strip() if console_limit_confirmed else None,
                    now if console_limit_confirmed else None,
                    int(not console_limit_confirmed),
                    (
                        None
                        if console_limit_confirmed
                        else "console_hard_spending_limit_unconfirmed"
                    ),
                    now,
                ),
            )
        return self.x_billing_status()

    def x_billing_status(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM x_billing_settings WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("X billing settings are missing")
        settings = dict(row)
        cycle_start = settings["billing_cycle_start"]
        cycle_end = settings["billing_cycle_end"]
        accrued = 0
        reserved = 0
        if isinstance(cycle_start, str) and isinstance(cycle_end, str):
            usage = self.connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN outcome != 'reserved'
                        THEN actual_cost_microusd ELSE 0 END), 0) AS accrued,
                    COALESCE(SUM(CASE WHEN outcome = 'reserved'
                        THEN reserved_cost_microusd ELSE 0 END), 0) AS reserved
                FROM x_request_events
                WHERE created_at >= ? AND created_at < ?
                """,
                (cycle_start, cycle_end),
            ).fetchone()
            accrued = int(usage["accrued"])
            reserved = int(usage["reserved"])
        cap = settings["local_cycle_spending_cap_microusd"]
        return {
            "local_cycle_spending_cap_microusd": cap,
            "console_hard_spending_limit_microusd": settings[
                "console_hard_spending_limit_microusd"
            ],
            "billing_cycle_start": cycle_start,
            "billing_cycle_end": cycle_end,
            "console_limit_confirmed": bool(settings["console_limit_confirmed"]),
            "confirmed_by": settings["confirmed_by"],
            "confirmed_at": settings["confirmed_at"],
            "circuit_breaker_open": bool(settings["circuit_breaker_open"]),
            "circuit_breaker_reason": settings["circuit_breaker_reason"],
            "accrued_cost_microusd": accrued,
            "reserved_exposure_microusd": reserved,
            "remaining_local_cycle_microusd": (
                max(0, int(cap) - accrued - reserved)
                if isinstance(cap, int)
                else None
            ),
            "active_price": self.active_x_price_snapshot(),
            "updated_at": settings["updated_at"],
        }

    def preflight_x_billing(
        self,
        *,
        local_run_budget_microusd: int,
        page_size: int,
    ) -> dict[str, Any]:
        status = self.x_billing_status()
        if not status["console_limit_confirmed"]:
            raise XBillingGateError(
                "X Developer Console hard spending limit 尚未确认"
            )
        if status["circuit_breaker_open"]:
            raise XBillingGateError(
                "X 费用熔断器已开启："
                + str(status["circuit_breaker_reason"] or "unknown")
            )
        start_value = status["billing_cycle_start"]
        end_value = status["billing_cycle_end"]
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            raise XBillingGateError("X billing cycle 尚未配置")
        now = datetime.now(timezone.utc)
        start = _utc_timestamp(start_value, field="X billing_cycle_start")
        end = _utc_timestamp(end_value, field="X billing_cycle_end")
        if not start <= now < end:
            raise XBillingGateError("X billing cycle 当前无效")
        local_cap = status["local_cycle_spending_cap_microusd"]
        console_cap = status["console_hard_spending_limit_microusd"]
        if not isinstance(local_cap, int) or not isinstance(console_cap, int):
            raise XBillingGateError("X spending caps 尚未配置")
        if local_cap > console_cap:
            raise XBillingGateError(
                "X 本机 billing-cycle cap 高于 Console hard spending limit"
            )
        price = status["active_price"]
        if not isinstance(price, dict):
            raise XBillingGateError("X post_read active price snapshot 缺失")
        worst_page_cost = page_size * int(price["unit_price_microusd"])
        if local_run_budget_microusd < worst_page_cost:
            raise XBillingGateError("X 本机 run 预算不足以覆盖一页最坏成本")
        remaining = status["remaining_local_cycle_microusd"]
        if not isinstance(remaining, int) or remaining < worst_page_cost:
            raise XBillingGateError("X 本机 billing-cycle cap 剩余额度不足")
        return {
            "price_snapshot_id": price["price_snapshot_id"],
            "unit_price_microusd": price["unit_price_microusd"],
            "currency": price["currency"],
            "pricing_policy_version": price["pricing_policy_version"],
            "local_run_budget_microusd": local_run_budget_microusd,
            "local_cycle_spending_cap_microusd": local_cap,
            "console_hard_spending_limit_microusd": console_cap,
            "billing_cycle_start": start_value,
            "billing_cycle_end": end_value,
        }

    def bind_x_run_billing(
        self,
        collection_run_id: str,
        binding: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        run = self.connection.execute(
            "SELECT platform FROM collection_runs WHERE collection_run_id = ?",
            (collection_run_id,),
        ).fetchone()
        if run is None or run["platform"] != "x":
            raise ValueError("X billing snapshot 只能绑定 X run")
        self.connection.execute(
            """
            INSERT INTO x_run_billing_snapshots(
                collection_run_id, price_snapshot_id,
                unit_price_microusd, currency, pricing_policy_version,
                local_run_budget_microusd,
                local_cycle_spending_cap_microusd,
                console_hard_spending_limit_microusd,
                billing_cycle_start, billing_cycle_end, bound_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                collection_run_id,
                binding["price_snapshot_id"],
                binding["unit_price_microusd"],
                binding["currency"],
                binding["pricing_policy_version"],
                binding["local_run_budget_microusd"],
                binding["local_cycle_spending_cap_microusd"],
                binding["console_hard_spending_limit_microusd"],
                binding["billing_cycle_start"],
                binding["billing_cycle_end"],
                _utc_now(),
            ),
        )
        if commit:
            self.connection.commit()
        snapshot = self.x_run_billing_snapshot(collection_run_id)
        if snapshot is None:
            raise RuntimeError("X run billing snapshot was not stored")
        return snapshot

    def x_run_billing_snapshot(
        self, collection_run_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM x_run_billing_snapshots WHERE collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return None
        output = dict(row)
        output["unit_price_usd"] = _microusd_text(
            int(output["unit_price_microusd"])
        )
        return output

    def open_x_circuit_breaker(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("X 熔断原因不能为空")
        with self.connection:
            self.connection.execute(
                """
                UPDATE x_billing_settings
                SET circuit_breaker_open = 1, circuit_breaker_reason = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (reason.strip(), _utc_now()),
            )

    def reserve_x_request(
        self,
        collection_run_id: str,
        *,
        max_resources: int,
    ) -> int:
        if isinstance(max_resources, bool) or not isinstance(max_resources, int) or not (
            1 <= max_resources <= 100
        ):
            raise ValueError("X max_resources 必须在 1 到 100 之间")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            snapshot = self.connection.execute(
                """
                SELECT r.platform, b.*
                FROM collection_runs r
                JOIN x_run_billing_snapshots b
                    ON b.collection_run_id = r.collection_run_id
                WHERE r.collection_run_id = ?
                """,
                (collection_run_id,),
            ).fetchone()
            if snapshot is None or snapshot["platform"] != "x":
                raise ValueError("X 请求必须绑定 X run billing snapshot")
            settings = self.connection.execute(
                "SELECT * FROM x_billing_settings WHERE singleton = 1"
            ).fetchone()
            if settings is None:
                raise RuntimeError("X billing settings are missing")
            if not bool(settings["console_limit_confirmed"]):
                raise XBillingGateError(
                    "X Developer Console hard spending limit 尚未确认"
                )
            if bool(settings["circuit_breaker_open"]):
                raise XBillingGateError(
                    "X 费用熔断器已开启："
                    + str(settings["circuit_breaker_reason"] or "unknown")
                )
            active_price = self.connection.execute(
                """
                SELECT price_snapshot_id FROM x_price_snapshots
                WHERE resource_type = 'post_read' AND active = 1
                """
            ).fetchone()
            if (
                active_price is None
                or active_price["price_snapshot_id"] != snapshot["price_snapshot_id"]
            ):
                self.connection.execute(
                    """
                    UPDATE x_billing_settings
                    SET circuit_breaker_open = 1,
                        circuit_breaker_reason = 'active_price_snapshot_changed',
                        updated_at = ? WHERE singleton = 1
                    """,
                    (_utc_now(),),
                )
                self.connection.commit()
                raise XBillingGateError(
                    "X active price snapshot changed; start a newly priced run"
                )
            now = datetime.now(timezone.utc)
            cycle_start_value = settings["billing_cycle_start"]
            cycle_end_value = settings["billing_cycle_end"]
            if not isinstance(cycle_start_value, str) or not isinstance(
                cycle_end_value, str
            ):
                raise XBillingGateError("X billing cycle 尚未配置")
            cycle_start = _utc_timestamp(
                cycle_start_value, field="X billing_cycle_start"
            )
            cycle_end = _utc_timestamp(
                cycle_end_value, field="X billing_cycle_end"
            )
            if not cycle_start <= now < cycle_end:
                raise XBillingGateError("X billing cycle 当前无效")
            unit_price = int(snapshot["unit_price_microusd"])
            reserved_cost = max_resources * unit_price
            run_exposure = int(self.connection.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN outcome = 'reserved' THEN reserved_cost_microusd
                         ELSE actual_cost_microusd END
                ), 0)
                FROM x_request_events WHERE collection_run_id = ?
                """,
                (collection_run_id,),
            ).fetchone()[0])
            if run_exposure + reserved_cost > int(
                snapshot["local_run_budget_microusd"]
            ):
                raise XBudgetExceeded(
                    "X local run budget exceeded",
                    budget_scope="run",
                )
            cycle_exposure = int(self.connection.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN outcome = 'reserved' THEN reserved_cost_microusd
                         ELSE actual_cost_microusd END
                ), 0)
                FROM x_request_events
                WHERE created_at >= ? AND created_at < ?
                """,
                (cycle_start_value, cycle_end_value),
            ).fetchone()[0])
            cycle_cap = settings["local_cycle_spending_cap_microusd"]
            if not isinstance(cycle_cap, int):
                raise XBillingGateError("X local billing-cycle cap 尚未配置")
            if cycle_exposure + reserved_cost > cycle_cap:
                self.connection.execute(
                    """
                    UPDATE x_billing_settings
                    SET circuit_breaker_open = 1,
                        circuit_breaker_reason = 'local_billing_cycle_cap_exhausted',
                        updated_at = ? WHERE singleton = 1
                    """,
                    (_utc_now(),),
                )
                self.connection.commit()
                raise XBudgetExceeded(
                    "X local billing-cycle budget exceeded",
                    budget_scope="cycle",
                )
            cursor = self.connection.execute(
                """
                INSERT INTO x_request_events(
                    collection_run_id, operation, price_snapshot_id,
                    unit_price_microusd, reserved_resources,
                    reserved_cost_microusd, created_at
                ) VALUES (?, 'recent.search', ?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    snapshot["price_snapshot_id"],
                    unit_price,
                    max_resources,
                    reserved_cost,
                    _utc_now(),
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise

    def finish_x_request(
        self,
        request_event_id: int,
        *,
        outcome: str,
        actual_resources: int,
        error_code: str | None = None,
    ) -> None:
        if outcome not in {"succeeded", "failed", "indeterminate"}:
            raise ValueError("无效的 X 请求结果")
        if (
            isinstance(actual_resources, bool)
            or not isinstance(actual_resources, int)
            or actual_resources < 0
        ):
            raise ValueError("X actual_resources 必须是非负整数")
        if outcome == "failed" and actual_resources != 0:
            raise ValueError("失败的 X 请求不得记录已计费资源")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            event = self.connection.execute(
                """
                SELECT reserved_resources, unit_price_microusd, outcome
                FROM x_request_events WHERE request_event_id = ?
                """,
                (request_event_id,),
            ).fetchone()
            if event is None or event["outcome"] != "reserved":
                raise KeyError(request_event_id)
            if actual_resources > int(event["reserved_resources"]):
                raise ValueError("X actual_resources 超过预留资源数")
            if (
                outcome == "indeterminate"
                and actual_resources != int(event["reserved_resources"])
            ):
                raise ValueError("结果不确定的 X 请求必须按最坏资源数结算")
            actual_cost = actual_resources * int(event["unit_price_microusd"])
            self.connection.execute(
                """
                UPDATE x_request_events
                SET actual_resources = ?, actual_cost_microusd = ?,
                    outcome = ?, error_code = ?, completed_at = ?
                WHERE request_event_id = ?
                """,
                (
                    actual_resources,
                    actual_cost,
                    outcome,
                    error_code,
                    _utc_now(),
                    request_event_id,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def x_request_events(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        if collection_run_id is None:
            rows = self.connection.execute(
                "SELECT * FROM x_request_events ORDER BY request_event_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM x_request_events
                WHERE collection_run_id = ? ORDER BY request_event_id
                """,
                (collection_run_id,),
            ).fetchall()
        output = []
        for row in rows:
            event = dict(row)
            event["unit_price_usd"] = _microusd_text(
                int(event["unit_price_microusd"])
            )
            event["reserved_cost_usd"] = _microusd_text(
                int(event["reserved_cost_microusd"])
            )
            event["actual_cost_usd"] = (
                _microusd_text(int(event["actual_cost_microusd"]))
                if isinstance(event["actual_cost_microusd"], int)
                else None
            )
            output.append(event)
        return output

    def save_youtube_run_state(self, collection_run_id: str, state: dict[str, Any]) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO youtube_run_state(collection_run_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(collection_run_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (collection_run_id, _json(state), _utc_now()),
            )

    def youtube_run_state(self, collection_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT state_json FROM youtube_run_state WHERE collection_run_id = ?",
            (collection_run_id,),
        ).fetchone()
        return json.loads(row["state_json"]) if row is not None else None

    def save_youtube_published_after(self, scope_id: str, published_after: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO youtube_scope_state(scope_id, published_after, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    published_after = MAX(youtube_scope_state.published_after, excluded.published_after),
                    updated_at = excluded.updated_at
                """,
                (scope_id, published_after, _utc_now()),
            )

    def youtube_published_after(self, scope_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT published_after FROM youtube_scope_state WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        return str(row["published_after"]) if row is not None and row["published_after"] else None

    def save_mastodon_instance_state(
        self,
        collection_run_id: str,
        query_id: str,
        observed_instance: str,
        *,
        access_method: str,
        next_page_token: str | None,
        max_status_id_candidate: str | None = None,
        pages_fetched: int,
        statuses_seen: int,
        sightings_count: int,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO mastodon_instance_states(
                    collection_run_id, query_id, observed_instance, access_method,
                    next_page_token, max_status_id_candidate, pages_fetched,
                    statuses_seen, sightings_count,
                    status, error_code, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_run_id, query_id, observed_instance) DO UPDATE SET
                    next_page_token = excluded.next_page_token,
                    max_status_id_candidate = excluded.max_status_id_candidate,
                    pages_fetched = excluded.pages_fetched,
                    statuses_seen = excluded.statuses_seen,
                    sightings_count = excluded.sightings_count,
                    status = excluded.status,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    collection_run_id, query_id, observed_instance, access_method,
                    next_page_token, max_status_id_candidate, pages_fetched,
                    statuses_seen, sightings_count,
                    status, error_code, error_message, _utc_now(),
                ),
            )

    def mastodon_instance_states(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM mastodon_instance_states
            WHERE collection_run_id = ?
            ORDER BY observed_instance, query_id
            """,
            (collection_run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_mastodon_scope_high_watermark(
        self,
        scope_id: str,
        query_id: str,
        observed_instance: str,
        max_status_id: str,
    ) -> None:
        with self.connection:
            current = self.connection.execute(
                """
                SELECT max_status_id FROM mastodon_scope_state
                WHERE scope_id = ? AND query_id = ? AND observed_instance = ?
                """,
                (scope_id, query_id, observed_instance),
            ).fetchone()
            selected = max_status_id
            if current is not None:
                try:
                    selected = str(max(int(current["max_status_id"]), int(max_status_id)))
                except ValueError:
                    selected = max(str(current["max_status_id"]), max_status_id)
            self.connection.execute(
                """
                INSERT INTO mastodon_scope_state(
                    scope_id, query_id, observed_instance, max_status_id, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope_id, query_id, observed_instance) DO UPDATE SET
                    max_status_id = excluded.max_status_id,
                    updated_at = excluded.updated_at
                """,
                (scope_id, query_id, observed_instance, selected, _utc_now()),
            )

    def mastodon_scope_high_watermark(
        self, scope_id: str, query_id: str, observed_instance: str
    ) -> str | None:
        row = self.connection.execute(
            """
            SELECT max_status_id FROM mastodon_scope_state
            WHERE scope_id = ? AND query_id = ? AND observed_instance = ?
            """,
            (scope_id, query_id, observed_instance),
        ).fetchone()
        return str(row["max_status_id"]) if row is not None else None

    def record_mastodon_sighting(
        self,
        observation_id: str,
        collection_run_id: str,
        query_id: str,
        observed_instance: str,
        *,
        local_status_id: str,
        platform_item_id: str,
        status_uri: str | None,
        visibility: str,
        payload: dict[str, Any],
    ) -> bool:
        with self.connection:
            return self.connection.execute(
                """
                INSERT OR IGNORE INTO mastodon_sightings(
                    observation_id, collection_run_id, query_id,
                    observed_instance, local_status_id, platform_item_id,
                    status_uri, visibility, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id, collection_run_id, query_id,
                    observed_instance, local_status_id, platform_item_id,
                    status_uri, visibility, _json(payload), _utc_now(),
                ),
            ).rowcount == 1

    def mastodon_sightings(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM mastodon_sightings
            WHERE collection_run_id = ?
            ORDER BY sighting_id
            """,
            (collection_run_id,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            output.append(item)
        return output

    def save_api_collection_state(
        self,
        collection_run_id: str,
        platform: str,
        query_id: str,
        partition_key: str,
        state: dict[str, Any],
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO api_collection_states(
                    collection_run_id, platform, query_id, partition_key,
                    state_json, status, error_code, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_run_id, query_id, partition_key) DO UPDATE SET
                    state_json = excluded.state_json,
                    status = excluded.status,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    collection_run_id, platform, query_id, partition_key,
                    _json(state), status, error_code, error_message, _utc_now(),
                ),
            )

    def api_collection_states(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM api_collection_states
            WHERE collection_run_id = ?
            ORDER BY platform, partition_key, query_id
            """,
            (collection_run_id,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["state"] = json.loads(item.pop("state_json"))
            output.append(item)
        return output

    def save_api_scope_state(
        self,
        scope_id: str,
        platform: str,
        query_id: str,
        partition_key: str,
        state: dict[str, Any],
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO api_scope_states(
                    scope_id, platform, query_id, partition_key,
                    state_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_id, query_id, partition_key) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (
                    scope_id, platform, query_id, partition_key,
                    _json(state), _utc_now(),
                ),
            )

    def api_scope_state(
        self, scope_id: str, query_id: str, partition_key: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT state_json FROM api_scope_states
            WHERE scope_id = ? AND query_id = ? AND partition_key = ?
            """,
            (scope_id, query_id, partition_key),
        ).fetchone()
        return json.loads(row["state_json"]) if row is not None else None

    def mastodon_observation_sightings(
        self, observation_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM mastodon_sightings
            WHERE observation_id = ?
            ORDER BY observed_instance, sighting_id
            """,
            (observation_id,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            output.append(item)
        return output

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM audit_events ORDER BY audit_id DESC LIMIT ?", (limit,)
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json"))
            output.append(item)
        return output

    def export_data(self, collection_run_id: str) -> dict[str, Any]:
        run = self.get_run(collection_run_id)
        if run is None:
            raise KeyError(collection_run_id)
        manifest = json.loads(run["manifest_json"])
        query_ids = manifest.get("query_ids") or []
        if not isinstance(query_ids, list) or not all(
            isinstance(query_id, str) for query_id in query_ids
        ):
            raise ValueError("run manifest query_ids are invalid")
        observations = [
            json.loads(row["record_json"])
            for row in self.connection.execute(
                """
                SELECT record_json FROM observations
                WHERE collection_run_id = ? ORDER BY created_at, observation_id
                """,
                (collection_run_id,),
            ).fetchall()
        ]
        query_rows = {}
        if query_ids:
            placeholders = ",".join("?" for _ in query_ids)
            query_rows = {
                row["query_id"]: json.loads(row["record_json"])
                for row in self.connection.execute(
                    f"SELECT query_id, record_json FROM queries WHERE query_id IN ({placeholders})",
                    query_ids,
                ).fetchall()
            }
        missing_query_ids = [query_id for query_id in query_ids if query_id not in query_rows]
        if missing_query_ids:
            raise RuntimeError(
                "run query snapshot is missing: " + ", ".join(missing_query_ids)
            )
        queries = [query_rows[query_id] for query_id in query_ids]
        sources = [
            json.loads(row["record_json"])
            for row in self.connection.execute(
                """
                SELECT DISTINCT s.record_json, s.source_id FROM sources s
                JOIN observations o ON o.source_id = s.source_id
                WHERE o.collection_run_id = ? ORDER BY s.source_id
                """,
                (collection_run_id,),
            ).fetchall()
        ]
        tiktok_request_events = self.tiktok_request_events(collection_run_id)
        tiktok_settings = self.connection.execute(
            """
            SELECT daily_request_budget, policy_version, updated_at
            FROM tiktok_quota_settings WHERE singleton = 1
            """
        ).fetchone()
        tiktok_quota_snapshot = {
            "daily_request_budget": int(tiktok_settings["daily_request_budget"]),
            "policy_version": tiktok_settings["policy_version"],
            "reset_timezone": "UTC",
            "settings_updated_at": tiktok_settings["updated_at"],
            "quota_dates": [
                self.tiktok_quota_status(quota_date)
                for quota_date in sorted({
                    event["quota_date"] for event in tiktok_request_events
                })
            ],
        } if tiktok_settings is not None else None
        x_request_events = self.x_request_events(collection_run_id)
        x_run_billing_snapshot = self.x_run_billing_snapshot(collection_run_id)
        x_billing_status = self.x_billing_status()
        return {
            "run": run,
            "manifest": manifest,
            "observations": observations,
            "queries": queries,
            "sources": sources,
            "review_history": [
                row for row in self.review_history()
                if row["collection_run_id"] == collection_run_id
            ],
            "screening_history": self.screening_history(
                collection_run_id=collection_run_id
            ),
            "audit": [
                row for row in self.list_audit(10000)
                if row["entity_id"] == collection_run_id
                or row["details"].get("collection_run_id") == collection_run_id
            ],
            "youtube_quota_usage": [
                dict(row) for row in self.connection.execute(
                    """
                          SELECT quota_event_id, operation, units, quota_date, outcome, created_at,
                              quota_policy_version, quota_bucket
                    FROM youtube_quota_events WHERE collection_run_id = ?
                    ORDER BY quota_event_id
                    """,
                    (collection_run_id,),
                ).fetchall()
            ],
            "run_governance": self.get_run_governance(collection_run_id),
            "run_registry": self.get_run_registry(collection_run_id),
            "run_quota_policy": self.get_run_quota_policy(collection_run_id),
            "independent_annotations": self.independent_annotations(collection_run_id),
            "adjudications": self.adjudications(collection_run_id),
            "quality_reports": self.quality_reports(collection_run_id),
            "query_yield_policy": self.get_run_query_yield_policy(
                collection_run_id
            ),
            "query_yield_reports": self.query_yield_reports(collection_run_id),
            "observation_query_matches": self.observation_query_matches(
                collection_run_id
            ),
            "mastodon_instance_states": self.mastodon_instance_states(
                collection_run_id
            ),
            "mastodon_sightings": [
                {key: value for key, value in row.items() if key != "payload"}
                for row in self.mastodon_sightings(collection_run_id)
            ],
            "api_collection_states": self.api_collection_states(collection_run_id),
            "tiktok_request_events": tiktok_request_events,
            "tiktok_quota_snapshot": tiktok_quota_snapshot,
            "x_request_events": x_request_events,
            "x_run_billing_snapshot": x_run_billing_snapshot,
            "x_billing_status": x_billing_status,
        }

    def record_observation_query_match(
        self,
        observation_id: str,
        collection_run_id: str,
        query_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO observation_query_matches(
                    observation_id, collection_run_id, query_id, context_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (observation_id, collection_run_id, query_id, _json(context), now),
            )
        row = self.connection.execute(
            """
            SELECT * FROM observation_query_matches
            WHERE observation_id = ? AND query_id = ?
            """,
            (observation_id, query_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("observation query match insert failed")
        result = dict(row)
        result["context"] = json.loads(result.pop("context_json"))
        return result

    def observation_query_matches(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM observation_query_matches
            WHERE collection_run_id = ? ORDER BY observation_id, query_id
            """,
            (collection_run_id,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["context"] = json.loads(item.pop("context_json"))
            output.append(item)
        return output

    @staticmethod
    def _schedule_dict(row: sqlite3.Row) -> dict[str, Any]:
        output = dict(row)
        output["enabled"] = bool(output["enabled"])
        return output

    @staticmethod
    def _scope_dict(row: sqlite3.Row) -> dict[str, Any]:
        output = dict(row)
        output["keywords"] = json.loads(output.pop("keywords_json"))
        output["languages"] = json.loads(output.pop("languages_json"))
        output["active"] = bool(output["active"])
        return output

    def create_run(
        self,
        collection_run_id: str,
        manifest: dict[str, Any],
        *,
        scope_id: str | None = None,
        trigger_type: str = "manual",
        parent_collection_run_id: str | None = None,
        schedule_id: str | None = None,
        registry_snapshot: dict[str, Any] | None = None,
        query_yield_policy: dict[str, Any] | None = None,
        query_yield_assessment_mode: str = "retrospective",
        x_billing_binding: dict[str, Any] | None = None,
    ) -> None:
        platform = str(manifest.get("platform") or "")
        if not platform:
            raise ValueError("run manifest requires platform")
        self.connection.execute(
            """
            INSERT INTO collection_runs(
                collection_run_id, platform, manifest_json, status, started_at, scope_id
            ) VALUES (?, ?, ?, 'running', ?, ?)
            ON CONFLICT(collection_run_id) DO UPDATE SET manifest_json = excluded.manifest_json
            """,
            (collection_run_id, platform, _json(manifest), _utc_now(), scope_id),
        )
        self.connection.execute(
            """
            INSERT OR REPLACE INTO run_triggers(
                collection_run_id, trigger_type, parent_collection_run_id,
                schedule_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                collection_run_id, trigger_type, parent_collection_run_id,
                schedule_id, _utc_now(),
            ),
        )
        self.connection.execute(
            """
            INSERT OR IGNORE INTO run_governance(
                collection_run_id, usage_classification, analysis_allowed,
                release_allowed, reason, decided_by, decided_at
            ) VALUES (?, 'research_candidate', 1, 0, ?, 'system', ?)
            """,
            (
                collection_run_id,
                "Local analysis candidate; research release requires a separate quality decision.",
                _utc_now(),
            ),
        )
        if registry_snapshot is None:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO run_registry_snapshots(
                    collection_run_id, binding_status, captured_at
                ) VALUES (?, 'legacy_unbound', ?)
                """,
                (collection_run_id, _utc_now()),
            )
        else:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO run_registry_snapshots(
                    collection_run_id, binding_status,
                    object_map_version, object_map_sha256,
                    codebook_version, codebook_sha256,
                    snapshot_json, captured_at
                ) VALUES (?, 'bound', ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    registry_snapshot["object_map_version"],
                    registry_snapshot["object_map_sha256"],
                    registry_snapshot["codebook_version"],
                    registry_snapshot["codebook_sha256"],
                    _json(registry_snapshot),
                    _utc_now(),
                ),
            )
        if query_yield_policy is not None:
            if query_yield_assessment_mode not in {"preregistered", "retrospective"}:
                raise ValueError("invalid query-yield assessment mode")
            self.connection.execute(
                """
                INSERT OR IGNORE INTO run_query_yield_policies(
                    collection_run_id, assessment_mode, policy_json, captured_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    query_yield_assessment_mode,
                    _json(query_yield_policy),
                    _utc_now(),
                ),
            )
        if x_billing_binding is not None:
            if platform != "x":
                self.connection.rollback()
                raise ValueError("X billing snapshot 只能绑定 X run")
            try:
                self.bind_x_run_billing(
                    collection_run_id,
                    x_billing_binding,
                    commit=False,
                )
            except Exception:
                self.connection.rollback()
                raise
        self.connection.commit()

    def get_run(self, collection_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM collection_runs WHERE collection_run_id = ?",
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return None
        run = dict(row)
        run["quota_policy"] = self.get_run_quota_policy(collection_run_id)
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM collection_runs ORDER BY started_at DESC"
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["manifest"] = json.loads(item.pop("manifest_json"))
            trigger = self.connection.execute(
                "SELECT * FROM run_triggers WHERE collection_run_id = ?",
                (item["collection_run_id"],),
            ).fetchone()
            item["trigger"] = dict(trigger) if trigger is not None else None
            item["run_governance"] = self.get_run_governance(item["collection_run_id"])
            item["run_registry"] = self.get_run_registry(item["collection_run_id"])
            item["quota_policy"] = self.get_run_quota_policy(item["collection_run_id"])
            quality_reports = self.quality_reports(item["collection_run_id"])
            item["latest_quality_report"] = quality_reports[-1] if quality_reports else None
            query_yield_reports = self.query_yield_reports(item["collection_run_id"])
            item["latest_query_yield_report"] = (
                query_yield_reports[-1] if query_yield_reports else None
            )
            output.append(item)
        return output

    def count_scope_runs(self, scope_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM collection_runs WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def get_run_registry(self, collection_run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM run_registry_snapshots WHERE collection_run_id = ?",
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return None
        registry = dict(row)
        snapshot_json = registry.pop("snapshot_json")
        registry["snapshot"] = json.loads(snapshot_json) if snapshot_json else None
        return registry

    def get_run_query_yield_policy(
        self, collection_run_id: str
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT assessment_mode, policy_json, captured_at
            FROM run_query_yield_policies WHERE collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "collection_run_id": collection_run_id,
            "assessment_mode": row["assessment_mode"],
            "policy": json.loads(row["policy_json"]),
            "captured_at": row["captured_at"],
        }

    def _sync_run_manifest(self, collection_run_id: str) -> None:
        row = self.connection.execute(
            """
            SELECT manifest_json, status, completed_at,
                   received_count, normalized_count, failure_count
            FROM collection_runs WHERE collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        if row is None:
            return

        reviewed = bool(self.connection.execute(
            """
            SELECT EXISTS(
                SELECT 1 FROM review_events
                WHERE collection_run_id = ?
                  AND new_status IN ('human_verified', 'excluded')
            )
            """,
            (collection_run_id,),
        ).fetchone()[0])
        manifest = json.loads(row["manifest_json"])
        if reviewed:
            manifest_status = "reviewed"
        elif row["status"] == "failed":
            manifest_status = "closed"
        elif row["status"] in {"completed", "stopped"}:
            manifest_status = "normalized" if row["normalized_count"] else "collected"
        else:
            manifest_status = "planned"

        previous_counts = manifest.get("counts")
        requested = previous_counts.get("requested") if isinstance(previous_counts, dict) else None
        manifest["status"] = manifest_status
        manifest["completed_at"] = row["completed_at"]
        manifest["counts"] = {
            "requested": requested,
            "received": row["received_count"],
            "normalized": row["normalized_count"],
            "failures": row["failure_count"],
            "human_verified": self.connection.execute(
                """
                SELECT COUNT(*) FROM observations
                WHERE collection_run_id = ? AND annotation_status = 'human_verified'
                """,
                (collection_run_id,),
            ).fetchone()[0],
        }
        self.connection.execute(
            "UPDATE collection_runs SET manifest_json = ? WHERE collection_run_id = ?",
            (_json(manifest), collection_run_id),
        )

    def increment_received(self, collection_run_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE collection_runs SET received_count = received_count + 1 WHERE collection_run_id = ?",
                (collection_run_id,),
            )

    def finish_run(self, collection_run_id: str, status: str) -> None:
        completed_at = _utc_now()
        with self.connection:
            self.connection.execute(
                "UPDATE collection_runs SET status = ?, completed_at = ? WHERE collection_run_id = ?",
                (status, completed_at, collection_run_id),
            )
            self._sync_run_manifest(collection_run_id)

    def ingest_observation(
        self,
        record: dict[str, Any],
        raw_event: dict[str, Any],
        *,
        cursor: int,
        source: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically persist evidence, its normalized record, and resume cursor."""

        now = _utc_now()
        values = (
            record["observation_id"],
            record["collection_run_id"],
            record["platform"],
            record["platform_item_id"],
            record["source_id"],
            record["annotation_status"],
            _json(record),
            now,
            now,
        )
        with self.connection:
            event_key = f"{record['platform']}\x1f{cursor}\x1f{record['platform_item_id']}"
            event_inserted = self.connection.execute(
                """
                INSERT OR IGNORE INTO ingested_events(
                    event_key, platform, cursor, platform_item_id,
                    first_collection_run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    record["platform"],
                    cursor,
                    record["platform_item_id"],
                    record["collection_run_id"],
                    now,
                ),
            ).rowcount == 1
            if not event_inserted:
                self.connection.execute(
                    """
                    INSERT INTO collector_cursors(platform, cursor, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(platform) DO UPDATE SET
                        cursor = MAX(collector_cursors.cursor, excluded.cursor),
                        updated_at = excluded.updated_at
                    """,
                    (record["platform"], cursor, now),
                )
                return False
            inserted = self.connection.execute(
                """
                INSERT OR IGNORE INTO observations(
                    observation_id, collection_run_id, platform, platform_item_id,
                    source_id, annotation_status, record_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            ).rowcount == 1
            if inserted:
                if source is not None:
                    self.connection.execute(
                        """
                        INSERT INTO sources(source_id, record_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(source_id) DO UPDATE SET
                            record_json = excluded.record_json,
                            updated_at = excluded.updated_at
                        """,
                        (record["source_id"], _json(source), now, now),
                    )
                self.connection.execute(
                    """
                    INSERT INTO raw_events(
                        observation_id, collection_run_id, platform, platform_item_id,
                        cursor, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["observation_id"],
                        record["collection_run_id"],
                        record["platform"],
                        record["platform_item_id"],
                        cursor,
                        _json(raw_event),
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    UPDATE collection_runs
                    SET normalized_count = normalized_count + 1
                    WHERE collection_run_id = ?
                    """,
                    (record["collection_run_id"],),
                )
                self.connection.execute(
                    """
                    INSERT INTO screening_events(
                        observation_id, collection_run_id, decision, rule_version,
                        signals_json, tool_name, tool_version, decided_by,
                        reason, created_at
                    ) VALUES (?, ?, 'uncertain', 'social_screening_v0.1.0', ?,
                              'GLYPH candidate router', '0.1.0', 'machine', ?, ?)
                    """,
                    (
                        record["observation_id"],
                        record["collection_run_id"],
                        _json({
                            "query_id": record.get("query_id"),
                            "content_status": record.get("content_status"),
                            "language_hint": record.get("language_bcp47"),
                        }),
                        "采集命中仅生成候选；对象—评价关系需人工筛选。",
                        now,
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO collector_cursors(platform, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    cursor = MAX(collector_cursors.cursor, excluded.cursor),
                    updated_at = excluded.updated_at
                """,
                (record["platform"], cursor, now),
            )
        return inserted

    def save_cursor(self, platform: str, cursor: int) -> None:
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO collector_cursors(platform, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    cursor = MAX(collector_cursors.cursor, excluded.cursor),
                    updated_at = excluded.updated_at
                """,
                (platform, cursor, now),
            )

    def record_error(
        self,
        collection_run_id: str | None,
        *,
        cursor: int | None,
        error_code: str,
        message: str,
        payload_sha256: str | None,
        retryable: bool,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO collection_errors(
                    collection_run_id, cursor, error_code, message,
                    payload_sha256, retryable, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id, cursor, error_code, message[:4000],
                    payload_sha256, int(retryable), _utc_now(),
                ),
            )
            if collection_run_id is not None:
                self.connection.execute(
                    """
                    UPDATE collection_runs SET failure_count = failure_count + 1
                    WHERE collection_run_id = ?
                    """,
                    (collection_run_id,),
                )

    def list_errors(self, collection_run_id: str | None = None) -> list[dict[str, Any]]:
        if collection_run_id is None:
            rows = self.connection.execute(
                "SELECT * FROM collection_errors ORDER BY error_id DESC"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM collection_errors
                WHERE collection_run_id = ? ORDER BY error_id DESC
                """,
                (collection_run_id,),
            ).fetchall()
        output = [dict(row) for row in rows]
        for item in output:
            item["retryable"] = bool(item["retryable"])
        return output

    def get_cursor(self, platform: str) -> int | None:
        row = self.connection.execute(
            "SELECT cursor FROM collector_cursors WHERE platform = ?", (platform,)
        ).fetchone()
        return int(row["cursor"]) if row is not None else None

    def get_observation(self, observation_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM observations WHERE observation_id = ?", (observation_id,)
        ).fetchone()

    def list_observations(self, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self.connection.execute(
                "SELECT record_json FROM observations ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT record_json FROM observations
                WHERE annotation_status = ? ORDER BY created_at, observation_id
                """,
                (status,),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def list_review_candidates(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT o.record_json
            FROM observations o
            JOIN run_governance g ON g.collection_run_id = o.collection_run_id
            JOIN run_registry_snapshots rs ON rs.collection_run_id = o.collection_run_id
                        JOIN screening_events se ON se.screening_id = (
                                SELECT MAX(latest.screening_id)
                                FROM screening_events latest
                                WHERE latest.observation_id = o.observation_id
                        )
            WHERE o.annotation_status = 'candidate'
              AND g.analysis_allowed = 1
              AND rs.binding_status = 'bound'
              AND se.decision = 'include'
              AND (? IS NULL OR o.collection_run_id = ?)
            ORDER BY o.created_at, o.observation_id
            """,
            (collection_run_id, collection_run_id),
        ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def list_screening_candidates(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT o.record_json
            FROM observations o
            JOIN run_governance g ON g.collection_run_id = o.collection_run_id
            JOIN run_registry_snapshots rs ON rs.collection_run_id = o.collection_run_id
            JOIN screening_events se ON se.screening_id = (
                SELECT MAX(latest.screening_id)
                FROM screening_events latest
                WHERE latest.observation_id = o.observation_id
            )
            WHERE o.annotation_status = 'candidate'
              AND g.analysis_allowed = 1
              AND rs.binding_status = 'bound'
              AND se.decision = 'uncertain'
                            AND (? IS NULL OR o.collection_run_id = ?)
            ORDER BY o.created_at, o.observation_id
                        """,
                        (collection_run_id, collection_run_id),
        ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def record_screening(
        self,
        observation_id: str,
        *,
        decision: str,
        rule_version: str,
        signals: dict[str, Any],
        tool_name: str,
        tool_version: str,
        decided_by: str,
        reason: str,
    ) -> dict[str, Any]:
        if decision not in {"include", "exclude", "uncertain"}:
            raise ValueError("无效相关性筛选决定")
        if not reason.strip():
            raise ValueError("相关性筛选必须填写理由")
        observation = self.get_observation(observation_id)
        if observation is None:
            raise KeyError(observation_id)
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO screening_events(
                    observation_id, collection_run_id, decision, rule_version,
                    signals_json, tool_name, tool_version, decided_by,
                    reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id, observation["collection_run_id"], decision,
                    rule_version, _json(signals), tool_name, tool_version,
                    decided_by, reason.strip(), _utc_now(),
                ),
            )
        row = self.connection.execute(
            "SELECT * FROM screening_events WHERE screening_id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return self._screening_dict(row)

    def latest_screening(self, observation_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT * FROM screening_events
            WHERE observation_id = ? ORDER BY screening_id DESC LIMIT 1
            """,
            (observation_id,),
        ).fetchone()
        return self._screening_dict(row) if row is not None else None

    def screening_history(
        self,
        observation_id: str | None = None,
        *,
        collection_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if observation_id is not None:
            rows = self.connection.execute(
                """
                SELECT * FROM screening_events
                WHERE observation_id = ? ORDER BY screening_id DESC
                """,
                (observation_id,),
            ).fetchall()
        elif collection_run_id is not None:
            rows = self.connection.execute(
                """
                SELECT * FROM screening_events
                WHERE collection_run_id = ? ORDER BY screening_id
                """,
                (collection_run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM screening_events ORDER BY screening_id DESC"
            ).fetchall()
        return [self._screening_dict(row) for row in rows]

    def record_independent_annotation(
        self,
        observation_id: str,
        coder_id: str,
        annotation: dict[str, Any],
        *,
        object_map_sha256: str,
        codebook_sha256: str,
    ) -> dict[str, Any]:
        observation = self.get_observation(observation_id)
        if observation is None:
            raise KeyError(observation_id)
        now = _utc_now()
        try:
            with self.connection:
                cursor = self.connection.execute(
                    """
                    INSERT INTO independent_annotations(
                        observation_id, collection_run_id, coder_id,
                        annotation_json, object_map_sha256, codebook_sha256,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        observation["collection_run_id"],
                        coder_id,
                        _json(annotation),
                        object_map_sha256,
                        codebook_sha256,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("同一编码员不能重复提交该 observation 的独立编码") from error
        return self._independent_annotation(int(cursor.lastrowid))

    def _independent_annotation(self, annotation_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM independent_annotations WHERE annotation_id = ?",
            (annotation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(annotation_id)
        output = dict(row)
        output.update(json.loads(output.pop("annotation_json")))
        return output

    def independent_annotations(
        self, collection_run_id: str, observation_id: str | None = None
    ) -> list[dict[str, Any]]:
        if observation_id is None:
            rows = self.connection.execute(
                """
                SELECT annotation_id FROM independent_annotations
                WHERE collection_run_id = ? ORDER BY annotation_id
                """,
                (collection_run_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT annotation_id FROM independent_annotations
                WHERE collection_run_id = ? AND observation_id = ?
                ORDER BY annotation_id
                """,
                (collection_run_id, observation_id),
            ).fetchall()
        return [self._independent_annotation(int(row[0])) for row in rows]

    def record_adjudication(
        self,
        observation_id: str,
        adjudicator_id: str,
        adjudication: dict[str, Any],
        reason: str,
        gold_record: dict[str, Any],
    ) -> dict[str, Any]:
        observation = self.get_observation(observation_id)
        if observation is None:
            raise KeyError(observation_id)
        previous = json.loads(observation["record_json"])
        now = _utc_now()
        try:
            with self.connection:
                cursor = self.connection.execute(
                    """
                    INSERT INTO adjudications(
                        observation_id, collection_run_id, adjudicator_id,
                        adjudication_json, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        observation["collection_run_id"],
                        adjudicator_id,
                        _json(adjudication),
                        reason,
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    UPDATE observations
                    SET annotation_status = ?, record_json = ?, updated_at = ?
                    WHERE observation_id = ?
                    """,
                    (
                        gold_record["annotation_status"],
                        _json(gold_record),
                        now,
                        observation_id,
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO review_events(
                        observation_id, collection_run_id, reviewer_ref,
                        previous_status, new_status, previous_record_json,
                        new_record_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_id,
                        observation["collection_run_id"],
                        adjudicator_id,
                        previous["annotation_status"],
                        gold_record["annotation_status"],
                        _json(previous),
                        _json(gold_record),
                        now,
                    ),
                )
                self._sync_run_manifest(observation["collection_run_id"])
        except sqlite3.IntegrityError as error:
            raise ValueError("该 observation 已完成裁决，不能覆盖") from error
        row = self.connection.execute(
            "SELECT * FROM adjudications WHERE adjudication_id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        output = dict(row)
        output.update(json.loads(output.pop("adjudication_json")))
        return output

    def adjudications(self, collection_run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM adjudications
            WHERE collection_run_id = ? ORDER BY adjudication_id
            """,
            (collection_run_id,),
        ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item.update(json.loads(item.pop("adjudication_json")))
            output.append(item)
        return output

    def record_quality_report(
        self, collection_run_id: str, report: dict[str, Any]
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            agreement = self.connection.execute(
                """
                INSERT INTO agreement_reports(collection_run_id, report_json, created_at)
                VALUES (?, ?, ?)
                """,
                (collection_run_id, _json(report["agreement"]), now),
            )
            quality = self.connection.execute(
                """
                INSERT INTO run_quality_reports(
                    collection_run_id, status, report_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (collection_run_id, report["status"], _json(report), now),
            )
        return {
            **report,
            "agreement_report_id": int(agreement.lastrowid),
            "quality_report_id": int(quality.lastrowid),
            "created_at": now,
        }

    def quality_reports(self, collection_run_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT quality_report_id, report_json, created_at
            FROM run_quality_reports
            WHERE collection_run_id = ? ORDER BY quality_report_id
            """,
            (collection_run_id,),
        ).fetchall()
        return [
            {
                **json.loads(row["report_json"]),
                "quality_report_id": row["quality_report_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_query_yield_report(
        self,
        collection_run_id: str,
        report: dict[str, Any],
        evidence_revision: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO query_yield_reports(
                    collection_run_id, status, report_json,
                    evidence_revision_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    collection_run_id,
                    report["status"],
                    _json(report),
                    _json(evidence_revision),
                    now,
                ),
            )
        return {
            **report,
            "query_yield_report_id": int(cursor.lastrowid),
            "evidence_revision": evidence_revision,
            "created_at": now,
        }

    def query_yield_reports(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT query_yield_report_id, report_json,
                   evidence_revision_json, created_at
            FROM query_yield_reports
            WHERE collection_run_id = ? ORDER BY query_yield_report_id
            """,
            (collection_run_id,),
        ).fetchall()
        return [
            {
                **json.loads(row["report_json"]),
                "query_yield_report_id": row["query_yield_report_id"],
                "evidence_revision": json.loads(row["evidence_revision_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def query_yield_evidence_revision(
        self, collection_run_id: str
    ) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT
                r.status AS run_status,
                (SELECT COUNT(*) FROM observation_query_matches m
                 WHERE m.collection_run_id = r.collection_run_id)
                    AS query_match_count,
                (SELECT COALESCE(MAX(s.screening_id), 0) FROM screening_events s
                 WHERE s.collection_run_id = r.collection_run_id)
                    AS max_screening_id,
                (SELECT COUNT(*) FROM screening_events s
                 WHERE s.collection_run_id = r.collection_run_id)
                    AS screening_count
            FROM collection_runs r
            WHERE r.collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(collection_run_id)
        return dict(row)

    def quality_evidence_revision(self, collection_run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT
                r.status AS run_status,
                g.usage_classification,
                g.analysis_allowed,
                (SELECT COUNT(*) FROM observations o
                 WHERE o.collection_run_id = r.collection_run_id) AS observation_count,
                (SELECT COALESCE(MAX(s.screening_id), 0) FROM screening_events s
                 WHERE s.collection_run_id = r.collection_run_id) AS max_screening_id,
                (SELECT COUNT(*) FROM screening_events s
                 WHERE s.collection_run_id = r.collection_run_id) AS screening_count,
                (SELECT COALESCE(MAX(v.review_id), 0) FROM review_events v
                 WHERE v.collection_run_id = r.collection_run_id) AS max_review_id,
                (SELECT COUNT(*) FROM review_events v
                 WHERE v.collection_run_id = r.collection_run_id) AS review_count,
                (SELECT COALESCE(MAX(a.annotation_id), 0) FROM independent_annotations a
                 WHERE a.collection_run_id = r.collection_run_id) AS max_annotation_id,
                (SELECT COUNT(*) FROM independent_annotations a
                 WHERE a.collection_run_id = r.collection_run_id) AS annotation_count,
                (SELECT COALESCE(MAX(d.adjudication_id), 0) FROM adjudications d
                 WHERE d.collection_run_id = r.collection_run_id) AS max_adjudication_id,
                (SELECT COUNT(*) FROM adjudications d
                 WHERE d.collection_run_id = r.collection_run_id) AS adjudication_count
            FROM collection_runs r
            JOIN run_governance g USING(collection_run_id)
            WHERE r.collection_run_id = ?
            """,
            (collection_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(collection_run_id)
        revision = dict(row)
        revision["analysis_allowed"] = bool(revision["analysis_allowed"])
        return revision

    @staticmethod
    def _screening_dict(row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        event["signals"] = json.loads(event.pop("signals_json"))
        return event

    def list_analysis_observations(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT o.record_json
            FROM observations o
            JOIN run_governance g ON g.collection_run_id = o.collection_run_id
                        JOIN run_registry_snapshots rs ON rs.collection_run_id = o.collection_run_id
            WHERE o.annotation_status = 'human_verified'
              AND g.analysis_allowed = 1
                            AND rs.binding_status = 'bound'
            ORDER BY o.created_at, o.observation_id
            """
        ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def update_observation(self, record: dict[str, Any], reviewer_ref: str) -> None:
        current = self.get_observation(record["observation_id"])
        if current is None:
            raise KeyError(record["observation_id"])
        previous = json.loads(current["record_json"])
        now = _utc_now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE observations
                SET annotation_status = ?, record_json = ?, updated_at = ?
                WHERE observation_id = ?
                """,
                (record["annotation_status"], _json(record), now, record["observation_id"]),
            )
            self.connection.execute(
                """
                INSERT INTO review_events(
                    observation_id, collection_run_id, reviewer_ref,
                    previous_status, new_status, previous_record_json,
                    new_record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["observation_id"], record["collection_run_id"], reviewer_ref,
                    previous["annotation_status"], record["annotation_status"],
                    _json(previous), _json(record), now,
                ),
            )
            self._sync_run_manifest(record["collection_run_id"])

    def review_history(self, observation_id: str | None = None) -> list[dict[str, Any]]:
        if observation_id is None:
            rows = self.connection.execute(
                "SELECT * FROM review_events ORDER BY review_id DESC"
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM review_events WHERE observation_id = ?
                ORDER BY review_id DESC
                """,
                (observation_id,),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["previous_record"] = json.loads(item.pop("previous_record_json"))
            item["new_record"] = json.loads(item.pop("new_record_json"))
            output.append(item)
        return output

    def evidence(self, observation_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT o.record_json, r.payload_json, q.record_json AS query_json,
                   s.record_json AS source_json, cr.manifest_json,
                   cr.received_count, cr.normalized_count, cr.failure_count
            FROM observations o
            JOIN raw_events r ON r.observation_id = o.observation_id
            JOIN collection_runs cr ON cr.collection_run_id = o.collection_run_id
            LEFT JOIN queries q ON q.query_id = json_extract(o.record_json, '$.query_id')
            LEFT JOIN sources s ON s.source_id = o.source_id
            WHERE o.observation_id = ?
            """,
            (observation_id,),
        ).fetchone()
        if row is None:
            return None
        observation = json.loads(row["record_json"])
        manifest = json.loads(row["manifest_json"])
        manifest["counts"] = {
            "requested": None,
            "received": row["received_count"],
            "normalized": row["normalized_count"],
            "failures": row["failure_count"],
            "human_verified": self.connection.execute(
                """
                SELECT COUNT(*) FROM observations
                WHERE collection_run_id = ? AND annotation_status = 'human_verified'
                """,
                (observation["collection_run_id"],),
            ).fetchone()[0],
        }
        return {
            "observation": observation,
            "raw_event": json.loads(row["payload_json"]),
            "query": json.loads(row["query_json"]) if row["query_json"] else None,
            "source": json.loads(row["source_json"]) if row["source_json"] else None,
            "run_manifest": manifest,
            "run_governance": self.get_run_governance(observation["collection_run_id"]),
            "run_registry": self.get_run_registry(observation["collection_run_id"]),
            "screening_history": self.screening_history(observation["observation_id"]),
            "mastodon_sightings": self.mastodon_observation_sightings(
                observation["observation_id"]
            ),
        }

    def table_count(self, table: str) -> int:
        allowed = {
            "collection_runs", "observations", "raw_events", "collector_cursors",
            "research_scopes", "queries", "sources", "collection_errors",
            "review_events", "ingested_events", "schedules", "run_triggers",
            "audit_events",
            "youtube_quota_settings", "youtube_quota_events",
            "youtube_run_state", "youtube_scope_state", "run_governance",
            "run_registry_snapshots",
            "youtube_run_quota_policies",
            "screening_events",
            "independent_annotations", "adjudications", "agreement_reports",
            "run_quality_reports",
            "mastodon_instance_states", "mastodon_scope_state",
            "mastodon_sightings",
            "observation_query_matches",
            "api_collection_states", "api_scope_states",
            "tiktok_quota_settings", "tiktok_request_events",
            "x_price_snapshots", "x_billing_settings",
            "x_run_billing_snapshots", "x_request_events",
        }
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def monitoring(self) -> dict[str, Any]:
        database_bytes = self.path.stat().st_size if self.path.exists() else 0
        wal_path = self.path.with_name(self.path.name + "-wal")
        disk = shutil.disk_usage(self.path.parent)
        run_status = {
            row["status"]: int(row["count"])
            for row in self.connection.execute(
                "SELECT status, COUNT(*) AS count FROM collection_runs GROUP BY status"
            ).fetchall()
        }
        review_status = {
            row["annotation_status"]: int(row["count"])
            for row in self.connection.execute(
                """
                SELECT annotation_status, COUNT(*) AS count
                FROM observations GROUP BY annotation_status
                """
            ).fetchall()
        }
        mastodon_state_counts = {
            row["status"]: int(row["count"])
            for row in self.connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM mastodon_instance_states GROUP BY status
                """
            ).fetchall()
        }
        mastodon_instances = []
        for row in self.connection.execute(
            """
            SELECT observed_instance, COUNT(*) AS run_queries,
                   SUM(status = 'completed') AS completed,
                   SUM(status = 'failed') AS failed,
                   SUM(sightings_count) AS sightings,
                   MAX(updated_at) AS latest_update
            FROM mastodon_instance_states
            GROUP BY observed_instance ORDER BY observed_instance
            """
        ).fetchall():
            mastodon_instances.append(dict(row))
        bounded_api_state_counts: dict[str, dict[str, int]] = {}
        for row in self.connection.execute(
            """
            SELECT platform, status, COUNT(*) AS count
            FROM api_collection_states
            GROUP BY platform, status ORDER BY platform, status
            """
        ).fetchall():
            bounded_api_state_counts.setdefault(row["platform"], {})[
                row["status"]
            ] = int(row["count"])
        bounded_api_partitions = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT platform, partition_key, COUNT(*) AS run_queries,
                       SUM(status = 'completed') AS completed,
                       SUM(status = 'failed') AS failed,
                       MAX(updated_at) AS latest_update
                FROM api_collection_states
                GROUP BY platform, partition_key
                ORDER BY platform, partition_key
                """
            ).fetchall()
        ]
        return {
            "database_bytes": database_bytes,
            "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
            "disk_free_bytes": disk.free,
            "run_status": run_status,
            "review_status": review_status,
            "error_count": self.table_count("collection_errors"),
            "retryable_error_count": int(self.connection.execute(
                "SELECT COUNT(*) FROM collection_errors WHERE retryable = 1"
            ).fetchone()[0]),
            "mastodon": {
                "state_counts": mastodon_state_counts,
                "sightings": self.table_count("mastodon_sightings"),
                "instances": mastodon_instances,
            },
            "bounded_api": {
                "state_counts": bounded_api_state_counts,
                "partitions": bounded_api_partitions,
            },
            "schedules": self.list_schedules(),
        }
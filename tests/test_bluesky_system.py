from __future__ import annotations

import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.bluesky import ResearchScope, normalize_jetstream_event
from glyph_features.social_system.cli import build_parser, main
from glyph_features.social_system.collector import BlueskyCollector
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.web import create_app
from tools.social_io import validation_errors, validator


def _observation(run_id: str = "social_run_bluesky_test") -> dict:
    return {
        "observation_id": "obs_bluesky_test_001",
        "collection_run_id": run_id,
        "platform": "bluesky",
        "platform_item_id": "at://did:plc:test/app.bsky.feed.post/abc123",
        "source_id": "src_bluesky_test_001",
        "url": "https://bsky.app/profile/did:plc:test/post/abc123",
        "annotation_status": "unannotated",
    }


def _v2_post_event() -> dict:
    return {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#commit",
            "did": "did:plc:example",
            "seq": 24664288881,
            "time": "2026-09-02T08:30:00Z",
            "operation": "create",
            "collection": "app.bsky.feed.post",
            "rkey": "3abc123",
            "cid": "bafyexample",
            "record": {
                "$type": "app.bsky.feed.post",
                "createdAt": "2026-09-02T08:29:59Z",
                "langs": ["en"],
                "text": "This typography and wordmark study feels modern and premium.",
            },
        },
    }

def _include_first_screening(service: SocialNarrativeService) -> str:
    observation_id = service.screening_queue()[0]["observation_id"]
    service.screen_observation(
        observation_id,
        decision="include",
        reason="fixture 明确包含对象—评价关系。",
    )
    return observation_id


def test_store_ingest_is_idempotent_and_cursor_survives_restart(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    run_id = "social_run_bluesky_test"
    raw_event = {"time_us": 1_788_225_600_000_000, "kind": "commit"}

    with ResearchStore(database) as store:
        store.create_run(run_id, {"collection_run_id": run_id, "platform": "bluesky"})
        assert store.ingest_observation(_observation(), raw_event, cursor=raw_event["time_us"])
        assert not store.ingest_observation(_observation(), raw_event, cursor=raw_event["time_us"])
        assert store.table_count("observations") == 1
        assert store.table_count("raw_events") == 1

    with ResearchStore(database) as reopened:
        assert reopened.get_cursor("bluesky") == raw_event["time_us"]
        stored = reopened.get_observation("obs_bluesky_test_001")
        assert stored is not None
        assert json.loads(stored["record_json"])["platform_item_id"] == _observation()["platform_item_id"]


def test_store_serializes_concurrent_first_migration(tmp_path: Path):
    database = tmp_path / "concurrent.sqlite3"

    def open_store(_: int) -> int:
        with ResearchStore(database) as store:
            return store.table_count("research_scopes")

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(open_store, range(4))) == [0, 0, 0, 0]


def test_v2_jetstream_post_is_filtered_and_normalized_to_existing_schema():
    scope = ResearchScope(
        query_id="q_bluesky_typography_en",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography", "wordmark"),
        languages=("en",),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        exact_query='"Latin typography" premium',
    )
    event = _v2_post_event()

    record = normalize_jetstream_event(
        event,
        scope=scope,
        collection_run_id="social_run_bluesky_test",
        normalized_at="2026-09-02T08:30:00Z",
    )

    assert record is not None
    assert record["platform_item_id"] == "at://did:plc:example/app.bsky.feed.post/3abc123"
    assert record["url"] == "https://bsky.app/profile/did:plc:example/post/3abc123"
    assert record["annotation_status"] == "candidate"
    assert record["object_type"] is None
    assert record["object_label"] is None
    assert record["query_id"] == scope.query_id
    assert record["query_text"] == '"Latin typography" premium'
    assert validation_errors(record, validator()) == []

    event["payload"]["record"]["langs"] = ["fr"]
    assert normalize_jetstream_event(
        event,
        scope=scope,
        collection_run_id="social_run_bluesky_test",
        normalized_at="2026-09-02T08:30:00Z",
    ) is None
    event["payload"]["record"]["langs"] = ["en"]
    event["payload"]["record"]["text"] = "The interface was typographically designed."
    assert normalize_jetstream_event(
        event,
        scope=scope,
        collection_run_id="social_run_bluesky_test",
        normalized_at="2026-09-02T08:30:00Z",
    ) is None


def test_service_closes_scope_review_analysis_and_evidence_loop(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="拉丁字形叙事",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography", "wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_event(run["collection_run_id"], _v2_post_event())
    assert not service.process_event(run["collection_run_id"], _v2_post_event())
    service.finish_run(run["collection_run_id"], "completed")

    before = service.analysis()
    assert before["included_records"] == 0
    _include_first_screening(service)
    queue = service.review_queue()
    assert len(queue) == 1

    reviewed = service.review_observation(
        queue[0]["observation_id"],
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern", "premium"],
        evidence_span="typography and wordmark study feels modern and premium",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )
    assert reviewed["annotation_status"] == "human_verified"
    assert validation_errors(reviewed, validator()) == []

    after = service.analysis()
    assert after["included_records"] == 1
    assert {row["term"] for row in after["matrix_a"]} == {"modern", "premium"}
    evidence = service.evidence(reviewed["observation_id"])
    assert evidence["observation"]["observation_id"] == reviewed["observation_id"]
    assert evidence["raw_event"]["payload"]["seq"] == 24664288881
    assert evidence["query"]["query_id"] == scope["query_id"]
    assert evidence["source"]["source_id"] == reviewed["source_id"]
    assert evidence["run_manifest"]["collection_run_id"] == run["collection_run_id"]
    assert evidence["run_manifest"]["status"] == "reviewed"
    assert evidence["run_manifest"]["completed_at"] is not None
    assert evidence["run_manifest"]["counts"] == {
        "requested": None,
        "received": 2,
        "normalized": 1,
        "failures": 0,
        "human_verified": 1,
    }

    with ResearchStore(service.database_path) as store:
        stored_run = store.get_run(run["collection_run_id"])
        assert stored_run is not None
        assert json.loads(stored_run["manifest_json"]) == evidence["run_manifest"]


def test_same_jetstream_event_is_idempotent_across_runs(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="跨运行重放测试",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
    )
    first_run = service.start_run(scope["scope_id"])
    second_run = service.start_run(scope["scope_id"])

    assert service.process_event(first_run["collection_run_id"], _v2_post_event())
    assert not service.process_event(second_run["collection_run_id"], _v2_post_event())
    with ResearchStore(service.database_path) as store:
        assert store.table_count("observations") == 1
        assert store.table_count("ingested_events") == 1


class _FakeConnection:
    def __init__(self, messages: list[dict], terminal_error: Exception | None = None):
        self.messages = [json.dumps(message) for message in messages]
        self.terminal_error = terminal_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.messages:
            return self.messages.pop(0)
        if self.terminal_error is not None:
            error = self.terminal_error
            self.terminal_error = None
            raise error
        raise StopAsyncIteration


def test_collector_reconnects_from_cursor_and_ignores_inclusive_replay(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="实时恢复测试",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
    )
    run = service.start_run(scope["scope_id"])
    first = _v2_post_event()
    second = copy.deepcopy(first)
    second["payload"]["seq"] += 1
    second["payload"]["rkey"] = "3abc124"
    connections = [
        _FakeConnection([first], ConnectionError("test disconnect")),
        _FakeConnection([first, second]),
    ]
    urls: list[str] = []
    proxies: list[str | None] = []

    def connect(url: str, **kwargs):
        urls.append(url)
        proxies.append(kwargs.get("proxy"))
        return connections.pop(0)

    async def no_sleep(delay: float):
        return None

    collector = BlueskyCollector(
        service,
        proxy_url="http://127.0.0.1:7897",
        connection_factory=connect,
        sleep=no_sleep,
    )
    result = asyncio.run(collector.run(run["collection_run_id"], max_items=2))

    assert result == {"status": "completed", "inserted": 2}
    assert f"cursor={first['payload']['seq']}" in urls[1]
    assert proxies == ["http://127.0.0.1:7897", "http://127.0.0.1:7897"]
    with ResearchStore(service.database_path) as store:
        assert store.table_count("observations") == 2
    errors = service.errors(run["collection_run_id"])
    assert len(errors) == 1
    assert errors[0]["error_code"] == "connection_error"
    assert errors[0]["retryable"] is True


def test_cli_reads_outbound_proxy_from_environment(monkeypatch):
    monkeypatch.setenv("GLYPH_OUTBOUND_PROXY", "http://127.0.0.1:7897")
    args = build_parser().parse_args(["serve"])
    assert args.proxy == "http://127.0.0.1:7897"


def test_cli_creates_verified_database_backup(tmp_path: Path, capsys):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    assert main([
        "backup", "--database", str(database), "--backup-root", str(backup_root)
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["integrity_check"] == "ok"
    assert output["schema_version"] == SCHEMA_VERSION
    assert (backup_root / output["backup_id"] / "glyph-social.sqlite3").is_file()


def test_schedules_persist_and_can_be_disabled(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="持续采集范围",
        object_type="style_family",
        object_label="sans",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )

    schedule = service.create_schedule(
        scope["scope_id"], interval_minutes=30, enabled=True
    )
    assert schedule["scope_id"] == scope["scope_id"]
    assert schedule["interval_minutes"] == 30
    assert schedule["enabled"] is True

    reopened = SocialNarrativeService(database)
    assert reopened.list_schedules() == [schedule]
    disabled = reopened.update_schedule(
        schedule["schedule_id"], interval_minutes=60, enabled=False
    )
    assert disabled["interval_minutes"] == 60
    assert disabled["enabled"] is False
    assert reopened.list_schedules()[0] == disabled


def test_web_restores_enabled_schedule_jobs(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="调度恢复",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2027-09-03T00:00:00Z",
        max_items=5,
    )
    schedule = service.create_schedule(
        scope["scope_id"], interval_minutes=30, enabled=True
    )

    app = create_app(database, outbound_proxy="http://127.0.0.1:7897")
    with TestClient(app) as client:
        assert app.state.collectors.scheduler.get_job(schedule["schedule_id"]) is not None
        health = client.get("/api/health").json()
        assert health["scheduler_running"] is True
        assert health["enabled_schedules"] == 1
        disabled = client.put(
            f"/api/schedules/{schedule['schedule_id']}",
            json={"interval_minutes": 30, "enabled": False},
        )
        assert disabled.status_code == 200
        assert app.state.collectors.scheduler.get_job(schedule["schedule_id"]) is None


def test_scope_archival_disables_schedule_and_retry_keeps_lineage(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="可归档范围",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2027-09-03T00:00:00Z",
        max_items=5,
    )
    schedule = service.create_schedule(
        scope["scope_id"], interval_minutes=30, enabled=True
    )
    first = service.start_run(scope["scope_id"])
    service.finish_run(first["collection_run_id"], "failed")
    retry = service.start_run(
        scope["scope_id"],
        trigger_type="retry",
        parent_collection_run_id=first["collection_run_id"],
    )
    service.finish_run(retry["collection_run_id"], "stopped")

    updated = service.update_scope(
        scope["scope_id"],
        name="已归档范围",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography", "wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2027-09-03T00:00:00Z",
        max_items=10,
        active=False,
    )
    assert updated["active"] is False
    assert service.get_schedule(schedule["schedule_id"])["enabled"] is False
    retry_row = next(
        row for row in service.list_runs()
        if row["collection_run_id"] == retry["collection_run_id"]
    )
    assert retry_row["trigger"]["trigger_type"] == "retry"
    assert retry_row["trigger"]["parent_collection_run_id"] == first["collection_run_id"]
    assert any(event["event_type"] == "scope_updated" for event in service.audit())


def test_schedule_can_trigger_a_bounded_audited_run(tmp_path: Path, monkeypatch):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="即时调度",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2027-09-03T00:00:00Z",
        max_items=5,
    )
    schedule = service.create_schedule(
        scope["scope_id"], interval_minutes=30, enabled=True
    )

    async def finish_immediately(collector, collection_run_id, *, max_items):
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(BlueskyCollector, "run", finish_immediately)
    with TestClient(create_app(database)) as client:
        response = client.post(f"/api/schedules/{schedule['schedule_id']}/run")
        assert response.status_code == 202
        run_id = response.json()["collection_run_id"]
        stored_schedule = client.get("/api/schedules").json()[0]
        assert stored_schedule["last_collection_run_id"] == run_id
        run = next(row for row in client.get("/api/runs").json() if row["collection_run_id"] == run_id)
        assert run["trigger"]["trigger_type"] == "scheduled"
        assert run["trigger"]["schedule_id"] == schedule["schedule_id"]


def test_completed_run_exports_a_valid_research_package(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    export_root = tmp_path / "exports"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="导出范围",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )
    run = service.start_run(scope["scope_id"])
    run_id = run["collection_run_id"]
    assert service.process_event(run_id, _v2_post_event())
    observation_id = _include_first_screening(service)
    service.review_observation(
        observation_id,
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern"],
        evidence_span="typography and wordmark study feels modern and premium",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )
    service.finish_run(run_id, "completed")

    result = service.export_run(run_id, export_root)
    export_dir = Path(result["directory"])
    assert result["valid"] is True
    assert result["record_count"] == 1
    assert result["narrative_count"] == 1
    assert Path(result["archive"]).is_file()
    assert json.loads((export_dir / "validation.json").read_text())["valid"] is True
    assert (export_dir / "matrices" / "matrix_b_object_given_term.csv").is_file()
    assert (export_dir / "matrices" / "time_series.csv").is_file()


def test_backup_restore_recovers_reviews_cursor_and_audit(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="备份恢复",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_event(run["collection_run_id"], _v2_post_event())
    observation_id = _include_first_screening(service)
    service.review_observation(
        observation_id,
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern"],
        evidence_span="typography and wordmark study feels modern and premium",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )
    service.finish_run(run["collection_run_id"], "completed")
    backed_up_cursor = service.cursor()
    backup = service.create_backup(backup_root)

    service.review_observation(
        observation_id,
        status="candidate",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=[],
        evidence_span=None,
        stance=None,
        confidence=None,
        exclusion_reason=None,
    )
    with ResearchStore(database) as store:
        store.save_cursor("bluesky", backed_up_cursor + 100)

    restored = service.restore_backup(backup_root, backup["backup_id"])
    assert restored["integrity_check"] == "ok"
    assert restored["pre_restore_backup_id"] != backup["backup_id"]
    assert service.cursor() == backed_up_cursor
    assert service.observations("human_verified")[0]["observation_id"] == observation_id
    assert any(event["event_type"] == "database_restored" for event in service.audit())
    assert len(service.list_backups(backup_root)) == 2


def test_restore_rejects_a_tampered_backup(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    backup = service.create_backup(backup_root)
    backup_database = backup_root / backup["backup_id"] / "glyph-social.sqlite3"
    backup_database.write_bytes(backup_database.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        service.restore_backup(backup_root, backup["backup_id"])
    with ResearchStore(database) as store:
        assert store.table_count("audit_events") >= 2


def test_analysis_and_monitoring_expose_verified_operational_views(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="分析监控",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_event(run["collection_run_id"], _v2_post_event())
    observation_id = _include_first_screening(service)
    service.review_observation(
        observation_id,
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern"],
        evidence_span="typography and wordmark study feels modern and premium",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )
    service.finish_run(run["collection_run_id"], "completed")

    analysis = service.analysis()
    assert analysis["matrix_b"][0]["p_object_given_term"] == "1.00000000"
    assert analysis["time_series"][0]["time_bucket"] == "2026-08-31"
    assert analysis["platform_summary"] == [{"platform": "bluesky", "record_count": 1}]
    monitoring = service.monitoring(tmp_path / "backups")
    assert monitoring["database_bytes"] > 0
    assert monitoring["review_status"]["human_verified"] == 1
    assert monitoring["api_cost"] == 0
    assert "max_items" in monitoring["quota_basis"]


def test_web_api_connects_scope_review_analysis_and_evidence(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    client = TestClient(create_app(database, outbound_proxy="http://127.0.0.1:7897"))
    home = client.get("/")
    assert home.status_code == 200
    assert "GLYPH 社会叙事" in home.text
    assert '<select name="object_label"' in home.text
    assert '<select name="aesthetic_terms" multiple' in home.text
    registry_response = client.get("/api/registries")
    assert registry_response.status_code == 200
    registry = registry_response.json()
    assert {row["canonical_label"] for row in registry["objects"]} >= {"latin", "han"}
    assert "premium" in registry["codes"]["aesthetic_term"]

    scope_response = client.post("/api/scopes", json={
        "name": "网页闭环测试",
        "object_type": "writing_system",
        "object_label": "latin",
        "keywords": ["typography"],
        "languages": ["en"],
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-03T00:00:00Z",
        "max_items": 5,
    })
    assert scope_response.status_code == 201
    scope = scope_response.json()

    service = SocialNarrativeService(database)
    run = service.start_run(scope["scope_id"])
    assert service.process_event(run["collection_run_id"], _v2_post_event())
    screening_queue = client.get("/api/screening-queue").json()
    assert len(screening_queue) == 1
    screen_response = client.post(
        f"/api/observations/{screening_queue[0]['observation_id']}/screen",
        json={
            "decision": "include",
            "reason": "原文明确连接 latin typography 与 modern/premium。",
        },
    )
    assert screen_response.status_code == 200
    queue = client.get("/api/review-queue").json()
    observation_id = queue[0]["observation_id"]
    review_response = client.post(f"/api/observations/{observation_id}/review", json={
        "status": "human_verified",
        "object_type": "writing_system",
        "object_label": "latin",
        "aesthetic_terms": ["modern"],
        "evidence_span": "typography and wordmark study feels modern and premium",
        "stance": "descriptive",
        "confidence": 0.9,
        "exclusion_reason": None,
    })
    assert review_response.status_code == 200
    history = client.get(
        "/api/review-history", params={"observation_id": observation_id}
    ).json()
    assert history[0]["new_status"] == "human_verified"
    analysis = client.get("/api/analysis").json()
    assert analysis["included_records"] == 1
    assert analysis["matrix_a"][0]["term"] == "modern"
    evidence = client.get(f"/api/evidence/{observation_id}").json()
    assert evidence["query"]["query_id"] == scope["query_id"]
    health = client.get("/api/health").json()
    assert health["database"] == "ok"
    assert health["outbound_proxy_configured"] is True
    assert "7897" not in json.dumps(health)


def test_web_review_exclusion_requires_only_reason(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    client = TestClient(create_app(database))
    home = client.get("/")
    review_form = home.text.split('<form id="review-form"', 1)[1].split("</form>", 1)[0]
    assert 'name="aesthetic_terms" required' not in review_form
    assert 'name="evidence_span" rows="3" required' not in review_form

    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="排除审核测试",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_event(run["collection_run_id"], _v2_post_event())
    observation_id = _include_first_screening(service)
    payload = {
        "status": "excluded",
        "object_type": "",
        "object_label": "",
        "aesthetic_terms": [],
        "evidence_span": None,
        "stance": None,
        "confidence": None,
        "exclusion_reason": None,
    }

    missing_reason = client.post(
        f"/api/observations/{observation_id}/review", json=payload
    )
    assert missing_reason.status_code == 422

    payload["exclusion_reason"] = "未对应冻结 codebook 中的审美术语"
    excluded = client.post(
        f"/api/observations/{observation_id}/review", json=payload
    )
    assert excluded.status_code == 200
    assert excluded.json()["annotation_status"] == "excluded"
    assert client.get("/api/review-queue").json() == []
    assert client.get("/api/analysis").json()["included_records"] == 0
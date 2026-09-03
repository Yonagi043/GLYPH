from __future__ import annotations

import asyncio
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.bluesky import ResearchScope
from glyph_features.social_system.collector import TikTokCollector
from glyph_features.social_system.tiktok import (
    TikTokApiError,
    TikTokResearchClient,
    normalize_tiktok_comment,
    normalize_tiktok_video,
)
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.web import create_app
from tools.social_io import validation_errors, validator


ROOT = Path(__file__).parents[1]


def _fixture() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/tiktok_research_api_v1.json").read_text(
            encoding="utf-8"
        )
    )


def _scope() -> ResearchScope:
    return ResearchScope(
        query_id="q_tiktok_typography",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography",),
        languages=("en",),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        exact_query="latin typography",
    )


def test_tiktok_video_normalizes_without_manufacturing_gold():
    video = _fixture()["video_query_pages"][0]["response"]["data"]["videos"][0]

    record = normalize_tiktok_video(
        video,
        scope=_scope(),
        collection_run_id="social_run_tiktok_fixture",
        normalized_at="2026-09-03T10:00:00Z",
    )

    assert record["schema_version"] == "0.1.0"
    assert record["platform"] == "tiktok"
    assert record["platform_item_id"] == "video:7520000000000000001"
    assert record["url"] == (
        "https://www.tiktok.com/player/v1/7520000000000000001"
    )
    assert record["text"] == "A modern Latin typography study."
    assert record["annotation_status"] == "candidate"
    assert record["author_ref"] is None
    assert record["author_role"] is None
    assert record["object_type"] is None
    assert record["object_label"] is None
    assert record["aesthetic_terms"] == []
    assert record["stance"] is None
    assert record["engagement"]["view_count"] == 120
    assert record["engagement"]["like_count"] == 20
    assert "bounded Research API" in record["governance"]["notes"]
    assert "not a TikTok-wide sample" in record["governance"]["notes"]
    assert validation_errors(record, validator()) == []


def test_tiktok_comments_preserve_top_level_and_reply_hierarchy():
    fixture = _fixture()
    top_level = fixture["comment_pages"]["7520000000000000001"][0][
        "response"
    ]["data"]["comments"][0]
    reply = fixture["reply_pages"]["7530000000000000001"][0]["response"][
        "data"
    ]["comments"][0]

    top_record = normalize_tiktok_comment(
        top_level,
        video_id="7520000000000000001",
        scope=_scope(),
        collection_run_id="social_run_tiktok_fixture",
        normalized_at="2026-09-03T10:00:00Z",
    )
    reply_record = normalize_tiktok_comment(
        reply,
        video_id="7520000000000000001",
        parent_comment_id="7530000000000000001",
        scope=_scope(),
        collection_run_id="social_run_tiktok_fixture",
        normalized_at="2026-09-03T10:00:00Z",
    )

    assert top_record["platform_item_id"] == "comment:7530000000000000001"
    assert top_record["references"] == [{
        "relation": "parent",
        "target_item_id": "video:7520000000000000001",
        "target_url": "https://www.tiktok.com/player/v1/7520000000000000001",
    }]
    assert reply_record["platform_item_id"] == "comment:7530000000000000002"
    assert reply_record["references"] == [{
        "relation": "reply",
        "target_item_id": "comment:7530000000000000001",
        "target_url": "https://www.tiktok.com/player/v1/7520000000000000001",
    }]
    assert top_record["author_ref"] is None
    assert reply_record["author_ref"] is None
    assert validation_errors(top_record, validator()) == []
    assert validation_errors(reply_record, validator()) == []


def _scope_arguments() -> dict:
    return {
        "platform": "tiktok",
        "name": "TikTok Research API fixture",
        "object_type": "writing_system",
        "object_label": "latin",
        "keywords": ["typography"],
        "languages": ["en"],
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-03T23:59:59Z",
        "max_items": 20,
        "exact_query": "latin typography",
        "max_videos": 2,
        "max_comment_threads_per_video": 2,
        "max_replies_per_thread": 1,
        "tiktok_query": _fixture()["video_query_pages"][0]["request"]["query"],
        "tiktok_video_page_size": 50,
        "tiktok_max_video_pages": 2,
        "tiktok_comment_page_size": 100,
        "tiktok_max_comment_pages_per_video": 2,
        "tiktok_reply_page_size": 100,
        "tiktok_max_reply_pages_per_comment": 2,
        "tiktok_request_delay_seconds": 0.0,
    }


def _web_scope_payload() -> dict:
    return _scope_arguments()


def test_tiktok_scope_freezes_query_window_layers_and_manifest(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")

    scope = service.create_scope(**_scope_arguments())
    stored = service.get_scope(scope["scope_id"])
    options = stored["platform_options"]

    assert options == {
        "comment_page_size": 100,
        "daily_request_limit": 1000,
        "end_date": "20260903",
        "max_comment_pages_per_video": 2,
        "max_reply_pages_per_comment": 2,
        "max_video_pages": 2,
        "query": _fixture()["video_query_pages"][0]["request"]["query"],
        "quota_policy_version": "tiktok_research_api_2026-09-01",
        "reply_page_size": 100,
        "request_delay_seconds": 0.0,
        "start_date": "20260901",
        "video_page_size": 50,
    }
    assert stored["layer_quotas"] == {
        "max_videos": 2,
        "max_comment_threads_per_video": 2,
        "max_replies_per_thread": 1,
    }
    manifest = service.start_run(scope["scope_id"])
    assert manifest["platform"] == "tiktok"
    assert manifest["sampling"]["method"] == "api_pagination"
    assert manifest["collector"]["endpoint"] == (
        "https://open.tiktokapis.com/v2/research"
    )
    assert "30 个 UTC 日历日" in manifest["notes"]
    assert "不代表 TikTok 全网样本" in manifest["notes"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"window_end": "2026-10-01T23:59:59Z"}, "30"),
        ({"window_start": "2026-09-01T12:00:00Z"}, "UTC"),
        ({
            "tiktok_query": {
                "and": [{
                    "operation": "CONTAINS",
                    "field_name": "private_profile",
                    "field_values": ["fixture"],
                }]
            }
        }, "TikTok"),
    ],
)
def test_tiktok_scope_rejects_unrepresentable_windows_and_query_ast(
    tmp_path: Path, changes: dict, message: str
):
    arguments = {**_scope_arguments(), **changes}
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")

    with pytest.raises(ValueError, match=message):
        service.create_scope(**arguments)
    assert service.list_scopes() == []


def test_web_rejects_tiktok_start_without_credentials_before_creating_run(
    tmp_path: Path,
):
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy="http://127.0.0.1:7897",
        tiktok_client_key="",
        tiktok_client_secret="",
    )
    with TestClient(app) as client:
        created = client.post("/api/scopes", json=_web_scope_payload())
        assert created.status_code == 201
        scope = created.json()

        response = client.post("/api/runs", json={"scope_id": scope["scope_id"]})

        assert response.status_code == 422
        assert "TikTok Research API" in response.json()["detail"]
        assert client.get("/api/runs").json() == []
        health = client.get("/api/health").json()
        assert health["tiktok_credentials_configured"] is False
        assert "tiktok" in health["platforms"]
        monitoring = client.get("/api/monitoring").json()
        assert monitoring["tiktok_credentials_configured"] is False
        assert monitoring["tiktok_quota"]["reset_timezone"] == "UTC"
        assert "REDACTED" not in json.dumps(health)
        assert "REDACTED" not in json.dumps(monitoring)


def test_web_selects_tiktok_collector_with_boolean_readiness(
    tmp_path: Path,
    monkeypatch,
):
    collected: list[tuple[str, int]] = []

    async def finish_immediately(collector, collection_run_id, *, max_items):
        collected.append((collection_run_id, max_items))
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(TikTokCollector, "run", finish_immediately)
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy="http://127.0.0.1:7897",
        tiktok_client_key="REDACTED_TEST_CLIENT_KEY",
        tiktok_client_secret="REDACTED_TEST_CLIENT_SECRET",
    )
    with TestClient(app) as client:
        scope = client.post("/api/scopes", json=_web_scope_payload()).json()
        started = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert started.status_code == 202
        assert started.json()["platform"] == "tiktok"
        for _ in range(20):
            if collected:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert collected == [(started.json()["collection_run_id"], 20)]
        health = client.get("/api/health").json()
        assert health["tiktok_credentials_configured"] is True
        assert "REDACTED_TEST" not in json.dumps(health)


def test_tiktok_monitoring_and_export_preserve_query_state_and_request_audit(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    asyncio.run(TikTokCollector(
        service,
        client=_FakeTikTokClient(_fixture()),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=20))

    monitoring = service.monitoring(tmp_path / "backups")
    assert "tiktok" in monitoring["platforms"]
    assert "TikTok Research API" in monitoring["sources"]
    assert monitoring["bounded_api"]["state_counts"]["tiktok"] == {
        "completed": 4
    }
    assert monitoring["tiktok_quota"]["used_requests"] == 5

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    states = json.loads(
        (export_directory / "api_collection_states.json").read_text(
            encoding="utf-8"
        )
    )
    events = json.loads(
        (export_directory / "tiktok_request_events.json").read_text(
            encoding="utf-8"
        )
    )
    quota = json.loads(
        (export_directory / "tiktok_quota_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    with (export_directory / "queries.csv").open(encoding="utf-8") as handle:
        query = next(csv.DictReader(handle))

    assert len(states) == 4
    assert len(events) == 5
    assert {event["outcome"] for event in events} == {"succeeded"}
    assert quota["quota_dates"][0]["used_requests"] == 5
    assert quota["reset_timezone"] == "UTC"
    assert json.loads(query["tiktok_query_json"]) == _scope_arguments()[
        "tiktok_query"
    ]
    assert query["tiktok_video_page_size"] == "50"
    assert query["tiktok_max_video_pages"] == "2"
    assert query["tiktok_comment_page_size"] == "100"
    assert query["tiktok_max_comment_pages_per_video"] == "2"
    assert query["tiktok_reply_page_size"] == "100"
    assert query["tiktok_max_reply_pages_per_comment"] == "2"
    assert query["tiktok_request_delay_seconds"] == "0.0"


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class _FakeTikTokOpener:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        self.requests.append(request)
        if request.full_url.endswith("/v2/oauth/token/"):
            token_number = sum(
                item.full_url.endswith("/v2/oauth/token/")
                for item in self.requests
            )
            return _FakeResponse({
                **self.fixture["token_response"],
                "access_token": f"REDACTED_FIXTURE_CLIENT_ACCESS_TOKEN_{token_number}",
            })
        request_body = json.loads((request.data or b"").decode("utf-8"))
        page_index = int(request_body["cursor"])
        return _FakeResponse(
            self.fixture["video_query_pages"][page_index]["response"]
        )


def test_tiktok_client_uses_client_token_and_parses_search_pagination():
    fixture = _fixture()
    opener = _FakeTikTokOpener(fixture)
    clock = [1000.0]
    client = TikTokResearchClient(
        client_key="REDACTED_TEST_CLIENT_KEY",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
        clock=lambda: clock[0],
    )

    first = asyncio.run(client.query_videos(
        fixture["video_query_pages"][0]["request"]
    ))
    clock[0] += 8000
    second = asyncio.run(client.query_videos(
        fixture["video_query_pages"][1]["request"]
    ))

    assert first == {
        "items": fixture["video_query_pages"][0]["response"]["data"]["videos"],
        "cursor": 1,
        "has_more": True,
        "search_id": "REDACTED_FIXTURE_SEARCH_ID",
    }
    assert second["cursor"] == 2
    assert second["has_more"] is False
    assert second["search_id"] == first["search_id"]
    assert len(opener.requests) == 4
    token_requests = [
        request for request in opener.requests
        if request.full_url.endswith("/v2/oauth/token/")
    ]
    api_requests = [
        request for request in opener.requests
        if "/v2/research/video/query/" in request.full_url
    ]
    assert all(
        request.data == (
            b"client_key=REDACTED_TEST_CLIENT_KEY&"
            b"client_secret=REDACTED_TEST_CLIENT_SECRET&"
            b"grant_type=client_credentials"
        )
        for request in token_requests
    )
    assert [request.get_header("Authorization") for request in api_requests] == [
        "Bearer REDACTED_FIXTURE_CLIENT_ACCESS_TOKEN_1",
        "Bearer REDACTED_FIXTURE_CLIENT_ACCESS_TOKEN_2",
    ]
    assert all(request.get_method() == "POST" for request in opener.requests)
    assert all("REDACTED_TEST" not in request.full_url for request in opener.requests)
    assert all("username" not in request.full_url for request in api_requests)
    assert all("fields=" in request.full_url for request in api_requests)


class _RefreshingTikTokOpener:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.requests: list[Request] = []
        self.api_attempts = 0

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        self.requests.append(request)
        if request.full_url.endswith("/v2/oauth/token/"):
            token_number = sum(
                item.full_url.endswith("/v2/oauth/token/")
                for item in self.requests
            )
            return _FakeResponse({
                **self.fixture["token_response"],
                "access_token": f"REDACTED_REFRESH_TOKEN_{token_number}",
            })
        self.api_attempts += 1
        if self.api_attempts == 1:
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)
        return _FakeResponse(self.fixture["video_query_pages"][0]["response"])


def test_tiktok_client_refreshes_token_once_after_http_401():
    opener = _RefreshingTikTokOpener(_fixture())
    client = TikTokResearchClient(
        client_key="REDACTED_TEST_CLIENT_KEY",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
    )

    result = asyncio.run(client.query_videos(
        _fixture()["video_query_pages"][0]["request"]
    ))

    assert result["cursor"] == 1
    api_requests = [
        request for request in opener.requests
        if "/v2/research/video/query/" in request.full_url
    ]
    assert [request.get_header("Authorization") for request in api_requests] == [
        "Bearer REDACTED_REFRESH_TOKEN_1",
        "Bearer REDACTED_REFRESH_TOKEN_2",
    ]


class _ErrorEnvelopeTikTokOpener:
    def __init__(self, fixture: dict, api_code: str):
        self.fixture = fixture
        self.api_code = api_code

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        if request.full_url.endswith("/v2/oauth/token/"):
            return _FakeResponse(self.fixture["token_response"])
        return _FakeResponse({
            "data": {},
            "error": {"code": self.api_code, "message": "fixture error"},
        })


@pytest.mark.parametrize(
    ("api_code", "retryable"),
    [("internal_error", True), ("invalid_params", False)],
)
def test_tiktok_client_classifies_platform_error_envelope(
    api_code: str,
    retryable: bool,
):
    client = TikTokResearchClient(
        client_key="REDACTED_TEST_CLIENT_KEY",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        proxy_url="http://127.0.0.1:7897",
        opener=_ErrorEnvelopeTikTokOpener(_fixture(), api_code),
    )

    with pytest.raises(TikTokApiError) as captured:
        asyncio.run(client.query_videos(
            _fixture()["video_query_pages"][0]["request"]
        ))

    assert captured.value.api_code == api_code
    assert captured.value.retryable is retryable


class _FakeTikTokCommentOpener:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        self.requests.append(request)
        if request.full_url.endswith("/v2/oauth/token/"):
            return _FakeResponse(self.fixture["token_response"])
        body = json.loads((request.data or b"").decode("utf-8"))
        if "video_id" in body:
            page = self.fixture["comment_pages"][body["video_id"]][0]
        else:
            page = self.fixture["reply_pages"][body["comment_id"]][0]
        return _FakeResponse(page["response"])


def test_tiktok_client_lists_top_level_comments_and_replies_without_identity_fields():
    fixture = _fixture()
    opener = _FakeTikTokCommentOpener(fixture)
    client = TikTokResearchClient(
        client_key="REDACTED_TEST_CLIENT_KEY",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
    )

    comments = asyncio.run(client.list_comments(
        fixture["comment_pages"]["7520000000000000001"][0]["request"]
    ))
    replies = asyncio.run(client.list_comments(
        fixture["reply_pages"]["7530000000000000001"][0]["request"]
    ))

    assert comments["items"][0]["id"] == "7530000000000000001"
    assert comments["cursor"] == 1
    assert comments["has_more"] is False
    assert replies["items"][0]["parent_comment_id"] == "7530000000000000001"
    assert replies["cursor"] == 1
    api_requests = [
        request for request in opener.requests
        if "/v2/research/video/comment/list/" in request.full_url
    ]
    assert len(api_requests) == 2
    assert all("username" not in request.full_url for request in api_requests)
    assert all(
        request.get_header("Authorization")
        == "Bearer REDACTED_FIXTURE_CLIENT_ACCESS_TOKEN"
        for request in api_requests
    )


@pytest.mark.parametrize(
    "body",
    [
        {"max_count": 100, "cursor": 0},
        {
            "video_id": "7520000000000000001",
            "comment_id": "7530000000000000001",
            "max_count": 100,
            "cursor": 0,
        },
    ],
)
def test_tiktok_client_rejects_ambiguous_comment_targets(body: dict):
    client = TikTokResearchClient(
        client_key="REDACTED_TEST_CLIENT_KEY",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        proxy_url="http://127.0.0.1:7897",
        opener=_FakeTikTokCommentOpener(_fixture()),
    )

    with pytest.raises(ValueError, match="video_id.*comment_id"):
        asyncio.run(client.list_comments(body))


def test_tiktok_daily_request_guard_reserves_attempts_atomically_by_utc_date(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    service.set_tiktok_daily_request_budget(2)

    first = service.reserve_tiktok_request(
        run["collection_run_id"], "video.query", quota_date="2026-09-02"
    )
    service.finish_tiktok_request(first, outcome="succeeded")
    second = service.reserve_tiktok_request(
        run["collection_run_id"], "comment.list", quota_date="2026-09-02"
    )
    service.finish_tiktok_request(
        second, outcome="failed", error_code="fixture_error"
    )

    assert service.tiktok_quota_status("2026-09-02") == {
        "quota_date": "2026-09-02",
        "daily_request_budget": 2,
        "used_requests": 2,
        "remaining_requests": 0,
        "policy_version": "tiktok_research_api_2026-09-01",
        "reset_timezone": "UTC",
    }
    with pytest.raises(ValueError, match="TikTok.*daily request"):
        service.reserve_tiktok_request(
            run["collection_run_id"], "video.query", quota_date="2026-09-02"
        )
    assert len(service.tiktok_request_events(run["collection_run_id"])) == 2

    next_day = service.reserve_tiktok_request(
        run["collection_run_id"], "video.query", quota_date="2026-09-03"
    )
    assert isinstance(next_day, int)
    assert service.tiktok_quota_status("2026-09-03")["used_requests"] == 1
    with pytest.raises(ValueError, match="1.*1000"):
        service.set_tiktok_daily_request_budget(1001)


class _FakeTikTokClient:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.calls: list[tuple[str, dict]] = []

    async def query_videos(self, body: dict):
        self.calls.append(("video.query", dict(body)))
        page_index = int(body["cursor"])
        data = self.fixture["video_query_pages"][page_index]["response"]["data"]
        return {
            "items": data["videos"],
            "cursor": data["cursor"],
            "has_more": data["has_more"],
            "search_id": data["search_id"],
        }

    async def list_comments(self, body: dict):
        self.calls.append(("comment.list", dict(body)))
        if "video_id" in body:
            page = self.fixture["comment_pages"][body["video_id"]][0]
        else:
            page = self.fixture["reply_pages"][body["comment_id"]][0]
        data = page["response"]["data"]
        return {
            "items": data["comments"],
            "cursor": data["cursor"],
            "has_more": data["has_more"],
        }


def test_tiktok_collector_preserves_search_cursor_layers_quota_and_provenance(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    client = _FakeTikTokClient(_fixture())

    result = asyncio.run(TikTokCollector(
        service,
        client=client,
        sleep=lambda _delay: asyncio.sleep(0),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=20))

    assert result == {
        "status": "completed",
        "inserted": 4,
        "videos": 2,
        "comments": 1,
        "replies": 1,
        "requests": 5,
        "partitions_failed": 0,
    }
    assert [operation for operation, _body in client.calls] == [
        "video.query",
        "video.query",
        "comment.list",
        "comment.list",
        "comment.list",
    ]
    assert client.calls[1][1]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"
    assert len(service.observations()) == 4
    matches = service.observation_query_matches(run["collection_run_id"])
    assert len(matches) == 4
    assert {match["query_id"] for match in matches} == {scope["query_id"]}
    events = service.tiktok_request_events(run["collection_run_id"])
    assert len(events) == 5
    assert {event["outcome"] for event in events} == {"succeeded"}
    states = service.api_collection_states(run["collection_run_id"])
    assert {state["partition_key"] for state in states} == {
        "videos",
        "video:7520000000000000001:comments",
        "video:7520000000000000002:comments",
        "comment:7530000000000000001:replies",
    }
    assert {state["status"] for state in states} == {"completed"}
    video_state = next(state for state in states if state["partition_key"] == "videos")
    assert video_state["state"] == {
        "cursor": 2,
        "has_more": False,
        "item_ids": ["7520000000000000001", "7520000000000000002"],
        "pages_fetched": 2,
        "search_id": "REDACTED_FIXTURE_SEARCH_ID",
        "items_seen": 2,
    }
    shortfalls = [
        event for event in service.audit()
        if event["event_type"] == "tiktok_comment_page_shortfall"
    ]
    assert len(shortfalls) == 2
    assert all(event["details"]["possible_unavailable_items"] for event in shortfalls)

    repeated = asyncio.run(TikTokCollector(
        service,
        client=client,
        max_retries=0,
    ).run(run["collection_run_id"], max_items=20))
    assert repeated["inserted"] == 0
    assert repeated["requests"] == 0
    assert len(client.calls) == 5
    assert len(service.observations()) == 4


class _InterruptingTikTokClient(_FakeTikTokClient):
    async def query_videos(self, body: dict):
        if len([call for call in self.calls if call[0] == "video.query"]) == 1:
            self.calls.append(("video.query", dict(body)))
            raise asyncio.CancelledError
        return await super().query_videos(body)


def test_tiktok_collector_resumes_video_query_with_same_search_id_and_cursor(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    arguments = {
        **_scope_arguments(),
        "max_comment_threads_per_video": 0,
        "max_replies_per_thread": 0,
    }
    scope = service.create_scope(**arguments)
    run = service.start_run(scope["scope_id"])
    client = _InterruptingTikTokClient(_fixture())
    collector = TikTokCollector(service, client=client, max_retries=0)

    stopped = asyncio.run(collector.run(run["collection_run_id"], max_items=20))
    assert stopped["status"] == "stopped"
    video_state = service.api_collection_states(run["collection_run_id"])[0]
    assert video_state["status"] == "running"
    assert video_state["state"]["cursor"] == 1
    assert video_state["state"]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"

    resumed = asyncio.run(collector.run(run["collection_run_id"], max_items=20))
    assert resumed["status"] == "completed"
    assert resumed["inserted"] == 1
    video_calls = [body for operation, body in client.calls if operation == "video.query"]
    assert [body["cursor"] for body in video_calls] == [0, 1, 1]
    assert video_calls[1]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"
    assert video_calls[2]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"
    assert len(service.observations()) == 2
    assert len(service.tiktok_request_events(run["collection_run_id"])) == 3


def test_tiktok_collector_stops_before_call_at_daily_budget_and_resumes_next_utc_day(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    arguments = {
        **_scope_arguments(),
        "max_comment_threads_per_video": 0,
        "max_replies_per_thread": 0,
    }
    scope = service.create_scope(**arguments)
    run = service.start_run(scope["scope_id"])
    service.set_tiktok_daily_request_budget(1)
    now = [datetime(2026, 9, 2, 12, tzinfo=timezone.utc)]
    client = _FakeTikTokClient(_fixture())
    collector = TikTokCollector(
        service,
        client=client,
        max_retries=0,
        now=lambda: now[0],
    )

    exhausted = asyncio.run(collector.run(run["collection_run_id"], max_items=20))
    assert exhausted["status"] == "quota_exhausted"
    assert exhausted["inserted"] == 1
    assert exhausted["requests"] == 1
    assert len(client.calls) == 1
    assert service.get_run(run["collection_run_id"])["status"] == "stopped"
    assert service.api_collection_states(run["collection_run_id"])[0]["state"][
        "cursor"
    ] == 1

    now[0] = datetime(2026, 9, 3, 0, 1, tzinfo=timezone.utc)
    resumed = asyncio.run(collector.run(run["collection_run_id"], max_items=20))
    assert resumed["status"] == "completed"
    assert resumed["inserted"] == 1
    assert resumed["requests"] == 1
    assert [body["cursor"] for _operation, body in client.calls] == [0, 1]
    assert client.calls[1][1]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"


class _ChangedSearchIdTikTokClient(_FakeTikTokClient):
    async def query_videos(self, body: dict):
        result = await super().query_videos(body)
        if body["cursor"] == 1:
            result["search_id"] = "REDACTED_DIFFERENT_SEARCH_ID"
        return result


def test_tiktok_collector_rejects_changed_search_id_without_losing_resume_state(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    client = _ChangedSearchIdTikTokClient(_fixture())

    result = asyncio.run(TikTokCollector(
        service,
        client=client,
        max_retries=0,
    ).run(run["collection_run_id"], max_items=20))

    assert result["status"] == "failed"
    assert result["inserted"] == 1
    assert result["partitions_failed"] == 1
    assert [operation for operation, _body in client.calls] == [
        "video.query",
        "video.query",
    ]
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["partition_key"] == "videos"
    assert state["status"] == "failed"
    assert state["state"]["cursor"] == 1
    assert state["state"]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"
    assert service.errors(run["collection_run_id"])[-1]["error_code"] == (
        "tiktok_api_search_id_changed"
    )


class _RetryOnceTikTokClient(_FakeTikTokClient):
    def __init__(self, fixture: dict, status_code: int):
        super().__init__(fixture)
        self.status_code = status_code
        self.failed = False

    async def query_videos(self, body: dict):
        if not self.failed:
            self.failed = True
            self.calls.append(("video.query", dict(body)))
            raise TikTokApiError(
                f"fixture HTTP {self.status_code}",
                status_code=self.status_code,
                api_code=None,
                retryable=True,
                retry_after_seconds=4.0,
            )
        return await super().query_videos(body)


@pytest.mark.parametrize("status_code", [429, 503])
def test_tiktok_collector_charges_each_retry_attempt(
    tmp_path: Path,
    status_code: int,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    arguments = {
        **_scope_arguments(),
        "max_comment_threads_per_video": 0,
        "max_replies_per_thread": 0,
    }
    scope = service.create_scope(**arguments)
    run = service.start_run(scope["scope_id"])
    client = _RetryOnceTikTokClient(_fixture(), status_code)
    delays: list[float] = []

    result = asyncio.run(TikTokCollector(
        service,
        client=client,
        max_retries=1,
        sleep=lambda delay: delays.append(delay) or asyncio.sleep(0),
    ).run(run["collection_run_id"], max_items=20))

    assert result["status"] == "completed"
    assert result["inserted"] == 2
    assert result["requests"] == 3
    assert delays == [4.0]
    events = service.tiktok_request_events(run["collection_run_id"])
    assert [event["outcome"] for event in events] == [
        "failed",
        "succeeded",
        "succeeded",
    ]
    assert events[0]["error_code"] == (
        "tiktok_rate_limited" if status_code == 429 else "tiktok_http_503"
    )


class _OneCommentPartitionFailsTikTokClient(_FakeTikTokClient):
    async def list_comments(self, body: dict):
        if body.get("video_id") == "7520000000000000001":
            self.calls.append(("comment.list", dict(body)))
            raise TikTokApiError(
                "fixture HTTP 401",
                status_code=401,
                api_code=None,
                retryable=False,
            )
        return await super().list_comments(body)


def test_tiktok_collector_isolates_nonretryable_comment_partition_failure(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    arguments = {**_scope_arguments(), "max_replies_per_thread": 0}
    scope = service.create_scope(**arguments)
    run = service.start_run(scope["scope_id"])
    client = _OneCommentPartitionFailsTikTokClient(_fixture())

    result = asyncio.run(TikTokCollector(
        service,
        client=client,
        max_retries=3,
    ).run(run["collection_run_id"], max_items=20))

    assert result == {
        "status": "completed",
        "inserted": 2,
        "videos": 2,
        "comments": 0,
        "replies": 0,
        "requests": 4,
        "partitions_failed": 1,
    }
    states = {
        state["partition_key"]: state
        for state in service.api_collection_states(run["collection_run_id"])
    }
    assert states["video:7520000000000000001:comments"]["status"] == "failed"
    assert states["video:7520000000000000001:comments"]["error_code"] == (
        "tiktok_authentication"
    )
    assert states["video:7520000000000000002:comments"]["status"] == "completed"
    assert service.errors(run["collection_run_id"])[-1]["error_code"] == (
        "tiktok_authentication"
    )


def test_schema_v16_migration_preserves_v15_records_and_api_state(tmp_path: Path):
    database = tmp_path / "legacy-v15.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    video = _fixture()["video_query_pages"][0]["response"]["data"]["videos"][0]
    assert service.process_tiktok_resource(
        run["collection_run_id"],
        video,
        resource_type="video",
        query_id=scope["query_id"],
    )
    service.save_api_collection_state(
        run["collection_run_id"],
        "tiktok",
        scope["query_id"],
        "videos",
        {
            "cursor": 1,
            "has_more": True,
            "item_ids": ["7520000000000000001"],
            "items_seen": 1,
            "pages_fetched": 1,
            "search_id": "REDACTED_FIXTURE_SEARCH_ID",
        },
        status="running",
    )
    preserved_tables = (
        "research_scopes",
        "queries",
        "collection_runs",
        "observations",
        "raw_events",
        "observation_query_matches",
        "api_collection_states",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DROP TABLE x_request_events;
            DROP TABLE x_run_billing_snapshots;
            DROP TABLE x_billing_settings;
            DROP TABLE x_price_snapshots;
            DROP TABLE tiktok_request_events;
            DROP TABLE tiktok_quota_settings;
            PRAGMA user_version = 15;
            """
        )
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in preserved_tables
        }

    with ResearchStore(database) as store:
        after = {table: store.table_count(table) for table in preserved_tables}
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == (
            SCHEMA_VERSION
        )
        assert store.table_count("tiktok_quota_settings") == 1
        assert store.table_count("tiktok_request_events") == 0

    assert before == after == {
        "research_scopes": 1,
        "queries": 1,
        "collection_runs": 1,
        "observations": 1,
        "raw_events": 1,
        "observation_query_matches": 1,
        "api_collection_states": 1,
    }
    restored_state = service.api_collection_states(run["collection_run_id"])[0]
    assert restored_state["state"]["search_id"] == "REDACTED_FIXTURE_SEARCH_ID"


def test_backup_restore_recovers_tiktok_quota_settings_and_request_events(
    tmp_path: Path,
):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(**_scope_arguments())
    run = service.start_run(scope["scope_id"])
    service.set_tiktok_daily_request_budget(7)
    event_id = service.reserve_tiktok_request(
        run["collection_run_id"],
        "video.query",
        quota_date="2026-09-02",
    )
    service.finish_tiktok_request(event_id, outcome="succeeded")
    backup = service.create_backup(backup_root, reason="tiktok_fixture")

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM tiktok_request_events")
        connection.execute(
            "UPDATE tiktok_quota_settings SET daily_request_budget = 2"
        )
    restored = service.restore_backup(backup_root, backup["backup_id"])

    assert restored["source_schema_version"] == SCHEMA_VERSION
    assert restored["schema_version"] == SCHEMA_VERSION
    assert restored["integrity_check"] == "ok"
    assert restored["pre_restore_backup_id"] != backup["backup_id"]
    events = service.tiktok_request_events(run["collection_run_id"])
    assert len(events) == 1
    assert events[0]["outcome"] == "succeeded"
    assert service.tiktok_quota_status("2026-09-02") == {
        "quota_date": "2026-09-02",
        "daily_request_budget": 7,
        "used_requests": 1,
        "remaining_requests": 6,
        "policy_version": "tiktok_research_api_2026-09-01",
        "reset_timezone": "UTC",
    }
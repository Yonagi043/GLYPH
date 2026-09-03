from __future__ import annotations

import json
import asyncio
import csv
import sqlite3
from pathlib import Path
from urllib.request import Request

from fastapi.testclient import TestClient

from glyph_features.social_system.bluesky import ResearchScope
from glyph_features.social_system.collector import RedditCollector
from glyph_features.social_system.reddit import (
    RedditApiClient,
    RedditApiError,
    normalize_reddit_post,
    reddit_content_status,
)
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.web import create_app
from tools.social_io import validation_errors, validator


ROOT = Path(__file__).parents[1]


def _fixture() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/reddit_api_v1.json").read_text(encoding="utf-8")
    )


def _scope() -> ResearchScope:
    return ResearchScope(
        query_id="q_reddit_typography",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography",),
        languages=("en",),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        exact_query="latin typography modern",
    )


def test_reddit_post_normalizes_without_manufacturing_gold():
    child = _fixture()["search_pages"][0]["response"]["data"]["children"][0]

    record = normalize_reddit_post(
        child,
        subreddit="typography",
        access_method="subreddit_search",
        scope=_scope(),
        collection_run_id="social_run_reddit_fixture",
        normalized_at="2026-09-02T10:00:00Z",
    )

    assert record is not None
    assert record["schema_version"] == "0.1.0"
    assert record["platform"] == "reddit"
    assert record["platform_item_id"] == "t3_fixture001"
    assert record["url"] == (
        "https://www.reddit.com/r/typography/comments/fixture001/modern_wordmark/"
    )
    assert record["title"] == "A modern Latin sans wordmark"
    assert record["text"] == "The letterforms feel clear and restrained."
    assert record["language_bcp47"] is None
    assert record["annotation_status"] == "candidate"
    assert record["author_ref"] is None
    assert record["author_role"] is None
    assert record["object_type"] is None
    assert record["object_label"] is None
    assert record["aesthetic_terms"] == []
    assert record["stance"] is None
    assert "bounded subreddit search" in record["governance"]["notes"]
    assert "not a Reddit-wide sample" in record["governance"]["notes"]
    assert validation_errors(record, validator()) == []


def test_reddit_removed_post_is_classified_before_normalization():
    child = _fixture()["search_pages"][0]["response"]["data"]["children"][1]

    assert reddit_content_status(child) == "removed"
    assert normalize_reddit_post(
        child,
        subreddit="typography",
        access_method="subreddit_search",
        scope=_scope(),
        collection_run_id="social_run_reddit_fixture",
        normalized_at="2026-09-02T10:00:00Z",
    ) is None


def test_reddit_scope_freezes_platform_options_and_manifest(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit typography fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["Typography", "design"],
        reddit_access_method="subreddit_search",
        reddit_sort="new",
        reddit_time_filter="month",
        reddit_page_size=25,
        reddit_max_pages_per_subreddit=2,
        reddit_request_delay_seconds=0,
    )

    query = service.get_scope(scope["scope_id"])["queries"][0]
    assert query["platform_options"] == {
        "access_method": "subreddit_search",
        "max_pages_per_subreddit": 2,
        "page_size": 25,
        "request_delay_seconds": 0.0,
        "sort": "new",
        "subreddits": ["design", "typography"],
        "time_filter": "month",
    }

    manifest = service.start_run(scope["scope_id"])
    assert manifest["schema_version"] == "0.1.0"
    assert manifest["platform"] == "reddit"
    assert manifest["sampling"]["method"] == "api_pagination"
    assert "r/design" in manifest["notes"]
    assert "r/typography" in manifest["notes"]
    assert "不代表 Reddit 全网样本" in manifest["notes"]


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


class _FakeRedditOpener:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.requests: list[Request] = []
        self.response_index = 0

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        self.requests.append(request)
        if request.full_url.endswith("/api/v1/access_token"):
            token_number = sum(
                item.full_url.endswith("/api/v1/access_token")
                for item in self.requests
            )
            return _FakeResponse({
                **self.fixture["oauth_token_response"],
                "access_token": f"REDACTED_FIXTURE_ACCESS_TOKEN_{token_number}",
            })
        page = self.fixture["search_pages"][self.response_index]
        self.response_index += 1
        return _FakeResponse(page["response"], page["rate_limit_headers"])


def test_reddit_client_refreshes_oauth_and_parses_listing_without_url_secrets():
    fixture = _fixture()
    clock = [1000.0]
    opener = _FakeRedditOpener(fixture)
    client = RedditApiClient(
        client_id="REDACTED_TEST_CLIENT_ID",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        refresh_token="REDACTED_TEST_REFRESH_TOKEN",
        user_agent="macos:glyph-social:0.1.0 (by /u/research_fixture)",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
        clock=lambda: clock[0],
    )

    first = asyncio.run(client.request(
        "/r/typography/search",
        fixture["search_pages"][0]["request"],
    ))
    clock[0] += 4000
    second = asyncio.run(client.request(
        "/r/typography/search",
        fixture["search_pages"][1]["request"],
    ))

    assert [len(first[0]), first[1]] == [2, "t3_fixture002"]
    assert [len(second[0]), second[1]] == [1, None]
    assert first[2] == {"used": 1.0, "remaining": 59.0, "reset": 60.0}
    assert len(opener.requests) == 4
    token_requests = [
        request for request in opener.requests
        if request.full_url.endswith("/api/v1/access_token")
    ]
    api_requests = [
        request for request in opener.requests
        if request.full_url.startswith("https://oauth.reddit.com/")
    ]
    assert [request.data for request in token_requests] == [
        b"grant_type=refresh_token&refresh_token=REDACTED_TEST_REFRESH_TOKEN",
        b"grant_type=refresh_token&refresh_token=REDACTED_FIXTURE_REFRESH_TOKEN",
    ]
    assert all(request.get_header("Authorization").startswith("Basic ") for request in token_requests)
    assert [request.get_header("Authorization") for request in api_requests] == [
        "Bearer REDACTED_FIXTURE_ACCESS_TOKEN_1",
        "Bearer REDACTED_FIXTURE_ACCESS_TOKEN_2",
    ]
    assert all(
        request.get_header("User-agent")
        == "macos:glyph-social:0.1.0 (by /u/research_fixture)"
        for request in api_requests
    )
    assert all("REDACTED_TEST" not in request.full_url for request in opener.requests)


def test_reddit_client_app_only_grant_does_not_manufacture_refresh_token():
    fixture = _fixture()
    fixture["oauth_token_response"].pop("refresh_token", None)
    opener = _FakeRedditOpener(fixture)
    client = RedditApiClient(
        client_id="REDACTED_TEST_CLIENT_ID",
        client_secret="REDACTED_TEST_CLIENT_SECRET",
        user_agent="macos:glyph-social:0.1.0 (by /u/research_fixture)",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
    )

    asyncio.run(client.request(
        "/r/typography/search",
        fixture["search_pages"][0]["request"],
    ))

    token_request = opener.requests[0]
    assert token_request.data == b"grant_type=client_credentials"
    assert client.refresh_token is None
    assert b"refresh_token" not in token_request.data


class _FakeRedditClient:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.calls: list[tuple[str, dict]] = []

    async def request(self, endpoint: str, parameters: dict):
        self.calls.append((endpoint, dict(parameters)))
        page_index = 1 if parameters.get("after") else 0
        page = self.fixture["search_pages"][page_index]
        data = page["response"]["data"]
        headers = page["rate_limit_headers"]
        return data["children"], data["after"], {
            "used": float(headers["X-Ratelimit-Used"]),
            "remaining": float(headers["X-Ratelimit-Remaining"]),
            "reset": float(headers["X-Ratelimit-Reset"]),
        }


def test_reddit_collector_paginates_audits_removed_and_preserves_query_provenance(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit collector fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_access_method="subreddit_search",
        reddit_sort="new",
        reddit_time_filter="month",
        reddit_page_size=2,
        reddit_max_pages_per_subreddit=2,
        reddit_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _FakeRedditClient(_fixture())

    result = asyncio.run(RedditCollector(
        service,
        client=client,
        sleep=lambda _delay: asyncio.sleep(0),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))

    assert result == {
        "status": "completed",
        "inserted": 2,
        "pages_fetched": 2,
        "subreddits_completed": 1,
        "subreddits_failed": 0,
        "unavailable": 1,
    }
    assert [call[1].get("after") for call in client.calls] == [None, "t3_fixture002"]
    assert len(service.observations()) == 2
    matches = service.observation_query_matches(run["collection_run_id"])
    assert len(matches) == 2
    assert {row["query_id"] for row in matches} == {scope["query_id"]}
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["platform"] == "reddit"
    assert state["partition_key"] == "typography"
    assert state["status"] == "completed"
    assert state["state"] == {
        "items_seen": 3,
        "last_rate_limit": {"remaining": 58.0, "reset": 59.0, "used": 2.0},
        "next_page_token": None,
        "pages_fetched": 2,
        "unavailable_count": 1,
    }
    removed_audits = [
        event for event in service.audit()
        if event["event_type"] == "reddit_item_removed"
    ]
    assert len(removed_audits) == 1
    assert removed_audits[0]["details"]["payload_sha256"]
    assert "selftext" not in removed_audits[0]["details"]

    repeated = asyncio.run(RedditCollector(
        service,
        client=client,
        sleep=lambda _delay: asyncio.sleep(0),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))
    assert repeated["inserted"] == 0
    assert len(client.calls) == 2
    assert len(service.observations()) == 2


class _InterruptingRedditClient(_FakeRedditClient):
    async def request(self, endpoint: str, parameters: dict):
        self.calls.append((endpoint, dict(parameters)))
        if len(self.calls) == 2:
            raise asyncio.CancelledError
        page_index = 1 if parameters.get("after") else 0
        page = self.fixture["search_pages"][page_index]
        data = page["response"]["data"]
        headers = page["rate_limit_headers"]
        return data["children"], data["after"], {
            "used": float(headers["X-Ratelimit-Used"]),
            "remaining": float(headers["X-Ratelimit-Remaining"]),
            "reset": float(headers["X-Ratelimit-Reset"]),
        }


def test_reddit_collector_resumes_from_saved_after_token(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit resume fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_sort="new",
        reddit_page_size=2,
        reddit_max_pages_per_subreddit=2,
        reddit_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _InterruptingRedditClient(_fixture())
    collector = RedditCollector(service, client=client, max_retries=0)

    stopped = asyncio.run(collector.run(run["collection_run_id"], max_items=10))
    assert stopped["status"] == "stopped"
    assert stopped["inserted"] == 1
    assert service.api_collection_states(run["collection_run_id"])[0]["state"][
        "next_page_token"
    ] == "t3_fixture002"

    resumed = asyncio.run(collector.run(run["collection_run_id"], max_items=10))
    assert resumed["status"] == "completed"
    assert resumed["inserted"] == 1
    assert [call[1].get("after") for call in client.calls] == [
        None,
        "t3_fixture002",
        "t3_fixture002",
    ]
    assert len(service.observations()) == 2


class _RetryingRedditClient:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.calls = 0

    async def request(self, endpoint: str, parameters: dict):
        del endpoint, parameters
        self.calls += 1
        if self.calls == 1:
            raise RedditApiError(
                "fixture rate limit",
                status_code=429,
                retryable=True,
                retry_after_seconds=4.0,
            )
        if self.calls == 2:
            raise RedditApiError(
                "fixture service unavailable",
                status_code=503,
                retryable=True,
            )
        page = self.fixture["search_pages"][1]
        return page["response"]["data"]["children"], None, {
            "used": 3.0,
            "remaining": 57.0,
            "reset": 58.0,
        }


def test_reddit_collector_retries_rate_limit_and_server_errors(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit retry fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_sort="new",
        reddit_page_size=1,
        reddit_max_pages_per_subreddit=1,
        reddit_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _RetryingRedditClient(_fixture())
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(RedditCollector(
        service,
        client=client,
        sleep=record_delay,
        max_retries=2,
    ).run(run["collection_run_id"], max_items=10))

    assert result["status"] == "completed"
    assert result["inserted"] == 1
    assert client.calls == 3
    assert delays == [4.0, 2.0]
    assert service.errors(run["collection_run_id"]) == []


class _SinglePageRedditClient:
    def __init__(self, children: list[dict]):
        self.children = children
        self.calls = 0

    async def request(self, endpoint: str, parameters: dict):
        del endpoint, parameters
        self.calls += 1
        return self.children, None, {
            "used": float(self.calls),
            "remaining": 60.0 - self.calls,
            "reset": 60.0,
        }


class _PartitionFailureRedditClient:
    def __init__(self, fixture: dict):
        valid = fixture["search_pages"][1]["response"]["data"]["children"][0]
        malformed = json.loads(json.dumps(valid))
        malformed["data"].update({
            "id": "fixture_malformed",
            "name": "t3_fixture_malformed",
            "title": "Malformed fixture with no timestamp",
        })
        malformed["data"].pop("created_utc")
        self.children = [malformed, valid]

    async def request(self, endpoint: str, parameters: dict):
        del parameters
        if "/r/blocked/" in endpoint:
            raise RedditApiError(
                "fixture forbidden", status_code=403, retryable=False
            )
        if "/r/missing/" in endpoint:
            raise RedditApiError(
                "fixture missing", status_code=404, retryable=False
            )
        return self.children, None, {
            "used": 1.0,
            "remaining": 59.0,
            "reset": 60.0,
        }


def test_reddit_collector_isolates_partition_and_malformed_item_failures(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit partition failure fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["blocked", "missing", "typography"],
        reddit_sort="new",
        reddit_page_size=2,
        reddit_max_pages_per_subreddit=1,
        reddit_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])

    result = asyncio.run(RedditCollector(
        service,
        client=_PartitionFailureRedditClient(_fixture()),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))

    assert result == {
        "status": "completed",
        "inserted": 1,
        "pages_fetched": 1,
        "subreddits_completed": 1,
        "subreddits_failed": 2,
        "unavailable": 0,
    }
    assert len(service.observations()) == 1
    errors = service.errors(run["collection_run_id"])
    assert {error["error_code"] for error in errors} == {
        "reddit_authentication",
        "reddit_subreddit_unavailable",
        "reddit_item_invalid",
    }
    states = service.api_collection_states(run["collection_run_id"])
    assert {state["partition_key"]: state["status"] for state in states} == {
        "blocked": "failed",
        "missing": "failed",
        "typography": "completed",
    }


def test_reddit_new_order_advances_scope_high_water_without_reingesting_old_posts(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit incremental fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_sort="new",
        reddit_page_size=10,
        reddit_max_pages_per_subreddit=1,
        reddit_request_delay_seconds=0,
    )
    old_post = _fixture()["search_pages"][0]["response"]["data"]["children"][0]
    first_run = service.start_run(scope["scope_id"])
    first_result = asyncio.run(RedditCollector(
        service,
        client=_SinglePageRedditClient([old_post]),
        max_retries=0,
    ).run(first_run["collection_run_id"], max_items=10))
    assert first_result["inserted"] == 1
    first_state = service.api_scope_state(
        scope["scope_id"], scope["query_id"], "typography"
    )
    assert first_state == {"max_created_utc": 1788260400.0}

    new_post = json.loads(json.dumps(old_post))
    new_post["data"].update({
        "id": "fixture003",
        "name": "t3_fixture003",
        "created_utc": 1788264000,
        "permalink": "/r/typography/comments/fixture003/newer_wordmark/",
        "title": "A newer typography fixture",
    })
    second_run = service.start_run(scope["scope_id"])
    second_result = asyncio.run(RedditCollector(
        service,
        client=_SinglePageRedditClient([new_post, old_post]),
        max_retries=0,
    ).run(second_run["collection_run_id"], max_items=10))

    assert second_result["inserted"] == 1
    assert len(service.observations()) == 2
    assert service.api_scope_state(
        scope["scope_id"], scope["query_id"], "typography"
    ) == {"max_created_utc": 1788264000.0}
    high_water_audits = [
        event for event in service.audit()
        if event["event_type"] == "reddit_item_at_or_before_high_watermark"
    ]
    assert len(high_water_audits) == 1


def test_schema_v15_migration_preserves_existing_social_records(tmp_path: Path):
    database = tmp_path / "legacy-v14.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="reddit",
        name="Reddit migration fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_reddit_post(
        run["collection_run_id"],
        _fixture()["search_pages"][0]["response"]["data"]["children"][0],
        subreddit="typography",
        query_id=scope["query_id"],
    )

    preserved_tables = (
        "research_scopes",
        "queries",
        "collection_runs",
        "observations",
        "raw_events",
        "observation_query_matches",
    )
    with sqlite3.connect(database) as connection:
        observation_id = connection.execute(
            "SELECT observation_id FROM observations"
        ).fetchone()[0]
        raw_payload = connection.execute(
            "SELECT payload_json FROM raw_events"
        ).fetchone()[0]
        connection.executescript(
            """
            DROP TABLE x_request_events;
            DROP TABLE x_run_billing_snapshots;
            DROP TABLE x_billing_settings;
            DROP TABLE x_price_snapshots;
            DROP TABLE tiktok_request_events;
            DROP TABLE tiktok_quota_settings;
            DROP TABLE api_scope_states;
            DROP TABLE api_collection_states;
            PRAGMA user_version = 14;
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
        assert store.table_count("api_collection_states") == 0
        assert store.table_count("api_scope_states") == 0
        assert store.connection.execute(
            "SELECT observation_id FROM observations"
        ).fetchone()[0] == observation_id
        assert store.connection.execute(
            "SELECT payload_json FROM raw_events"
        ).fetchone()[0] == raw_payload

    assert before == after == {
        "research_scopes": 1,
        "queries": 1,
        "collection_runs": 1,
        "observations": 1,
        "raw_events": 1,
        "observation_query_matches": 1,
    }


def _reddit_web_scope_payload() -> dict:
    return {
        "platform": "reddit",
        "name": "Reddit Web fixture",
        "object_type": "writing_system",
        "object_label": "latin",
        "keywords": ["typography"],
        "languages": ["en"],
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2027-09-03T00:00:00Z",
        "max_items": 5,
        "exact_query": "latin typography modern",
        "reddit_subreddits": ["typography"],
        "reddit_access_method": "subreddit_search",
        "reddit_sort": "new",
        "reddit_time_filter": "month",
        "reddit_page_size": 25,
        "reddit_max_pages_per_subreddit": 2,
        "reddit_request_delay_seconds": 1.0,
    }


def test_web_creates_reddit_scope_selects_collector_and_exposes_boolean_readiness(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "glyph-social.sqlite3"
    collected: list[tuple[str, int]] = []

    async def finish_immediately(collector, collection_run_id, *, max_items):
        collected.append((collection_run_id, max_items))
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(RedditCollector, "run", finish_immediately)
    app = create_app(
        database,
        outbound_proxy="http://127.0.0.1:7897",
        reddit_client_id="REDACTED_TEST_CLIENT_ID",
        reddit_client_secret="REDACTED_TEST_CLIENT_SECRET",
        reddit_refresh_token="REDACTED_TEST_REFRESH_TOKEN",
        reddit_user_agent="macos:glyph-social:0.1.0 (by /u/research_fixture)",
    )
    with TestClient(app) as client:
        response = client.post("/api/scopes", json=_reddit_web_scope_payload())
        assert response.status_code == 201
        scope = response.json()
        assert scope["platform_options"]["subreddits"] == ["typography"]
        started = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert started.status_code == 202
        assert started.json()["platform"] == "reddit"
        for _ in range(20):
            if collected:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert collected == [(started.json()["collection_run_id"], 5)]
        health = client.get("/api/health").json()
        assert health["reddit_credentials_configured"] is True
        assert "reddit" in health["platforms"]
        assert "REDACTED_TEST" not in json.dumps(health)


def test_web_rejects_reddit_start_without_credentials_before_creating_run(
    tmp_path: Path,
):
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy="http://127.0.0.1:7897",
        reddit_client_id="",
        reddit_client_secret="",
        reddit_refresh_token="",
        reddit_user_agent="",
    )
    with TestClient(app) as client:
        scope = client.post(
            "/api/scopes", json=_reddit_web_scope_payload()
        ).json()
        response = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert response.status_code == 422
        assert "Reddit" in response.json()["detail"]
        assert client.get("/api/runs").json() == []
        assert client.get("/api/health").json()[
            "reddit_credentials_configured"
        ] is False


def test_reddit_evidence_monitoring_and_export_preserve_bounded_api_audit(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="reddit",
        name="Reddit audit fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_sort="new",
        reddit_page_size=2,
        reddit_max_pages_per_subreddit=2,
        reddit_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    asyncio.run(RedditCollector(
        service,
        client=_FakeRedditClient(_fixture()),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))
    observation = service.observations()[0]

    evidence = service.evidence(observation["observation_id"])
    assert evidence["raw_event"]["kind"] == "reddit_post"
    assert evidence["raw_event"]["matched_query_id"] == scope["query_id"]
    assert evidence["raw_event"]["subreddit"] == "typography"

    monitoring = service.monitoring(tmp_path / "backups")
    assert "reddit" in monitoring["platforms"]
    assert "Reddit Data API" in monitoring["sources"]
    assert monitoring["bounded_api"]["state_counts"]["reddit"] == {
        "completed": 1
    }
    assert monitoring["bounded_api"]["partitions"][0]["partition_key"] == (
        "typography"
    )

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    states = json.loads(
        (export_directory / "api_collection_states.json").read_text(encoding="utf-8")
    )
    with (export_directory / "queries.csv").open(encoding="utf-8") as handle:
        query = next(csv.DictReader(handle))
    assert len(states) == 1
    assert states[0]["platform"] == "reddit"
    assert states[0]["state"]["pages_fetched"] == 2
    assert query["reddit_subreddits"] == "typography"
    assert query["reddit_access_method"] == "subreddit_search"
    assert query["reddit_sort"] == "new"
    assert query["reddit_time_filter"] == "all"
    assert query["reddit_page_size"] == "2"
    assert query["reddit_max_pages_per_subreddit"] == "2"


def test_backup_restore_recovers_reddit_run_and_scope_states(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="reddit",
        name="Reddit backup fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="latin typography modern",
        reddit_subreddits=["typography"],
        reddit_sort="new",
    )
    run = service.start_run(scope["scope_id"])
    service.save_api_collection_state(
        run["collection_run_id"],
        "reddit",
        scope["query_id"],
        "typography",
        {
            "items_seen": 2,
            "last_rate_limit": {"used": 1.0, "remaining": 59.0, "reset": 60.0},
            "next_page_token": "t3_fixture002",
            "pages_fetched": 1,
            "unavailable_count": 1,
        },
        status="running",
    )
    service.save_api_scope_state(
        scope["scope_id"],
        "reddit",
        scope["query_id"],
        "typography",
        {"max_created_utc": 1788260400.0},
    )
    backup = service.create_backup(backup_root, reason="reddit_fixture")

    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DELETE FROM api_collection_states;
            DELETE FROM api_scope_states;
            """
        )
    restored = service.restore_backup(backup_root, backup["backup_id"])

    assert restored["schema_version"] == SCHEMA_VERSION
    assert service.api_collection_states(run["collection_run_id"])[0]["state"][
        "next_page_token"
    ] == "t3_fixture002"
    assert service.api_scope_state(
        scope["scope_id"], scope["query_id"], "typography"
    ) == {"max_created_utc": 1788260400.0}

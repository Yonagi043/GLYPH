from __future__ import annotations

import asyncio
import csv
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.bluesky import ResearchScope
from glyph_features.social_system.collector import XCollector
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import (
    ResearchStore,
    XBillingGateError,
    XBudgetExceeded,
)
from glyph_features.social_system.web import create_app
from glyph_features.social_system.x import (
    XApiError,
    XRecentSearchClient,
    normalize_x_post,
)
from tools.social_io import validation_errors, validator


ROOT = Path(__file__).parents[1]


def _fixture() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/x_api_v2_recent_search.json").read_text(
            encoding="utf-8"
        )
    )


def _scope() -> ResearchScope:
    return ResearchScope(
        query_id="q_x_typography",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography", "wordmark"),
        languages=("en",),
        window_start="2026-08-27T15:00:00Z",
        window_end="2026-09-02T15:00:00Z",
        exact_query="(typography OR wordmark) lang:en -is:retweet",
    )


def _scope_arguments() -> dict:
    return {
        "platform": "x",
        "name": "X recent search fixture",
        "object_type": "writing_system",
        "object_label": "latin",
        "keywords": ["typography", "wordmark"],
        "languages": ["en"],
        "window_start": "2026-08-27T15:00:00Z",
        "window_end": "2026-09-02T15:00:00Z",
        "max_items": 20,
        "exact_query": "(typography OR wordmark) lang:en -is:retweet",
        "max_videos": 20,
        "max_comment_threads_per_video": 0,
        "max_replies_per_thread": 0,
        "x_page_size": 10,
        "x_max_pages": 2,
        "x_request_delay_seconds": 0.0,
        "x_local_run_budget_microusd": 100000,
    }


def test_x_post_normalizes_without_identity_or_manufactured_gold():
    post = _fixture()["search_pages"][0]["response"]["data"][1]

    record = normalize_x_post(
        post,
        scope=_scope(),
        collection_run_id="social_run_x_fixture",
        normalized_at="2026-09-02T16:00:00Z",
    )

    assert record["platform"] == "x"
    assert record["platform_item_id"] == "1962900000000000002"
    assert record["url"] == "https://x.com/i/status/1962900000000000002"
    assert record["language_bcp47"] == "en"
    assert record["annotation_status"] == "candidate"
    assert record["author_ref"] is None
    assert record["author_role"] is None
    assert record["object_type"] is None
    assert record["object_label"] is None
    assert record["aesthetic_terms"] == []
    assert record["stance"] is None
    assert record["engagement"]["like_count"] == 7
    assert record["engagement"]["comment_count"] == 1
    assert record["engagement"]["share_count"] == 1
    assert record["references"] == [{
        "relation": "reply",
        "target_item_id": "1962900000000000001",
        "target_url": "https://x.com/i/status/1962900000000000001",
    }]
    assert "not an X-wide sample" in record["governance"]["notes"]
    assert validation_errors(record, validator()) == []


def test_x_scope_freezes_recent_search_window_pagination_and_budget(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")

    scope = service.create_scope(**_scope_arguments())
    stored = service.get_scope(scope["scope_id"])

    assert stored["platform_options"] == {
        "access_method": "recent_search",
        "end_time": "2026-09-02T15:00:00Z",
        "local_run_budget_microusd": 100000,
        "max_pages": 2,
        "page_size": 10,
        "post_fields": "created_at,lang,public_metrics,referenced_tweets",
        "query": "(typography OR wordmark) lang:en -is:retweet",
        "request_delay_seconds": 0.0,
        "start_time": "2026-08-27T15:00:00Z",
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"window_start": "2026-08-25T14:59:59Z"}, "7"),
        ({"x_page_size": 9}, "10"),
        ({"x_local_run_budget_microusd": 0}, "预算"),
    ],
)
def test_x_scope_rejects_unbounded_recent_search_configuration(
    tmp_path: Path,
    changes: dict,
    message: str,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")

    with pytest.raises(ValueError, match=message):
        service.create_scope(**{**_scope_arguments(), **changes})

    assert service.list_scopes() == []


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict[str, str]):
        self.payload = json.dumps(payload).encode("utf-8")
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


class _FakeXOpener:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float):
        assert timeout == 30.0
        self.requests.append(request)
        page = self.fixture["search_pages"][len(self.requests) - 1]
        return _FakeResponse(page["response"], page["response_headers"])


def test_x_client_maps_next_token_to_pagination_token_and_minimizes_fields():
    fixture = _fixture()
    opener = _FakeXOpener(fixture)
    client = XRecentSearchClient(
        bearer_token="REDACTED_TEST_BEARER_TOKEN",
        proxy_url="http://127.0.0.1:7897",
        opener=opener,
    )

    first = asyncio.run(client.search(fixture["search_pages"][0]["request"]))
    second = asyncio.run(client.search(fixture["search_pages"][1]["request"]))

    assert first["next_token"] == "REDACTED_FIXTURE_NEXT_TOKEN_1"
    assert first["result_count"] == 2
    assert first["rate_limit"] == {
        "limit": 450,
        "remaining": 449,
        "reset": 1788362100,
    }
    assert second["next_token"] is None
    assert second["result_count"] == 1
    first_query = parse_qs(urlparse(opener.requests[0].full_url).query)
    second_query = parse_qs(urlparse(opener.requests[1].full_url).query)
    assert first_query["tweet.fields"] == [
        "created_at,lang,public_metrics,referenced_tweets"
    ]
    assert "expansions" not in first_query
    assert "user.fields" not in first_query
    assert second_query["pagination_token"] == [
        "REDACTED_FIXTURE_NEXT_TOKEN_1"
    ]
    assert all(
        request.get_header("Authorization") == "Bearer REDACTED_TEST_BEARER_TOKEN"
        for request in opener.requests
    )
    assert all("REDACTED_TEST" not in request.full_url for request in opener.requests)


def test_x_run_requires_console_hard_limit_and_binds_dated_price_snapshot(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())

    initial = service.x_billing_status()
    assert initial["console_limit_confirmed"] is False
    assert initial["circuit_breaker_open"] is True
    assert initial["active_price"]["resource_type"] == "post_read"
    assert initial["active_price"]["unit_price_microusd"] == 5000
    assert initial["active_price"]["unit_price_usd"] == "0.005"
    assert initial["active_price"]["effective_date"] == "2026-09-02"

    with pytest.raises(ValueError, match="Console.*spending limit"):
        service.start_run(scope["scope_id"])
    assert service.list_runs() == []

    configured = service.configure_x_billing_guard(
        local_cycle_spending_cap_microusd=1_000_000,
        console_hard_spending_limit_microusd=2_000_000,
        billing_cycle_start="2026-01-01T00:00:00Z",
        billing_cycle_end="2027-01-01T00:00:00Z",
        console_limit_confirmed=True,
        confirmed_by="fixture_researcher",
    )
    assert configured["console_limit_confirmed"] is True
    assert configured["circuit_breaker_open"] is False

    manifest = service.start_run(scope["scope_id"])
    snapshot = service.x_run_billing_snapshot(manifest["collection_run_id"])
    assert snapshot["unit_price_microusd"] == 5000
    assert snapshot["unit_price_usd"] == "0.005"
    assert snapshot["local_run_budget_microusd"] == 100000
    assert snapshot["local_cycle_spending_cap_microusd"] == 1_000_000
    assert snapshot["console_hard_spending_limit_microusd"] == 2_000_000


def _configure_x_guard(
    service: SocialNarrativeService,
    *,
    local_cycle_cap: int = 1_000_000,
) -> None:
    service.configure_x_billing_guard(
        local_cycle_spending_cap_microusd=local_cycle_cap,
        console_hard_spending_limit_microusd=2_000_000,
        billing_cycle_start="2026-01-01T00:00:00Z",
        billing_cycle_end="2027-01-01T00:00:00Z",
        console_limit_confirmed=True,
        confirmed_by="fixture_researcher",
    )


def test_x_request_events_reserve_worst_case_and_settle_actual_resources(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])

    succeeded = service.reserve_x_request(
        run["collection_run_id"], max_resources=10
    )
    service.finish_x_request(
        succeeded, outcome="succeeded", actual_resources=2
    )
    failed = service.reserve_x_request(
        run["collection_run_id"], max_resources=10
    )
    service.finish_x_request(
        failed,
        outcome="failed",
        actual_resources=0,
        error_code="x_http_503",
    )

    events = service.x_request_events(run["collection_run_id"])
    assert [event["reserved_cost_microusd"] for event in events] == [50000, 50000]
    assert [event["actual_resources"] for event in events] == [2, 0]
    assert [event["actual_cost_microusd"] for event in events] == [10000, 0]
    assert [event["outcome"] for event in events] == ["succeeded", "failed"]
    status = service.x_billing_status()
    assert status["accrued_cost_microusd"] == 10000
    assert status["reserved_exposure_microusd"] == 0

    final_allowed = service.reserve_x_request(
        run["collection_run_id"], max_resources=10
    )
    service.finish_x_request(
        final_allowed, outcome="succeeded", actual_resources=10
    )
    with pytest.raises(XBudgetExceeded) as captured:
        service.reserve_x_request(run["collection_run_id"], max_resources=10)
    assert captured.value.budget_scope == "run"
    assert service.x_billing_status()["circuit_breaker_open"] is False


def test_x_cycle_budget_exhaustion_opens_global_circuit_breaker(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service, local_cycle_cap=60000)
    run = service.start_run(scope["scope_id"])
    event_id = service.reserve_x_request(
        run["collection_run_id"], max_resources=10
    )
    service.finish_x_request(event_id, outcome="succeeded", actual_resources=2)

    with pytest.raises(XBudgetExceeded) as captured:
        service.reserve_x_request(run["collection_run_id"], max_resources=11)

    assert captured.value.budget_scope == "cycle"
    status = service.x_billing_status()
    assert status["circuit_breaker_open"] is True
    assert status["circuit_breaker_reason"] == "local_billing_cycle_cap_exhausted"


def test_x_price_change_stops_old_run_and_new_run_binds_new_snapshot(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    first_run = service.start_run(scope["scope_id"])
    first_snapshot = service.x_run_billing_snapshot(
        first_run["collection_run_id"]
    )

    updated_price = service.record_x_price_snapshot(
        unit_price_microusd=6000,
        effective_date="2026-09-03",
        source_url="https://docs.x.com/x-api/getting-started/pricing",
        pricing_policy_version="x_pay_per_use_2026-09-03_fixture",
    )

    assert updated_price["unit_price_usd"] == "0.006"
    assert service.x_billing_status()["circuit_breaker_reason"] == (
        "active_price_snapshot_changed"
    )
    with pytest.raises(XBillingGateError):
        service.reserve_x_request(first_run["collection_run_id"], max_resources=10)
    _configure_x_guard(service)
    second_run = service.start_run(scope["scope_id"])
    second_snapshot = service.x_run_billing_snapshot(
        second_run["collection_run_id"]
    )

    assert first_snapshot["unit_price_microusd"] == 5000
    assert second_snapshot["unit_price_microusd"] == 6000
    assert second_snapshot["price_snapshot_id"] != first_snapshot[
        "price_snapshot_id"
    ]


class _FakeXClient:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.calls: list[dict] = []
        self.response_index = 0

    async def search(self, parameters: dict) -> dict:
        self.calls.append(dict(parameters))
        page = self.fixture["search_pages"][self.response_index]
        self.response_index += 1
        assert parameters == page["request"]
        payload = page["response"]
        return {
            "items": payload["data"],
            "next_token": payload["meta"].get("next_token"),
            "result_count": payload["meta"]["result_count"],
            "rate_limit": {
                "limit": int(page["response_headers"]["x-rate-limit-limit"]),
                "remaining": int(
                    page["response_headers"]["x-rate-limit-remaining"]
                ),
                "reset": int(page["response_headers"]["x-rate-limit-reset"]),
            },
        }


def test_x_collector_resumes_token_charges_resources_and_is_idempotent(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    client = _FakeXClient(_fixture())
    collector = XCollector(service, client=client, max_retries=0)

    result = asyncio.run(collector.run(run["collection_run_id"], max_items=20))

    assert result == {
        "status": "completed",
        "inserted": 3,
        "items_seen": 3,
        "pages_fetched": 2,
        "requests": 2,
        "partitions_failed": 0,
    }
    assert client.calls[1]["pagination_token"] == (
        "REDACTED_FIXTURE_NEXT_TOKEN_1"
    )
    events = service.x_request_events(run["collection_run_id"])
    assert [event["reserved_resources"] for event in events] == [10, 10]
    assert [event["actual_resources"] for event in events] == [2, 1]
    assert [event["actual_cost_microusd"] for event in events] == [10000, 5000]
    assert {event["outcome"] for event in events} == {"succeeded"}
    states = service.api_collection_states(run["collection_run_id"])
    assert len(states) == 1
    assert states[0]["partition_key"] == "recent_search"
    assert states[0]["status"] == "completed"
    assert states[0]["state"] == {
        "items_seen": 3,
        "last_rate_limit": {
            "limit": 450,
            "remaining": 448,
            "reset": 1788362100,
        },
        "next_token": None,
        "pages_fetched": 2,
    }
    assert len(service.observations()) == 3
    matches = service.observation_query_matches(run["collection_run_id"])
    assert len(matches) == 3
    assert {match["query_id"] for match in matches} == {scope["query_id"]}

    repeated = asyncio.run(
        collector.run(run["collection_run_id"], max_items=20)
    )
    assert repeated["inserted"] == 0
    assert repeated["requests"] == 0
    assert len(client.calls) == 2


class _RetryOnceXClient(_FakeXClient):
    def __init__(self, fixture: dict, status_code: int):
        super().__init__(fixture)
        self.status_code = status_code
        self.failed = False

    async def search(self, parameters: dict) -> dict:
        if not self.failed:
            self.failed = True
            self.calls.append(dict(parameters))
            raise XApiError(
                f"fixture HTTP {self.status_code}",
                status_code=self.status_code,
                api_code=None,
                retryable=True,
                retry_after_seconds=4.0,
            )
        return await super().search(parameters)


@pytest.mark.parametrize("status_code", [429, 503])
def test_x_collector_accounts_for_each_retry_attempt(
    tmp_path: Path,
    status_code: int,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    client = _RetryOnceXClient(_fixture(), status_code)
    delays: list[float] = []

    result = asyncio.run(XCollector(
        service,
        client=client,
        max_retries=1,
        sleep=lambda delay: delays.append(delay) or asyncio.sleep(0),
    ).run(run["collection_run_id"], max_items=20))

    assert result["status"] == "completed"
    assert result["inserted"] == 3
    assert result["requests"] == 3
    assert delays == [4.0]
    events = service.x_request_events(run["collection_run_id"])
    assert [event["outcome"] for event in events] == [
        "failed",
        "succeeded",
        "succeeded",
    ]
    assert events[0]["actual_cost_microusd"] == 0
    assert events[0]["error_code"] == (
        "x_rate_limited" if status_code == 429 else "x_http_503"
    )


class _InterruptingXClient(_FakeXClient):
    def __init__(self, fixture: dict):
        super().__init__(fixture)
        self.interrupted = False

    async def search(self, parameters: dict) -> dict:
        if self.response_index == 1 and not self.interrupted:
            self.interrupted = True
            self.calls.append(dict(parameters))
            raise asyncio.CancelledError
        return await super().search(parameters)


def test_x_collector_resumes_next_token_after_indeterminate_cancellation(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**{
        **_scope_arguments(),
        "x_local_run_budget_microusd": 200000,
    })
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    client = _InterruptingXClient(_fixture())
    collector = XCollector(service, client=client, max_retries=0)

    stopped = asyncio.run(
        collector.run(run["collection_run_id"], max_items=20)
    )
    assert stopped["status"] == "stopped"
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["status"] == "running"
    assert state["state"]["next_token"] == "REDACTED_FIXTURE_NEXT_TOKEN_1"

    resumed = asyncio.run(
        collector.run(run["collection_run_id"], max_items=20)
    )
    assert resumed["status"] == "completed"
    assert resumed["inserted"] == 1
    assert client.calls[-1]["pagination_token"] == (
        "REDACTED_FIXTURE_NEXT_TOKEN_1"
    )
    events = service.x_request_events(run["collection_run_id"])
    assert [event["outcome"] for event in events] == [
        "succeeded",
        "indeterminate",
        "succeeded",
    ]
    assert [event["actual_cost_microusd"] for event in events] == [
        10000,
        50000,
        5000,
    ]


class _FailingXClient:
    def __init__(self, error: XApiError):
        self.error = error
        self.calls: list[dict] = []

    async def search(self, parameters: dict) -> dict:
        self.calls.append(dict(parameters))
        raise self.error


def test_x_collector_does_not_retry_authentication_failure(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    client = _FailingXClient(XApiError(
        "fixture HTTP 401",
        status_code=401,
        api_code=None,
        retryable=False,
    ))

    result = asyncio.run(XCollector(
        service, client=client, max_retries=3
    ).run(run["collection_run_id"], max_items=20))

    assert result["status"] == "failed"
    assert result["requests"] == 1
    assert len(client.calls) == 1
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["status"] == "failed"
    assert state["error_code"] == "x_authentication"
    event = service.x_request_events(run["collection_run_id"])[0]
    assert event["outcome"] == "failed"
    assert event["actual_cost_microusd"] == 0


def test_x_collector_stops_before_request_that_exceeds_run_budget(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**{
        **_scope_arguments(),
        "x_local_run_budget_microusd": 50000,
    })
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    client = _FakeXClient(_fixture())

    result = asyncio.run(XCollector(
        service, client=client, max_retries=0
    ).run(run["collection_run_id"], max_items=20))

    assert result["status"] == "budget_exhausted"
    assert result["inserted"] == 2
    assert result["requests"] == 1
    assert len(client.calls) == 1
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["status"] == "running"
    assert state["state"]["next_token"] == "REDACTED_FIXTURE_NEXT_TOKEN_1"
    assert service.x_billing_status()["circuit_breaker_open"] is False


def test_x_ingest_strips_unapproved_identity_before_raw_evidence(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    post = dict(_fixture()["search_pages"][0]["response"]["data"][0])
    post["author_id"] = "REDACTED_UNAPPROVED_AUTHOR_ID"

    assert service.process_x_post(
        run["collection_run_id"], post, query_id=scope["query_id"]
    )

    observation = service.observations()[0]
    evidence = service.evidence(observation["observation_id"])
    assert "author_id" not in evidence["raw_event"]["resource"]
    assert evidence["observation"]["author_ref"] is None


def test_schema_v17_migration_preserves_v16_run_and_api_state(tmp_path: Path):
    database = tmp_path / "legacy-v16.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="bluesky",
        name="v16 migration fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-08-27T15:00:00Z",
        window_end="2026-09-02T15:00:00Z",
        max_items=20,
    )
    run = service.start_run(scope["scope_id"])
    service.save_api_collection_state(
        run["collection_run_id"],
        "reddit",
        scope["query_id"],
        "migration-fixture",
        {"next_page_token": "REDACTED_V16_CURSOR", "pages_fetched": 1},
        status="running",
    )
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            DROP TABLE x_request_events;
            DROP TABLE x_run_billing_snapshots;
            DROP TABLE x_billing_settings;
            DROP TABLE x_price_snapshots;
            PRAGMA user_version = 16;
            """
        )
    finally:
        connection.close()

    migrated = SocialNarrativeService(database)

    assert migrated.get_scope(scope["scope_id"])["name"] == "v16 migration fixture"
    assert migrated.get_run(run["collection_run_id"])["status"] == "running"
    assert migrated.api_collection_states(run["collection_run_id"])[0]["state"] == {
        "next_page_token": "REDACTED_V16_CURSOR",
        "pages_fetched": 1,
    }
    status = migrated.x_billing_status()
    assert status["console_limit_confirmed"] is False
    assert status["circuit_breaker_open"] is True
    assert status["active_price"]["unit_price_microusd"] == 5000


def test_backup_restore_recovers_x_billing_requests_and_resume_state(
    tmp_path: Path,
):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    event_id = service.reserve_x_request(
        run["collection_run_id"], max_resources=10
    )
    service.finish_x_request(
        event_id, outcome="succeeded", actual_resources=2
    )
    service.save_api_collection_state(
        run["collection_run_id"],
        "x",
        scope["query_id"],
        "recent_search",
        {
            "items_seen": 2,
            "last_rate_limit": {"limit": 450, "remaining": 449, "reset": 1788362100},
            "next_token": "REDACTED_FIXTURE_NEXT_TOKEN_1",
            "pages_fetched": 1,
        },
        status="running",
    )
    backup = service.create_backup(backup_root, reason="x_fixture")
    service.record_x_price_snapshot(
        unit_price_microusd=6000,
        effective_date="2026-09-03",
        source_url="https://docs.x.com/x-api/getting-started/pricing",
        pricing_policy_version="x_pay_per_use_2026-09-03_fixture",
    )

    restored = service.restore_backup(backup_root, backup["backup_id"])

    assert restored["integrity_check"] == "ok"
    assert restored["source_schema_version"] == 17
    assert restored["schema_version"] == 17
    assert service.x_billing_status()["active_price"]["unit_price_microusd"] == 5000
    snapshot = service.x_run_billing_snapshot(run["collection_run_id"])
    assert snapshot["unit_price_microusd"] == 5000
    events = service.x_request_events(run["collection_run_id"])
    assert len(events) == 1
    assert events[0]["actual_cost_microusd"] == 10000
    state = service.api_collection_states(run["collection_run_id"])[0]
    assert state["state"]["next_token"] == "REDACTED_FIXTURE_NEXT_TOKEN_1"


def test_x_run_creation_rolls_back_when_billing_binding_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)

    def fail_binding(
        self: ResearchStore,
        collection_run_id: str,
        binding: dict,
        *,
        commit: bool = True,
    ) -> dict:
        raise sqlite3.OperationalError("fixture binding failure")

    monkeypatch.setattr(ResearchStore, "bind_x_run_billing", fail_binding)

    with pytest.raises(sqlite3.OperationalError, match="fixture binding failure"):
        service.start_run(scope["scope_id"])

    assert service.list_runs() == []


@pytest.mark.parametrize(
    ("bearer_token", "proxy_url"),
    [
        ("", "http://127.0.0.1:7897"),
        ("REDACTED_TEST_BEARER_TOKEN", None),
        ("REDACTED_TEST_BEARER_TOKEN", "http://127.0.0.1:9999"),
    ],
)
def test_web_rejects_x_start_without_bearer_and_fixed_proxy(
    tmp_path: Path,
    bearer_token: str,
    proxy_url: str | None,
):
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy=proxy_url,
        x_bearer_token=bearer_token,
    )
    with TestClient(app) as client:
        created = client.post("/api/scopes", json=_scope_arguments())
        assert created.status_code == 201
        response = client.post(
            "/api/runs", json={"scope_id": created.json()["scope_id"]}
        )

        assert response.status_code == 422
        assert "X API" in response.json()["detail"]
        assert client.get("/api/runs").json() == []
        health = client.get("/api/health").json()
        assert health["x_credentials_configured"] is False
        assert health["x_collection_ready"] is False
        assert "x" in health["platforms"]
        assert "REDACTED_TEST" not in json.dumps(health)


def test_web_requires_x_billing_guard_before_creating_run(tmp_path: Path):
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy="http://127.0.0.1:7897",
        x_bearer_token="REDACTED_TEST_BEARER_TOKEN",
    )
    with TestClient(app) as client:
        scope = client.post("/api/scopes", json=_scope_arguments()).json()

        response = client.post("/api/runs", json={"scope_id": scope["scope_id"]})

        assert response.status_code == 422
        assert "Console" in response.json()["detail"]
        assert client.get("/api/runs").json() == []
        health = client.get("/api/health").json()
        assert health["x_credentials_configured"] is True
        assert health["x_collection_ready"] is False
        assert health["x_billing"]["circuit_breaker_open"] is True
        assert "REDACTED_TEST" not in json.dumps(health)


def test_web_selects_x_collector_with_boolean_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    collected: list[tuple[str, int]] = []

    async def finish_immediately(
        collector: XCollector, collection_run_id: str, *, max_items: int
    ) -> dict:
        collected.append((collection_run_id, max_items))
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(XCollector, "run", finish_immediately)
    app = create_app(
        tmp_path / "glyph-social.sqlite3",
        outbound_proxy="http://127.0.0.1:7897",
        x_bearer_token="REDACTED_TEST_BEARER_TOKEN",
    )
    _configure_x_guard(app.state.service)
    with TestClient(app) as client:
        scope = client.post("/api/scopes", json=_scope_arguments()).json()
        started = client.post("/api/runs", json={"scope_id": scope["scope_id"]})

        assert started.status_code == 202
        assert started.json()["platform"] == "x"
        for _ in range(20):
            if collected:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert collected == [(started.json()["collection_run_id"], 20)]
        health = client.get("/api/health").json()
        assert health["x_credentials_configured"] is True
        assert health["x_collection_ready"] is True
        assert "REDACTED_TEST" not in json.dumps(health)


def test_x_monitoring_and_export_include_billing_and_resource_audit(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(**_scope_arguments())
    _configure_x_guard(service)
    run = service.start_run(scope["scope_id"])
    asyncio.run(XCollector(
        service, client=_FakeXClient(_fixture()), max_retries=0
    ).run(run["collection_run_id"], max_items=20))

    monitoring = service.monitoring(tmp_path / "backups")
    assert "x" in monitoring["platforms"]
    assert "X API v2 recent search" in monitoring["sources"]
    assert monitoring["bounded_api"]["state_counts"]["x"] == {"completed": 1}
    assert monitoring["x_billing"]["accrued_cost_microusd"] == 15000
    assert monitoring["x_billing"]["active_price"]["effective_date"] == (
        "2026-09-02"
    )

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    events = json.loads(
        (export_directory / "x_request_events.json").read_text(encoding="utf-8")
    )
    binding = json.loads(
        (export_directory / "x_run_billing_snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    billing = json.loads(
        (export_directory / "x_billing_status.json").read_text(encoding="utf-8")
    )
    with (export_directory / "queries.csv").open(encoding="utf-8") as handle:
        query = next(csv.DictReader(handle))

    assert [event["actual_resources"] for event in events] == [2, 1]
    assert binding["unit_price_microusd"] == 5000
    assert billing["accrued_cost_microusd"] == 15000
    assert query["x_query"] == _scope_arguments()["exact_query"]
    assert query["x_page_size"] == "10"
    assert query["x_max_pages"] == "2"
    assert query["x_local_run_budget_microusd"] == "100000"
    exported_text = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in export_directory.rglob("*")
        if path.is_file()
    )
    assert "REDACTED_TEST_BEARER_TOKEN" not in exported_text


def test_x_controls_are_present_without_browser_credential_input():
    static_root = ROOT / "src/glyph_features/social_system/static"
    html = (static_root / "index.html").read_text(encoding="utf-8")
    javascript = (static_root / "app.js").read_text(encoding="utf-8")

    assert 'name="platform" value="x"' in html
    for field in (
        "x_page_size",
        "x_max_pages",
        "x_request_delay_seconds",
        "x_local_run_budget_microusd",
    ):
        assert f'name="{field}"' in html
        assert field in javascript
    assert "x_collection_ready" in javascript
    assert "active_price" in javascript
    assert "remaining_local_cycle_microusd" in javascript
    assert "x_bearer_token" not in html
    assert "x_bearer_token" not in javascript
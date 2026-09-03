from __future__ import annotations

import asyncio
import csv
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.backups import create_backup as create_database_backup
from glyph_features.social_system.bluesky import ResearchScope
from glyph_features.social_system.collector import MastodonCollector
from glyph_features.social_system.mastodon import (
    MastodonApiClient,
    MastodonApiError,
    canonical_federated_account,
    clean_mastodon_html,
    normalize_mastodon_status,
)
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.web import create_app
from tools.social_io import validation_errors, validator


ROOT = Path(__file__).parents[1]


def _fixture() -> dict:
    return json.loads(
        (ROOT / "tests/fixtures/mastodon_api_v1.json").read_text(encoding="utf-8")
    )


def _scope() -> ResearchScope:
    return ResearchScope(
        query_id="q_mastodon_typography",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography",),
        languages=("en",),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        exact_query="#typography",
    )


def test_mastodon_status_normalizes_to_v02_without_manufacturing_gold():
    fixture = _fixture()
    status = fixture["observer.example"]["typography"][0]

    assert clean_mastodon_html(status["content"]) == (
        "Typography & identity\nSecond line #typography"
    )
    assert canonical_federated_account(status["account"]) == (
        "redacted@origin.example"
    )

    record = normalize_mastodon_status(
        status,
        observed_instance="observer.example",
        hashtag="typography",
        scope=_scope(),
        collection_run_id="social_run_mastodon_fixture",
        normalized_at="2026-09-02T10:06:00Z",
    )

    assert record is not None
    assert record["schema_version"] == "0.2.0"
    assert record["platform"] == "mastodon"
    assert record["platform_item_id"] == "status:origin.example:109876543210"
    assert record["url"] == "https://origin.example/@redacted/109876543210"
    assert record["text"] == "Typography & identity\nSecond line #typography"
    assert record["language_bcp47"] == "en"
    assert record["engagement"] == {
        "like_count": 5,
        "comment_count": 3,
        "share_count": 4,
        "quote_count": None,
        "view_count": None,
        "score": None,
        "observed_at": "2026-09-02T10:05:00Z",
        "is_public": True,
    }
    assert record["governance"]["author_handling"] == "local_only"
    assert "observer.example" in record["governance"]["notes"]
    assert "visibility=public" in record["governance"]["notes"]
    assert record["author_ref"] is None
    assert record["author_role"] is None
    assert record["object_type"] is None
    assert record["object_label"] is None
    assert record["aesthetic_terms"] == []
    assert record["stance"] is None
    assert validation_errors(record, validator()) == []


def test_mastodon_identity_is_stable_across_observing_instances_and_replies_link():
    fixture = _fixture()
    first = normalize_mastodon_status(
        fixture["observer.example"]["typography"][0],
        observed_instance="observer.example",
        hashtag="typography",
        scope=_scope(),
        collection_run_id="social_run_mastodon_fixture",
        normalized_at="2026-09-02T10:06:00Z",
    )
    second = normalize_mastodon_status(
        fixture["second.example"]["typography"][0],
        observed_instance="second.example",
        hashtag="typography",
        scope=_scope(),
        collection_run_id="social_run_mastodon_fixture",
        normalized_at="2026-09-02T10:06:00Z",
    )
    reply = normalize_mastodon_status(
        fixture["observer.example"]["typography"][1],
        observed_instance="observer.example",
        hashtag="typography",
        scope=_scope(),
        collection_run_id="social_run_mastodon_fixture",
        normalized_at="2026-09-02T10:11:00Z",
    )

    assert first is not None and second is not None and reply is not None
    assert first["platform_item_id"] == second["platform_item_id"]
    assert first["observation_id"] == second["observation_id"]
    assert reply["references"] == [{
        "relation": "reply",
        "target_item_id": "status:observer.example:700001",
        "target_url": None,
    }]


def test_mastodon_private_status_is_not_normalized_from_public_timeline():
    status = _fixture()["observer.example"]["typography"][2]
    assert normalize_mastodon_status(
        status,
        observed_instance="observer.example",
        hashtag="typography",
        scope=_scope(),
        collection_run_id="social_run_mastodon_fixture",
        normalized_at="2026-09-02T10:21:00Z",
    ) is None


def test_mastodon_search_governance_describes_instance_dependent_search():
    record = normalize_mastodon_status(
        _fixture()["observer.example"]["typography"][0],
        observed_instance="observer.example",
        hashtag="typography identity",
        access_method="search_statuses",
        scope=ResearchScope(
            query_id="q_mastodon_search",
            object_type="writing_system",
            object_label="latin",
            keywords=("typography",),
            languages=("en",),
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-03T00:00:00Z",
            exact_query="typography identity",
        ),
        collection_run_id="social_run_mastodon_search_fixture",
        normalized_at="2026-09-02T10:06:00Z",
    )

    assert record is not None
    notes = record["governance"]["notes"]
    assert "bounded status search" in notes
    assert "availability and ranking are instance-dependent" in notes
    assert "hashtag timeline" not in notes


@pytest.mark.parametrize(
    "exact_query",
    ["typography", "#type design", "#typography since:2026-09-01"],
)
def test_mastodon_hashtag_timeline_rejects_non_hashtag_queries(
    tmp_path: Path, exact_query: str
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")

    with pytest.raises(ValueError, match="单个 #hashtag"):
        service.create_scope(
            platform="mastodon",
            name="Invalid Mastodon hashtag fixture",
            object_type="writing_system",
            object_label="latin",
            keywords=["typography"],
            languages=["en"],
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-03T00:00:00Z",
            max_items=10,
            exact_query=exact_query,
            mastodon_instances=["observer.example"],
            mastodon_access_method="hashtag_timeline",
        )


def test_mastodon_scope_freezes_instances_and_manifest_before_collection(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon typography fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=20,
        exact_query="#typography",
        mastodon_instances=["observer.example", "https://SECOND.example/"],
        mastodon_access_method="hashtag_timeline",
        mastodon_page_size=20,
        mastodon_max_pages_per_instance=2,
        mastodon_request_delay_seconds=1.0,
    )

    assert scope["platform"] == "mastodon"
    query = service.get_scope(scope["scope_id"])["queries"][0]
    assert query["platform_options"] == {
        "access_method": "hashtag_timeline",
        "instances": ["observer.example", "second.example"],
        "max_pages_per_instance": 2,
        "page_size": 20,
        "request_delay_seconds": 1.0,
    }

    manifest = service.start_run(scope["scope_id"])
    assert manifest["schema_version"] == "0.2.0"
    assert manifest["platform"] == "mastodon"
    assert manifest["sampling"]["method"] == "api_pagination"
    assert "observer.example" in manifest["notes"]
    assert "second.example" in manifest["notes"]
    assert "不代表 Mastodon 全网样本" in manifest["notes"]


class _FakeMastodonClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str, dict]] = []

    async def request(
        self, instance: str, endpoint: str, parameters: dict
    ) -> tuple[list[dict], str | None]:
        self.calls.append((instance, endpoint, parameters))
        if instance == "failed.example":
            raise MastodonApiError(
                "fixture authentication required",
                status_code=401,
                retryable=False,
            )
        items = self.payload[instance]["typography"]
        if parameters.get("max_id") is None:
            return items[:1], "PAGE_2" if instance == "observer.example" else None
        assert parameters["max_id"] == "PAGE_2"
        return items[1:2], None


def test_mastodon_collector_isolates_instance_failures_and_audits_sightings(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon multi-instance fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=[
            "observer.example",
            "second.example",
            "failed.example",
        ],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=2,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _FakeMastodonClient(_fixture())

    result = asyncio.run(MastodonCollector(
        service,
        client=client,
        sleep=lambda _delay: asyncio.sleep(0),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))

    assert result == {
        "status": "completed",
        "inserted": 2,
        "instances_completed": 2,
        "instances_failed": 1,
        "sightings": 3,
    }
    assert len(service.observations()) == 2
    sightings = service.mastodon_sightings(run["collection_run_id"])
    assert len(sightings) == 3
    duplicate_sightings = [
        row for row in sightings
        if row["platform_item_id"] == "status:origin.example:109876543210"
    ]
    assert {row["observed_instance"] for row in duplicate_sightings} == {
        "observer.example", "second.example",
    }
    states = service.mastodon_instance_states(run["collection_run_id"])
    assert [(row["observed_instance"], row["status"]) for row in states] == [
        ("failed.example", "failed"),
        ("observer.example", "completed"),
        ("second.example", "completed"),
    ]
    errors = service.errors(run["collection_run_id"])
    assert len(errors) == 1
    assert errors[0]["error_code"] == "mastodon_instance_authentication"
    assert "failed.example" in errors[0]["message"]


class _InterruptingMastodonClient:
    def __init__(self, payload: dict):
        self.items = payload["observer.example"]["typography"]
        self.calls: list[dict] = []

    async def request(
        self, instance: str, endpoint: str, parameters: dict
    ) -> tuple[list[dict], str | None]:
        assert instance == "observer.example"
        assert endpoint.endswith("/typography")
        self.calls.append(dict(parameters))
        if len(self.calls) == 2:
            raise asyncio.CancelledError
        if parameters.get("max_id") is None:
            return self.items[:1], "PAGE_2"
        assert parameters["max_id"] == "PAGE_2"
        return self.items[1:2], None


def test_mastodon_collector_resumes_each_instance_from_saved_page_token(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon resume fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=2,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _InterruptingMastodonClient(_fixture())
    collector = MastodonCollector(service, client=client, max_retries=0)

    interrupted = asyncio.run(collector.run(run["collection_run_id"], max_items=10))
    assert interrupted["status"] == "stopped"
    assert service.mastodon_instance_states(run["collection_run_id"])[0][
        "next_page_token"
    ] == "PAGE_2"

    resumed = asyncio.run(collector.run(run["collection_run_id"], max_items=10))

    assert client.calls[2]["max_id"] == "PAGE_2"
    assert resumed == {
        "status": "completed",
        "inserted": 1,
        "instances_completed": 1,
        "instances_failed": 0,
        "sightings": 1,
    }
    state = service.mastodon_instance_states(run["collection_run_id"])[0]
    assert state["pages_fetched"] == 2
    assert state["statuses_seen"] == 2
    assert state["sightings_count"] == 2


class _RetryingMastodonClient:
    def __init__(self, status: dict):
        self.status = status
        self.calls = 0

    async def request(
        self, instance: str, endpoint: str, parameters: dict
    ) -> tuple[list[dict], str | None]:
        del instance, endpoint, parameters
        self.calls += 1
        if self.calls <= 2:
            status_code = 429 if self.calls == 1 else 503
            raise MastodonApiError(
                f"fixture HTTP {status_code}",
                status_code=status_code,
                retryable=True,
            )
        return [self.status], None


def test_mastodon_collector_retries_429_and_5xx_without_error_pollution(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon retry fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=1,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    client = _RetryingMastodonClient(
        _fixture()["observer.example"]["typography"][0]
    )
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(MastodonCollector(
        service,
        client=client,
        sleep=record_delay,
        max_retries=2,
    ).run(run["collection_run_id"], max_items=10))

    assert result["status"] == "completed"
    assert result["inserted"] == 1
    assert client.calls == 3
    assert delays == [1.0, 2.0]
    assert service.errors(run["collection_run_id"]) == []
    assert service.mastodon_instance_states(run["collection_run_id"])[0][
        "status"
    ] == "completed"


class _IncrementalMastodonClient:
    def __init__(self, status: dict):
        self.status = status
        self.calls: list[dict] = []

    async def request(
        self, instance: str, endpoint: str, parameters: dict
    ) -> tuple[list[dict], str | None]:
        del instance, endpoint
        self.calls.append(dict(parameters))
        return ([self.status] if parameters.get("since_id") is None else []), None


class _MalformedMastodonClient:
    def __init__(self, statuses: list[dict]):
        self.statuses = statuses

    async def request(
        self, instance: str, endpoint: str, parameters: dict
    ) -> tuple[list[dict], str | None]:
        del instance, endpoint, parameters
        return self.statuses, None


def test_mastodon_collector_isolates_malformed_status_within_page(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon malformed status fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=2,
        mastodon_max_pages_per_instance=1,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    valid_status = _fixture()["observer.example"]["typography"][0]
    malformed_status = dict(valid_status, id="malformed")
    malformed_status.pop("created_at")

    result = asyncio.run(MastodonCollector(
        service,
        client=_MalformedMastodonClient([malformed_status, valid_status]),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))

    assert result["status"] == "completed"
    assert result["inserted"] == 1
    assert len(service.observations()) == 1
    errors = service.errors(run["collection_run_id"])
    assert len(errors) == 1
    assert errors[0]["error_code"] == "mastodon_status_invalid"
    assert errors[0]["retryable"] is False


def test_mastodon_new_run_uses_completed_instance_high_watermark(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon incremental fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=1,
        mastodon_request_delay_seconds=0,
    )
    status = _fixture()["observer.example"]["typography"][0]
    client = _IncrementalMastodonClient(status)
    first_run = service.start_run(scope["scope_id"])
    first = asyncio.run(MastodonCollector(
        service, client=client, max_retries=0
    ).run(first_run["collection_run_id"], max_items=10))
    second_run = service.start_run(scope["scope_id"])
    second = asyncio.run(MastodonCollector(
        service, client=client, max_retries=0
    ).run(second_run["collection_run_id"], max_items=10))

    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert client.calls == [
        {"limit": 1, "max_id": None},
        {"limit": 1, "max_id": None, "since_id": "700001"},
    ]
    assert len(service.observations()) == 1


def test_mastodon_max_items_truncation_does_not_advance_high_watermark(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon truncated page fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=2,
        mastodon_max_pages_per_instance=1,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    query_id = service.get_scope(scope["scope_id"])["queries"][0]["query_id"]

    result = asyncio.run(MastodonCollector(
        service,
        client=_FakeMastodonClient(_fixture()),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=1))

    assert result["inserted"] == 1
    assert service.mastodon_scope_high_watermark(
        scope["scope_id"], query_id, "observer.example"
    ) is None


def test_schema_v14_migration_preserves_existing_social_records(tmp_path: Path):
    database = tmp_path / "legacy-v13.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon migration fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
    )
    run = service.start_run(scope["scope_id"])
    inserted, sighting_inserted = service.process_mastodon_status(
        run["collection_run_id"],
        _fixture()["observer.example"]["typography"][0],
        observed_instance="observer.example",
        hashtag="typography",
    )
    assert inserted and sighting_inserted

    preserved_tables = (
        "research_scopes", "queries", "collection_runs", "observations", "raw_events",
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
            DROP TABLE api_scope_states;
            DROP TABLE api_collection_states;
            DROP TABLE mastodon_sightings;
            DROP TABLE mastodon_scope_state;
            DROP TABLE mastodon_instance_states;
            PRAGMA user_version = 13;
            """
        )
        before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in preserved_tables
        }

    with ResearchStore(database) as store:
        after = {table: store.table_count(table) for table in preserved_tables}
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.table_count("mastodon_instance_states") == 0
        assert store.table_count("mastodon_scope_state") == 0
        assert store.table_count("mastodon_sightings") == 0

    assert before == after == {
        "research_scopes": 1,
        "queries": 1,
        "collection_runs": 1,
        "observations": 1,
        "raw_events": 1,
    }


class _FakeHttpResponse:
    def __init__(self, payload: list[dict]):
        self.payload = payload
        self.headers = {
            "Link": (
                '<https://observer.example/api/v1/timelines/tag/typography?'
                'max_id=PAGE_2&limit=1>; rel="next"'
            )
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _FakeHttpOpener:
    def __init__(self, payload: list[dict]):
        self.response = _FakeHttpResponse(payload)
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout: float):
        self.request = request
        self.timeout = timeout
        return self.response


def test_mastodon_api_client_injects_proxy_auth_and_parses_next_max_id():
    proxy_url = "http://127.0.0.1:8080"
    client = MastodonApiClient(
        access_tokens={"https://OBSERVER.example/": "fixture-token"},
        proxy_url=proxy_url,
        timeout_seconds=12.0,
    )
    assert any(
        getattr(handler, "proxies", {}).get("https") == proxy_url
        for handler in client.opener.handlers
    )
    opener = _FakeHttpOpener(
        [_fixture()["observer.example"]["typography"][0]]
    )
    client.opener = opener

    statuses, next_page_token = asyncio.run(client.request(
        "observer.example",
        "/api/v1/timelines/tag/typography",
        {"limit": 1},
    ))

    assert len(statuses) == 1
    assert next_page_token == "PAGE_2"
    assert opener.timeout == 12.0
    assert opener.request.full_url == (
        "https://observer.example/api/v1/timelines/tag/typography?limit=1"
    )
    assert opener.request.get_header("Authorization") == "Bearer fixture-token"


def test_web_creates_mastodon_scope_and_selects_mastodon_collector(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "glyph-social.sqlite3"
    collected: list[tuple[str, int]] = []

    async def finish_immediately(collector, collection_run_id, *, max_items):
        collected.append((collection_run_id, max_items))
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(MastodonCollector, "run", finish_immediately)
    app = create_app(database)
    with TestClient(app) as client:
        response = client.post("/api/scopes", json={
            "platform": "mastodon",
            "name": "Mastodon Web fixture",
            "object_type": "writing_system",
            "object_label": "latin",
            "keywords": ["typography"],
            "languages": ["en"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2027-09-03T00:00:00Z",
            "max_items": 5,
            "exact_query": "#typography",
            "mastodon_instances": ["observer.example", "second.example"],
            "mastodon_access_method": "hashtag_timeline",
            "mastodon_page_size": 20,
            "mastodon_max_pages_per_instance": 2,
            "mastodon_request_delay_seconds": 1.0,
        })
        assert response.status_code == 201
        scope = response.json()
        assert scope["platform_options"]["instances"] == [
            "observer.example", "second.example",
        ]
        started = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert started.status_code == 202
        assert started.json()["platform"] == "mastodon"
        for _ in range(20):
            if collected:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert collected == [(started.json()["collection_run_id"], 5)]


def test_web_schedule_routes_mastodon_and_records_trigger(tmp_path: Path, monkeypatch):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon scheduled fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2099-09-03T00:00:00Z",
        max_items=3,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
    )
    collected: list[str] = []

    async def finish_immediately(collector, collection_run_id, *, max_items):
        assert max_items == 3
        collected.append(collection_run_id)
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(MastodonCollector, "run", finish_immediately)
    app = create_app(database)
    with TestClient(app) as client:
        schedule_response = client.post("/api/schedules", json={
            "scope_id": scope["scope_id"],
            "interval_minutes": 60,
            "enabled": True,
        })
        assert schedule_response.status_code == 201
        schedule = schedule_response.json()
        started = client.post(f"/api/schedules/{schedule['schedule_id']}/run")
        assert started.status_code == 202
        for _ in range(20):
            if collected:
                break
            asyncio.run(asyncio.sleep(0.01))
        assert collected == [started.json()["collection_run_id"]]
        run = next(
            row for row in client.get("/api/runs").json()
            if row["collection_run_id"] == started.json()["collection_run_id"]
        )
        assert run["trigger"]["trigger_type"] == "scheduled"
        assert run["trigger"]["schedule_id"] == schedule["schedule_id"]


def test_mastodon_evidence_monitoring_and_export_preserve_instance_audit(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon audit fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=[
            "observer.example", "second.example", "failed.example",
        ],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=2,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    asyncio.run(MastodonCollector(
        service,
        client=_FakeMastodonClient(_fixture()),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))
    duplicate = next(
        row for row in service.observations()
        if row["platform_item_id"] == "status:origin.example:109876543210"
    )

    evidence = service.evidence(duplicate["observation_id"])
    assert {
        row["observed_instance"] for row in evidence["mastodon_sightings"]
    } == {"observer.example", "second.example"}
    assert all("payload" in row for row in evidence["mastodon_sightings"])

    monitoring = service.monitoring(tmp_path / "backups")
    assert "mastodon" in monitoring["platforms"]
    assert monitoring["mastodon"]["state_counts"] == {
        "completed": 2,
        "failed": 1,
    }
    assert monitoring["mastodon"]["sightings"] == 3

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    states = json.loads(
        (export_directory / "mastodon_instance_states.json").read_text(encoding="utf-8")
    )
    sightings = [
        json.loads(line)
        for line in (export_directory / "mastodon_sightings.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    with (export_directory / "queries.csv").open(encoding="utf-8") as handle:
        query = next(csv.DictReader(handle))
    assert len(states) == 3
    assert len(sightings) == 3
    assert all("payload" not in row for row in sightings)
    assert query["mastodon_instances"] == (
        "failed.example|observer.example|second.example"
    )
    assert query["mastodon_access_method"] == "hashtag_timeline"


def test_backup_restore_recovers_mastodon_instance_state_and_sightings(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon backup fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
        mastodon_page_size=1,
        mastodon_max_pages_per_instance=1,
        mastodon_request_delay_seconds=0,
    )
    run = service.start_run(scope["scope_id"])
    asyncio.run(MastodonCollector(
        service,
        client=_IncrementalMastodonClient(
            _fixture()["observer.example"]["typography"][0]
        ),
        max_retries=0,
    ).run(run["collection_run_id"], max_items=10))
    query_id = service.get_scope(scope["scope_id"])["queries"][0]["query_id"]
    backup = service.create_backup(backup_root, reason="mastodon_fixture")

    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            DELETE FROM mastodon_sightings;
            DELETE FROM mastodon_instance_states;
            DELETE FROM mastodon_scope_state;
            """
        )
    assert service.mastodon_sightings(run["collection_run_id"]) == []

    restored = service.restore_backup(backup_root, backup["backup_id"])

    assert restored["schema_version"] == SCHEMA_VERSION
    assert len(service.mastodon_sightings(run["collection_run_id"])) == 1
    assert service.mastodon_instance_states(run["collection_run_id"])[0][
        "status"
    ] == "completed"
    assert service.mastodon_scope_high_watermark(
        scope["scope_id"], query_id, "observer.example"
    ) == "700001"


def test_mastodon_candidate_reuses_screening_review_and_analysis_path(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="mastodon",
        name="Mastodon review fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query="#typography",
        mastodon_instances=["observer.example"],
    )
    run = service.start_run(scope["scope_id"])
    inserted, _ = service.process_mastodon_status(
        run["collection_run_id"],
        _fixture()["observer.example"]["typography"][0],
        observed_instance="observer.example",
        hashtag="typography",
    )
    assert inserted
    service.finish_run(run["collection_run_id"], "completed")
    candidate = service.screening_queue(run["collection_run_id"])[0]
    service.screen_observation(
        candidate["observation_id"],
        decision="include",
        reason="fixture 明确连接 typography 与 identity 评价语境。",
    )
    reviewed = service.review_observation(
        candidate["observation_id"],
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern"],
        evidence_span="Typography & identity",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )

    assert reviewed["annotation_status"] == "human_verified"
    assert validation_errors(reviewed, validator()) == []
    analysis = service.analysis()
    assert analysis["included_records"] == 1
    assert analysis["platform_summary"] == [
        {"platform": "mastodon", "record_count": 1}
    ]


def test_current_service_restores_and_migrates_v13_backup(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        name="Legacy backup fixture",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
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
            DROP TABLE api_scope_states;
            DROP TABLE api_collection_states;
            DROP TABLE mastodon_sightings;
            DROP TABLE mastodon_scope_state;
            DROP TABLE mastodon_instance_states;
            PRAGMA user_version = 13;
            """
        )
    legacy_backup = create_database_backup(
        database, backup_root, reason="pre_v14_fixture"
    )
    assert legacy_backup["schema_version"] == 13

    restored = service.restore_backup(backup_root, legacy_backup["backup_id"])

    assert restored["source_schema_version"] == 13
    assert restored["schema_version"] == SCHEMA_VERSION
    assert service.get_scope(scope["scope_id"])["name"] == "Legacy backup fixture"
    with ResearchStore(database) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
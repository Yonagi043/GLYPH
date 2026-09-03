from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from glyph_features.social_system import storage as social_storage
from glyph_features.social_system.bluesky import ResearchScope
from glyph_features.social_system.collector import YouTubeCollector
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.youtube import (
    YouTubeApiError,
    normalize_youtube_comment,
    normalize_youtube_video,
)
from tools.social_io import validation_errors, validator
from fastapi.testclient import TestClient
from glyph_features.social_system.web import create_app


FIXTURE = Path(__file__).parent / "fixtures" / "youtube_api_v3.json"


def test_scope_queries_preserve_registration_order_with_same_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        social_storage, "_utc_now", lambda: "2026-09-02T00:00:00Z"
    )
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    exact_queries = [
        '"Latin typography" premium',
        '"Latin typography" modern',
        '"Latin typeface" premium',
        '"Latin typeface" modern',
        '"Latin letterforms" premium',
        '"Latin letterforms" modern',
    ]
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 同秒查询顺序",
        object_type="writing_system",
        object_label="latin",
        keywords=["Latin typography", "Latin typeface", "Latin letterforms"],
        languages=["en"],
        window_start="2026-03-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        max_items=240,
        query_family="object_aesthetic",
        phase="calibration",
        exact_query=exact_queries[0],
        max_videos=20,
        max_comment_threads_per_video=0,
        max_replies_per_thread=0,
    )
    for exact_query in exact_queries[1:]:
        service.add_scope_query(
            scope["scope_id"],
            query_family="object_aesthetic",
            phase="calibration",
            exact_query=exact_query,
        )

    registered = service.get_scope(scope["scope_id"])["queries"]

    assert [query["exact_query"] for query in registered] == exact_queries
SCREENING_FIXTURE = Path(__file__).parent / "fixtures" / "youtube_screening_cases.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _screening_fixture() -> dict:
    return json.loads(SCREENING_FIXTURE.read_text(encoding="utf-8"))


def _scope() -> ResearchScope:
    return ResearchScope(
        query_id="q_youtube_typography_en",
        object_type="writing_system",
        object_label="latin",
        keywords=("typography", "wordmark"),
        languages=("en",),
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
    )


def test_youtube_scope_builds_api_pagination_manifest(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 字体叙事",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography", "wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )

    manifest = service.start_run(scope["scope_id"])

    assert scope["platform"] == "youtube"
    assert scope["scope_id"].startswith("scope_youtube_")
    assert manifest["platform"] == "youtube"
    assert manifest["collection_run_id"].startswith("social_run_youtube_")
    assert manifest["sampling"]["method"] == "api_pagination"
    assert manifest["collector"]["endpoint"] == "https://www.googleapis.com/youtube/v3"
    assert manifest["collector"]["api_version"] == "v3"


def test_query_update_preserves_old_run_snapshot(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 查询快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    first_run = service.start_run(scope["scope_id"])

    updated = service.update_scope(
        scope["scope_id"],
        platform="youtube",
        name="YouTube 查询快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        active=True,
    )
    second_run = service.start_run(scope["scope_id"])

    with ResearchStore(database) as store:
        first_export = store.export_data(first_run["collection_run_id"])
        second_export = store.export_data(second_run["collection_run_id"])

    assert updated["query_id"] != scope["query_id"]
    assert first_run["query_ids"] == [scope["query_id"]]
    assert second_run["query_ids"] == [updated["query_id"]]
    assert [query["query_text"] for query in first_export["queries"]] == ["typography"]
    assert [query["query_text"] for query in second_export["queries"]] == ["wordmark"]


def test_scope_run_freezes_multiple_queries_and_preserves_duplicate_matches(
    tmp_path: Path,
):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 多查询快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        query_family="object_aesthetic",
        phase="confirmatory",
        exact_query='"Latin" typography',
        max_comment_threads_per_video=0,
        max_replies_per_thread=0,
    )
    second_query = service.add_scope_query(
        scope["scope_id"],
        query_family="object_context",
        phase="confirmatory",
        exact_query='"Latin" "brand identity"',
    )
    registered = service.get_scope(scope["scope_id"])["queries"]
    assert [query["query_id"] for query in registered] == [
        scope["query_id"], second_query["query_id"]
    ]
    hydrated_scope = service.list_scopes()[0]
    assert hydrated_scope["query_family"] == "object_aesthetic"
    assert hydrated_scope["phase"] == "confirmatory"
    assert hydrated_scope["exact_query"] == '"Latin" typography'
    assert hydrated_scope["layer_quotas"]["max_videos"] == 10
    with TestClient(create_app(database)) as client:
        response = client.get(f"/api/scopes/{scope['scope_id']}/queries")
        assert response.status_code == 200
        assert [row["query_id"] for row in response.json()] == [
            scope["query_id"], second_query["query_id"]
        ]

    run = service.start_run(scope["scope_id"])
    assert run["query_ids"] == [scope["query_id"], second_query["query_id"]]
    assert [
        snapshot["exact_query"]
        for snapshot in service.run_scope_snapshots(run["collection_run_id"])
    ] == ['"Latin" typography', '"Latin" "brand identity"']

    video = json.loads(json.dumps(_fixture()["videos"]["items"][0]))
    assert service.process_youtube_resource(
        run["collection_run_id"],
        video,
        {"kind": "video", "matched_query": scope["query_id"]},
        query_id=scope["query_id"],
    )
    assert not service.process_youtube_resource(
        run["collection_run_id"],
        video,
        {"kind": "video", "matched_query": second_query["query_id"]},
        query_id=second_query["query_id"],
    )
    second_video = json.loads(json.dumps(video))
    second_video["id"] = "fixtureSecondQuery01"
    assert service.process_youtube_resource(
        run["collection_run_id"],
        second_video,
        {"kind": "video", "matched_query": second_query["query_id"]},
        query_id=second_query["query_id"],
    )

    with ResearchStore(database) as store:
        exported = store.export_data(run["collection_run_id"])
    assert len(exported["observations"]) == 2
    assert {
        row["platform_item_id"]: row["query_text"]
        for row in exported["observations"]
    } == {
        f"video:{video['id']}": '"Latin" typography',
        "video:fixtureSecondQuery01": '"Latin" "brand identity"',
    }
    assert [query["query_id"] for query in exported["queries"]] == run["query_ids"]
    assert {
        match["query_id"] for match in exported["observation_query_matches"]
    } == set(run["query_ids"])
    service.finish_run(run["collection_run_id"], "completed")
    package = service.export_run(run["collection_run_id"], tmp_path / "exports")
    matches = [
        json.loads(line)
        for line in (
            Path(package["directory"]) / "observation_query_matches.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert {match["query_id"] for match in matches} == set(run["query_ids"])


def test_old_run_normalization_uses_its_query_snapshot_after_scope_update(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 运行中查询快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query='"Latin typography" premium',
    )
    run = service.start_run(scope["scope_id"])
    service.update_scope(
        scope["scope_id"],
        platform="youtube",
        name="YouTube 运行中查询快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        active=True,
    )
    video = _fixture()["videos"]["items"][0]

    assert service.process_youtube_resource(
        run["collection_run_id"], video, {"kind": "video", "video": video}
    )

    record = service.observations()[0]
    assert record["query_id"] == scope["query_id"]
    assert record["query_text"] == '"Latin typography" premium'


def test_ingest_rejects_query_text_that_differs_from_run_snapshot(
    tmp_path: Path, monkeypatch,
):
    from glyph_features.social_system import service as service_module

    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube query provenance guard",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
        exact_query='"Latin typography" premium',
    )
    run = service.start_run(scope["scope_id"])
    original_normalizer = service_module.normalize_youtube_video

    def mismatched_normalizer(*args, **kwargs):
        record = original_normalizer(*args, **kwargs)
        record["query_text"] = "typography"
        return record

    monkeypatch.setattr(
        service_module, "normalize_youtube_video", mismatched_normalizer
    )

    with pytest.raises(ValueError, match="运行冻结 query 不一致"):
        service.process_youtube_resource(
            run["collection_run_id"],
            _fixture()["videos"]["items"][0],
            {"kind": "video"},
        )

    assert service.observations() == []


def test_engineering_only_run_is_auditable_but_cannot_enter_analysis(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 工程审计样本",
        object_type="writing_system",
        object_label="latin",
        keywords=["logo design"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(scope["scope_id"])
    video = _fixture()["videos"]["items"][0]
    service.process_youtube_resource(
        run["collection_run_id"], video, {"kind": "video", "video": video}
    )
    observation = service.observations()[0]

    governance = service.set_run_governance(
        run["collection_run_id"],
        usage_classification="engineering_only",
        reason="查询偏离研究对象—评价核心，仅保留工程审计。",
    )

    assert governance["analysis_allowed"] is False
    assert governance["release_allowed"] is False
    assert service.review_queue() == []
    with pytest.raises(ValueError, match="engineering-only"):
        service.review_observation(
            observation["observation_id"],
            status="human_verified",
            object_type="writing_system",
            object_label="latin",
            aesthetic_terms=["precise"],
            evidence_span="Typography",
            stance="descriptive",
            confidence=0.9,
            exclusion_reason=None,
        )
    assert service.analysis()["included_records"] == 0

    service.finish_run(run["collection_run_id"], "completed")
    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    exported_governance = json.loads(
        (export_directory / "run_governance.json").read_text(encoding="utf-8")
    )
    assert exported_governance["usage_classification"] == "engineering_only"
    assert (export_directory / "observations.jsonl").read_text(encoding="utf-8").strip()
    assert not (export_directory / "narratives.jsonl").read_text(encoding="utf-8").strip()
    assert service.evidence(observation["observation_id"])["run_governance"] == governance


def test_run_registry_snapshot_rejects_unregistered_gold_codes(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube registry 契约",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(scope["scope_id"])
    video = json.loads(json.dumps(_fixture()["videos"]["items"][0]))
    video["snippet"]["description"] = "Latin typography feels premium."
    service.process_youtube_resource(
        run["collection_run_id"], video, {"kind": "video", "video": video}
    )
    observation = service.observations()[0]
    service.screen_observation(
        observation["observation_id"],
        decision="include",
        reason="fixture 明确包含对象—评价关系。",
    )

    with ResearchStore(database) as store:
        exported = store.export_data(run["collection_run_id"])
    query = exported["queries"][0]
    registry = exported["run_registry"]
    assert len(query["object_map_sha256"]) == 64
    assert len(query["codebook_sha256"]) == 64
    assert query["codebook_version"] == "0.1.0"
    assert registry["binding_status"] == "bound"
    assert registry["object_map_sha256"] == query["object_map_sha256"]
    assert registry["codebook_sha256"] == query["codebook_sha256"]

    review = {
        "status": "human_verified",
        "object_type": "writing_system",
        "object_label": "latin",
        "aesthetic_terms": ["precise"],
        "evidence_span": "Latin typography feels premium",
        "stance": "descriptive",
        "confidence": 0.9,
        "exclusion_reason": None,
    }
    with pytest.raises(ValueError, match="未登记"):
        service.review_observation(observation["observation_id"], **review)
    with pytest.raises(ValueError, match="未登记"):
        service.review_observation(
            observation["observation_id"],
            **{**review, "object_label": "logo_design", "aesthetic_terms": ["premium"]},
        )

    verified = service.review_observation(
        observation["observation_id"],
        **{**review, "aesthetic_terms": ["premium"]},
    )
    assert verified["object_label"] == "latin"
    assert verified["aesthetic_terms"] == ["premium"]


def test_youtube_screening_fixture_separates_relevant_counterexamples(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 筛选语义夹具",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
    )
    run = service.start_run(scope["scope_id"])
    fixture = _screening_fixture()
    expected_by_item = {}
    for case in fixture["cases"]:
        resource = case["resource"]
        kind = case["kind"]
        assert service.process_youtube_resource(
            run["collection_run_id"],
            resource,
            {"kind": kind, "fixture_case_id": case["case_id"], "resource": resource},
            video_id=case.get("video_id"),
            parent_comment_id=case.get("parent_comment_id"),
        )
        item_prefix = "video" if kind == "video" else "comment"
        expected_by_item[f"{item_prefix}:{resource['id']}"] = case

    observations = service.observations()
    for observation in observations:
        case = expected_by_item[observation["platform_item_id"]]
        service.screen_observation(
            observation["observation_id"],
            decision=case["expected_decision"],
            reason=case["reason"],
        )

    latest_decisions = {
        observation["platform_item_id"]: service.latest_screening(
            observation["observation_id"]
        )["decision"]
        for observation in observations
    }
    assert latest_decisions == {
        item_id: case["expected_decision"] for item_id, case in expected_by_item.items()
    }
    assert {row["platform_item_id"] for row in service.review_queue()} == {
        "video:fixturePositive01",
        "comment:fixtureNegative01",
        "comment:fixtureReply01",
    }
    assert {row["platform_item_id"] for row in service.screening_queue()} == {
        "comment:fixtureMixed01"
    }
    reply = next(
        row for row in observations if row["platform_item_id"] == "comment:fixtureReply01"
    )
    assert reply["references"] == [{
        "relation": "reply",
        "target_item_id": "comment:fixtureNegative01",
        "target_url": "https://www.youtube.com/watch?lc=fixtureNegative01&v=fixturePositive01",
    }]


def test_screening_events_gate_the_human_coding_queue(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 独立筛选",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(scope["scope_id"])
    video = json.loads(json.dumps(_fixture()["videos"]["items"][0]))
    video["snippet"]["description"] = "Latin typography feels premium."
    service.process_youtube_resource(
        run["collection_run_id"], video, {"kind": "video", "video": video}
    )
    observation = service.observations()[0]

    assert service.review_queue() == []
    assert [row["observation_id"] for row in service.screening_queue()] == [
        observation["observation_id"]
    ]
    machine_event = service.screening_history(observation["observation_id"])[0]
    assert machine_event["decision"] == "uncertain"
    assert machine_event["decided_by"] == "machine"
    assert machine_event["rule_version"] == "social_screening_v0.1.0"
    assert machine_event["signals"]["query_id"] == scope["query_id"]

    with pytest.raises(ValueError, match="相关性筛选"):
        service.review_observation(
            observation["observation_id"],
            status="human_verified",
            object_type="writing_system",
            object_label="latin",
            aesthetic_terms=["premium"],
            evidence_span="Latin typography feels premium",
            stance="descriptive",
            confidence=0.9,
            exclusion_reason=None,
        )

    included = service.screen_observation(
        observation["observation_id"],
        decision="include",
        reason="原文明确连接 latin typography 与 premium。",
    )
    assert included["decision"] == "include"
    assert included["decided_by"] == "annotator_local01"
    assert [row["observation_id"] for row in service.review_queue()] == [
        observation["observation_id"]
    ]
    history = service.screening_history(observation["observation_id"])
    assert [event["decision"] for event in history] == ["include", "uncertain"]


def test_youtube_v3_video_and_comments_normalize_to_frozen_schema():
    payload = _fixture()
    video = payload["videos"]["items"][0]
    channel = payload["channels"]["items"][0]
    thread = payload["commentThreads"]["items"][0]
    top_level = thread["snippet"]["topLevelComment"]
    reply = thread["replies"]["comments"][0]
    common = {
        "scope": _scope(),
        "collection_run_id": "social_run_youtube_test",
        "normalized_at": "2026-09-02T10:00:00Z",
    }

    video_record = normalize_youtube_video(video, channel=channel, **common)
    top_record = normalize_youtube_comment(
        top_level,
        video_id=video["id"],
        reply_count=thread["snippet"]["totalReplyCount"],
        **common,
    )
    reply_record = normalize_youtube_comment(
        reply,
        video_id=video["id"],
        parent_comment_id=top_level["id"],
        **common,
    )

    assert video_record["platform_item_id"] == "video:vidTypography01"
    assert video_record["url"] == "https://www.youtube.com/watch?v=vidTypography01"
    assert video_record["engagement"]["view_count"] == 1200
    assert video_record["engagement"]["comment_count"] == 2
    assert top_record["platform_item_id"] == "comment:commentTop01"
    assert top_record["engagement"]["comment_count"] == 2
    assert top_record["references"] == [{
        "relation": "parent",
        "target_item_id": "video:vidTypography01",
        "target_url": "https://www.youtube.com/watch?v=vidTypography01",
    }]
    assert reply_record["references"] == [{
        "relation": "reply",
        "target_item_id": "comment:commentTop01",
        "target_url": "https://www.youtube.com/watch?lc=commentTop01&v=vidTypography01",
    }]
    assert all(
        record["object_type"] is None and record["object_label"] is None
        for record in (video_record, top_record, reply_record)
    )
    assert "UCCommenterRedacted" not in json.dumps(top_record)
    assert validation_errors(video_record, validator()) == []
    assert validation_errors(top_record, validator()) == []
    assert validation_errors(reply_record, validator()) == []


def test_youtube_quota_budget_and_checkpoint_survive_restart(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 配额恢复",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(scope["scope_id"])
    now = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)

    service.set_youtube_quota_budgets(shared_unit_budget=1, search_call_budget=1)
    service.consume_youtube_quota(run["collection_run_id"], "search.list", now=now)
    with pytest.raises(ValueError, match="搜索调用配额"):
        service.consume_youtube_quota(run["collection_run_id"], "search.list", now=now)
    service.consume_youtube_quota(run["collection_run_id"], "videos.list", now=now)
    with pytest.raises(ValueError, match="共享单位配额"):
        service.consume_youtube_quota(run["collection_run_id"], "comments.list", now=now)
    service.save_youtube_run_state(run["collection_run_id"], {
        "language_index": 0,
        "search_page_token": "SEARCH_PAGE_2",
    })

    reopened = SocialNarrativeService(database)
    quota = reopened.youtube_quota_status(now=now)
    assert quota["policy_version"] == "youtube_data_api_2026-06-01"
    assert quota["daily_budget"] == 1
    assert quota["used_units"] == 1
    assert quota["remaining_units"] == 0
    assert quota["search_daily_call_budget"] == 1
    assert quota["used_search_calls"] == 1
    assert quota["remaining_search_calls"] == 0
    assert quota["usage_by_operation"] == {
        "search.list": 1,
        "videos.list": 1,
    }
    assert reopened.get_run(run["collection_run_id"])["quota_policy"]["policy_version"] == (
        "youtube_data_api_2026-06-01"
    )
    assert reopened.youtube_run_state(run["collection_run_id"]) == {
        "language_index": 0,
        "search_page_token": "SEARCH_PAGE_2",
    }


def test_youtube_run_quota_snapshot_cannot_be_relaxed_after_start(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    service.set_youtube_quota_budgets(
        shared_unit_budget=100,
        search_call_budget=100,
    )
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 冻结运行配额",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=10,
    )
    run = service.start_run(
        scope["scope_id"],
        youtube_run_search_call_budget=1,
        youtube_run_shared_unit_budget=2,
    )
    now = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    assert service.get_run(run["collection_run_id"])["quota_policy"] == {
        "collection_run_id": run["collection_run_id"],
        "policy_version": "youtube_data_api_2026-06-01",
        "search_call_budget": 1,
        "shared_unit_budget": 2,
        "reset_timezone": "America/Los_Angeles",
        "captured_at": service.get_run(run["collection_run_id"])["quota_policy"][
            "captured_at"
        ],
    }

    service.consume_youtube_quota(run["collection_run_id"], "search.list", now=now)
    with pytest.raises(ValueError, match="运行冻结搜索配额"):
        service.consume_youtube_quota(
            run["collection_run_id"], "search.list", now=now
        )
    service.consume_youtube_quota(run["collection_run_id"], "videos.list", now=now)
    service.consume_youtube_quota(run["collection_run_id"], "channels.list", now=now)
    with pytest.raises(ValueError, match="运行冻结共享配额"):
        service.consume_youtube_quota(
            run["collection_run_id"], "comments.list", now=now
        )


def test_schema_v10_preserves_legacy_youtube_quota_events(tmp_path: Path):
    database = tmp_path / "legacy-v9.sqlite3"
    quota_date = "2026-09-02"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE collection_runs (
                collection_run_id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                started_at TEXT NOT NULL
            );
            CREATE TABLE youtube_quota_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                daily_budget INTEGER NOT NULL CHECK(daily_budget > 0),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE youtube_quota_events (
                quota_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_run_id TEXT NOT NULL REFERENCES collection_runs(collection_run_id),
                operation TEXT NOT NULL,
                units INTEGER NOT NULL CHECK(units > 0),
                quota_date TEXT NOT NULL,
                outcome TEXT NOT NULL DEFAULT 'attempted',
                created_at TEXT NOT NULL
            );
            INSERT INTO collection_runs VALUES (
                'social_run_youtube_legacy', 'youtube', '2026-09-02T00:00:00Z'
            );
            INSERT INTO youtube_quota_settings VALUES (1, 300, '2026-09-02T00:00:00Z');
            INSERT INTO youtube_quota_events(
                collection_run_id, operation, units, quota_date, outcome, created_at
            ) VALUES (
                'social_run_youtube_legacy', 'search.list', 100,
                '2026-09-02', 'success', '2026-09-02T00:00:01Z'
            );
            PRAGMA user_version = 9;
            """
        )

    with ResearchStore(database) as store:
        assert store.get_run_quota_policy("social_run_youtube_legacy") == {
            "collection_run_id": "social_run_youtube_legacy",
            "policy_version": "legacy_pre_2026-06-01",
            "search_call_budget": None,
            "shared_unit_budget": 300,
            "reset_timezone": "America/Los_Angeles",
            "captured_at": "2026-09-02T00:00:00Z",
        }
        event = dict(store.connection.execute(
            "SELECT operation, units, quota_policy_version, quota_bucket "
            "FROM youtube_quota_events"
        ).fetchone())
        assert event == {
            "operation": "search.list",
            "units": 100,
            "quota_policy_version": "legacy_pre_2026-06-01",
            "quota_bucket": "legacy_shared_units",
        }


def test_youtube_item_is_idempotent_within_run_but_recaptured_across_runs(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 跨运行快照",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
    )
    first_run = service.start_run(scope["scope_id"])
    second_run = service.start_run(scope["scope_id"])
    video = _fixture()["videos"]["items"][0]
    raw_event = {"kind": "video", "video": video, "channel": None}

    assert service.process_youtube_resource(
        first_run["collection_run_id"], video, raw_event
    )
    assert not service.process_youtube_resource(
        first_run["collection_run_id"], video, raw_event
    )
    assert service.process_youtube_resource(
        second_run["collection_run_id"], video, raw_event
    )
    observations = service.observations()
    assert len(observations) == 2
    assert len({row["observation_id"] for row in observations}) == 2


class _FakeYouTubeClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    async def request(self, resource: str, parameters: dict) -> dict:
        self.calls.append((resource, parameters))
        return self.payload[resource]


class _LayeredQuotaYouTubeClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def request(self, resource: str, parameters: dict) -> dict:
        self.calls.append((resource, parameters))
        if resource == "search":
            return {
                "items": [
                    {"id": {"videoId": video_id}, "snippet": {"publishedAt": "2026-09-02T08:00:00Z"}}
                    for video_id in ("videoLayerA", "videoLayerB", "videoLayerC")
                ]
            }
        if resource == "videos":
            return {
                "items": [
                    {
                        "id": video_id,
                        "snippet": {
                            "publishedAt": "2026-09-02T08:00:00Z",
                            "title": f"Latin typography {video_id}",
                            "description": "Latin typography feels premium.",
                            "defaultLanguage": "en",
                        },
                        "statistics": {"commentCount": "1"},
                    }
                    for video_id in parameters["id"].split(",")
                ]
            }
        if resource == "commentThreads":
            video_id = parameters["videoId"]
            return {
                "items": [
                    {
                        "id": f"thread-{video_id}-{thread_index}",
                        "snippet": {
                            "videoId": video_id,
                            "totalReplyCount": 2,
                            "topLevelComment": {
                                "id": f"top-{video_id}-{thread_index}",
                                "snippet": {
                                    "videoId": video_id,
                                    "textOriginal": "Latin typography feels premium.",
                                    "publishedAt": "2026-09-02T09:00:00Z",
                                },
                            },
                        },
                        "replies": {"comments": [
                            {
                                "id": f"reply-{video_id}-{thread_index}-{reply_index}",
                                "snippet": {
                                    "parentId": f"top-{video_id}-{thread_index}",
                                    "videoId": video_id,
                                    "textOriginal": "I agree about the premium typography.",
                                    "publishedAt": "2026-09-02T09:05:00Z",
                                },
                            }
                            for reply_index in range(2)
                        ]},
                    }
                    for thread_index in range(2)
                ],
            }
        raise AssertionError(resource)


class _MultiQueryYouTubeClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def request(self, resource: str, parameters: dict) -> dict:
        self.calls.append((resource, parameters))
        if resource == "search":
            video_id = (
                "videoTypographyQuery"
                if parameters["q"] == '"Latin" typography'
                else "videoBrandQuery"
            )
            return {"items": [{
                "id": {"videoId": video_id},
                "snippet": {"publishedAt": "2026-09-02T08:00:00Z"},
            }]}
        if resource == "videos":
            return {"items": [{
                "id": video_id,
                "snippet": {
                    "publishedAt": "2026-09-02T08:00:00Z",
                    "title": f"Latin identity {video_id}",
                    "description": "Latin typography feels premium.",
                    "defaultLanguage": "en",
                },
                "statistics": {"commentCount": "0"},
            } for video_id in parameters["id"].split(",")]}
        raise AssertionError(resource)


def test_youtube_layered_quotas_cover_multiple_videos_and_report_denominators(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 分层配额",
        object_type="writing_system",
        object_label="latin",
        keywords=["latin", "typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
        query_family="object_aesthetic",
        phase="exploratory",
        exact_query='"Latin" typography',
        max_videos=2,
        max_comment_threads_per_video=1,
        max_replies_per_thread=1,
    )
    run = service.start_run(scope["scope_id"])
    client = _LayeredQuotaYouTubeClient()

    collector = YouTubeCollector(service, client=client)
    discovery = asyncio.run(collector.run(
        run["collection_run_id"], max_items=2
    ))

    assert discovery == {"status": "awaiting_screening", "inserted": 2}
    assert not any(resource == "commentThreads" for resource, _ in client.calls)
    candidates = service.screening_queue()
    service.screen_observation(
        candidates[0]["observation_id"],
        decision="include",
        reason="fixture 视频标题和描述明确讨论 Latin typography。",
    )
    unresolved = asyncio.run(collector.run(run["collection_run_id"], max_items=2))
    assert unresolved == {"status": "awaiting_screening", "inserted": 0}
    assert not any(resource == "commentThreads" for resource, _ in client.calls)
    service.screen_observation(
        candidates[1]["observation_id"],
        decision="include",
        reason="fixture 视频标题和描述明确讨论 Latin typography。",
    )

    comments = asyncio.run(collector.run(run["collection_run_id"], max_items=2))

    assert comments == {"status": "completed", "inserted": 2}
    comment_video_ids = [
        parameters["videoId"]
        for resource, parameters in client.calls
        if resource == "commentThreads"
    ]
    assert comment_video_ids == ["videoLayerA", "videoLayerB"]
    state = service.youtube_run_state(run["collection_run_id"])
    assert state["metrics"] == {
        "search_results": 3,
        "video_details": 2,
        "video_candidates": 2,
        "videos_inserted": 2,
        "videos_screening_included": 2,
        "videos_screening_excluded": 0,
        "comment_threads_seen": 2,
        "top_comments_inserted": 2,
        "replies_seen": 0,
        "replies_inserted": 0,
    }
    with ResearchStore(service.database_path) as store:
        query = store.export_data(run["collection_run_id"])["queries"][0]
    assert query["query_family"] == "object_aesthetic"
    assert query["phase"] == "exploratory"
    assert query["exact_query"] == '"Latin" typography'
    assert query["layer_quotas"] == {
        "max_videos": 2,
        "max_comment_threads_per_video": 1,
        "max_replies_per_thread": 1,
    }


def test_youtube_comment_budget_must_cover_video_candidate_capacity(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 评论容量阻断",
        object_type="writing_system",
        object_label="latin",
        keywords=["latin", "typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
        query_family="object_aesthetic",
        phase="exploratory",
        exact_query='"Latin" typography',
        max_videos=2,
        max_comment_threads_per_video=1,
        max_replies_per_thread=0,
    )

    with pytest.raises(ValueError, match="不得低于全部 query 的视频候选上限"):
        service.start_run(scope["scope_id"])


def test_youtube_collector_executes_all_frozen_scope_queries(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 多查询执行",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
        query_family="object_aesthetic",
        phase="confirmatory",
        exact_query='"Latin" typography',
        max_videos=1,
        max_comment_threads_per_video=0,
        max_replies_per_thread=0,
    )
    second = service.add_scope_query(
        scope["scope_id"],
        query_family="object_context",
        phase="confirmatory",
        exact_query='"Latin" "brand identity"',
    )
    run = service.start_run(scope["scope_id"])
    client = _MultiQueryYouTubeClient()

    result = asyncio.run(
        YouTubeCollector(service, client=client).run(
            run["collection_run_id"], max_items=1
        )
    )

    assert result == {"status": "completed", "inserted": 2}
    assert [
        parameters["q"] for resource, parameters in client.calls
        if resource == "search"
    ] == ['"Latin" typography', '"Latin" "brand identity"']
    assert [resource for resource, _ in client.calls] == [
        "search", "videos", "search", "videos"
    ]
    assert len(service.observations()) == 2
    state = service.youtube_run_state(run["collection_run_id"])
    assert state["query_index"] == 2
    assert state["query_metrics"] == {
        scope["query_id"]: {"video_candidates": 1},
        second["query_id"]: {"video_candidates": 1},
    }


def test_overlapping_queries_collect_comments_once_and_keep_all_matches(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 重叠查询",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=4,
        query_family="object_aesthetic",
        phase="confirmatory",
        exact_query='"Latin" typography',
        max_videos=1,
    )
    second = service.add_scope_query(
        scope["scope_id"],
        query_family="object_context",
        phase="confirmatory",
        exact_query='"Latin" "brand identity"',
    )
    run = service.start_run(scope["scope_id"])
    client = _FakeYouTubeClient(_fixture())
    collector = YouTubeCollector(service, client=client)

    discovery = asyncio.run(collector.run(run["collection_run_id"], max_items=4))
    assert discovery == {"status": "awaiting_screening", "inserted": 1}
    video = service.screening_queue()[0]
    service.screen_observation(
        video["observation_id"],
        decision="include",
        reason="两条 query 均命中同一 fixture 视频。",
    )
    comments = asyncio.run(collector.run(run["collection_run_id"], max_items=4))

    assert comments == {"status": "completed", "inserted": 3}
    assert sum(resource == "commentThreads" for resource, _ in client.calls) == 1
    matches = service.observation_query_matches(run["collection_run_id"])
    query_ids_by_observation: dict[str, set[str]] = {}
    for match in matches:
        query_ids_by_observation.setdefault(match["observation_id"], set()).add(
            match["query_id"]
        )
    assert len(query_ids_by_observation) == 4
    assert all(
        query_ids == {scope["query_id"], second["query_id"]}
        for query_ids in query_ids_by_observation.values()
    )


def test_youtube_collector_runs_offline_fixture_end_to_end(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    service.set_youtube_daily_quota_budget(500)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 离线闭环",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography", "wordmark"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=4,
        max_videos=1,
    )
    run = service.start_run(scope["scope_id"])
    client = _FakeYouTubeClient(_fixture())
    collector = YouTubeCollector(service, client=client)

    discovery = asyncio.run(collector.run(run["collection_run_id"], max_items=4))

    assert discovery == {"status": "awaiting_screening", "inserted": 1}
    assert [resource for resource, _ in client.calls] == ["search", "videos", "channels"]
    video_candidate = service.screening_queue()[0]
    service.screen_observation(
        video_candidate["observation_id"],
        decision="include",
        reason="fixture 视频明确讨论 typography 和 wordmark。",
    )

    result = asyncio.run(collector.run(run["collection_run_id"], max_items=4))

    assert result == {"status": "completed", "inserted": 3}
    assert [resource for resource, _ in client.calls] == [
        "search", "videos", "channels", "commentThreads", "comments",
    ]
    assert client.calls[0][1]["publishedAfter"] == scope["window_start"]
    assert client.calls[0][1]["publishedBefore"] == scope["window_end"]
    assert client.calls[0][1]["relevanceLanguage"] == "en"
    quota_status = service.youtube_quota_status()
    assert quota_status["used_search_calls"] == 1
    assert quota_status["used_units"] == 4
    observations = service.observations()
    assert {row["platform_item_id"] for row in observations} == {
        "video:vidTypography01",
        "comment:commentTop01",
        "comment:commentReply01",
        "comment:commentReply02",
    }
    evidence = service.evidence(
        next(row["observation_id"] for row in observations if row["platform_item_id"].startswith("video:"))
    )
    assert evidence["raw_event"]["video"]["statistics"]["viewCount"] == "1200"
    assert evidence["raw_event"]["channel"]["id"] == "UCResearchExample"
    assert service.youtube_published_after(scope["scope_id"]) is None
    top_comment = next(
        row for row in observations if row["platform_item_id"] == "comment:commentTop01"
    )
    service.screen_observation(
        top_comment["observation_id"],
        decision="include",
        reason="fixture 评论明确连接 wordmark typography 与 premium。",
    )
    service.review_observation(
        top_comment["observation_id"],
        status="human_verified",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["premium"],
        evidence_span="wordmark typography feels premium",
        stance="descriptive",
        confidence=0.9,
        exclusion_reason=None,
    )
    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_directory = Path(exported["directory"])
    assert exported["valid"] is True
    assert exported["narrative_count"] == 1
    quota_usage = json.loads(
        (export_directory / "youtube_quota_usage.json").read_text(encoding="utf-8")
    )
    assert sum(event["units"] for event in quota_usage) == 5
    assert {event["quota_policy_version"] for event in quota_usage} == {
        "youtube_data_api_2026-06-01"
    }
    assert {event["quota_bucket"] for event in quota_usage} == {
        "search_calls", "shared_units"
    }
    assert {event["operation"] for event in quota_usage} == {
        "search.list",
        "videos.list",
        "channels.list",
        "commentThreads.list",
        "comments.list",
    }


def test_youtube_collector_requires_local_key_before_network(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    with pytest.raises(ValueError, match="GLYPH_YOUTUBE_API_KEY"):
        YouTubeCollector(service, api_key="")


class _RetryingYouTubeClient:
    def __init__(self):
        self.attempts = 0

    async def request(self, resource: str, parameters: dict) -> dict:
        self.attempts += 1
        if self.attempts == 1:
            raise YouTubeApiError(
                "temporary backend error",
                status_code=503,
                reason="backendError",
                retryable=True,
            )
        return {"items": []}


def test_youtube_retry_is_bounded_and_each_attempt_consumes_quota(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    service.set_youtube_daily_quota_budget(500)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 重试记账",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
    )
    run = service.start_run(scope["scope_id"])

    async def no_sleep(delay: float):
        return None

    client = _RetryingYouTubeClient()
    collector = YouTubeCollector(service, client=client, sleep=no_sleep)
    result = asyncio.run(collector.run(run["collection_run_id"], max_items=1))

    assert result == {"status": "completed", "inserted": 0}
    assert client.attempts == 2
    quota = service.youtube_quota_status()
    assert quota["used_search_calls"] == 2
    assert quota["used_units"] == 0
    errors = service.errors(run["collection_run_id"])
    assert errors[0]["error_code"] == "youtube_api_503"
    assert errors[0]["retryable"] is True


class _QuotaExceededClient:
    def __init__(self):
        self.attempts = 0

    async def request(self, resource: str, parameters: dict) -> dict:
        self.attempts += 1
        raise YouTubeApiError(
            "daily quota exceeded",
            status_code=403,
            reason="quotaExceeded",
            retryable=False,
        )


def test_youtube_quota_exceeded_is_not_retried(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 云端配额耗尽",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
    )
    run = service.start_run(scope["scope_id"])
    client = _QuotaExceededClient()

    with pytest.raises(YouTubeApiError, match="quota exceeded"):
        asyncio.run(YouTubeCollector(service, client=client).run(
            run["collection_run_id"], max_items=1
        ))

    assert client.attempts == 1
    quota = service.youtube_quota_status()
    assert quota["used_search_calls"] == 1
    assert quota["used_units"] == 0
    error = service.errors(run["collection_run_id"])[0]
    assert error["error_code"] == "youtube_api_403"
    assert error["retryable"] is False


def test_youtube_budget_guard_blocks_network_and_records_failure(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    service.set_youtube_quota_budgets(shared_unit_budget=50, search_call_budget=1)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 预算阻断",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=1,
    )
    run = service.start_run(scope["scope_id"])
    service.consume_youtube_quota(run["collection_run_id"], "search.list")
    client = _FakeYouTubeClient(_fixture())

    with pytest.raises(ValueError, match="YouTube 搜索调用配额"):
        asyncio.run(YouTubeCollector(service, client=client).run(
            run["collection_run_id"], max_items=1
        ))

    assert client.calls == []
    assert service.get_run(run["collection_run_id"])["status"] == "failed"
    errors = service.errors(run["collection_run_id"])
    assert errors[0]["error_code"] == "youtube_quota_budget"
    assert errors[0]["retryable"] is False


class _CommentsDisabledClient(_FakeYouTubeClient):
    async def request(self, resource: str, parameters: dict) -> dict:
        self.calls.append((resource, parameters))
        if resource == "commentThreads":
            raise YouTubeApiError(
                "comments disabled",
                status_code=403,
                reason="commentsDisabled",
                retryable=False,
            )
        payload = json.loads(json.dumps(self.payload[resource]))
        if resource == "search":
            payload.pop("nextPageToken", None)
        return payload


def test_youtube_comments_disabled_is_recorded_without_failing_video_run(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 关闭评论",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
    )
    run = service.start_run(scope["scope_id"])
    client = _CommentsDisabledClient(_fixture())

    collector = YouTubeCollector(service, client=client)
    discovery = asyncio.run(collector.run(
        run["collection_run_id"], max_items=2
    ))
    assert discovery == {"status": "awaiting_screening", "inserted": 1}
    video_candidate = service.screening_queue()[0]
    service.screen_observation(
        video_candidate["observation_id"],
        decision="include",
        reason="fixture 视频明确讨论 typography。",
    )

    result = asyncio.run(collector.run(run["collection_run_id"], max_items=2))

    assert result == {"status": "completed", "inserted": 0}
    assert service.get_run(run["collection_run_id"])["status"] == "completed"
    errors = service.errors(run["collection_run_id"])
    assert errors[0]["error_code"] == "youtube_api_403"
    assert errors[0]["retryable"] is False


def test_backup_restore_recovers_youtube_quota_and_checkpoint(tmp_path: Path):
    database = tmp_path / "glyph-social.sqlite3"
    backup_root = tmp_path / "backups"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 备份恢复",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=2,
    )
    run = service.start_run(scope["scope_id"])
    service.set_youtube_daily_quota_budget(150)
    service.consume_youtube_quota(run["collection_run_id"], "search.list")
    service.save_youtube_run_state(run["collection_run_id"], {
        "language_index": 0,
        "search_page_token": "BACKED_UP_PAGE",
    })
    service.finish_run(run["collection_run_id"], "stopped")
    backup = service.create_backup(backup_root)

    service.set_youtube_daily_quota_budget(999)
    service.save_youtube_run_state(run["collection_run_id"], {
        "language_index": 1,
        "search_page_token": None,
    })
    restored = service.restore_backup(backup_root, backup["backup_id"])

    assert restored["schema_version"] == SCHEMA_VERSION
    assert service.youtube_quota_status()["daily_budget"] == 150
    assert service.youtube_quota_status()["used_search_calls"] == 1
    assert service.youtube_quota_status()["used_units"] == 0
    assert service.youtube_run_state(run["collection_run_id"]) == {
        "language_index": 0,
        "search_page_token": "BACKED_UP_PAGE",
    }


def test_web_selects_youtube_collector_and_exposes_quota(tmp_path: Path, monkeypatch):
    database = tmp_path / "glyph-social.sqlite3"

    async def finish_immediately(collector, collection_run_id, *, max_items):
        collector.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": 0}

    monkeypatch.setattr(YouTubeCollector, "run", finish_immediately)
    app = create_app(database, youtube_api_key="local-test-key")
    with TestClient(app) as client:
        scope_response = client.post("/api/scopes", json={
            "platform": "youtube",
            "name": "YouTube Web 调度",
            "object_type": "writing_system",
            "object_label": "latin",
            "keywords": ["typography"],
            "languages": ["en"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2027-09-03T00:00:00Z",
            "max_items": 5,
        })
        assert scope_response.status_code == 201
        scope = scope_response.json()
        started = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert started.status_code == 202
        assert started.json()["platform"] == "youtube"
        updated = client.put("/api/youtube/quota", json={
            "daily_budget": 750,
            "search_daily_call_budget": 75,
        })
        assert updated.status_code == 200
        assert updated.json()["daily_budget"] == 750
        assert updated.json()["search_daily_call_budget"] == 75
        assert client.get("/api/monitoring").json()["youtube_quota"]["daily_budget"] == 750


def test_web_continues_same_youtube_run_after_video_screening(tmp_path: Path, monkeypatch):
    database = tmp_path / "glyph-social.sqlite3"
    service = SocialNarrativeService(database)
    scope = service.create_scope(
        platform="youtube",
        name="YouTube 筛选后续跑",
        object_type="writing_system",
        object_label="latin",
        keywords=["typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=5,
    )
    run = service.start_run(scope["scope_id"])
    service.finish_run(run["collection_run_id"], "awaiting_screening")

    async def keep_resumed_run_active(collector, collection_run_id, *, max_items):
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(YouTubeCollector, "run", keep_resumed_run_active)
    app = create_app(database, youtube_api_key="local-test-key")
    with TestClient(app) as client:
        response = client.post(f"/api/runs/{run['collection_run_id']}/continue")
        assert response.status_code == 202
        assert response.json()["collection_run_id"] == run["collection_run_id"]
        assert set(app.state.collectors.tasks) == {run["collection_run_id"]}
        assert len(client.get("/api/runs").json()) == 1
        rejected = client.post(f"/api/runs/{run['collection_run_id']}/continue")
        assert rejected.status_code == 422


def test_web_rejects_youtube_start_without_local_api_key(tmp_path: Path):
    app = create_app(tmp_path / "glyph-social.sqlite3", youtube_api_key="")
    with TestClient(app) as client:
        scope = client.post("/api/scopes", json={
            "platform": "youtube",
            "name": "YouTube 无密钥",
            "object_type": "writing_system",
            "object_label": "latin",
            "keywords": ["typography"],
            "languages": ["en"],
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2027-09-03T00:00:00Z",
            "max_items": 5,
        }).json()
        response = client.post("/api/runs", json={"scope_id": scope["scope_id"]})
        assert response.status_code == 422
        assert "GLYPH_YOUTUBE_API_KEY" in response.json()["detail"]
        assert client.get("/api/runs").json() == []
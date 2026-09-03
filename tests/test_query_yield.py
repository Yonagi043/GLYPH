from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.query_yield import (
    DEFAULT_POLICY,
    build_query_yield_report,
    wilson_interval,
)
from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.storage import SCHEMA_VERSION, ResearchStore
from glyph_features.social_system.web import create_app


def _query(query_id: str) -> dict:
    return {
        "query_id": query_id,
        "query_family": "object_aesthetic",
        "phase": "calibration",
        "exact_query": f'"Latin typography" {query_id}',
    }


def _evidence(query_id: str, included: int, total: int = 20):
    matches = []
    screenings = []
    for index in range(1, total + 1):
        observation_id = f"obs_{query_id}_{index:02d}"
        matches.append({
            "observation_id": observation_id,
            "query_id": query_id,
            "context": {
                "kind": "video",
                "retrieval": {"candidate_rank": index},
            },
        })
        screenings.append({
            "screening_id": index,
            "observation_id": observation_id,
            "decision": "include" if index <= included else "exclude",
            "signals": {"manual_review": True},
        })
    return matches, screenings


def test_query_yield_distinguishes_pass_fail_and_inconclusive():
    passing_matches, passing_screenings = _evidence("premium", included=6)
    failing_matches, failing_screenings = _evidence("modern", included=2)
    report = build_query_yield_report(
        collection_run_id="run_calibration",
        run_status="completed",
        queries=[_query("premium"), _query("modern")],
        matches=passing_matches + failing_matches,
        screening_history=passing_screenings + [
            {**row, "screening_id": row["screening_id"] + 20}
            for row in failing_screenings
        ],
        policy=DEFAULT_POLICY,
        assessment_mode="preregistered",
    )

    assert report["status"] == "failed"
    assert report["calibration_passed"] is False
    assert report["calibration_passed_query_ids"] == ["premium"]
    assert report["candidate_query_match_count"] == 40
    premium, modern = report["query_results"]
    assert premium["status"] == "passed"
    assert premium["precision_at_k"] == 0.3
    assert premium["precision_at_k_interval"]["lower"] > 0.10
    assert modern["status"] == "failed"
    assert modern["precision_at_k"] == 0.1
    assert modern["failure_reasons"] == [
        "included_at_k_below_minimum",
        "precision_at_k_below_minimum",
        "precision_lower_bound_below_minimum",
    ]


def test_small_retrospective_pilot_is_inconclusive_not_failed():
    matches, screenings = _evidence("premium", included=0, total=2)
    for match in matches:
        match["context"] = {"kind": "video"}
    report = build_query_yield_report(
        collection_run_id="run_small_pilot",
        run_status="completed",
        queries=[_query("premium")],
        matches=matches,
        screening_history=screenings,
    )

    result = report["query_results"][0]
    assert report["status"] == "inconclusive"
    assert report["calibration_passed"] is False
    assert result["overall_precision"] == 0.0
    assert result["overall_precision_interval"]["upper"] == pytest.approx(
        0.6576197725
    )
    assert result["precision_at_k"] is None
    assert result["inconclusive_reasons"] == [
        "retrieved_below_evaluation_k",
        "rank_metadata_incomplete",
    ]


def test_wilson_interval_rejects_invalid_counts():
    assert wilson_interval(0, 0) is None
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(3, 2)


def test_incomplete_run_cannot_expose_queries_for_promotion():
    matches, screenings = _evidence("premium", included=6)
    report = build_query_yield_report(
        collection_run_id="run_still_collecting",
        run_status="running",
        queries=[_query("premium")],
        matches=matches,
        screening_history=screenings,
        assessment_mode="preregistered",
    )

    assert report["status"] == "inconclusive"
    assert report["global_inconclusive_reasons"] == ["run_not_completed"]
    assert report["query_results"][0]["status"] == "passed"
    assert report["calibration_passed_query_ids"] == []


def test_comments_do_not_inflate_query_yield_denominator():
    matches, screenings = _evidence("premium", included=6)
    matches.append({
        "observation_id": "obs_comment",
        "query_id": "premium",
        "context": {"kind": "commentThread"},
    })
    report = build_query_yield_report(
        collection_run_id="run_with_comments",
        run_status="completed",
        queries=[_query("premium")],
        matches=matches,
        screening_history=screenings,
        assessment_mode="preregistered",
    )

    assert report["unique_candidate_count"] == 20
    assert report["candidate_query_match_count"] == 20
    assert report["query_results"][0]["retrieved_count"] == 20


def test_preregistered_calibration_report_is_persisted_exported_and_staleable(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        platform="youtube",
        name="YouTube query 产出校准",
        object_type="writing_system",
        object_label="latin",
        keywords=["latin", "typography"],
        languages=["en"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-03T00:00:00Z",
        max_items=20,
        query_family="object_aesthetic",
        phase="calibration",
        exact_query='"Latin typography" premium',
        max_videos=20,
        max_comment_threads_per_video=0,
        max_replies_per_thread=0,
        query_yield_min_precision_at_k=0.29,
        query_yield_min_precision_lower_bound=0.12,
    )
    failed_query = service.add_scope_query(
        scope["scope_id"],
        query_family="object_aesthetic",
        phase="calibration",
        exact_query='"Latin letterforms" modern',
    )
    run = service.start_run(scope["scope_id"])
    for query_index, query_id in enumerate(
        [scope["query_id"], failed_query["query_id"]], start=1
    ):
        for rank in range(1, 21):
            resource = {
                "id": f"calibration{query_index}_{rank:02d}",
                "snippet": {
                    "publishedAt": "2026-09-02T08:00:00Z",
                    "title": f"Latin typography candidate {query_index}-{rank}",
                    "description": "Candidate for independent relevance screening.",
                    "defaultLanguage": "en",
                },
                "statistics": {"commentCount": "0"},
            }
            assert service.process_youtube_resource(
                run["collection_run_id"],
                resource,
                {"kind": "video", "matched_query_id": query_id},
                query_id=query_id,
                candidate_rank=rank,
            )
    service.finish_run(run["collection_run_id"], "completed")

    matches = service.observation_query_matches(run["collection_run_id"])
    retrieval_by_observation = {
        row["observation_id"]: (
            row["query_id"],
            row["context"]["retrieval"]["candidate_rank"],
        )
        for row in matches
    }
    blinded_queue = service.screening_queue(run["collection_run_id"])
    assert blinded_queue == service.screening_queue(run["collection_run_id"])
    assert all("query_id" not in row and "query_text" not in row for row in blinded_queue)
    assert len(blinded_queue) == 40
    assert [
        retrieval_by_observation[row["observation_id"]][1]
        for row in blinded_queue[:20]
    ] != list(range(1, 21))
    for observation_id, (query_id, rank) in retrieval_by_observation.items():
        service.screen_observation(
            observation_id,
            decision=(
                "include"
                if query_id == scope["query_id"] and rank <= 6
                else "exclude"
            ),
            reason="离线 fixture 的独立相关性判断。",
        )

    with TestClient(create_app(service.database_path)) as client:
        response = client.post(
            f"/api/runs/{run['collection_run_id']}/query-yield"
        )
        assert response.status_code == 200
        report = response.json()
        workspace = client.get(
            f"/api/runs/{run['collection_run_id']}/query-yield"
        ).json()
    query_results = {
        row["query_id"]: row for row in report["query_results"]
    }
    assert report["status"] == "failed"
    assert report["calibration_passed"] is False
    assert report["calibration_passed_query_ids"] == [scope["query_id"]]
    assert query_results[scope["query_id"]]["precision_at_k"] == 0.3
    assert query_results[failed_query["query_id"]]["status"] == "failed"
    assert workspace["policy_snapshot"]["assessment_mode"] == "preregistered"
    assert workspace["policy_snapshot"]["policy"]["min_precision_at_k"] == 0.29
    assert workspace["policy_snapshot"]["policy"][
        "min_precision_lower_bound"
    ] == 0.12
    assert workspace["latest_report_is_current"] is True

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_dir = Path(exported["directory"])
    policy = json.loads(
        (export_dir / "query_yield_policy.json").read_text(encoding="utf-8")
    )
    snapshot = json.loads(
        (export_dir / "yield_calibration.json").read_text(encoding="utf-8")
    )
    history = [
        json.loads(line)
        for line in (export_dir / "query_yield_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert policy["assessment_mode"] == "preregistered"
    assert snapshot["evidence_revision"] == report["evidence_revision"]
    assert history[-1]["query_yield_report_id"] == report["query_yield_report_id"]

    promotion_payload = {
        "name": "YouTube 独立确认范围",
        "window_start": "2026-09-03T00:00:00Z",
        "window_end": "2026-10-03T00:00:00Z",
        "max_items": 120,
        "max_videos": 20,
        "max_comment_threads_per_video": 10,
        "max_replies_per_thread": 5,
    }
    with TestClient(create_app(service.database_path)) as client:
        missing_design_response = client.post(
            f"/api/runs/{run['collection_run_id']}/query-yield/promote",
            json={},
        )
        overlapping_response = client.post(
            f"/api/runs/{run['collection_run_id']}/query-yield/promote",
            json={
                **promotion_payload,
                "window_start": "2026-09-02T00:00:00Z",
                "window_end": "2026-09-04T00:00:00Z",
            },
        )
        promotion_response = client.post(
            f"/api/runs/{run['collection_run_id']}/query-yield/promote",
            json=promotion_payload,
        )
    assert missing_design_response.status_code == 422
    assert overlapping_response.status_code == 409
    assert "不得与 calibration 窗口重叠" in overlapping_response.json()["detail"]
    assert promotion_response.status_code == 200
    promotion = promotion_response.json()
    promoted = promotion["promoted_queries"]
    confirmatory_scope = promotion["confirmatory_scope"]
    assert len(promoted) == 1
    assert confirmatory_scope["scope_id"] != scope["scope_id"]
    assert confirmatory_scope["window_start"] == "2026-09-03T00:00:00Z"
    assert confirmatory_scope["window_end"] == "2026-10-03T00:00:00Z"
    assert confirmatory_scope["max_items"] == 120
    assert promoted[0]["phase"] == "confirmatory"
    assert promoted[0]["layer_quotas"] == {
        "max_videos": 20,
        "max_comment_threads_per_video": 10,
        "max_replies_per_thread": 5,
    }
    assert promoted[0]["supersedes_query_id"] == scope["query_id"]
    assert promoted[0]["promotion_evidence"] == {
        "collection_run_id": run["collection_run_id"],
        "source_query_id": scope["query_id"],
        "query_yield_report_id": report["query_yield_report_id"],
        "policy_version": "query_yield_v0.1.0",
    }
    assert service.get_scope(scope["scope_id"])["active"] is False
    active_queries = service.get_scope(confirmatory_scope["scope_id"])["queries"]
    assert [query["query_id"] for query in active_queries] == [
        promoted[0]["query_id"]
    ]
    confirmation_run = service.start_run(confirmatory_scope["scope_id"])
    assert confirmation_run["query_ids"] == [promoted[0]["query_id"]]
    with TestClient(create_app(service.database_path)) as client:
        duplicate_response = client.post(
            f"/api/runs/{run['collection_run_id']}/query-yield/promote",
            json={**promotion_payload, "window_end": "2026-11-03T00:00:00Z"},
        )
    assert duplicate_response.status_code == 409
    assert len(service.list_scopes()) == 2

    changed_observation_id = next(
        observation_id
        for observation_id, (query_id, rank) in retrieval_by_observation.items()
        if query_id == scope["query_id"] and rank == 1
    )
    service.screen_observation(
        changed_observation_id,
        decision="exclude",
        reason="第二轮人工复核后改判为不相关。",
    )
    stale_workspace = service.query_yield_workspace(run["collection_run_id"])
    assert stale_workspace["latest_report_is_current"] is False
    assert stale_workspace["current_report"]["query_results"][0][
        "included_count"
    ] == 5
    with pytest.raises(ValueError, match="校准证据已变化"):
        service.start_run(confirmatory_scope["scope_id"])

    with ResearchStore(service.database_path) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_calibration_scope_rejects_shallow_or_mixed_phase_design(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    common = {
        "platform": "youtube",
        "object_type": "writing_system",
        "object_label": "latin",
        "keywords": ["latin", "typography"],
        "languages": ["en"],
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-03T00:00:00Z",
        "max_items": 20,
        "query_family": "object_aesthetic",
        "phase": "calibration",
        "max_comment_threads_per_video": 0,
        "max_replies_per_thread": 0,
    }
    with pytest.raises(ValueError, match="不得低于 evaluation_k"):
        service.create_scope(
            name="深度不足",
            exact_query='"Latin typography" premium',
            max_videos=19,
            **common,
        )

    scope = service.create_scope(
        name="阶段混跑阻断",
        exact_query='"Latin typography" premium',
        max_videos=20,
        **common,
    )
    with pytest.raises(ValueError, match="calibration scope 不得启用调度"):
        service.create_schedule(scope["scope_id"], interval_minutes=60, enabled=True)
    schedule = service.create_schedule(
        scope["scope_id"], interval_minutes=60, enabled=False
    )
    with pytest.raises(ValueError, match="calibration scope 不得启用调度"):
        service.update_schedule(
            schedule["schedule_id"], interval_minutes=60, enabled=True
        )
    with pytest.raises(ValueError, match="calibration run 只能手动启动"):
        service.start_run(scope["scope_id"], trigger_type="scheduled")
    service.start_run(scope["scope_id"])
    with pytest.raises(ValueError, match="calibration scope 只能运行一次"):
        service.start_run(scope["scope_id"])
    with pytest.raises(ValueError, match="calibration run 只能手动启动"):
        service.start_run(scope["scope_id"], trigger_type="retry")
    service.add_scope_query(
        scope["scope_id"],
        query_family="object_aesthetic",
        phase="confirmatory",
        exact_query='"Latin typography" modern',
    )
    with pytest.raises(ValueError, match="不得与其他研究阶段混合"):
        service.start_run(scope["scope_id"])
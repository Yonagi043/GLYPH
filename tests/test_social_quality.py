from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.social_system.service import SocialNarrativeService
from glyph_features.social_system.web import create_app


def _post_event(index: int, text: str) -> dict:
    return {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#commit",
            "did": "did:plc:quality-fixture",
            "seq": 24_664_300_000 + index,
            "time": "2026-09-02T08:30:00Z",
            "operation": "create",
            "collection": "app.bsky.feed.post",
            "rkey": f"quality{index:03d}",
            "cid": f"bafyquality{index:03d}",
            "record": {
                "$type": "app.bsky.feed.post",
                "createdAt": "2026-09-02T08:29:59Z",
                "langs": ["en"],
                "text": text,
            },
        },
    }


def test_quality_gate_blocks_low_agreement_and_preserves_adjudication_inputs(
    tmp_path: Path,
):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="确认阶段双编质量",
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
    )
    run = service.start_run(scope["scope_id"])
    texts = [
        "Latin typography feels premium.",
        "Latin typography feels modern.",
    ]
    for index, text in enumerate(texts, start=1):
        assert service.process_event(
            run["collection_run_id"], _post_event(index, text)
        )
    observations = {row["text"]: row for row in service.observations()}
    for observation in observations.values():
        service.screen_observation(
            observation["observation_id"],
            decision="include",
            reason="fixture 明确包含对象—评价关系。",
        )

    first = observations[texts[0]]
    second = observations[texts[1]]
    shared = {
        "object_type": "writing_system",
        "object_label": "latin",
        "stance": "positive",
        "language_confirmed": True,
        "author_role": "ordinary_user",
    }
    for coder_id in ("annotator_aa", "annotator_bb"):
        service.submit_independent_annotation(
            first["observation_id"],
            coder_id=coder_id,
            aesthetic_terms=["premium"],
            evidence_span=texts[0],
            **shared,
        )
    service.submit_independent_annotation(
        second["observation_id"],
        coder_id="annotator_aa",
        aesthetic_terms=["modern"],
        evidence_span=texts[1],
        **shared,
    )
    service.submit_independent_annotation(
        second["observation_id"],
        coder_id="annotator_bb",
        object_type="writing_system",
        object_label="han",
        aesthetic_terms=["modern"],
        evidence_span=texts[1],
        stance="negative",
        language_confirmed=True,
        author_role="ordinary_user",
    )

    report = service.evaluate_run_quality(run["collection_run_id"])
    assert report["status"] == "failed"
    assert report["double_coded_count"] == 2
    assert report["agreement"]["object_label"]["alpha"] < 0.80
    assert report["agreement"]["stance"]["alpha"] < 0.80
    assert "agreement_below_0.80" in report["blockers"]

    service.adjudicate_observation(
        second["observation_id"],
        adjudicator_id="annotator_cc",
        object_type="writing_system",
        object_label="latin",
        aesthetic_terms=["modern"],
        evidence_span=texts[1],
        stance="positive",
        confidence=1.0,
        reason="第三位编码员依据原文裁决。",
        author_role="ordinary_user",
    )
    assert len(service.independent_annotations(run["collection_run_id"])) == 4
    assert len(service.adjudications(run["collection_run_id"])) == 1
    adjudicated = next(
        row
        for row in service.observations()
        if row["observation_id"] == second["observation_id"]
    )
    assert adjudicated["annotation_status"] == "human_verified"
    assert adjudicated["annotator_ref"] == "annotator_cc"


def test_quality_gate_passes_complete_agreement_without_enabling_release(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="确认阶段一致性通过",
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
    )
    run = service.start_run(scope["scope_id"])
    cases = [
        ("Latin typography feels premium.", "latin", "premium", "positive"),
        ("Han typography is modern, not traditional.", "han", "modern", "negative"),
    ]
    for index, (text, _, _, _) in enumerate(cases, start=1):
        assert service.process_event(run["collection_run_id"], _post_event(index, text))
    service.finish_run(run["collection_run_id"], "completed")
    observations = {row["text"]: row for row in service.observations()}
    for text, object_label, term, stance in cases:
        observation_id = observations[text]["observation_id"]
        service.screen_observation(
            observation_id,
            decision="include",
            reason="fixture 明确包含对象—评价关系。",
        )
        for coder_id in ("annotator_aa", "annotator_bb"):
            service.submit_independent_annotation(
                observation_id,
                coder_id=coder_id,
                object_type="writing_system",
                object_label=object_label,
                aesthetic_terms=[term],
                evidence_span=text,
                stance=stance,
                language_confirmed=True,
                author_role="ordinary_user",
            )
        service.review_observation(
            observation_id,
            status="human_verified",
            object_type="writing_system",
            object_label=object_label,
            aesthetic_terms=[term],
            evidence_span=text,
            stance=stance,
            confidence=1.0,
            exclusion_reason=None,
            author_role="ordinary_user",
        )

    report = service.evaluate_run_quality(run["collection_run_id"])
    assert report["status"] == "passed"
    assert report["blockers"] == []
    assert report["agreement"]["object_label"]["alpha"] == 1.0
    assert report["agreement"]["stance"]["alpha"] == 1.0
    assert all(
        row["alpha"] == 1.0
        for row in report["agreement"]["aesthetic_terms"].values()
    )
    assert report["quality_gate_passed"] is True
    assert report["governance_release_allowed"] is False
    with TestClient(create_app(service.database_path)) as client:
        workspace = client.get(
            f"/api/runs/{run['collection_run_id']}/quality-workspace"
        )
        assert workspace.status_code == 200
        assert len(workspace.json()["independent_annotations"]) == 4
        response = client.post(
            f"/api/runs/{run['collection_run_id']}/release",
            json={
                "release_allowed": True,
                "reason": "质量报告通过后由本机研究者明确批准 fixture 发布。",
            },
        )
        assert response.status_code == 200
        governance = response.json()
    assert governance["release_allowed"] is True

    exported = service.export_run(run["collection_run_id"], tmp_path / "exports")
    export_dir = Path(exported["directory"])
    annotations = [
        json.loads(line)
        for line in (export_dir / "independent_annotations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    quality_reports = [
        json.loads(line)
        for line in (export_dir / "quality_reports.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    with (export_dir / "queries.csv").open(encoding="utf-8", newline="") as handle:
        query = next(csv.DictReader(handle))
    assert len(annotations) == 4
    assert quality_reports[-1]["quality_gate_passed"] is True
    assert query["query_family"] == "object_aesthetic"
    assert query["phase"] == "confirmatory"
    assert query["exact_query"] == '"Latin" typography'
    service.set_run_release(
        run["collection_run_id"],
        release_allowed=False,
        reason="fixture 撤销发布授权以测试报告过期。",
    )
    first_observation = observations[cases[0][0]]
    service.screen_observation(
        first_observation["observation_id"],
        decision="include",
        reason="第二次人工复核后仍纳入。",
    )
    with pytest.raises(ValueError, match="证据已变化"):
        service.set_run_release(
            run["collection_run_id"],
            release_allowed=True,
            reason="不得复用过期通过报告。",
        )


def test_release_rejects_failed_quality_report(tmp_path: Path):
    service = SocialNarrativeService(tmp_path / "glyph-social.sqlite3")
    scope = service.create_scope(
        name="质量报告过期阻断",
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
    )
    run = service.start_run(scope["scope_id"])
    assert service.process_event(
        run["collection_run_id"], _post_event(1, "Latin typography feels premium.")
    )
    service.finish_run(run["collection_run_id"], "completed")
    observation = service.observations()[0]
    service.screen_observation(
        observation["observation_id"],
        decision="include",
        reason="fixture 明确包含对象—评价关系。",
    )
    failed = service.evaluate_run_quality(run["collection_run_id"])
    assert failed["status"] == "failed"
    with pytest.raises(ValueError, match="最新质量报告未通过"):
        service.set_run_release(
            run["collection_run_id"],
            release_allowed=True,
            reason="不得绕过失败报告。",
        )

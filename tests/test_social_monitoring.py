from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.social_io import validation_errors, validator, write_jsonl


ROOT = Path(__file__).parents[1]


def _record(number: int, object_label: str, terms: list[str], *, status: str = "human_verified", platform: str = "x", engagement: int = 0) -> dict:
    """Create a minimal but schema-complete observation for deterministic tests."""

    record = {
        "schema_version": "0.1.0",
        "observation_id": f"obs_test_{number:03d}",
        "collection_run_id": "social_run_test",
        "platform": platform,
        "platform_item_id": str(number),
        "source_id": f"src_test_{number:03d}",
        "url": f"https://example.org/item/{number}",
        "source_kind": "imported_export",
        "query_id": "q_test_terms",
        "query_text": "test",
        "published_at": f"2026-08-{number + 1:02d}T00:00:00Z",
        "collected_at": "2026-09-01T00:00:00Z",
        "language_bcp47": "en",
        "region_hint": "INTL",
        "title": None,
        "text": f"Evidence text {number}",
        "content_status": "available",
        "author_ref": None,
        "author_role": "ordinary_user",
        "writing_system": "latin",
        "style_family": "sans",
        "object_type": "writing_system",
        "object_label": object_label,
        "stimulus_id": None,
        "font_id": None,
        "aesthetic_terms": terms,
        "brand_context": [],
        "stance": "descriptive",
        "mechanism_claim": None,
        "evidence_span": f"Evidence text {number}",
        "engagement": {
            "like_count": engagement,
            "comment_count": None,
            "share_count": None,
            "quote_count": None,
            "view_count": None,
            "score": None,
            "observed_at": "2026-09-01T00:00:00Z",
            "is_public": True,
        },
        "references": [],
        "annotation_status": status,
        "annotator_ref": "annotator_test01",
        "human_verified_at": "2026-09-01T00:00:00Z",
        "exclusion_reason": None,
        "governance": {
            "author_handling": "not_collected",
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": None,
        },
        "normalization": {
            "normalizer_version": "test",
            "input_sha256": "0" * 64,
            "record_sha256": "0" * 64,
            "normalized_at": "2026-09-01T00:00:00Z",
        },
        "extra": {},
    }
    if status != "human_verified":
        record["human_verified_at"] = None
        record["evidence_span"] = None
    return record


def test_template_record_validates():
    record = json.loads((ROOT / "data/templates/social_observations.jsonl").read_text(encoding="utf-8"))
    assert validation_errors(record, validator()) == []


@pytest.mark.parametrize(
    "relative_path",
    [
        "data/templates/social_codebook.csv",
        "data/templates/social_object_map.csv",
        "data/templates/social_queries.csv",
        "data/templates/stimulus_manifest.csv",
        "data/templates/visual_features.csv",
    ],
)
def test_csv_templates_are_rectangular(relative_path: str):
    """A malformed CSV row would silently shift fields in DictReader."""

    with (ROOT / relative_path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows
    assert all(len(row) == len(rows[0]) for row in rows)


def test_demo_validates_with_its_generated_source_registry():
    """The checked-in synthetic fixture is a complete, reviewable example."""

    command = [
        sys.executable,
        str(ROOT / "tools/validate_social_observations.py"),
        "--input",
        str(ROOT / "demo/social_narrative/observations.jsonl"),
        "--queries",
        str(ROOT / "data/templates/social_queries.csv"),
        "--codebook",
        str(ROOT / "data/templates/social_codebook.csv"),
        "--objects",
        str(ROOT / "data/templates/social_object_map.csv"),
        "--sources",
        str(ROOT / "demo/social_narrative/sources.csv"),
        "--run-manifest",
        str(ROOT / "demo/social_narrative/run_manifest.json"),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert '"valid": true' in result.stdout


def test_social_run_manifest_template_validates():
    from tools.social_io import schema_validator

    schema_path = ROOT / "schema/social_run_manifest.schema.json"
    if not schema_path.exists():
        pytest.skip("run-manifest schema is optional in older checkouts")
    check = schema_validator(schema_path)
    manifest = json.loads((ROOT / "data/templates/social_run_manifest.json").read_text(encoding="utf-8"))
    assert list(check.iter_errors(manifest)) == []


def test_human_verified_record_requires_evidence():
    record = _record(1, "latin", ["premium"])
    record["evidence_span"] = None
    assert validation_errors(record, validator())


def test_normalizer_accepts_pretty_printed_api_payload_and_is_deterministic(tmp_path: Path):
    payload = {
        "data": [
            {
                "id": "abc123",
                "created_at": "2026-08-31T10:20:30Z",
                "text": "Latin wordmark feels premium",
                "public_metrics": {"like_count": 4, "reply_count": 2, "repost_count": 1, "quote_count": 0},
                "lang": "en",
            }
        ]
    }
    source = tmp_path / "api.json"
    source.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_a = tmp_path / "a.jsonl"
    out_b = tmp_path / "b.jsonl"
    base = [sys.executable, str(ROOT / "tools/normalize_social_records.py"), "--input", str(source), "--platform", "x", "--source-kind", "official_api", "--collection-run-id", "social_run_test_x", "--normalized-at", "2026-09-01T00:00:00Z"]
    first = subprocess.run(base + ["--output", str(out_a)], cwd=ROOT, text=True, capture_output=True)
    second = subprocess.run(base + ["--output", str(out_b)], cwd=ROOT, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert out_a.read_bytes() == out_b.read_bytes()
    rows = [json.loads(line) for line in out_a.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["author_ref"] is None
    assert rows[0]["engagement"]["comment_count"] == 2
    assert validation_errors(rows[0], validator()) == []
    audit = subprocess.run(
        [sys.executable, str(ROOT / "tools/validate_social_observations.py"), "--input", str(out_a)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert audit.returncode == 0, audit.stderr


def test_normalizer_preserves_failures(tmp_path: Path):
    source = tmp_path / "bad.jsonl"
    source.write_text(json.dumps({"text": "no id or usable public URL"}) + "\n", encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [sys.executable, str(ROOT / "tools/normalize_social_records.py"), "--input", str(source), "--output", str(output), "--platform", "public_web", "--collection-run-id", "social_run_test_bad", "--allow-failures"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    with (tmp_path / "observations.jsonl.failures.csv").open(encoding="utf-8", newline="") as handle:
        failures = list(csv.DictReader(handle))
    assert len(failures) == 1
    assert failures[0]["error_code"] == "missing_item_id"
    assert output.read_text(encoding="utf-8") == ""


def test_normalizer_rejects_duplicate_platform_items_even_with_custom_ids(tmp_path: Path):
    source = tmp_path / "duplicates.json"
    source.write_text(json.dumps([
        {"id": "same", "observation_id": "obs_custom_001", "url": "https://example.org/a"},
        {"id": "same", "observation_id": "obs_custom_002", "url": "https://example.org/a"},
    ]), encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [sys.executable, str(ROOT / "tools/normalize_social_records.py"), "--input", str(source), "--output", str(output), "--platform", "public_web", "--collection-run-id", "social_run_test_dup", "--normalized-at", "2026-09-01T00:00:00Z", "--allow-failures"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    failures = list(csv.DictReader((tmp_path / "observations.jsonl.failures.csv").open(encoding="utf-8", newline="")))
    assert failures[0]["error_code"] == "duplicate_platform_item"


def test_normalizer_does_not_overwrite_without_force(tmp_path: Path):
    source = tmp_path / "one.json"
    source.write_text(json.dumps({"id": "one", "url": "https://example.org/one"}), encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [sys.executable, str(ROOT / "tools/normalize_social_records.py"), "--input", str(source), "--output", str(output), "--platform", "public_web", "--collection-run-id", "social_run_test_overwrite", "--normalized-at", "2026-09-01T00:00:00Z"]
    assert subprocess.run(command, cwd=ROOT, text=True, capture_output=True).returncode == 0
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert second.returncode == 2
    assert "output exists" in second.stderr


def test_normalizer_records_input_parse_failure(tmp_path: Path):
    source = tmp_path / "malformed.jsonl"
    source.write_text('{"id": "ok"}\nnot-json\n', encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [sys.executable, str(ROOT / "tools/normalize_social_records.py"), "--input", str(source), "--output", str(output), "--platform", "x", "--collection-run-id", "social_run_test_parse", "--normalized-at", "2026-09-01T00:00:00Z"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 2
    failures = list(csv.DictReader((tmp_path / "observations.jsonl.failures.csv").open(encoding="utf-8", newline="")))
    assert len(failures) == 1
    assert failures[0]["error_code"] == "input_parse_error"


def test_summarizer_writes_both_directions_and_lift(tmp_path: Path):
    records = [
        _record(1, "latin", ["premium"]),
        _record(2, "latin", ["premium", "modern"]),
        _record(3, "han", ["traditional"]),
        _record(4, "han", ["premium"]),
    ]
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, records)
    output_dir = tmp_path / "matrices"
    command = [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    with (output_dir / "matrix_a_term_given_object.csv").open(encoding="utf-8", newline="") as handle:
        matrix_a = list(csv.DictReader(handle))
    with (output_dir / "matrix_b_object_given_term.csv").open(encoding="utf-8", newline="") as handle:
        matrix_b = list(csv.DictReader(handle))
    with (output_dir / "lift.csv").open(encoding="utf-8", newline="") as handle:
        lift = list(csv.DictReader(handle))
    latin_premium = next(row for row in matrix_a if row["object_label"] == "latin" and row["term"] == "premium")
    # Two of three Latin/Han records carry premium; both Latin records do.
    assert latin_premium["p_term_given_object"] == "1.00000000"
    premium_for_latin = next(row for row in matrix_b if row["term"] == "premium" and row["object_label"] == "latin")
    assert premium_for_latin["p_object_given_term"] == "0.66666667"
    latin_lift = next(row for row in lift if row["object_label"] == "latin" and row["term"] == "premium")
    assert latin_lift["lift"] == "1.33333333"
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["included_records"] == 4
    assert summary["weight_mode"] == "records"
    assert summary["engagement"]["like_count"]["sum"] == 0


def test_summarizer_rejects_duplicate_observation_ids(tmp_path: Path):
    record = _record(1, "latin", ["premium"])
    observations = tmp_path / "duplicates.jsonl"
    write_jsonl(observations, [record, dict(record)])
    output_dir = tmp_path / "matrices"
    command = [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 2
    assert "duplicate observation_id" in result.stderr


def test_summarizer_does_not_overwrite_without_force(tmp_path: Path):
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [_record(1, "latin", ["premium"])])
    output_dir = tmp_path / "matrices"
    command = [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir)]
    assert subprocess.run(command, cwd=ROOT, text=True, capture_output=True).returncode == 0
    second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert second.returncode == 2
    assert "output exists" in second.stderr


def test_projector_requires_review_confidence_and_emits_shared_narrative(tmp_path: Path):
    record = _record(1, "latin", ["premium", "modern"])
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [record])
    output = tmp_path / "narratives.jsonl"
    command = [sys.executable, str(ROOT / "tools/project_social_to_narratives.py"), "--input", str(observations), "--output", str(output)]
    missing = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert missing.returncode == 2
    assert "missing_annotation_confidence" in (tmp_path / "narratives.jsonl.failures.csv").read_text(encoding="utf-8")

    output.unlink()
    (tmp_path / "narratives.jsonl.failures.csv").unlink()
    record["annotation_confidence"] = 0.9
    write_jsonl(observations, [record])
    ok = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert ok.returncode == 0, ok.stderr
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert sorted(row["aesthetic_term"] for row in rows) == ["modern", "premium"]
    assert all(row["human_verified"] is True and row["confidence"] == 0.9 for row in rows)


def test_engagement_weight_never_uses_views_as_interactions(tmp_path: Path):
    records = [_record(1, "latin", ["premium"], engagement=2), _record(2, "han", ["premium"], engagement=3)]
    records[0]["engagement"]["view_count"] = 100000
    records[1]["engagement"]["view_count"] = 1
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, records)
    output_dir = tmp_path / "matrices"
    command = [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir), "--platform", "x", "--weight", "engagement"]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["engagement"]["view_count"]["sum"] == 100001
    assert summary["weighted_records"] == 2
    rows = list(csv.DictReader((output_dir / "lift.csv").open(encoding="utf-8", newline="")))
    latin = next(row for row in rows if row["object_label"] == "latin")
    assert latin["object_weight"] == "2.00000000"


def test_normalizer_canonicalizes_tracking_parameters_and_fragment(tmp_path: Path):
    source = tmp_path / "url.json"
    source.write_text(json.dumps({
        "id": "url-1",
        "url": "HTTPS://Example.ORG/item?utm_source=test&b=2&a=1#section",
        "text": "A public typography note",
    }), encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [
        sys.executable, str(ROOT / "tools/normalize_social_records.py"),
        "--input", str(source), "--output", str(output),
        "--platform", "public_web", "--collection-run-id", "social_run_url_test",
        "--normalized-at", "2026-09-01T00:00:00Z",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["url"] == "https://example.org/item?a=1&b=2"


def test_normalizer_rejects_short_author_salt_without_writing_output(tmp_path: Path):
    source = tmp_path / "one.json"
    source.write_text(json.dumps({"id": "one", "url": "https://example.org/one"}), encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [
        sys.executable, str(ROOT / "tools/normalize_social_records.py"),
        "--input", str(source), "--output", str(output),
        "--platform", "public_web", "--collection-run-id", "social_run_salt_test",
        "--author-salt", "too-short",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 2
    assert "author-salt" in result.stderr
    assert not output.exists()


def test_normalizer_requires_annotator_for_human_verified_rows(tmp_path: Path):
    source = tmp_path / "reviewed.json"
    source.write_text(json.dumps({
        "id": "reviewed-1",
        "url": "https://example.org/reviewed",
        "text": "The form is premium",
        "human_verified": True,
        "human_verified_at": "2026-09-01T00:00:00Z",
        "object_type": "writing_system",
        "object_label": "latin",
        "aesthetic_terms": ["premium"],
        "evidence_span": "The form is premium",
    }), encoding="utf-8")
    output = tmp_path / "observations.jsonl"
    command = [
        sys.executable, str(ROOT / "tools/normalize_social_records.py"),
        "--input", str(source), "--output", str(output),
        "--platform", "public_web", "--collection-run-id", "social_run_review_test",
        "--allow-failures",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    failures = list(csv.DictReader((tmp_path / "observations.jsonl.failures.csv").open(encoding="utf-8", newline="")))
    assert failures[0]["error_code"] == "human_verified_requires_annotator_ref"


def test_same_platform_item_in_different_runs_gets_distinct_observation_ids(tmp_path: Path):
    source = tmp_path / "one.json"
    source.write_text(json.dumps({"id": "repeat-1", "url": "https://example.org/repeat"}), encoding="utf-8")
    rows = []
    for run_id, name in [("social_run_repeat_a", "a"), ("social_run_repeat_b", "b")]:
        output = tmp_path / f"{name}.jsonl"
        command = [
            sys.executable, str(ROOT / "tools/normalize_social_records.py"),
            "--input", str(source), "--output", str(output),
            "--platform", "public_web", "--collection-run-id", run_id,
            "--normalized-at", "2026-09-01T00:00:00Z",
        ]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        rows.append(json.loads(output.read_text(encoding="utf-8")))
    assert rows[0]["platform_item_id"] == rows[1]["platform_item_id"] == "repeat-1"
    assert rows[0]["observation_id"] != rows[1]["observation_id"]


def test_summarizer_keeps_reference_edges_when_terms_are_missing(tmp_path: Path):
    record = _record(1, "latin", [], status="candidate")
    record["references"] = [{"relation": "reply", "target_item_id": "outside"}]
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [record])
    output_dir = tmp_path / "matrices"
    command = [
        sys.executable, str(ROOT / "tools/summarize_narratives.py"),
        "--input", str(observations), "--output-dir", str(output_dir),
        "--status", "candidate",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    edges = list(csv.DictReader((output_dir / "reference_edges.csv").open(encoding="utf-8", newline="")))
    assert len(edges) == 1
    assert edges[0]["target_item_id"] == "outside"


def test_projector_maps_creator_to_unknown_in_frozen_schema(tmp_path: Path):
    record = _record(1, "latin", ["premium"])
    record["author_role"] = "creator"
    record["annotation_confidence"] = 0.9
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [record])
    output = tmp_path / "narratives.jsonl"
    command = [
        sys.executable, str(ROOT / "tools/project_social_to_narratives.py"),
        "--input", str(observations), "--output", str(output),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    projected = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert projected[0]["author_role"] == "unknown"


def test_schema_requires_annotator_ref_for_human_verified():
    record = _record(1, "latin", ["premium"])
    record["annotator_ref"] = None
    assert validation_errors(record, validator())


def test_release_validator_detects_record_hash_mismatch(tmp_path: Path):
    record = json.loads((ROOT / "demo/social_narrative/observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
    record["text"] += " tampered"
    observations = tmp_path / "tampered.jsonl"
    write_jsonl(observations, [record])
    command = [
        sys.executable, str(ROOT / "tools/validate_social_observations.py"),
        "--input", str(observations),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 1
    assert "record_hash_mismatch" in result.stderr


def test_release_validator_rejects_placeholder_hashes_without_opt_in(tmp_path: Path):
    observations = tmp_path / "template.jsonl"
    record = json.loads((ROOT / "data/templates/social_observations.jsonl").read_text(encoding="utf-8"))
    write_jsonl(observations, [record])
    command = [
        sys.executable,
        str(ROOT / "tools/validate_social_observations.py"),
        "--input",
        str(observations),
    ]
    rejected = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert rejected.returncode == 1
    assert "zero_record_hash" in rejected.stderr
    accepted = subprocess.run(command + ["--allow-zero-hash"], cwd=ROOT, text=True, capture_output=True)
    assert accepted.returncode == 0


def test_release_validator_rejects_duplicate_platform_item_within_run(tmp_path: Path):
    first = _record(1, "latin", ["premium"])
    second = _record(2, "han", ["traditional"])
    second["platform_item_id"] = first["platform_item_id"]
    observations = tmp_path / "duplicates.jsonl"
    write_jsonl(observations, [first, second])
    command = [
        sys.executable, str(ROOT / "tools/validate_social_observations.py"),
        "--input", str(observations),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 1
    assert "duplicate_platform_item" in result.stderr


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({"media_type": "image/png", "text": ""}, "image_only"),
        ({"media_type": "video/mp4", "text": ""}, "video_only"),
        ({"is_deleted": True, "text": "formerly visible"}, "deleted"),
    ],
)
def test_normalizer_infers_nontext_content_status(tmp_path: Path, extra: dict, expected: str):
    source = tmp_path / f"{expected}.json"
    source.write_text(json.dumps({
        "id": expected,
        "url": f"https://example.org/{expected}",
        **extra,
    }), encoding="utf-8")
    output = tmp_path / f"{expected}.jsonl"
    command = [
        sys.executable, str(ROOT / "tools/normalize_social_records.py"),
        "--input", str(source), "--output", str(output),
        "--platform", "public_web", "--collection-run-id", f"social_run_{expected}",
        "--normalized-at", "2026-09-01T00:00:00Z",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["content_status"] == expected


def test_normalizer_and_summary_preserve_negative_reddit_score(tmp_path: Path):
    source = tmp_path / "reddit.json"
    source.write_text(json.dumps({
        "id": "neg-score",
        "url": "https://example.org/reddit/neg-score",
        "text": "A synthetic premium typography statement",
        "score": -3,
        "object_type": "writing_system",
        "object_label": "latin",
        "aesthetic_terms": ["premium"],
        "evidence_span": "premium typography statement",
        "human_verified": True,
        "annotator_ref": "annotator_test01",
        "human_verified_at": "2026-09-01T00:00:00Z",
    }), encoding="utf-8")
    observations = tmp_path / "observations.jsonl"
    normalize = [
        sys.executable, str(ROOT / "tools/normalize_social_records.py"),
        "--input", str(source), "--output", str(observations),
        "--platform", "reddit", "--collection-run-id", "social_run_negative_score",
        "--normalized-at", "2026-09-01T00:00:00Z",
    ]
    normalized = subprocess.run(normalize, cwd=ROOT, text=True, capture_output=True)
    assert normalized.returncode == 0, normalized.stderr
    assert json.loads(observations.read_text(encoding="utf-8"))["engagement"]["score"] == -3
    output_dir = tmp_path / "matrices"
    summarized = subprocess.run(
        [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert summarized.returncode == 0, summarized.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["engagement"]["score"]["sum"] == -3
    assert summary["engagement"]["score"]["max"] == -3


def test_nonrecord_weight_requires_one_platform(tmp_path: Path):
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [_record(1, "latin", ["premium"], engagement=2)])
    result = subprocess.run(
        [
            sys.executable, str(ROOT / "tools/summarize_narratives.py"),
            "--input", str(observations), "--output-dir", str(tmp_path / "matrices"),
            "--weight", "likes",
        ],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert "platform-local" in result.stderr


def test_summarizer_writes_role_reference_and_time_indexes(tmp_path: Path):
    record = _record(1, "latin", ["premium"])
    record["author_role"] = "design_media"
    record["references"] = [{"relation": "quote", "target_item_id": "outside"}]
    observations = tmp_path / "observations.jsonl"
    write_jsonl(observations, [record])
    output_dir = tmp_path / "matrices"
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/summarize_narratives.py"), "--input", str(observations), "--output-dir", str(output_dir), "--time-granularity", "day"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    roles = list(csv.DictReader((output_dir / "role_timeline.csv").open(encoding="utf-8", newline="")))
    edges = list(csv.DictReader((output_dir / "reference_edges.csv").open(encoding="utf-8", newline="")))
    times = list(csv.DictReader((output_dir / "time_series.csv").open(encoding="utf-8", newline="")))
    assert roles[0]["author_role"] == "design_media"
    assert edges[0]["relation"] == "quote"
    assert times[0]["time_bucket"] == "2026-08-02"

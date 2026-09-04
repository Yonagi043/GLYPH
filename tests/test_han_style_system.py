from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from glyph_features.asset_system.catalog import validate_record
from glyph_features.han_style_system.adapters import build_adapter_records, integration_requests
from glyph_features.han_style_system.claims import validate_claims
from glyph_features.han_style_system.cli import (
    EXIT_NO_OVERWRITE,
    EXIT_OK,
    EXIT_RECORD_FAILURE,
    main as han_cli,
)
from glyph_features.han_style_system.glyphs import (
    load_content_sets,
    validate_character_mappings,
    validate_glyph_instances,
)
from glyph_features.han_style_system.handoff import build_handoff_bundle
from glyph_features.han_style_system.ontology import TARGET_STYLE_CODES, validate_ontology
from glyph_features.han_style_system.review import (
    RUBRIC_DIMENSIONS,
    ReviewError,
    aggregate_reviews,
    build_review_package,
    import_review_rows,
    validate_review_records,
)
from glyph_features.han_style_system.stimuli import build_stimulus_candidates


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "data/fixtures/han_style_system"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def fixture_context() -> dict[str, list[dict]]:
    return {
        "ontology": read_jsonl(FIXTURE / "ontology.jsonl"),
        "mappings": read_jsonl(FIXTURE / "character_mappings.jsonl"),
        "glyphs": read_jsonl(FIXTURE / "glyph_instances.jsonl"),
        "assets": read_jsonl(
            ROOT / "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl"
        ),
        "rights": read_jsonl(
            ROOT / "data/fixtures/asset_system/reference_handoff_v1/rights_evidence.jsonl"
        ),
    }


def synthetic_review_rows(package_dir: Path, decisions: tuple[str, str] = ("pass", "pass")) -> list[dict[str, str]]:
    with (package_dir / "review_template.csv").open(encoding="utf-8", newline="") as handle:
        template = next(csv.DictReader(handle))
    rows: list[dict[str, str]] = []
    for index, decision in enumerate(decisions, start=1):
        row = dict(template)
        row.update(
            {
                "reviewer_id": f"reviewer_fixture_{index:02d}",
                "reviewer_role": "type_or_visual_design",
                "review_origin": "synthetic_fixture",
                "overall_decision": decision,
                "reason_codes": "FIXTURE_ONLY|INSTANCE_LEVEL_ONLY",
                "notes": "Synthetic workflow test; not an expert conclusion.",
                "reviewed_at": f"2026-09-04T0{index}:00:00Z",
            }
        )
        for dimension in RUBRIC_DIMENSIONS:
            row[dimension] = "not_applicable"
        rows.append(row)
    return rows


def ontology_records() -> list[dict]:
    classification = {
        "small_seal": "historical_script",
        "clerical": "historical_script",
        "regular": "historical_script",
        "running": "historical_script",
        "cursive": "historical_script",
        "song": "print_type_category",
        "sans": "modern_digital_category",
        "slender_gold": "calligrapher_style",
    }
    chinese_names = {
        "small_seal": "小篆",
        "clerical": "隶书",
        "regular": "楷书",
        "running": "行书",
        "cursive": "草书",
        "song": "宋体",
        "sans": "黑体",
        "slender_gold": "瘦金体",
    }
    return [
        {
            "schema_version": "1.0.0",
            "style_id": f"style_hs{index:02d}",
            "target_code": target_code,
            "canonical_names": {"zh-Hans": chinese_names[target_code], "en": target_code.replace("_", " ")},
            "historical_names": [],
            "aliases": [],
            "classification_level": classification[target_code],
            "broader_style_ids": [],
            "historical_period": {"label": None, "start_year": None, "end_year": None, "uncertainty": "unknown"},
            "regions": [],
            "typical_media": [],
            "usage_contexts": [],
            "definition_source_ids": ["source_han_fixture_protocol"],
            "record_status": "candidate",
            "human_review_status": "pending",
        }
        for index, target_code in enumerate(sorted(TARGET_STYLE_CODES), start=1)
    ]


def test_ontology_expresses_all_target_styles_without_conflating_classification_levels() -> None:
    records = ontology_records()
    assert validate_ontology(records, ROOT / "schema/han_style_concept.schema.json") == []
    assert {record["classification_level"] for record in records} == {
        "historical_script",
        "calligrapher_style",
        "print_type_category",
        "modern_digital_category",
    }


def test_ontology_rejects_unknown_parent_and_ambiguous_alias() -> None:
    records = copy.deepcopy(ontology_records())
    records[0]["broader_style_ids"] = ["style_missing"]
    records[0]["aliases"] = [{"term": "共享别名", "language_bcp47": "zh-Hans", "alias_type": "controlled"}]
    records[1]["aliases"] = [{"term": "共享别名", "language_bcp47": "zh-Hans", "alias_type": "controlled"}]

    errors = validate_ontology(records, ROOT / "schema/han_style_concept.schema.json")

    assert any(error.startswith("HAN_STYLE_PARENT_UNKNOWN") for error in errors)
    assert any(error.startswith("HAN_ALIAS_AMBIGUOUS") for error in errors)


def test_fixture_contracts_validate_against_task01_assets() -> None:
    sources = read_jsonl(FIXTURE / "sources.jsonl")
    task01_sources = read_jsonl(
        ROOT / "data/fixtures/asset_system/reference_handoff_v1/sources.jsonl"
    )
    source_ids = {record["source_id"] for record in [*sources, *task01_sources]}
    ontology = read_jsonl(FIXTURE / "ontology.jsonl")
    mappings = read_jsonl(FIXTURE / "character_mappings.jsonl")
    claims = read_jsonl(FIXTURE / "claims.jsonl")
    glyphs = read_jsonl(FIXTURE / "glyph_instances.jsonl")
    assets = read_jsonl(
        ROOT / "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl"
    )

    assert all(validate_record(record, ROOT / "schema/source.schema.json") == [] for record in sources)
    assert validate_ontology(ontology, ROOT / "schema/han_style_concept.schema.json") == []
    content_sets = load_content_sets(ROOT / "data/fixtures/content_sets.csv")
    assert validate_character_mappings(
        mappings,
        ROOT / "schema/han_character_mapping.schema.json",
        content_sets,
        source_ids,
    ) == []
    style_ids = {record["style_id"] for record in ontology}
    mapping_ids = {record["mapping_id"] for record in mappings}
    claim_ids = {record["claim_id"] for record in claims}
    glyph_ids = {record["glyph_instance_id"] for record in glyphs}
    assert validate_claims(
        claims,
        ROOT / "schema/han_knowledge_claim.schema.json",
        style_ids=style_ids,
        glyph_ids=glyph_ids,
        source_ids=source_ids,
    ) == []
    assert validate_glyph_instances(
        glyphs,
        ROOT / "schema/han_glyph_instance.schema.json",
        workspace_root=ROOT,
        style_ids=style_ids,
        mapping_ids=mapping_ids,
        source_ids=source_ids,
        asset_records=assets,
        claim_ids=claim_ids,
    ) == []


def test_character_mapping_rejects_silent_unicode_substitution() -> None:
    mappings = read_jsonl(FIXTURE / "character_mappings.jsonl")
    mappings[0]["display_text"] = "水"
    errors = validate_character_mappings(
        mappings,
        ROOT / "schema/han_character_mapping.schema.json",
        load_content_sets(ROOT / "data/fixtures/content_sets.csv"),
        {"source_han_fixture_protocol"},
    )
    assert any(error.startswith("HAN_CONTENT_TEXT_MISMATCH") for error in errors)
    assert any(error.startswith("HAN_UNICODE_CODEPOINT_MISMATCH") for error in errors)


def test_glyph_asset_relationships_and_parent_cycles_are_validated() -> None:
    context = fixture_context()
    glyphs = [copy.deepcopy(context["glyphs"][0]), copy.deepcopy(context["glyphs"][0])]
    glyphs[0]["glyph_instance_id"] = "glyph_cycle_01"
    glyphs[0]["parent_glyph_instance_id"] = "glyph_cycle_02"
    glyphs[0]["work_id"] = "work_mismatch"
    glyphs[1]["glyph_instance_id"] = "glyph_cycle_02"
    glyphs[1]["parent_glyph_instance_id"] = "glyph_cycle_01"
    errors = validate_glyph_instances(
        glyphs,
        ROOT / "schema/han_glyph_instance.schema.json",
        workspace_root=ROOT,
        style_ids={record["style_id"] for record in context["ontology"]},
        mapping_ids={record["mapping_id"] for record in context["mappings"]},
        source_ids={glyph["source_id"] for glyph in glyphs},
        asset_records=context["assets"],
        claim_ids=set(),
    )
    assert any(error.startswith("HAN_GLYPH_ASSET_WORK_MISMATCH") for error in errors)
    assert any(error.startswith("HAN_GLYPH_PARENT_CYCLE") for error in errors)


def test_cultural_association_cannot_be_encoded_as_historical_fact() -> None:
    claims = read_jsonl(FIXTURE / "claims.jsonl")
    claims[1]["relation"] = "historically_is"
    errors = validate_claims(
        claims,
        ROOT / "schema/han_knowledge_claim.schema.json",
        style_ids={"style_hs01"},
        glyph_ids=set(),
        source_ids={"source_han_fixture_protocol"},
    )
    assert any(error.startswith("HAN_ASSOCIATION_AS_FACT") for error in errors)


def test_review_package_and_synthetic_double_review_remain_fixture_only(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    manifest = build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    assert manifest["gate_status"] == "blocked"
    assert (package_dir / "index.html").is_file()
    assert (package_dir / "review_template.csv").is_file()
    item = read_jsonl(package_dir / "items.jsonl")[0]
    assert item["source_asset"]["mime_type"] == "image/png"
    assert item["source_asset"]["path"].endswith(".png")

    reviews = import_review_rows(
        package_dir,
        synthetic_review_rows(package_dir),
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    assert validate_review_records(reviews, ROOT / "schema/expert_review.schema.json") == []
    summary = aggregate_reviews(reviews, minimum_independent_reviews=2)["glyph_han_fixture_01"]
    assert summary["fixture_status"] == "passed"
    assert summary["formal_status"] == "blocked"
    assert summary["real_review_count"] == 0

    candidates = build_stimulus_candidates(
        context["glyphs"],
        context["mappings"],
        reviews,
        context["rights"],
        schema_path=ROOT / "schema/han_stimulus_candidate.schema.json",
        render_profiles=["bbox_height_matched", "ink_area_matched"],
        minimum_independent_reviews=2,
        minimum_independent_exemplars=3,
        created_at="2026-09-04T00:00:00Z",
    )
    assert len(candidates) == 2
    assert {candidate["release_status"] for candidate in candidates} == {"fixture_only"}
    assert {candidate["stimulus_id"] for candidate in candidates} == {None}
    assert {candidate["inference_scope"]["scope"] for candidate in candidates} == {"instance_level_only"}
    assert all("REAL_EXPERT_REVIEWS_REQUIRED" in candidate["task01_freeze"]["blockers"] for candidate in candidates)

    adapters = build_adapter_records(
        context["ontology"],
        candidates,
        schema_path=ROOT / "schema/han_adapter_record.schema.json",
    )
    assert len([record for record in adapters if record["target_system"] == "TASK-02"]) == 2
    assert {record["status"] for record in adapters if record["target_system"] == "TASK-02"} == {"fixture_only"}
    assert {record["status"] for record in adapters if record["target_system"] == "TASK-03"} == {"blocked"}
    wp2 = [record for record in adapters if record["target_system"] == "WP2"]
    assert len(wp2) == 8
    assert sum(record["payload"]["existing_registry_match"] for record in wp2) == 2
    assert {request["target_system"] for request in integration_requests(adapters)} == {
        "TASK-01",
        "TASK-02",
        "TASK-03",
        "WP2",
    }


def test_review_conflict_is_retained_and_blocks_fixture_status(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    reviews = import_review_rows(
        package_dir,
        synthetic_review_rows(package_dir, decisions=("pass", "fail")),
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    summary = aggregate_reviews(reviews, minimum_independent_reviews=2)["glyph_han_fixture_01"]
    assert summary["fixture_status"] == "conflicted"
    assert summary["decision_counts"] == {"fail": 1, "pass": 1}
    assert len(reviews) == 2


def test_real_expert_review_requires_external_gate_approval(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    rows = synthetic_review_rows(package_dir)
    rows[0]["review_origin"] = "real_expert"
    rows[0]["reviewer_id"] = "reviewer_pseudonymous_01"
    with pytest.raises(ReviewError, match="GATE_EXPERT_APPROVAL_REQUIRED"):
        import_review_rows(
            package_dir,
            rows,
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_review_package_and_records_detect_tampering(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    rows = synthetic_review_rows(package_dir)
    reviews = import_review_rows(
        package_dir,
        rows,
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    reviews[0]["notes"] = "tampered"
    assert any(
        error.startswith("HAN_REVIEW_SIGNATURE_MISMATCH")
        for error in validate_review_records(reviews, ROOT / "schema/expert_review.schema.json")
    )

    with (package_dir / "items.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(ReviewError, match="REVIEW_PACKAGE_TAMPERED"):
        import_review_rows(
            package_dir,
            rows,
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_review_package_detects_workbench_tampering(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    rows = synthetic_review_rows(package_dir)
    with (package_dir / "index.html").open("a", encoding="utf-8") as handle:
        handle.write("<!-- tampered -->")
    with pytest.raises(ReviewError, match="REVIEW_PACKAGE_TAMPERED"):
        import_review_rows(
            package_dir,
            rows,
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_review_package_rejects_paths_outside_package(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    rows = synthetic_review_rows(package_dir)
    manifest_path = package_dir / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["item_manifest"]["path"] = "../../items.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReviewError, match="REVIEW_PACKAGE_PATH_INVALID"):
        import_review_rows(
            package_dir,
            rows,
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_adjudication_requires_existing_conflicting_reviews(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    rows = synthetic_review_rows(package_dir, decisions=("pass", "fail"))
    adjudication = dict(rows[0])
    adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_03",
            "round": "2",
            "review_round_type": "adjudication",
            "prior_review_visibility": "visible_for_adjudication",
            "conflict_review_ids": "review_missing_01|review_missing_02",
        }
    )
    with pytest.raises(ReviewError, match="REVIEW_REFERENCE_INVALID"):
        import_review_rows(
            package_dir,
            [*rows, adjudication],
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_adjudication_retains_independent_conflicting_reviews(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    build_review_package(
        context["glyphs"],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="fixture-seed-v1",
    )
    independent_rows = synthetic_review_rows(package_dir, decisions=("pass", "fail"))
    independent_reviews = import_review_rows(
        package_dir,
        independent_rows,
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    adjudication = dict(independent_rows[0])
    adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_03",
            "round": "2",
            "review_round_type": "adjudication",
            "prior_review_visibility": "visible_for_adjudication",
            "overall_decision": "needs_revision",
            "conflict_review_ids": "|".join(review["review_id"] for review in independent_reviews),
        }
    )
    reviews = import_review_rows(
        package_dir,
        [*independent_rows, adjudication],
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    assert len(reviews) == 3
    assert [review["overall_decision"] for review in reviews[:2]] == ["pass", "fail"]
    assert reviews[2]["conflict_review_ids"] == [review["review_id"] for review in independent_reviews]
    assert validate_review_records(reviews, ROOT / "schema/expert_review.schema.json") == []


def test_review_package_is_no_overwrite(tmp_path: Path) -> None:
    context = fixture_context()
    package_dir = tmp_path / "review-package"
    arguments = {
        "workspace_root": ROOT,
        "output_dir": package_dir,
        "created_at": "2026-09-04T00:00:00Z",
        "ordering_seed": "fixture-seed-v1",
    }
    build_review_package(context["glyphs"], context["mappings"], context["assets"], **arguments)
    with pytest.raises(FileExistsError):
        build_review_package(context["glyphs"], context["mappings"], context["assets"], **arguments)


def test_cli_validates_fixture_and_builds_review_candidate_bundle(tmp_path: Path) -> None:
    task01_root = ROOT / "data/fixtures/asset_system/reference_handoff_v1"
    common_sources = [
        "--sources",
        str(FIXTURE / "sources.jsonl"),
        "--sources",
        str(task01_root / "sources.jsonl"),
    ]
    assert han_cli(
        [
            "validate-ontology",
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--sources",
            str(FIXTURE / "sources.jsonl"),
        ]
    ) == EXIT_OK
    assert han_cli(
        [
            "validate-glyphs",
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--mappings",
            str(FIXTURE / "character_mappings.jsonl"),
            "--glyphs",
            str(FIXTURE / "glyph_instances.jsonl"),
            "--claims",
            str(FIXTURE / "claims.jsonl"),
            *common_sources,
            "--assets",
            str(task01_root / "fixture/asset_candidates.jsonl"),
            "--content-sets",
            str(ROOT / "data/fixtures/content_sets.csv"),
        ]
    ) == EXIT_OK

    package_dir = tmp_path / "review-package"
    package_command = [
        "build-review-package",
        "--glyphs",
        str(FIXTURE / "glyph_instances.jsonl"),
        "--mappings",
        str(FIXTURE / "character_mappings.jsonl"),
        "--assets",
        str(task01_root / "fixture/asset_candidates.jsonl"),
        "--output-dir",
        str(package_dir),
        "--created-at",
        "2026-09-04T00:00:00Z",
        "--ordering-seed",
        "fixture-seed-v1",
    ]
    assert han_cli(package_command) == EXIT_OK
    assert han_cli(package_command) == EXIT_NO_OVERWRITE

    submissions = tmp_path / "synthetic-reviews.csv"
    rows = synthetic_review_rows(package_dir)
    with submissions.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    reviews_path = tmp_path / "reviews.jsonl"
    assert han_cli(
        [
            "import-reviews",
            "--package-dir",
            str(package_dir),
            "--input",
            str(submissions),
            "--output",
            str(reviews_path),
        ]
    ) == EXIT_OK
    assert han_cli(
        [
            "import-reviews",
            "--package-dir",
            str(package_dir),
            "--input",
            str(submissions),
            "--output",
            str(reviews_path),
        ]
    ) == EXIT_NO_OVERWRITE

    candidate_dir = tmp_path / "candidate-bundle"
    assert han_cli(
        [
            "build-stimulus-candidates",
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--mappings",
            str(FIXTURE / "character_mappings.jsonl"),
            "--glyphs",
            str(FIXTURE / "glyph_instances.jsonl"),
            "--reviews",
            str(reviews_path),
            "--rights-evidence",
            str(task01_root / "rights_evidence.jsonl"),
            "--output-dir",
            str(candidate_dir),
            "--created-at",
            "2026-09-04T00:00:00Z",
        ]
    ) == EXIT_OK
    candidates = read_jsonl(candidate_dir / "stimulus_candidates.jsonl")
    adapters = read_jsonl(candidate_dir / "adapters.jsonl")
    assert len(candidates) == 2
    assert len(adapters) == 14
    assert json.loads((candidate_dir / "integration_requests.json").read_text(encoding="utf-8"))


def test_cli_claim_import_preserves_valid_rows_on_partial_failure(tmp_path: Path) -> None:
    input_path = tmp_path / "claims.csv"
    fieldnames = [
        "claim_id",
        "claim_domain",
        "claim_type",
        "subject_type",
        "subject_id",
        "relation",
        "object_id",
        "object_value",
        "source_id",
        "source_locator",
        "evidence_span",
        "original_language_bcp47",
        "translation_text",
        "translation_language_bcp47",
        "translation_review_status",
        "evidence_grade",
        "confidence",
        "uncertainty",
        "extraction_method",
        "verification_status",
        "human_reviewer_id",
        "stance",
    ]
    valid = {
        "claim_domain": "protocol_boundary",
        "claim_type": "object_boundary",
        "subject_type": "style_concept",
        "subject_id": "style_hs01",
        "relation": "object_boundary",
        "object_value": "fixture boundary",
        "source_id": "source_han_fixture_protocol",
        "source_locator": "fixture/row-1",
        "evidence_span": "Fixture-only protocol boundary.",
        "original_language_bcp47": "en",
        "evidence_grade": "fixture",
        "confidence": "1",
        "uncertainty": "Not historical evidence.",
        "extraction_method": "protocol_fixture",
        "verification_status": "fixture_only",
        "stance": "supports",
    }
    invalid = {**valid, "source_id": "source_missing", "source_locator": "fixture/row-2"}
    with input_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(valid)
        writer.writerow(invalid)
    output = tmp_path / "claims.jsonl"
    failures = tmp_path / "failures.jsonl"
    exit_code = han_cli(
        [
            "import-claims",
            "--input",
            str(input_path),
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--glyphs",
            str(FIXTURE / "glyph_instances.jsonl"),
            "--sources",
            str(FIXTURE / "sources.jsonl"),
            "--output",
            str(output),
            "--failure-output",
            str(failures),
        ]
    )
    assert exit_code == EXIT_RECORD_FAILURE
    assert len(read_jsonl(output)) == 1
    assert read_jsonl(failures)[0]["code"] == "CLAIM_ROW_INVALID"


def test_cli_preflights_existing_failure_output_before_record_writes(tmp_path: Path) -> None:
    input_path = tmp_path / "claims.csv"
    input_path.write_text(
        (ROOT / "data/templates/han_knowledge_claims.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output = tmp_path / "claims.jsonl"
    failures = tmp_path / "failures.jsonl"
    failures.write_text("reserved\n", encoding="utf-8")
    exit_code = han_cli(
        [
            "import-claims",
            "--input",
            str(input_path),
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--glyphs",
            str(FIXTURE / "glyph_instances.jsonl"),
            "--sources",
            str(FIXTURE / "sources.jsonl"),
            "--output",
            str(output),
            "--failure-output",
            str(failures),
        ]
    )
    assert exit_code == EXIT_NO_OVERWRITE
    assert not output.exists()
    assert failures.read_text(encoding="utf-8") == "reserved\n"


def test_handoff_dry_run_reports_fixture_boundaries(tmp_path: Path) -> None:
    summary = build_handoff_bundle(
        ROOT,
        tmp_path / "unused",
        ROOT / "configs/han_style_protocol_v1.yaml",
        implementation_commit="af3820836a6ffa92c63016b0e308f624f9b42db0",
        created_at="2026-09-04T07:00:00Z",
        dry_run=True,
    )
    assert summary["style_count"] == 8
    assert summary["review_summary"] == {
        "subject_count": 1,
        "synthetic_review_count": 2,
        "real_review_count": 0,
        "fixture_status": "passed",
        "formal_status": "blocked",
    }
    assert summary["inference_readiness"] == {
        "minimum_independent_exemplars_for_category": 3,
        "formal_pilot_candidate_count": 0,
        "task01_assigned_stimulus_count": 0,
        "instance_level_candidate_count": 2,
        "category_level_candidate_count": 0,
        "default_scope": "instance_level_only",
    }

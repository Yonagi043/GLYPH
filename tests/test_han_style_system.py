from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from glyph_features.asset_system.catalog import canonical_json, validate_record
from glyph_features.han_style_system import PROTOCOL_VERSION
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
from glyph_features.han_style_system.handoff import build_handoff_bundle, validate_handoff
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


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


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
                "reviewer_role": "history_or_paleography" if index == 1 else "type_or_visual_design",
                "review_origin": "synthetic_fixture",
                "overall_decision": decision,
                "reason_codes": "FIXTURE_ONLY|INSTANCE_LEVEL_ONLY",
                "notes": "Synthetic workflow test; not an expert conclusion.",
                "reviewed_at": f"2026-09-04T0{index}:00:00Z",
            }
        )
        for dimension in RUBRIC_DIMENSIONS:
            row[dimension] = "pass"
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


def test_protocol_version_matches_config() -> None:
    config = json.loads((ROOT / "configs/han_style_protocol_v1.yaml").read_text(encoding="utf-8"))

    assert config["protocol_version"] == f"han_style_v{PROTOCOL_VERSION}"


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


def test_claim_graph_rejects_unknown_work_object_and_human_decision() -> None:
    claim = copy.deepcopy(read_jsonl(FIXTURE / "claims.jsonl")[0])
    claim.update(
        {
            "subject_type": "work",
            "subject_id": "work_missing_01",
            "relation": "derived_from_glyph",
            "object_type": "glyph_instance",
            "object_id": "glyph_missing_01",
            "object_value": None,
            "verification_status": "human_verified",
            "human_reviewer_id": "reviewer_missing_01",
            "human_decision_id": "decision_missing_01",
            "extraction_method": "manual",
            "evidence_grade": "A",
        }
    )

    errors = validate_claims(
        [claim],
        ROOT / "schema/han_knowledge_claim.schema.json",
        style_ids={"style_hs01"},
        glyph_ids={"glyph_han_fixture_01"},
        source_ids={"source_han_fixture_protocol"},
    )

    assert any(error.startswith("HAN_CLAIM_SUBJECT_UNKNOWN") for error in errors)
    assert any(error.startswith("HAN_CLAIM_OBJECT_UNKNOWN") for error in errors)
    assert any(error.startswith("HAN_CLAIM_HUMAN_DECISION_UNKNOWN") for error in errors)


def test_claim_graph_rejects_caller_supplied_human_decision() -> None:
    claim = copy.deepcopy(read_jsonl(FIXTURE / "claims.jsonl")[0])
    claim.update(
        {
            "verification_status": "human_verified",
            "human_reviewer_id": "reviewer_self_asserted_01",
            "human_decision_id": "decision_self_asserted_01",
            "extraction_method": "manual",
            "evidence_grade": "A",
        }
    )
    evidence_sha256 = hashlib.sha256(
        canonical_json(
            {
                "source_id": claim["source_id"],
                "source_locator": claim["source_locator"],
                "evidence_span": claim["evidence_span"],
            }
        )
    ).hexdigest()

    errors = validate_claims(
        [claim],
        ROOT / "schema/han_knowledge_claim.schema.json",
        style_ids={"style_hs01"},
        glyph_ids=set(),
        source_ids={"source_han_fixture_protocol"},
        human_decisions={
            "decision_self_asserted_01": {
                "decision_id": "decision_self_asserted_01",
                "claim_id": claim["claim_id"],
                "reviewer_id": "reviewer_self_asserted_01",
                "evidence_sha256": evidence_sha256,
                "decision": "verified",
            }
        },
    )

    assert "HAN_CLAIM_HUMAN_DECISION_SOURCE_UNTRUSTED" in errors
    assert any(error.startswith("HAN_CLAIM_HUMAN_DECISION_UNKNOWN") for error in errors)


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
    assert all("INPUT_GRAPH_UNVERIFIED" in candidate["task01_freeze"]["blockers"] for candidate in candidates)

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


def test_task01_adapter_exposes_ready_freeze_request() -> None:
    context = fixture_context()
    candidate = copy.deepcopy(
        read_jsonl(FIXTURE / "reference_run_v1/candidate_bundle/stimulus_candidates.jsonl")[0]
    )
    candidate.update(
        {
            "data_origin": "source_record",
            "candidate_level": "historical_source_specimen",
            "release_status": "eligible_for_task01_freeze",
        }
    )
    candidate["task01_freeze"] = {
        "status": "ready_for_request",
        "blockers": [],
        "requested_contract": "TASK-01 stimulus freeze",
    }
    candidate["review_summary"].update(
        {"formal_status": "passed", "real_review_count": 2, "formal_policy_blockers": []}
    )
    candidate["rights_summary"]["status"] = "passed"
    candidate["mapping_status"] = "evidence_supported"

    adapters = build_adapter_records(
        context["ontology"],
        [candidate],
        schema_path=ROOT / "schema/han_adapter_record.schema.json",
    )
    task01 = next(record for record in adapters if record["target_system"] == "TASK-01")
    request = next(record for record in integration_requests(adapters) if record["target_system"] == "TASK-01")

    assert task01["status"] == "ready"
    assert task01["blocking_reasons"] == []
    assert request["status"] == "ready"


def test_task01_adapter_rejects_inconsistent_self_asserted_ready() -> None:
    context = fixture_context()
    candidate = copy.deepcopy(
        read_jsonl(FIXTURE / "reference_run_v1/candidate_bundle/stimulus_candidates.jsonl")[0]
    )
    candidate.update(
        {
            "data_origin": "source_record",
            "candidate_level": "historical_source_specimen",
            "release_status": "eligible_for_task01_freeze",
        }
    )
    candidate["task01_freeze"] = {
        "status": "ready_for_request",
        "blockers": [],
        "requested_contract": "TASK-01 stimulus freeze",
    }

    adapters = build_adapter_records(
        context["ontology"],
        [candidate],
        schema_path=ROOT / "schema/han_adapter_record.schema.json",
    )
    task01 = next(record for record in adapters if record["target_system"] == "TASK-01")
    request = next(record for record in integration_requests(adapters) if record["target_system"] == "TASK-01")

    assert task01["status"] == "blocked"
    assert "FORMAL_REVIEW_NOT_PASSED" in task01["blocking_reasons"]
    assert "FORMAL_RIGHTS_NOT_PASSED" in task01["blocking_reasons"]
    assert request["status"] == "blocked"


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


def test_same_role_all_na_reviews_cannot_satisfy_formal_policy() -> None:
    reviews = copy.deepcopy(read_jsonl(FIXTURE / "reference_run_v1/reviews.jsonl"))
    for review in reviews:
        review["review_origin"] = "real_expert"
        review["gate_approval_id"] = "approval_untrusted_01"
        review["reviewer_role"] = "type_or_visual_design"
        review["signature_sha256"] = hashlib.sha256(
            canonical_json({key: value for key, value in review.items() if key != "signature_sha256"})
        ).hexdigest()

    summary = aggregate_reviews(reviews, minimum_independent_reviews=2)["glyph_han_fixture_01"]

    assert summary["formal_status"] == "blocked"


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


def test_review_records_cannot_borrow_accepted_file_hash(tmp_path: Path) -> None:
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
        synthetic_review_rows(package_dir),
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    accepted_file = tmp_path / "accepted-reviews.jsonl"
    write_jsonl(accepted_file, reviews)
    substituted = copy.deepcopy(reviews)
    substituted[0]["notes"] = "Substituted in-memory review with a valid signature."
    substituted[0]["signature_sha256"] = hashlib.sha256(
        canonical_json(
            {key: value for key, value in substituted[0].items() if key != "signature_sha256"}
        )
    ).hexdigest()

    errors = validate_review_records(
        substituted,
        ROOT / "schema/expert_review.schema.json",
        package_dir=package_dir,
        review_records_path=accepted_file,
    )

    assert "HAN_REVIEW_RECORDS_FILE_MISMATCH" in errors


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


def test_research_local_package_is_restricted_and_unknown_rights_are_rejected(tmp_path: Path) -> None:
    context = fixture_context()
    glyph = copy.deepcopy(context["glyphs"][0])
    glyph.update(
        {
            "data_origin": "source_record",
            "acquisition_type": "historical_source",
            "rights_tier": "research_local_only",
            "release_tier": "research_local_only",
            "identity_status": "evidence_supported",
            "attribution_status": "evidence_supported",
            "structure_qc": {"status": "needs_review", "failure_codes": ["GLYPH_STRUCTURE_UNVERIFIED"]},
            "expert_review_status": "in_review",
        }
    )
    package_dir = tmp_path / "local-review-package"
    manifest = build_review_package(
        [glyph],
        context["mappings"],
        context["assets"],
        workspace_root=ROOT,
        output_dir=package_dir,
        created_at="2026-09-04T00:00:00Z",
        ordering_seed="local-fixture-seed-v1",
        access_level="research_local_only",
        access_authorization_id="fixture_local_review_authorization_v1",
        task01_handoff_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
        rights_evidence_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/rights_evidence.jsonl",
    )
    assert manifest["asset_access_level"] == "research_local_only"
    assert manifest["redistribution_status"] == "prohibited"
    assert manifest["asset_copy_policy"] == "local_review_package_only"
    assert package_dir.stat().st_mode & 0o077 == 0

    blocked = copy.deepcopy(glyph)
    blocked["glyph_instance_id"] = "glyph_blocked_rights_01"
    blocked["rights_tier"] = "blocked_unknown"
    with pytest.raises(ReviewError, match="REVIEW_ASSET_NOT_AUTHORIZED"):
        build_review_package(
            [blocked],
            context["mappings"],
            context["assets"],
            workspace_root=ROOT,
            output_dir=tmp_path / "blocked-package",
            created_at="2026-09-04T00:00:00Z",
            ordering_seed="blocked-fixture-seed-v1",
            access_level="research_local_only",
            access_authorization_id="fixture_local_review_authorization_v1",
            task01_handoff_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
            rights_evidence_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/rights_evidence.jsonl",
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
    assert reviews[2]["conflict_review_ids"] == sorted(
        review["review_id"] for review in independent_reviews
    )
    assert validate_review_records(reviews, ROOT / "schema/expert_review.schema.json") == []


def test_authorized_adjudication_resolves_conflict_without_overwriting_reviews(tmp_path: Path) -> None:
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
    independent_rows[0]["reviewer_role"] = "history_or_paleography"
    independent_rows[1]["reviewer_role"] = "type_or_visual_design"
    for row in independent_rows:
        for dimension in RUBRIC_DIMENSIONS:
            row[dimension] = "pass"
    independent = import_review_rows(
        package_dir,
        independent_rows,
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    adjudication = dict(independent_rows[0])
    adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_adjudicator_01",
            "round": "2",
            "review_round_type": "adjudication",
            "independence_attestation": "false",
            "prior_review_visibility": "visible_for_adjudication",
            "overall_decision": "needs_revision",
            "conflict_review_ids": "|".join(review["review_id"] for review in independent),
        }
    )

    reviews = import_review_rows(
        package_dir,
        [*independent_rows, adjudication],
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    summary = aggregate_reviews(reviews, minimum_independent_reviews=2)["glyph_han_fixture_01"]

    assert len(reviews) == 3
    assert summary["fixture_status"] == "needs_revision"
    assert summary["decision_counts"] == {"fail": 1, "needs_revision": 1, "pass": 1}
    assert summary["adjudication_review_ids"] == [reviews[2]["review_id"]]


def test_authorized_adjudication_supersedes_chain_uses_terminal_decision(tmp_path: Path) -> None:
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
    independent = import_review_rows(
        package_dir,
        independent_rows,
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    conflict_ids = "|".join(review["review_id"] for review in independent)
    first_adjudication = dict(independent_rows[0])
    first_adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_03",
            "round": "2",
            "review_round_type": "adjudication",
            "prior_review_visibility": "visible_for_adjudication",
            "overall_decision": "needs_revision",
            "conflict_review_ids": conflict_ids,
        }
    )
    first_round = import_review_rows(
        package_dir,
        [*independent_rows, first_adjudication],
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    second_adjudication = dict(first_adjudication)
    second_adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_adjudicator_01",
            "reviewer_role": "history_or_paleography",
            "round": "3",
            "overall_decision": "pass",
            "supersedes_review_id": first_round[2]["review_id"],
        }
    )

    reviews = import_review_rows(
        package_dir,
        [*independent_rows, first_adjudication, second_adjudication],
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    summary = aggregate_reviews(reviews, minimum_independent_reviews=2)["glyph_han_fixture_01"]

    assert summary["fixture_status"] == "passed"
    assert summary["decision_counts"] == {"fail": 1, "needs_revision": 1, "pass": 2}
    assert summary["adjudication_review_ids"] == sorted(
        [reviews[2]["review_id"], reviews[3]["review_id"]]
    )


def test_unauthorized_adjudicator_cannot_resolve_conflict(tmp_path: Path) -> None:
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
    independent = import_review_rows(
        package_dir,
        independent_rows,
        schema_path=ROOT / "schema/expert_review.schema.json",
    )
    adjudication = dict(independent_rows[0])
    adjudication.update(
        {
            "reviewer_id": "reviewer_fixture_untrusted_99",
            "round": "2",
            "review_round_type": "adjudication",
            "independence_attestation": "false",
            "prior_review_visibility": "visible_for_adjudication",
            "overall_decision": "pass",
            "conflict_review_ids": "|".join(review["review_id"] for review in independent),
        }
    )

    with pytest.raises(ReviewError, match="REVIEW_ADJUDICATOR_UNAUTHORIZED"):
        import_review_rows(
            package_dir,
            [*independent_rows, adjudication],
            schema_path=ROOT / "schema/expert_review.schema.json",
        )


def test_lineage_units_cannot_be_forged_with_cluster_ids() -> None:
    from glyph_features.han_style_system.stimuli import derive_lineage_units

    context = fixture_context()
    shared = []
    for index in range(3):
        glyph = copy.deepcopy(context["glyphs"][0])
        glyph["glyph_instance_id"] = f"glyph_shared_lineage_{index}"
        glyph["exemplar_cluster_id"] = f"cluster_claimed_independent_{index}"
        shared.append(glyph)
    shared_units = derive_lineage_units(shared)
    assert len(set(shared_units.values())) == 1

    independent = []
    for index in range(3):
        glyph = copy.deepcopy(context["glyphs"][0])
        glyph["glyph_instance_id"] = f"glyph_independent_lineage_{index}"
        glyph["exemplar_cluster_id"] = f"cluster_independent_{index}"
        glyph["work_id"] = f"work_independent_{index}"
        glyph["source_id"] = f"source_independent_{index}"
        glyph["asset_id"] = f"asset_independent_{index}"
        glyph["representation_asset_ids"] = {
            key: f"asset_{key.lower()}_{index}" for key in glyph["representation_asset_ids"]
        }
        independent.append(glyph)
    independent_units = derive_lineage_units(independent)
    assert len(set(independent_units.values())) == 3


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
            "--review-package-dir",
            str(package_dir),
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
    assert all("INPUT_GRAPH_UNVERIFIED" not in candidate["task01_freeze"]["blockers"] for candidate in candidates)
    assert json.loads((candidate_dir / "integration_requests.json").read_text(encoding="utf-8"))


def test_cli_rejects_self_asserted_formal_review_and_rights(tmp_path: Path) -> None:
    context = fixture_context()
    mappings = copy.deepcopy(context["mappings"])
    mappings[0]["mapping_status"] = "evidence_supported"
    mappings[0]["human_review_status"] = "passed"
    glyphs = copy.deepcopy(context["glyphs"])
    glyphs[0].update(
        {
            "data_origin": "source_record",
            "acquisition_type": "historical_source",
            "release_tier": "release_candidate",
            "rights_tier": "research_local_only",
            "identity_status": "evidence_supported",
            "attribution_status": "evidence_supported",
            "structure_qc": {"status": "passed", "failure_codes": []},
            "expert_review_status": "passed",
        }
    )
    reviews = copy.deepcopy(read_jsonl(FIXTURE / "reference_run_v1/reviews.jsonl"))
    for review in reviews:
        review["review_origin"] = "real_expert"
        review["gate_approval_id"] = "approval_self_asserted_01"
        review["reviewer_role"] = "type_or_visual_design"
        review["signature_sha256"] = hashlib.sha256(
            canonical_json({key: value for key, value in review.items() if key != "signature_sha256"})
        ).hexdigest()
    rights = copy.deepcopy(
        next(record for record in context["rights"] if record["source_id"] == glyphs[0]["source_id"])
    )
    rights.update(
        {
            "rights_evidence_id": "rights_self_asserted_01",
            "basis": "explicit_license",
            "license_status": "research_only",
            "rights_tier": "research_local_only",
            "permitted_uses": ["research_stimulus_local"],
            "redistribution_allowed": False,
            "decision_status": "passed",
        }
    )
    mappings_path = tmp_path / "mappings.jsonl"
    glyphs_path = tmp_path / "glyphs.jsonl"
    reviews_path = tmp_path / "reviews.jsonl"
    rights_path = tmp_path / "rights.jsonl"
    write_jsonl(mappings_path, mappings)
    write_jsonl(glyphs_path, glyphs)
    write_jsonl(reviews_path, reviews)
    write_jsonl(rights_path, [rights])
    output_dir = tmp_path / "candidate-bundle"

    exit_code = han_cli(
        [
            "build-stimulus-candidates",
            "--ontology",
            str(FIXTURE / "ontology.jsonl"),
            "--mappings",
            str(mappings_path),
            "--glyphs",
            str(glyphs_path),
            "--reviews",
            str(reviews_path),
            "--rights-evidence",
            str(rights_path),
            "--output-dir",
            str(output_dir),
            "--created-at",
            "2026-09-04T00:00:00Z",
        ]
    )
    candidates = read_jsonl(output_dir / "stimulus_candidates.jsonl") if output_dir.exists() else []

    assert exit_code != EXIT_OK or not any(
        candidate["release_status"] == "eligible_for_task01_freeze"
        or candidate["task01_freeze"]["status"] == "ready_for_request"
        for candidate in candidates
    )


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


def test_handoff_dry_run_uses_configured_review_policy(tmp_path: Path) -> None:
    config = json.loads((ROOT / "configs/han_style_protocol_v1.yaml").read_text(encoding="utf-8"))
    config["review"]["minimum_substantive_dimensions_per_review"] = 9
    config_path = tmp_path / "han_style_protocol.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    summary = build_handoff_bundle(
        ROOT,
        tmp_path / "unused",
        config_path,
        implementation_commit="af3820836a6ffa92c63016b0e308f624f9b42db0",
        created_at="2026-09-04T07:00:00Z",
        dry_run=True,
    )

    assert summary["review_summary"]["fixture_status"] == "blocked"


def test_handoff_global_gates_require_nonempty_all_candidate_pass() -> None:
    from glyph_features.han_style_system.handoff import _semantic_gate_statuses

    passed = {
        "data_origin": "source_record",
        "rights_summary": {"status": "passed"},
        "task01_freeze": {"status": "assigned"},
        "release_status": "task01_frozen",
        "stimulus_id": "stim_gate_01",
        "inference_scope": {"scope": "category_candidate"},
    }
    blocked = copy.deepcopy(passed)
    blocked.update(
        {
            "rights_summary": {"status": "blocked"},
            "task01_freeze": {"status": "blocked"},
            "release_status": "blocked",
            "stimulus_id": None,
            "inference_scope": {"scope": "instance_level_only"},
        }
    )
    reviews = {"glyph_01": {"fixture_status": "passed", "formal_status": "passed"}}

    mixed = _semantic_gate_statuses([passed, blocked], reviews)
    empty = _semantic_gate_statuses([], {})

    assert mixed["formal_asset_rights"] == "blocked"
    assert mixed["task01_stimulus_freeze"] == "blocked"
    assert mixed["category_level_inference"] == "blocked"
    assert empty["formal_expert_review"] == "blocked"
    assert empty["formal_asset_rights"] == "blocked"
    assert empty["task01_stimulus_freeze"] == "blocked"
    assert empty["category_level_inference"] == "blocked"


def test_validate_handoff_accepts_direct_schema_directory() -> None:
    exit_code = han_cli(
        [
            "validate-handoff",
            str(FIXTURE / "reference_handoff_v1/handoff_manifest.json"),
            "--workspace-root",
            str(ROOT),
            "--schema-root",
            str(ROOT / "schema"),
        ]
    )

    assert exit_code == EXIT_OK


def test_strict_handoff_recomputes_review_and_gate_truth(tmp_path: Path) -> None:
    manifest = json.loads(
        (FIXTURE / "reference_handoff_v1/handoff_manifest.json").read_text(encoding="utf-8")
    )
    manifest["review_summary"]["synthetic_review_count"] = 999
    next(
        gate for gate in manifest["quality_gates"] if gate["gate_id"] == "formal_expert_review"
    )["status"] = "passed"
    tampered = tmp_path / "handoff_manifest.json"
    tampered.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    errors = validate_handoff(tampered, ROOT)

    assert "HAN_HANDOFF_REVIEW_SUMMARY_MISMATCH" in errors
    assert "HAN_HANDOFF_GATE_TRUTH_MISMATCH gate=formal_expert_review" in errors


@pytest.mark.parametrize("forge_claim_graph", [False, True])
def test_strict_handoff_rejects_self_consistent_forged_candidate_bundle(
    forge_claim_graph: bool,
) -> None:
    def record_count(path: Path) -> int:
        if path.suffix == ".jsonl":
            return len(read_jsonl(path))
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                return len(list(csv.DictReader(handle)))
        if path.name.endswith("checksums.sha256"):
            return len([line for line in path.read_text(encoding="utf-8").splitlines() if line])
        value = json.loads(path.read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 1

    def artifact(path: Path, logical_type: str) -> dict:
        return {
            "logical_type": logical_type,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "record_count": record_count(path),
            "rights_or_privacy_level": "metadata_only",
            "schema_version": None,
            "implementation_bound": True,
        }

    with tempfile.TemporaryDirectory(prefix=".han-handoff-attack-", dir=ROOT) as temporary:
        attack_root = Path(temporary)
        candidates = copy.deepcopy(
            read_jsonl(FIXTURE / "reference_run_v1/candidate_bundle/stimulus_candidates.jsonl")
        )
        for index, candidate in enumerate(candidates, start=1):
            candidate["data_origin"] = "source_record"
            candidate["review_summary"].update(
                {
                    "real_review_count": 2,
                    "formal_status": "passed",
                    "formal_policy_blockers": [],
                }
            )
            candidate["rights_summary"]["status"] = "passed"
            candidate["task01_freeze"] = {
                "status": "assigned",
                "blockers": [],
                "requested_contract": "TASK-01 stimulus freeze",
            }
            candidate["release_status"] = "task01_frozen"
            candidate["stimulus_id"] = f"stim_attack_{index:02d}"
        candidate_path = attack_root / "stimulus_candidates.jsonl"
        write_jsonl(candidate_path, candidates)
        adapters = build_adapter_records(
            read_jsonl(FIXTURE / "ontology.jsonl"),
            candidates,
            schema_path=str(ROOT / "schema/han_adapter_record.schema.json"),
        )
        adapter_path = attack_root / "adapters.jsonl"
        write_jsonl(adapter_path, adapters)
        request_path = attack_root / "integration_requests.json"
        request_path.write_text(
            json.dumps(integration_requests(adapters), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        claim_path = FIXTURE / "claims.jsonl"
        if forge_claim_graph:
            claims = copy.deepcopy(read_jsonl(claim_path))
            claims[0].update(
                {
                    "subject_type": "work",
                    "subject_id": "work_self_asserted_01",
                    "relation": "derived_from_glyph",
                    "object_type": "glyph_instance",
                    "object_id": "glyph_self_asserted_01",
                    "object_value": None,
                }
            )
            claim_path = attack_root / "claims.jsonl"
            write_jsonl(claim_path, claims)

        output_specs = [
            (FIXTURE / "ontology.jsonl", "style_ontology"),
            (FIXTURE / "character_mappings.jsonl", "character_mapping"),
            (FIXTURE / "glyph_instances.jsonl", "glyph_instance"),
            (claim_path, "knowledge_claim"),
            (FIXTURE / "sources.jsonl", "source_catalog"),
            (FIXTURE / "reference_run_v1/reviews.jsonl", "expert_review"),
            (FIXTURE / "reference_run_v1/review_package/package_manifest.json", "review_package_manifest"),
            (candidate_path, "stimulus_candidate"),
            (adapter_path, "adapter_record"),
            (request_path, "integration_requests"),
        ]
        outputs = [artifact(path, logical_type) for path, logical_type in output_specs]
        checksum_path = attack_root / "checksums.sha256"
        checksum_path.write_text(
            "".join(f"{item['sha256']}  {item['path']}\n" for item in outputs),
            encoding="utf-8",
        )
        outputs.append(artifact(checksum_path, "checksums"))
        input_specs = [
            (ROOT / "data/fixtures/content_sets.csv", "content_set"),
            (ROOT / "configs/han_style_protocol_v1.yaml", "han_style_config"),
            (ROOT / "configs/han_style_trust_root_v1.json", "han_style_trust_root"),
            (ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json", "task01_handoff"),
            (ROOT / "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl", "task01_fixture_assets"),
            (ROOT / "data/fixtures/asset_system/reference_handoff_v1/rights_evidence.jsonl", "task01_rights_evidence"),
            (ROOT / "data/fixtures/asset_system/reference_handoff_v1/sources.jsonl", "task01_source_catalog"),
        ]
        manifest = {
            "readiness": {
                "engineering_ready": True,
                "pilot_ready": True,
                "research_validated": False,
            },
            "input_snapshots": [artifact(path, logical_type) for path, logical_type in input_specs],
            "outputs": outputs,
            "review_summary": {
                "subject_count": 1,
                "synthetic_review_count": 2,
                "real_review_count": 2,
                "fixture_status": "passed",
                "formal_status": "passed",
            },
            "inference_readiness": {
                "minimum_independent_exemplars_for_category": 3,
                "formal_pilot_candidate_count": 0,
                "task01_assigned_stimulus_count": 2,
                "instance_level_candidate_count": 2,
                "category_level_candidate_count": 0,
                "default_scope": "instance_level_only",
            },
            "quality_gates": [
                {"gate_id": "schema_and_hash_validation", "status": "passed", "evidence": outputs[0]["path"]},
                {"gate_id": "synthetic_double_review", "status": "fixture_only", "evidence": candidate_path.relative_to(ROOT).as_posix()},
                {"gate_id": "formal_expert_review", "status": "passed", "evidence": candidate_path.relative_to(ROOT).as_posix()},
                {"gate_id": "formal_asset_rights", "status": "passed", "evidence": candidate_path.relative_to(ROOT).as_posix()},
                {"gate_id": "restricted_terms", "status": "blocked", "evidence": candidate_path.relative_to(ROOT).as_posix()},
                {"gate_id": "task01_stimulus_freeze", "status": "passed", "evidence": candidate_path.relative_to(ROOT).as_posix()},
                {"gate_id": "category_level_inference", "status": "blocked", "evidence": candidate_path.relative_to(ROOT).as_posix()},
            ],
            "blocked_human_gates": [],
            "next_task_entrypoints": [],
        }
        manifest_path = attack_root / "handoff_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        errors = validate_handoff(manifest_path, ROOT)

        assert not any(error.startswith("HAN_HANDOFF_HASH_MISMATCH") for error in errors)
        assert "HAN_HANDOFF_CHECKSUM_SET_MISMATCH" not in errors
        if forge_claim_graph:
            assert any(error.startswith("HAN_CLAIM_SUBJECT_UNKNOWN") for error in errors)
            assert any(error.startswith("HAN_CLAIM_OBJECT_UNKNOWN") for error in errors)
            assert any(error.startswith("HAN_HANDOFF_SEMANTIC_REBUILD_FAILED") for error in errors)
        else:
            assert "HAN_HANDOFF_CANDIDATE_SEMANTICS_MISMATCH" in errors
            assert "HAN_HANDOFF_ADAPTER_SEMANTICS_MISMATCH" in errors
            assert "HAN_HANDOFF_INTEGRATION_REQUESTS_MISMATCH" in errors
            assert "HAN_HANDOFF_REVIEW_SUMMARY_MISMATCH" in errors
            assert "HAN_HANDOFF_GATE_TRUTH_MISMATCH gate=formal_asset_rights" in errors
            assert "HAN_HANDOFF_GATE_TRUTH_MISMATCH gate=task01_stimulus_freeze" in errors
            assert "HAN_HANDOFF_READINESS_UNTRUTHFUL" in errors

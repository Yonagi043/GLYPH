from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.asset_system.catalog import validate_record
from glyph_features.experiment_system.assignment import audit_assignments, build_assignments
from glyph_features.experiment_system.export import (
    ExportBlocked,
    read_and_validate_export,
    require_export_eligible,
    write_deidentified_export,
)
from glyph_features.experiment_system.fixtures import build_synthetic_catalog, load_task01_fixture
from glyph_features.experiment_system import handoff as handoff_module
from glyph_features.experiment_system.handoff import _contains_absolute_path
from glyph_features.experiment_system.schema import canonical_sha256, validate_contract_set
from glyph_features.experiment_system.storage import ExperimentStore, StoreError
from glyph_features.experiment_system.quality import audit_exclusion_parity, build_quality_decision
from glyph_features.experiment_system.power import power_scenarios
from glyph_features.experiment_system.web import create_app
from glyph_features.experiment_system.cli import (
    EXIT_NO_OVERWRITE,
    EXIT_OK,
    EXIT_OPERATION,
    EXIT_VALIDATION,
    main as experiment_cli,
)


ROOT = Path(__file__).parents[1]
STUDY_ID = "study_cross_cultural_v1"


def rating_record() -> dict:
    return {
        "schema_version": "2.0.0",
        "rating_id": "rating_fixture_001",
        "study_id": "study_cross_cultural_v1",
        "questionnaire_version": "1.0.0",
        "assignment_id": "assignment_fixture_001",
        "block_id": "block_fixture_001",
        "presentation_id": "presentation_fixture_001",
        "stimulus_id": "stim_fixture_001",
        "participant_id": "synp_fixture_001",
        "data_origin": "synthetic",
        "respondent_language_bcp47": "zh-Hans",
        "native_scripts": ["han", "latin"],
        "item_id": "item_aesthetic",
        "construct": "aesthetic",
        "rating_scale": "likert_1_7",
        "response": {"value": 5, "missing_reason": None},
        "displayed_asset_sha256": "a" * 64,
        "trial_index": 1,
        "response_time_ms": 1800,
        "attention_check": None,
        "quality": {
            "rule_version": "1.0.0",
            "exclude_from_analysis": False,
            "reason_codes": [],
        },
        "collected_at": "2026-09-04T00:00:00Z",
    }


def test_rating_v2_keeps_v1_compatible_and_fixes_scale_range() -> None:
    old_record = {
        "rating_id": "rating_demo_001",
        "study_id": "study_pilot_001",
        "stimulus_id": "stim_demo_001",
        "participant_id": "p_demo_001",
        "trial_index": 1,
        "respondent_language_bcp47": "zh",
        "native_script": "han",
        "rating_scale": "likert_1_7",
        "ratings": {"aesthetic": 5},
        "attention_check_passed": True,
        "collected_at": "2026-08-29T00:00:00Z",
    }
    assert validate_record(old_record, ROOT / "schema/human_rating.schema.json") == []

    record = rating_record()
    assert validate_record(record, ROOT / "schema/experiment_rating.schema.json") == []
    record["response"]["value"] = 8
    assert validate_record(record, ROOT / "schema/experiment_rating.schema.json")


def test_rating_v2_rejects_pii_persona_and_ambiguous_missing_values() -> None:
    for key, value in (("email", "fixture@example.invalid"), ("ip_address", "192.0.2.1")):
        record = rating_record()
        record[key] = value
        assert validate_record(record, ROOT / "schema/experiment_rating.schema.json")

    persona = rating_record()
    persona["data_origin"] = "persona"
    assert validate_record(persona, ROOT / "schema/experiment_rating.schema.json")

    missing = rating_record()
    missing["response"] = {"value": None, "missing_reason": None}
    assert validate_record(missing, ROOT / "schema/experiment_rating.schema.json")


def test_synthetic_records_are_mechanically_blocked_from_formal_use() -> None:
    record = rating_record()
    require_export_eligible([record], purpose="engineering_fixture")
    for purpose in ("formal_analysis", "release"):
        with pytest.raises(ExportBlocked) as caught:
            require_export_eligible([copy.deepcopy(record)], purpose=purpose)
        assert caught.value.code == "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN"


def contract_records() -> tuple[dict, dict, dict, dict]:
    protocol = {
        "schema_version": "1.0.0",
        "study_id": "study_cross_cultural_v1",
        "protocol_version": "1.0.0",
        "title": "Synthetic cross-cultural engineering study",
        "status": "engineering_fixture_frozen",
        "synthetic_only": True,
        "research_questions": ["Do ratings interact with native and stimulus scripts?"],
        "hypotheses": [{"hypothesis_id": "H1", "statement": "An interaction may exist.", "estimand": "native-script by stimulus-script interaction", "analysis_class": "confirmatory"}],
        "design": {"presentation_condition": "visual_blind", "target_script_groups": ["latin", "han", "kana", "hangul"], "block_size": 8, "anchor_count": 1, "max_consecutive_same_script": 1},
        "outcomes": {"primary": ["aesthetic", "premium"], "secondary": ["visual_clarity", "recognition"]},
        "sampling_plan": {"quota_basis": "self_reported_native_scripts_not_nationality", "power_scenarios": [{"standardized_effect": effect, "participant_icc": 0.2, "stimulus_icc": 0.2} for effect in (0.1, 0.2, 0.3)], "sample_size_status": "scenario_only_pending_participant_gate"},
        "randomization": {"algorithm": "balanced_incomplete_block_v1", "seed_namespace": "fixture-seed", "balance_tolerance": 1, "resume_policy": "persist_assignment_and_resume_next_unsubmitted_presentation"},
        "exclusion_rules": {"version": "1.0.0", "rules": [{"code": "CONSENT_MISSING", "criterion": "Consent is absent.", "action": "flag_preserve_raw"}], "outcome_blind": True},
        "analysis_plan": {"primary_model": "ordinal_mixed_effects", "participant_effect": "random_intercept", "stimulus_effect": "random_intercept", "interaction": "native_script_x_stimulus_script", "multiple_comparisons": "Holm within outcome family", "missingness": "preserve_reason_never_zero_impute", "confirmatory_frozen": True},
        "measurement_invariance": {"required_before_cross_language_comparison": True, "sequence": ["configural", "metric", "scalar"], "current_status": "not_tested_no_real_participants"},
        "human_gates": {"GATE-ETHICS": "blocked", "GATE-PARTICIPANTS": "blocked", "GATE-TRANSLATION": "blocked"},
        "created_at": "2026-09-04T00:00:00Z",
    }
    modules = [
        "information_consent", "eligibility", "language_scripts", "training_exposure", "device_practice",
        "visual_ratings", "recognition", "quality", "optional_feedback", "completion_withdrawal",
    ]
    questionnaire = {
        "schema_version": "1.0.0",
        "study_id": protocol["study_id"],
        "questionnaire_version": "1.0.0",
        "source_language": "zh-Hans",
        "supported_languages": ["zh-Hans", "en", "ja", "ko"],
        "status": "draft_unreviewed",
        "modules": modules,
        "scale_definitions": {
            "likert_1_7": {
                "minimum": 1,
                "maximum": 7,
                "missing_codes": ["not_applicable", "refused"],
                "anchors": {
                    language: {"low": "low", "mid": "mid", "high": "high", "not_applicable": "not applicable", "refused": "refused"}
                    for language in ("zh-Hans", "en", "ja", "ko")
                },
            }
        },
        "items": [{
            "item_id": "item_aesthetic",
            "module": "visual_ratings",
            "construct": "aesthetic",
            "response_type": "likert_1_7",
            "option_set": "rating_1_7_na",
            "required": True,
            "translations": {
                language: {"text": text, "review_status": status}
                for language, text, status in (
                    ("zh-Hans", "整体上，这个视觉形式美观吗？", "source_draft"),
                    ("en", "Overall, is this visual form aesthetically pleasing?", "translated_draft_unreviewed"),
                    ("ja", "全体として、この視覚形式は美しいですか。", "translated_draft_unreviewed"),
                    ("ko", "전반적으로 이 시각적 형태가 아름답습니까?", "translated_draft_unreviewed"),
                )
            },
        }],
        "translation_workflow": {"machine_translation_claimed_reviewed": False, "back_translation": "not_started", "committee_review": "not_started", "cognitive_interviews": "not_started", "change_policy": "wording_change_requires_new_questionnaire_version"},
    }
    participant = {
        "schema_version": "1.0.0",
        "study_id": protocol["study_id"],
        "participant_id": "synp_fixture_001",
        "data_origin": "synthetic",
        "questionnaire_language": "zh-Hans",
        "mother_tongues": [{"bcp47": "zh-Hans", "dominance": "primary"}, {"bcp47": "en", "dominance": "additional"}],
        "native_scripts": ["han", "latin"],
        "script_proficiencies": [{"script": script, "reading": 5, "writing": 4, "exposure_frequency": 5} for script in ("latin", "han", "kana", "hangul")],
        "region_category": "east_asia",
        "cross_cultural_exposure": "moderate",
        "training": {"design": "none", "typography": "none", "calligraphy": "none"},
        "age_band": "25_34",
        "education_level": "undergraduate",
        "language_understood": True,
        "created_at": "2026-09-04T00:00:00Z",
    }
    consent = {
        "schema_version": "1.0.0",
        "study_id": protocol["study_id"],
        "participant_id": participant["participant_id"],
        "data_origin": "synthetic",
        "consent_version": "1.0.0",
        "status": "consented",
        "age_eligible": True,
        "recorded_at": "2026-09-04T00:00:00Z",
    }
    return protocol, questionnaire, participant, consent


def test_protocol_questionnaire_participant_and_consent_contracts() -> None:
    records = contract_records()
    assert validate_contract_set(*records) == []
    assert canonical_sha256(records[1]) == canonical_sha256(copy.deepcopy(records[1]))

    broken = copy.deepcopy(records)
    broken[1]["supported_languages"].remove("ko")
    assert "questionnaire: LANGUAGE_SET_INCOMPLETE" in validate_contract_set(*broken)

    pii = copy.deepcopy(records)
    pii[2]["email"] = "fixture@example.invalid"
    assert any("participant" in error and "email" in error for error in validate_contract_set(*pii))


def synthetic_catalog() -> list[dict]:
    asset = {
        "path": "data/fixtures/asset_system/reference_handoff_v1/fixture/derived/asset_c7e16ea61e90d876c6fe05b9.B_shape.png",
        "sha256": "578e75ef3abe8d182efce7c9b8445fedc673eeef74397fe0f23c04ecc309199b",
        "mime_type": "image/png",
        "byte_size": 10819,
    }
    return [
        {
            "stimulus_id": f"stim_task03_{script}_{index:02d}",
            "source_stimulus_id": "stim_eco_ed82ad5985adf0287b9a",
            "work_id": f"work_task03_{script}_{index:02d}",
            "writing_system": script,
            "is_anchor": index == 1,
            "asset": asset,
            "rights_tier": "open",
            "release_status": "fixture_only",
            "blind_metadata": {"award_hidden": True, "source_hidden": True, "brand_hidden": True, "filename_hidden": True},
            "data_origin": "synthetic",
        }
        for script in ("latin", "han", "kana", "hangul")
        for index in range(1, 5)
    ]


def synthetic_participants(count: int = 1000) -> list[dict[str, str]]:
    groups = ("latin", "han", "kana", "hangul")
    return [
        {"participant_id": f"synp_{index:04d}", "participant_group": groups[index % 4], "data_origin": "synthetic"}
        for index in range(count)
    ]


def test_balanced_incomplete_blocks_cover_1000_synthetic_participants() -> None:
    stimuli = synthetic_catalog()
    first = build_assignments(
        synthetic_participants(), stimuli, study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="task03-fixture-seed"
    )
    repeated = build_assignments(
        synthetic_participants(), stimuli, study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="task03-fixture-seed"
    )
    alternative = build_assignments(
        synthetic_participants(), stimuli, study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="task03-alternative-seed"
    )
    audit = audit_assignments(first, stimuli, block_size=8, balance_tolerance=1)
    alternative_audit = audit_assignments(alternative, stimuli, block_size=8, balance_tolerance=1)
    assert audit["valid"], audit["errors"]
    assert audit["assignment_count"] == 1000
    assert audit["trial_count"] == audit["unique_presentation_count"] == 8000
    assert audit["max_group_stimulus_exposure_spread"] <= 1
    assert audit["max_stimulus_position_spread"] <= 1
    assert all(sum(bool(trial["is_anchor"]) for trial in assignment["trials"]) == 2 for assignment in first)
    assert first == repeated
    assert audit["summary_sha256"] != alternative_audit["summary_sha256"]
    assert alternative_audit["valid"], alternative_audit["errors"]
    assert validate_record(first[0], ROOT / "schema/experiment_assignment.schema.json") == []

    position_broken = copy.deepcopy(first)
    target_stimulus = stimuli[0]["stimulus_id"]
    for assignment in position_broken:
        for trial in assignment["trials"]:
            if trial["stimulus_id"] == target_stimulus:
                trial["trial_index"] = 1
    broken_audit = audit_assignments(position_broken, stimuli, block_size=8, balance_tolerance=1)
    assert any(error.startswith("POSITION_IMBALANCE:") for error in broken_audit["errors"])

    unknown_stimulus = copy.deepcopy(first)
    unknown_stimulus[0]["trials"][0]["stimulus_id"] = "stim_task03_unknown_01"
    unknown_audit = audit_assignments(unknown_stimulus, stimuli, block_size=8, balance_tolerance=1)
    assert any(error.startswith("UNKNOWN_STIMULUS:") for error in unknown_audit["errors"])

    spoofed_metadata = copy.deepcopy(first)
    spoofed_metadata[0]["trials"][0]["asset_sha256"] = "0" * 64
    metadata_audit = audit_assignments(spoofed_metadata, stimuli, block_size=8, balance_tolerance=1)
    assert any(error.endswith(":asset_sha256") for error in metadata_audit["errors"])


def test_assignment_never_repeats_a_work_within_a_block() -> None:
    stimuli = synthetic_catalog()
    stimuli[1]["work_id"] = stimuli[0]["work_id"]
    assignments = build_assignments(
        synthetic_participants(32), stimuli, study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="work-constraint"
    )
    assert all(len({trial["work_id"] for trial in row["trials"]}) == 8 for row in assignments)


def test_task01_fixture_intake_is_strict_and_catalog_is_synthetic_only() -> None:
    upstream = load_task01_fixture()
    assert upstream["manifest_sha256"] == "acc193134495401b9a026aab0e7a866d7f15202b9b865db0d73d6f689bd1bdab"
    assert upstream["stimulus"]["stimulus_id"] == "stim_eco_ed82ad5985adf0287b9a"
    catalog = build_synthetic_catalog()
    assert len(catalog["items"]) == 16
    assert {item["writing_system"] for item in catalog["items"]} == {"latin", "han", "kana", "hangul"}
    assert {item["data_origin"] for item in catalog["items"]} == {"synthetic"}
    assert {item["release_status"] for item in catalog["items"]} == {"fixture_only"}


def test_frozen_study_protocol_validates() -> None:
    protocol = __import__("json").loads((ROOT / "configs/cross_cultural_study_v1.json").read_text(encoding="utf-8"))
    assert validate_record(protocol, ROOT / "schema/study_protocol.schema.json") == []
    assert protocol["synthetic_only"] is True
    assert set(protocol["human_gates"].values()) == {"blocked"}


def test_four_language_questionnaire_is_complete_and_unreviewed() -> None:
    questionnaire = __import__("json").loads((ROOT / "configs/questionnaire_v1.json").read_text(encoding="utf-8"))
    assert validate_record(questionnaire, ROOT / "schema/questionnaire_definition.schema.json") == []
    assert set(questionnaire["supported_languages"]) == {"zh-Hans", "en", "ja", "ko"}
    assert len(questionnaire["modules"]) == 10
    assert len({item["item_id"] for item in questionnaire["items"]}) == len(questionnaire["items"])
    for item in questionnaire["items"]:
        assert set(item["translations"]) == {"zh-Hans", "en", "ja", "ko"}
        assert item["translations"]["zh-Hans"]["review_status"] == "source_draft"
        assert all(
            item["translations"][language]["review_status"] == "translated_draft_unreviewed"
            for language in ("en", "ja", "ko")
        )


def trial_submission(
    assignment: dict,
    *,
    request_id: str = "request_fixture_001",
    trial_offset: int = 0,
) -> tuple[dict, list[dict]]:
    trial = assignment["trials"][trial_offset]
    event = {
        "schema_version": "1.0.0",
        "event_id": "event_fixture_001",
        "request_id": request_id,
        "study_id": assignment["study_id"],
        "assignment_id": assignment["assignment_id"],
        "presentation_id": trial["presentation_id"],
        "participant_id": assignment["participant_id"],
        "data_origin": assignment["data_origin"],
        "stimulus_id": trial["stimulus_id"],
        "expected_asset_sha256": trial["asset_sha256"],
        "displayed_asset_sha256": trial["asset_sha256"],
        "load_status": "loaded",
        "trial_index": trial["trial_index"],
        "started_at": "2026-09-04T00:00:00Z",
        "ended_at": "2026-09-04T00:00:02Z",
        "preload_ms": 12,
        "response_ms": 1800,
        "viewport": {"css_width": 1280, "css_height": 800, "stimulus_css_width": 512, "stimulus_css_height": 512, "device_pixel_ratio": 2},
        "focus_loss_count": 0,
        "zoom_anomaly": False,
        "quality_signals": [],
    }
    rating = rating_record()
    rating.update({
        "rating_id": f"rating_{trial['presentation_id'][-12:]}",
        "assignment_id": assignment["assignment_id"],
        "block_id": assignment["block_id"],
        "presentation_id": trial["presentation_id"],
        "stimulus_id": trial["stimulus_id"],
        "participant_id": assignment["participant_id"],
        "data_origin": assignment["data_origin"],
        "displayed_asset_sha256": trial["asset_sha256"],
        "trial_index": trial["trial_index"],
    })
    return event, [rating]


def test_store_persists_assignment_and_idempotent_concurrent_submission(tmp_path: Path) -> None:
    assignment = build_assignments(
        synthetic_participants(1), synthetic_catalog(), study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="store-test"
    )[0]
    database = tmp_path / "restricted" / "experiment.sqlite3"
    store = ExperimentStore(database)
    _, created = store.save_assignment(assignment)
    assert created
    persisted, created_again = ExperimentStore(database).save_assignment(copy.deepcopy(assignment))
    assert not created_again
    assert persisted == assignment

    event, ratings = trial_submission(assignment)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: ExperimentStore(database).submit_trial(event, ratings), range(8)))
    assert [result["status"] for result in results].count("accepted") == 1
    assert [result["status"] for result in results].count("duplicate") == 7
    assert store.counts() == {"assignments": 1, "presentations": 1, "ratings": 1}
    assert ExperimentStore(database).assignment_for(assignment["participant_id"])["resume_next_trial"] == 2


def test_store_rejects_conflicting_retry_and_unverified_asset(tmp_path: Path) -> None:
    assignment = build_assignments(
        synthetic_participants(1), synthetic_catalog(), study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="store-conflict"
    )[0]
    store = ExperimentStore(tmp_path / "experiment.sqlite3")
    store.save_assignment(assignment)
    event, ratings = trial_submission(assignment)
    store.submit_trial(event, ratings)

    conflict = copy.deepcopy(event)
    conflict["response_ms"] += 1
    with pytest.raises(StoreError) as caught:
        store.submit_trial(conflict, ratings)
    assert caught.value.code == "REQUEST_ID_CONFLICT"

    second_event, second_ratings = trial_submission(
        assignment,
        request_id="request_fixture_second_trial",
        trial_offset=1,
    )
    second_ratings[0]["rating_id"] = ratings[0]["rating_id"]
    with pytest.raises(StoreError) as caught:
        store.submit_trial(second_event, second_ratings)
    assert caught.value.code == "RATING_ID_CONFLICT"

    second_assignment = build_assignments(
        synthetic_participants(1), synthetic_catalog(), study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="store-hash"
    )[0]
    second_store = ExperimentStore(tmp_path / "second.sqlite3")
    second_store.save_assignment(second_assignment)
    bad_event, bad_ratings = trial_submission(second_assignment, request_id="request_fixture_002")
    bad_event["displayed_asset_sha256"] = "0" * 64
    with pytest.raises(StoreError) as caught:
        second_store.submit_trial(bad_event, bad_ratings)
    assert caught.value.code == "DISPLAY_ASSET_NOT_VERIFIED"


def test_store_persists_synthetic_mode_and_rejects_real_or_questionnaire_spoofing(tmp_path: Path) -> None:
    assignment = build_assignments(
        synthetic_participants(1), synthetic_catalog(), study_id="study_cross_cultural_v1", questionnaire_version="1.0.0", seed="store-lock"
    )[0]
    store = ExperimentStore(tmp_path / "experiment.sqlite3")
    assert store.system_status() == {
        "synthetic_only": True,
        "study_id": STUDY_ID,
        "questionnaire_version": "1.0.0",
    }

    real_assignment = copy.deepcopy(assignment)
    real_assignment["participant_id"] = "p_fixture_001"
    real_assignment["data_origin"] = "real"
    with pytest.raises(StoreError) as caught:
        store.save_assignment(real_assignment)
    assert caught.value.code == "REAL_COLLECTION_LOCKED"

    wrong_study = copy.deepcopy(assignment)
    wrong_study["study_id"] = "study_other"
    with pytest.raises(StoreError) as caught:
        store.save_assignment(wrong_study)
    assert caught.value.code == "STUDY_ID_MISMATCH"

    unknown_stimulus = copy.deepcopy(assignment)
    unknown_stimulus["trials"][0]["stimulus_id"] = "stim_task03_unknown_01"
    with pytest.raises(StoreError) as caught:
        store.save_assignment(unknown_stimulus)
    assert caught.value.code == "ASSIGNMENT_STIMULUS_NOT_IN_CATALOG"

    spoofed_asset = copy.deepcopy(assignment)
    spoofed_asset["trials"][0]["asset_sha256"] = "0" * 64
    with pytest.raises(StoreError) as caught:
        store.save_assignment(spoofed_asset)
    assert caught.value.code == "ASSIGNMENT_CATALOG_MISMATCH"

    store.save_assignment(assignment)
    event, ratings = trial_submission(assignment)
    real_event = copy.deepcopy(event)
    real_event["data_origin"] = "real"
    with pytest.raises(StoreError) as caught:
        store.submit_trial(real_event, ratings)
    assert caught.value.code == "REAL_COLLECTION_LOCKED"

    wrong_construct = copy.deepcopy(ratings)
    wrong_construct[0]["construct"] = "premium"
    with pytest.raises(StoreError) as caught:
        store.submit_trial(event, wrong_construct)
    assert caught.value.code == "QUESTIONNAIRE_CONSTRUCT_MISMATCH"


def test_quality_decisions_are_versioned_and_group_rates_are_audited() -> None:
    _, _, participant, consent = contract_records()
    decision = build_quality_decision(participant, consent, [], [], decided_at="2026-09-04T00:00:00Z")
    assert decision["exclude_from_analysis"] is True
    assert decision["reason_codes"] == ["INCOMPLETE"]
    revised = build_quality_decision(
        participant, consent, [], [], previous_decision_id=decision["decision_id"], decided_at="2026-09-04T00:01:00Z"
    )
    assert revised["previous_decision_id"] == decision["decision_id"]
    second = copy.deepcopy(decision)
    second["participant_id"] = "synp_fixture_002"
    second["exclude_from_analysis"] = False
    second["reason_codes"] = []
    parity = audit_exclusion_parity(
        [decision, second], {"synp_fixture_001": "han", "synp_fixture_002": "latin"}
    )
    assert parity["warning"] == "GROUP_EXCLUSION_RATE_DIFFERENCE"


def test_deidentified_export_preserves_missingness_and_blocks_formal_use(tmp_path: Path) -> None:
    record = rating_record()
    record["response"] = {"value": None, "missing_reason": "not_applicable"}
    output = tmp_path / "exports" / "ratings.jsonl"
    summary = write_deidentified_export([record], output, purpose="engineering_fixture")
    assert summary["record_count"] == 1
    restored = read_and_validate_export(output, purpose="engineering_fixture")
    assert restored[0]["response"] == {"value": None, "missing_reason": "not_applicable"}
    for purpose in ("formal_analysis", "release"):
        with pytest.raises(ExportBlocked) as read_caught:
            read_and_validate_export(output, purpose=purpose)
        assert read_caught.value.code == "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN"
    with pytest.raises(ExportBlocked) as caught:
        write_deidentified_export(
            [record], tmp_path / "formal.jsonl", purpose="formal_analysis", human_gates={gate: "passed" for gate in ("GATE-ETHICS", "GATE-PARTICIPANTS", "GATE-TRANSLATION")}
        )
    assert caught.value.code == "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN"


def test_power_scenarios_are_explicit_assumptions_not_approved_effects() -> None:
    protocol = __import__("json").loads((ROOT / "configs/cross_cultural_study_v1.json").read_text(encoding="utf-8"))
    report = power_scenarios(protocol)
    assert report["status"] == "planning_scenarios_not_approved_sample_size"
    assert report["scenario_total_range"][0] > 0
    low_effect = next(row for row in report["scenarios"] if row["standardized_effect"] == 0.1)
    high_effect = next(row for row in report["scenarios"] if row["standardized_effect"] == 0.3)
    assert low_effect["required_total_approx"] > high_effect["required_total_approx"]


def test_synthetic_web_api_hides_metadata_and_verifies_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "experiment.sqlite3", study_id=STUDY_ID))
    index = client.get("/")
    assert index.status_code == 200
    assert "SYNTHETIC ONLY" in index.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    status = client.get("/api/status").json()
    assert status["synthetic_only"] is True
    assert status["database_mode"] == {
        "synthetic_only": True,
        "study_id": STUDY_ID,
        "questionnaire_version": "1.0.0",
    }
    assert status["real_collection_locked"] is True
    assert status["formal_stimulus_entrypoint"] == "blocked"
    practice = client.get("/api/practice")
    assert practice.status_code == 200
    assert not ({"asset_path", "writing_system", "work_id", "source_stimulus_id"} & set(practice.json()))
    practice_asset = client.get(practice.json()["asset_url"])
    assert __import__("hashlib").sha256(practice_asset.content).hexdigest() == practice.json()["expected_asset_sha256"]
    response = client.post(
        "/api/session",
        json={"language": "en", "native_scripts": ["latin"], "session_nonce": "browserfixture01"},
    )
    assert response.status_code == 200
    spoofed = client.post(
        "/api/session",
        json={"language": "en", "native_scripts": ["latin"], "session_nonce": "browserfixture02", "data_origin": "real"},
    )
    assert spoofed.status_code == 422
    session = response.json()
    assert len(session["trials"]) == 8
    assert not ({"asset_path", "writing_system", "work_id", "source_stimulus_id"} & set(session["trials"][0]))
    asset_response = client.get(session["trials"][0]["asset_url"])
    assert asset_response.status_code == 200
    assert __import__("hashlib").sha256(asset_response.content).hexdigest() == session["trials"][0]["expected_asset_sha256"]
    resumed = client.get(f"/api/session/{session['participant_id']}")
    assert resumed.status_code == 200
    assert resumed.json()["assignment_id"] == session["assignment_id"]


def test_cli_validates_study_and_runs_1000_participant_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert experiment_cli(["validate-study"]) == EXIT_OK
    validation = __import__("json").loads(capsys.readouterr().out)
    assert validation["valid"] is True
    assert validation["language_count"] == 4

    report_path = tmp_path / "dry-run.json"
    assert experiment_cli(["synthetic-dry-run", "--participants", "1000", "--output", str(report_path)]) == EXIT_OK
    dry_run = __import__("json").loads(capsys.readouterr().out)
    assert dry_run["simulated_response_count"] == 8000
    assert dry_run["lost_trial_count"] == dry_run["duplicate_response_count"] == 0
    assert dry_run["formal_analysis_allowed"] is False
    assert experiment_cli(["synthetic-dry-run", "--output", str(report_path)]) == EXIT_NO_OVERWRITE
    capsys.readouterr()


def test_cli_builds_and_audits_blocks_and_keeps_real_collection_locked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "blocks"
    assert experiment_cli(["build-blocks", "--study-id", STUDY_ID, "--participants", "32", "--output-dir", str(output)]) == EXIT_OK
    capsys.readouterr()
    assert experiment_cli([
        "audit-assignments",
        "--study-id", STUDY_ID,
        "--assignments", str(output / "assignments.jsonl"),
        "--catalog", str(output / "stimulus_catalog.json"),
    ]) == EXIT_OK
    audit = __import__("json").loads(capsys.readouterr().out)
    assert audit["valid"] is True
    wrong_catalog = __import__("json").loads((output / "stimulus_catalog.json").read_text(encoding="utf-8"))
    wrong_catalog["study_id"] = "study_other"
    wrong_catalog_path = tmp_path / "wrong-catalog.json"
    wrong_catalog_path.write_text(__import__("json").dumps(wrong_catalog), encoding="utf-8")
    assert experiment_cli([
        "audit-assignments",
        "--study-id", STUDY_ID,
        "--assignments", str(output / "assignments.jsonl"),
        "--catalog", str(wrong_catalog_path),
    ]) == EXIT_VALIDATION
    mismatched = __import__("json").loads(capsys.readouterr().out)
    assert any(error.startswith("STUDY_ID_MISMATCH:catalog:") for error in mismatched["errors"])
    assert experiment_cli(["build-blocks", "--study-id", STUDY_ID, "--participants", "32", "--output-dir", str(output)]) == EXIT_NO_OVERWRITE
    capsys.readouterr()
    assert experiment_cli(["serve", "--study-id", STUDY_ID]) == EXIT_OPERATION
    locked = __import__("json").loads(capsys.readouterr().err)
    assert locked["code"] == "REAL_COLLECTION_LOCKED"


@pytest.mark.parametrize(
    "arguments",
    [
        ["build-blocks", "--output-dir", "unused"],
        ["audit-assignments", "--assignments", "unused", "--catalog", "unused"],
        ["serve"],
        ["export", "--output", "unused", "--purpose", "engineering_fixture", "--deidentified"],
    ],
)
def test_study_scoped_cli_commands_require_study_id(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        experiment_cli(arguments)
    assert caught.value.code == 2


def test_frozen_study_id_rejects_other_studies(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "wrong-study-blocks"
    assert experiment_cli([
        "build-blocks",
        "--study-id", "study_other",
        "--output-dir", str(output),
    ]) == EXIT_OPERATION
    failure = __import__("json").loads(capsys.readouterr().err)
    assert failure["code"] == "STUDY_ID_MISMATCH"
    assert not output.exists()
    with pytest.raises(ValueError, match="STUDY_ID_MISMATCH"):
        create_app(tmp_path / "wrong-study.sqlite3", study_id="study_other")


def test_deidentified_export_is_bound_to_the_frozen_study(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assignment = build_assignments(
        synthetic_participants(1), synthetic_catalog(), study_id=STUDY_ID, questionnaire_version="1.0.0", seed="export-study"
    )[0]
    database = tmp_path / "experiment.sqlite3"
    store = ExperimentStore(database)
    store.save_assignment(assignment)
    event, ratings = trial_submission(assignment)
    store.submit_trial(event, ratings)
    output = tmp_path / "ratings.jsonl"
    assert experiment_cli([
        "export",
        "--study-id", STUDY_ID,
        "--database", str(database),
        "--output", str(output),
        "--purpose", "engineering_fixture",
        "--deidentified",
    ]) == EXIT_OK
    summary = __import__("json").loads(capsys.readouterr().out)
    assert summary["record_count"] == 1

    mismatched = copy.deepcopy(assignment)
    mismatched["study_id"] = "study_other"
    with pytest.raises(StoreError) as caught:
        ExperimentStore(tmp_path / "other.sqlite3").save_assignment(mismatched)
    assert caught.value.code == "STUDY_ID_MISMATCH"


def test_cli_builds_schema_valid_reference_bundle_without_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "reference"
    assert experiment_cli(["build-reference", "--output-dir", str(output)]) == EXIT_OK
    summary = __import__("json").loads(capsys.readouterr().out)
    assert summary["artifact_count"] == 9
    schema_files = {
        "study_protocol.json": "study_protocol.schema.json",
        "questionnaire_definition.json": "questionnaire_definition.schema.json",
        "participant_profile.json": "participant_profile.schema.json",
        "consent_receipt.json": "consent_receipt.schema.json",
        "stimulus_catalog.json": "experiment_stimulus_catalog.schema.json",
        "assignment.json": "experiment_assignment.schema.json",
        "presentation_event.json": "presentation_event.schema.json",
        "quality_decision.json": "quality_decision.schema.json",
    }
    for filename, schema_name in schema_files.items():
        record = __import__("json").loads((output / filename).read_text(encoding="utf-8"))
        assert validate_record(record, ROOT / "schema" / schema_name) == []
    assert len(read_and_validate_export(output / "ratings.jsonl", purpose="engineering_fixture")) == 7
    assert experiment_cli(["build-reference", "--output-dir", str(output)]) == EXIT_NO_OVERWRITE


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("artifact=/workspace/project/data/file.json", True),
        ('{"path":"/srv/glyph/file.json"}', True),
        ("file:///custom/root/file.json", True),
        (r"C:\\workspace\\glyph\\file.json", True),
        ("data/releases/task03/file.json", False),
        ("https://json-schema.org/draft/2020-12/schema", False),
        ("#/$defs/artifact", False),
        ("GET /api/status and /static/app.js", False),
        ("desktop/mobile and 桌面/移动", False),
    ],
)
def test_handoff_absolute_path_scan_is_portable(tmp_path: Path, payload: str, expected: bool) -> None:
    candidate = tmp_path / "candidate.txt"
    candidate.write_text(payload, encoding="utf-8")
    assert _contains_absolute_path(candidate) is expected


def test_handoff_builder_revalidates_task01_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_upstream(root: Path) -> None:
        raise ValueError(f"TASK01_CHECKPOINT_HANDOFF_MISMATCH:{root.name}")

    monkeypatch.setattr(handoff_module, "load_task01_fixture", reject_upstream)
    output = tmp_path / "handoff"
    with pytest.raises(ValueError, match="TASK01_CHECKPOINT_HANDOFF_MISMATCH"):
        handoff_module.build_handoff(
            ROOT,
            output,
            implementation_commit="0" * 40,
            created_at="2026-09-04T00:00:00Z",
            evidence_dir=tmp_path / "evidence",
            validation_summary_path=tmp_path / "validation.json",
        )
    assert not output.exists()
    assert not output.with_name(".handoff.staging").exists()
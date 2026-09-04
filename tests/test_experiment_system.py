from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.asset_system.catalog import validate_record
from glyph_features.experiment_system.assignment import audit_assignments, build_assignments
from glyph_features.experiment_system.export import (
    ExportBlocked,
    read_and_validate_bundle,
    read_and_validate_export,
    require_export_eligible,
    validate_deidentified_bundle,
    write_deidentified_bundle,
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
REQUIRED_RATINGS = (
    ("item_aesthetic", "aesthetic"),
    ("item_premium", "premium"),
    ("item_modern", "modern"),
    ("item_trustworthy", "trustworthy"),
    ("item_visual_clarity", "visual_clarity"),
    ("item_recognition", "recognition"),
    ("item_unfamiliarity", "unfamiliarity"),
)


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
        "schema_version": "1.1.0",
        "study_id": protocol["study_id"],
        "protocol_version": protocol["protocol_version"],
        "questionnaire_version": questionnaire["questionnaire_version"],
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


def web_session_payload(
    session_nonce: str,
    *,
    language: str = "en",
    native_scripts: list[str] | None = None,
) -> dict:
    scripts = native_scripts or ["latin", "han"]
    return {
        "language": language,
        "session_nonce": session_nonce,
        "profile": {
            "mother_tongues": [
                {"bcp47": language, "dominance": "primary"},
                {"bcp47": "zh-Hans" if language == "en" else "en", "dominance": "additional"},
            ],
            "native_scripts": scripts,
            "script_proficiencies": [
                {"script": script, "reading": 4, "writing": 3, "exposure_frequency": 5}
                for script in ("latin", "han", "kana", "hangul")
            ],
            "region_category": "multiple",
            "cross_cultural_exposure": "moderate",
            "training": {"design": "informal", "typography": "none", "calligraphy": "none"},
            "age_band": "25_34",
            "education_level": "undergraduate",
            "language_understood": True,
        },
        "consent": {
            "consent_version": "1.0.0",
            "status": "consented",
            "age_eligible": True,
        },
    }


def allocate_store_session(store: ExperimentStore, *, seed: str) -> dict:
    protocol = json.loads((ROOT / "configs/cross_cultural_study_v1.json").read_text(encoding="utf-8"))
    payload = web_session_payload(
        f"store_{hashlib.sha256(seed.encode()).hexdigest()[:16]}",
        language="zh-Hans",
        native_scripts=["han", "latin"],
    )
    participant_id = f"synp_store_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
    participant = {
        "participant_id": participant_id,
        "participant_group": "multiscript",
        "data_origin": "synthetic",
    }
    recorded_at = protocol["created_at"]
    profile = {
        **payload["profile"],
        "schema_version": "1.0.0",
        "study_id": STUDY_ID,
        "participant_id": participant_id,
        "data_origin": "synthetic",
        "questionnaire_language": payload["language"],
        "created_at": recorded_at,
    }
    consent = {
        **payload["consent"],
        "schema_version": "1.1.0",
        "study_id": STUDY_ID,
        "protocol_version": protocol["protocol_version"],
        "questionnaire_version": "1.0.0",
        "participant_id": participant_id,
        "data_origin": "synthetic",
        "recorded_at": recorded_at,
    }
    assignment, created = store.allocate_assignment(
        participant,
        profile=profile,
        consent=consent,
        session_nonce=payload["session_nonce"],
        request_payload=payload,
        seed=seed,
        block_size=protocol["design"]["block_size"],
        required_anchor_count=protocol["design"]["anchor_count"],
        created_at=recorded_at,
    )
    assert created
    return assignment


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
        "attention_response": "circle",
    }
    ratings = []
    for item_id, construct in REQUIRED_RATINGS:
        rating = rating_record()
        rating.update({
            "rating_id": f"rating_{trial['presentation_id'][-12:]}_{item_id.removeprefix('item_')}",
            "assignment_id": assignment["assignment_id"],
            "block_id": assignment["block_id"],
            "presentation_id": trial["presentation_id"],
            "stimulus_id": trial["stimulus_id"],
            "participant_id": assignment["participant_id"],
            "data_origin": assignment["data_origin"],
            "displayed_asset_sha256": trial["asset_sha256"],
            "trial_index": trial["trial_index"],
            "item_id": item_id,
            "construct": construct,
        })
        ratings.append(rating)
    return event, ratings


def web_trial_submission(
    session: dict,
    *,
    trial_offset: int,
    response_ms: int = 1800,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    response_value: int = 4,
) -> tuple[dict, list[dict]]:
    trial = session["trials"][trial_offset]
    suffix = trial["presentation_id"][-16:]
    event = {
        "schema_version": "1.0.0",
        "event_id": f"event_{suffix}",
        "request_id": f"request_{suffix}",
        "study_id": session["study_id"],
        "assignment_id": session["assignment_id"],
        "presentation_id": trial["presentation_id"],
        "participant_id": session["participant_id"],
        "data_origin": "synthetic",
        "stimulus_id": trial["stimulus_id"],
        "expected_asset_sha256": trial["expected_asset_sha256"],
        "displayed_asset_sha256": trial["expected_asset_sha256"],
        "load_status": "loaded",
        "trial_index": trial["trial_index"],
        "started_at": "2026-09-04T00:00:00Z",
        "ended_at": f"2026-09-04T00:00:{trial_offset + 1:02d}Z",
        "preload_ms": 12,
        "response_ms": response_ms,
        "viewport": {
            "css_width": viewport_width,
            "css_height": viewport_height,
            "stimulus_css_width": max(1, min(512, viewport_width)),
            "stimulus_css_height": max(1, min(512, viewport_height)),
            "device_pixel_ratio": 2,
        },
        "focus_loss_count": 0,
        "zoom_anomaly": False,
        "attention_response": "circle",
    }
    ratings = []
    for item_id, construct in REQUIRED_RATINGS:
        rating = rating_record()
        rating.update({
            "rating_id": f"rating_{suffix}_{item_id.removeprefix('item_')}",
            "assignment_id": session["assignment_id"],
            "block_id": session["block_id"],
            "presentation_id": trial["presentation_id"],
            "stimulus_id": trial["stimulus_id"],
            "participant_id": session["participant_id"],
            "respondent_language_bcp47": session["profile"]["questionnaire_language"],
            "native_scripts": session["profile"]["native_scripts"],
            "displayed_asset_sha256": trial["expected_asset_sha256"],
            "trial_index": trial["trial_index"],
            "response_time_ms": response_ms,
            "response": {"value": response_value, "missing_reason": None},
            "item_id": item_id,
            "construct": construct,
            "quality": {"rule_version": "1.0.0", "exclude_from_analysis": False, "reason_codes": []},
            "collected_at": event["ended_at"],
        })
        ratings.append(rating)
    return event, ratings


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

    database = tmp_path / "restricted" / "submission.sqlite3"
    store = ExperimentStore(database)
    assignment = allocate_store_session(store, seed="store-test-submission")
    event, ratings = trial_submission(assignment)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: ExperimentStore(database).submit_trial(event, ratings), range(8)))
    assert [result["status"] for result in results].count("accepted") == 1
    assert [result["status"] for result in results].count("duplicate") == 7
    assert store.counts() == {
        "profiles": 1,
        "consents": 1,
        "assignments": 1,
        "presentations": 1,
        "ratings": 7,
        "quality_decisions": 1,
    }
    assert ExperimentStore(database).assignment_for(assignment["participant_id"])["resume_next_trial"] == 2


def test_store_rejects_conflicting_retry_and_unverified_asset(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiment.sqlite3")
    assignment = allocate_store_session(store, seed="store-conflict")
    event, ratings = trial_submission(assignment)
    store.submit_trial(event, ratings)

    conflict = copy.deepcopy(event)
    conflict["response_ms"] += 1
    conflict_ratings = copy.deepcopy(ratings)
    for rating in conflict_ratings:
        rating["response_time_ms"] += 1
    with pytest.raises(StoreError) as caught:
        store.submit_trial(conflict, conflict_ratings)
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

    second_store = ExperimentStore(tmp_path / "second.sqlite3")
    second_assignment = allocate_store_session(second_store, seed="store-hash")
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

    submission_store = ExperimentStore(tmp_path / "submission.sqlite3")
    submission_assignment = allocate_store_session(submission_store, seed="store-lock-submission")
    event, ratings = trial_submission(submission_assignment)
    real_event = copy.deepcopy(event)
    real_event["data_origin"] = "real"
    with pytest.raises(StoreError) as caught:
        submission_store.submit_trial(real_event, ratings)
    assert caught.value.code == "REAL_COLLECTION_LOCKED"

    wrong_construct = copy.deepcopy(ratings)
    wrong_construct[0]["construct"] = "premium"
    with pytest.raises(StoreError) as caught:
        submission_store.submit_trial(event, wrong_construct)
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
        json=web_session_payload("browserfixture01", native_scripts=["latin"]),
    )
    assert response.status_code == 200
    spoofed = client.post(
        "/api/session",
        json={**web_session_payload("browserfixture02", native_scripts=["latin"]), "data_origin": "real"},
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


def test_web_ui_collects_complete_profile_and_never_decides_quality() -> None:
    app_js = (ROOT / "src/glyph_features/experiment_system/static/app.js").read_text(encoding="utf-8")
    for field_name in (
        "mother-tongue",
        "dominant-language",
        "proficiency-reading",
        "proficiency-writing",
        "proficiency-exposure",
        "training-design",
        "training-typography",
        "training-calligraphy",
        "region-category",
        "cross-cultural-exposure",
        "age-band",
        "education-level",
    ):
        assert field_name in app_js
    assert "profile: state.profile" in app_js
    assert "consent: state.consent" in app_js
    assert "attention_response: state.attentionResponse" in app_js
    assert "state.language = state.profile.questionnaire_language" in app_js
    assert "languageSelect.disabled = Boolean(state.assignment)" in app_js
    assert "attention_check:" not in app_js
    assert "quality:" not in app_js


def test_web_session_persists_and_restores_profile_and_consent(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    response = client.post("/api/session", json=web_session_payload("profileconsent01"))
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["profile"]["mother_tongues"] == [
        {"bcp47": "en", "dominance": "primary"},
        {"bcp47": "zh-Hans", "dominance": "additional"},
    ]
    assert session["profile"]["native_scripts"] == ["latin", "han"]
    assert {row["script"] for row in session["profile"]["script_proficiencies"]} == {
        "latin", "han", "kana", "hangul",
    }
    assert session["consent"] == {
        "schema_version": "1.1.0",
        "study_id": STUDY_ID,
        "protocol_version": "1.0.0",
        "questionnaire_version": "1.0.0",
        "participant_id": session["participant_id"],
        "data_origin": "synthetic",
        "consent_version": "1.0.0",
        "status": "consented",
        "age_eligible": True,
        "recorded_at": session["consent"]["recorded_at"],
    }
    resumed = TestClient(create_app(database, study_id=STUDY_ID)).get(
        f"/api/session/{session['participant_id']}"
    )
    assert resumed.status_code == 200
    assert resumed.json()["profile"] == session["profile"]
    assert resumed.json()["consent"] == session["consent"]
    assert ExperimentStore(database).counts() == {
        "profiles": 1,
        "consents": 1,
        "assignments": 1,
        "presentations": 0,
        "ratings": 0,
        "quality_decisions": 0,
    }


def test_server_is_authoritative_for_quality_and_preserves_history(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("qualityattack01")).json()
    event, ratings = web_trial_submission(
        session,
        trial_offset=0,
        response_ms=1,
        viewport_width=240,
        viewport_height=320,
    )
    ratings[0]["quality"] = {
        "rule_version": "1.0.0",
        "exclude_from_analysis": False,
        "reason_codes": [],
    }
    event["attention_response"] = "square"
    ratings[0]["attention_check"] = True
    first = client.post("/api/submissions", json={"event": event, "ratings": ratings})
    assert first.status_code == 200, first.text
    first_decision = first.json()["quality_decision"]
    assert first_decision["exclude_from_analysis"] is True
    assert {"ATTENTION_FAILED", "INCOMPLETE", "TOO_FAST", "VIEWPORT_UNUSABLE"} <= set(first_decision["reason_codes"])
    assert first_decision["previous_decision_id"] is None

    second_event, second_ratings = web_trial_submission(session, trial_offset=1, response_value=5)
    second = client.post("/api/submissions", json={"event": second_event, "ratings": second_ratings})
    assert second.status_code == 200, second.text
    second_decision = second.json()["quality_decision"]
    assert second_decision["previous_decision_id"] == first_decision["decision_id"]
    assert second_decision["decision_id"] != first_decision["decision_id"]
    resumed = client.get(f"/api/session/{session['participant_id']}").json()
    assert resumed["quality_decision"] == second_decision
    assert ExperimentStore(database).counts()["quality_decisions"] == 2


def test_server_rejects_incomplete_required_rating_set(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "experiment.sqlite3", study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("missingratings01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    response = client.post("/api/submissions", json={"event": event, "ratings": ratings[:1]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RATING_ITEM_SET_MISMATCH"
    unexpected = copy.deepcopy(ratings[0])
    unexpected.update({
        "rating_id": f"{unexpected['rating_id']}_brand_fit",
        "item_id": "item_brand_fit",
        "construct": "brand_fit",
    })
    response = client.post("/api/submissions", json={"event": event, "ratings": [*ratings, unexpected]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RATING_ITEM_SET_MISMATCH"


def test_web_session_rejects_missing_profile_with_stable_code(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "experiment.sqlite3", study_id=STUDY_ID))
    response = client.post(
        "/api/session",
        json={"language": "en", "session_nonce": "missingprofile01", "consent": {"status": "consented"}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PROFILE_REQUIRED"


def test_web_session_allocation_uses_persistent_global_quotas(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    sessions: list[dict] = []
    for batch in range(2):
        client = TestClient(create_app(database, study_id=STUDY_ID))
        for offset in range(32):
            response = client.post(
                "/api/session",
                json=web_session_payload(
                    f"persistent{batch:02d}{offset:04d}",
                    native_scripts=["latin"],
                ),
            )
            assert response.status_code == 200, response.text
            sessions.append(response.json())

    exposure: Counter[str] = Counter()
    positions: dict[str, Counter[int]] = defaultdict(Counter)
    for session in sessions:
        for trial in session["trials"]:
            exposure[trial["stimulus_id"]] += 1
            positions[trial["stimulus_id"]][trial["trial_index"]] += 1

    assert len(exposure) == 16
    assert max(exposure.values()) - min(exposure.values()) <= 1
    assert max(
        max(position_counts[position] for position in range(1, 9))
        - min(position_counts[position] for position in range(1, 9))
        for position_counts in positions.values()
    ) <= 1
    assert TestClient(create_app(database, study_id=STUDY_ID)).get("/api/debug/counts").json()["assignments"] == 64


def test_web_session_nonce_is_transactional_under_concurrency(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    same_payload = web_session_payload("concurrent_same01", native_scripts=["latin"])
    with ThreadPoolExecutor(max_workers=8) as executor:
        same_results = list(executor.map(lambda _: client.post("/api/session", json=same_payload), range(8)))
    assert {response.status_code for response in same_results} == {200}
    assert len({response.json()["assignment_id"] for response in same_results}) == 1

    different_payloads = [
        web_session_payload(f"concurrent_diff{index:02d}", native_scripts=["latin"])
        for index in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        different_results = list(
            executor.map(lambda payload: client.post("/api/session", json=payload), different_payloads)
        )
    assert {response.status_code for response in different_results} == {200}
    sessions = [same_results[0].json(), *(response.json() for response in different_results)]
    assert len({session["assignment_id"] for session in sessions}) == 17
    exposure = Counter(
        trial["stimulus_id"]
        for session in sessions
        for trial in session["trials"]
    )
    assert len(exposure) == 16
    assert max(exposure.values()) - min(exposure.values()) <= 1
    assert ExperimentStore(database).counts()["assignments"] == 17


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
    database = tmp_path / "experiment.sqlite3"
    store = ExperimentStore(database)
    assignment = allocate_store_session(store, seed="export-study")
    event, ratings = trial_submission(assignment)
    store.submit_trial(event, ratings)
    output = tmp_path / "export"
    assert experiment_cli([
        "export",
        "--study-id", STUDY_ID,
        "--database", str(database),
        "--output", str(output),
        "--purpose", "engineering_fixture",
        "--deidentified",
    ]) == EXIT_OK
    summary = __import__("json").loads(capsys.readouterr().out)
    assert summary["record_counts"] == {
        "assignments": 1,
        "consents": 1,
        "presentations": 1,
        "profiles": 1,
        "quality_decisions": 1,
        "ratings": 7,
    }

    mismatched = copy.deepcopy(assignment)
    mismatched["study_id"] = "study_other"
    with pytest.raises(StoreError) as caught:
        ExperimentStore(tmp_path / "other.sqlite3").save_assignment(mismatched)
    assert caught.value.code == "STUDY_ID_MISMATCH"


def test_cli_exports_complete_deidentified_session_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("exportbundle01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200

    output = tmp_path / "deidentified-export"
    assert experiment_cli([
        "export",
        "--study-id", STUDY_ID,
        "--database", str(database),
        "--output", str(output),
        "--purpose", "engineering_fixture",
        "--deidentified",
    ]) == EXIT_OK
    summary = __import__("json").loads(capsys.readouterr().out)
    assert summary["record_counts"] == {
        "assignments": 1,
        "consents": 1,
        "presentations": 1,
        "profiles": 1,
        "quality_decisions": 1,
        "ratings": 7,
    }
    manifest = __import__("json").loads((output / "export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic_only"] is True
    assert manifest["quality_rule_version"] == "1.0.0"
    assert {artifact["record_type"] for artifact in manifest["artifacts"]} == set(summary["record_counts"])
    for filename in (
        "participant_profiles.jsonl",
        "consent_receipts.jsonl",
        "assignments.jsonl",
        "presentation_events.jsonl",
        "ratings.jsonl",
        "quality_decisions.jsonl",
    ):
        assert (output / filename).is_file()

    formal_output = tmp_path / "formal-export"
    assert experiment_cli([
        "export",
        "--study-id", STUDY_ID,
        "--database", str(database),
        "--output", str(formal_output),
        "--purpose", "formal_analysis",
        "--deidentified",
    ]) == EXIT_OPERATION
    assert __import__("json").loads(capsys.readouterr().err)["code"] == "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN"
    assert not formal_output.exists()


def test_bundle_reader_rejects_server_quality_exclusions_for_formal_use(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("formalquality01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    records = ExperimentStore(database).deidentified_records(study_id=STUDY_ID)
    real_participant_id = "p_reference_001"
    for rows in records.values():
        for record in rows:
            record["data_origin"] = "real"
            if "participant_id" in record:
                record["participant_id"] = real_participant_id
    previous = records["quality_decisions"][0]
    decision = build_quality_decision(
        records["profiles"][0],
        records["consents"][0],
        records["presentations"],
        records["ratings"],
        decided_at=previous["decided_at"],
    )
    records["quality_decisions"] = [decision]
    server_quality = {
        "rule_version": decision["rule_version"],
        "exclude_from_analysis": decision["exclude_from_analysis"],
        "reason_codes": decision["reason_codes"],
    }
    for rating in records["ratings"]:
        rating["quality"] = server_quality

    output = tmp_path / "formal-bundle"
    write_deidentified_bundle(records, output, purpose="engineering_fixture")
    manifest_path = output / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["purpose"] = "formal_analysis"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gates = {gate: "passed" for gate in ("GATE-ETHICS", "GATE-PARTICIPANTS", "GATE-TRANSLATION")}
    with pytest.raises(ExportBlocked) as caught:
        read_and_validate_bundle(output, purpose="formal_analysis", human_gates=gates)
    assert caught.value.code == "QUALITY_EXCLUSION_PRESENT"


def test_bundle_validation_recomputes_every_quality_history_node(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("qualityhistory01")).json()
    for trial_offset in range(2):
        event, ratings = web_trial_submission(session, trial_offset=trial_offset)
        assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    records = ExperimentStore(database).deidentified_records(study_id=STUDY_ID)
    records["quality_decisions"][0]["reason_codes"].append("TOO_FAST")
    errors = validate_deidentified_bundle(records)
    assert any(error.startswith("QUALITY_DECISION_RECOMPUTE_MISMATCH:") for error in errors)


def test_bundle_validation_rejects_quality_history_branches(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("qualitybranch01")).json()
    for trial_offset in range(2):
        event, ratings = web_trial_submission(session, trial_offset=trial_offset)
        assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    records = ExperimentStore(database).deidentified_records(study_id=STUDY_ID)
    branch = copy.deepcopy(records["quality_decisions"][1])
    branch["decision_id"] = "quality_branch_0001"
    records["quality_decisions"].append(branch)
    errors = validate_deidentified_bundle(records)
    assert any(error.startswith("QUALITY_HISTORY_BRANCH:") for error in errors)


def test_bundle_validation_rejects_duplicate_participant_assignments(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("duplicateassignment01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    records = ExperimentStore(database).deidentified_records(study_id=STUDY_ID)
    duplicate = copy.deepcopy(records["assignments"][0])
    duplicate["assignment_id"] = "assignment_duplicate_001"
    duplicate["block_id"] = "block_duplicate_001"
    records["assignments"].insert(0, duplicate)
    errors = validate_deidentified_bundle(records)
    assert f"DUPLICATE_PARTICIPANT_ASSIGNMENT:{session['participant_id']}" in errors


def test_bundle_writer_rejects_missing_required_rating_items(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("bundlemissingrating01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    records = ExperimentStore(database).deidentified_records(study_id=STUDY_ID)
    removed = records["ratings"].pop()
    with pytest.raises(ExportBlocked) as caught:
        write_deidentified_bundle(records, tmp_path / "invalid-bundle", purpose="engineering_fixture")
    assert caught.value.code == "DEIDENTIFIED_BUNDLE_INVALID"
    assert "RATING_ITEM_SET_MISMATCH" in str(caught.value)
    records["ratings"].append(removed)
    unexpected = copy.deepcopy(removed)
    unexpected.update({
        "rating_id": f"{unexpected['rating_id']}_brand_fit",
        "item_id": "item_brand_fit",
        "construct": "brand_fit",
    })
    records["ratings"].append(unexpected)
    with pytest.raises(ExportBlocked) as caught:
        write_deidentified_bundle(records, tmp_path / "invalid-extra-bundle", purpose="engineering_fixture")
    assert caught.value.code == "DEIDENTIFIED_BUNDLE_INVALID"
    assert "RATING_ITEM_SET_MISMATCH" in str(caught.value)


def test_bundle_reader_binds_manifest_claims_to_records(tmp_path: Path) -> None:
    database = tmp_path / "experiment.sqlite3"
    client = TestClient(create_app(database, study_id=STUDY_ID))
    session = client.post("/api/session", json=web_session_payload("manifestbinding01")).json()
    event, ratings = web_trial_submission(session, trial_offset=0)
    assert client.post("/api/submissions", json={"event": event, "ratings": ratings}).status_code == 200
    output = tmp_path / "bundle"
    write_deidentified_bundle(
        ExperimentStore(database).deidentified_records(study_id=STUDY_ID),
        output,
        purpose="engineering_fixture",
    )
    manifest_path = output / "export_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["study_id"] = "study_other"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ExportBlocked) as caught:
        read_and_validate_bundle(output, purpose="engineering_fixture")
    assert caught.value.code == "EXPORT_MANIFEST_CONTENT_MISMATCH"

    manifest["study_id"] = STUDY_ID
    profiles = next(artifact for artifact in manifest["artifacts"] if artifact["record_type"] == "profiles")
    profiles["schema"] = "consent_receipt.schema.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ExportBlocked) as caught:
        read_and_validate_bundle(output, purpose="engineering_fixture")
    assert caught.value.code == "EXPORT_MANIFEST_BINDING_MISMATCH"


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


def _copy_handoff_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    source_manifest = ROOT / "data/releases/task03_cross_cultural_experiment_v1/handoff_manifest.json"
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    root = tmp_path / "workspace"
    for artifact in [*manifest["input_snapshots"], *manifest["outputs"]]:
        source = ROOT / artifact["path"]
        target = root / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for entrypoint in manifest["next_task_entrypoints"]:
        source = ROOT / entrypoint["path"]
        target = root / entrypoint["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if not any(artifact["path"] == entrypoint["path"] for artifact in manifest["outputs"]):
            input_artifact = next(
                (artifact for artifact in manifest["input_snapshots"] if artifact["path"] == entrypoint["path"]),
                None,
            )
            manifest["outputs"].append({
                "logical_type": "next_task_entrypoint",
                "path": entrypoint["path"],
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "record_count": 1,
                "privacy_level": input_artifact["privacy_level"] if input_artifact else "synthetic_fixture",
                "schema_version": input_artifact["schema_version"] if input_artifact else "1.0.0",
                "validation_schema": input_artifact["validation_schema"] if input_artifact else None,
            })
    records_root = root / "data/fixtures/experiment_system/reference_v1/records"
    consent_path = records_root / "consent_receipt.json"
    consent = json.loads(consent_path.read_text(encoding="utf-8"))
    consent.update({
        "schema_version": "1.1.0",
        "protocol_version": "1.0.0",
        "questionnaire_version": "1.0.0",
    })
    consent_path.write_text(json.dumps(consent, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reference_path = records_root / "reference_manifest.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    reference_consent = next(artifact for artifact in reference["artifacts"] if artifact["path"] == "consent_receipt.json")
    reference_consent["sha256"] = hashlib.sha256(consent_path.read_bytes()).hexdigest()
    reference_path.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["contract_versions"]["consent_receipt"] = "1.1.0"
    for artifact in manifest["outputs"]:
        target = root / artifact["path"]
        artifact["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        if artifact["path"].endswith("/records/consent_receipt.json"):
            artifact["schema_version"] = "1.1.0"
    manifest["outputs"].sort(key=lambda artifact: artifact["path"])
    manifest_path = root / "data/releases/task03_cross_cultural_experiment_v1/handoff_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(handoff_module, "_validate_producer", lambda manifest, root, errors: None)
    assert handoff_module.validate_handoff(manifest_path, root) == []
    return manifest_path, manifest


def test_strict_handoff_rejects_unprotected_or_modified_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    manifest["next_task_entrypoints"][1]["path"] = manifest["input_snapshots"][0]["path"]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = handoff_module.validate_handoff(manifest_path, manifest_path.parents[3])
    assert any(error.startswith("ENTRYPOINT_NOT_PROTECTED_OUTPUT:") for error in errors)


def test_strict_handoff_rejects_reference_manifest_removed_from_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    entrypoint_path = manifest["next_task_entrypoints"][1]["path"]
    manifest["outputs"] = [artifact for artifact in manifest["outputs"] if artifact["path"] != entrypoint_path]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = handoff_module.validate_handoff(manifest_path, manifest_path.parents[3])
    assert f"ENTRYPOINT_NOT_PROTECTED_OUTPUT:TASK-05:{entrypoint_path}" in errors


def test_strict_handoff_rejects_rehashed_reference_foreign_key_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    root = manifest_path.parents[3]
    records_root = root / "data/fixtures/experiment_system/reference_v1/records"
    quality_path = records_root / "quality_decision.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["participant_id"] = "synp_reference_diverged"
    quality_path.write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    reference_path = records_root / "reference_manifest.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    next(artifact for artifact in reference["artifacts"] if artifact["path"] == "quality_decision.json")["sha256"] = hashlib.sha256(quality_path.read_bytes()).hexdigest()
    reference_path.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for artifact in manifest["outputs"]:
        target = root / artifact["path"]
        if artifact["path"] in {
            "data/fixtures/experiment_system/reference_v1/records/quality_decision.json",
            "data/fixtures/experiment_system/reference_v1/records/reference_manifest.json",
        }:
            artifact["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    errors = handoff_module.validate_handoff(manifest_path, root)
    assert any(error.startswith("REFERENCE_QUALITY_PARTICIPANT_MISMATCH:") for error in errors)


def test_strict_handoff_recomputes_reference_record_counts_after_rehash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    root = manifest_path.parents[3]
    reference_path = root / "data/fixtures/experiment_system/reference_v1/records/reference_manifest.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    ratings = next(artifact for artifact in reference["artifacts"] if artifact["path"] == "ratings.jsonl")
    ratings["record_count"] -= 1
    reference_path.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    top_reference = next(artifact for artifact in manifest["outputs"] if artifact["path"].endswith("/records/reference_manifest.json"))
    top_reference["sha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = handoff_module.validate_handoff(manifest_path, root)
    assert "REFERENCE_REFERENCE_COUNT_MISMATCH:ratings.jsonl" in errors


def test_strict_handoff_rejects_rehashed_catalog_asset_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    root = manifest_path.parents[3]
    records_root = root / "data/fixtures/experiment_system/reference_v1/records"
    assignment_path = records_root / "assignment.json"
    event_path = records_root / "presentation_event.json"
    ratings_path = records_root / "ratings.jsonl"
    replacement_sha256 = "f" * 64
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    trial = next(item for item in assignment["trials"] if item["trial_index"] == 1)
    trial["asset_sha256"] = replacement_sha256
    assignment_path.write_text(json.dumps(assignment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["expected_asset_sha256"] = replacement_sha256
    event["displayed_asset_sha256"] = replacement_sha256
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ratings = [json.loads(line) for line in ratings_path.read_text(encoding="utf-8").splitlines() if line]
    for rating in ratings:
        rating["displayed_asset_sha256"] = replacement_sha256
    ratings_path.write_text(
        "".join(json.dumps(rating, sort_keys=True, separators=(",", ":")) + "\n" for rating in ratings),
        encoding="utf-8",
    )
    _rehash_reference_attack(manifest, root, {assignment_path, event_path, ratings_path})
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = handoff_module.validate_handoff(manifest_path, root)
    assert any(error.startswith("REFERENCE_ASSIGNMENT_CATALOG_MISMATCH:") for error in errors)


def test_strict_handoff_rejects_rehashed_questionnaire_item_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, manifest = _copy_handoff_workspace(tmp_path, monkeypatch)
    root = manifest_path.parents[3]
    ratings_path = root / "data/fixtures/experiment_system/reference_v1/records/ratings.jsonl"
    ratings = [json.loads(line) for line in ratings_path.read_text(encoding="utf-8").splitlines() if line]
    ratings[0]["item_id"] = "item_fabricated"
    ratings_path.write_text(
        "".join(json.dumps(rating, sort_keys=True, separators=(",", ":")) + "\n" for rating in ratings),
        encoding="utf-8",
    )
    _rehash_reference_attack(manifest, root, {ratings_path})
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    errors = handoff_module.validate_handoff(manifest_path, root)
    assert any(error.startswith("REFERENCE_RATING_QUESTIONNAIRE_MISMATCH:") for error in errors)


def _rehash_reference_attack(manifest: dict, root: Path, modified_paths: set[Path]) -> None:
    records_root = root / "data/fixtures/experiment_system/reference_v1/records"
    reference_path = records_root / "reference_manifest.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    modified_names = {path.name for path in modified_paths}
    for artifact in reference["artifacts"]:
        if artifact["path"] in modified_names:
            artifact["sha256"] = hashlib.sha256((records_root / artifact["path"]).read_bytes()).hexdigest()
    reference_path.write_text(json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    modified_paths.add(reference_path)
    modified_repo_paths = {path.relative_to(root).as_posix() for path in modified_paths}
    for artifact in manifest["outputs"]:
        if artifact["path"] in modified_repo_paths:
            artifact["sha256"] = hashlib.sha256((root / artifact["path"]).read_bytes()).hexdigest()
import json
import csv
import io
from pathlib import Path
import zipfile

from glyph_features.workbench.catalog import Catalog
from glyph_features.workbench.materials import MaterialCatalog
from glyph_features.workbench.personas import PersonaExecutor
from glyph_features.workbench.research import ResearchService, StudyConfig
from glyph_features.workbench.research_results import analyze_research, export_research


ROOT = Path(__file__).resolve().parents[1]


def test_missing_results_and_real_font_evidence_export(tmp_path):
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    item = next(item for item in research.materials.search(kind="existing_font_sample") if "NotoSerifSC" in item["representations"]["original"]["path"])
    config = StudyConfig(name="Evidence unit check", question="Is this sample aesthetically pleasing?", explanations=["form"], selections=[{"material_id":item["material_id"], "reason":"Existing same-content control"}], selection_scope="Other materials not needed in the local test.", stopping_rule="Engineering validation only, not model research.")
    run = research.create(config)
    executor = PersonaExecutor(research)
    executor.prepare(run["run_id"])
    result = analyze_research(research, executor, run["run_id"])
    assert result["actual_calls"] == 0
    assert result["materials"][0]["median_aesthetic"] is None
    assert result["materials"][0]["missing_or_unexecuted"] == 4
    assert result["four_line_evidence"]["instances"][0]["character_mapping"]
    assert not result["four_line_evidence"]["instances"][0]["task04_matches"]
    exported = export_research(result, tmp_path / "exports")
    assert export_research(result, tmp_path / "exports") == exported
    with zipfile.ZipFile(exported["path"]) as archive:
        assert set(archive.namelist()) == {"result.json", "ratings.csv", "manifest.json"}
        assert json.loads(archive.read("manifest.json"))["images_included"] is False


def test_matched_differences_exclude_deviations(tmp_path, monkeypatch):
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    samples = [item for item in research.materials.search(kind="existing_font_sample") if "Lato-" in item["representations"]["original"]["path"]]
    config = StudyConfig(name="Comparison unit check", question="Compare the same-content forms.", explanations=["form"], selections=[{"material_id": item["material_id"], "reason": "Existing same-content pair"} for item in samples], roles=["baseline", "en"], repetitions=2, selection_scope="Engineering test only.", stopping_rule="No model calls.")
    run = research.create(config)
    executor = PersonaExecutor(research)
    tasks = executor.prepare(run["run_id"])
    for task in tasks:
        condition = task["condition"]
        adjustment = int(condition["role"] == "en") + condition["repetition"] - int(condition["order"] == "reverse")
        task["attempts"] = [{"host_call_id": f"fixture-{task['task_id']}", "status": "completed", "raw_return": "ENGINEERING_FIXTURE_ONLY", "evidence": {"analysis_eligible": True, "model_display_name": "fixture", "visible_credits": "unknown"}, "ratings": [{"material_id": item["material_id"], "aesthetic": 2 + index * 2 + adjustment, "visual_clarity": 4} for index, item in enumerate(samples)]}]
    monkeypatch.setattr(executor, "tasks", lambda run_id: tasks)
    tasks[0]["attempts"][0]["ratings"][0]["reason"] = "=ENGINEERING_FIXTURE"
    result = analyze_research(research, executor, run["run_id"])
    assert len(result["rows"]) == 16
    assert len(result["identity_differences"]) == 8
    assert {item["difference"] for item in result["identity_differences"]} == {1}
    assert {item["difference"] for item in result["repeat_differences"]} == {1}
    assert {item["difference"] for item in result["order_and_call_differences"]} == {-1}
    assert {item["differences"]["aesthetic"] for item in result["within_content_font_pairs"]} == {2}
    assert len(result["font_comparison_summaries"]) == 2
    assert {item["role"] for item in result["font_comparison_summaries"]} == {"baseline", "en"}
    for summary in result["font_comparison_summaries"]:
        assert summary["matched_pairs"] == 4
        assert summary["aesthetic_differences"] == [2, 2, 2, 2]
        assert summary["order_mean_differences"] == {"forward": 2, "reverse": 2}
        assert summary["mean_clarity_difference"] == 0
    exported = export_research(result, tmp_path / "csv-test")
    with zipfile.ZipFile(exported["path"]) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("ratings.csv").decode())))
        assert rows[0]["reason"] == "'=ENGINEERING_FIXTURE"
        assert json.loads(archive.read("result.json"))["rows"][0]["reason"] == "=ENGINEERING_FIXTURE"
    tasks[0]["attempts"][0]["evidence"]["analysis_eligible"] = False
    tasks[0]["attempts"][0]["status"] = "protocol_deviation"
    result = analyze_research(research, executor, run["run_id"])
    assert len(result["rows"]) == 14
    assert len(result["identity_differences"]) == 6
    assert result["actual_calls"] == 8
    assert result["protocol_deviation_calls"] == 1


def test_representation_pairs_require_same_source_and_matching_condition():
    from copy import deepcopy
    from glyph_features.workbench.research_results import representation_comparison

    condition = {"role": "baseline", "order": "forward", "repetition": 0, "language": "en", "wording": "background"}
    rows = [{**condition, "material_id": "fixture", "model_display_name": "fixture", "task_id": "current", "aesthetic": 5}]
    tasks = [{"task_id": "reference", "condition": condition, "status": "completed", "attempts": [{"status": "completed", "host_call_id": "fixture", "evidence": {"analysis_eligible": True, "model_display_name": "fixture"}, "ratings": [{"material_id": "fixture", "aesthetic": 6}]}]}]
    reference = {"run_id": "reference", "snapshot": {"materials": [{"selection": {"material_id": "fixture"}, "input_sha256": "source", "source_input_sha256": "source"}]}}
    current = deepcopy(reference)
    current["snapshot"]["materials"][0]["input_sha256"] = "crop"
    comparison = representation_comparison(current, rows, reference, tasks)
    assert comparison["pairs"][0]["difference"] == -1
    assert comparison["reference_tasks_and_raw_returns"] == tasks
    tasks[0]["attempts"][0]["evidence"]["analysis_eligible"] = False
    assert not representation_comparison(current, rows, reference, tasks)["pairs"]
    tasks[0]["attempts"][0]["evidence"]["analysis_eligible"] = True
    current["snapshot"]["materials"][0]["source_input_sha256"] = "other"
    assert not representation_comparison(current, rows, reference, tasks)["pairs"]


def test_work_summary_does_not_count_repeated_inputs_as_independent_works():
    from glyph_features.workbench.research_results import summarize_representation_pairs

    materials = [{"selection": {"material_id": material_id}, "material": {"work_id": work_id}} for material_id, work_id in [("first", "work-one"), ("duplicate", "work-one"), ("second", "work-two"), ("unknown", None)]]
    pairs = [{"material_id": material_id, "role": "baseline", "order": "forward", "repetition": repetition, "difference": difference} for material_id, repetition, difference in [("first", 0, -2), ("duplicate", 0, 0), ("first", 1, -1), ("second", 0, 1), ("unknown", 0, 6)]]
    summary = summarize_representation_pairs({"pairs": pairs}, materials)
    assert summary["observed_work_count"] == 2
    assert summary["equal_work_mean_difference"] == 0
    assert summary["negative_works"] == summary["positive_works"] == 1
    assert len(summary["ungrouped_pairs"]) == 1
    assert summary["works"][0]["matched_conditions"] == 2
    assert summary["works"][0]["mean_difference"] == -1
    assert [item["mean_difference"] for item in summary["leave_one_work_out"]] == [1, -1]
    empty = summarize_representation_pairs({"pairs": []}, materials)
    assert empty["equal_work_mean_difference"] is None
    assert empty["leave_one_work_out"] == []


def test_assessment_freezes_result_and_supplies_next_comparison(tmp_path):
    import pytest
    from glyph_features.workbench.research import ResearchAssessment

    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = StudyConfig(name="Assessment fixture", question="Which explanation remains possible?", explanations=["Form hypothesis"], selections=[{"material_id": sample["material_id"], "reason": "Engineering fixture"}], selection_scope="Engineering fixture only", stopping_rule="No actual model calls")
    run = research.create(config)
    result = analyze_research(research, PersonaExecutor(research), run["run_id"])
    assessment = ResearchAssessment(basis_result_sha256=result["result_sha256"], conclusion="No observations exist in this engineering fixture.", explanation_updates=[{"explanation": "Form hypothesis", "judgment": "unresolved", "evidence": "No scores have been collected.", "material_ids": [sample["material_id"]]}], remaining_confounds=["Engineering fixture"], next_question="Does the comparison remain after removing color?", next_comparison="Keep content and geometry fixed and compare native color against grayscale.", decision="new_comparison")
    saved = research.save_assessment(run["run_id"], assessment, result)
    assert research.save_assessment(run["run_id"], assessment, result) == saved
    assert research.assessments(run["run_id"])[0]["basis_result"] == result
    next_config = research.continuation(saved["assessment_id"])
    assert next_config["question"] == assessment.next_question
    assert next_config["design_rationale"] == assessment.next_comparison
    following = research.create(StudyConfig.model_validate(next_config))
    assert following["snapshot"]["parent_assessment"]["assessment_id"] == saved["assessment_id"]
    assessment.basis_result_sha256 = "0" * 64
    with pytest.raises(ValueError, match="RESULT_CHANGED"):
        research.save_assessment(run["run_id"], assessment, result)
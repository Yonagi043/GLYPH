def test_completed_host_without_raw_return_requires_explicit_finalization(tmp_path, monkeypatch):
    from pathlib import Path
    from glyph_features.workbench.catalog import Catalog
    from glyph_features.workbench.materials import MaterialCatalog
    from glyph_features.workbench.research import ResearchService, StudyConfig
    from glyph_features.workbench.personas import PersonaExecutor

    root = Path(__file__).resolve().parents[1]
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(root), root)
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    run = research.create(StudyConfig(name="Missing host return fixture", question="Engineering evidence handling only?", explanations=["fixture"], selections=[{"material_id": sample["material_id"], "reason": "engineering fixture"}], roles=["baseline"], orders=["forward"], selection_scope="Engineering fixture only", stopping_rule="No actual model calls"))
    executor = PersonaExecutor(research)
    task = executor.prepare(run["run_id"])[0]
    executor.claim(run["run_id"])
    events = {"fixture-parent": {"toolId": "runSubagent", "toolCallId": "fixture-parent", "isComplete": True, "toolSpecificData": {"prompt": task["prompt_path"]}}}
    monkeypatch.setattr("glyph_features.workbench.personas.host_events", lambda session: events)
    executor.ingest(run["run_id"], tmp_path / "fixture.jsonl")
    assert executor.tasks(run["run_id"])[0]["attempts"] == []
    executor.ingest(run["run_id"], tmp_path / "fixture.jsonl", finalize_evidence=True)
    attempt = executor.tasks(run["run_id"])[0]["attempts"][0]
    assert attempt["status"] == "failed"
    assert attempt["ratings"] == []
    assert "HOST_RAW_RETURN_NOT_PERSISTED" in attempt["evidence"]["validation_issues"]
    assert not attempt["evidence"]["analysis_eligible"]

import json
from pathlib import Path

import pytest

from glyph_features.workbench.catalog import Catalog, CatalogError
from glyph_features.workbench.materials import MaterialCatalog
from glyph_features.workbench.personas import PersonaExecutor
from glyph_features.workbench.research import ResearchService, StudyConfig


ROOT = Path(__file__).resolve().parents[1]


def test_task_queue_raw_return_and_visual_evidence(tmp_path):
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    material = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = StudyConfig(name="Executor engineering check", question="Is the displayed form aesthetically pleasing?", explanations=["form"], selections=[{"material_id":material["material_id"], "reason":"existing sample"}], roles=["baseline"], orders=["forward"], selection_scope="Other materials outside the unit test.", stopping_rule="One engineering task only, not a research finding.")
    run = research.create(config)
    executor = PersonaExecutor(research)
    tasks = executor.prepare(run["run_id"])
    assert len(tasks) == 1
    claim = executor.claim(run["run_id"])
    assert claim["task_id"] == tasks[0]["task_id"]
    assert executor.claim(run["run_id"]) is None
    assert PersonaExecutor(research).tasks(run["run_id"])[0]["status"] == "leased"
    assert executor.pending(run["run_id"]) == [claim]
    task = tasks[0]
    raw = json.dumps({"task_id": task["task_id"], "data_type": "synthetic_persona", "visual_input_received": True, "ratings": [{"material_id": material["material_id"], "aesthetic": 99, "visual_clarity": 4, "visible_detail": "ENGINEERING_FIXTURE_ONLY"}]})
    parent = {"toolId": "runSubagent", "toolCallId": "fixture-parent", "isComplete": True, "toolSpecificData": {"prompt": claim["invocation_prompt"], "result": raw}}
    session = tmp_path / "engineering-host.jsonl"
    session.write_text(json.dumps(parent) + "\n")
    assert executor.ingest(run["run_id"], session)["awaiting_host_evidence"]
    pending = executor.tasks(run["run_id"])[0]
    assert pending["attempts"][0]["raw_return"] == raw
    assert pending["status"] == "awaiting_evidence"
    assert executor.pending(run["run_id"]) == []
    assert pending["attempts"][0]["evidence"]["analysis_eligible"] is False
    executor.ingest(run["run_id"], session, finalize_evidence=True)
    assert executor.tasks(run["run_id"])[0]["status"] == "failed"
    executor.retry(run["run_id"], task["task_id"])
    executor.ingest(run["run_id"], session)
    assert executor.tasks(run["run_id"])[0]["status"] == "queued"
    child = {"toolId":"copilot_viewImage", "toolCallId":"fixture-image", "isComplete":True, "subAgentInvocationId":"fixture-parent", "invocationMessage":task["inputs"][0]["path"]}
    session.write_text(json.dumps(parent) + "\n" + json.dumps(child) + "\n")
    result = executor.ingest(run["run_id"], session)
    attempt = result["tasks"][0]["attempts"][0]
    assert attempt["raw_return"] == raw
    assert attempt["ratings"][0]["aesthetic"] is None
    assert attempt["evidence"]["model_display_name"] == "unknown"
    assert result["tasks"][0]["status"] == "completed_with_missing"
    assert len(executor.ingest(run["run_id"], session)["tasks"][0]["attempts"]) == 1
    assert executor.claim(run["run_id"]) is None
    with pytest.raises(CatalogError, match="ONLY_FAILED"):
        executor.retry(run["run_id"], task["task_id"])
    unrelated = {"toolId":"copilot_readFile", "toolCallId":"fixture-context", "isComplete":True, "subAgentInvocationId":"fixture-parent", "invocationMessage":"AUTORESEARCH.md"}
    session.write_text(json.dumps(parent) + "\n" + json.dumps(child) + "\n" + json.dumps(unrelated) + "\n")
    result = executor.ingest(run["run_id"], session)
    assert result["tasks"][0]["status"] == "protocol_deviation"
    assert result["tasks"][0]["attempts"][0]["raw_return"] == raw
    assert result["tasks"][0]["attempts"][0]["evidence"]["analysis_eligible"] is False
    executor.suspend(run["run_id"])
    assert research.get(run["run_id"])["status"] == "suspended"
    executor.resume(run["run_id"])
    assert executor.tasks(run["run_id"])[0]["status"] == "protocol_deviation"
    assert executor.claim(run["run_id"]) is None


def test_invalid_return_preserves_failure_not_fabricated_ratings():
    assert PersonaExecutor.validate_return({"task_id":"example", "inputs":[]}, "not json") == ([], ["RAW_RETURN_NOT_JSON"])


def test_explicit_plan_and_actual_image_order(tmp_path):
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    samples = research.materials.search(kind="existing_font_sample")[:3]
    material_ids = [item["material_id"] for item in samples]
    from itertools import permutations
    config = StudyConfig(
        name="Explicit order fixture", question="Engineering sequence check only?",
        explanations=["fixture"], roles=["baseline"], orders=["forward"],
        selections=[{"material_id": material_id, "reason": "engineering fixture"} for material_id in material_ids],
        selection_scope="Engineering fixture only", stopping_rule="No model calls",
        design_version="explicit-sequence-test-v1",
        presentation_plan=[{"condition_id": str(index), "group_id": "content", "material_ids": list(order)} for index, order in enumerate(permutations(material_ids))],
    )
    run = research.create(config)
    executor = PersonaExecutor(research)
    tasks = executor.prepare(run["run_id"])
    assert [[image["material_id"] for image in task["inputs"]] for task in tasks] == [list(order) for order in permutations(material_ids)]
    task = tasks[0]
    rows = [{"material_id": material_id, "aesthetic": 4, "visual_clarity": 4, "visible_detail": "FIXTURE"} for material_id in material_ids]
    raw = json.dumps({"task_id": task["task_id"], "data_type": "synthetic_persona", "visual_input_received": True, "ratings": rows})
    parent = {"toolId": "runSubagent", "toolCallId": "parent", "isComplete": True, "toolSpecificData": {"prompt": task["prompt_path"], "result": raw}}
    children = [{"toolId": "copilot_viewImage", "toolCallId": f"image-{index}", "isComplete": True, "subAgentInvocationId": "parent", "invocationMessage": image["path"]} for index, image in enumerate(task["inputs"])]
    session = tmp_path / "host.jsonl"
    session.write_text("\n".join(json.dumps(event) for event in [parent, *reversed(children)]))
    attempt = executor.ingest(run["run_id"], session)["tasks"][0]["attempts"][0]
    assert attempt["status"] == "protocol_deviation"
    assert not attempt["evidence"]["analysis_eligible"]
    assert "HOST_IMAGE_SEQUENCE_MISMATCH" in attempt["evidence"]["validation_issues"]
    session.write_text("\n".join(json.dumps(event) for event in [parent, *children]))
    attempt = executor.ingest(run["run_id"], session)["tasks"][0]["attempts"][0]
    assert attempt["status"] == "completed"
    assert attempt["evidence"]["actual_image_sequence"] == material_ids
    assert attempt["evidence"]["analysis_eligible"]
    parsed = json.loads(raw)
    parsed["ratings"].reverse()
    parent["toolSpecificData"]["result"] = json.dumps(parsed)
    session.write_text("\n".join(json.dumps(event) for event in [parent, *children]))
    attempt = executor.ingest(run["run_id"], session)["tasks"][0]["attempts"][0]
    assert attempt["status"] == "protocol_deviation"
    assert not attempt["evidence"]["analysis_eligible"]


def test_exact_slot_set_contrasts_do_not_match_other_positions():
    from glyph_features.workbench.research_results import summarize_presentation_pairs
    common = {"group_id": "text", "reference_material_id": "sans", "comparison_material_id": "serif", "reference_position": 1, "comparison_position": 2, "role": "baseline", "repetition": 0, "language": "en", "wording": "background", "model_display_name": "fixture"}
    pair = {**common, "task_id": "pair", "set_size": 2, "differences": {"aesthetic": 0}}
    triple = {**common, "task_id": "triple", "set_size": 3, "differences": {"aesthetic": 1}}
    unmatched = {**triple, "task_id": "unmatched", "reference_position": 2, "comparison_position": 3}
    result = summarize_presentation_pairs([pair, triple, unmatched])
    assert len(result["matched_slot_set_contrasts"]) == 1
    assert result["matched_slot_set_contrasts"][0]["difference_of_differences"] == 1


def test_measurement_bridge_items_and_not_collected(tmp_path):
    from glyph_features.workbench.research import QUESTIONNAIRE_SCALES
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = StudyConfig(name="Bridge fixture", question="Are outcomes measured separately?", explanations=["fixture"], selections=[{"material_id": sample["material_id"], "reason": "engineering fixture"}], roles=["baseline"], orders=["forward"], selection_scope="Engineering only", stopping_rule="No model calls", presentation_mode="measurement_bridge", repetitions=2)
    run = research.create(config)
    tasks = PersonaExecutor(research).prepare(run["run_id"])
    assert len(tasks) == 8
    for task in tasks:
        assert run["run_id"] not in task["prompt_path"]
        assert all(run["run_id"] not in image["path"] for image in task["inputs"])
        mode = task["condition"]["questionnaire_mode"]
        scales = QUESTIONNAIRE_SCALES[mode]
        prompt = Path(task["prompt_path"]).read_text()
        assert "synthetic_persona-q3" in prompt
        assert ("premium_positioning" in prompt) == ("premium_positioning" in scales)
        rating = {"material_id": sample["material_id"], **{scale: 4 for scale in scales}, "visible_detail": "FIXTURE"}
        raw = {"task_id": task["task_id"], "data_type": "synthetic_persona", "visual_input_received": True, "ratings": [rating]}
        rows, issues = PersonaExecutor.validate_return(task, json.dumps(raw))
        assert not issues
        for scale in ("aesthetic", "visual_clarity", "premium_positioning"):
            assert rows[0]["outcome_status"][scale] == ("observed" if scale in scales else "not_collected")
        if mode == "aesthetic_only":
            rating["premium_positioning"] = 4
            assert "UNPRESENTED_OUTCOME_SCORED" in PersonaExecutor.validate_return(task, json.dumps(raw))[1]
    config.bridge_modes = ["aesthetic_premium", "premium_aesthetic"]
    dual_run = research.create(config)
    dual_tasks = PersonaExecutor(research).prepare(dual_run["run_id"])
    assert len(dual_tasks) == 4
    assert {task["condition"]["questionnaire_mode"] for task in dual_tasks} == set(config.bridge_modes)


def test_automatic_triplet_pairs_cover_slots_and_repetitions(tmp_path):
    from itertools import permutations

    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    samples = research.materials.search(kind="existing_font_sample")[:3]
    material_ids = [sample["material_id"] for sample in samples]
    font_ids = [f"fixture-font-{index}" for index in range(3)]
    for sample, font_id in zip(samples, font_ids):
        research.materials.items[sample["material_id"]]["sample_provenance"] = {
            "content": "fixture-only", "font_asset_id": font_id,
        }
    config = StudyConfig(
        name="Automatic triplet fixture", question="Scheduling only?",
        explanations=["fixture"], roles=["baseline"], orders=["forward"],
        selections=[{"material_id": material_id, "reason": "engineering fixture"} for material_id in material_ids],
        presentation_mode="triplet_pairs", focal_font_ids=font_ids[:2], repetitions=2,
        selection_scope="Fixture images, not three matched fonts", stopping_rule="No model calls",
    )
    run = research.create(config)
    executor = PersonaExecutor(research)
    tasks = executor.prepare(run["run_id"])
    assert len(tasks) == 16
    expected = set(permutations(material_ids)) | {tuple(material_ids[:2]), tuple(reversed(material_ids[:2]))}
    for repetition in range(2):
        cycle = [task for task in tasks if task["condition"]["repetition"] == repetition]
        assert {tuple(image["material_id"] for image in task["inputs"]) for task in cycle} == expected
        triplets = [task for task in cycle if len(task["inputs"]) == 3]
        for slot in range(3):
            assert all(sum(task["inputs"][slot]["material_id"] == material_id for task in triplets) == 2 for material_id in material_ids)
    assert research.create(config)["config"]["presentation_plan"] == run["config"]["presentation_plan"]
    config.selections = config.selections[:2]
    with pytest.raises(CatalogError, match="EACH_CONTENT_REQUIRES_THREE_FONTS_WITH_FOCAL_PAIR"):
        research.create(config)


@pytest.mark.parametrize("mode", ["aesthetic_pair", "aesthetic_pair_only"])
def test_pair_choice_prompt_raw_and_not_collected(tmp_path, mode):
    research = ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)
    sample = research.materials.search(kind="existing_font_sample")[0]
    config = StudyConfig(name="Pair parser fixture", question="Choice preservation?", explanations=["fixture"], selections=[{"material_id": sample["material_id"], "reason": "engineering fixture"}], roles=["baseline"], orders=["forward"], questionnaire_mode=mode, selection_scope="Not a real paired stimulus", stopping_rule="No model calls")
    run = research.create(config)
    executor = PersonaExecutor(research)
    task = executor.prepare(run["run_id"])[0]
    prompt = Path(task["prompt_path"]).read_text()
    assert ("heavier_choice" in prompt) == (mode == "aesthetic_pair")
    assert ("thicker strokes" in prompt) == (mode == "aesthetic_pair")
    rating = {"material_id": sample["material_id"], "preference_choice": "B", **({"heavier_choice": "A"} if mode == "aesthetic_pair" else {}), "visible_detail": "FIXTURE_ONLY"}
    raw = {"task_id": task["task_id"], "data_type": "synthetic_persona", "visual_input_received": True, "ratings": [rating]}
    rows, issues = executor.validate_return(task, json.dumps(raw))
    assert not issues and rows[0]["preference_choice"] == "B"
    assert rows[0]["aesthetic"] is None and rows[0]["outcome_status"]["aesthetic"] == "not_collected"
    parent = {"toolId": "runSubagent", "toolCallId": "parent", "isComplete": True, "toolSpecificData": {"prompt": task["prompt_path"], "result": json.dumps(raw)}}
    image = {"toolId": "copilot_viewImage", "toolCallId": "image", "isComplete": True, "subAgentInvocationId": "parent", "invocationMessage": task["inputs"][0]["path"]}
    session = tmp_path / "host.jsonl"
    session.write_text("\n".join(json.dumps(event) for event in [parent, image]))
    assert executor.ingest(run["run_id"], session)["tasks"][0]["attempts"][0]["ratings"][0]["preference_choice"] == "B"
    import csv
    import io
    import zipfile
    from glyph_features.workbench.research_results import analyze_research, export_research
    result = analyze_research(research, executor, run["run_id"])
    assert result["paired_choices"][0]["preference_choice"] == "B"
    assert result["materials"][0]["planned_observations"] == 0
    exported = export_research(result, tmp_path / "exports")
    with zipfile.ZipFile(exported["path"]) as archive:
        exported_row = next(csv.DictReader(io.StringIO(archive.read("ratings.csv").decode())))
        assert exported_row["preference_choice"] == "B"
        assert exported_row["heavier_choice"] == ("A" if mode == "aesthetic_pair" else "")
        assert exported_row["aesthetic_status"] == "not_collected"
    rating["preference_choice"] = "C"
    assert executor.validate_return(task, json.dumps(raw))[1] == ["PAIR_CHOICE_INVALID"]
    rating["preference_choice"] = "unable"
    assert executor.validate_return(task, json.dumps(raw))[1] == ["PAIR_MISSING_REASON_REQUIRED"]
    rating["preference_choice"] = "tie"
    rating["aesthetic"] = 7
    assert "UNPRESENTED_OUTCOME_SCORED" in executor.validate_return(task, json.dumps(raw))[1]
    del rating["aesthetic"]
    if mode == "aesthetic_pair":
        rating["preference_choice"] = rating.pop("preference_choice")
    else:
        rating["heavier_choice"] = "A"
    assert executor.validate_return(task, json.dumps(raw))[1] == ["QUESTION_ITEM_ORDER_OR_COVERAGE_MISMATCH"]
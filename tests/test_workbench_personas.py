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
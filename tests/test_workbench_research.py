from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from glyph_features.workbench.app import create_app
from glyph_features.workbench.catalog import Catalog
from glyph_features.workbench.materials import MaterialCatalog
from glyph_features.workbench.research import FontSampleConfig, ResearchService, StudyConfig
from glyph_features.workbench.personas import PersonaExecutor


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def research(tmp_path, unapproved_research_uses):
    return ResearchService(Catalog(tmp_path / "catalog.sqlite3"), MaterialCatalog(ROOT), ROOT)


def config_for(material_id):
    return StudyConfig(
        name="Existing sample comparison",
        question="Which existing sample looks more aesthetically pleasing?",
        explanations=["visual form", "prompted familiarity"],
        selections=[{"material_id": material_id, "reason": "existing controlled sample"}],
        selection_scope="Other materials are outside this content-matched comparison.",
        stopping_rule="Complete matched order/identity conditions, then assess missingness and variability.",
    )


def test_measure_existing_font_reopens_without_recomputing(research):
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = config_for(sample["material_id"])
    created = research.create(config)
    measured = research.measure(created["run_id"])
    assert measured["status"] == "measured"
    assert len(measured["measurements"][0]["thresholds"]) == 3
    assert measured["measurements"][0]["measurement_kind"] == "B_shape"
    assert research.create(config) == measured
    assert research.measure(created["run_id"]) == measured
    reopened = ResearchService(research.catalog, research.materials, ROOT)
    assert reopened.get(created["run_id"]) == measured


def test_controlled_font_render_sets_weight_and_preserves_canvas(research):
    variable = next(item for item in research.materials.search(kind="font_file") if "NotoSansSC-Variable" in item["representations"]["original"]["path"])
    serif = next(item for item in research.materials.search(kind="font_file") if "NotoSerifSC-Regular.otf" in item["representations"]["original"]["path"])
    config = FontSampleConfig(font_ids=[variable["material_id"], serif["material_id"]], texts=["城市书店"], weight=400)
    samples = research.render_font_samples(config)
    assert len(samples) == 2
    assert samples[0]["sample_provenance"]["variation_axes"]["wght"] == 400
    assert samples[1]["sample_provenance"]["weight"] == 400
    assert research.render_font_samples(config) == samples
    reopened = ResearchService(research.catalog, MaterialCatalog(ROOT), ROOT)
    for sample in samples:
        with Image.open(reopened.materials.image_path(sample["material_id"], "original")) as image:
            assert image.size == (1280, 320)
            assert image.getextrema() == (0, 255)
        study_config = config_for(sample["material_id"])
        study_config.selections[0].representation = "original"
        run = reopened.create(study_config)
        assert not run["snapshot"]["blockers"]
        assert reopened.measure(run["run_id"])["measurements"][0]["measurement_kind"] == "B_shape"
    with pytest.raises(ValueError, match="MISSING_CHARACTERS"):
        research.render_font_samples(config.model_copy(update={"texts": ["\U0010ffff"]}))
    with pytest.raises(ValueError, match="DOES_NOT_FIT"):
        research.render_font_samples(config.model_copy(update={"texts": ["城" * 40]}))


def test_unapproved_commercial_material_is_persistently_blocked(research):
    item = research.materials.search(award="Indigo")[0]
    run = research.create(config_for(item["material_id"]))
    assert run["status"] == "blocked"
    assert {item["use"] for item in run["snapshot"]["blockers"]} == {"local_analysis", "model_input"}
    measured = research.measure(run["run_id"])
    assert measured["measurements"][0]["status"] == "blocked"
    assert measured["snapshot"]["data_origin"] == "synthetic_persona"
    config = config_for(item["material_id"]).model_dump()
    config["orders"] = []
    with pytest.raises(ValueError):
        StudyConfig.model_validate(config)


def test_study_http_configuration_and_recovery(tmp_path):
    app = create_app(ROOT, catalog_database=tmp_path / "catalog.sqlite3", social_database=tmp_path / "unused.sqlite3", export_root=tmp_path / "export", backup_root=tmp_path / "backup", restore_root=tmp_path / "restore", material_root=ROOT)
    with TestClient(app) as client:
        item = next(item for item in app.state.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/research", json=config_for(item["material_id"]).model_dump(), headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        assert client.get(f"/api/research/{run_id}").json() == response.json()
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post(f"/api/research/{run_id}/measure", headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert response.status_code == 200
        assert response.json()["status"] == "measured"
        assert len(client.get("/api/research").json()["runs"]) == 1
        token = client.get("/api/session").json()["csrf_token"]
        prepared = client.post(f"/api/research/{run_id}/tasks", headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert prepared.status_code == 200
        tasks = client.get(f"/api/research/{run_id}/tasks").json()
        assert tasks["backend_can_call_subagent"] is False
        assert len(tasks["tasks"]) == 4
        result = client.get(f"/api/research/{run_id}/results")
        assert result.status_code == 200
        assert result.json()["actual_calls"] == 0
        assessment = {"basis_result_sha256": result.json()["result_sha256"], "conclusion": "Engineering check: there are no actual responses.", "explanation_updates": [{"explanation": "visual form", "judgment": "unresolved", "evidence": "No ratings yet in this fixture.", "material_ids": [item["material_id"]]}], "remaining_confounds": ["No actual model calls"], "next_question": "Does the same form change after color removal?", "next_comparison": "Keep content and geometry fixed while changing the color mode.", "decision": "new_comparison"}
        token = client.get("/api/session").json()["csrf_token"]
        saved = client.post(f"/api/research/{run_id}/assessments", json=assessment, headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert saved.status_code == 201
        assert client.get(f"/api/research/{run_id}/assessments").json()["assessments"][0]["basis_result"] == result.json()
        continued = client.get(f"/api/research-assessments/{saved.json()['assessment_id']}/continue").json()["config"]
        assert continued["question"] == assessment["next_question"]
        assert client.get(f"/api/research/{run_id}/results").json()["research_assessments"][0]["conclusion"] == assessment["conclusion"]
        token = client.get("/api/session").json()["csrf_token"]
        exported = client.post(f"/api/research/{run_id}/export", headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert exported.status_code == 200
        assert exported.json()["manifest"]["images_included"] is False
        assert client.get(exported.json()["download_url"]).status_code == 200
        assert client.get("/api/research-exports/invalid").status_code == 422
        token = client.get("/api/session").json()["csrf_token"]
        rendered = client.post("/api/research/font-samples", json={"font_ids": [item["font_asset_id"]], "texts": ["Bookshop"]}, headers={"Origin": "http://localhost", "X-GLYPH-CSRF": token})
        assert rendered.status_code == 201
        sample_id = rendered.json()["items"][0]["material_id"]
        assert client.get(f"/api/materials/{sample_id}/image/original").status_code == 200
        assert not (tmp_path / "unused.sqlite3").exists()


def test_scoped_commercial_use_preserves_history_and_exclusions(research, monkeypatch):
    item = research.materials.search(award="Indigo")[0]
    config = config_for(item["material_id"])
    previous = research.create(config)
    source_path = "data/fixtures/asset_system/reference_handoff_v1/sources.jsonl"
    decision = {
        "version": "research_material_uses_1", "decision_id": "engineering_fixture_only",
        "basis": "user_declared_open", "model_channel": "existing_copilot",
        "scope": {"source_catalog_path": source_path, "source_catalog_sha256": research.materials.manifest_hashes[source_path],
                  "candidate_kind": "ecological_award_image", "original_path_prefix": "图包与字体包/图包/"},
        "uses": ["local_analysis", "model_input"], "restrictions": [],
    }
    changed = deepcopy(item)
    changed["material_id"] = "outside_fixture"
    changed["representations"]["original"]["sha256"] = "0" * 64
    research.materials.items[changed["material_id"]] = changed
    research.materials._apply_research_use_decision(decision)
    assert changed["use_status"]["model_input"] == "needs_use_evidence"
    assert sum(record["use_status"]["model_input"].startswith("allowed") for record in research.materials.search(kind="ecological_award_image")) == 375
    assert item["use_status"]["redistribution"] == "not_authorized"
    assert item["candidate"]["rights_tier"] == "blocked_unknown"
    current = research.create(config)
    assert current["status"] == "configured"
    assert current["run_id"] != previous["run_id"]
    assert research.get(previous["run_id"]) == previous
    measured = research.measure(current["run_id"])
    assert measured["measurements"][0]["measurement_kind"] == "A_layout"
    executor = PersonaExecutor(research)
    executor.prepare(current["run_id"])
    assert executor.claim(current["run_id"])["task_id"]
    restricted = deepcopy(decision)
    restricted["restrictions"] = [{"material_id": item["material_id"], "sha256": item["representations"]["original"]["sha256"],
                                   "uses": ["model_input"], "source_url": "https://example.invalid/fixture-terms", "quote": "Engineering restriction fixture, not actual material terms."}]
    research.materials._apply_research_use_decision(restricted)
    assert item["use_status"]["local_analysis"].startswith("allowed")
    assert item["use_status"]["model_input"] == "blocked_explicit_use_restriction"
    restricted_run = research.create(config)
    assert {blocker["use"] for blocker in restricted_run["snapshot"]["blockers"]} == {"model_input"}
    clean = MaterialCatalog(ROOT)
    wrong_scope = deepcopy(decision)
    wrong_scope["scope"]["source_catalog_sha256"] = "0" * 64
    clean._apply_research_use_decision(wrong_scope)
    assert clean.items[item["material_id"]]["use_status"]["model_input"] == "needs_use_evidence"
    def changed_file(*args):
        raise ValueError("fixture changed file")
    monkeypatch.setattr("glyph_features.workbench.materials.resolve_workspace_asset", changed_file)
    clean._apply_research_use_decision(decision)
    assert clean.items[item["material_id"]]["use_status"]["model_input"] == "needs_use_evidence"


def test_selected_region_is_the_measured_and_questionnaire_input(research):
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = config_for(sample["material_id"])
    config.selections[0].crop_box = (10, 15, 110, 95)
    run = research.create(config)
    selected = run["snapshot"]["materials"][0]
    input_path = research.input_image(run["run_id"], sample["material_id"])
    assert Image.open(input_path).size == (100, 80)
    assert selected["input_sha256"] != selected["source_input_sha256"]
    assert research.create(config) == run
    executor = PersonaExecutor(research)
    executor.prepare(run["run_id"])
    assert executor.tasks(run["run_id"])[0]["inputs"][0]["sha256"] == selected["input_sha256"]
    assert research.get(run["run_id"])["measurements"][0]["crop_box"] == [10, 15, 110, 95]
    config.selections[0].crop_box = (0, 0, 999999, 95)
    invalid = research.create(config)
    assert invalid["status"] == "blocked"
    assert invalid["snapshot"]["blockers"][0]["reason"] == "STUDY_CROP_OUTSIDE_IMAGE"


def test_layout_keeps_values_without_inapplicable_skeleton_work(monkeypatch):
    import numpy as np
    from glyph_features.vision_system import extract
    from glyph_features.vision_system.definitions import load_registry

    registry = load_registry(ROOT / "configs/visual_measurements_v2.yaml", ROOT / "schema")
    array = np.full((80, 100), 255, dtype=np.uint8)
    array[10:60, 20:70] = 0
    array[25:45, 35:55] = 255
    defaults = registry.payload["algorithm_defaults"]
    reference = extract._binary_metrics(array < 128, component_connectivity=int(defaults["component_connectivity"]), hole_connectivity=int(defaults["hole_connectivity"]), skeleton_algorithm=str(defaults["skeleton_algorithm"]), symmetry_alignment=str(defaults["symmetry_alignment"]))
    def forbidden_skeleton(*args):
        raise AssertionError("inapplicable skeleton calculation")
    monkeypatch.setattr(extract, "skeletonize", forbidden_skeleton)
    measured = extract.measure_array(array, "A_layout", registry, binary_threshold=128)
    for definition in registry.definitions:
        code = definition["feature_code"]
        if "A_layout" in definition["input_representations"]:
            assert measured[code] == reference.get(code, extract.Metric(None, missing_code="MEASUREMENT_NOT_IMPLEMENTED"))
        else:
            assert measured[code].missing_code == "REPRESENTATION_NOT_APPLICABLE"


def test_confirmed_text_polarity_and_preview_match_frozen_input(research):
    import io
    import numpy as np
    from glyph_features.workbench.research import MaterialSelection, measurement_array, representation_preview

    pixels = np.zeros((80, 100), dtype=np.uint8)
    pixels[20:60, 30:70] = 255
    image = Image.fromarray(pixels)
    assert (measurement_array(image, "light") < 128).sum() == 1600
    assert (np.asarray(representation_preview(image, "light", "mask")) == 0).sum() == 1600
    assert np.asarray(representation_preview(image, "light", "overlay"))[30, 40, 1] < 255
    with pytest.raises(ValueError, match="TEXT_REGION_REQUIRES"):
        MaterialSelection(material_id="fixture", reason="test", foreground="light")
    sample = next(item for item in research.materials.search(kind="existing_font_sample") if "Lato-Regular" in item["representations"]["original"]["path"])
    config = config_for(sample["material_id"])
    config.selections[0].crop_box = (10, 15, 110, 95)
    config.selections[0].foreground = "dark"
    config.selections[0].foreground_note = "Engineering fixture only; not an observation of real commercial text."
    run = research.create(config)
    preview = Image.open(io.BytesIO(research.preview(config.selections[0])))
    frozen = Image.open(run["snapshot"]["materials"][0]["input_path"])
    assert np.array_equal(np.asarray(preview), np.asarray(frozen))
    measured = research.measure(run["run_id"])["measurements"][0]
    assert measured["measurement_kind"] == "B_shape"
    assert measured["mask"]["source_input_sha256"] == run["snapshot"]["materials"][0]["input_sha256"]
    assert measured["scope"] == "exploratory_observer_confirmed_text_region_not_expert_reviewed"


def test_color_conversion_grouped_tasks_and_denominators(research):
    import io
    import numpy as np
    from glyph_features.workbench.research import MaterialSelection, transform_image
    from glyph_features.workbench.research_results import analyze_research

    selection = MaterialSelection(material_id="fixture", reason="engineering test", color_mode="grayscale")
    image = Image.new("RGB", (300, 200), (180, 60, 30))
    converted = transform_image(image, selection)
    assert converted.size == image.size
    assert np.array_equal(np.asarray(converted.convert("L")), np.asarray(image.convert("L")))
    assert np.array_equal(np.asarray(converted)[:, :, 0], np.asarray(converted)[:, :, 2])
    selection.max_edge = 150
    assert transform_image(image, selection).size == (150, 100)
    samples = [item for item in research.materials.search(kind="existing_font_sample") if "Lato-" in item["representations"]["original"]["path"]]
    config = config_for(samples[0]["material_id"])
    config.task_size = 1
    config.selections = [MaterialSelection(material_id=item["material_id"], reason="engineering comparison", color_mode="grayscale", max_edge=160) for item in samples]
    run = research.create(config)
    for record, selected in zip(run["snapshot"]["materials"], config.selections):
        assert np.array_equal(np.asarray(Image.open(record["input_path"])), np.asarray(Image.open(io.BytesIO(research.preview(selected)))))
    executor = PersonaExecutor(research)
    tasks = executor.prepare(run["run_id"])
    assert len(tasks) == 8
    assert all(len(task["inputs"]) == 1 for task in tasks)
    executor.claim(run["run_id"])
    before = executor.tasks(run["run_id"])
    assert executor.prepare(run["run_id"]) == before
    result = analyze_research(research, executor, run["run_id"])
    assert all(item["planned_observations"] == 4 for item in result["materials"])
    assert all(item["missing_or_unexecuted"] == 4 for item in result["materials"])
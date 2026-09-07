from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.workbench.app import create_app
from glyph_features.workbench.materials import MaterialCatalog


ROOT = Path(__file__).resolve().parents[1]


def test_existing_materials_link_full_paths_and_keep_use_boundaries(unapproved_research_uses):
    materials = MaterialCatalog(ROOT)
    summary = materials.summary()
    assert summary["repository_candidates"] == 388
    assert summary["unique_image_hashes"] == 372
    assert summary["unique_works"] == 358
    assert summary["auxiliary_font_files"] >= 7
    assert summary["kinds"]["font_file"] == 13 + summary["auxiliary_font_files"]
    assert materials.items["font_noto_sans_latn"]["auxiliary_font_inventory"]["file_hash_verified_against_inventory"]
    assert materials.items["font_noto_sans_latn"]["use_status"]["local_analysis"] == "allowed_existing_inventory_OFL_1.1"
    assert materials.items["font_noto_sans_latn"]["use_status"]["model_input"] == "not_applicable_font_binary"
    assert summary["awards"] == {"DFA": 80, "GDC": 46, "Golden Pin": 72, "Indigo": 90, "WOLDA": 87}
    assert summary["standardized_matched"] == 388
    repeated = next(item for item in materials.items.values() if item.get("same_image_ids"))
    for related_id in repeated["same_image_ids"]:
        assert materials.items[related_id]["representations"]["original"]["sha256"] == repeated["representations"]["original"]["sha256"]
    assert any(item.get("same_work_ids") for item in materials.items.values())
    assert not summary["missing_files"]
    assert len(summary["unmatched_transforms"]) == 2
    assert all(not row["source_exists"] for row in summary["unmatched_transforms"])
    assert all(row["source"].endswith("preloader.png") for row in summary["unmatched_transforms"])
    for award in ("Indigo", "DFA"):
        item = materials.search(award=award)[0]
        assert item["source"]["source_id"] == item["candidate"]["source_id"]
        assert item["candidate"]["rights_tier"] == "blocked_unknown"
        assert item["use_status"]["model_input"] == "needs_use_evidence"
        assert materials.image_path(item["material_id"], "original").is_file()
        assert materials.image_path(item["material_id"], "standardized").is_file()
    samples = materials.search(kind="existing_font_sample")
    assert len(samples) == 13
    assert materials.image_path(samples[0]["material_id"], "standardized").is_file()
    assert all(item.get("font_asset_id") for item in samples)
    eligible = [item for item in samples if item["use_status"]["model_input"].startswith("allowed") and not item["sample_provenance"]["missing_characters"]]
    assert len(eligible) == 11
    ma_shan = next(item for item in samples if "MaShanZheng" in item["representations"]["original"]["path"])
    assert set(ma_shan["sample_provenance"]["missing_characters"]) == set("東國龍鳳")
    assert ma_shan["use_status"]["study_eligibility"] == "blocked_missing_characters"
    with pytest.raises(ValueError):
        materials.safe_path("../outside.png")


def test_material_root_can_be_explicit_without_copying_assets():
    materials = MaterialCatalog(ROOT)
    material_id = materials.search(award="GDC")[0]["material_id"]
    reopened = MaterialCatalog(ROOT)
    assert reopened.items[material_id] == materials.items[material_id]


def test_registered_use_decision_is_loaded_without_releasing_assets():
    materials = MaterialCatalog(ROOT)
    commercial = materials.search(kind="ecological_award_image")
    assert len(commercial) == 375
    decision_path = "configs/research_material_uses_v1.json"
    for item in commercial:
        assert item["use_status"]["local_analysis"] == "allowed_user_declared_open_A11"
        assert item["use_status"]["model_input"] == "allowed_user_declared_open_A11"
        assert item["use_status"]["redistribution"] == "not_authorized"
        assert item["candidate"]["rights_tier"] == "blocked_unknown"
        evidence = item["research_use_decision"]
        assert evidence["decision_path"] == decision_path
        assert evidence["decision_sha256"] == materials.manifest_hashes[decision_path]
        assert evidence["formal_rights_gate_changed"] is False


def test_material_api_uses_explicit_root_and_does_not_initialize_social(tmp_path):
    app = create_app(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "absent-social.sqlite3",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
        material_root=ROOT,
    )
    with TestClient(app) as client:
        response = client.get("/api/materials", params={"award": "Indigo", "limit": 2})
        assert response.status_code == 200
        assert response.json()["total"] == 90
        item = response.json()["items"][0]
        material_id = item["material_id"]
        assert client.get(f"/api/materials/{material_id}").json() == item
        image = client.get(f"/api/materials/{material_id}/image/standardized")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert client.get("/api/materials/unknown").status_code == 404
        assert client.get("/api/materials?limit=0").status_code == 422
    assert not (tmp_path / "absent-social.sqlite3").exists()
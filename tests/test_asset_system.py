from __future__ import annotations

import copy
import csv
import json
import runpy
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from glyph_features.asset_system.catalog import (
    load_json_config,
    build_open_fixture,
    build_repository_inventory,
    migrate_award_sources,
    normalize_repo_path,
    sha256_file,
    stable_id,
    validate_record,
)
from glyph_features.asset_system.qc import duplicate_annotations, inspect_image, script_purity_violations
from glyph_features.asset_system.curation import apply_curation_decisions, build_review_queue, freeze_ecological_stimulus
from glyph_features.asset_system.rights import build_rights_evidence, freeze_blockers, release_blockers
from glyph_features.asset_system.transform import RepresentationNotApplicable, transform_candidate
from glyph_features.asset_system.export import build_handoff_bundle, validate_handoff
from glyph_features.asset_system.cli import (
    EXIT_NO_OVERWRITE,
    EXIT_OPERATION_ERROR,
    EXIT_RECORD_FAILURE,
    main as asset_cli,
)


ROOT = Path(__file__).parents[1]


def candidate_record() -> dict:
    return {
        "schema_version": "1.0.0",
        "asset_id": "asset_fixture_original",
        "record_origin": "generated_fixture",
        "source_id": "source_fixture_open",
        "parent_asset_id": None,
        "work_id": "work_fixture_wordmark",
        "asset_role": "original",
        "candidate_kind": "isolated_wordmark",
        "asset_ref": {
            "path": "data/fixtures/asset_system/open_fixture.ppm",
            "sha256": "a" * 64,
            "mime_type": "image/x-portable-pixmap",
            "byte_size": 128,
        },
        "pixel_metadata": {
            "width_px": 16,
            "height_px": 12,
            "mode": "RGB",
            "color_space": "sRGB",
            "has_alpha": False,
            "dpi_x": None,
            "dpi_y": None,
        },
        "rights_tier": "open",
        "transform": None,
        "automated_qc": {
            "status": "passed",
            "decodable": True,
            "pixel_limit_status": "passed",
            "hash_duplicate_status": "unique",
            "perceptual_duplicate_status": "unique",
            "boundary_status": "passed",
            "format_status": "passed",
            "failure_codes": [],
        },
        "classification": {
            "automated_suggestion": "isolated_wordmark_clean",
            "human_decision": None,
            "fixture_decision": "isolated_wordmark_clean",
            "suggestion_method": "fixture_protocol",
        },
        "target_geometry": {
            "geometry_type": "bbox",
            "coordinates": [2, 2, 14, 10],
            "confirmed_by": "fixture_protocol",
            "confirmed_at": "2026-09-04T00:00:00Z",
        },
        "curation_status": "passed",
        "exclusion_codes": [],
        "review": {
            "method": "fixture_protocol",
            "reviewer_id": "fixture_protocol",
            "reviewed_at": "2026-09-04T00:00:00Z",
            "decision": "passed",
            "notes": "Synthetic, redistributable fixture; not a human-curated research asset.",
        },
        "award_context": None,
        "font_metadata": None,
    }


def passed_rights_evidence(record: dict, *, intended_use: str = "engineering_fixture") -> dict:
    evidence = {
        "schema_version": "2.0.0",
        "source_id": record["source_id"],
        "checked_at": "2026-09-04",
        "checked_by": "test_reviewer",
        "basis": "project_generated_cc0",
        "license_status": "open",
        "rights_tier": record["rights_tier"],
        "permitted_uses": [intended_use],
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "license_text_or_id": "CC0-1.0",
        "redistribution_allowed": True,
        "page_snapshot": None,
        "decision_status": "passed",
        "notes": "test fixture",
    }
    evidence["rights_evidence_id"] = stable_id("rights", evidence)
    return evidence


def refresh_rights_evidence_id(evidence: dict) -> None:
    content = {key: value for key, value in evidence.items() if key != "rights_evidence_id"}
    evidence["rights_evidence_id"] = stable_id("rights", content)


def test_candidate_schema_accepts_fixture_and_enforces_parent_transform() -> None:
    record = candidate_record()
    assert validate_record(record, ROOT / "schema/asset_candidate.schema.json") == []

    derived = copy.deepcopy(record)
    derived["asset_id"] = "asset_fixture_shape"
    derived["asset_role"] = "B_shape"
    derived["parent_asset_id"] = record["asset_id"]
    derived["transform"] = {
        "tool": "glyph-assets",
        "tool_version": "1.0.0",
        "config_sha256": "b" * 64,
        "parent_sha256": "a" * 64,
        "parameters": {"bbox": [2, 2, 14, 10]},
    }
    assert validate_record(derived, ROOT / "schema/asset_candidate.schema.json") == []

    derived["parent_asset_id"] = None
    assert validate_record(derived, ROOT / "schema/asset_candidate.schema.json")


def test_fixture_gate_never_becomes_formal_release() -> None:
    record = candidate_record()
    assert freeze_blockers(record, fixture_only=True) == []
    assert "ASSET_HUMAN_REVIEW_REQUIRED" in freeze_blockers(record)
    assert "RELEASE_FIXTURE_ONLY" in release_blockers(record)


def test_unknown_rights_and_pending_curation_are_blocked() -> None:
    record = candidate_record()
    record["rights_tier"] = "blocked_unknown"
    record["curation_status"] = "pending"
    blockers = freeze_blockers(record, fixture_only=True)
    assert "ASSET_RIGHTS_BLOCKED" in blockers
    assert "ASSET_CURATION_NOT_PASSED" in blockers
    assert "FIXTURE_OPEN_RIGHTS_REQUIRED" in blockers


def test_automated_suggestion_cannot_replace_human_decision() -> None:
    record = candidate_record()
    record["classification"]["fixture_decision"] = None
    assert "FIXTURE_CLASSIFICATION_REQUIRED" in freeze_blockers(record, fixture_only=True)
    record["classification"]["fixture_decision"] = "isolated_wordmark_clean"
    assert record["classification"]["human_decision"] is None
    assert freeze_blockers(record, fixture_only=True) == []


def test_repository_paths_are_posix_and_relative() -> None:
    assert normalize_repo_path(r"data\fixtures\asset_system\fixture.png") == "data/fixtures/asset_system/fixture.png"
    for value in ("/tmp/fixture.png", r"C:\fixture.png", "../fixture.png"):
        try:
            normalize_repo_path(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {value}")


def test_image_qc_handles_common_modes_and_pixel_limits(tmp_path: Path) -> None:
    for mode in ("L", "RGB", "RGBA", "P"):
        path = tmp_path / f"{mode}.png"
        image = Image.new(mode, (8, 8), 127)
        image.save(path)
        result = inspect_image(
            path,
            max_pixels=64,
            target_bbox=[1, 1, 7, 7],
            assume_srgb_without_profile=True,
        )
        assert result["automated_qc"]["status"] == "passed"
        assert len(result["sha256"]) == 64
        assert result["perceptual_hash"] is not None

    oversized = tmp_path / "oversized.png"
    Image.new("RGB", (11, 10), "white").save(oversized)
    result = inspect_image(oversized, max_pixels=100)
    assert "QC_PIXEL_LIMIT_EXCEEDED" in result["automated_qc"]["failure_codes"]
    assert result["perceptual_hash"] is None

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    result = inspect_image(corrupt, max_pixels=100)
    assert result["automated_qc"]["failure_codes"] == ["QC_DECODE_FAILED"]


def test_exif_orientation_and_background_edge_cases(tmp_path: Path) -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    oriented_path = tmp_path / "oriented.jpg"
    oriented = Image.new("RGB", (16, 12), "white")
    ImageDraw.Draw(oriented).rectangle((2, 2, 13, 9), fill="black")
    exif = Image.Exif()
    exif[274] = 6
    oriented.save(oriented_path, exif=exif)
    record = candidate_record()
    record["asset_ref"]["sha256"] = sha256_file(oriented_path)
    layout = transform_candidate(
        record,
        oriented_path,
        tmp_path / "layout",
        "A_layout",
        config,
        logical_output_root="fixture/derived",
    )[0]
    assert (layout["pixel_metadata"]["width_px"], layout["pixel_metadata"]["height_px"]) == (12, 16)
    assert layout["transform"]["parameters"]["input_size"] == [16, 12]

    transparent_path = tmp_path / "transparent.png"
    transparent = Image.new("RGBA", (16, 12), (0, 0, 0, 0))
    ImageDraw.Draw(transparent).rectangle((2, 2, 13, 9), fill=(0, 0, 0, 255))
    transparent.save(transparent_path)
    record["asset_ref"]["sha256"] = sha256_file(transparent_path)
    shape_records = transform_candidate(
        record,
        transparent_path,
        tmp_path / "shape",
        "B_shape",
        config,
        logical_output_root="fixture/derived",
    )
    shape_path = tmp_path / "shape" / Path(shape_records[0]["asset_ref"]["path"]).name
    with Image.open(shape_path) as shape:
        assert shape.mode == "L"
        assert shape.getpixel((0, 0)) == 255

    for color in (0, 255):
        flat_path = tmp_path / f"flat-{color}.png"
        Image.new("L", (16, 12), color).save(flat_path)
        record["asset_ref"]["sha256"] = sha256_file(flat_path)
        with pytest.raises(RepresentationNotApplicable, match="C_INK_NOT_APPLICABLE"):
            transform_candidate(
                record,
                flat_path,
                tmp_path / f"ink-{color}",
                "C_ink",
                config,
                logical_output_root="fixture/derived",
            )


def test_exact_and_near_duplicates_are_distinct_states() -> None:
    records = [
        {"asset_id": "asset_a", "sha256": "a" * 64, "perceptual_hash": "0000000000000000"},
        {"asset_id": "asset_b", "sha256": "a" * 64, "perceptual_hash": "0000000000000000"},
        {"asset_id": "asset_c", "sha256": "c" * 64, "perceptual_hash": "ffffffffffffffff"},
        {"asset_id": "asset_d", "sha256": "d" * 64, "perceptual_hash": "fffffffffffffffe"},
    ]
    annotated = duplicate_annotations(records, near_threshold=1)
    assert annotated[0]["hash_duplicate_status"] == "duplicate_exact"
    assert annotated[1]["duplicate_of"] == "asset_a"
    assert annotated[3]["perceptual_duplicate_status"] == "duplicate_near"
    assert annotated[3]["near_duplicate_of"] == "asset_c"


def test_latin_fixture_rejects_cyrillic_lookalike() -> None:
    assert script_purity_violations("Aa Bb Gg Rr Handgloves 1234", "Latn") == []
    assert script_purity_violations("Rр", "Latn") == ["U+0440"]
    sample_module = runpy.run_path(str(ROOT / "图包与字体包/标准化流程/render_font_samples.py"))
    assert script_purity_violations(sample_module["SAMPLES"]["拉丁文字"], "Latn") == []


def test_abc_transform_is_deterministic_and_preserves_parent_chain(tmp_path: Path) -> None:
    source = tmp_path / "fixture.png"
    image = Image.new("RGB", (16, 12), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 13, 9), fill=96)
    draw.rectangle((5, 3, 10, 8), fill=32)
    image.save(source)

    record = candidate_record()
    record["asset_ref"]["sha256"] = sha256_file(source)
    record["asset_ref"]["byte_size"] = source.stat().st_size
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    output = tmp_path / "derived"
    records = []
    for representation in ("A_layout", "B_shape", "C_ink"):
        records.extend(
            transform_candidate(
                record,
                source,
                output,
                representation,
                config,
                logical_output_root="data/fixtures/asset_system/derived",
            )
        )

    assert {item["asset_role"] for item in records} == {"A_layout", "B_shape", "mask", "C_ink"}
    assert all(item["parent_asset_id"] == record["asset_id"] for item in records)
    assert all(item["transform"]["parent_sha256"] == record["asset_ref"]["sha256"] for item in records)
    assert all(validate_record(item, ROOT / "schema/asset_candidate.schema.json") == [] for item in records)
    layout = next(item for item in records if item["asset_role"] == "A_layout")
    shape = next(item for item in records if item["asset_role"] == "B_shape")
    assert (layout["pixel_metadata"]["width_px"], layout["pixel_metadata"]["height_px"]) == (16, 12)
    assert (shape["pixel_metadata"]["width_px"], shape["pixel_metadata"]["height_px"]) == (512, 512)

    repeated = []
    for representation in ("A_layout", "B_shape", "C_ink"):
        repeated.extend(
            transform_candidate(
                record,
                source,
                tmp_path / "repeated",
                representation,
                config,
                logical_output_root="data/fixtures/asset_system/derived",
            )
        )
    assert [(item["asset_id"], item["asset_ref"]["sha256"]) for item in repeated] == [
        (item["asset_id"], item["asset_ref"]["sha256"]) for item in records
    ]


def test_visual_v1_hash_survives_non_visual_contract_upgrades() -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    from glyph_features.asset_system.transform import config_sha256

    assert config_sha256(config) == "b6373dd53dc648cecc51a229eae788ac43e855113fa75989b4675e1b5ba069c9"


def test_polygon_candidate_transforms_through_cli_with_masked_pixels(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("L", (16, 12), 0).save(source)
    record = candidate_record()
    record["asset_ref"] = {
        "path": "source.png",
        "sha256": sha256_file(source),
        "mime_type": "image/png",
        "byte_size": source.stat().st_size,
    }
    record["target_geometry"] = {
        "geometry_type": "polygon",
        "coordinates": [2, 2, 14, 2, 8, 10],
        "confirmed_by": "reviewer_01",
        "confirmed_at": "2026-09-04T00:00:00Z",
    }
    assert validate_record(record, ROOT / "schema/asset_candidate.schema.json") == []
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(json.dumps(record) + "\n", encoding="utf-8")
    output = tmp_path / "output"
    assert asset_cli(
        [
            "transform",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(candidates),
            "--representation", "B_shape",
            "--output-dir", str(output),
            "--logical-output-root", "output/derived",
        ]
    ) == 0
    records = [json.loads(line) for line in (output / "asset_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    shape = next(item for item in records if item["asset_role"] == "B_shape")
    parameters = shape["transform"]["parameters"]
    assert parameters["geometry_type"] == "polygon"
    assert parameters["polygon"] == [2.0, 2.0, 14.0, 2.0, 8.0, 10.0]
    assert parameters["bbox"] == [2, 2, 14, 10]
    assert len(parameters["matrix"]) == 9

    def mapped_pixel(source_x: float, source_y: float) -> tuple[int, int]:
        matrix = parameters["matrix"]
        return round(matrix[0] * source_x + matrix[2]), round(matrix[4] * source_y + matrix[5])

    shape_path = tmp_path / shape["asset_ref"]["path"]
    with Image.open(shape_path) as rendered:
        assert rendered.getpixel(mapped_pixel(8, 4)) < 32
        assert rendered.getpixel(mapped_pixel(3, 8)) > 240


def test_transform_refuses_overwrite_and_changes_id_with_conditions(tmp_path: Path) -> None:
    source = tmp_path / "fixture.png"
    Image.new("RGB", (16, 12), 100).save(source)
    record = candidate_record()
    record["asset_ref"]["sha256"] = sha256_file(source)
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    output = tmp_path / "derived"
    original = transform_candidate(
        record,
        source,
        output,
        "B_shape",
        config,
        logical_output_root="data/fixtures/asset_system/derived",
    )
    with pytest.raises(FileExistsError):
        transform_candidate(
            record,
            source,
            output,
            "B_shape",
            config,
            logical_output_root="data/fixtures/asset_system/derived",
        )

    changed_config = copy.deepcopy(config)
    changed_config["representations"]["B_shape"]["content_px"] = [400, 400]
    changed = transform_candidate(
        record,
        source,
        output,
        "B_shape",
        changed_config,
        logical_output_root="data/fixtures/asset_system/derived",
    )
    assert original[0]["asset_id"] != changed[0]["asset_id"]


def test_c_ink_marks_binary_input_not_applicable(tmp_path: Path) -> None:
    source = tmp_path / "binary.png"
    Image.new("1", (16, 12), 1).save(source)
    record = candidate_record()
    record["asset_ref"]["sha256"] = sha256_file(source)
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    with pytest.raises(RepresentationNotApplicable, match="C_INK_NOT_APPLICABLE"):
        transform_candidate(
            record,
            source,
            tmp_path / "derived",
            "C_ink",
            config,
            logical_output_root="data/fixtures/asset_system/derived",
        )


def test_legacy_source_migration_repairs_without_changing_inputs() -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    audit = migrate_award_sources(ROOT, config)
    snapshots = {item["award"]: item for item in audit["source_table_snapshots"]}
    assert {award: item["row_count"] for award, item in snapshots.items()} == {
        "DFA": 80,
        "Indigo": 90,
        "WOLDA": 90,
        "Golden Pin": 90,
        "GDC": 53,
    }
    assert len(audit["asset_source_map"]) == 375
    issue_counts: dict[str, int] = {}
    for issue in audit["issues"]:
        issue_counts[issue["code"]] = issue_counts.get(issue["code"], 0) + 1
    assert issue_counts["GDC_SHIFTED_COLUMNS"] == 15
    assert issue_counts["SOURCE_DUPLICATE_FILE_ROW"] == 18
    assert issue_counts["SOURCE_FILENAME_EXTENSION_REPAIRED"] == 25
    assert issue_counts["SOURCE_WITHOUT_FILE"] == 10
    assert issue_counts.get("FILE_WITHOUT_SOURCE", 0) == 0
    assert all(len(item["sha256"]) == 64 for item in snapshots.values())
    assert {row["award"] for row in audit["normalized_rows"]} == {"DFA", "Indigo", "WOLDA", "Golden Pin", "GDC"}


def test_source_migration_reports_missing_extra_columns_and_invalid_urls(tmp_path: Path) -> None:
    award_dir = tmp_path / "DFA"
    award_dir.mkdir()
    Image.new("RGB", (2, 2), "white").save(award_dir / "valid.png")
    Image.new("RGB", (2, 2), "black").save(award_dir / "bad.png")
    (award_dir / "sources.csv").write_text(
        "award,year,file,url,bytes,page,fetched\n"
        "DFA,2024,valid.png,https://example.invalid/a,79,https://example.invalid/work/a,2026-09-04T00:00:00Z\n"
        "DFA,2024,missing.png,https://example.invalid/b,79,2026-09-04T00:00:00Z\n"
        "DFA,2024,extra.png,https://example.invalid/c,79,https://example.invalid/work/c,2026-09-04T00:00:00Z,extra\n"
        "DFA,2024,bad.png,not-a-url,79,ftp://example.invalid/work/bad,2026-09-04T00:00:00Z\n",
        encoding="utf-8",
    )
    audit = migrate_award_sources(
        tmp_path,
        {
            "awards": ["DFA"],
            "inventory": {"snapshot_date": "2026-09-04", "award_roots": {"DFA": "DFA"}},
        },
    )
    issue_counts: dict[str, int] = {}
    for issue in audit["issues"]:
        issue_counts[issue["code"]] = issue_counts.get(issue["code"], 0) + 1
    assert issue_counts["SOURCE_ROW_WIDTH_INVALID"] == 2
    assert issue_counts["SOURCE_URL_INVALID"] == 2
    assert len(audit["normalized_rows"]) == 2


def test_source_migration_disambiguates_by_year_and_rejects_duplicate_basename(tmp_path: Path) -> None:
    award_dir = tmp_path / "DFA"
    (award_dir / "2023").mkdir(parents=True)
    (award_dir / "2024").mkdir()
    Image.new("RGB", (2, 2), "white").save(award_dir / "2023/a.png")
    Image.new("RGB", (2, 2), "black").save(award_dir / "2024/a.png")
    (award_dir / "sources.csv").write_text(
        "award,year,file,url,bytes,page,fetched\n"
        "DFA,2023,a.png,https://example.invalid/2023,79,https://example.invalid/work/2023,2026-09-04T00:00:00Z\n"
        "DFA,2025,a.png,https://example.invalid/2025,79,https://example.invalid/work/2025,2026-09-04T00:00:00Z\n",
        encoding="utf-8",
    )
    audit = migrate_award_sources(
        tmp_path,
        {
            "awards": ["DFA"],
            "inventory": {"snapshot_date": "2026-09-04", "award_roots": {"DFA": "DFA"}},
        },
    )
    assert set(audit["asset_source_map"]) == {"DFA/2023/a.png"}
    ambiguous = [issue for issue in audit["issues"] if issue["code"] == "SOURCE_FILE_AMBIGUOUS"]
    assert len(ambiguous) == 1
    assert ambiguous[0]["row_number"] == 3


def test_repository_inventory_registers_all_images_and_font_relationships() -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    audit = migrate_award_sources(ROOT, config)
    inventory = build_repository_inventory(ROOT, config, audit)
    summary = inventory["summary"]
    assert summary["candidate_count"] == 388
    assert summary["image_file_count"] == 375
    assert summary["image_unique_sha256_count"] == 372
    assert summary["font_file_count"] == 13
    assert summary["font_family_count"] == 12
    assert summary["oversize_image_count"] == 4
    assert summary["exact_duplicate_file_count"] == 6
    assert summary["curation_passed_count"] == 0
    assert summary["rights_tiers"] == {"blocked_unknown": 388}
    assert sum(len(years) for years in summary["award_years"].values()) == 22
    assert len(summary["award_years"]["Golden Pin"]) == 4
    assert len(summary["award_years"]["GDC"]) == 3
    assert len(summary["font_families"]) == 12
    assert next(item for item in summary["font_families"] if item["family_name"] == "Lato")["file_count"] == 2
    assert {record["award_context"]["award"] for record in inventory["candidates"] if record["award_context"]} == {
        "DFA", "Indigo", "WOLDA", "Golden Pin", "GDC"
    }
    font_candidates = [record for record in inventory["candidates"] if record["candidate_kind"] == "font_file"]
    lato = [record for record in font_candidates if record["font_metadata"]["family_name"] == "Lato"]
    assert len(lato) == 2
    assert len({record["font_metadata"]["family_id"] for record in lato}) == 1
    assert all(record["font_metadata"]["license_hint"]["sidecar_files"] == [] for record in font_candidates)
    assert all(validate_record(record, ROOT / "schema/asset_candidate.schema.json") == [] for record in inventory["candidates"])
    assert all(validate_record(record, ROOT / "schema/source.schema.json") == [] for record in inventory["sources"])


def test_human_curation_decision_is_separate_from_automated_suggestion() -> None:
    record = candidate_record()
    record["record_origin"] = "repository_asset"
    record["classification"]["human_decision"] = None
    record["target_geometry"] = None
    record["curation_status"] = "needs_review"
    record["review"] = {"method": "none", "reviewer_id": None, "reviewed_at": None, "decision": None, "notes": None}
    queue = build_review_queue([record])
    assert len(queue) == 1
    assert queue[0]["automated_suggestion"] == "isolated_wordmark_clean"
    assert queue[0]["human_decision"] == ""
    decision = {
        "asset_id": record["asset_id"],
        "human_decision": "isolated_wordmark_clean",
        "curation_status": "passed",
        "target_bbox_json": "[2,2,14,10]",
        "reviewer_id": "reviewer_local_01",
        "reviewed_at": "2026-09-04T01:00:00Z",
        "exclusion_codes": "",
        "notes": "bbox confirmed",
    }
    curated = apply_curation_decisions([record], [decision])[0]
    assert curated["classification"]["automated_suggestion"] == "isolated_wordmark_clean"
    assert curated["classification"]["human_decision"] == "isolated_wordmark_clean"
    assert curated["review"]["method"] == "human"
    assert curated["target_geometry"]["confirmed_by"] == "reviewer_local_01"

    invalid = dict(decision, reviewer_id="")
    with pytest.raises(ValueError, match="reviewer"):
        apply_curation_decisions([record], [invalid])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewed_at", "2026-09-04T09:00:00+09:00", "must be UTC"),
        ("human_decision", "not-a-class", "invalid human content class"),
        ("exclusion_codes", "NOT_A_CODE", "invalid exclusion code"),
        ("target_polygon_json", "[0,0,1,1,2]", "invalid target geometry"),
    ],
)
def test_curation_decision_validates_human_fields(field: str, value: str, message: str) -> None:
    record = candidate_record()
    record["curation_status"] = "needs_review"
    decision = {
        "asset_id": record["asset_id"],
        "human_decision": "isolated_wordmark_clean",
        "curation_status": "passed",
        "target_bbox_json": "[2,2,14,10]",
        "target_polygon_json": "",
        "reviewer_id": "reviewer_01",
        "reviewed_at": "2026-09-04T00:00:00Z",
        "exclusion_codes": "",
        "notes": "validation",
    }
    if field == "target_polygon_json":
        decision["target_bbox_json"] = ""
    decision[field] = value
    with pytest.raises(ValueError, match=message):
        apply_curation_decisions([record], [decision])


def test_import_curation_cli_reruns_qc_before_transform(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGB", (16, 12), "white")
    ImageDraw.Draw(image).rectangle((2, 2, 13, 9), fill=64)
    image.save(source)
    record = candidate_record()
    record["record_origin"] = "repository_asset"
    record["rights_tier"] = "blocked_unknown"
    record["asset_ref"] = {
        "path": "source.png",
        "sha256": sha256_file(source),
        "mime_type": "image/png",
        "byte_size": source.stat().st_size,
    }
    record["automated_qc"]["status"] = "needs_review"
    record["automated_qc"]["boundary_status"] = "needs_review"
    record["classification"]["human_decision"] = None
    record["classification"]["fixture_decision"] = None
    record["target_geometry"] = None
    record["curation_status"] = "needs_review"
    record["exclusion_codes"] = ["RIGHTS_BLOCKED"]
    record["review"] = {"method": "none", "reviewer_id": None, "reviewed_at": None, "decision": None, "notes": None}
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(json.dumps(record) + "\n", encoding="utf-8")
    decisions = tmp_path / "decisions.csv"
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "asset_id", "human_decision", "curation_status", "target_bbox_json",
                "target_polygon_json", "reviewer_id", "reviewed_at", "exclusion_codes", "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "asset_id": record["asset_id"],
                "human_decision": "isolated_wordmark_clean",
                "curation_status": "passed",
                "target_bbox_json": "[2,2,14,10]",
                "target_polygon_json": "",
                "reviewer_id": "reviewer_01",
                "reviewed_at": "2026-09-04T00:00:00Z",
                "exclusion_codes": "",
                "notes": "confirmed",
            }
        )
    curated_path = tmp_path / "curated.jsonl"
    assert asset_cli(
        [
            "import-curation",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(candidates),
            "--decisions", str(decisions),
            "--output", str(curated_path),
        ]
    ) == 0
    curated = json.loads(curated_path.read_text(encoding="utf-8"))
    assert curated["curation_status"] == "passed"
    assert curated["automated_qc"]["status"] == "passed"
    assert freeze_blockers(curated) == ["ASSET_RIGHTS_BLOCKED"]
    assert asset_cli(
        [
            "transform",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(curated_path),
            "--representation", "B_shape",
            "--output-dir", str(tmp_path / "transformed"),
            "--logical-output-root", "transformed/derived",
        ]
    ) == 0


def test_import_curation_cli_cannot_promote_corrupt_image(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "corrupt.png"
    source.write_bytes(b"not an image")
    record = candidate_record()
    record["record_origin"] = "repository_asset"
    record["rights_tier"] = "blocked_unknown"
    record["asset_ref"] = {
        "path": "corrupt.png",
        "sha256": sha256_file(source),
        "mime_type": "image/png",
        "byte_size": source.stat().st_size,
    }
    record["automated_qc"]["status"] = "needs_review"
    record["automated_qc"]["boundary_status"] = "needs_review"
    record["classification"]["human_decision"] = None
    record["classification"]["fixture_decision"] = None
    record["target_geometry"] = None
    record["curation_status"] = "needs_review"
    record["exclusion_codes"] = ["RIGHTS_BLOCKED"]
    record["review"] = {"method": "none", "reviewer_id": None, "reviewed_at": None, "decision": None, "notes": None}
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(json.dumps(record) + "\n", encoding="utf-8")
    decisions = tmp_path / "decisions.csv"
    decisions.write_text(
        "asset_id,human_decision,curation_status,target_bbox_json,target_polygon_json,reviewer_id,reviewed_at,exclusion_codes,notes\n"
        f'{record["asset_id"]},isolated_wordmark_clean,passed,"[2,2,14,10]",,reviewer_01,2026-09-04T00:00:00Z,,corrupt\n',
        encoding="utf-8",
    )
    exit_code = asset_cli(
        [
            "import-curation",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(candidates),
            "--decisions", str(decisions),
            "--output", str(tmp_path / "curated.jsonl"),
        ]
    )
    assert exit_code == EXIT_OPERATION_ERROR
    assert json.loads(capsys.readouterr().err)["code"] == "CURATION_QC_NOT_PASSED"
    assert not (tmp_path / "curated.jsonl").exists()


def test_real_inventory_candidate_reaches_freeze_and_is_blocked_only_by_rights(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    audit = migrate_award_sources(ROOT, config)
    inventory = build_repository_inventory(ROOT, config, audit)
    eligible = [
        record
        for record in inventory["candidates"]
        if record["candidate_kind"] == "ecological_award_image"
        and record["automated_qc"]["status"] == "needs_review"
        and record["automated_qc"]["failure_codes"] == []
        and record["automated_qc"]["hash_duplicate_status"] == "unique"
        and record["automated_qc"]["perceptual_duplicate_status"] == "unique"
    ]
    original = copy.deepcopy(min(eligible, key=lambda item: item["asset_ref"]["byte_size"]))
    mirrored_source = tmp_path / original["asset_ref"]["path"]
    mirrored_source.parent.mkdir(parents=True)
    mirrored_source.write_bytes((ROOT / original["asset_ref"]["path"]).read_bytes())
    candidates_path = tmp_path / "candidates.jsonl"
    candidates_path.write_text(json.dumps(original) + "\n", encoding="utf-8")
    metadata = original["pixel_metadata"]
    decisions_path = tmp_path / "curation_decisions.csv"
    with decisions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "asset_id", "human_decision", "curation_status", "target_bbox_json",
                "target_polygon_json", "reviewer_id", "reviewed_at", "exclusion_codes", "notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "asset_id": original["asset_id"],
                "human_decision": "project_board_or_poster",
                "curation_status": "passed",
                "target_bbox_json": json.dumps([0, 0, metadata["width_px"], metadata["height_px"]]),
                "target_polygon_json": "",
                "reviewer_id": "test_reviewer_real_inventory",
                "reviewed_at": "2026-09-04T00:00:00Z",
                "exclusion_codes": "",
                "notes": "Regression-only review decision for a mirrored real inventory candidate.",
            }
        )
    curated_path = tmp_path / "curated.jsonl"
    assert asset_cli(
        [
            "import-curation",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(candidates_path),
            "--decisions", str(decisions_path),
            "--output", str(curated_path),
        ]
    ) == 0
    curated = json.loads(curated_path.read_text(encoding="utf-8"))
    assert curated["automated_qc"]["status"] == "passed"
    assert freeze_blockers(curated) == ["ASSET_RIGHTS_BLOCKED"]

    derived: list[dict] = []
    for representation in ("A_layout", "B_shape"):
        output = tmp_path / f"{representation}-output"
        assert asset_cli(
            [
                "transform",
                "--workspace-root", str(tmp_path),
                "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
                "--candidates", str(curated_path),
                "--representation", representation,
                "--output-dir", str(output),
            ]
        ) == 0
        derived.extend(
            json.loads(line)
            for line in (output / "asset_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        )
    derived_path = tmp_path / "derived.jsonl"
    derived_path.write_text("".join(json.dumps(record) + "\n" for record in derived), encoding="utf-8")
    evidence = passed_rights_evidence(curated, intended_use="metadata_audit")
    evidence.update(
        {
            "rights_evidence_id": "rights_real_inventory_pending",
            "basis": "source_metadata_only",
            "license_status": "unknown",
            "rights_tier": "blocked_unknown",
            "license_url": None,
            "license_text_or_id": None,
            "redistribution_allowed": None,
            "decision_status": "pending_human_review",
        }
    )
    refresh_rights_evidence_id(evidence)
    evidence_path = tmp_path / "rights.jsonl"
    evidence_path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert asset_cli(
        [
            "freeze-stimuli",
            "--workspace-root", str(tmp_path),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--originals", str(curated_path),
            "--derived", str(derived_path),
            "--rights-evidence", str(evidence_path),
            "--output", str(tmp_path / "stimuli.jsonl"),
            "--created-at", "2026-09-04T00:00:00Z",
        ]
    ) == EXIT_RECORD_FAILURE
    assert json.loads(capsys.readouterr().err)["code"] == "RIGHTS_EVIDENCE_PENDING"


def test_fixture_freeze_requires_complete_parent_bound_representations(tmp_path: Path) -> None:
    source = tmp_path / "fixture.png"
    image = Image.new("RGB", (16, 12), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 13, 9), fill=96)
    draw.rectangle((5, 3, 10, 8), fill=32)
    image.save(source)
    original = candidate_record()
    original["asset_ref"]["sha256"] = sha256_file(source)
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    derived = []
    for representation in ("A_layout", "B_shape", "C_ink"):
        derived.extend(
            transform_candidate(
                original,
                source,
                tmp_path / "derived",
                representation,
                config,
                logical_output_root="data/fixtures/asset_system/derived",
            )
        )
    stimulus = freeze_ecological_stimulus(
        original,
        derived,
        created_at="2026-09-04T00:00:00Z",
        fixture_only=True,
        rights_evidence=passed_rights_evidence(original),
    )
    assert stimulus["release_status"] == "fixture_only"
    assert validate_record(stimulus, ROOT / "schema/ecological_stimulus.schema.json") == []
    with pytest.raises(ValueError, match="missing representations"):
        freeze_ecological_stimulus(
            original,
            [record for record in derived if record["asset_role"] != "B_shape"],
            created_at="2026-09-04T00:00:00Z",
            fixture_only=True,
            rights_evidence=passed_rights_evidence(original),
        )
    with pytest.raises(ValueError, match="HUMAN_REVIEW_REQUIRED"):
        freeze_ecological_stimulus(
            original,
            derived,
            created_at="2026-09-04T00:00:00Z",
            fixture_only=False,
            rights_evidence=passed_rights_evidence(original, intended_use="research_stimulus_local"),
        )


def test_tracked_open_fixture_has_explicit_rights_and_no_human_gold() -> None:
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    fixture = build_open_fixture(ROOT, config)
    source = fixture["source"]
    candidate = fixture["candidate"]
    assert source["license_status"] == "open"
    assert source["license_text_or_id"] == "CC0-1.0"
    assert source["redistribution_allowed"] is True
    assert candidate["classification"]["human_decision"] is None
    assert candidate["classification"]["fixture_decision"] == "isolated_wordmark_clean"
    assert validate_record(source, ROOT / "schema/source.schema.json") == []
    assert validate_record(candidate, ROOT / "schema/asset_candidate.schema.json") == []
    evidence = build_rights_evidence(
        [source],
        checked_at=config["inventory"]["snapshot_date"],
        fixture_source_id=source["source_id"],
    )
    assert evidence[0]["decision_status"] == "passed"
    assert evidence[0]["rights_tier"] == "open"
    assert validate_record(evidence[0], ROOT / "schema/rights_evidence.schema.json") == []


def test_handoff_bundle_is_valid_immutable_and_detects_tampering(tmp_path: Path) -> None:
    legacy_source_path = "图包与字体包/图包/中文奖项/DFA/sources.csv"
    legacy_source_sha256 = sha256_file(ROOT / legacy_source_path)
    candidate = candidate_record()
    candidate.update(
        {
            "asset_id": "asset_repository_test",
            "record_origin": "repository_asset",
            "source_id": "source_repository_test",
            "work_id": "work_repository_test",
            "candidate_kind": "ecological_award_image",
            "rights_tier": "blocked_unknown",
            "target_geometry": None,
            "curation_status": "needs_review",
            "award_context": {
                "award": "DFA",
                "year": 2024,
                "edition": None,
                "category": None,
                "award_status": None,
            },
        }
    )
    candidate["classification"] = {
        "automated_suggestion": "uncertain",
        "human_decision": None,
        "fixture_decision": None,
        "suggestion_method": "test",
    }
    candidate["review"] = {
        "method": "none",
        "reviewer_id": None,
        "reviewed_at": None,
        "decision": None,
        "notes": None,
    }
    source = {
        "source_id": "source_repository_test",
        "source_type": "award_page",
        "title": "Test award source",
        "publisher_or_creator": "DFA",
        "url": "https://example.invalid/work/1",
        "published_at": None,
        "accessed_at": "2026-09-04",
        "language_bcp47": None,
        "region": None,
        "license_status": "unknown",
        "license_text_or_id": None,
        "redistribution_allowed": None,
        "local_archive": candidate["asset_ref"],
        "notes": None,
    }
    award_summary = {
        award: {
            "file_count": 1 if award == "DFA" else 0,
            "unique_binary_count": 1 if award == "DFA" else 0,
            "unique_work_count": 1 if award == "DFA" else 0,
            "curation_passed_count": 0,
            "rights_tiers": {"blocked_unknown": 1} if award == "DFA" else {},
            "content_suggestions": {"uncertain": 1} if award == "DFA" else {},
        }
        for award in ("DFA", "Indigo", "WOLDA", "Golden Pin", "GDC")
    }
    inventory = {
        "candidates": [candidate],
        "sources": [source],
        "source_audit": {
            "source_table_snapshots": [
                {
                    "award": "DFA",
                    "path": legacy_source_path,
                    "sha256": legacy_source_sha256,
                    "row_count": 80,
                    "header": [],
                    "row_widths": {},
                }
            ],
            "normalized_rows": [
                {
                    "source_id": source["source_id"], "award": "DFA", "year": 2024, "edition": None,
                    "work_id": candidate["work_id"], "local_path": candidate["asset_ref"]["path"],
                    "recorded_file": "fixture.ppm", "asset_url": source["url"], "source_page_url": source["url"],
                    "bytes_reported": 128, "award_status": None, "title": source["title"], "creator": "DFA",
                    "category": None, "fetched_at": "2026-09-04T00:00:00Z", "legacy_source_path": legacy_source_path,
                    "legacy_source_sha256": legacy_source_sha256, "legacy_row_number": 2, "repair_codes": [],
                }
            ],
            "issues": [
                {"award": "DFA", "source_path": legacy_source_path, "row_number": 2, "code": "TEST_REVIEW_REQUIRED", "detail": "fixture"}
            ],
        },
        "summary": {
            "candidate_count": 1,
            "image_file_count": 1,
            "image_unique_sha256_count": 1,
            "font_file_count": 0,
            "font_family_count": 0,
            "unique_work_count": 1,
            "curation_passed_count": 0,
            "rights_tiers": {"blocked_unknown": 1},
            "qc_statuses": {"passed": 1},
            "oversize_image_count": 0,
            "exact_duplicate_file_count": 0,
            "near_duplicate_file_count": 0,
            "source_issue_count": 1,
            "awards": award_summary,
        },
    }
    output = tmp_path / "bundle"
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    summary = build_handoff_bundle(
        ROOT,
        output,
        ROOT / "configs/asset_curation_v1.yaml",
        git_commit=base_commit,
        created_at="2026-09-04T00:00:00Z",
        artifact_path_prefix="bundle",
        inventory_data=inventory,
    )
    assert summary["readiness"] == {
        "engineering_ready": True,
        "pilot_ready": False,
        "research_validated": False,
    }
    for csv_name in ("source_migration.csv", "source_issues.csv", "review_queue.csv"):
        assert b"\r\n" not in (output / csv_name).read_bytes()
    manifest_path = output / "handoff_manifest.json"
    assert validate_handoff(manifest_path, tmp_path, schema_root=ROOT, input_root=ROOT) == []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["handoff_schema_version"] == "2.0.0"
    assert manifest["contract_compatibility"]["backward_compatible"] is False
    assert manifest["producer_provenance"]["base_commit"] == base_commit
    git_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    assert manifest["producer_provenance"]["working_tree_state"] == ("dirty" if git_status else "clean")
    assert isinstance(manifest["producer_provenance"]["producer_snapshot_matches_base"], bool)
    assert {item["role"] for item in manifest["producer_provenance"]["files"]} == {
        "entrypoint", "dependency_lock", "config", "schema", "producer_source"
    }
    run_manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert "executable" not in run_manifest["environment"]
    assert {gate["gate_id"] for gate in manifest["blocked_human_gates"]} == {
        "GATE-RIGHTS", "GATE-HISTORY", "GATE-TERMS", "GATE-RELEASE"
    }
    with pytest.raises(FileExistsError):
        build_handoff_bundle(
            ROOT,
            output,
            ROOT / "configs/asset_curation_v1.yaml",
            git_commit=base_commit,
            created_at="2026-09-04T00:00:00Z",
            artifact_path_prefix="bundle",
            inventory_data=inventory,
        )
    invalid_input_manifest = copy.deepcopy(manifest)
    invalid_input_manifest["input_snapshots"][0]["sha256"] = "0" * 64
    invalid_input_path = output / "invalid_input_handoff.json"
    invalid_input_path.write_text(json.dumps(invalid_input_manifest), encoding="utf-8")
    assert "input hash mismatch: configs/asset_curation_v1.yaml" in validate_handoff(
        invalid_input_path,
        tmp_path,
        schema_root=ROOT,
        input_root=ROOT,
    )
    invalid_producer_manifest = copy.deepcopy(manifest)
    invalid_producer_manifest["producer_provenance"]["files"][0]["sha256"] = "0" * 64
    invalid_producer_path = output / "invalid_producer_handoff.json"
    invalid_producer_path.write_text(json.dumps(invalid_producer_manifest), encoding="utf-8")
    producer_errors = validate_handoff(invalid_producer_path, tmp_path, schema_root=ROOT, input_root=ROOT)
    assert any(error.startswith("producer hash mismatch:") for error in producer_errors)
    assert "producer aggregate hash mismatch" in producer_errors
    incomplete_producer_manifest = copy.deepcopy(manifest)
    incomplete_producer_manifest["producer_provenance"]["files"].pop()
    incomplete_producer_path = output / "incomplete_producer_handoff.json"
    incomplete_producer_path.write_text(json.dumps(incomplete_producer_manifest), encoding="utf-8")
    assert any(
        error.startswith("producer snapshot file set mismatch:")
        for error in validate_handoff(incomplete_producer_path, tmp_path, schema_root=ROOT, input_root=ROOT)
    )
    missing_provenance_manifest = copy.deepcopy(manifest)
    del missing_provenance_manifest["producer_provenance"]
    missing_provenance_path = output / "missing_provenance_handoff.json"
    missing_provenance_path.write_text(json.dumps(missing_provenance_manifest), encoding="utf-8")
    assert any(
        "'producer_provenance' is a required property" in error
        for error in validate_handoff(missing_provenance_path, tmp_path, schema_root=ROOT, input_root=ROOT)
    )

    leak_path = output / "portability_probe.txt"
    leak_path.write_text("/Users/local-only/.venv/bin/python3\n", encoding="utf-8")
    leak_manifest = copy.deepcopy(manifest)
    leak_manifest_path = output / "leak_handoff.json"
    leak_manifest_path.write_text(json.dumps(leak_manifest), encoding="utf-8")
    assert "absolute filesystem path leak: portability_probe.txt" in validate_handoff(
        leak_manifest_path,
        tmp_path,
        schema_root=ROOT,
        input_root=ROOT,
    )
    (output / "inventory_summary.json").write_text("{}\n", encoding="utf-8")
    assert "hash mismatch: bundle/inventory_summary.json" in validate_handoff(
        manifest_path,
        tmp_path,
        schema_root=ROOT,
        input_root=ROOT,
    )


def test_transform_cli_dry_run_partial_failure_and_no_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "fixture.png"
    Image.new("RGB", (16, 12), 96).save(source)
    good = candidate_record()
    good["asset_ref"] = {
        "path": "fixture.png",
        "sha256": sha256_file(source),
        "mime_type": "image/png",
        "byte_size": source.stat().st_size,
    }
    missing = copy.deepcopy(good)
    missing["asset_id"] = "asset_fixture_missing"
    missing["asset_ref"]["path"] = "missing.png"
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text(
        "".join(json.dumps(record) + "\n" for record in (good, missing)),
        encoding="utf-8",
    )
    output = tmp_path / "output"
    common = [
        "transform",
        "--workspace-root", str(tmp_path),
        "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
        "--candidates", str(candidates),
        "--representation", "A_layout",
        "--output-dir", str(output),
    ]
    assert asset_cli([*common, "--dry-run"]) == EXIT_RECORD_FAILURE
    assert not output.exists()

    failures = tmp_path / "failures.jsonl"
    assert asset_cli([*common, "--failure-output", str(failures)]) == EXIT_RECORD_FAILURE
    assert len(list((output / "derived").glob("*.png"))) == 1
    failure_records = [json.loads(line) for line in failures.read_text(encoding="utf-8").splitlines()]
    assert failure_records[0]["code"] == "ASSET_FILE_MISSING"
    assert failure_records[0]["record_id"] == "asset_fixture_missing"

    overwrite_failures = tmp_path / "overwrite_failures.jsonl"
    assert asset_cli([*common, "--failure-output", str(overwrite_failures)]) == EXIT_NO_OVERWRITE
    assert json.loads(overwrite_failures.read_text(encoding="utf-8"))["code"] == "NO_OVERWRITE"

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    empty_output = tmp_path / "empty-output"
    empty_failures = tmp_path / "empty-failures.jsonl"
    empty_args = [
        "transform",
        "--workspace-root", str(tmp_path),
        "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
        "--candidates", str(empty),
        "--representation", "A_layout",
        "--output-dir", str(empty_output),
        "--failure-output", str(empty_failures),
    ]
    assert asset_cli(empty_args) == EXIT_RECORD_FAILURE
    assert not empty_output.exists()
    assert json.loads(empty_failures.read_text(encoding="utf-8"))["code"] == "EMPTY_INPUT"

    preserved_failure = tmp_path / "preserved-failure.jsonl"
    preserved_failure.write_text("preserve me\n", encoding="utf-8")
    assert asset_cli([*common, "--failure-output", str(preserved_failure)]) == EXIT_NO_OVERWRITE
    assert preserved_failure.read_text(encoding="utf-8") == "preserve me\n"


@pytest.mark.parametrize(
    ("path_kind", "expected_code"),
    [
        ("absolute", "ASSET_PATH_NOT_CANONICAL"),
        ("traversal", "ASSET_PATH_NOT_CANONICAL"),
        ("windows", "ASSET_PATH_NOT_CANONICAL"),
        ("symlink", "ASSET_PATH_OUTSIDE_WORKSPACE"),
    ],
)
def test_transform_cli_rejects_workspace_escape_before_decode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    path_kind: str,
    expected_code: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.pgm"
    outside.write_bytes((ROOT / "data/fixtures/asset_system/open_fixture.pgm").read_bytes())
    if path_kind == "absolute":
        candidate_path = str(outside)
    elif path_kind == "traversal":
        candidate_path = "../outside.pgm"
    elif path_kind == "windows":
        candidate_path = r"C:\outside.pgm"
    else:
        (workspace / "linked.pgm").symlink_to(outside)
        candidate_path = "linked.pgm"
    record = candidate_record()
    record["asset_ref"] = {
        "path": candidate_path,
        "sha256": sha256_file(outside),
        "mime_type": "image/x-portable-graymap",
        "byte_size": outside.stat().st_size,
    }
    candidates = workspace / "candidates.jsonl"
    candidates.write_text(json.dumps(record) + "\n", encoding="utf-8")
    exit_code = asset_cli(
        [
            "transform",
            "--workspace-root", str(workspace),
            "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
            "--candidates", str(candidates),
            "--representation", "A_layout",
            "--output-dir", str(workspace / "output"),
            "--dry-run",
        ]
    )
    failure = json.loads(capsys.readouterr().err)
    assert exit_code == EXIT_RECORD_FAILURE
    assert failure["code"] == expected_code


def _freeze_cli_fixture(workspace: Path) -> tuple[list[str], list[dict], Path]:
    source = workspace / "source.png"
    image = Image.new("RGB", (16, 12), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, 13, 9), fill=96)
    draw.rectangle((5, 3, 10, 8), fill=32)
    image.save(source)
    original = candidate_record()
    original["asset_ref"] = {
        "path": "source.png",
        "sha256": sha256_file(source),
        "mime_type": "image/png",
        "byte_size": source.stat().st_size,
    }
    config = load_json_config(ROOT / "configs/asset_curation_v1.yaml")
    derived: list[dict] = []
    for representation in ("A_layout", "B_shape", "C_ink"):
        derived.extend(
            transform_candidate(
                original,
                source,
                workspace / "derived",
                representation,
                config,
                logical_output_root="derived",
            )
        )
    originals_path = workspace / "originals.jsonl"
    derived_path = workspace / "derived.jsonl"
    evidence_path = workspace / "rights.jsonl"
    originals_path.write_text(json.dumps(original) + "\n", encoding="utf-8")
    derived_path.write_text("".join(json.dumps(record) + "\n" for record in derived), encoding="utf-8")
    common = [
        "freeze-stimuli",
        "--workspace-root", str(workspace),
        "--config", str(ROOT / "configs/asset_curation_v1.yaml"),
        "--originals", str(originals_path),
        "--derived", str(derived_path),
        "--rights-evidence", str(evidence_path),
        "--output", str(workspace / "stimuli.jsonl"),
        "--created-at", "2026-09-04T00:00:00Z",
        "--fixture-only",
        "--dry-run",
    ]
    return common, derived, evidence_path


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [("missing", "ASSET_FILE_MISSING"), ("forged", "ASSET_SHA256_MISMATCH")],
)
def test_freeze_cli_rejects_missing_or_forged_derived_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tamper: str,
    expected_code: str,
) -> None:
    common, derived, evidence_path = _freeze_cli_fixture(tmp_path)
    evidence_path.write_text(json.dumps(passed_rights_evidence(candidate_record())) + "\n", encoding="utf-8")
    target = tmp_path / derived[0]["asset_ref"]["path"]
    if tamper == "missing":
        target.unlink()
    else:
        payload = target.read_bytes()
        target.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    assert asset_cli(common) == EXIT_RECORD_FAILURE
    assert json.loads(capsys.readouterr().err)["code"] == expected_code


@pytest.mark.parametrize(
    ("evidence_state", "expected_code"),
    [
        ("absent", "RIGHTS_EVIDENCE_MISSING"),
        ("pending", "RIGHTS_EVIDENCE_PENDING"),
        ("conflicting", "RIGHTS_EVIDENCE_CONFLICT"),
        ("tier_mismatch", "RIGHTS_TIER_MISMATCH"),
    ],
)
def test_freeze_cli_requires_unambiguous_passed_rights_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    evidence_state: str,
    expected_code: str,
) -> None:
    common, _, evidence_path = _freeze_cli_fixture(tmp_path)
    evidence = passed_rights_evidence(candidate_record())
    records: list[dict] = []
    if evidence_state == "pending":
        evidence["decision_status"] = "pending_human_review"
        refresh_rights_evidence_id(evidence)
        records = [evidence]
    elif evidence_state == "conflicting":
        conflicting = copy.deepcopy(evidence)
        conflicting["rights_evidence_id"] = "rights_fixture_conflicting"
        conflicting["rights_tier"] = "research_local_only"
        refresh_rights_evidence_id(conflicting)
        records = [evidence, conflicting]
    elif evidence_state == "tier_mismatch":
        evidence["rights_tier"] = "research_local_only"
        refresh_rights_evidence_id(evidence)
        records = [evidence]
    evidence_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    assert asset_cli(common) == EXIT_RECORD_FAILURE
    assert json.loads(capsys.readouterr().err)["code"] == expected_code


def test_freeze_cli_rejects_forged_rights_evidence_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common, _, evidence_path = _freeze_cli_fixture(tmp_path)
    evidence = passed_rights_evidence(candidate_record())
    evidence["checked_by"] = "forged_reviewer"
    evidence_path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    assert asset_cli(common) == EXIT_RECORD_FAILURE
    assert json.loads(capsys.readouterr().err)["code"] == "RIGHTS_EVIDENCE_ID_MISMATCH"


def test_freeze_cli_validates_orphan_derived_records(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    common, derived, evidence_path = _freeze_cli_fixture(tmp_path)
    evidence_path.write_text(json.dumps(passed_rights_evidence(candidate_record())) + "\n", encoding="utf-8")
    orphan = copy.deepcopy(derived[0])
    orphan["asset_id"] = "asset_orphan_invalid"
    orphan["parent_asset_id"] = "asset_unknown_parent"
    orphan["asset_role"] = "invalid_role"
    (tmp_path / "derived.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in [*derived, orphan]),
        encoding="utf-8",
    )
    assert asset_cli(common) == EXIT_RECORD_FAILURE
    failures = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert any(
        failure["record_id"] == "asset_orphan_invalid" and failure["code"] == "CANDIDATE_SCHEMA_INVALID"
        for failure in failures
    )


@pytest.mark.parametrize(
    ("path_kind", "expected_code"),
    [
        ("absolute", "ASSET_PATH_NOT_CANONICAL"),
        ("traversal", "ASSET_PATH_NOT_CANONICAL"),
        ("symlink", "ASSET_PATH_OUTSIDE_WORKSPACE"),
    ],
)
def test_freeze_cli_rejects_derived_workspace_escape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    path_kind: str,
    expected_code: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    common, derived, evidence_path = _freeze_cli_fixture(workspace)
    evidence_path.write_text(json.dumps(passed_rights_evidence(candidate_record())) + "\n", encoding="utf-8")
    original_path = workspace / derived[0]["asset_ref"]["path"]
    outside = tmp_path / "outside.png"
    outside.write_bytes(original_path.read_bytes())
    if path_kind == "absolute":
        derived[0]["asset_ref"]["path"] = str(outside)
    elif path_kind == "traversal":
        derived[0]["asset_ref"]["path"] = "../outside.png"
    else:
        (workspace / "linked.png").symlink_to(outside)
        derived[0]["asset_ref"]["path"] = "linked.png"
    (workspace / "derived.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in derived),
        encoding="utf-8",
    )
    assert asset_cli(common) == EXIT_RECORD_FAILURE
    assert json.loads(capsys.readouterr().err)["code"] == expected_code
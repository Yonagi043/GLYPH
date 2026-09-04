import csv
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import pytest

from glyph_features.vision_system.cli import main as vision_main
from glyph_features.vision_system.compat import long_to_v1_wide, v1_wide_to_long
from glyph_features.vision_system.definitions import canonical_sha256, load_registry
from glyph_features.vision_system.extract import (
    VisionSystemError,
    _safe_repo_file,
    extract_handoff,
    measure_array,
    sha256_file,
)
from glyph_features.vision_system.handoff import build_handoff_bundle, validate_handoff
from glyph_features.vision_system.qc import qc_run, verify_checksums


ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def registry():
    return load_registry(ROOT / "configs/visual_measurements_v2.yaml", ROOT / "schema")


def _registry_with_algorithm_defaults(tmp_path, **overrides):
    payload = json.loads((ROOT / "configs/visual_measurements_v2.yaml").read_text(encoding="utf-8"))
    payload["algorithm_defaults"].update(overrides)
    config_sha256 = canonical_sha256(payload["algorithm_defaults"])
    payload["algorithm_config_sha256"] = config_sha256
    for definition in payload["features"]:
        definition["algorithm"]["default_config_sha256"] = config_sha256
    path = tmp_path / f"registry-{config_sha256[:12]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_registry(path, ROOT / "schema")


def test_registry_maps_eight_dimensions_to_ten_constructs_without_scores():
    registry = load_registry(ROOT / "configs/visual_measurements_v2.yaml", ROOT / "schema")

    assert registry.version == "2.0.1"
    assert registry.dimension_codes == {
        "geometry",
        "density",
        "proportion",
        "stroke_gesture",
        "layout",
        "visual_center",
        "reading_rhythm",
        "uniformity",
    }
    assert registry.construct_codes == {
        "D1_balance",
        "D2_symmetry",
        "D3_proportion_scale",
        "D4_unity_consistency",
        "D5_rhythm_sequence",
        "C1_brushwork_line_quality",
        "C2_character_structure",
        "C3_spatial_arrangement",
        "C4_ink_tone",
        "C5_qi_movement_proxy",
    }
    assert len(registry.feature_codes) == len(set(registry.feature_codes))
    assert len(registry.active_feature_codes) == 20
    assert len(registry.feature_codes) == 28
    assert {
        definition["feature_code"]
        for definition in registry.definitions
        if definition["status"] == "deprecated"
    } == {
        "whitespace_ratio",
        "straight_curve_ratio",
        "inter_glyph_spacing_mean_norm",
        "inter_glyph_spacing_sd_norm",
        "rhythm_periodicity",
        "unit_area_cv",
        "unit_width_cv",
        "unit_height_cv",
    }
    assert "total_score" not in registry.feature_codes
    assert all("score" not in code for code in registry.feature_codes)


def test_algorithm_threshold_connectivity_and_holes_drive_measurements(tmp_path):
    low_threshold = _registry_with_algorithm_defaults(tmp_path, binary_threshold=100)
    high_threshold = _registry_with_algorithm_defaults(tmp_path, binary_threshold=200)
    threshold_case = np.full((5, 5), 255, dtype=np.uint8)
    threshold_case[2, 1:4] = 150
    assert measure_array(threshold_case, "B_shape", low_threshold)["ink_coverage_ratio"].value is None
    assert measure_array(threshold_case, "B_shape", high_threshold)["ink_coverage_ratio"].value == pytest.approx(3 / 25)

    diagonal = np.full((4, 4), 255, dtype=np.uint8)
    diagonal[1, 1] = 0
    diagonal[2, 2] = 0
    four_components = _registry_with_algorithm_defaults(tmp_path, component_connectivity=4)
    eight_components = _registry_with_algorithm_defaults(tmp_path, component_connectivity=8)
    assert measure_array(diagonal, "B_shape", four_components)["connected_component_count"].value == 2
    assert measure_array(diagonal, "B_shape", eight_components)["connected_component_count"].value == 1

    diagonal_vent = np.full((5, 5), 255, dtype=np.uint8)
    diagonal_vent[1:4, 1:4] = 0
    diagonal_vent[1, 1] = 255
    diagonal_vent[2, 2] = 255
    four_holes = _registry_with_algorithm_defaults(tmp_path, hole_connectivity=4)
    eight_holes = _registry_with_algorithm_defaults(tmp_path, hole_connectivity=8)
    assert measure_array(diagonal_vent, "B_shape", four_holes)["closure_count"].value == 1
    assert measure_array(diagonal_vent, "B_shape", eight_holes)["closure_count"].value == 0


def test_algorithm_skeleton_symmetry_and_tonal_bins_are_executable(tmp_path, registry):
    line = np.full((7, 9), 255, dtype=np.uint8)
    line[3, 2:7] = 0
    assert measure_array(line, "B_shape", registry)["skeleton_endpoint_count"].value == 2

    asymmetric = np.full((4, 6), 255, dtype=np.uint8)
    asymmetric[1:3, 1] = 0
    asymmetric[2, 2] = 0
    expected_differences = np.count_nonzero((asymmetric < 128) != np.fliplr(asymmetric < 128))
    expected_similarity = 1.0 - expected_differences / asymmetric.size
    assert measure_array(asymmetric, "B_shape", registry)["symmetry_horizontal"].value == pytest.approx(expected_similarity)

    tonal = np.asarray([[0, 16, 64, 80], [128, 144, 192, 208]], dtype=np.uint8)
    four_bins = _registry_with_algorithm_defaults(tmp_path, tonal_bins=4)
    thirty_two_bins = _registry_with_algorithm_defaults(tmp_path, tonal_bins=32)
    assert measure_array(tonal, "C_ink", four_bins)["gray_entropy_ink"].value == pytest.approx(2.0)
    assert measure_array(tonal, "C_ink", thirty_two_bins)["gray_entropy_ink"].value == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("component_connectivity", 6),
        ("hole_connectivity", 6),
        ("skeleton_algorithm", "unknown.skeletonizer"),
        ("symmetry_alignment", "foreground_bbox"),
    ],
)
def test_unsupported_algorithm_enum_has_stable_code(tmp_path, field, value):
    with pytest.raises(ValueError, match=rf"ALGORITHM_CONFIG_UNSUPPORTED.*{field}"):
        _registry_with_algorithm_defaults(tmp_path, **{field: value})


def test_task01_fixture_extracts_schema_valid_long_records_without_scores(tmp_path, registry):
    output = tmp_path / "extract_fixture_contract"
    summary = extract_handoff(
        workspace_root=ROOT,
        handoff_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
        registry_path=ROOT / "configs/visual_measurements_v2.yaml",
        schema_root=ROOT / "schema",
        output_dir=output,
        extraction_run_id="extract_fixture_contract",
        computed_at="2026-09-04T08:00:00Z",
        allow_fixture=True,
    )

    records = [json.loads(line) for line in (output / "measurements.jsonl").read_text().splitlines()]
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert summary["failure_count"] == 0
    assert summary["measurement_count"] == len(records)
    assert {record["representation"] for record in records} == {"A_layout", "B_shape", "C_ink"}
    assert {record["measurement_status"] for record in records} <= {"valid", "missing"}
    assert all(record["input_sha256"] and record["algorithm_config_sha256"] for record in records)
    assert canonical_sha256(manifest["resolved_algorithm_config"]) == manifest["algorithm_config_sha256"]
    assert manifest["resolved_algorithm_config"] == registry.payload["algorithm_defaults"]
    assert manifest["task01_lineage"]["handoff"]["sha256"] == manifest["task01_handoff_sha256"]
    assert {record["source_contract_sha256"] for record in records} == {manifest["task01_handoff_sha256"]}
    assert {item["representation"] for item in manifest["supporting_representations"]} == {"B_shape_mask"}
    assert {
        manifest["task01_lineage"][key]["path"]
        for key in ("asset_candidates", "stimuli")
    } == {
        "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/stimuli.jsonl",
    }
    assert all(
        record["value"] is None or math.isfinite(record["value"])
        for record in records
    )
    assert "score" not in json.dumps(records, ensure_ascii=False).lower()


def test_cli_extract_qc_and_no_overwrite_contract(tmp_path):
    run_dir = tmp_path / "cli_reference_run"
    common = ["--workspace-root", str(ROOT), "--schema-root", str(ROOT / "schema")]

    assert vision_main([
        "validate-definitions",
        *common,
        "--registry", str(ROOT / "configs/visual_measurements_v2.yaml"),
    ]) == 0
    extract_args = [
        "extract",
        *common,
        "--registry", str(ROOT / "configs/visual_measurements_v2.yaml"),
        "--asset-handoff", str(ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"),
        "--output-dir", str(run_dir),
        "--run-id", "cli_reference_run",
        "--computed-at", "2026-09-04T08:00:00Z",
        "--allow-fixture",
    ]
    assert vision_main(extract_args) == 0
    assert vision_main(extract_args) == 3
    assert vision_main(["qc", *common, "--run-dir", str(run_dir)]) == 0

    quality = json.loads((run_dir / "quality_report.json").read_text())
    assert quality["computational_stability"]["status"] == "passed"
    assert quality["surface_validity"]["status"] == "blocked"
    assert quality["construct_validity"]["status"] == "blocked"
    assert quality["predictive_validity"]["status"] == "blocked"
    assert quality["readiness"] == {
        "engineering_ready": True,
        "pilot_ready": False,
        "research_validated": False,
    }


def test_analytic_rectangle_keeps_layout_position_and_exact_ratios(registry):
    left = np.full((20, 20), 255, dtype=np.uint8)
    left[5:15, 2:6] = 0
    shifted = np.full_like(left, 255)
    shifted[5:15, 8:12] = 0

    left_metrics = measure_array(left, "A_layout", registry)
    shifted_metrics = measure_array(shifted, "A_layout", registry)
    shape_metrics = measure_array(left, "B_shape", registry)
    assert left_metrics["ink_coverage_ratio"].value == pytest.approx(0.1)
    assert shape_metrics["bbox_fill_ratio"].value == pytest.approx(1.0)
    assert left_metrics["bbox_aspect_ratio"].value == pytest.approx(0.4)
    assert left_metrics["centroid_x_norm"].value == pytest.approx(0.175)
    assert shifted_metrics["centroid_x_norm"].value == pytest.approx(0.475)
    assert left_metrics["centroid_y_norm"].value == shifted_metrics["centroid_y_norm"].value


def test_brightness_changes_ink_metrics_not_binary_shape(registry):
    dark = np.full((24, 24), 255, dtype=np.uint8)
    dark[6:18, 6:10] = 20
    dark[6:18, 10:14] = 50
    dark[6:18, 14:18] = 80
    lighter = dark.copy()
    lighter[dark < 128] += 20

    dark_shape = measure_array(dark, "B_shape", registry)
    light_shape = measure_array(lighter, "B_shape", registry)
    for code in ("ink_coverage_ratio", "bbox_fill_ratio", "bbox_aspect_ratio", "connected_component_count"):
        assert dark_shape[code].value == light_shape[code].value
    dark_ink = measure_array(dark, "C_ink", registry)
    light_ink = measure_array(lighter, "C_ink", registry)
    assert dark_ink["gray_mean_ink"].value > light_ink["gray_mean_ink"].value
    assert dark_ink["gray_entropy_ink"].value == pytest.approx(light_ink["gray_entropy_ink"].value)


def test_cross_script_small_components_are_never_silently_removed(registry):
    fixture = json.loads(
        (ROOT / "data/fixtures/visual_measurements/cross_script_component_cases.json").read_text()
    )
    assert fixture["license"] == "CC0-1.0"
    for case in fixture["cases"]:
        image = np.full((32, 32), 255, dtype=np.uint8)
        for x0, y0, x1, y1 in case["rectangles"]:
            image[y0:y1, x0:x1] = 0
        metrics = measure_array(image, "B_shape", registry)
        assert metrics["connected_component_count"].value == case["expected_component_count"], case["case_id"]


def test_v1_wide_long_round_trip_preserves_historical_semantics(tmp_path):
    run = ROOT / "data/processed/visual_features_v1/runs/render_551362ca0ff22f33"
    source = run / "visual_features.csv"
    long_output = tmp_path / "v1_measurements.jsonl"
    reconstructed = tmp_path / "visual_features.roundtrip.csv"

    summary = v1_wide_to_long(
        csv_path=source,
        run_manifest_path=run / "run_manifest.json",
        registry_path=ROOT / "configs/visual_measurements_v2.yaml",
        schema_root=ROOT / "schema",
        workspace_root=ROOT,
        output_path=long_output,
    )
    long_to_v1_wide(long_output, reconstructed, ROOT / "schema")

    with source.open(encoding="utf-8", newline="") as handle:
        expected = list(csv.DictReader(handle))
    with reconstructed.open(encoding="utf-8", newline="") as handle:
        actual = list(csv.DictReader(handle))
    assert summary["wide_record_count"] == len(expected)
    assert summary["long_record_count"] == len(expected) * 17
    assert len(actual) == len(expected)
    json_fields = {
        "feature_numerators_json",
        "feature_denominators_json",
        "feature_units_json",
        "feature_applicability_json",
        "missing_reasons_json",
    }
    numeric_fields = set(expected[0]) - {
        "feature_record_id", "stimulus_id", "extraction_run_id", "feature_definition_version",
        "representation", "normalization_profile", "dimensions", "applicability",
        "measurement_status", "missing_reason", "algorithm_config_sha256", *json_fields,
    }
    for expected_row, actual_row in zip(expected, actual):
        for field in expected_row:
            if field in json_fields:
                assert json.loads(actual_row[field]) == json.loads(expected_row[field])
            elif field in numeric_fields and expected_row[field] != "":
                assert float(actual_row[field]) == float(expected_row[field])
            else:
                assert actual_row[field] == expected_row[field]
    assert "total_score" not in long_output.read_text(encoding="utf-8")


def test_empty_and_degenerate_images_are_explicit_missing_not_nonfinite(registry):
    with pytest.raises(VisionSystemError, match="IMAGE_SHAPE_INVALID"):
        measure_array(np.empty((0, 0), dtype=np.uint8), "A_layout", registry)

    white = measure_array(np.full((16, 16), 255, dtype=np.uint8), "A_layout", registry)
    assert all(metric.value is None and metric.missing_code for metric in white.values())

    black = measure_array(np.zeros((16, 16), dtype=np.uint8), "C_ink", registry)
    assert black["gray_mean_ink"].value is None
    assert black["gray_mean_ink"].missing_code == "INSUFFICIENT_TONAL_RANGE"
    assert all(metric.value is None or math.isfinite(float(metric.value)) for metric in black.values())


def test_representation_applicability_is_registry_driven(registry):
    image = np.full((16, 16), 255, dtype=np.uint8)
    image[4:12, 5:11] = np.arange(48, dtype=np.uint8).reshape(8, 6) + 20
    for representation in ("A_layout", "B_shape", "C_ink"):
        measured = measure_array(image, representation, registry)
        for definition in registry.definitions:
            if representation not in definition["input_representations"]:
                assert measured[definition["feature_code"]].missing_code == "REPRESENTATION_NOT_APPLICABLE"


def test_task01_handoff_tamper_and_path_escape_are_rejected(tmp_path):
    with pytest.raises(VisionSystemError, match="UNSAFE_PATH"):
        _safe_repo_file(ROOT, "../outside.png")

    source = ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"
    with tempfile.TemporaryDirectory(prefix="task02-tampered-", dir=ROOT) as directory:
        tampered = Path(directory) / "handoff_manifest.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["created_at"] = "2026-09-04T00:00:00Z"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(VisionSystemError, match="TASK01_HANDOFF_INVALID"):
            extract_handoff(
                workspace_root=ROOT,
                handoff_path=tampered,
                registry_path=ROOT / "configs/visual_measurements_v2.yaml",
                schema_root=ROOT / "schema",
                output_dir=tmp_path / "must_not_publish",
                extraction_run_id="tampered_handoff",
                computed_at="2026-09-04T08:00:00Z",
                allow_fixture=True,
            )


@pytest.mark.parametrize(
    "tamper,expected_code",
    [
        ("input", "INPUT_HASH_MISMATCH"),
        ("registry", "REGISTRY_HASH_MISMATCH"),
        ("config", "ALGORITHM_CONFIG_HASH_MISMATCH"),
        ("resolved_config", "ALGORITHM_CONFIG_RESOLUTION_MISMATCH"),
        ("task01_contract", "TASK01_CONTRACT_HASH_MISMATCH"),
        ("measurement", "COMPUTATIONAL_STABILITY_FAILED"),
    ],
)
def test_qc_detects_integrity_tampering(tmp_path, tamper, expected_code):
    source_run = _fixture_run(tmp_path / "source", "qc_tamper_source")
    isolated_root, run = _isolate_qc_run(tmp_path / tamper, source_run)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "input":
        input_path = isolated_root / manifest["input_representations"][0]["path"]
        input_path.write_bytes(input_path.read_bytes() + b"tampered")
    elif tamper == "registry":
        registry_path = isolated_root / manifest["registry_path"]
        registry_path.write_text(registry_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif tamper == "config":
        manifest["algorithm_config_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif tamper == "resolved_config":
        manifest["resolved_algorithm_config"]["tonal_bins"] = 4
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif tamper == "task01_contract":
        task01_path = isolated_root / manifest["task01_handoff_path"]
        task01_path.write_text(task01_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    else:
        records = [json.loads(line) for line in (run / "measurements.jsonl").read_text().splitlines()]
        record = next(item for item in records if item["measurement_status"] == "valid")
        record["value"] = float(record["value"]) + 0.125
        (run / "measurements.jsonl").write_text(
            "".join(json.dumps(item, allow_nan=False) + "\n" for item in records),
            encoding="utf-8",
        )
    report = qc_run(run, isolated_root, ROOT / "schema")
    assert expected_code in {error["code"] for error in report["errors"]}
    assert report["readiness"]["engineering_ready"] is False


def test_qc_rejects_nonfinite_json_and_checksum_tampering(tmp_path):
    source_run = _fixture_run(tmp_path / "source", "qc_nonfinite_source")
    isolated_root, nonfinite_run = _isolate_qc_run(tmp_path / "nonfinite", source_run)
    measurement_path = nonfinite_run / "measurements.jsonl"
    measurement_path.write_text(measurement_path.read_text().replace('"value":', '"value":NaN,"replaced_value":', 1))
    with pytest.raises(VisionSystemError, match="NONFINITE_JSON"):
        qc_run(nonfinite_run, isolated_root, ROOT / "schema")

    clean_root, clean_run = _isolate_qc_run(tmp_path / "checksum", source_run)
    report = qc_run(clean_run, clean_root, ROOT / "schema")
    assert report["readiness"]["engineering_ready"] is True
    assert verify_checksums(clean_run) == []
    (clean_run / "measurements.jsonl").write_text(
        (clean_run / "measurements.jsonl").read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert verify_checksums(clean_run) == ["hash mismatch: measurements.jsonl"]


def test_extract_partial_failure_returns_one_and_retains_completed_records(tmp_path, monkeypatch):
    from glyph_features.vision_system import extract as extract_module

    original_load = extract_module._load_grayscale

    def fail_shape(path):
        if ".B_shape." in path.name:
            raise VisionSystemError("SIMULATED_DECODE_FAILURE", path.name)
        return original_load(path)

    monkeypatch.setattr(extract_module, "_load_grayscale", fail_shape)
    output = tmp_path / "partial_failure"
    exit_code = vision_main([
        "extract",
        "--workspace-root", str(ROOT),
        "--schema-root", str(ROOT / "schema"),
        "--registry", str(ROOT / "configs/visual_measurements_v2.yaml"),
        "--asset-handoff", str(ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"),
        "--output-dir", str(output),
        "--run-id", "partial_failure",
        "--computed-at", "2026-09-04T08:00:00Z",
        "--allow-fixture",
    ])

    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    failures = [json.loads(line) for line in (output / "failures.jsonl").read_text().splitlines()]
    records = [json.loads(line) for line in (output / "measurements.jsonl").read_text().splitlines()]
    assert exit_code == 1
    assert manifest["failure_count"] == 1
    assert failures[0]["representation"] == "B_shape"
    assert {record["representation"] for record in records} == {"A_layout", "C_ink"}
    assert str(ROOT) not in json.dumps(manifest)


def test_v1_adapter_rejects_unknown_wide_column(tmp_path):
    run = ROOT / "data/processed/visual_features_v1/runs/render_551362ca0ff22f33"
    source = run / "visual_features.csv"
    modified = tmp_path / "unknown_column.csv"
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = [*(reader.fieldnames or []), "mystery_score"]
    with modified.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "mystery_score": "99"})

    with pytest.raises(VisionSystemError, match="V1_COLUMNS_INVALID"):
        v1_wide_to_long(
            csv_path=modified,
            run_manifest_path=run / "run_manifest.json",
            registry_path=ROOT / "configs/visual_measurements_v2.yaml",
            schema_root=ROOT / "schema",
            workspace_root=ROOT,
            output_path=tmp_path / "must_not_write.jsonl",
        )


def test_handoff_build_validate_tamper_and_no_overwrite(tmp_path):
    root, output, manifest = _build_handoff_test_repo(tmp_path)

    assert validate_handoff(manifest, root) == []
    assert vision_main([
        "validate-handoff",
        "--workspace-root", str(root),
        "--schema-root", str(root / "schema"),
        str(manifest),
    ]) == 0
    with pytest.raises(FileExistsError):
        build_handoff_bundle(
            workspace_root=root,
            reference_run_dir=root / "data/fixtures/visual_measurements/reference_run_v1",
            output_dir=output,
            git_commit=_git_head(root),
            created_at="2026-09-04T09:00:00Z",
        )

    measurement_path = root / "data/fixtures/visual_measurements/reference_run_v1/measurements.jsonl"
    measurement_path.write_text(measurement_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    errors = validate_handoff(manifest, root)
    assert any("hash mismatch" in error for error in errors)
    assert any("reference checksum" in error for error in errors)


def test_handoff_rejects_rehashed_cross_artifact_lineage_fork(tmp_path, capsys):
    root, output, manifest_path = _build_handoff_test_repo(tmp_path)
    run = root / "data/fixtures/visual_measurements/reference_run_v1"
    task01_path = root / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"
    measurements_path = run / "measurements.jsonl"

    measurements = [json.loads(line) for line in measurements_path.read_text(encoding="utf-8").splitlines()]
    original_contract_sha256 = sha256_file(task01_path)
    assert {record["source_contract_sha256"] for record in measurements} == {original_contract_sha256}

    task01 = json.loads(task01_path.read_text(encoding="utf-8"))
    task01["created_at"] = "2026-09-04T04:08:00Z"
    _write_json_test(task01_path, task01)
    forked_contract_sha256 = sha256_file(task01_path)

    run_manifest_path = run / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["task01_handoff_sha256"] = forked_contract_sha256
    run_manifest["input_representations"][0]["asset_id"] = "asset_semantic_fork"
    _write_json_test(run_manifest_path, run_manifest)

    measurements[0]["input_sha256"] = "f" * 64
    measurements_path.write_text(
        "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in measurements),
        encoding="utf-8",
    )
    _refresh_checksums(run / "checksums.sha256", run)

    handoff = json.loads(manifest_path.read_text(encoding="utf-8"))
    next(item for item in handoff["input_snapshots"] if item["logical_type"] == "task01_handoff")["sha256"] = forked_contract_sha256
    for logical_type, path in {
        "long_measurements": measurements_path,
        "run_manifest": run_manifest_path,
        "reference_checksums": run / "checksums.sha256",
    }.items():
        next(item for item in handoff["outputs"] if item["logical_type"] == logical_type)["sha256"] = sha256_file(path)
    _write_json_test(manifest_path, handoff)
    _refresh_checksums(output / "checksums.sha256", output)

    errors = validate_handoff(manifest_path, root)
    assert any("task01_handoff.accepted_checkpoint_sha256" in error for error in errors)
    assert any("run_manifest.input_representations[0].asset_id" in error for error in errors)
    assert any("measurements[0].source_contract_sha256" in error for error in errors)
    assert any("measurements[0].input_sha256" in error for error in errors)
    assert vision_main([
        "validate-handoff",
        "--workspace-root", str(root),
        "--schema-root", str(root / "schema"),
        str(manifest_path),
    ]) == 1
    assert "source_contract_sha256" in capsys.readouterr().err


def _build_handoff_test_repo(tmp_path):
    source_run = _fixture_run(tmp_path / "source", "handoff_contract")
    qc_run(source_run, ROOT, ROOT / "schema")
    root = tmp_path / "repo"
    files = [
        "pyproject.toml",
        "runtime.lock.json",
        "configs/visual_measurements_v2.yaml",
        "schema/visual_feature_definition.schema.json",
        "schema/visual_measurement.schema.json",
        "schema/visual_measurement_handoff.schema.json",
        "schema/visual_expert_gate.schema.json",
        "docs/visual_measurement_protocol_zh.md",
        "docs/visual_measurement_migration_zh.md",
        "data/fixtures/visual_measurements/cross_script_component_cases.json",
        "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/stimuli.jsonl",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/derived/asset_6e451135614c28ccf86c714a.A_layout.png",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/derived/asset_c7e16ea61e90d876c6fe05b9.B_shape.png",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/derived/asset_904a6f00145466ed82ec606f.mask.png",
        "data/fixtures/asset_system/reference_handoff_v1/fixture/derived/asset_e3d69a8b57fddd8087ffb0f1.C_ink.png",
    ]
    for relative in files:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    shutil.copytree(
        ROOT / "src/glyph_features/vision_system",
        root / "src/glyph_features/vision_system",
    )
    shutil.copytree(
        source_run,
        root / "data/fixtures/visual_measurements/reference_run_v1",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _git_add_paths(root, [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts])
    subprocess.run(
        [
            "git", "-c", "user.name=TASK-02 Test", "-c", "user.email=task02@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", "upstream snapshot",
        ],
        cwd=root,
        check=True,
    )
    upstream_commit = _git_head(root)
    config_path = root / "configs/visual_measurements_v2.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["accepted_task01_commit"] = upstream_commit
    _write_json_test(config_path, config)
    run = root / "data/fixtures/visual_measurements/reference_run_v1"
    registry_path = run / "feature_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["accepted_task01_commit"] = upstream_commit
    _write_json_test(registry_path, registry)
    run_manifest_path = run / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    run_manifest["accepted_task01_commit"] = upstream_commit
    run_manifest["task01_lineage"]["accepted_commit"] = upstream_commit
    run_manifest["registry_sha256"] = sha256_file(config_path)
    _write_json_test(run_manifest_path, run_manifest)
    _refresh_checksums(run / "checksums.sha256", run)
    _git_add_paths(
        root,
        [config_path, registry_path, run_manifest_path, run / "checksums.sha256"],
    )
    subprocess.run(
        [
            "git", "-c", "user.name=TASK-02 Test", "-c", "user.email=task02@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture producer",
        ],
        cwd=root,
        check=True,
    )
    git_commit = _git_head(root)
    output = root / "data/fixtures/visual_measurements/reference_handoff_v1"

    summary = build_handoff_bundle(
        workspace_root=root,
        reference_run_dir=root / "data/fixtures/visual_measurements/reference_run_v1",
        output_dir=output,
        git_commit=git_commit,
        created_at="2026-09-04T09:00:00Z",
    )

    assert summary["valid"] is True
    return root, output, output / "handoff_manifest.json"


def _git_head(root):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()


def _git_add_paths(root, paths):
    relative_paths = [str(path.relative_to(root)) for path in paths]
    subprocess.run(["git", "add", "--", *relative_paths], cwd=root, check=True)


def _write_json_test(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _refresh_checksums(checksum_path, root):
    names = [line.split("  ", 1)[1] for line in checksum_path.read_text(encoding="utf-8").splitlines() if line]
    checksum_path.write_text(
        "".join(f"{sha256_file(root / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


def _fixture_run(parent: Path, run_id: str) -> Path:
    run = parent / run_id
    extract_handoff(
        workspace_root=ROOT,
        handoff_path=ROOT / "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json",
        registry_path=ROOT / "configs/visual_measurements_v2.yaml",
        schema_root=ROOT / "schema",
        output_dir=run,
        extraction_run_id=run_id,
        computed_at="2026-09-04T08:00:00Z",
        allow_fixture=True,
    )
    return run


def _isolate_qc_run(parent: Path, source_run: Path) -> tuple[Path, Path]:
    root = parent / "root"
    run = root / "run"
    shutil.copytree(source_run, run)
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    relative_paths = [
        manifest["registry_path"],
        manifest["task01_handoff_path"],
        manifest["task01_lineage"]["asset_candidates"]["path"],
        manifest["task01_lineage"]["stimuli"]["path"],
        *(item["path"] for item in manifest["input_representations"]),
        *(item["path"] for item in manifest["supporting_representations"]),
    ]
    for relative in relative_paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    return root, run
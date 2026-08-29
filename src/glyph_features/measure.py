"""Feature extraction from immutable v1 render outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.morphology import skeletonize

FEATURES = [
    "ink_coverage_ratio", "whitespace_ratio", "bbox_fill_ratio", "bbox_aspect_ratio",
    "connected_component_count", "closure_count", "symmetry_horizontal", "symmetry_vertical",
    "straight_curve_ratio", "centroid_x_norm", "centroid_y_norm",
    "inter_glyph_spacing_mean_norm", "inter_glyph_spacing_sd_norm", "rhythm_periodicity",
    "unit_area_cv", "unit_width_cv", "unit_height_cv",
]
DIMENSIONS = {
    "ink_coverage_ratio": ["density"], "whitespace_ratio": ["density"], "bbox_fill_ratio": ["density"],
    "bbox_aspect_ratio": ["proportion"], "connected_component_count": ["density"], "closure_count": ["density"],
    "symmetry_horizontal": ["geometry"], "symmetry_vertical": ["geometry"], "straight_curve_ratio": ["stroke_gesture"],
    "centroid_x_norm": ["visual_center"], "centroid_y_norm": ["visual_center"],
    "inter_glyph_spacing_mean_norm": ["layout", "reading_rhythm"], "inter_glyph_spacing_sd_norm": ["layout", "reading_rhythm"],
    "rhythm_periodicity": ["reading_rhythm"], "unit_area_cv": ["uniformity"], "unit_width_cv": ["uniformity"], "unit_height_cv": ["uniformity"],
}
MULTI_ONLY = {"inter_glyph_spacing_mean_norm", "inter_glyph_spacing_sd_norm", "rhythm_periodicity", "unit_area_cv", "unit_width_cv", "unit_height_cv"}
UNITS = {
    "ink_coverage_ratio": "ratio", "whitespace_ratio": "ratio", "bbox_fill_ratio": "ratio",
    "bbox_aspect_ratio": "ratio", "connected_component_count": "count", "closure_count": "count",
    "symmetry_horizontal": "ratio", "symmetry_vertical": "ratio", "straight_curve_ratio": "ratio",
    "centroid_x_norm": "ratio", "centroid_y_norm": "ratio", "inter_glyph_spacing_mean_norm": "ratio",
    "inter_glyph_spacing_sd_norm": "ratio", "rhythm_periodicity": "ratio", "unit_area_cv": "ratio",
    "unit_width_cv": "ratio", "unit_height_cv": "ratio",
}


def _stats(path: str | Path, threshold: int = 128) -> dict[str, Any] | None:
    image = Image.open(path).convert("L")
    width, height = image.size
    array = np.asarray(image, dtype=np.uint8)
    foreground = array < threshold
    ys, xs = np.nonzero(foreground)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    bbox_width, bbox_height = x1 - x0, y1 - y0
    area = int(foreground.sum())
    def symmetry(axis: str) -> float:
        flipped = np.fliplr(foreground) if axis == "horizontal" else np.flipud(foreground)
        difference = np.count_nonzero(foreground != flipped)
        return 1.0 - float(difference) / (width * height)

    # Work on the ink bounding box. SciPy labels make the frozen 8-neighbour
    # component definition and the complementary 4-neighbour hole definition
    # practical at the protocol canvas size.
    local = foreground[y0:y1, x0:x1]
    components = int(ndimage.label(local, structure=np.ones((3, 3), dtype=np.uint8))[1])
    inner = ~local
    labels, background_regions = ndimage.label(inner, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8))
    edge_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    holes = int(background_regions - len(edge_labels[edge_labels != 0]))
    skeleton = skeletonize(local)
    skeleton_y, skeleton_x = np.nonzero(skeleton)
    total_length = 0.0
    straight_length = 0.0
    if skeleton_x.size:
        # Count each undirected 8-neighbour edge once, then classify degree-2
        # pixels by the frozen 15-degree local direction rule.
        offsets = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
        total_length = float(sum(np.count_nonzero(skeleton[max(0, dy): skeleton.shape[0] + min(0, dy), max(0, dx): skeleton.shape[1] + min(0, dx)] & skeleton[max(0, -dy): skeleton.shape[0] - max(0, dy), max(0, -dx): skeleton.shape[1] - max(0, dx)]) * math.hypot(dy, dx) for dy, dx in offsets if (dy, dx) in ((0, 1), (1, 0), (1, 1), (1, -1))))
        for y, x in zip(skeleton_y.tolist(), skeleton_x.tolist()):
            neighbours = [(dy, dx) for dy, dx in offsets if 0 <= y + dy < skeleton.shape[0] and 0 <= x + dx < skeleton.shape[1] and skeleton[y + dy, x + dx]]
            if len(neighbours) != 2:
                continue
            (dy1, dx1), (dy2, dx2) = neighbours
            v1 = np.array([dy1, dx1], dtype=float)
            v2 = np.array([dy2, dx2], dtype=float)
            cosine = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
            turn = abs(180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
            if turn <= 15.0:
                straight_length += (float(np.linalg.norm(v1)) + float(np.linalg.norm(v2))) / 2.0
    straight_curve = None if total_length == 0 else straight_length / total_length
    return {
        "ink_coverage_ratio": area / (width * height), "whitespace_ratio": 1 - area / (width * height),
        "bbox_fill_ratio": area / (bbox_width * bbox_height), "bbox_aspect_ratio": bbox_width / bbox_height,
        "connected_component_count": components, "closure_count": max(0, holes),
        "symmetry_horizontal": symmetry("horizontal"), "symmetry_vertical": symmetry("vertical"),
        "centroid_x_norm": float(xs.mean() / width), "centroid_y_norm": float(ys.mean() / height),
        "straight_curve_ratio": straight_curve,
        "bbox": [x0, y0, x1, y1], "width": width, "height": height, "area": area,
    }


def _cv(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = float(np.mean(values))
    return None if mean == 0 else float(np.std(values, ddof=0) / mean)


def _sequence_features(record: dict[str, Any], stats: dict[str, Any], foreground: np.ndarray) -> dict[str, Any]:
    boxes = [box for box in record.get("unit_bboxes", []) if box]
    if len(boxes) < 2:
        return {key: None for key in MULTI_ONLY}
    bbox_height = max(1, stats["bbox"][3] - stats["bbox"][1])
    gaps = [((boxes[i + 1][0] - boxes[i][2]) / bbox_height) for i in range(len(boxes) - 1)]
    widths = [float(box[2] - box[0]) for box in boxes]
    heights = [float(box[3] - box[1]) for box in boxes]
    areas = []
    for box in boxes:
        x0, y0, x1, y1 = [int(v) for v in box]
        areas.append(float(foreground[max(0, y0):min(foreground.shape[0], y1), max(0, x0):min(foreground.shape[1], x1)].sum()))
    periodicity = None
    if len(gaps) >= 4:
        values = np.asarray(gaps, dtype=float)
        values = values - values.mean()
        denom = float(np.dot(values, values))
        if denom:
            periodicity = float(max(0.0, min(1.0, np.max([abs(np.dot(values[:-lag], values[lag:]) / denom) for lag in range(1, len(values))]))))
    return {
        "inter_glyph_spacing_mean_norm": float(np.mean(gaps)),
        "inter_glyph_spacing_sd_norm": float(np.std(gaps, ddof=0)) if len(gaps) > 1 else None,
        "rhythm_periodicity": periodicity,
        "unit_area_cv": _cv(areas), "unit_width_cv": _cv(widths), "unit_height_cv": _cv(heights),
    }


def _record(run_payload: dict[str, Any], row: dict[str, Any], representation: str, path: str, threshold: int) -> dict[str, Any] | None:
    stats = _stats(path, threshold)
    if stats is None:
        return None
    values = {key: stats.get(key) for key in FEATURES}
    image = np.asarray(Image.open(path).convert("L"), dtype=np.uint8)
    foreground = image < threshold
    values.update(_sequence_features(row, stats, foreground))
    unit_count = int(row["unit_count"])
    for key in MULTI_ONLY:
        if unit_count == 1:
            values[key] = None
    dimensions = sorted({dimension for key in FEATURES for dimension in DIMENSIONS[key]})
    applicability = "direct" if unit_count == 1 else "protocol_dependent"
    numerators = {
        "ink_coverage_ratio": stats["area"], "whitespace_ratio": stats["width"] * stats["height"] - stats["area"],
        "bbox_fill_ratio": stats["area"], "bbox_aspect_ratio": stats["bbox"][2] - stats["bbox"][0],
    }
    denominators = {
        "ink_coverage_ratio": stats["width"] * stats["height"], "whitespace_ratio": stats["width"] * stats["height"],
        "bbox_fill_ratio": (stats["bbox"][2] - stats["bbox"][0]) * (stats["bbox"][3] - stats["bbox"][1]),
        "bbox_aspect_ratio": stats["bbox"][3] - stats["bbox"][1],
    }
    missing = [key for key, value in values.items() if value is None]
    applicability_by_feature = {
        key: ("not_applicable" if key in MULTI_ONLY and unit_count == 1 else "protocol_dependent" if key in MULTI_ONLY or key == "straight_curve_ratio" else "direct")
        for key in FEATURES
    }
    missing_reasons = {
        key: ("MEASURE_NOT_APPLICABLE" if applicability_by_feature[key] == "not_applicable" else "MEASURE_SKELETON_UNSTABLE" if key == "straight_curve_ratio" else "MEASURE_SEQUENCE_TOO_SHORT" if key == "rhythm_periodicity" else "MEASURE_ZERO_DENOMINATOR")
        for key in missing if key in applicability_by_feature
    }
    feature_id = "feat_" + hashlib.sha256(f"{row['stimulus_id']}|{run_payload['run_id']}|{representation}".encode()).hexdigest()[:20]
    return {
        "feature_record_id": feature_id, "stimulus_id": row["stimulus_id"], "extraction_run_id": run_payload["run_id"],
        "feature_definition_version": "1.1.0", "representation": representation, "normalization_profile": row["render_profile"],
        "dimensions": dimensions, "applicability": applicability, "measurement_status": "valid",
        "missing_reason": None, "algorithm_config_sha256": run_payload.get("config_sha256"),
        "feature_numerators": numerators, "feature_denominators": denominators,
        "feature_units": {key: UNITS[key] for key in FEATURES}, "feature_applicability": applicability_by_feature,
        "missing_reasons": missing_reasons, "features": values, "missing_features": missing,
        "computed_at": run_payload.get("created_at"), "software": run_payload.get("software", {}).get("pillow"),
    }


def measure_run(run_dir: str | Path, output_path: str | Path | None = None) -> list[dict[str, Any]]:
    run = Path(run_dir)
    payload = json.loads((run / "render_results.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for row in payload["results"]:
        if row.get("status") != "passed":
            continue
        records.extend(filter(None, (
            _record(payload, row, "raster_binary", row["mask_path"], 128),
            _record(payload, row, "raster_grayscale", row["gray_path"], 254),
        )))
    records.sort(key=lambda item: (item["stimulus_id"], item["extraction_run_id"], item["normalization_profile"], item["representation"]))
    output = Path(output_path) if output_path else run / "visual_features.csv"
    fields = ["feature_record_id", "stimulus_id", "extraction_run_id", "feature_definition_version", "representation", "normalization_profile", "dimensions", "applicability", "measurement_status", "missing_reason", "algorithm_config_sha256", "feature_numerators_json", "feature_denominators_json", "feature_units_json", "feature_applicability_json", "missing_reasons_json"] + FEATURES
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                **{key: record[key] for key in fields[:11]}, "dimensions": "|".join(record["dimensions"]),
                "feature_numerators_json": json.dumps(record["feature_numerators"], sort_keys=True, ensure_ascii=False),
                "feature_denominators_json": json.dumps(record["feature_denominators"], sort_keys=True, ensure_ascii=False),
                "feature_units_json": json.dumps(record["feature_units"], sort_keys=True, ensure_ascii=False),
                "feature_applicability_json": json.dumps(record["feature_applicability"], sort_keys=True, ensure_ascii=False),
                "missing_reasons_json": json.dumps(record["missing_reasons"], sort_keys=True, ensure_ascii=False), **record["features"],
            })
    return records


measure_results = measure_run

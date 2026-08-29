"""Deterministic text shaping and raster rendering for GLYPH visual-features v1."""
from __future__ import annotations

import csv
import copy
import hashlib
import json
import os
import platform
import shutil
import unicodedata
from importlib.metadata import version
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import uharfbuzz as hb
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FAILURE_CODES = {
    "ASSET_LICENSE_UNKNOWN",
    "ASSET_MISSING_GLYPH",
    "RENDER_FALLBACK_DETECTED",
    "RENDER_CLUSTER_MISMATCH",
    "RENDER_OUT_OF_BOUNDS",
    "NORMALIZATION_FAILED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_config(path: str | Path) -> dict[str, Any]:
    """Read the JSON-compatible YAML config without hidden parser defaults."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("v1 config must be JSON-compatible YAML; install PyYAML only for a future protocol") from exc
    if not isinstance(value, dict):
        raise ValueError("config root must be an object")
    return value


def _resolve_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _ink_bbox(image: Image.Image, threshold: int = 128) -> tuple[int, int, int, int] | None:
    arr = np.asarray(image)
    ys, xs = np.where(arr < threshold)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if xs.size else None


def shape_text(font_path: str | Path, text: str, language: str, expected_units: int, features: Iterable[str]) -> dict[str, Any]:
    """Return HarfBuzz glyph and cluster information used by both QC and rendering."""
    face = hb.Face(Path(font_path).read_bytes())
    font = hb.Font(face)
    hb.ot_font_set_funcs(font)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    if language:
        buffer.language = language
    feature_map: dict[str, bool] = {}
    for item in features:
        item = str(item)
        if item.startswith("-"):
            feature_map[item[1:]] = False
        elif "=" in item:
            key, value = item.split("=", 1)
            feature_map[key] = value not in {"0", "false", "False"}
        else:
            feature_map[item] = True
    hb.shape(font, buffer, feature_map)
    infos = buffer.glyph_infos
    positions = buffer.glyph_positions
    clusters: list[int] = []
    for info in infos:
        if info.cluster not in clusters:
            clusters.append(info.cluster)
    missing = any(info.codepoint == 0 for info in infos)
    return {
        "glyph_count": len(infos),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "missing_glyph": missing,
        "advances": [position.x_advance for position in positions],
        "upem": face.upem,
    }


def _draw_units(font: ImageFont.FreeTypeFont, units: list[str], language: str, features: list[str]) -> tuple[Image.Image, list[tuple[int, int, int, int] | None], int]:
    """Draw units with Pillow's deterministic basic layout, preserving unit boxes.

    HarfBuzz performs the protocol-level shaping and cluster validation before
    this function. Pillow builds without libraqm cannot accept language/features
    arguments, so the raster path deliberately uses BASIC layout and draws each
    manifest unit separately; this also prevents implicit cross-unit kerning.
    """
    surface = Image.new("L", (4096, 2048), 255)
    draw = ImageDraw.Draw(surface)
    baseline = 1500
    x = 128
    boxes: list[tuple[int, int, int, int] | None] = []
    for unit in units:
        draw.text((x, baseline), unit, font=font, fill=0, anchor="ls")
        box = _ink_bbox(surface)
        # Difference from the previous global box gives the unit-local box.
        if box is None:
            boxes.append(None)
        else:
            unit_surface = Image.new("L", surface.size, 255)
            ImageDraw.Draw(unit_surface).text((x, baseline), unit, font=font, fill=0, anchor="ls")
            boxes.append(_ink_bbox(unit_surface))
        x += max(1, round(font.getlength(unit)))
    return surface, boxes, baseline


def _render_row(row: dict[str, str], cfg: dict[str, Any], root: Path, out_dir: Path, canvas_override: tuple[int, int] | None = None, threshold_override: int | None = None) -> dict[str, Any]:
    width = int(canvas_override[0] if canvas_override else cfg["canvas"]["width_px"])
    height = int(canvas_override[1] if canvas_override else cfg["canvas"]["height_px"])
    threshold = int(threshold_override if threshold_override is not None else cfg["thresholds"]["binary"])
    font_path = _resolve_path(row["font_path"], root)
    if not font_path.exists():
        return {"status": "missing", "failure_code": "ASSET_MISSING_GLYPH", "message": f"font file not found: {font_path}"}
    text = unicodedata.normalize("NFC", row["content"])
    units = list(text)
    expected_units = int(row["unit_count"])
    if len(units) != expected_units:
        return {"status": "missing", "failure_code": "RENDER_CLUSTER_MISMATCH", "message": "NFC unit count differs from manifest"}
    shaping = cfg["shaping"]
    shaped = shape_text(font_path, text, row.get("language_bcp47", ""), expected_units, shaping["features"])
    if shaped["missing_glyph"]:
        return {"status": "missing", "failure_code": "ASSET_MISSING_GLYPH", "message": "HarfBuzz returned a .notdef glyph"}
    if shaped["cluster_count"] != expected_units:
        return {"status": "missing", "failure_code": "RENDER_CLUSTER_MISMATCH", "message": f"expected {expected_units} clusters, got {shaped['cluster_count']}"}
    size = 900 if expected_units == 1 else 700
    try:
        font = ImageFont.truetype(str(font_path), size=size, layout_engine=ImageFont.Layout.BASIC)
    except Exception as exc:
        return {"status": "missing", "failure_code": "ASSET_MISSING_GLYPH", "message": str(exc)}
    surface, unit_boxes, baseline = _draw_units(font, units, row.get("language_bcp47", ""), list(shaping["features"]))
    original_bbox = _ink_bbox(surface, threshold)
    if original_bbox is None:
        return {"status": "missing", "failure_code": "ASSET_MISSING_GLYPH", "message": "empty ink"}
    crop = surface.crop(original_bbox)
    binary_area = sum(1 for value in crop.getdata() if value < threshold)
    if binary_area <= 0:
        return {"status": "missing", "failure_code": "ASSET_MISSING_GLYPH", "message": "empty binary ink"}
    profile = row["render_profile"]
    if profile == "bbox_height_matched":
        target_height = int(cfg["profiles"][profile]["target_height_px"])
        scale = target_height / max(1, original_bbox[3] - original_bbox[1])
    elif profile == "ink_area_matched":
        target_ratio = float(cfg["profiles"][profile]["target_ratio"])
        scale = (target_ratio * width * height / binary_area) ** 0.5
    else:
        return {"status": "missing", "failure_code": "NORMALIZATION_FAILED", "message": f"unknown profile {profile}"}
    new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    if new_size[0] > width or new_size[1] > height:
        return {"status": "missing", "failure_code": "NORMALIZATION_FAILED", "message": "normalized ink exceeds canvas"}

    # Integer raster dimensions can move the measured area by more than the
    # 0.001 acceptance tolerance.  Calibrate only the final integer size by a
    # small deterministic search around the protocol scale; this preserves
    # uniform scaling and never rescues an out-of-bounds condition.
    if profile == "ink_area_matched":
        target_ratio = float(cfg["profiles"][profile]["target_ratio"])
        candidates: list[tuple[float, float, tuple[int, int], Image.Image, float]] = []
        for step in range(-20, 21):
            candidate_scale = scale * (1.0 + step * 0.0005)
            candidate_size = (max(1, round(crop.width * candidate_scale)), max(1, round(crop.height * candidate_scale)))
            if candidate_size[0] > width or candidate_size[1] > height:
                continue
            candidate = crop.resize(candidate_size, Image.Resampling.LANCZOS)
            ratio = np.count_nonzero(np.asarray(candidate) < threshold) / (width * height)
            candidates.append((abs(ratio - target_ratio), candidate_scale, candidate_size, candidate, ratio))
        if candidates:
            _, scale, new_size, crop, _ = min(candidates, key=lambda item: (item[0], item[2][0], item[2][1]))
        else:
            crop = crop.resize(new_size, Image.Resampling.LANCZOS)
    else:
        crop = crop.resize(new_size, Image.Resampling.LANCZOS)
    normalized_bbox = _ink_bbox(crop, threshold)
    if normalized_bbox is None:
        return {"status": "missing", "failure_code": "NORMALIZATION_FAILED", "message": "normalization removed ink"}
    # Use the actual binary bbox after resampling for protocol tolerances.
    ink_w = normalized_bbox[2] - normalized_bbox[0]
    ink_h = normalized_bbox[3] - normalized_bbox[1]
    if profile == "bbox_height_matched" and abs(ink_h - int(cfg["profiles"][profile]["target_height_px"])) > 1:
        return {"status": "missing", "failure_code": "NORMALIZATION_FAILED", "message": f"height target error: {ink_h}"}
    if profile == "ink_area_matched":
        measured_ratio = np.count_nonzero(np.asarray(crop) < threshold) / (width * height)
        if abs(measured_ratio - float(cfg["profiles"][profile]["target_ratio"])) > 0.001:
            return {"status": "missing", "failure_code": "NORMALIZATION_FAILED", "message": f"ink ratio target error: {measured_ratio:.6f}"}
    # Reposition by the declared anchors; preserve a baseline anchor for sequences.
    if expected_units > 1:
        baseline_offset = baseline - original_bbox[1]
        paste_y = round(cfg["anchors"]["multi_baseline_y"] - baseline_offset * scale)
    else:
        paste_y = round(cfg["anchors"]["single_ink_bbox_center"][1] - normalized_bbox[1] - ink_h / 2)
    paste_x = round(cfg["anchors"].get("multi_text_center_x", cfg["anchors"]["single_ink_bbox_center"][0]) - normalized_bbox[0] - ink_w / 2)
    if paste_x < 0 or paste_y < 0 or paste_x + crop.width > width or paste_y + crop.height > height:
        return {"status": "missing", "failure_code": "RENDER_OUT_OF_BOUNDS", "message": "anchor placement exceeds canvas"}
    canvas = Image.new("L", (width, height), 255)
    canvas.paste(crop, (paste_x, paste_y))
    mask = canvas.point(lambda value: 0 if value < threshold else 255, mode="L")
    out_dir.mkdir(parents=True, exist_ok=True)
    gray_path = out_dir / f"{row['stimulus_id']}.gray.png"
    mask_path = out_dir / f"{row['stimulus_id']}.mask.png"
    if gray_path.exists() or mask_path.exists():
        raise FileExistsError(f"refusing to overwrite {row['stimulus_id']}")
    dpi = int(cfg["canvas"]["dpi"])
    canvas.save(gray_path, format="PNG", dpi=(dpi, dpi))
    mask.save(mask_path, format="PNG", dpi=(dpi, dpi))
    transformed_units: list[list[int] | None] = []
    for box in unit_boxes:
        if box is None:
            transformed_units.append(None)
            continue
        transformed_units.append([
            round(paste_x + (box[0] - original_bbox[0]) * scale),
            round(paste_y + (box[1] - original_bbox[1]) * scale),
            round(paste_x + (box[2] - original_bbox[0]) * scale),
            round(paste_y + (box[3] - original_bbox[1]) * scale),
        ])
    return {
        "status": "passed",
        "gray_path": str(gray_path),
        "mask_path": str(mask_path),
        "gray_sha256": sha256(gray_path),
        "mask_sha256": sha256(mask_path),
        "ink_bbox": [paste_x + normalized_bbox[0], paste_y + normalized_bbox[1], paste_x + normalized_bbox[2], paste_y + normalized_bbox[3]],
        "unit_bboxes": transformed_units,
        "cluster_count": shaped["cluster_count"],
        "clusters": shaped["clusters"],
        "width_px": width,
        "height_px": height,
        "binary_threshold": threshold,
        "baseline_y": cfg["anchors"]["multi_baseline_y"] if expected_units > 1 else None,
    }


def _asset_map(manifest_path: Path) -> dict[str, dict[str, str]]:
    inventory = manifest_path.parent / "asset_inventory.csv"
    if not inventory.exists():
        return {}
    with inventory.open(encoding="utf-8", newline="") as handle:
        return {row["font_id"]: row for row in csv.DictReader(handle)}


def render_manifest(config_path: str | Path, manifest_path: str | Path, output_dir: str | Path | None = None, *, canvas_override: tuple[int, int] | None = None, threshold_override: int | None = None) -> tuple[str, list[dict[str, Any]], Path]:
    config_path = Path(config_path)
    manifest_path = Path(manifest_path)
    cfg = load_config(config_path)
    if canvas_override:
        # Resolution sensitivity preserves relative display size: the pixel
        # height target scales with the smaller canvas ratio, while the area
        # proportion remains dimensionless and unchanged.
        base_w = int(cfg["canvas"]["width_px"])
        base_h = int(cfg["canvas"]["height_px"])
        cfg = copy.deepcopy(cfg)
        resolution_scale = min(canvas_override[0] / base_w, canvas_override[1] / base_h)
        cfg["profiles"]["bbox_height_matched"]["target_height_px"] = max(1, round(int(cfg["profiles"]["bbox_height_matched"]["target_height_px"]) * resolution_scale))
        x_scale = canvas_override[0] / base_w
        y_scale = canvas_override[1] / base_h
        cfg["anchors"]["single_ink_bbox_center"] = [round(cfg["anchors"]["single_ink_bbox_center"][0] * x_scale), round(cfg["anchors"]["single_ink_bbox_center"][1] * y_scale)]
        cfg["anchors"]["multi_text_center_x"] = round(cfg["anchors"]["multi_text_center_x"] * x_scale)
        cfg["anchors"]["multi_baseline_y"] = round(cfg["anchors"]["multi_baseline_y"] * y_scale)
    raw_manifest = manifest_path.read_bytes()
    config_hash = sha256(config_path)
    manifest_hash = sha256_bytes(raw_manifest)
    implementation_hash = sha256(Path(__file__))
    inventory_path = manifest_path.parent / "asset_inventory.csv"
    inventory_hash = sha256(inventory_path) if inventory_path.exists() else None
    run_descriptor = {"manifest_sha256": manifest_hash, "config_sha256": config_hash, "implementation_sha256": implementation_hash, "asset_inventory_sha256": inventory_hash, "canvas": canvas_override, "threshold": threshold_override}
    run_id = "render_" + sha256_bytes(canonical_json(run_descriptor))[:16]
    root = Path.cwd()
    if output_dir is None:
        output = manifest_path.parent / "runs" / run_id
    else:
        output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"run directory already exists and is non-empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8", newline="")))
    assets = _asset_map(manifest_path)
    results: list[dict[str, Any]] = []
    for row in rows:
        asset = assets.get(row.get("font_id", ""))
        if asset and asset.get("license_id", "UNKNOWN") in {"", "UNKNOWN"}:
            result = {"status": "missing", "failure_code": "ASSET_LICENSE_UNKNOWN", "message": "font license is unknown"}
        elif asset and asset.get("sha256") and Path(_resolve_path(row["font_path"], root)).exists() and sha256(_resolve_path(row["font_path"], root)) != asset["sha256"]:
            result = {"status": "missing", "failure_code": "ASSET_LICENSE_UNKNOWN", "message": "font hash does not match inventory"}
        else:
            result = _render_row(row, cfg, root, output / "rendered", canvas_override, threshold_override)
        results.append({**row, **result})
    payload = {
        "run_id": run_id,
        "protocol_version": cfg["protocol_version"],
        "schema_versions": cfg.get("schema_versions", {}),
        "config_path": str(config_path),
        "config_sha256": config_hash,
        "implementation_sha256": implementation_hash,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "asset_inventory_sha256": inventory_hash,
        "canvas": {"width_px": canvas_override[0], "height_px": canvas_override[1]} if canvas_override else cfg["canvas"],
        "threshold": threshold_override if threshold_override is not None else cfg["thresholds"]["binary"],
        "profiles": cfg["profiles"],
        "software": {
            "python": platform.python_version(), "pillow": Image.__version__,
            "numpy": np.__version__, "uharfbuzz": version("uharfbuzz"),
            "fonttools": version("fonttools"), "platform": platform.platform(),
        },
        "created_at": utc_now(),
        "results": results,
    }
    (output / "render_results.json").write_bytes(canonical_json(payload) + b"\n")
    (output / "run_manifest.json").write_bytes(canonical_json(payload) + b"\n")
    shutil.copy2(manifest_path, output / "manifest.csv")
    log_lines = [f"run_id={run_id}", f"manifest_sha256={manifest_hash}", f"config_sha256={config_hash}", f"implementation_sha256={implementation_hash}", f"output_dir={output}", f"exit_code=0"]
    (output / "run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return run_id, results, output

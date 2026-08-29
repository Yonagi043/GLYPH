"""Audit whether frozen normalization targets fit the declared canvas.

This is a diagnostic only: it never changes a stimulus, font, or protocol
parameter.  It makes geometric impossibility explicit before a batch run.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from glyph_features.render import _draw_units, _ink_bbox, _resolve_path, load_config  # noqa: E402


FIELDS = [
    "stimulus_id", "script_code_iso15924", "content_set_id", "content",
    "font_id", "render_profile", "canvas_width_px", "canvas_height_px",
    "original_ink_width_px", "original_ink_height_px", "binary_area_px",
    "target_scale", "target_width_px", "target_height_px", "fits_canvas",
    "limiting_axis", "max_fit_scale", "max_fit_area_ratio", "target_area_ratio",
    "diagnosis",
]


def audit(config_path: Path, manifest_path: Path, output_path: Path) -> int:
    cfg = load_config(config_path)
    width = int(cfg["canvas"]["width_px"])
    height = int(cfg["canvas"]["height_px"])
    rows = list(csv.DictReader(manifest_path.open(encoding="utf-8", newline="")))
    out = []
    for row in rows:
        font_path = _resolve_path(row["font_path"], ROOT)
        units = list(row["content"])
        size = 900 if int(row["unit_count"]) == 1 else 700
        font = ImageFont.truetype(str(font_path), size=size, layout_engine=ImageFont.Layout.BASIC)
        surface, _, _ = _draw_units(font, units, row.get("language_bcp47", ""), cfg["shaping"]["features"])
        bbox = _ink_bbox(surface, int(cfg["thresholds"]["binary"]))
        if bbox is None:
            continue
        crop_w, crop_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        area = sum(1 for value in surface.crop(bbox).getdata() if value < int(cfg["thresholds"]["binary"]))
        if row["render_profile"] == "bbox_height_matched":
            target_h = float(cfg["profiles"][row["render_profile"]]["target_height_px"])
            scale = target_h / crop_h
            target_area_ratio = ""
        else:
            target_area_ratio = float(cfg["profiles"][row["render_profile"]]["target_ratio"])
            scale = (target_area_ratio * width * height / area) ** 0.5
        target_w, target_h = crop_w * scale, crop_h * scale
        fits = target_w <= width and target_h <= height
        fit_scale = min(width / crop_w, height / crop_h)
        limiting = "none" if fits else ("width" if width / crop_w < height / crop_h else "height")
        max_ratio = area * fit_scale * fit_scale / (width * height)
        if fits:
            diagnosis = "geometrically_feasible"
        elif row["render_profile"] == "bbox_height_matched":
            diagnosis = "bbox_height_target_and_canvas_aspect_ratio_conflict"
        else:
            diagnosis = "ink_area_target_and_canvas_bounds_conflict"
        out.append({
            "stimulus_id": row["stimulus_id"], "script_code_iso15924": row["script_code_iso15924"],
            "content_set_id": row["content_set_id"], "content": row["content"], "font_id": row["font_id"],
            "render_profile": row["render_profile"], "canvas_width_px": width, "canvas_height_px": height,
            "original_ink_width_px": crop_w, "original_ink_height_px": crop_h, "binary_area_px": area,
            "target_scale": f"{scale:.9f}", "target_width_px": f"{target_w:.3f}", "target_height_px": f"{target_h:.3f}",
            "fits_canvas": str(fits).lower(), "limiting_axis": limiting, "max_fit_scale": f"{fit_scale:.9f}",
            "max_fit_area_ratio": f"{max_ratio:.9f}", "target_area_ratio": target_area_ratio,
            "diagnosis": diagnosis,
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(out)
    summary = {"rows": len(out), "infeasible": sum(r["fits_canvas"] == "false" for r in out)}
    output_path.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    failed = [r for r in out if r["fits_canvas"] == "false"]
    by_profile = {}
    for profile in ("bbox_height_matched", "ink_area_matched"):
        subset = [r for r in failed if r["render_profile"] == profile]
        by_profile[profile] = {"count": len(subset), "width": sum(r["limiting_axis"] == "width" for r in subset), "height": sum(r["limiting_axis"] == "height" for r in subset)}
    conclusion = (
        "All audited conditions fit the canvas under the active protocol targets."
        if not failed else
        "The failures cannot be repaired by rerunning the same implementation. Resolving them requires an explicit protocol revision (for example, changing a target, content/tracking, or profile scope), followed by a version bump and a complete rerun."
    )
    report = [
        "# Normalization Feasibility Audit",
        "",
        "This diagnostic evaluates the frozen protocol without changing any stimulus or target.",
        "",
        f"- Conditions audited: **{len(out)}**",
        f"- Geometrically infeasible: **{len(failed)}**",
        f"- bbox-height failures: **{by_profile['bbox_height_matched']['count']}** ({by_profile['bbox_height_matched']['width']} width-bound)",
        f"- ink-area failures: **{by_profile['ink_area_matched']['count']}** ({by_profile['ink_area_matched']['width']} width-bound, {by_profile['ink_area_matched']['height']} height-bound)",
        "",
        "For a single uniformly scaled raster, a target can fit only when both target width and target height are within the canvas. The CSV records the exact dimensions and limiting axis for every condition; no crop, non-uniform stretch, fallback font, or target adjustment is applied.",
        "",
        conclusion,
    ]
    output_path.with_suffix(".md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/visual_features_v1.yaml")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/processed/visual_features_v1/manifest.csv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return audit(args.config, args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())

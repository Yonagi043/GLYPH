"""Project the frozen CSV manifest into stimulus.schema 1.1.0 records.

The CSV remains the deterministic input matrix; this command materializes the
complete shared-schema record only after a render run supplies asset hashes.
"""
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, RefResolver

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_NAMES = {"Latn": "Latin", "Hani": "Han", "Kana": "Kana", "Hang": "Hangul"}


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _record(row: dict[str, str], result: dict, run: dict, assets: dict[str, dict[str, str]], cfg: dict) -> dict:
    inventory = assets.get(row["font_id"], {})
    rendered = Path(result.get("gray_path", ""))
    if not rendered.is_absolute():
        rendered = ROOT / rendered
    profile = row["render_profile"]
    target_ratio = float(cfg["profiles"]["ink_area_matched"]["target_ratio"])
    return {
        "schema_version": "1.1.0",
        "stimulus_id": row["stimulus_id"],
        "research_lines": row["research_lines"].split("|"),
        "writing_system": row["writing_system"],
        "script_code_iso15924": row["script_code_iso15924"],
        "script_name": SCRIPT_NAMES[row["script_code_iso15924"]],
        "style_family": row["style_family"],
        "content_set": {"content_set_id": row["content_set_id"], "unit_count": int(row["unit_count"]), "semantic_status": row["semantic_status"]},
        "render_profile": profile,
        "text": {
            "content": row["content"],
            "unicode_codepoints": [f"U+{ord(ch):04X}" for ch in row["content"]],
            "language_bcp47": row["language_bcp47"] or None,
            "semantic_status": row["semantic_status"],
            "meaning_gloss": None,
            "character_count": len(row["content"]),
        },
        "font": {
            "font_id": row["font_id"],
            "family_name": inventory.get("family_name", row["font_id"]),
            "postscript_name": None,
            "version": inventory.get("font_version") or None,
            "role": "source_font",
            "file": {"path": row["font_path"], "sha256": inventory.get("sha256", "")},
        },
        "canvas": {"width_px": int(run["canvas"]["width_px"]), "height_px": int(run["canvas"]["height_px"]), "background_rgba": [255, 255, 255, 255], "color_space": "grayscale", "dpi": int(run["canvas"].get("dpi", cfg["canvas"]["dpi"]))},
        "foreground_rgba": [0, 0, 0, 255],
        "ink_area_target_ratio": target_ratio,
        "layout": {"line_count": 1, "alignment": "center", "orientation": "horizontal", "tracking_px": 0, "leading_px": 0, "rotation_deg": 0, "positioning": "text_layout"},
        "shaping": {"engine": cfg["shaping"]["engine"], "language": row["language_bcp47"] or "", "features": cfg["shaping"]["features"], "unicode_normalization": cfg["shaping"]["unicode_normalization"], "hinting": cfg["shaping"]["hinting"]},
        "anchors": cfg["anchors"],
        "readability": {"readability_condition": "not_applicable", "familiarity_condition": "controlled_unfamiliar", "pretest_readability_mean": None, "pretest_familiarity_mean": None, "pretest_sample_size": None},
        "semantic_control": "unrelated_content",
        "provenance": {"source_id": row["font_id"], "source_uri": inventory.get("source_uri"), "acquisition_method": "rendered_from_font", "license_status": "open", "license_id": inventory.get("license_id"), "accessed_at": inventory.get("accessed_at") or datetime.now(timezone.utc).date().isoformat()},
        "assets": {"rendered": {"path": str(rendered.relative_to(ROOT)) if rendered.exists() else str(rendered), "sha256": result.get("gray_sha256", ""), "mime_type": "image/png", "byte_size": rendered.stat().st_size if rendered.exists() else 0}, "source": None},
        "qc": {"status": "passed" if result.get("status") == "passed" else "failed", "checked_at": run.get("created_at"), "reviewer": None, "notes": result.get("message")},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/visual_features_v1.yaml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads((args.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    with (args.manifest).open(encoding="utf-8", newline="") as h: rows = list(csv.DictReader(h))
    inventory_path = args.manifest.parent / "asset_inventory.csv"
    with inventory_path.open(encoding="utf-8", newline="") as h: assets = {r["font_id"]: r for r in csv.DictReader(h)}
    results = {r["stimulus_id"]: r for r in run["results"]}
    schema_path = ROOT / "schema/stimulus.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, resolver=RefResolver(schema_path.parent.as_uri() + "/", schema), format_checker=FormatChecker())
    records = [_record(row, results[row["stimulus_id"]], run, assets, cfg) for row in rows]
    errors = []
    for index, record in enumerate(records, start=1):
        errors.extend(f"record {index}: {error.message}" for error in validator.iter_errors(record))
    if errors:
        print("invalid stimulus records:", *errors[:20], sep="\n")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for record in records) + "\n", encoding="utf-8")
    print(f"valid stimulus records {len(records)} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

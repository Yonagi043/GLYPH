"""Materialize the deterministic fixture subset used for human review."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(manifest: Path, output: Path) -> int:
    with manifest.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = []
    for row in rows:
        is_unit = row["content_set_id"].endswith("_u01") or row["content_set_id"].endswith("_u02")
        is_baseline = row["style_family"] == "sans"
        is_han_example = row["script_code_iso15924"] == "Hani" and row["unit_count"] == "1"
        if is_unit and (is_baseline or is_han_example):
            selected.append({k: row[k] for k in ("stimulus_id", "script_code_iso15924", "content_set_id", "content", "font_id", "style_family", "render_profile")})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selected[0]))
        writer.writeheader(); writer.writerows(selected)
    print(f"wrote {len(selected)} fixture stimuli -> {output}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/processed/visual_features_v1/manifest.csv")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(build(args.manifest, args.output))

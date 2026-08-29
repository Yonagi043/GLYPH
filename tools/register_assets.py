"""Register the exact font files used by the public v1 fixture."""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from fontTools.ttLib import TTFont

ASSETS = [
    ("font_noto_sans_latn", "WP3_baseline", "Noto Sans", "data/assets/fonts/NotoSans-Regular.ttf", "Noto Sans Regular"),
    ("font_noto_sans_sc", "WP3_baseline", "Noto Sans CJK SC", "data/assets/fonts/NotoSansCJKsc-Regular.otf", "Noto Sans CJK SC Regular"),
    ("font_noto_sans_jp", "WP3_baseline", "Noto Sans CJK JP", "data/assets/fonts/NotoSansCJKjp-Regular.otf", "Noto Sans CJK JP Regular"),
    ("font_noto_sans_kr", "WP3_baseline", "Noto Sans KR", "data/assets/fonts/NotoSansKR-static.ttf", "Noto Sans KR Regular (wght=400 instance)"),
    ("font_noto_serif_sc", "WP4_serif_example", "Noto Serif SC", "data/assets/fonts/NotoSerifSC-Regular.ttf", "Noto Serif SC Regular (wght=400 instance)"),
    ("font_bpmf_iansui", "WP4_regular_hand_example", "Bpmf Iansui", "data/assets/fonts/BpmfIansui-Regular.ttf", "Bpmf Iansui Regular"),
    ("font_lxgw_marker_gothic", "WP4_decorative_example", "LXGW Marker Gothic", "data/assets/fonts/LXGWMarkerGothic-Regular.ttf", "LXGW Marker Gothic Regular"),
]

SOURCE_URIS = {
    "font_noto_sans_latn": "https://github.com/notofonts/latin-greek-cyrillic/tree/main/fonts/NotoSans/full/ttf",
    "font_noto_sans_sc": "https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese",
    "font_noto_sans_jp": "https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/Japanese",
    "font_noto_sans_kr": "https://github.com/notofonts/noto-cjk/tree/main/Sans/Variable/OTF",
    "font_noto_serif_sc": "https://github.com/notofonts/noto-cjk/tree/main/Serif/Variable/OTF/SimplifiedChinese",
    "font_bpmf_iansui": "https://github.com/google/fonts/tree/main/ofl/bpmfiansui",
    "font_lxgw_marker_gothic": "https://github.com/google/fonts/tree/main/ofl/lxgwmarkergothic",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/processed/visual_features_v1/asset_inventory.csv")
    args = parser.parse_args()
    root = Path.cwd()
    fields = ["font_id", "role", "family_name", "file_path", "font_version", "variable_axes", "unicode_coverage_status", "source_uri", "accessed_at", "license_id", "license_uri", "license_text_path", "license_text_sha256", "redistributable", "distribution_tier", "sha256", "reviewer", "reviewed_at"]
    rows = []
    fixture_rows = list(csv.DictReader((root / "data/fixtures/content_sets.csv").open(encoding="utf-8", newline="")))
    required_by_font = {
        "font_noto_sans_latn": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Latn" for ch in row["content"]},
        "font_noto_sans_sc": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Hani" for ch in row["content"]},
        "font_noto_sans_jp": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Kana" for ch in row["content"]},
        "font_noto_sans_kr": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Hang" for ch in row["content"]},
        "font_noto_serif_sc": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Hani" for ch in row["content"]},
        "font_bpmf_iansui": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Hani" for ch in row["content"]},
        "font_lxgw_marker_gothic": {ord(ch) for row in fixture_rows if row["script_code_iso15924"] == "Hani" for ch in row["content"]},
    }
    for font_id, role, family, relative, version in ASSETS:
        path = root / relative
        if not path.exists():
            raise FileNotFoundError(path)
        font = TTFont(path, fontNumber=0)
        cmap = {codepoint for table in font["cmap"].tables for codepoint in table.cmap}
        missing = required_by_font[font_id] - cmap
        if missing:
            raise ValueError(f"{font_id} missing fixture codepoints: " + ",".join(f"U+{c:04X}" for c in sorted(missing)))
        if any(tag in font for tag in ("COLR", "SVG ", "CBDT", "sbix")):
            raise ValueError(f"{font_id} is a color/bitmap font")
        rows.append({
            "font_id": font_id, "role": role, "family_name": family, "file_path": relative,
            "font_version": version, "variable_axes": "", "unicode_coverage_status": "complete",
            "source_uri": SOURCE_URIS[font_id], "accessed_at": "2026-08-29",
            "license_id": "OFL-1.1", "license_uri": "https://openfontlicense.org/", "license_text_path": "data/assets/fonts/OFL.txt", "license_text_sha256": digest(root / "data/assets/fonts/OFL.txt"), "redistributable": "true",
            "distribution_tier": "public", "sha256": digest(path), "reviewer": "GLYPH", "reviewed_at": "2026-08-29",
        })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} asset records to {output}")


if __name__ == "__main__":
    main()

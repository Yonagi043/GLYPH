"""Build the exploratory, open-font R1 visual questionnaire materials."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
from importlib.metadata import version
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
from fontTools.ttLib import TTFont

from glyph_features.render import sha256, shape_text
from glyph_features.vision_system.definitions import load_registry
from glyph_features.vision_system.extract import measure_array


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/processed/autoresearch/2026-09-07-b01"
FONT_ROOT = ROOT / "data/assets/fonts"
SOURCES = [
    ("zh", "Han", "tea", "\u6625\u8336", "NotoSansCJKsc-Regular.otf"),
    ("zh", "Han", "tea", "\u6625\u8336", "NotoSerifSC-Regular.ttf"),
    ("zh", "Han", "tea", "\u6625\u8336", "LXGWWenKai-Regular.ttf"),
    ("zh", "Han", "moon", "\u5c71\u6708", "NotoSansCJKsc-Regular.otf"),
    ("zh", "Han", "moon", "\u5c71\u6708", "NotoSerifSC-Regular.ttf"),
    ("zh", "Han", "moon", "\u5c71\u6708", "LXGWWenKai-Regular.ttf"),
    ("en", "Latin", "tea", "Spring Tea", "NotoSans-Regular.ttf"),
    ("en", "Latin", "moon", "Mountain Moon", "NotoSans-Regular.ttf"),
    ("ja", "Han+Hiragana", "tea", "\u6625\u306e\u304a\u8336", "NotoSansCJKjp-Regular.otf"),
    ("ja", "Han+Hiragana", "moon", "\u5c71\u3068\u6708", "NotoSansCJKjp-Regular.otf"),
    ("ko", "Hangul", "tea", "\ubd04\ucc28", "NotoSansKR-static.ttf"),
    ("ko", "Hangul", "moon", "\uc0b0\uacfc \ub2ec", "NotoSansKR-static.ttf"),
]
ORDER = [8, 1, 10, 4, 7, 3, 11, 2, 9, 6, 12, 5]


def write_json(destination: Path, payload: object) -> None:
    destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def renderer():
    source = ROOT / "\u56fe\u5305\u4e0e\u5b57\u4f53\u5305/\u6807\u51c6\u5316\u6d41\u7a0b/render_font_samples.py"
    spec = importlib.util.spec_from_file_location("existing_font_renderer", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, source


def normalize(image: Image.Image) -> Image.Image:
    array = np.asarray(image.convert("L"))
    vertical, horizontal = np.nonzero(array < 128)
    assert horizontal.size, "empty rendering"
    crop = image.crop((int(horizontal.min()), int(vertical.min()), int(horizontal.max()) + 1, int(vertical.max()) + 1))
    scale = min(80 / crop.height, 560 / crop.width)
    size = (round(crop.width * scale), round(crop.height * scale))
    resized = crop.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("L", (600, 160), 255)
    canvas.paste(resized, ((600 - size[0]) // 2, (160 - size[1]) // 2))
    return canvas


def build(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "images").mkdir()
    (output / "raw_renders").mkdir()
    module, render_source = renderer()
    registry_file = ROOT / "configs/visual_measurements_v2.yaml"
    registry = load_registry(registry_file, ROOT / "schema")
    records = []
    measurements = []
    for index, (language, script, content_group, text, filename) in enumerate(SOURCES, 1):
        stimulus_id = f"M{index:02d}"
        font_file = FONT_ROOT / filename
        with TTFont(font_file) as font:
            names = {str(name_id): sorted({record.toUnicode() for record in font["name"].names if record.nameID == name_id}) for name_id in (1, 2, 13, 14)}
            assert any("Open Font License" in value for value in names["13"]), filename
            assert all(ord(character) in font.getBestCmap() for character in text), (filename, text)
            weight = font["OS/2"].usWeightClass
        shaped = shape_text(font_file, text, language, len(text), [])
        assert not shaped["missing_glyph"], stimulus_id
        raw_file = output / "raw_renders" / f"{stimulus_id}.png"
        module.render_one(str(font_file), text, str(raw_file))
        with Image.open(raw_file) as raw_image:
            image = normalize(raw_image)
        image_file = output / "images" / f"{stimulus_id}.png"
        image.save(image_file)
        array = np.asarray(image)
        foreground = array < 128
        vertical, horizontal = np.nonzero(foreground)
        assert 0 < horizontal.min() < horizontal.max() < 599
        assert 0 < vertical.min() < vertical.max() < 159
        records.append({
            "stimulus_id": stimulus_id, "material_type": "controlled_generated",
            "language": language, "script": script, "content_group": content_group,
            "text": text, "font_path": font_file.relative_to(ROOT).as_posix(),
            "font_sha256": sha256(font_file), "font_metadata": names, "weight_class": weight,
            "license": "SIL-OFL-1.1", "image": image_file.relative_to(output).as_posix(),
            "sha256": sha256(image_file), "raw_sha256": sha256(raw_file),
            "ink_height": int(vertical.max() - vertical.min() + 1),
            "ink_width": int(horizontal.max() - horizontal.min() + 1),
            "ink_pixels": int(foreground.sum()),
        })
        for threshold in (96, 128, 160):
            metrics = measure_array(array, "B_shape", registry, binary_threshold=threshold)
            assert metrics == measure_array(array, "B_shape", registry, binary_threshold=threshold)
            measurements.append({"stimulus_id": stimulus_id, "threshold": threshold, "metrics": {code: asdict(metric) for code, metric in metrics.items()}})
    boards = {}
    for order_id, order in (("forward", ORDER), ("reverse", list(reversed(ORDER)))):
        board = Image.new("RGB", (1200, 1200), "white")
        draw = ImageDraw.Draw(board)
        for position, index in enumerate(order):
            left, top = (position % 2) * 600, (position // 2) * 200
            stimulus_id = f"M{index:02d}"
            draw.text((left + 18, top + 12), stimulus_id, fill="black", font_size=20)
            with Image.open(output / "images" / f"{stimulus_id}.png") as image:
                board.paste(image, (left, top + 36))
        board_file = output / f"board_{order_id}.png"
        board.save(board_file)
        boards[order_id] = {"path": board_file.name, "sha256": sha256(board_file), "row_major_ids": [f"M{index:02d}" for index in order]}
    import glyph_features.vision_system.extract as extractor
    manifest = {
        "run_id": "ar-b01-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "data_type": "controlled_generated", "formal_stimulus_release": False,
        "software": {name: version(name) for name in ("Pillow", "numpy", "scipy", "scikit-image", "fonttools", "uharfbuzz")},
        "python": sys.version, "interpreter": sys.executable,
        "build_script_sha256": sha256(__file__), "render_source_sha256": sha256(render_source),
        "measurement_source_sha256": sha256(extractor.__file__), "registry_sha256": sha256(registry_file),
        "normalization": "black on white; bbox height target 80px, width cap 560px; isotropic resize; 600x160 canvas",
        "layout": "existing Pillow BASIC renderer, no RAQM; no implicit font fallback; shaping checked separately with HarfBuzz",
        "limits": ["Not actual commercial artwork", "Generic candidate wordmarks, not verified novel brand names", "Translations/content lengths and font coverage unbalanced", "Japanese includes shared Han plus Hiragana", "Nominal weight 400 is not matched perceived stroke weight", "Contact-sheet spatial order is not sequential exposure"],
        "stimuli": records, "boards": boards,
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "measurements.json", measurements)
    print(json.dumps({"output": str(output), "stimuli": len(records), "threshold_measurements": len(measurements), "ink_heights": [record["ink_height"] for record in records]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    build(arguments.output)

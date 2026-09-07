"""Measure two permitted commercial-logo renditions with explicit polarity."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
from PIL import Image

from glyph_features.render import sha256
from glyph_features.vision_system.definitions import load_registry
from glyph_features.vision_system.extract import measure_array


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/processed/autoresearch/2026-09-07-commercial"


def measure() -> None:
    sources = json.loads((RUN / "sources.json").read_text())
    registry_file = ROOT / "configs/visual_measurements_v2.yaml"
    registry = load_registry(registry_file, ROOT / "schema")
    records = []
    for asset in sources["assets"]:
        image_file = RUN / asset["local_file"]
        rgba = Image.open(image_file).convert("RGBA")
        pixels = np.asarray(rgba)
        composite = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("RGB")
        composite.save(RUN / f"{asset['asset_id']}_white_composite.png")
        gray = np.asarray(composite.convert("L"))
        opaque = pixels[:, :, 3] > 127
        if asset["asset_id"] == "C01":
            letters = opaque
            rule = "Alpha > 127; this inspected file contains dark lettering on transparency, no panel."
            scripts = "Latin + Han (Japanese brand spelling; Han is not assigned a unique language)"
        else:
            letters = opaque & (pixels[:, :, :3].min(axis=2) > 240)
            rule = "Alpha > 127 and min(R,G,B) > 240; white lettering on opaque red panels. No general segmentation claim."
            scripts = "Katakana + Latin; two side-by-side panels"
        letter_image = np.where(letters, 0, 255).astype(np.uint8)
        Image.fromarray(letter_image).save(RUN / f"{asset['asset_id']}_letters.png")
        variants = {
            "layout_dark_pixels": (gray, "A_layout"),
            "diagnostic_dark_pixels_misused_as_shape": (gray, "B_shape"),
            "explicit_letters": (letter_image, "B_shape"),
        }
        measurements = {}
        for variant, (array, representation) in variants.items():
            measured = measure_array(array, representation, registry)
            assert measured == measure_array(array, representation, registry)
            assert measured["ink_coverage_ratio"].value == int((array < 128).sum()) / array.size
            measurements[variant] = {code: asdict(metric) for code, metric in measured.items()}
        dark = gray < 128
        intersection = int((dark & letters).sum())
        union = int((dark | letters).sum())
        assert union > 0
        if asset["asset_id"] == "C02":
            assert intersection == 0, "Expected disjoint letter and panel masks"
            assert measurements["diagnostic_dark_pixels_misused_as_shape"]["connected_component_count"]["value"] != measurements["explicit_letters"]["connected_component_count"]["value"]
        records.append({
            "asset_id": asset["asset_id"], "material_type": sources["material_type"],
            "source_file_sha256": sha256(image_file), "file_size_bytes": image_file.stat().st_size,
            "observed_dimensions": list(rgba.size), "observed_scripts": scripts,
            "letter_selection_rule": rule, "dark_letter_intersection_pixels": intersection,
            "dark_letter_union_pixels": union, "dark_letter_iou": intersection / union,
            "measurements": measurements,
        })
    import glyph_features.vision_system.extract as extractor
    output = {
        "run_id": sources["run_id"], "computed_at": datetime.now(timezone.utc).isoformat(),
        "sources_sha256": sha256(RUN / "sources.json"), "script_sha256": sha256(__file__),
        "measurement_source_sha256": sha256(extractor.__file__), "registry_sha256": sha256(registry_file),
        "records": records,
        "interpretation": "Dark-foreground layout descriptors are valid descriptions of that declared mask, not automatically letter morphology. Use explicit polarity/region selection for glyph comparisons; retain layout separately.",
        "limits": ["Two brands are not representative", "Both marks mix scripts", "No aesthetic ratings or brand-effect estimates from this probe", "Server-rasterized Commons renditions, not official-master authentication", "Hand-declared masks are local to these two inspected images, not a new validated general extractor", "No formal asset handoff release or rights approval claimed"],
    }
    (RUN / "measurements.json").write_text(json.dumps(output, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    for record in records:
        print(record["asset_id"], "IoU", record["dark_letter_iou"], {variant: {code: metrics[code]["value"] for code in ("ink_coverage_ratio", "connected_component_count", "closure_count")} for variant, metrics in record["measurements"].items()})


if __name__ == "__main__":
    measure()

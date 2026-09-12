from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from glyph_features.workbench.materials import MaterialCatalog


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed/autoresearch/2026-09-11-synthesis"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_json(name: str, value: object) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def acquire(name: str, url: str) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / name
    if Path(name).name != name:
        raise ValueError("Source name must be a filename")
    if destination.exists():
        raise ValueError("Preserve existing source bytes; choose a new version")
    content = subprocess.check_output([
        "curl", "--proxy", "http://127.0.0.1:7897", "--fail", "--location",
        "--silent", "--show-error", "--max-time", "60", url,
    ])
    destination.write_bytes(content)
    save_json(name + ".source.json", {
        "url": url, "accessed": "2026-09-11", "sha256": digest(content),
        "bytes": len(content), "reading_status": "downloaded_not_automatically_verified",
    })
    print(json.dumps({"file": str(destination), "bytes": len(content), "sha256": digest(content)}))
    if name.endswith(".xml"):
        root = ET.fromstring(content)
        sections = []
        for element in root.findall(".//body//sec"):
            title = element.find("title")
            if title is not None:
                sections.append("## " + "".join(title.itertext()))
            for paragraph in element.findall("p"):
                sections.append("".join(paragraph.itertext()))
        (OUTPUT / (name + ".txt")).write_text("\n\n".join(sections) + "\n", encoding="utf-8")


def inventory() -> None:
    materials = MaterialCatalog(ROOT)
    rows = []
    for item in materials.items.values():
        if item["kind"] != "ecological_award_image":
            continue
        candidate, source = item["candidate"], item["source"]
        rows.append({
            "material_id": item["material_id"], "work_id": item["work_id"],
            "title": source["title"], "creator": source.get("publisher_or_creator"),
            "award": candidate["award_context"]["award"], "year": candidate["award_context"]["year"],
            "path": item["representations"]["original"]["path"],
            "sha256": item["representations"]["original"]["sha256"],
            "source_url": source["url"], "scene": "not_visually_coded",
            "script": "not_visually_coded", "font_or_style": "unknown",
        })
    save_json("commercial_inventory.json", rows)
    with (OUTPUT / "commercial_inventory.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"images": len(rows), "works": len({row["work_id"] for row in rows}),
               "unique_images": len({row["sha256"] for row in rows}),
               "awards": dict(Counter(row["award"] for row in rows)),
               "classification": "No scene or script inferred from award or filename"}
    save_json("inventory_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


def analyze_characters() -> None:
    source = OUTPUT / "character_exp2.csv"
    with source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    fonts = ["kai", "gyo", "sou", "rei", "ten"]
    grouped = {}
    seen = set()
    for row in rows:
        identity = (row["randomID"], row["stimulus"])
        assert identity not in seen
        seen.add(identity)
        assert row["font"] in fonts
        value = int(row["beauty"])
        assert 1 <= value <= 4
        grouped.setdefault(row["randomID"], {}).setdefault(row["font"], []).append(value)
    assert len(rows) == 7200 and len(grouped) == 80
    assert all(set(values) == set(fonts) for values in grouped.values())
    assert all(len(scores) == 18 for values in grouped.values() for scores in values.values())
    participant_means = [
        {font: statistics.mean(grouped[identity][font]) for font in fonts}
        for identity in sorted(grouped)
    ]
    generator = random.Random(20260911)
    resamples = [generator.choices(range(80), k=80) for _ in range(5000)]
    comparisons = []
    for font in fonts:
        if font == "gyo":
            continue
        differences = [entry[font] - entry["gyo"] for entry in participant_means]
        sampled = sorted(statistics.mean(differences[index] for index in sample) for sample in resamples)
        interval = statistics.quantiles(sampled, n=40, method="inclusive")
        comparisons.append({
            "font": font, "reference": "gyo",
            "mean_difference": statistics.mean(differences),
            "bootstrap_95_percentile": [interval[0], interval[-1]],
            "participant_positive": sum(value > 1e-12 for value in differences),
            "participant_tied": sum(abs(value) <= 1e-12 for value in differences),
            "participant_negative": sum(value < -1e-12 for value in differences),
        })
    result = {
        "source_sha256": digest(source.read_bytes()), "source_doi": "10.1371/journal.pone.0318353",
        "analysis": "Exploratory descriptive reanalysis of published, already-filtered Experiment 2",
        "participants": 80, "rows": len(rows), "stimuli_per_participant": 90,
        "font_means": {font: statistics.mean(entry[font] for entry in participant_means) for font in fonts},
        "comparisons": comparisons, "bootstrap_seed": 20260911, "bootstrap_samples": 5000,
        "resampling_unit": "participant; all five font means kept together",
        "limits": "No item resampling, exclusion replication, causal estimate, or GLMM refit; intervals are pointwise, not simultaneous",
    }
    save_json("character_exp2_reanalysis.json", result)
    print(json.dumps(result, ensure_ascii=False))


def board(ids: list[str], name: str) -> None:
    materials = MaterialCatalog(ROOT)
    if Path(name).name != name or not name.endswith(".png"):
        raise ValueError("Board name must be a PNG filename")
    columns, width, height = 3, 600, 420
    canvas = Image.new("RGB", (columns * width, ((len(ids) + columns - 1) // columns) * height), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    label = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 17)
    manifest = []
    for index, material_id in enumerate(ids):
        item = materials.items[material_id]
        source = item["representations"]["original"]
        data = (ROOT / source["path"]).read_bytes()
        assert digest(data) == source["sha256"]
        assert item["use_status"]["local_analysis"].startswith("allowed")
        with Image.open(ROOT / source["path"]) as image:
            original_size = image.size
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((width - 16, height - 48), Image.Resampling.LANCZOS)
            left, top = (index % columns) * width, (index // columns) * height
            canvas.paste(image, (left + (width - image.width) // 2, top + 8))
        draw.text((left + 8, top + height - 34), f"{index + 1:02d} {material_id}", fill="black", font=label)
        manifest.append({"index": index + 1, "material_id": material_id, "work_id": item["work_id"],
                         "title": item["source"]["title"], "path": source["path"],
                         "source_sha256": source["sha256"], "original_size": original_size,
                         "transform": "EXIF transpose, RGB, proportional thumbnail; no crop"})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT / name)
    save_json(name + ".manifest.json", manifest)
    print(json.dumps({"board": str(OUTPUT / name), "materials": len(manifest)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inventory", "acquire", "board", "analyze-characters"])
    parser.add_argument("values", nargs="*")
    args = parser.parse_args()
    if args.action == "inventory":
        inventory()
    elif args.action == "acquire":
        acquire(*args.values)
    elif args.action == "analyze-characters":
        analyze_characters()
    else:
        board(args.values[1:], args.values[0])
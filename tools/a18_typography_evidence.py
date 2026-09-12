"""Local A18 weight comparison and report figures using the existing workbench."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from glyph_features.asset_system.catalog import canonical_json, sha256_file, stable_id
from glyph_features.workbench.catalog import Catalog
from glyph_features.workbench.materials import MaterialCatalog
from glyph_features.workbench.personas import PersonaExecutor
from glyph_features.workbench.research import (
    FontSampleConfig,
    MaterialSelection,
    PresentationCondition,
    ResearchService,
    StudyConfig,
)
from glyph_features.workbench.research_results import analyze_research


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT.parent / "GLYPH-worktrees" / "task-05"
OUTPUT = ROOT / "data/processed/autoresearch/2026-09-11-report"
SANS = "asset_42301739c81790589f49c776"
SERIF = "asset_2a1da22bd728c4e88aa290af"
ROBOTO = "asset_649a8b6b9e5387be75f4f4af"
TEXTS = {"zh": ["林间花房", "港湾面包"], "en": ["Forest Flowers", "Harbor Bakery"]}


def services():
    research = ResearchService(
        Catalog(ENGINE / "data/processed/workbench_v04/catalog.sqlite3"),
        MaterialCatalog(ROOT), ENGINE,
    )
    return research, PersonaExecutor(research)


def write_json(name, value):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def label_font(size):
    font = ImageFont.truetype(str(ROOT / "图包与字体包/字体包/汉字/NotoSansSC-Variable.ttf"), size)
    font.set_variation_by_axes([400])
    return font


def figure(research, samples, language):
    variants = [(SANS, 100), (SANS, 400), (SANS, 900), (SERIF, 400)] if language == "zh" else [(ROBOTO, 100), (ROBOTO, 400), (ROBOTO, 900)]
    board = Image.new("RGB", (1440, 90 + 220 * len(variants)), "white")
    drawing = ImageDraw.Draw(board)
    for column, text in enumerate(TEXTS[language]):
        drawing.text((column * 720 + 24, 20), text, fill="#182c24", font=label_font(32))
        for row, (family, weight) in enumerate(variants):
            item = samples[(text, family, weight)]
            source = research.materials.image_path(item["material_id"], "original")
            with Image.open(source) as image:
                board.paste(image.convert("RGB").resize((704, 176), Image.Resampling.LANCZOS), (column * 720 + 8, 122 + row * 220))
            name = "Serif" if family == SERIF else "Sans" if family == SANS else "Roboto"
            drawing.text((column * 720 + 24, 90 + row * 220), f"{name} / w{weight}", fill="#333333", font=label_font(23))
    board.save(OUTPUT / f"weight_{language}.png")


def commercial_figure(research):
    run = research.get("study_dfbb8c0bf244a35dd49b9d6a")
    board = Image.new("RGB", (1440, 690), "#f3f4f2")
    drawing = ImageDraw.Draw(board)
    for column, record in enumerate(run["snapshot"]["materials"]):
        source = Path(record["input_path"])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["input_sha256"]
        with Image.open(source) as image:
            preview = image.convert("RGB")
            preview.thumbnail((680, 510), Image.Resampling.LANCZOS)
            board.paste(preview, (column * 720 + (720 - preview.width) // 2, 130 + (510 - preview.height) // 2))
        title = "Hanyi Redcloud Li" if column == 0 else "Kontrapunkt Type"
        drawing.text((column * 720 + 24, 24), title, fill="#182c24", font=label_font(32))
        drawing.text((column * 720 + 24, 76), "A median: 6 / clarity: 5" if column == 0 else "A median: 5 / clarity: 6", fill="#333333", font=label_font(25))
    board.save(OUTPUT / "commercial_regions.png")


def prepare():
    research, executor = services()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    samples = {}
    for family, language in [(SANS, "zh"), (ROBOTO, "en"), (SERIF, "zh")]:
        for weight in ([400] if family == SERIF else [100, 400, 900]):
            for item in research.render_font_samples(FontSampleConfig(font_ids=[family], texts=TEXTS[language], weight=weight)):
                samples[(item["sample_provenance"]["content"], family, weight)] = item
    measurements = []
    for (text, family, weight), item in samples.items():
        source = research.materials.image_path(item["material_id"], "original")
        with Image.open(source) as image:
            array = np.asarray(image.convert("L"))
            assert image.size == (1280, 320)
        for threshold in [96, 128, 160]:
            mask = array < threshold
            vertical, horizontal = np.where(mask)
            bbox_area = int((horizontal.max() - horizontal.min() + 1) * (vertical.max() - vertical.min() + 1))
            measurements.append({"material_id": item["material_id"], "content": text, "font_id": family, "weight": weight, "threshold": threshold, "canvas_fill": float(mask.mean()), "bbox_fill": float(mask.sum() / bbox_area), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    for language, family in [("zh", SANS), ("en", ROBOTO)]:
        for text in TEXTS[language]:
            for threshold in [96, 128, 160]:
                fills = [next(entry["canvas_fill"] for entry in measurements if entry["content"] == text and entry["font_id"] == family and entry["weight"] == weight and entry["threshold"] == threshold) for weight in [100, 400, 900]]
                assert fills[0] < fills[1] < fills[2]
        figure(research, samples, language)
    commercial_figure(research)
    contrasts = {}
    plan = []
    for language, family in [("zh", SANS), ("en", ROBOTO)]:
        for content_index, text in enumerate(TEXTS[language]):
            pairs = [("w400-w100", (family, 400), (family, 100)), ("w900-w400", (family, 900), (family, 400))]
            if language == "zh":
                pairs += [("serif400-sans100", (SERIF, 400), (SANS, 100)), ("serif400-sans400", (SERIF, 400), (SANS, 400))]
            for name, positive, reference in pairs:
                group = f"{language}{content_index + 1}-{name}"
                material_ids = [samples[(text, *variant)]["material_id"] for variant in [positive, reference]]
                contrasts[group] = {"content": text, "language": language, "contrast": name, "positive": material_ids[0], "reference": material_ids[1]}
                for repetition in range(2):
                    for order in ["ab", "ba"]:
                        plan.append(PresentationCondition(condition_id=order, group_id=group, material_ids=material_ids if order == "ab" else material_ids[::-1], repetition=repetition, questionnaire_mode="aesthetic_only"))
    random.Random(20260915).shuffle(plan)
    config = StudyConfig(
        name="W01 字重与类别：两家族、四新零售字样",
        question="同一家族字重变化能否改变美观；宋体对极细黑体的优势是否在常规黑体对照中保持？",
        explanations=["同一家族的重量选择影响具体字样美观，类别不足以决定偏好", "宋体对黑体的优势不依赖黑体是极细还是常规字重", "更粗的字重在所有当前字样上更好看"],
        selections=[MaterialSelection(material_id=item["material_id"], representation="original", reason="新零售字样；固定96px/1280x320，真实字重轴，未按评分选择") for item in samples.values()],
        roles=["baseline"], orders=["forward", "reverse"], repetitions=1,
        questionnaire_mode="aesthetic_only", presentation_mode="explicit", presentation_plan=plan,
        design_version="W01-20260911-v1", parent_assessment_id="assessment_d674cd9f3ae5a4b38ce89e6f",
        design_rationale="AB01之后改用两图、两读取方向各两次，既有q3只问美观。中文两新字样含黑体100/400/900及宋体400；拉丁两新字样含Roboto100/400/900，wdth保持默认100。两个语言不是匹配翻译实验；新字样为控制材料，不是商业原作。",
        selection_scope="四新花店/面包店字样按类别覆盖选定，与旧评分无关；两独立无衬线家族内比较，不以两语言差估文字系统作用。旧商业实例作为报告的实际设计证据，未替换原图。",
        stopping_rule="完成12内容内对比各两读取方向两次共48调用，保留全部失败及反例，不按方向追加。若量尺对这些大幅可见重量差仍无重复分辨力，则停止同类评分并另立直接偏好测量版本；不称无重量效应。",
        predictions=["重量主张若成立，至少一个同家族对比跨两个内容与两方向/重复保持非零方向；全零或反向收窄主张。", "类别不依赖重量主张若成立，宋体减黑体在100和400对照下都应保持正向；不预定哪方胜。", "单调加粗主张要求400减100及900减400在全部四字样均正向；持平或负差是反例。"],
        design_contract={"status": "frozen_exploratory_before_answers", "protocol": "W01-20260911-v1", "evidence_level": "synthetic_persona", "primary_outcome": "aesthetic", "contrasts": contrasts, "seed": 20260915, "unit": "font-instance/content within shared-model calls; not independent humans", "outcomes_not_collected": ["premium_positioning", "visual_clarity"], "exclusions": "existing view/order/JSON compliance only; no score or reason-based exclusions", "matching": "same group, order, repetition; within-call positive minus reference", "scope_axes": {"writing": "Chinese Han and English Latin analyzed separately", "brand_origin": "not applicable to generated controls", "designer_origin": "not inferred", "evaluator": "shared-model baseline, no fictional language group contrast"}},
    )
    run = research.create(config)
    assert not run["snapshot"]["blockers"]
    tasks = executor.prepare(run["run_id"])
    assert len(tasks) == 48 and all(len(task["inputs"]) == 2 for task in tasks)
    write_json("weight_protocol.json", {"run_id": run["run_id"], "config": run["config"], "snapshot": run["snapshot"]})
    write_json("weight_measurements.json", measurements)
    print(json.dumps({"run_id": run["run_id"], "tasks": len(tasks), "materials": len(samples), "figures": str(OUTPUT), "monotonic_ink_checks": 12}, ensure_ascii=False))


def analyze():
    frozen = json.loads((OUTPUT / "weight_protocol.json").read_text(encoding="utf-8"))
    research, executor = services()
    result = analyze_research(research, executor, frozen["run_id"])
    contrasts = frozen["config"]["design_contract"]["contrasts"]
    system_rows = {(row["task_id"], row["material_id"]): row for row in result["rows"]}
    paired = []
    statuses = Counter()
    for task in result["tasks_and_raw_returns"]:
        for attempt in task["attempts"]:
            statuses[attempt["status"]] += 1
            if not attempt["evidence"].get("analysis_eligible"):
                continue
            raw = json.loads(attempt["raw_return"])
            scores = {row["material_id"]: row["aesthetic"] for row in raw["ratings"]}
            assert list(scores) == [entry["material_id"] for entry in task["inputs"]]
            for material_id, value in scores.items():
                assert system_rows[(task["task_id"], material_id)]["aesthetic"] == value
            contrast = contrasts[task["condition"]["group_id"]]
            positive, reference = scores[contrast["positive"]], scores[contrast["reference"]]
            paired.append({**contrast, "task_id": task["task_id"], "order": task["condition"]["order"], "repetition": task["condition"]["repetition"], "positive_score": positive, "reference_score": reference, "difference": None if positive is None or reference is None else positive - reference})
    groups = defaultdict(list)
    for pair in paired:
        groups[(pair["content"], pair["contrast"])].append(pair)
    summary = []
    for (text, name), pairs in groups.items():
        ordered = sorted(pairs, key=lambda pair: (pair["order"], pair["repetition"]))
        values = [pair["difference"] for pair in ordered]
        observed = [value for value in values if value is not None]
        summary.append({"content": text, "contrast": name, "differences_ab0_ab1_ba0_ba1": values, "observed": len(observed), "mean": sum(observed) / len(observed) if observed else None})
    evidence = {"run_id": frozen["run_id"], "result_sha256": result["result_sha256"], "statuses": dict(statuses), "raw_verified_rows": len(system_rows), "pairs": paired, "summary": summary}
    write_json("weight_results.json", evidence)
    if paired:
        with (OUTPUT / "weight_pairs.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(paired[0]))
            writer.writeheader()
            writer.writerows(paired)
    print(json.dumps({key: value for key, value in evidence.items() if key != "pairs"}, ensure_ascii=False, indent=2))


def prepare_pair(stage):
    research, executor = services()
    frozen = json.loads((OUTPUT / "weight_protocol.json").read_text(encoding="utf-8"))
    by_id = {record["selection"]["material_id"]: record for record in frozen["snapshot"]["materials"]}
    by_variant = {(record["material"]["sample_provenance"]["content"], record["material"]["sample_provenance"]["font_asset_id"], record["material"]["sample_provenance"]["weight"]): record for record in by_id.values()}
    if stage == "pilot":
        comparisons = [{"content": TEXTS[language][0], "language": language, "contrast": "w900-w100", "positive": by_variant[(TEXTS[language][0], family, 900)]["selection"]["material_id"], "reference": by_variant[(TEXTS[language][0], family, 100)]["selection"]["material_id"]} for language, family in [("zh", SANS), ("en", ROBOTO)]]
    else:
        comparisons = list(frozen["config"]["design_contract"]["contrasts"].values())
    directory = research.output_root / "font_samples"
    selections, plan, mapping = [], [], {}
    for comparison in comparisons:
        records = [by_id[comparison[key]] for key in ["positive", "reference"]]
        images = []
        boxes = []
        for record in records:
            assert sha256_file(record["input_path"]) == record["input_sha256"]
            with Image.open(record["input_path"]) as source:
                image = source.convert("RGB")
                pixels = np.asarray(image.convert("L"))
                vertical, horizontal = np.where(pixels < 160)
                boxes.append((int(horizontal.min()), int(vertical.min()), int(horizontal.max()) + 1, int(vertical.max()) + 1))
                images.append(image)
        common = [min(box[0] for box in boxes) - 32, min(box[1] for box in boxes) - 24, max(box[2] for box in boxes) + 32, max(box[3] for box in boxes) + 24]
        width, height = common[2] - common[0], common[3] - common[1]
        for swap in [False, True]:
            members = records[::-1] if swap else records
            selected_images = images[::-1] if swap else images
            provenance = {"source_run": frozen["run_id"], "members": [{"label": label, "material_id": record["selection"]["material_id"], "sha256": record["input_sha256"]} for label, record in zip(["A", "B"], members)], "common_crop": common, "scale": 1, "labels_excluded_from_judgment": True, "content": comparison["content"]}
            material_id = stable_id("sample", provenance)
            board = Image.new("RGB", (width * 2 + 24, height + 60), "white")
            drawing = ImageDraw.Draw(board)
            for column, (label, image) in enumerate(zip(["A", "B"], selected_images)):
                drawing.text((column * (width + 24) + 12, 8), label, font=label_font(26), fill="black")
                cropped = image.crop(common)
                board.paste(cropped, (column * (width + 24), 60))
                assert np.array_equal(np.asarray(board.crop((column * (width + 24), 60, column * (width + 24) + width, height + 60))), np.asarray(cropped))
            image_path = directory / f"{material_id}.png"
            if not image_path.exists():
                board.save(image_path)
            else:
                with Image.open(image_path) as existing:
                    assert np.array_equal(np.asarray(existing), np.asarray(board))
            item = {"material_id": material_id, "kind": "paired_design_board", "candidate": None, "work_id": None, "source": {"title": f"{stage}: {comparison['content']} / {comparison['contrast']} / {'BA' if swap else 'AB'}"}, "rights_evidence": [], "representations": {"original": {"path": image_path.name, "sha256": sha256_file(image_path), "exists": True}}, "use_status": {"local_analysis": "allowed_verified_font_render", "model_input": "allowed_verified_font_render", "redistribution": "not_authorized"}, "board_provenance": provenance, "gaps": ["Generated comparison board, not a commercial original or single-font sample"]}
            manifest = directory / f"{material_id}.json"
            if manifest.exists():
                assert manifest.read_bytes() == canonical_json(item)
            else:
                manifest.write_bytes(canonical_json(item))
            mapping[material_id] = {**comparison, **provenance, "positive_label": "B" if swap else "A", "swapped": swap}
            selections.append(MaterialSelection(material_id=material_id, representation="original", reason="同屏直接比较，共同裁剪且1:1像素，标签随机侧而不透露字体信息"))
            plan.append(PresentationCondition(condition_id="board", group_id=material_id, material_ids=[material_id], questionnaire_mode="aesthetic_pair"))
    research.materials.attach_generated_samples(directory)
    random.Random(20260916).shuffle(plan)
    run = research.create(StudyConfig(
        name=f"W02-{stage} 同屏美观选择与粗细核对",
        question="同屏、允许持平的直接美观选择能否区分具体重量及类别，而非受7点评分压缩？",
        explanations=["同屏直接选择具有分辨力，且能辨认真实字重变化", "字重选择改变具体字样的美观偏好，不存在单调加粗规则"],
        selections=selections, roles=["baseline"], repetitions=1,
        questionnaire_mode="aesthetic_pair", presentation_mode="explicit", presentation_plan=plan,
        design_version=f"W02-{stage}-20260911-v1",
        selection_scope="复用W01全部源字节；pilot按清单第一个中文/英文内容、极端100/900，不按新分数挑选；main按原12对比。",
        design_rationale="共同bbox加固定留白、原像素1:1两列；左右交换，A/B仅位置标签。美观选择先，粗细核对后；这是新呈现和新测量的联合改动，不单估量尺效应。",
        stopping_rule="pilot四份：两个家族极端重量左右交换。仅在全部四份粗细核对正确且无看图违规时扩展main；否则保留全部原答并停止此测量，转独立证据。main完成12对比左右交换24份，不为赢家追加；较细/较粗/持平选择按内容和侧位分别报告。",
        design_contract={"status": "frozen_exploratory_before_answers", "primary_outcome": "aesthetic_preference", "primary_construct": "aesthetic", "scalar_aesthetic": "not_collected", "post_choice_check": "heavier_choice", "board_mapping": mapping, "exclusions": "host compliance; semantic weight errors reported, not silently excluded", "instrument": "synthetic_persona-q4-pair", "model_scope": "same displayed Auto route, not human subjects"},
    ))
    tasks = executor.prepare(run["run_id"])
    assert len(tasks) == len(plan) == (4 if stage == "pilot" else 24)
    write_json(f"pair_{stage}_protocol.json", {"run_id": run["run_id"], "config": run["config"], "snapshot": run["snapshot"]})
    print(json.dumps({"run_id": run["run_id"], "tasks": len(tasks), "example": str(directory / f"{next(iter(mapping))}.png")}, ensure_ascii=False))


def analyze_pairs():
    research, executor = services()
    summaries = []
    for stage in ["pilot", "main", "model", "fixed", "unprimed"]:
        frozen = json.loads((OUTPUT / f"pair_{stage}_protocol.json").read_text(encoding="utf-8"))
        result = analyze_research(research, executor, frozen["run_id"])
        mapping = frozen["config"]["design_contract"]["board_mapping"]
        invocations = {task["task_id"]: executor.invocation(task, frozen["config"])["invocation_prompt"] for task in executor.tasks(frozen["run_id"])}
        system = {(row["task_id"], row["material_id"]): row for row in result["rows"]}
        rows = []
        for task in result["tasks_and_raw_returns"]:
            for attempt in task["attempts"]:
                evidence = attempt["evidence"]
                if not evidence.get("analysis_eligible"):
                    continue
                assert evidence["outer_prompt"] == invocations[task["task_id"]]
                raw = json.loads(attempt["raw_return"])["ratings"]
                assert len(raw) == 1 and raw[0]["material_id"] == task["inputs"][0]["material_id"]
                rating = raw[0]
                stored = system[(task["task_id"], rating["material_id"])]
                for field in (["preference_choice"] if stage == "unprimed" else ["preference_choice", "heavier_choice"]):
                    assert rating[field] == stored[field]
                assert stored["aesthetic"] is None
                board = mapping[rating["material_id"]]
                if stage in {"model", "fixed", "unprimed"}:
                    assert evidence["model_display_name"] == "GPT-6 Astra"
                choice = rating["preference_choice"]
                selected = next((member["material_id"] for member in board["members"] if member["label"] == choice), None)
                winner = ("positive" if selected == board["positive"] else "reference") if selected else choice
                rows.append({"task_id": task["task_id"], **rating, "content": board["content"], "contrast": board["contrast"], "positive_label": board["positive_label"], "winner": winner, "weight_correct": rating["heavier_choice"] == board["positive_label"] if board["contrast"].startswith("w") and stage != "unprimed" else None, "model": evidence["model_display_name"]})
        groups = defaultdict(list)
        for row in rows:
            groups[(row["content"], row["contrast"])].append(row)
        summary = [{"content": content, "contrast": contrast, "winners_positive_at_A_then_B": [row["winner"] for row in sorted(group, key=lambda row: row["positive_label"])], "weight_checks": [row["weight_correct"] for row in group]} for (content, contrast), group in groups.items()]
        report = {"stage": stage, "run_id": frozen["run_id"], "result_sha256": result["result_sha256"], "statuses": dict(Counter(task["status"] for task in result["tasks_and_raw_returns"])), "rows": rows, "summary": summary}
        write_json(f"pair_{stage}_results.json", report)
        summaries.append({key: value for key, value in report.items() if key != "rows"})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "analyze", "pair-pilot", "pair-main", "analyze-pairs"])
    action = parser.parse_args().action
    if action == "analyze-pairs":
        analyze_pairs()
    elif action.startswith("pair-"):
        prepare_pair(action.split("-")[1])
    elif action == "prepare":
        prepare()
    else:
        analyze()
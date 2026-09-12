"""Persistent exploratory studies, separate from human and fixture ratings."""

from __future__ import annotations

import json
import io
import sqlite3
import random
from dataclasses import asdict
from itertools import permutations
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version
from fontTools.ttLib import TTFont
from pydantic import BaseModel, Field, model_validator

from glyph_features.asset_system.catalog import canonical_json, sha256_file, stable_id, utc_now
from glyph_features.vision_system.definitions import load_registry
from glyph_features.vision_system.extract import measure_array

from .catalog import Catalog, CatalogError
from .materials import MaterialCatalog


QuestionnaireMode = Literal["q2", "aesthetic_only", "premium_only", "aesthetic_premium", "premium_aesthetic", "aesthetic_pair", "aesthetic_pair_only"]
QUESTIONNAIRE_SCALES = {
    "q2": ("aesthetic", "visual_clarity"),
    "aesthetic_only": ("aesthetic",),
    "premium_only": ("premium_positioning",),
    "aesthetic_premium": ("aesthetic", "premium_positioning"),
    "premium_aesthetic": ("premium_positioning", "aesthetic"),
    "aesthetic_pair": (),
    "aesthetic_pair_only": (),
}


class MaterialSelection(BaseModel):
    material_id: str
    representation: Literal["original", "standardized"] = "standardized"
    reason: str = Field(min_length=3, max_length=2000)
    crop_box: tuple[int, int, int, int] | None = None
    foreground: Literal["unconfirmed", "dark", "light"] = "unconfirmed"
    foreground_note: str = Field(default="", max_length=2000)
    color_mode: Literal["native", "grayscale"] = "native"
    max_edge: int | None = Field(default=None, ge=128, le=4096)

    @model_validator(mode="after")
    def check_foreground(self):
        if self.foreground != "unconfirmed" and (self.crop_box is None or len(self.foreground_note.strip()) < 10):
            raise ValueError("TEXT_REGION_REQUIRES_CROP_AND_OBSERVATION")
        return self


def transform_image(image: Image.Image, selection: MaterialSelection) -> Image.Image:
    if selection.max_edge is not None and max(image.size) > selection.max_edge:
        image = image.copy()
        image.thumbnail((selection.max_edge, selection.max_edge), Image.Resampling.LANCZOS)
    if selection.color_mode == "grayscale":
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image.convert("RGBA")).convert("L").convert("RGB")
    return image


def measurement_array(image: Image.Image, foreground: str) -> np.ndarray:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", image.size, "white")
    array = np.asarray(Image.alpha_composite(background, rgba).convert("L"))
    return 255 - array if foreground == "light" else array


def representation_preview(image: Image.Image, foreground: str, layer: str) -> Image.Image:
    if layer == "input":
        return image
    mask = measurement_array(image, foreground) < 128
    if layer == "mask":
        return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    overlay = np.array(image.convert("RGB"), copy=True)
    overlay[mask] = (overlay[mask].astype(float) * 0.45 + np.array([230, 40, 100]) * 0.55).astype(np.uint8)
    return Image.fromarray(overlay)


class PresentationCondition(BaseModel):
    condition_id: str = Field(min_length=1, max_length=100)
    group_id: str = Field(min_length=1, max_length=100)
    material_ids: list[str] = Field(min_length=1)
    repetition: int = Field(default=0, ge=0)
    questionnaire_mode: QuestionnaireMode | None = None


class StudyConfig(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    question: str = Field(min_length=5, max_length=4000)
    explanations: list[str] = Field(min_length=1)
    selections: list[MaterialSelection] = Field(min_length=1)
    roles: list[Literal["baseline", "zh", "en", "ja", "ko"]] = Field(default_factory=lambda: ["baseline", "zh"])
    orders: list[Literal["forward", "reverse"]] = Field(default_factory=lambda: ["forward", "reverse"], min_length=1)
    questionnaire_language: Literal["en", "zh-Hans"] = "en"
    repetitions: int = Field(default=1, ge=1)
    task_size: int | None = Field(default=None, ge=1)
    wording: Literal["background", "profile"] = "background"
    executor_agent: Literal["Explore", "default"] = "Explore"
    primary_outcome: Literal["aesthetic"] = "aesthetic"
    reference_run_id: str | None = Field(default=None, pattern=r"^study_[0-9a-f]{24}$")
    parent_assessment_id: str | None = Field(default=None, pattern=r"^assessment_[0-9a-f]{24}$")
    design_rationale: str = Field(default="", max_length=5000)
    predictions: list[str] = Field(default_factory=list)
    selection_scope: str = Field(min_length=5, max_length=4000)
    stopping_rule: str = Field(min_length=5, max_length=4000)
    design_version: str = Field(default="exploratory_persona_study_1", min_length=1)
    presentation_plan: list[PresentationCondition] = Field(default_factory=list)
    design_contract: dict = Field(default_factory=dict)
    presentation_mode: Literal["legacy", "explicit", "triplet_pairs", "measurement_bridge"] = "legacy"
    questionnaire_mode: QuestionnaireMode = "q2"
    task_path_layout: Literal["nested_v1", "flat_v1"] = "flat_v1"
    bridge_modes: list[QuestionnaireMode] = Field(default_factory=lambda: ["aesthetic_only", "premium_only", "aesthetic_premium", "premium_aesthetic"], min_length=1)
    focal_font_ids: list[str] = Field(default_factory=list)
    schedule_seed: int = 20260911

    @model_validator(mode="after")
    def check_design(self):
        if "baseline" not in self.roles:
            raise ValueError("BASELINE_REQUIRED")
        for values in (self.roles, self.orders, [item.material_id for item in self.selections]):
            if len(values) != len(set(values)):
                raise ValueError("DUPLICATE_DESIGN_CONDITION")
        if self.presentation_plan:
            if self.presentation_mode not in {"triplet_pairs", "measurement_bridge"} and (self.repetitions != 1 or self.task_size is not None):
                raise ValueError("EXPLICIT_PLAN_OWNS_GROUPING_AND_REPETITIONS")
            selected_ids = {item.material_id for item in self.selections}
            identities = set()
            for entry in self.presentation_plan:
                identity = (entry.condition_id, entry.group_id, entry.repetition)
                if identity in identities or len(entry.material_ids) != len(set(entry.material_ids)):
                    raise ValueError("DUPLICATE_PRESENTATION")
                if not set(entry.material_ids) <= selected_ids:
                    raise ValueError("PRESENTATION_MATERIAL_NOT_SELECTED")
                identities.add(identity)
        return self


class ExplanationUpdate(BaseModel):
    explanation: str = Field(min_length=3, max_length=2000)
    judgment: Literal["supported", "not_supported", "unresolved"]
    evidence: str = Field(min_length=5, max_length=5000)
    material_ids: list[str] = Field(min_length=1)


class FontSampleConfig(BaseModel):
    font_ids: list[str] = Field(min_length=1)
    texts: list[str] = Field(min_length=1)
    font_size: int = Field(default=96, ge=16, le=256)
    weight: int = Field(default=400, ge=100, le=900)
    width: int = Field(default=1280, ge=256, le=2048)
    height: int = Field(default=320, ge=128, le=1024)


class ResearchAssessment(BaseModel):
    basis_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conclusion: str = Field(min_length=10, max_length=6000)
    explanation_updates: list[ExplanationUpdate] = Field(min_length=1)
    remaining_confounds: list[str] = Field(min_length=1)
    next_question: str = Field(min_length=5, max_length=4000)
    next_comparison: str = Field(min_length=10, max_length=5000)
    decision: Literal["new_comparison", "independent_materials", "repeat_check", "stop_path"]


class ResearchService:
    def __init__(self, catalog: Catalog, materials: MaterialCatalog, workspace_root: Path):
        self.catalog = catalog
        self.materials = materials
        self.workspace_root = workspace_root
        self.output_root = catalog.database_path.parent / "research"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.materials.attach_generated_samples(self.output_root / "font_samples")
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS research_studies (
                run_id TEXT PRIMARY KEY, config_json TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                measurements_json TEXT, status TEXT NOT NULL, error_json TEXT, created_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS research_assessments (
                assessment_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                record_json TEXT NOT NULL, created_at TEXT NOT NULL
            )""")

    def connect(self):
        connection = sqlite3.connect(self.catalog.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def render_font_samples(self, config: FontSampleConfig) -> list[dict]:
        prepared = []
        for font_id in dict.fromkeys(config.font_ids):
            item = self.materials.items.get(font_id)
            if not item or item["kind"] != "font_file":
                raise CatalogError("FONT_MATERIAL_REQUIRED")
            font_ref = item["representations"]["original"]
            font_path = self.materials.safe_path(font_ref["path"])
            if sha256_file(font_path) != font_ref["sha256"]:
                raise CatalogError("FONT_FILE_CHANGED")
            with TTFont(font_path) as metadata:
                license_texts = sorted({entry.toUnicode() for entry in metadata["name"].names if entry.nameID in {13, 14}})
                if not any("SIL Open Font License" in text and "1.1" in text for text in license_texts) and not item["use_status"]["local_analysis"].startswith("allowed"):
                    raise CatalogError("FONT_RENDER_LICENSE_NOT_VERIFIED")
                cmap = metadata.getBestCmap()
                axes = {axis.axisTag: axis.defaultValue for axis in metadata["fvar"].axes} if "fvar" in metadata else {}
                if "wght" in axes:
                    weight_axis = next(axis for axis in metadata["fvar"].axes if axis.axisTag == "wght")
                    if not weight_axis.minValue <= config.weight <= weight_axis.maxValue:
                        raise CatalogError("FONT_WEIGHT_OUTSIDE_AXIS")
                    axes["wght"] = config.weight
                elif metadata["OS/2"].usWeightClass != config.weight:
                    raise CatalogError("STATIC_FONT_WEIGHT_MISMATCH")
                family = sorted({entry.toUnicode() for entry in metadata["name"].names if entry.nameID == 1})
                font = ImageFont.truetype(str(font_path), config.font_size)
                if axes:
                    font.set_variation_by_axes(list(axes.values()))
                for text in dict.fromkeys(config.texts):
                    if not text.strip() or len(text) > 80 or any(character in text for character in "\n\r\t"):
                        raise CatalogError("FONT_SAMPLE_SINGLE_LINE_REQUIRED")
                    missing = sorted({character for character in text if not character.isspace() and ord(character) not in cmap})
                    if missing:
                        raise CatalogError(f"FONT_SAMPLE_MISSING_CHARACTERS:{''.join(missing)}")
                    image = Image.new("L", (config.width, config.height), 255)
                    drawing = ImageDraw.Draw(image)
                    box = drawing.textbbox((0, 0), text, font=font)
                    ink_width, ink_height = box[2] - box[0], box[3] - box[1]
                    if ink_width > config.width - 64 or ink_height > config.height - 64:
                        raise CatalogError("FONT_SAMPLE_DOES_NOT_FIT")
                    drawing.text(((config.width - ink_width) / 2 - box[0], (config.height - ink_height) / 2 - box[1]), text, font=font, fill=0)
                    provenance = {"font_ref": font_ref, "font_asset_id": font_id, "family_names": family, "content": text, "font_size": config.font_size, "weight": config.weight, "variation_axes": axes, "canvas": [config.width, config.height], "ink_bbox_size": [ink_width, ink_height], "missing_characters": [], "embedded_license": license_texts, "renderer": "Pillow centered fixed-canvas black-on-white", "pillow_version": pillow_version, "freetype_version": ImageFont.core.freetype2_version, "renderer_sha256": sha256_file(Path(__file__))}
                    material_id = stable_id("sample", provenance)
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    prepared.append((material_id, font_id, provenance, buffer.getvalue()))
        destination = self.output_root / "font_samples"
        destination.mkdir(parents=True, exist_ok=True)
        material_ids = []
        for material_id, font_id, provenance, image_bytes in prepared:
            image_path = destination / f"{material_id}.png"
            if image_path.exists():
                if image_path.read_bytes() != image_bytes:
                    raise CatalogError("GENERATED_SAMPLE_CHANGED")
            else:
                with image_path.open("xb") as output:
                    output.write(image_bytes)
            record = {"material_id": material_id, "kind": "controlled_font_sample", "candidate": None, "font_asset_id": font_id, "work_id": font_id, "source": {"title": f"{provenance['content']} | {provenance['family_names'][0]} | w{config.weight}"}, "rights_evidence": self.materials.items[font_id]["rights_evidence"], "representations": {"original": {"path": image_path.name, "sha256": sha256_file(image_path), "exists": True}}, "use_status": {"local_analysis": "allowed_verified_font_render", "model_input": "allowed_verified_font_render", "redistribution": "not_authorized"}, "sample_provenance": provenance, "gaps": []}
            manifest = destination / f"{material_id}.json"
            payload = canonical_json(record)
            if manifest.exists():
                if manifest.read_bytes() != payload:
                    raise CatalogError("GENERATED_SAMPLE_MANIFEST_CHANGED")
            else:
                with manifest.open("xb") as output:
                    output.write(payload)
            material_ids.append(material_id)
        self.materials.attach_generated_samples(destination)
        return [self.materials.items[material_id] for material_id in material_ids]

    def preview(self, selection: MaterialSelection, layer: str = "input") -> bytes:
        image_path = self.materials.image_path(selection.material_id, selection.representation)
        with Image.open(image_path) as source:
            image = source.copy()
        if selection.crop_box:
            left, top, right, bottom = selection.crop_box
            if not 0 <= left < right <= image.width or not 0 <= top < bottom <= image.height:
                raise CatalogError("STUDY_CROP_OUTSIDE_IMAGE")
            image = image.crop(selection.crop_box)
        image = transform_image(image, selection)
        buffer = io.BytesIO()
        representation_preview(image, selection.foreground, layer).save(buffer, format="PNG")
        return buffer.getvalue()

    def create(self, config: StudyConfig) -> dict:
        if config.presentation_mode == "measurement_bridge":
            plan = []
            generator = random.Random(config.schedule_seed)
            for repetition in range(config.repetitions):
                cycle = [PresentationCondition(condition_id=f"single-{mode}", group_id=selection.material_id, material_ids=[selection.material_id], repetition=repetition, questionnaire_mode=mode) for selection in config.selections for mode in dict.fromkeys(config.bridge_modes)]
                generator.shuffle(cycle)
                plan.extend(cycle)
            config = config.model_copy(update={"presentation_plan": plan, "design_version": "measurement-bridge-v1"})
        if config.presentation_mode == "triplet_pairs":
            if len(config.focal_font_ids) != 2 or len(set(config.focal_font_ids)) != 2:
                raise CatalogError("TWO_DISTINCT_FOCAL_FONTS_REQUIRED")
            groups = {}
            for selection in config.selections:
                item = self.materials.items.get(selection.material_id, {})
                sample = item.get("sample_provenance", {})
                if not sample.get("content"):
                    raise CatalogError("TRIPLET_PLAN_REQUIRES_FONT_SAMPLES")
                groups.setdefault(sample["content"], []).append((sample.get("font_asset_id"), selection.material_id))
            plan = []
            generator = random.Random(config.schedule_seed)
            for repetition in range(config.repetitions):
                cycle = []
                for content, members in groups.items():
                    by_font = dict(members)
                    if len(members) != 3 or len(by_font) != 3 or not set(config.focal_font_ids) <= set(by_font):
                        raise CatalogError("EACH_CONTENT_REQUIRES_THREE_FONTS_WITH_FOCAL_PAIR")
                    ordered_fonts = config.focal_font_ids + [font_id for font_id in by_font if font_id not in config.focal_font_ids]
                    for order in [*permutations(range(3)), (0, 1), (1, 0)]:
                        cycle.append(PresentationCondition(condition_id="set" + str(len(order)) + "-" + "".join(str(index + 1) for index in order), group_id=content, material_ids=[by_font[ordered_fonts[index]] for index in order], repetition=repetition))
                generator.shuffle(cycle)
                plan.extend(cycle)
            config = config.model_copy(update={"presentation_plan": plan, "design_version": "triplet-pairs-v1"})
        reference = self.get(config.reference_run_id) if config.reference_run_id else None
        parent_assessment = self.get_assessment(config.parent_assessment_id) if config.parent_assessment_id else None
        selected = []
        blockers = []
        for selection in config.selections:
            if selection.material_id not in self.materials.items:
                raise CatalogError("STUDY_MATERIAL_NOT_FOUND")
            item = self.materials.items[selection.material_id]
            selected_record = {"selection": selection.model_dump(), "material": item}
            try:
                image_path = self.materials.image_path(selection.material_id, selection.representation)
                selected_record["source_input_sha256"] = sha256_file(image_path)
                if selection.crop_box is not None:
                    with Image.open(image_path) as image:
                        left, top, right, bottom = selection.crop_box
                        if not 0 <= left < right <= image.width or not 0 <= top < bottom <= image.height:
                            raise CatalogError("STUDY_CROP_OUTSIDE_IMAGE")
                        selected_record["source_dimensions"] = list(image.size)
                        cropped = image.crop(selection.crop_box)
                        buffer = io.BytesIO()
                        cropped.save(buffer, format="PNG")
                    derived = self.output_root / "representations" / f"{stable_id('crop', {'source': selected_record['source_input_sha256'], 'box': selection.crop_box})}.png"
                    derived.parent.mkdir(parents=True, exist_ok=True)
                    if derived.exists():
                        if derived.read_bytes() != buffer.getvalue():
                            raise CatalogError("STUDY_DERIVED_IMAGE_CHANGED")
                    else:
                        with derived.open("xb") as destination:
                            destination.write(buffer.getvalue())
                    image_path = derived
                if selection.color_mode != "native" or selection.max_edge is not None:
                    with Image.open(image_path) as image:
                        transformed = transform_image(image, selection)
                        buffer = io.BytesIO()
                        transformed.save(buffer, format="PNG")
                        selected_record["display_transform"] = {"color_mode": selection.color_mode, "max_edge": selection.max_edge, "before_size": list(image.size), "after_size": list(transformed.size), "method": "Pillow optional Lanczos thumbnail; white-alpha composite/L/RGB"}
                    derived = self.output_root / "representations" / f"{stable_id('display', {'source': sha256_file(image_path), 'color_mode': selection.color_mode, 'max_edge': selection.max_edge})}.png"
                    derived.parent.mkdir(parents=True, exist_ok=True)
                    if derived.exists():
                        if derived.read_bytes() != buffer.getvalue():
                            raise CatalogError("STUDY_DERIVED_IMAGE_CHANGED")
                    else:
                        with derived.open("xb") as destination:
                            destination.write(buffer.getvalue())
                    image_path = derived
                selected_record["input_path"] = str(image_path)
                selected_record["input_sha256"] = sha256_file(image_path)
            except (KeyError, ValueError) as error:
                blockers.append({"material_id": selection.material_id, "use": "representation", "reason": str(error)})
            for use in ("local_analysis", "model_input"):
                if not item["use_status"][use].startswith("allowed"):
                    blockers.append({"material_id": selection.material_id, "use": use, "reason": item["use_status"][use]})
            if item["use_status"].get("study_eligibility") == "blocked_missing_characters":
                blockers.append({"material_id": selection.material_id, "use": "measurement_and_questionnaire", "reason": "SAMPLE_FONT_MISSING_CHARACTERS"})
            selected.append(selected_record)
        questionnaire = self.workspace_root / "configs/questionnaire_v1.json"
        registry = self.workspace_root / "configs/visual_measurements_v2.yaml"
        snapshot = {
            "version": "exploratory_persona_study_1",
            "data_origin": "synthetic_persona",
            "formal_stimulus_release": False,
            "materials": selected,
            "catalog_manifest_hashes": self.materials.manifest_hashes,
            "questionnaire_path": str(questionnaire),
            "questionnaire_sha256": sha256_file(questionnaire),
            "measurement_registry_sha256": sha256_file(registry),
            "blockers": blockers,
            "not_selected_count": len(self.materials.items) - len(selected),
            "not_selected_reason": config.selection_scope,
            "missing_rule": "Keep missing/refused/invalid responses; never exclude by score. Compare only matched observed items; report denominators.",
            "inference_boundary": "Shared-model repeated calls, not independent humans; prompt identity does not erase multilingual knowledge; reasons are not causal evidence.",
        }
        evidence_path = self.materials.root / "configs/research_evidence_v1.json"
        if evidence_path.is_file():
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            selected_ids = {item.material_id for item in config.selections}
            snapshot["specific_evidence"] = {
                "path": str(evidence_path), "sha256": sha256_file(evidence_path),
                "entries": [entry for entry in evidence["entries"] if selected_ids.intersection(entry["material_ids"])],
            }
        if reference:
            snapshot["reference_run"] = {"run_id": reference["run_id"], "config": reference["config"], "snapshot": reference["snapshot"]}
        if parent_assessment:
            snapshot["parent_assessment"] = parent_assessment
        run_id = stable_id("study", {"config": config.model_dump(), "snapshot": snapshot})
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO research_studies VALUES (?, ?, ?, NULL, ?, NULL, ?)",
                (run_id, canonical_json(config.model_dump()).decode(), canonical_json(snapshot).decode(), "blocked" if blockers else "configured", utc_now()),
            )
        return self.get(run_id)

    def input_image(self, run_id: str, material_id: str) -> Path:
        record = next((item for item in self.get(run_id)["snapshot"]["materials"] if item["selection"]["material_id"] == material_id), None)
        if record is None or "input_path" not in record:
            raise CatalogError("STUDY_INPUT_NOT_FOUND")
        input_path = Path(record["input_path"]).resolve()
        if not input_path.is_relative_to(self.materials.root) and not input_path.is_relative_to(self.output_root.resolve()):
            raise CatalogError("STUDY_INPUT_OUTSIDE_ROOT")
        if sha256_file(input_path) != record["input_sha256"]:
            raise CatalogError("STUDY_IMAGE_CHANGED")
        return input_path

    def get_assessment(self, assessment_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT record_json FROM research_assessments WHERE assessment_id = ?", (assessment_id,)).fetchone()
        if row is None:
            raise CatalogError("RESEARCH_ASSESSMENT_NOT_FOUND")
        return json.loads(row[0])

    def assessments(self, run_id: str) -> list[dict]:
        self.get(run_id)
        with self.connect() as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM research_assessments WHERE run_id = ? ORDER BY created_at, rowid", (run_id,))]

    def save_assessment(self, run_id: str, assessment: ResearchAssessment, result: dict) -> dict:
        if result["run_id"] != run_id or assessment.basis_result_sha256 != result["result_sha256"]:
            raise CatalogError("ASSESSMENT_RESULT_CHANGED_REFRESH_FIRST")
        selected_ids = {record["selection"]["material_id"] for record in result["snapshot"]["materials"]}
        for update in assessment.explanation_updates:
            if update.explanation not in result["config"]["explanations"]:
                raise CatalogError("ASSESSMENT_EXPLANATION_NOT_IN_STUDY")
            if not set(update.material_ids).issubset(selected_ids):
                raise CatalogError("ASSESSMENT_MATERIAL_NOT_IN_STUDY")
        payload = {"run_id": run_id, **assessment.model_dump(), "basis_result": result,
                   "evidence_level": "researcher_or_agent_interpretation_not_independent_causal_evidence"}
        assessment_id = stable_id("assessment", payload)
        record = {"assessment_id": assessment_id, **payload}
        with self.connect() as connection:
            connection.execute("INSERT OR IGNORE INTO research_assessments VALUES (?, ?, ?, ?)", (assessment_id, run_id, canonical_json(record).decode(), utc_now()))
        return self.get_assessment(assessment_id)

    def continuation(self, assessment_id: str) -> dict:
        assessment = self.get_assessment(assessment_id)
        original = self.get(assessment["run_id"])
        return {**original["config"], "name": f"{original['config']['name'][:145]}-后续比较",
                "question": assessment["next_question"], "design_rationale": assessment["next_comparison"],
                "parent_assessment_id": assessment_id, "reference_run_id": original["run_id"]}

    def get(self, run_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM research_studies WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise CatalogError("STUDY_NOT_FOUND")
        result = dict(row)
        for key in ("config", "snapshot", "measurements", "error"):
            encoded = result.pop(f"{key}_json")
            result[key] = json.loads(encoded) if encoded else None
        return result

    def list(self) -> list[dict]:
        with self.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT run_id FROM research_studies ORDER BY created_at, rowid")]
        return [self.get(run_id) for run_id in ids]

    def measure(self, run_id: str) -> dict:
        run = self.get(run_id)
        if run["measurements"] is not None:
            return run
        registry_path = self.workspace_root / "configs/visual_measurements_v2.yaml"
        if sha256_file(registry_path) != run["snapshot"]["measurement_registry_sha256"]:
            raise CatalogError("STUDY_REGISTRY_CHANGED")
        registry = load_registry(registry_path, self.workspace_root / "schema")
        measurements = []
        try:
            for record in run["snapshot"]["materials"]:
                material_id = record["selection"]["material_id"]
                blocking = [item for item in run["snapshot"]["blockers"] if item["material_id"] == material_id and item["use"] != "model_input"]
                if blocking:
                    measurements.append({"material_id": material_id, "status": "blocked", "reasons": blocking})
                    continue
                input_path = Path(record["input_path"])
                if sha256_file(input_path) != record["input_sha256"]:
                    raise CatalogError("STUDY_IMAGE_CHANGED")
                is_sample = record["material"]["kind"] in {"existing_font_sample", "controlled_font_sample"}
                foreground = record["selection"].get("foreground", "unconfirmed")
                confirmed_text = foreground != "unconfirmed"
                measurement_kind = "B_shape" if is_sample or confirmed_text else "A_layout"
                with Image.open(input_path) as image:
                    array = measurement_array(image, foreground)
                    mask_path = None
                    if confirmed_text:
                        mask_path = self.output_root / "representations" / f"{stable_id('mask', {'input': record['input_sha256'], 'foreground': foreground, 'threshold': 128})}.png"
                        buffer = io.BytesIO()
                        representation_preview(image, foreground, "mask").save(buffer, format="PNG")
                        if mask_path.exists():
                            if mask_path.read_bytes() != buffer.getvalue():
                                raise CatalogError("STUDY_DERIVED_IMAGE_CHANGED")
                        else:
                            with mask_path.open("xb") as destination:
                                destination.write(buffer.getvalue())
                thresholds = []
                for threshold in (96, 128, 160):
                    metrics = measure_array(array, measurement_kind, registry, binary_threshold=threshold)
                    thresholds.append({"threshold": threshold, "metrics": {code: asdict(metric) for code, metric in metrics.items()}})
                measurements.append({
                    "material_id": material_id,
                    "status": "measured",
                    "input_sha256": record["input_sha256"],
                    "input_path": record["input_path"],
                    "representation": record["selection"]["representation"],
                    "crop_box": record["selection"].get("crop_box"),
                    "foreground": foreground,
                    "foreground_note": record["selection"].get("foreground_note", ""),
                    "mask": {"path": str(mask_path), "sha256": sha256_file(mask_path), "threshold": 128, "source_input_sha256": record["input_sha256"]} if mask_path else None,
                    "measurement_kind": measurement_kind,
                    "scope": "exploratory_observer_confirmed_text_region_not_expert_reviewed" if confirmed_text else "exploratory_existing_sample" if is_sample else "selected_composition_region_not_isolated_glyph" if record["selection"].get("crop_box") else "full_commercial_composition_not_isolated_glyph",
                    "thresholds": thresholds,
                })
            with self.connect() as connection:
                connection.execute(
                    "UPDATE research_studies SET measurements_json = ?, status = ?, error_json = NULL WHERE run_id = ?",
                    (canonical_json(measurements).decode(), "blocked" if run["snapshot"]["blockers"] else "measured", run_id),
                )
        except Exception as error:
            with self.connect() as connection:
                connection.execute("UPDATE research_studies SET status = 'failed', error_json = ? WHERE run_id = ?", (json.dumps({"stage": "measurement", "error": str(error)}), run_id))
            raise
        return self.get(run_id)
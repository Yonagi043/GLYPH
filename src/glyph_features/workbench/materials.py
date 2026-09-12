"""Read existing research materials without rewriting their source contracts."""

from __future__ import annotations

import hashlib
import json
import ast
import csv
from collections import Counter
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from glyph_features.asset_system.catalog import (
    normalize_repo_path,
    resolve_workspace_asset,
    sha256_file,
    stable_id,
)

from .catalog import CatalogError


HANDOFF = "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"
PACK = "图包与字体包"
RESEARCH_USES = "configs/research_material_uses_v1.json"


class MaterialCatalog:
    def __init__(self, material_root: str | Path):
        self.root = Path(material_root).expanduser().resolve()
        self.items: dict[str, dict[str, Any]] = {}
        self.unmatched: list[dict[str, Any]] = []
        self.manifest_hashes: dict[str, str] = {}
        self._load()

    def safe_path(self, relative: str) -> Path:
        normalized = normalize_repo_path(relative)
        candidate = (self.root / normalized).resolve()
        if not candidate.is_relative_to(self.root):
            raise CatalogError("MATERIAL_PATH_OUTSIDE_ROOT")
        return candidate

    def _json(self, relative: str) -> Any:
        file_path = self.safe_path(relative)
        self.manifest_hashes[relative] = sha256_file(file_path)
        return json.loads(file_path.read_text(encoding="utf-8"))

    def _load(self) -> None:
        handoff = self._json(HANDOFF)
        records = {}
        for logical_type in (
            "repository_asset_candidates", "source_catalog", "rights_evidence"
        ):
            output = next(item for item in handoff["outputs"] if item["logical_type"] == logical_type)
            file_path = self.safe_path(output["path"])
            if sha256_file(file_path) != output["sha256"]:
                raise CatalogError(f"MATERIAL_CATALOG_HASH_MISMATCH:{logical_type}")
            rows = [json.loads(line) for line in file_path.read_text(encoding="utf-8").splitlines() if line]
            if len(rows) != output["record_count"]:
                raise CatalogError(f"MATERIAL_CATALOG_COUNT_MISMATCH:{logical_type}")
            records[logical_type] = rows
            self.manifest_hashes[output["path"]] = output["sha256"]
        sources = {row["source_id"]: row for row in records["source_catalog"]}
        rights: dict[str, list[dict[str, Any]]] = {}
        for row in records["rights_evidence"]:
            rights.setdefault(row["source_id"], []).append(row)
        by_original = {}
        for candidate in records["repository_asset_candidates"]:
            asset_id = candidate["asset_id"]
            original = candidate["asset_ref"]
            self.safe_path(original["path"])
            self.items[asset_id] = {
                "material_id": asset_id,
                "kind": candidate["candidate_kind"],
                "candidate": candidate,
                "source": sources.get(candidate["source_id"]),
                "rights_evidence": rights.get(candidate["source_id"], []),
                "work_id": candidate.get("work_id"),
                "representations": {"original": dict(original)},
                "use_status": self._uses(),
                "gaps": [],
            }
            by_original[original["path"]] = self.items[asset_id]

        output_root = self.safe_path(f"{PACK}/标准化输出")
        for manifest_path in sorted(output_root.glob("**/_manifest_*.json")):
            relative = manifest_path.relative_to(self.root).as_posix()
            manifest = self._json(relative)
            for transform in manifest["items"]:
                source_path = normalize_repo_path(f"{PACK}/{transform['src']}")
                output_path = normalize_repo_path(f"{PACK}/{transform['out']}")
                self.safe_path(source_path)
                self.safe_path(output_path)
                item = by_original.get(source_path)
                if item is None and transform["kind"] == "font":
                    material_id = stable_id("sample", {"manifest": relative, "source": source_path})
                    item = {
                        "material_id": material_id,
                        "kind": "existing_font_sample",
                        "candidate": None,
                        "source": {"local_archive": {"path": source_path}},
                        "rights_evidence": [],
                        "work_id": None,
                        "representations": {"original": {"path": source_path}},
                        "use_status": self._uses(),
                        "gaps": ["FONT_RENDER_PROVENANCE_NOT_YET_LINKED"],
                    }
                    self.items[material_id] = item
                if item is None:
                    self.unmatched.append({
                        "manifest": relative,
                        "source": source_path,
                        "reason": "NO_REPOSITORY_CANDIDATE",
                        "source_exists": self.safe_path(source_path).is_file(),
                    })
                    continue
                if "standardized" in item["representations"]:
                    raise CatalogError("MATERIAL_TRANSFORM_AMBIGUOUS")
                item["representations"]["standardized"] = {
                    "path": output_path,
                    "transform": transform,
                    "transform_manifest": relative,
                    "transform_manifest_sha256": self.manifest_hashes[relative],
                    "representation_status": "legacy_standardized_not_formal_ABC",
                }
                self._link_font_samples()
        for item in self.items.values():
            for representation in item["representations"].values():
                representation["exists"] = self.safe_path(representation["path"]).is_file()
            if item["kind"] == "ecological_award_image" and "standardized" not in item["representations"]:
                item["gaps"].append("STANDARDIZED_NOT_MATCHED")
        images = [item for item in self.items.values() if item["kind"] == "ecological_award_image"]
        for item in images:
            item["same_image_ids"] = [other["material_id"] for other in images if other["material_id"] != item["material_id"] and other["representations"]["original"]["sha256"] == item["representations"]["original"]["sha256"]]
            item["same_work_ids"] = [other["material_id"] for other in images if other["material_id"] != item["material_id"] and other["work_id"] == item["work_id"]]
        self._load_auxiliary_fonts()
        if self.safe_path(RESEARCH_USES).is_file():
            self._apply_research_use_decision(self._json(RESEARCH_USES))

    def _apply_research_use_decision(self, decision: dict[str, Any]) -> None:
        if decision["version"] != "research_material_uses_1" or decision["basis"] != "user_declared_open":
            raise CatalogError("UNSUPPORTED_RESEARCH_USE_DECISION")
        if decision["model_channel"] != "existing_copilot" or set(decision["uses"]) - {"local_analysis", "model_input"}:
            raise CatalogError("RESEARCH_USE_OUTSIDE_SUPPORTED_SCOPE")
        scope = decision["scope"]
        source_file = self.safe_path(scope["source_catalog_path"])
        if self.manifest_hashes.get(scope["source_catalog_path"]) != scope["source_catalog_sha256"]:
            return
        source_records = {
            row["source_id"]: row
            for row in (json.loads(line) for line in source_file.read_text(encoding="utf-8").splitlines() if line)
        }
        for item in self.items.values():
            if item["kind"] != scope["candidate_kind"] or not item["candidate"]:
                continue
            original = item["representations"]["original"]
            source = item["source"]
            if not source or source_records.get(source["source_id"]) != source:
                continue
            archived = source.get("local_archive") or {}
            if not original["path"].startswith(scope["original_path_prefix"]) or not archived or any(original.get(key) != archived.get(key) for key in ("sha256", "byte_size")):
                continue
            try:
                resolve_workspace_asset(self.root, original)
            except (ValueError, OSError):
                item["gaps"].append("RESEARCH_USE_INPUT_CHANGED_OR_MISSING")
                continue
            restrictions = [
                restriction for restriction in decision["restrictions"]
                if restriction["material_id"] == item["material_id"] and restriction["sha256"] == original["sha256"]
            ]
            item["research_use_decision"] = {
                "decision": decision,
                "decision_path": RESEARCH_USES,
                "decision_sha256": self.manifest_hashes.get(RESEARCH_USES),
                "source_id": source["source_id"],
                "material_id": item["material_id"],
                "input_sha256": original["sha256"],
                "source_archive_metadata_differences": [key for key in ("path", "mime_type") if original.get(key) != archived.get(key)],
                "applicable_restrictions": restrictions,
                "formal_rights_gate_changed": False,
            }
            for use in decision["uses"]:
                conflicts = [restriction for restriction in restrictions if use in restriction["uses"]]
                item["use_status"][use] = "blocked_explicit_use_restriction" if conflicts else "allowed_user_declared_open_A11"

    def _load_auxiliary_fonts(self) -> None:
        inventory_relative = "data/processed/visual_features_v1/asset_inventory.csv"
        inventory = self.safe_path(inventory_relative)
        records = {}
        if inventory.is_file():
            self.manifest_hashes[inventory_relative] = sha256_file(inventory)
            with inventory.open(encoding="utf-8", newline="") as source:
                records = {row["file_path"]: row for row in csv.DictReader(source)}
        directory = self.safe_path("data/assets/fonts")
        files = {item.relative_to(self.root).as_posix() for item in directory.iterdir() if item.suffix.lower() in {".ttf", ".otf"}} if directory.is_dir() else set()
        for relative in sorted(files | records.keys()):
            font_path = self.safe_path(relative)
            record = records.get(relative)
            exists = font_path.is_file()
            current_hash = sha256_file(font_path) if exists else None
            gaps = []
            uses = self._uses()
            uses["model_input"] = "not_applicable_font_binary"
            inventory_verified = bool(record and exists and current_hash == record["sha256"])
            if not record:
                gaps.append("NO_MATCHED_EXISTING_FONT_INVENTORY_RECORD")
            elif not inventory_verified:
                gaps.append("FONT_INVENTORY_FILE_MISSING_OR_CHANGED")
            if inventory_verified:
                license_path = self.safe_path(record["license_text_path"])
                license_verified = license_path.is_file() and sha256_file(license_path) == record["license_text_sha256"]
                if license_verified:
                    self.manifest_hashes[record["license_text_path"]] = record["license_text_sha256"]
                if license_verified and record["license_id"] == "OFL-1.1":
                    uses["local_analysis"] = "allowed_existing_inventory_OFL_1.1"
                else:
                    gaps.append("FONT_LICENSE_RECORD_NOT_VERIFIED")
            material_id = record["font_id"] if record else stable_id("font", {"path": relative})
            self.items[material_id] = {
                "material_id": material_id, "kind": "font_file", "candidate": None,
                "source": {"title": record["family_name"] if record else font_path.stem, "url": record["source_uri"] if record else None},
                "rights_evidence": [record] if record else [], "work_id": material_id,
                "representations": {"original": {"path": relative, "exists": exists, "sha256": current_hash, "byte_size": font_path.stat().st_size if exists else None}},
                "use_status": uses, "gaps": gaps,
                "auxiliary_font_inventory": {"path": inventory_relative, "record": record, "file_hash_verified_against_inventory": inventory_verified},
            }

    def _link_font_samples(self) -> None:
        renderer_relative = f"{PACK}/标准化流程/render_font_samples.py"
        renderer = self.safe_path(renderer_relative)
        samples = None
        for node in ast.parse(renderer.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SAMPLES" for target in node.targets):
                samples = ast.literal_eval(node.value)
        if not isinstance(samples, dict):
            raise CatalogError("FONT_SAMPLE_CONTENT_MAPPING_MISSING")
        fonts = {}
        for item in self.items.values():
            candidate = item["candidate"]
            if candidate and candidate.get("font_metadata"):
                font_path = Path(candidate["asset_ref"]["path"])
                fonts.setdefault((font_path.parent.name, font_path.stem), []).append(item)
        for item in self.items.values():
            if item["kind"] != "existing_font_sample":
                continue
            original = Path(item["representations"]["original"]["path"])
            matches = fonts.get((original.parent.name, original.stem), [])
            if len(matches) != 1:
                continue
            font_item = matches[0]
            font_path = resolve_workspace_asset(self.root, font_item["candidate"]["asset_ref"])
            content = samples[original.parent.name]
            with TTFont(font_path) as font:
                license_texts = sorted({record.toUnicode() for record in font["name"].names if record.nameID in {13, 14}})
                cmap = font.getBestCmap()
                missing = sorted({character for character in content if not character.isspace() and ord(character) not in cmap})
            ofl = any("SIL Open Font License" in text and "1.1" in text for text in license_texts)
            item["font_asset_id"] = font_item["material_id"]
            item["work_id"] = font_item["material_id"]
            item["source"] = font_item["source"]
            item["rights_evidence"] = font_item["rights_evidence"]
            item["sample_provenance"] = {
                "mapping": "renderer_group_and_stem_rule",
                "renderer_path": renderer_relative,
                "renderer_sha256": sha256_file(renderer),
                "font_ref": font_item["candidate"]["asset_ref"],
                "content": content,
                "script_group": original.parent.name,
                "missing_characters": missing,
                "embedded_license": license_texts,
                "historical_render_environment": "unknown",
            }
            item["gaps"] = ["HISTORICAL_RENDER_ENVIRONMENT_UNKNOWN"]
            if missing:
                item["gaps"].append("SAMPLE_FONT_MISSING_CHARACTERS")
            if ofl:
                item["use_status"]["local_analysis"] = "allowed_embedded_OFL_1.1"
                item["use_status"]["model_input"] = "allowed_embedded_OFL_1.1"
            if missing:
                item["use_status"]["study_eligibility"] = "blocked_missing_characters"
            else:
                item["use_status"]["study_eligibility"] = "existing_sample_instance_only"

    @staticmethod
    def _uses() -> dict[str, str]:
        return {
            "local_inventory_qc": "allowed_A9",
            "local_analysis": "needs_use_evidence",
            "model_input": "needs_use_evidence",
            "redistribution": "not_authorized",
        }

    def search(self, query: str = "", kind: str = "", award: str = "") -> list[dict[str, Any]]:
        result = []
        for item in self.items.values():
            if kind and item["kind"] != kind:
                continue
            candidate = item["candidate"] or {}
            if award and (candidate.get("award_context") or {}).get("award") != award:
                continue
            if query.casefold() not in json.dumps(item, ensure_ascii=False).casefold():
                continue
            result.append(item)
        return result

    def summary(self) -> dict[str, Any]:
        candidates = [item["candidate"] for item in self.items.values() if item["candidate"]]
        images = [item for item in candidates if item["candidate_kind"] == "ecological_award_image"]
        return {
            "material_root": str(self.root),
            "total": len(self.items),
            "repository_candidates": len(candidates),
            "auxiliary_font_files": sum("auxiliary_font_inventory" in item for item in self.items.values()),
            "kinds": dict(Counter(item["kind"] for item in self.items.values())),
            "awards": dict(Counter(item["award_context"]["award"] for item in images)),
            "unique_image_hashes": len({item["asset_ref"]["sha256"] for item in images}),
            "unique_works": len({item["work_id"] for item in images}),
            "standardized_matched": sum("standardized" in item["representations"] for item in self.items.values()),
            "missing_files": [
                {"material_id": item["material_id"], "path": representation["path"]}
                for item in self.items.values()
                for representation in item["representations"].values()
                if not representation["exists"]
            ],
            "unmatched_transforms": self.unmatched,
            "manifest_hashes": self.manifest_hashes,
        }

    def image_path(self, material_id: str, representation: str) -> Path:
        item = self.items[material_id]
        if item["kind"] in {"controlled_font_sample", "paired_design_board"}:
            selected = item["representations"][representation]
            image_path = (self.generated_root / selected["path"]).resolve()
            if not image_path.is_relative_to(self.generated_root) or sha256_file(image_path) != selected["sha256"]:
                raise CatalogError("GENERATED_SAMPLE_CHANGED_OR_OUTSIDE_ROOT")
            return image_path
        selected = item["representations"][representation]
        original = item["representations"]["original"]
        if original.get("sha256"):
            resolve_workspace_asset(self.root, original)
        if representation == "standardized":
            source = self.safe_path(original["path"])
            digest = hashlib.sha1(source.read_bytes()).hexdigest()
            if not digest.startswith(selected["transform"]["src_sha1"]):
                raise CatalogError("MATERIAL_TRANSFORM_SOURCE_CHANGED")
            if sha256_file(self.safe_path(selected["transform_manifest"])) != selected["transform_manifest_sha256"]:
                raise CatalogError("MATERIAL_TRANSFORM_MANIFEST_CHANGED")
        image_path = self.safe_path(selected["path"])
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise CatalogError("MATERIAL_NOT_VIEWABLE_IMAGE")
        if not image_path.is_file():
            raise CatalogError("MATERIAL_IMAGE_MISSING")
        return image_path

    def attach_generated_samples(self, directory: Path) -> None:
        self.generated_root = directory.resolve()
        if not directory.is_dir():
            return
        for manifest in sorted(directory.glob("sample_*.json")):
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if item.get("kind") not in {"controlled_font_sample", "paired_design_board"} or manifest.stem != item.get("material_id"):
                raise CatalogError("GENERATED_SAMPLE_MANIFEST_INVALID")
            self.items[item["material_id"]] = item
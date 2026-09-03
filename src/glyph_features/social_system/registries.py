"""Runtime loading and immutable snapshots for social-narrative registries."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs" / "social_narrative_v0.yaml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _registry_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("registry path is missing from protocol config")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"registry file is unavailable: {value}")
    return path


def load_registry_snapshot(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    registries = config.get("registries") if isinstance(config, dict) else None
    if not isinstance(registries, dict):
        raise ValueError("protocol config has no registries section")
    object_map_path = _registry_path(registries.get("object_map"))
    codebook_path = _registry_path(registries.get("codebook"))
    object_rows = _rows(object_map_path)
    codebook_rows = _rows(codebook_path)

    object_versions = {row.get("version", "").strip() for row in object_rows}
    codebook_versions = {row.get("version", "").strip() for row in codebook_rows}
    if len(object_versions) != 1 or not next(iter(object_versions), ""):
        raise ValueError("object map must declare exactly one non-empty version")
    if len(codebook_versions) != 1 or not next(iter(codebook_versions), ""):
        raise ValueError("codebook must declare exactly one non-empty version")

    object_type_codes = {
        row["code"].strip()
        for row in codebook_rows
        if row.get("code_type", "").strip() == "object_type" and row.get("code", "").strip()
    }
    objects = []
    seen_objects: set[tuple[str, str]] = set()
    for row in object_rows:
        if row.get("active", "").strip().casefold() not in {"true", "1", "yes"}:
            continue
        object_type = row.get("object_type", "").strip()
        canonical_label = row.get("canonical_label", "").strip()
        key = (object_type, canonical_label)
        if not object_type or not canonical_label or object_type not in object_type_codes:
            raise ValueError(f"object map contains an invalid active object: {key}")
        if key in seen_objects:
            raise ValueError(f"object map contains a duplicate active object: {key}")
        seen_objects.add(key)
        objects.append({
            "object_type": object_type,
            "canonical_label": canonical_label,
            "aliases": [
                value.strip() for value in row.get("aliases", "").split("|") if value.strip()
            ],
        })

    codes: dict[str, list[str]] = {}
    for row in codebook_rows:
        code_type = row.get("code_type", "").strip()
        code = row.get("code", "").strip()
        if code_type and code:
            codes.setdefault(code_type, []).append(code)
    for values in codes.values():
        values.sort()
    code_options = [
        {
            "code_type": row.get("code_type", "").strip(),
            "code": row.get("code", "").strip(),
            "display_zh": row.get("display_zh", "").strip(),
        }
        for row in codebook_rows
        if row.get("code_type", "").strip() and row.get("code", "").strip()
    ]
    objects.sort(key=lambda row: (row["object_type"], row["canonical_label"]))

    return {
        "object_map_path": str(object_map_path.relative_to(ROOT)),
        "object_map_version": next(iter(object_versions)),
        "object_map_sha256": _sha256(object_map_path),
        "codebook_path": str(codebook_path.relative_to(ROOT)),
        "codebook_version": next(iter(codebook_versions)),
        "codebook_sha256": _sha256(codebook_path),
        "objects": objects,
        "codes": codes,
        "code_options": code_options,
    }


def validate_registered_object(
    snapshot: dict[str, Any],
    object_type: str,
    object_label: str,
) -> None:
    registered = {
        (row.get("object_type"), row.get("canonical_label"))
        for row in snapshot.get("objects") or []
        if isinstance(row, dict)
    }
    if (object_type, object_label) not in registered:
        raise ValueError(f"未登记对象代码：{object_type}/{object_label}")


def validate_registered_terms(snapshot: dict[str, Any], terms: list[str]) -> None:
    allowed = set((snapshot.get("codes") or {}).get("aesthetic_term") or [])
    unknown = sorted(set(terms) - allowed)
    if unknown:
        raise ValueError("未登记审美术语：" + ", ".join(unknown))
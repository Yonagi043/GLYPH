"""Load and validate the versioned visual feature definition registry."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


SUPPORTED_SKELETON_ALGORITHM = "skimage.morphology.skeletonize"
SUPPORTED_SYMMETRY_ALIGNMENT = "representation_canvas"


class RegistryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


@dataclass(frozen=True)
class FeatureRegistry:
    """Validated registry data with convenient immutable code projections."""

    payload: dict[str, Any]

    @property
    def version(self) -> str:
        return str(self.payload["registry_version"])

    @property
    def definitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.payload["features"])

    @property
    def feature_codes(self) -> tuple[str, ...]:
        return tuple(item["feature_code"] for item in self.definitions)

    @property
    def active_definitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(item for item in self.definitions if item["status"] != "deprecated")

    @property
    def active_feature_codes(self) -> tuple[str, ...]:
        return tuple(item["feature_code"] for item in self.active_definitions)

    @property
    def dimension_codes(self) -> set[str]:
        return {item["code"] for item in self.payload["dimensions"]}

    @property
    def construct_codes(self) -> set[str]:
        return {item["code"] for item in self.payload["constructs"]}


def load_registry(config_path: str | Path, schema_root: str | Path) -> FeatureRegistry:
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    defaults = payload.get("algorithm_defaults")
    supported_enums = {
        "component_connectivity": (4, 8),
        "hole_connectivity": (4, 8),
        "skeleton_algorithm": (SUPPORTED_SKELETON_ALGORITHM,),
        "symmetry_alignment": (SUPPORTED_SYMMETRY_ALIGNMENT,),
    }
    if isinstance(defaults, dict):
        for field, supported in supported_enums.items():
            if field in defaults and defaults[field] not in supported:
                raise RegistryError(
                    "ALGORITHM_CONFIG_UNSUPPORTED",
                    f"unsupported {field}: {defaults[field]!r}",
                )
    schema_path = Path(schema_root) / "visual_feature_definition.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        detail = "; ".join(f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors)
        raise ValueError(f"invalid visual feature registry: {detail}")

    registry = FeatureRegistry(payload)
    _require_unique("dimension", [item["code"] for item in payload["dimensions"]])
    _require_unique("construct", [item["code"] for item in payload["constructs"]])
    _require_unique("feature", list(registry.feature_codes))
    if canonical_sha256(payload["algorithm_defaults"]) != payload["algorithm_config_sha256"]:
        raise ValueError("algorithm_config_sha256 does not match algorithm_defaults")
    for definition in registry.definitions:
        dimensions = {definition["dimensions"]["primary"], *definition["dimensions"]["secondary"]}
        unknown_dimensions = dimensions - registry.dimension_codes
        if unknown_dimensions:
            raise ValueError(f"{definition['feature_code']} references unknown dimensions: {sorted(unknown_dimensions)}")
        mapped_constructs = {mapping["construct_code"] for mapping in definition["construct_mappings"]}
        unknown_constructs = mapped_constructs - registry.construct_codes
        if unknown_constructs:
            raise ValueError(f"{definition['feature_code']} references unknown constructs: {sorted(unknown_constructs)}")
        if definition["algorithm"]["default_config_sha256"] != payload["algorithm_config_sha256"]:
            raise ValueError(f"{definition['feature_code']} has a stale algorithm config hash")
    if any("score" in code for code in registry.feature_codes):
        raise ValueError("canonical feature codes cannot publish uncalibrated scores")
    return registry


def _require_unique(label: str, values: list[str]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label} codes: {duplicates}")
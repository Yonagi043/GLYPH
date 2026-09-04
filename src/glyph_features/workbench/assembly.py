"""Build a pointer-only cross-module graph from validated reference handoffs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from glyph_features.asset_system.catalog import stable_id

from .catalog import Catalog, CatalogError


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CatalogError(f"REFERENCE_OBJECT_REQUIRED:{path.name}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise CatalogError(f"REFERENCE_OBJECT_REQUIRED:{path.name}")
    return rows


def _artifact_pointer(
    module_id: str,
    output: dict[str, Any],
    handoff_id: str,
) -> dict[str, Any]:
    classification = (
        output.get("privacy_level")
        or output.get("data_classification")
        or output.get("license_tier")
        or "unspecified_metadata"
    )
    return {
        "module_id": module_id,
        "logical_type": output["logical_type"],
        "path": output["path"],
        "sha256": output["sha256"],
        "schema_version": output.get("schema_version"),
        "data_classification": classification,
        "privacy_level": output.get("privacy_level"),
        "rights_tier": output.get("rights_tier") or output.get("license_tier"),
        "record_count": output.get("record_count"),
        "validation_schema": output.get("validation_schema"),
        "source_handoff_id": handoff_id,
    }


def _register_handoff_artifacts(
    catalog: Catalog,
    root: Path,
    results: Iterable[dict[str, Any]],
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for result in results:
        if result.get("compatible") is not True:
            continue
        handoff_id = catalog.register_handoff(result)
        manifest_path = root / result["manifest_path"]
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest_digest != result["manifest_sha256"]:
            raise CatalogError("HANDOFF_CHANGED_AFTER_VALIDATION")
        manifest = _read_json(manifest_path)
        for output in manifest.get("outputs") or []:
            if not isinstance(output, dict) or not {
                "logical_type",
                "path",
                "sha256",
            }.issubset(output):
                raise CatalogError("HANDOFF_OUTPUT_POINTER_INVALID")
            artifact_id = catalog.register_artifact(
                _artifact_pointer(result["module_id"], output, handoff_id)
            )
            artifacts[output["path"]] = artifact_id
    return artifacts


def _add_link(
    catalog: Catalog,
    *,
    source_module: str,
    source_type: str,
    source_id: str,
    target_module: str,
    target_type: str,
    target_id: str,
    relation: str,
    evidence_artifact_id: str,
    cluster_id: str | None = None,
    analysis_boundary: str | None = None,
) -> str:
    return catalog.register_entity_link(
        {
            "source_module": source_module,
            "source_type": source_type,
            "source_id": source_id,
            "target_module": target_module,
            "target_type": target_type,
            "target_id": target_id,
            "relation": relation,
            "evidence_artifact_id": evidence_artifact_id,
            "cluster_id": cluster_id,
            "analysis_boundary": analysis_boundary,
        }
    )


def _asset_links(catalog: Catalog, root: Path, artifacts: dict[str, str]) -> None:
    candidate_path = "data/fixtures/asset_system/reference_handoff_v1/fixture/asset_candidates.jsonl"
    stimulus_path = "data/fixtures/asset_system/reference_handoff_v1/fixture/stimuli.jsonl"
    for candidate in _read_jsonl(root / candidate_path):
        _add_link(
            catalog,
            source_module="assets",
            source_type="source",
            source_id=candidate["source_id"],
            target_module="assets",
            target_type="asset",
            target_id=candidate["asset_id"],
            relation="source_for_asset",
            evidence_artifact_id=artifacts[candidate_path],
            cluster_id=candidate.get("work_id"),
        )
        if candidate.get("parent_asset_id"):
            _add_link(
                catalog,
                source_module="assets",
                source_type="asset",
                source_id=candidate["parent_asset_id"],
                target_module="assets",
                target_type="asset",
                target_id=candidate["asset_id"],
                relation="derived_representation",
                evidence_artifact_id=artifacts[candidate_path],
                cluster_id=candidate.get("work_id"),
            )
    for stimulus in _read_jsonl(root / stimulus_path):
        _add_link(
            catalog,
            source_module="assets",
            source_type="source",
            source_id=stimulus["source_id"],
            target_module="assets",
            target_type="stimulus",
            target_id=stimulus["stimulus_id"],
            relation="source_for_stimulus",
            evidence_artifact_id=artifacts[stimulus_path],
        )
        for representation in stimulus["representations"].values():
            _add_link(
                catalog,
                source_module="assets",
                source_type="asset",
                source_id=representation["asset_id"],
                target_module="assets",
                target_type="stimulus",
                target_id=stimulus["stimulus_id"],
                relation="representation_for_stimulus",
                evidence_artifact_id=artifacts[stimulus_path],
            )


def _vision_links(catalog: Catalog, root: Path, artifacts: dict[str, str]) -> None:
    path = "data/fixtures/visual_measurements/reference_run_v2/measurements.jsonl"
    for measurement in _read_jsonl(root / path):
        for source_type, source_id in (
            ("stimulus", measurement["stimulus_id"]),
            ("asset", measurement["asset_id"]),
        ):
            _add_link(
                catalog,
                source_module="assets",
                source_type=source_type,
                source_id=source_id,
                target_module="vision",
                target_type="visual_measurement",
                target_id=measurement["measurement_id"],
                relation="measured_as",
                evidence_artifact_id=artifacts[path],
                cluster_id=measurement["feature_record_id"],
            )


def _experiment_links(catalog: Catalog, root: Path, artifacts: dict[str, str]) -> None:
    catalog_path = "data/fixtures/experiment_system/reference_v1/records/stimulus_catalog.json"
    rating_path = "data/fixtures/experiment_system/reference_v1/records/ratings.jsonl"
    for stimulus in _read_json(root / catalog_path)["items"]:
        _add_link(
            catalog,
            source_module="assets",
            source_type="stimulus",
            source_id=stimulus["source_stimulus_id"],
            target_module="experiment",
            target_type="experiment_stimulus",
            target_id=stimulus["stimulus_id"],
            relation="source_stimulus_for",
            evidence_artifact_id=artifacts[catalog_path],
            cluster_id=stimulus["work_id"],
        )
    for rating in _read_jsonl(root / rating_path):
        for source_type, source_id, relation in (
            ("experiment_stimulus", rating["stimulus_id"], "rated_in"),
            ("participant", rating["participant_id"], "provided_rating"),
        ):
            _add_link(
                catalog,
                source_module="experiment",
                source_type=source_type,
                source_id=source_id,
                target_module="experiment",
                target_type="rating",
                target_id=rating["rating_id"],
                relation=relation,
                evidence_artifact_id=artifacts[rating_path],
                cluster_id=rating["presentation_id"],
                analysis_boundary="excluded_fixture_rating"
                if rating["quality"]["exclude_from_analysis"]
                else "synthetic_engineering_only",
            )


def _han_links(catalog: Catalog, root: Path, artifacts: dict[str, str]) -> None:
    candidate_path = (
        "data/fixtures/han_style_system/reference_run_v1/candidate_bundle/stimulus_candidates.jsonl"
    )
    adapter_path = "data/fixtures/han_style_system/reference_run_v1/candidate_bundle/adapters.jsonl"
    for candidate in _read_jsonl(root / candidate_path):
        for target_type, target_id, relation in (
            ("style", candidate["style_id"], "candidate_has_style"),
            ("content_set", candidate["content_set_id"], "candidate_uses_content_set"),
        ):
            _add_link(
                catalog,
                source_module="han_style",
                source_type="stimulus_candidate",
                source_id=candidate["candidate_id"],
                target_module="han_style",
                target_type=target_type,
                target_id=target_id,
                relation=relation,
                evidence_artifact_id=artifacts[candidate_path],
                cluster_id=(candidate.get("exemplar_cluster_ids") or [None])[0],
                analysis_boundary=candidate["inference_scope"]["scope"],
            )
        for asset_id in candidate["representation_asset_ids"].values():
            _add_link(
                catalog,
                source_module="assets",
                source_type="asset",
                source_id=asset_id,
                target_module="han_style",
                target_type="stimulus_candidate",
                target_id=candidate["candidate_id"],
                relation="representation_for_han_candidate",
                evidence_artifact_id=artifacts[candidate_path],
                cluster_id=(candidate.get("exemplar_cluster_ids") or [None])[0],
                analysis_boundary=candidate["inference_scope"]["scope"],
            )

    for adapter in _read_jsonl(root / adapter_path):
        payload = adapter.get("payload") or {}
        if (
            adapter.get("target_system") != "WP2"
            or adapter.get("status") != "fixture_only"
            or payload.get("existing_registry_match") is not True
        ):
            continue
        object_id = stable_id(
            "object",
            {
                "object_type": payload["object_type"],
                "canonical_label": payload["canonical_label"],
                "registry_version": "0.1.0",
            },
        )
        _add_link(
            catalog,
            source_module="han_style",
            source_type="style",
            source_id=adapter["style_id"],
            target_module="social",
            target_type="narrative_object",
            target_id=object_id,
            relation="hypothesis_context_for",
            evidence_artifact_id=artifacts[adapter_path],
            analysis_boundary="context_only_not_participant_exposure",
        )


def _register_social_registry(catalog: Catalog, root: Path) -> str:
    path = "data/templates/social_object_map.csv"
    with (root / path).open(encoding="utf-8", newline="") as handle:
        versions = {row["version"] for row in csv.DictReader(handle)}
    if versions != {"0.1.0"}:
        raise CatalogError("SOCIAL_OBJECT_MAP_VERSION_AMBIGUOUS")
    return catalog.register_artifact(
        {
            "module_id": "social",
            "logical_type": "social_object_map",
            "path": path,
            "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
            "schema_version": "0.1.0",
            "data_classification": "public_code_or_schema",
            "record_count": 6,
        }
    )


def import_reference_graph(
    catalog: Catalog,
    workspace_root: str | Path,
    handoff_results: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Import validated pointers and explicit stable-ID links, idempotently."""

    root = Path(workspace_root).resolve()
    results = list(handoff_results)
    if not results or any(result.get("compatible") is not True for result in results):
        raise CatalogError("REFERENCE_GRAPH_REQUIRES_COMPATIBLE_HANDOFFS")
    artifacts = _register_handoff_artifacts(catalog, root, results)
    _register_social_registry(catalog, root)
    _asset_links(catalog, root, artifacts)
    _vision_links(catalog, root, artifacts)
    _experiment_links(catalog, root, artifacts)
    _han_links(catalog, root, artifacts)
    return {
        "artifact_count": len(catalog.rows("artifacts")),
        "entity_link_count": len(catalog.rows("entity_links")),
        "handoff_count": len(catalog.rows("handoff_imports")),
        "participant_exposure_links": sum(
            1
            for link in catalog.rows("entity_links")
            if link["relation"] == "participant_exposed_to_narrative"
        ),
    }
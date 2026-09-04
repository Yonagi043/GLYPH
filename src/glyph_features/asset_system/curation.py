"""Human review queues and immutable ecological stimulus freezing."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Iterable

from . import PROTOCOL_VERSION
from .catalog import AssetSystemError, canonical_json, stable_id
from .qc import target_geometry_bbox
from .rights import ELIGIBLE_CONTENT_CLASSES, freeze_blockers, select_rights_evidence


EXCLUSION_CODES = {
    "RIGHTS_BLOCKED", "SOURCE_MISSING", "SOURCE_ROW_INVALID", "DECODE_FAILED",
    "PIXEL_LIMIT_EXCEEDED", "DUPLICATE_EXACT", "DUPLICATE_NEAR", "NON_WINNER_ASSET",
    "TARGET_AMBIGUOUS", "CONTENT_NOT_ELIGIBLE", "MANUAL_REVIEW_REQUIRED",
}


def build_review_queue(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in sorted(candidates, key=lambda item: item["asset_id"]):
        if record["asset_role"] != "original" or record["curation_status"] == "passed":
            continue
        metadata = record.get("pixel_metadata") or {}
        rows.append(
            {
                "asset_id": record["asset_id"],
                "asset_path": record["asset_ref"]["path"],
                "source_id": record["source_id"],
                "work_id": record.get("work_id") or "",
                "candidate_kind": record["candidate_kind"],
                "rights_tier": record["rights_tier"],
                "automated_qc_status": record["automated_qc"]["status"],
                "automated_suggestion": record["classification"]["automated_suggestion"] or "",
                "width_px": metadata.get("width_px", ""),
                "height_px": metadata.get("height_px", ""),
                "human_decision": "",
                "curation_status": "",
                "target_bbox_json": "",
                "target_polygon_json": "",
                "reviewer_id": "",
                "reviewed_at": "",
                "exclusion_codes": "",
                "notes": "",
            }
        )
    return rows


def apply_curation_decisions(
    candidates: Iterable[dict[str, Any]],
    decisions: Iterable[dict[str, str]],
) -> list[dict[str, Any]]:
    records = {record["asset_id"]: copy.deepcopy(record) for record in candidates}
    seen: set[str] = set()
    for decision in decisions:
        asset_id = decision.get("asset_id", "").strip()
        if asset_id in seen:
            raise AssetSystemError("CURATION_DECISION_DUPLICATE", asset_id)
        seen.add(asset_id)
        if asset_id not in records:
            raise AssetSystemError("CURATION_ASSET_UNKNOWN", asset_id)
        reviewer_id = decision.get("reviewer_id", "").strip()
        reviewed_at = decision.get("reviewed_at", "").strip()
        status = decision.get("curation_status", "").strip()
        human_decision = decision.get("human_decision", "").strip()
        if not reviewer_id or not reviewed_at:
            raise AssetSystemError("CURATION_REVIEWER_REQUIRED", f"human reviewer and timestamp required: {asset_id}")
        try:
            parsed_timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise AssetSystemError("CURATION_TIMESTAMP_INVALID", f"{asset_id}: {reviewed_at}") from error
        if parsed_timestamp.utcoffset() != timedelta(0):
            raise AssetSystemError("CURATION_TIMESTAMP_NOT_UTC", f"review timestamp must be UTC: {asset_id}")
        if status not in {"passed", "excluded", "needs_review"}:
            raise AssetSystemError("CURATION_STATUS_INVALID", f"{asset_id}: {status}")
        if human_decision not in ELIGIBLE_CONTENT_CLASSES | {
            "award_header_or_navigation_asset",
            "call_for_entries_or_non_winner",
            "duplicate_exact",
            "duplicate_near",
            "unreadable_or_corrupt",
            "rights_blocked",
            "uncertain",
        }:
            raise AssetSystemError("CURATION_CLASS_INVALID", f"invalid human content class for {asset_id}: {human_decision}")
        bbox = None
        bbox_raw = decision.get("target_bbox_json", "").strip()
        polygon_raw = decision.get("target_polygon_json", "").strip()
        if bbox_raw and polygon_raw:
            raise AssetSystemError("CURATION_GEOMETRY_CONFLICT", asset_id)
        try:
            if bbox_raw:
                bbox = json.loads(bbox_raw)
            polygon = json.loads(polygon_raw) if polygon_raw else None
        except json.JSONDecodeError as error:
            raise AssetSystemError("CURATION_GEOMETRY_INVALID", f"{asset_id}: invalid JSON") from error
        geometry_type = "bbox" if bbox is not None else "polygon" if polygon is not None else None
        coordinates = bbox if bbox is not None else polygon
        if geometry_type is not None:
            try:
                target_geometry_bbox({"geometry_type": geometry_type, "coordinates": coordinates})
            except ValueError as error:
                raise AssetSystemError("CURATION_GEOMETRY_INVALID", f"invalid target geometry for {asset_id}: {error}") from error
        exclusions = sorted({value for value in decision.get("exclusion_codes", "").split("|") if value})
        invalid_exclusions = set(exclusions) - EXCLUSION_CODES
        if invalid_exclusions:
            raise AssetSystemError(
                "CURATION_EXCLUSION_CODE_INVALID",
                f"invalid exclusion code for {asset_id}: {','.join(sorted(invalid_exclusions))}",
            )
        if status == "passed" and (human_decision not in ELIGIBLE_CONTENT_CLASSES or geometry_type is None):
            raise AssetSystemError("CURATION_PASSED_REQUIREMENTS", asset_id)
        if status == "passed" and exclusions:
            raise AssetSystemError("CURATION_PASSED_HAS_EXCLUSIONS", asset_id)
        if status == "excluded" and not exclusions:
            raise AssetSystemError("CURATION_EXCLUDED_NO_REASON", asset_id)

        record = records[asset_id]
        record["classification"]["human_decision"] = human_decision
        record["target_geometry"] = (
            {
                "geometry_type": geometry_type,
                "coordinates": coordinates,
                "confirmed_by": reviewer_id,
                "confirmed_at": reviewed_at,
            }
            if geometry_type is not None
            else None
        )
        record["curation_status"] = status
        record["exclusion_codes"] = exclusions
        record["review"] = {
            "method": "human",
            "reviewer_id": reviewer_id,
            "reviewed_at": reviewed_at,
            "decision": status,
            "notes": decision.get("notes", "").strip() or None,
        }
    return [records[key] for key in sorted(records)]


def freeze_ecological_stimulus(
    original: dict[str, Any],
    derived: Iterable[dict[str, Any]],
    *,
    created_at: str,
    fixture_only: bool,
    rights_evidence: dict[str, Any],
    recommended_viewport_px: tuple[int, int] = (512, 512),
) -> dict[str, Any]:
    blockers = freeze_blockers(original, fixture_only=fixture_only)
    if blockers:
        raise ValueError("freeze blocked: " + ",".join(blockers))
    if not original.get("work_id"):
        raise ValueError("freeze blocked: ASSET_WORK_ID_REQUIRED")
    intended_use = "engineering_fixture" if fixture_only else "research_stimulus_local"
    verified_rights = select_rights_evidence(original, [rights_evidence], intended_use=intended_use)
    by_role: dict[str, dict[str, Any]] = {}
    for record in derived:
        role = record["asset_role"]
        if role in by_role:
            raise ValueError(f"freeze blocked: duplicate representation {role}")
        if record.get("parent_asset_id") != original["asset_id"]:
            raise ValueError(f"freeze blocked: invalid parent for {role}")
        if (record.get("transform") or {}).get("parent_sha256") != original["asset_ref"]["sha256"]:
            raise ValueError(f"freeze blocked: parent hash mismatch for {role}")
        by_role[role] = record
    missing = {"A_layout", "B_shape", "mask"} - set(by_role)
    if missing:
        raise ValueError("freeze blocked: missing representations " + ",".join(sorted(missing)))
    if fixture_only and "C_ink" not in by_role:
        raise ValueError("freeze blocked: fixture must exercise C_ink")

    presentation = {
        "award_metadata_hidden": True,
        "source_metadata_hidden": True,
        "recommended_viewport_px": list(recommended_viewport_px),
        "background_rgba": [255, 255, 255, 255],
    }
    representation_refs = {
        "A_layout": _representation_ref(by_role["A_layout"]),
        "B_shape": _representation_ref(by_role["B_shape"]),
        "B_shape_mask": _representation_ref(by_role["mask"]),
        "C_ink": _representation_ref(by_role["C_ink"]) if "C_ink" in by_role else None,
    }
    content_classification = original["classification"]["fixture_decision" if fixture_only else "human_decision"]
    condition = {
        "protocol_version": PROTOCOL_VERSION,
        "original_asset_id": original["asset_id"],
        "representations": representation_refs,
        "presentation": presentation,
        "content_classification": content_classification,
        "rights_evidence_id": verified_rights["rights_evidence_id"],
        "intended_use": intended_use,
    }
    condition_sha256 = hashlib.sha256(canonical_json(condition)).hexdigest()
    return {
        "schema_version": "2.0.0",
        "stimulus_id": stable_id("stim_eco", condition, length=20),
        "stimulus_kind": "generated_fixture" if fixture_only else "ecological_image",
        "protocol_version": PROTOCOL_VERSION,
        "condition_sha256": condition_sha256,
        "source_id": original["source_id"],
        "work_id": original["work_id"],
        "original_asset_id": original["asset_id"],
        "representations": representation_refs,
        "research_lines": ["WP1_cross_cultural_perception", "WP3_cross_script_visual_form"],
        "semantic_status": "nonlinguistic",
        "content_classification": content_classification,
        "presentation": presentation,
        "rights_tier": original["rights_tier"],
        "rights_evidence_id": verified_rights["rights_evidence_id"],
        "intended_use": intended_use,
        "release_status": "fixture_only" if fixture_only else "research_local_only",
        "qc": {
            "status": "passed",
            "review_method": original["review"]["method"],
            "notes": "Generated test fixture; not evidence of human curation." if fixture_only else None,
        },
        "created_at": created_at,
    }


def _representation_ref(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": record["asset_id"],
        "asset_role": record["asset_role"],
        "asset_ref": copy.deepcopy(record["asset_ref"]),
        "transform_config_sha256": record["transform"]["config_sha256"],
    }

"""Mechanical freeze and release gates; legal interpretation remains human."""
from __future__ import annotations

import re
from typing import Any

from .catalog import AssetSystemError, stable_id


ELIGIBLE_CONTENT_CLASSES = {
    "isolated_wordmark_clean",
    "logo_lockup_with_symbol",
    "project_board_or_poster",
    "mockup_or_scene",
}

RIGHTS_USES = {
    "engineering_fixture",
    "metadata_audit",
    "public_redistribution",
    "research_stimulus_local",
}


def freeze_blockers(record: dict[str, Any], *, fixture_only: bool = False) -> list[str]:
    blockers: list[str] = []
    asset_ref = record.get("asset_ref") or {}
    if not re.fullmatch(r"[a-f0-9]{64}", str(asset_ref.get("sha256", ""))):
        blockers.append("ASSET_SHA256_INVALID")
    if record.get("rights_tier") not in {"open", "research_local_only"}:
        blockers.append("ASSET_RIGHTS_BLOCKED")
    if (record.get("automated_qc") or {}).get("status") != "passed":
        blockers.append("ASSET_QC_NOT_PASSED")
    if record.get("curation_status") != "passed":
        blockers.append("ASSET_CURATION_NOT_PASSED")
    classification = record.get("classification") or {}
    if record.get("exclusion_codes"):
        blockers.append("ASSET_HAS_EXCLUSIONS")

    review = record.get("review") or {}
    if fixture_only:
        if classification.get("fixture_decision") not in ELIGIBLE_CONTENT_CLASSES:
            blockers.append("FIXTURE_CLASSIFICATION_REQUIRED")
        if record.get("record_origin") != "generated_fixture":
            blockers.append("FIXTURE_ORIGIN_REQUIRED")
        if record.get("rights_tier") != "open":
            blockers.append("FIXTURE_OPEN_RIGHTS_REQUIRED")
        if review.get("method") != "fixture_protocol" or review.get("decision") != "passed":
            blockers.append("FIXTURE_PROTOCOL_REVIEW_REQUIRED")
    else:
        if classification.get("human_decision") not in ELIGIBLE_CONTENT_CLASSES:
            blockers.append("ASSET_HUMAN_CLASSIFICATION_REQUIRED")
        if (
            review.get("method") != "human"
            or review.get("decision") != "passed"
            or not review.get("reviewer_id")
            or not review.get("reviewed_at")
        ):
            blockers.append("ASSET_HUMAN_REVIEW_REQUIRED")
    return sorted(set(blockers))


def release_blockers(record: dict[str, Any]) -> list[str]:
    blockers = freeze_blockers(record)
    if record.get("rights_tier") != "open":
        blockers.append("RELEASE_REDISTRIBUTION_BLOCKED")
    if record.get("record_origin") == "generated_fixture":
        blockers.append("RELEASE_FIXTURE_ONLY")
    return sorted(set(blockers))


def select_rights_evidence(
    record: dict[str, Any],
    evidence_records: list[dict[str, Any]],
    *,
    intended_use: str,
) -> dict[str, Any]:
    if intended_use not in RIGHTS_USES:
        raise AssetSystemError("RIGHTS_USE_INVALID", intended_use)
    matches = [item for item in evidence_records if item.get("source_id") == record.get("source_id")]
    if not matches:
        raise AssetSystemError("RIGHTS_EVIDENCE_MISSING", str(record.get("source_id")))
    if len(matches) != 1:
        raise AssetSystemError("RIGHTS_EVIDENCE_CONFLICT", str(record.get("source_id")))
    evidence = matches[0]
    if evidence.get("rights_evidence_id") != _rights_evidence_id(evidence):
        raise AssetSystemError("RIGHTS_EVIDENCE_ID_MISMATCH", str(evidence.get("rights_evidence_id")))
    decision_status = evidence.get("decision_status")
    if decision_status != "passed":
        code = "RIGHTS_EVIDENCE_PENDING" if decision_status == "pending_human_review" else "RIGHTS_EVIDENCE_BLOCKED"
        raise AssetSystemError(code, str(evidence.get("rights_evidence_id")))
    if evidence.get("rights_tier") != record.get("rights_tier"):
        raise AssetSystemError("RIGHTS_TIER_MISMATCH", str(evidence.get("rights_evidence_id")))
    if intended_use not in evidence.get("permitted_uses", []):
        raise AssetSystemError("RIGHTS_USE_NOT_PERMITTED", intended_use)
    return evidence


def build_rights_evidence(sources: list[dict[str, Any]], *, checked_at: str, fixture_source_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sources:
        is_fixture = source["source_id"] == fixture_source_id
        is_font = source["source_type"] == "font_file"
        basis = "project_generated_cc0" if is_fixture else "internal_metadata_only" if is_font else "source_metadata_only"
        rights_tier = "open" if is_fixture else "blocked_unknown"
        decision_status = "passed" if is_fixture else "pending_human_review"
        permitted_uses = sorted(RIGHTS_USES) if is_fixture else ["metadata_audit"]
        record = {
            "schema_version": "2.0.0",
            "source_id": source["source_id"],
            "checked_at": checked_at,
            "checked_by": "asset_inventory_v1",
            "basis": basis,
            "license_status": "open" if is_fixture else "unknown",
            "rights_tier": rights_tier,
            "permitted_uses": permitted_uses,
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/" if is_fixture else None,
            "license_text_or_id": "CC0-1.0" if is_fixture else None,
            "redistribution_allowed": True if is_fixture else None,
            "page_snapshot": None,
            "decision_status": decision_status,
            "notes": (
                "Project-generated fixture declaration in data/fixtures/asset_system/README.md."
                if is_fixture
                else "No verified licence page snapshot; human rights review required."
            ),
        }
        record["rights_evidence_id"] = _rights_evidence_id(record)
        records.append(record)
    return sorted(records, key=lambda item: item["rights_evidence_id"])


def _rights_evidence_id(record: dict[str, Any]) -> str:
    content = {key: value for key, value in record.items() if key != "rights_evidence_id"}
    return stable_id("rights", content)

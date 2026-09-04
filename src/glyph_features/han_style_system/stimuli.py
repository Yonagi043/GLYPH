"""Build controlled candidates while preserving TASK-01 stimulus ownership."""
from __future__ import annotations

from collections import Counter
from typing import Any

from glyph_features.asset_system.catalog import stable_id, validate_record
from glyph_features.han_style_system.review import aggregate_reviews


CANDIDATE_LEVELS = {
    "historical_source": "historical_source_specimen",
    "expert_tracing": "expert_traced_shape",
    "digital_font": "digital_font_specimen",
    "generated_fixture": "generated_candidate",
}


def build_stimulus_candidates(
    glyph_records: list[dict[str, Any]],
    mapping_records: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    rights_evidence: list[dict[str, Any]],
    *,
    schema_path: str,
    render_profiles: list[str],
    minimum_independent_reviews: int,
    minimum_independent_exemplars: int,
    created_at: str,
) -> list[dict[str, Any]]:
    mappings_by_id = {record["mapping_id"]: record for record in mapping_records}
    review_summaries = aggregate_reviews(
        reviews,
        minimum_independent_reviews=minimum_independent_reviews,
    )
    rights_by_source: dict[str, list[dict[str, Any]]] = {}
    for evidence in rights_evidence:
        rights_by_source.setdefault(evidence["source_id"], []).append(evidence)
    eligible_clusters_by_style: dict[str, set[str]] = {}
    for glyph in glyph_records:
        summary = review_summaries.get(glyph["glyph_instance_id"], _empty_review_summary())
        if _formal_glyph_ready(glyph, summary, rights_by_source.get(glyph["source_id"], [])):
            eligible_clusters_by_style.setdefault(glyph["style_id"], set()).add(glyph["exemplar_cluster_id"])

    candidates: list[dict[str, Any]] = []
    for glyph in glyph_records:
        mapping = mappings_by_id[glyph["mapping_id"]]
        review_summary = review_summaries.get(glyph["glyph_instance_id"], _empty_review_summary())
        evidence = rights_by_source.get(glyph["source_id"], [])
        rights_summary = _rights_summary(glyph, evidence)
        independent_count = len(eligible_clusters_by_style.get(glyph["style_id"], set()))
        inference_scope = {
            "scope": "category_candidate" if independent_count >= minimum_independent_exemplars else "instance_level_only",
            "independent_exemplar_count": independent_count,
            "minimum_for_category": minimum_independent_exemplars,
            "blockers": [] if independent_count >= minimum_independent_exemplars else ["INSUFFICIENT_INDEPENDENT_EXEMPLARS"],
        }
        for render_profile in render_profiles:
            blockers = _freeze_blockers(glyph, mapping, review_summary, rights_summary)
            data_origin = "synthetic_fixture" if glyph["data_origin"] == "generated_fixture" else "source_record"
            release_status = "fixture_only" if data_origin == "synthetic_fixture" else (
                "eligible_for_task01_freeze" if not blockers else "blocked"
            )
            task01_status = "ready_for_request" if release_status == "eligible_for_task01_freeze" else "blocked"
            candidate = {
                "schema_version": "1.0.0",
                "candidate_id": stable_id(
                    "han_candidate",
                    {
                        "glyph_instance_id": glyph["glyph_instance_id"],
                        "content_set_id": mapping["content_set_id"],
                        "render_profile": render_profile,
                    },
                ),
                "data_origin": data_origin,
                "candidate_level": CANDIDATE_LEVELS[glyph["acquisition_type"]],
                "style_id": glyph["style_id"],
                "glyph_instance_ids": [glyph["glyph_instance_id"]],
                "content_set_id": mapping["content_set_id"],
                "work_ids": [glyph["work_id"]],
                "font_ids": [glyph["font_id"]] if glyph["font_id"] else [],
                "exemplar_cluster_ids": [glyph["exemplar_cluster_id"]],
                "render_profile": render_profile,
                "representation_asset_ids": {
                    key: glyph["representation_asset_ids"][key]
                    for key in ("A_layout", "B_shape", "B_shape_mask", "C_ink")
                },
                "label_conditions": ["blind", "contextual"],
                "review_summary": review_summary,
                "rights_summary": rights_summary,
                "mapping_status": mapping["mapping_status"],
                "inference_scope": inference_scope,
                "task01_freeze": {
                    "status": task01_status,
                    "blockers": blockers,
                    "requested_contract": "TASK-01 stimulus freeze",
                },
                "release_status": release_status,
                "stimulus_id": None,
                "created_at": created_at,
            }
            errors = validate_record(candidate, schema_path)
            if errors:
                raise ValueError("HAN_CANDIDATE_SCHEMA_INVALID: " + "; ".join(errors))
            candidates.append(candidate)
    return sorted(candidates, key=lambda record: record["candidate_id"])


def _empty_review_summary() -> dict[str, Any]:
    return {
        "package_ids": [],
        "synthetic_review_count": 0,
        "real_review_count": 0,
        "fixture_status": "blocked",
        "formal_status": "blocked",
        "decision_counts": {},
    }


def _rights_summary(glyph: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    matching = [
        item for item in evidence
        if item.get("decision_status") == "passed" and item.get("rights_tier") == glyph["rights_tier"]
    ]
    permitted_uses = sorted({use for item in matching for use in item.get("permitted_uses", [])})
    if glyph["data_origin"] == "generated_fixture" and "engineering_fixture" in permitted_uses:
        status = "fixture_only"
    elif "research_stimulus_local" in permitted_uses:
        status = "passed"
    else:
        status = "blocked"
    return {
        "status": status,
        "rights_tier": glyph["rights_tier"],
        "rights_evidence_ids": sorted(item["rights_evidence_id"] for item in matching),
        "permitted_uses": permitted_uses,
    }


def _freeze_blockers(
    glyph: dict[str, Any],
    mapping: dict[str, Any],
    review_summary: dict[str, Any],
    rights_summary: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if glyph["data_origin"] == "generated_fixture":
        blockers.extend(["SYNTHETIC_FIXTURE", "GLYPH_IDENTITY_SYNTHETIC"])
    if glyph["identity_status"] != "evidence_supported":
        blockers.append("GLYPH_IDENTITY_NOT_EVIDENCE_SUPPORTED")
    if glyph["attribution_status"] != "evidence_supported":
        blockers.append("STYLE_ATTRIBUTION_NOT_EVIDENCE_SUPPORTED")
    if glyph["structure_qc"]["status"] != "passed":
        blockers.append("STRUCTURE_QC_NOT_PASSED")
    if mapping["mapping_status"] != "evidence_supported":
        blockers.append("CHARACTER_MAPPING_NOT_EVIDENCE_SUPPORTED")
    if review_summary["formal_status"] != "passed":
        blockers.append("REAL_EXPERT_REVIEWS_REQUIRED")
    if rights_summary["status"] != "passed":
        blockers.append("FORMAL_RIGHTS_REQUIRED")
    return sorted(set(blockers))


def _formal_glyph_ready(
    glyph: dict[str, Any],
    review_summary: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> bool:
    rights = _rights_summary(glyph, evidence)
    return (
        glyph["data_origin"] == "source_record"
        and glyph["identity_status"] == "evidence_supported"
        and glyph["attribution_status"] == "evidence_supported"
        and glyph["structure_qc"]["status"] == "passed"
        and review_summary["formal_status"] == "passed"
        and rights["status"] == "passed"
    )

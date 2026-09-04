"""Build controlled candidates while preserving TASK-01 stimulus ownership."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import stable_id, validate_record
from glyph_features.han_style_system.claims import validate_claims
from glyph_features.han_style_system.glyphs import (
    load_content_sets,
    validate_character_mappings,
    validate_glyph_instances,
)
from glyph_features.han_style_system.ontology import validate_ontology
from glyph_features.han_style_system.review import (
    DEFAULT_ROLE_GROUPS,
    RUBRIC_DIMENSIONS,
    aggregate_reviews,
    validate_review_records,
)
from glyph_features.han_style_system.rights import load_trusted_rights_snapshot


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
    review_package_dir: str | Path | None = None,
    review_records_path: str | Path | None = None,
    task01_handoff_path: str | Path | None = None,
    rights_evidence_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    ontology_records: list[dict[str, Any]] | None = None,
    source_records: list[dict[str, Any]] | None = None,
    asset_records: list[dict[str, Any]] | None = None,
    claim_records: list[dict[str, Any]] | None = None,
    content_sets_path: str | Path | None = None,
    minimum_substantive_dimensions: int = 2,
    required_dimensions: tuple[str, ...] = RUBRIC_DIMENSIONS,
    required_role_groups: tuple[frozenset[str], ...] = DEFAULT_ROLE_GROUPS,
) -> list[dict[str, Any]]:
    root = Path(workspace_root).resolve() if workspace_root is not None else Path(schema_path).resolve().parent.parent
    contracts = Path(schema_path).resolve().parent
    review_inputs = (review_package_dir, review_records_path)
    if sum(value is not None for value in review_inputs) == 1:
        raise ValueError("HAN_REVIEW_TRUST_INPUT_INCOMPLETE")
    review_trusted = review_package_dir is not None and review_records_path is not None
    input_errors = [
        f"HAN_MAPPING_SCHEMA_INVALID record={index}: {message}"
        for index, record in enumerate(mapping_records, start=1)
        for message in validate_record(record, contracts / "han_character_mapping.schema.json")
    ]
    input_errors += [
        f"HAN_GLYPH_SCHEMA_INVALID record={index}: {message}"
        for index, record in enumerate(glyph_records, start=1)
        for message in validate_record(record, contracts / "han_glyph_instance.schema.json")
    ]
    input_errors += [
        f"HAN_RIGHTS_SCHEMA_INVALID record={index}: {message}"
        for index, record in enumerate(rights_evidence, start=1)
        for message in validate_record(record, contracts / "rights_evidence.schema.json")
    ]
    input_errors += validate_review_records(
        reviews,
        contracts / "expert_review.schema.json",
        package_dir=review_package_dir if review_trusted else None,
        review_records_path=review_records_path if review_trusted else None,
    )
    mapping_ids = [record.get("mapping_id") for record in mapping_records]
    glyph_ids = [record.get("glyph_instance_id") for record in glyph_records]
    if len(mapping_ids) != len(set(mapping_ids)):
        input_errors.append("HAN_MAPPING_ID_DUPLICATE")
    if len(glyph_ids) != len(set(glyph_ids)):
        input_errors.append("HAN_GLYPH_ID_DUPLICATE")
    known_mapping_ids = set(mapping_ids)
    input_errors += [
        f"HAN_GLYPH_MAPPING_UNKNOWN glyph_instance_id={record.get('glyph_instance_id')}"
        for record in glyph_records
        if record.get("mapping_id") not in known_mapping_ids
    ]
    if input_errors:
        raise ValueError("HAN_CANDIDATE_INPUT_INVALID: " + "; ".join(sorted(set(input_errors))))

    graph_inputs = (
        ontology_records,
        source_records,
        asset_records,
        claim_records,
        content_sets_path,
    )
    if 0 < sum(value is not None for value in graph_inputs) < len(graph_inputs):
        raise ValueError("HAN_CANDIDATE_GRAPH_INPUT_INCOMPLETE")
    input_graph_verified = all(value is not None for value in graph_inputs)
    if input_graph_verified:
        assert ontology_records is not None
        assert source_records is not None
        assert asset_records is not None
        assert claim_records is not None
        assert content_sets_path is not None
        source_ids = {record["source_id"] for record in source_records}
        style_ids = {record["style_id"] for record in ontology_records}
        mapping_id_set = {str(value) for value in mapping_ids}
        glyph_id_set = {str(value) for value in glyph_ids}
        mappings_by_id = {record["mapping_id"]: record for record in mapping_records}
        candidate_ids = {
            stable_id(
                "han_candidate",
                {
                    "glyph_instance_id": glyph["glyph_instance_id"],
                    "content_set_id": mappings_by_id[glyph["mapping_id"]]["content_set_id"],
                    "render_profile": render_profile,
                },
            )
            for glyph in glyph_records
            for render_profile in render_profiles
        }
        graph_errors = validate_ontology(
            ontology_records,
            contracts / "han_style_concept.schema.json",
            source_ids,
        )
        graph_errors += validate_character_mappings(
            mapping_records,
            contracts / "han_character_mapping.schema.json",
            load_content_sets(content_sets_path),
            source_ids,
        )
        graph_errors += validate_claims(
            claim_records,
            contracts / "han_knowledge_claim.schema.json",
            style_ids=style_ids,
            glyph_ids=glyph_id_set,
            source_ids=source_ids,
            work_ids={record["work_id"] for record in glyph_records}
            | {record["work_id"] for record in asset_records if record.get("work_id")},
            font_ids={record["font_id"] for record in glyph_records if record.get("font_id")}
            | {
                record["font_metadata"]["font_id"]
                for record in asset_records
                if isinstance(record.get("font_metadata"), dict)
                and record["font_metadata"].get("font_id")
            },
            stimulus_candidate_ids=candidate_ids,
        )
        graph_errors += validate_glyph_instances(
            glyph_records,
            contracts / "han_glyph_instance.schema.json",
            workspace_root=root,
            style_ids=style_ids,
            mapping_ids=mapping_id_set,
            source_ids=source_ids,
            asset_records=asset_records,
            claim_ids={record["claim_id"] for record in claim_records},
        )
        graph_errors += [
            f"HAN_SOURCE_SCHEMA_INVALID record={index}: {message}"
            for index, record in enumerate(source_records, start=1)
            for message in validate_record(record, contracts / "source.schema.json")
        ]
        graph_errors += [
            f"HAN_ASSET_SCHEMA_INVALID record={index}: {message}"
            for index, record in enumerate(asset_records, start=1)
            for message in validate_record(record, contracts / "asset_candidate.schema.json")
        ]
        if graph_errors:
            raise ValueError("HAN_CANDIDATE_GRAPH_INVALID: " + "; ".join(sorted(set(graph_errors))))
    rights_snapshot = None
    if task01_handoff_path is not None or rights_evidence_path is not None:
        if task01_handoff_path is None or rights_evidence_path is None:
            raise ValueError("HAN_RIGHTS_TRUST_INPUT_INCOMPLETE")
        rights_snapshot = load_trusted_rights_snapshot(
            root,
            task01_handoff_path,
            rights_evidence_path,
        )
        if list(rights_snapshot.records) != rights_evidence:
            raise ValueError("HAN_RIGHTS_RECORDS_DO_NOT_MATCH_TRUSTED_OUTPUT")
    mappings_by_id = {record["mapping_id"]: record for record in mapping_records}
    review_summaries = aggregate_reviews(
        reviews,
        minimum_independent_reviews=minimum_independent_reviews,
        minimum_substantive_dimensions=minimum_substantive_dimensions,
        required_dimensions=required_dimensions,
        required_role_groups=required_role_groups,
    )
    if not review_trusted:
        for summary in review_summaries.values():
            summary["formal_status"] = "blocked"
            summary["formal_policy_blockers"] = sorted(
                set([*summary["formal_policy_blockers"], "REVIEW_BATCH_UNTRUSTED"])
            )
    rights_by_source: dict[str, list[dict[str, Any]]] = {}
    for evidence in rights_evidence:
        rights_by_source.setdefault(evidence["source_id"], []).append(evidence)
    lineage_units = derive_lineage_units(glyph_records)
    eligible_units_by_style: dict[str, set[str]] = {}
    for glyph in glyph_records:
        summary = review_summaries.get(glyph["glyph_instance_id"], _empty_review_summary())
        if input_graph_verified and _formal_glyph_ready(
            glyph,
            summary,
            rights_by_source.get(glyph["source_id"], []),
            rights_snapshot is not None and rights_snapshot.formal_gate_passed,
        ):
            eligible_units_by_style.setdefault(glyph["style_id"], set()).add(
                lineage_units[glyph["glyph_instance_id"]]
            )

    candidates: list[dict[str, Any]] = []
    for glyph in glyph_records:
        mapping = mappings_by_id[glyph["mapping_id"]]
        review_summary = review_summaries.get(glyph["glyph_instance_id"], _empty_review_summary())
        evidence = rights_by_source.get(glyph["source_id"], [])
        rights_summary = _rights_summary(
            glyph,
            evidence,
            formal_rights_trusted=rights_snapshot is not None and rights_snapshot.formal_gate_passed,
            task01_handoff_sha256=rights_snapshot.handoff_sha256 if rights_snapshot else None,
            rights_output_sha256=rights_snapshot.output_sha256 if rights_snapshot else None,
        )
        independent_count = len(eligible_units_by_style.get(glyph["style_id"], set()))
        inference_scope = {
            "scope": "category_candidate" if independent_count >= minimum_independent_exemplars else "instance_level_only",
            "independent_exemplar_count": independent_count,
            "minimum_for_category": minimum_independent_exemplars,
            "blockers": [] if independent_count >= minimum_independent_exemplars else ["INSUFFICIENT_INDEPENDENT_EXEMPLARS"],
        }
        for render_profile in render_profiles:
            blockers = _freeze_blockers(
                glyph,
                mapping,
                review_summary,
                rights_summary,
                input_graph_verified=input_graph_verified,
            )
            data_origin = "synthetic_fixture" if glyph["data_origin"] == "generated_fixture" else "source_record"
            release_status = "fixture_only" if data_origin == "synthetic_fixture" else (
                "eligible_for_task01_freeze" if not blockers else "blocked"
            )
            task01_status = "ready_for_request" if release_status == "eligible_for_task01_freeze" else "blocked"
            candidate = {
                "schema_version": "1.1.0",
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
                "lineage_unit_ids": [lineage_units[glyph["glyph_instance_id"]]],
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


def derive_lineage_units(glyph_records: list[dict[str, Any]]) -> dict[str, str]:
    parents = list(range(len(glyph_records)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    by_glyph_id = {
        record["glyph_instance_id"]: index
        for index, record in enumerate(glyph_records)
        if isinstance(record.get("glyph_instance_id"), str)
    }
    seen_anchors: dict[tuple[str, str], int] = {}
    for index, glyph in enumerate(glyph_records):
        anchors = {
            ("work", glyph.get("work_id")),
            ("source", glyph.get("source_id")),
            ("font", glyph.get("font_id")),
            ("static_instance", glyph.get("static_instance_sha256")),
            ("primary_asset", glyph.get("asset_id")),
        }
        for kind, value in anchors:
            if not isinstance(value, str) or not value:
                continue
            anchor = (kind, value)
            if anchor in seen_anchors:
                union(index, seen_anchors[anchor])
            else:
                seen_anchors[anchor] = index
        parent_id = glyph.get("parent_glyph_instance_id")
        if isinstance(parent_id, str) and parent_id in by_glyph_id:
            union(index, by_glyph_id[parent_id])

    members: dict[int, list[str]] = {}
    for index, glyph in enumerate(glyph_records):
        members.setdefault(find(index), []).append(glyph["glyph_instance_id"])
    unit_by_root = {
        root: stable_id("lineage", {"glyph_instance_ids": sorted(glyph_ids)})
        for root, glyph_ids in members.items()
    }
    return {
        glyph["glyph_instance_id"]: unit_by_root[find(index)]
        for index, glyph in enumerate(glyph_records)
    }


def _empty_review_summary() -> dict[str, Any]:
    return {
        "package_ids": [],
        "synthetic_review_count": 0,
        "real_review_count": 0,
        "fixture_status": "blocked",
        "formal_status": "blocked",
        "decision_counts": {},
        "fixture_policy_blockers": ["INSUFFICIENT_INDEPENDENT_REVIEWS"],
        "formal_policy_blockers": ["INSUFFICIENT_INDEPENDENT_REVIEWS"],
        "adjudication_review_ids": [],
    }


def _rights_summary(
    glyph: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    formal_rights_trusted: bool = False,
    task01_handoff_sha256: str | None = None,
    rights_output_sha256: str | None = None,
) -> dict[str, Any]:
    matching = [
        item for item in evidence
        if item.get("decision_status") == "passed"
        and (
            item.get("rights_tier") == glyph["rights_tier"]
            or (
                item.get("rights_tier") == "open"
                and glyph["rights_tier"] == "research_local_only"
            )
        )
    ]
    permitted_uses = sorted({use for item in matching for use in item.get("permitted_uses", [])})
    if glyph["data_origin"] == "generated_fixture" and "engineering_fixture" in permitted_uses:
        status = "fixture_only"
    elif formal_rights_trusted and "research_stimulus_local" in permitted_uses:
        status = "passed"
    else:
        status = "blocked"
    return {
        "status": status,
        "rights_tier": glyph["rights_tier"],
        "rights_evidence_ids": sorted(item["rights_evidence_id"] for item in matching),
        "permitted_uses": permitted_uses,
        "trust_source": "task01_handoff" if task01_handoff_sha256 else "standalone_untrusted",
        "task01_handoff_sha256": task01_handoff_sha256,
        "rights_output_sha256": rights_output_sha256,
    }


def _freeze_blockers(
    glyph: dict[str, Any],
    mapping: dict[str, Any],
    review_summary: dict[str, Any],
    rights_summary: dict[str, Any],
    *,
    input_graph_verified: bool,
) -> list[str]:
    blockers: list[str] = []
    if not input_graph_verified:
        blockers.append("INPUT_GRAPH_UNVERIFIED")
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
    formal_rights_trusted: bool = False,
) -> bool:
    rights = _rights_summary(
        glyph,
        evidence,
        formal_rights_trusted=formal_rights_trusted,
    )
    return (
        glyph["data_origin"] == "source_record"
        and glyph["identity_status"] == "evidence_supported"
        and glyph["attribution_status"] == "evidence_supported"
        and glyph["structure_qc"]["status"] == "passed"
        and review_summary["formal_status"] == "passed"
        and rights["status"] == "passed"
    )

"""Written-contract adapters for TASK-01/02/03 and WP2."""
from __future__ import annotations

from typing import Any

from glyph_features.asset_system.catalog import stable_id, validate_record


WP2_CANONICAL_LABELS = {"small_seal": "seal", "sans": "sans"}


def build_adapter_records(
    ontology: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    schema_path: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        common = {
            "style_id": candidate["style_id"],
            "candidate_id": candidate["candidate_id"],
            "stimulus_id": candidate["stimulus_id"],
            "data_origin": candidate["data_origin"],
        }
        records.extend(
            [
                _adapter(
                    "TASK-01",
                    "asset_candidate-1.0.0/ecological_stimulus-2.0.0",
                    common,
                    "fixture_only" if candidate["release_status"] == "fixture_only" else "blocked",
                    candidate["task01_freeze"]["blockers"],
                    ["TASK-01 remains the sole owner of formal stimulus_id assignment."],
                    {
                        "requested_render_profile": candidate["render_profile"],
                        "representation_asset_ids": candidate["representation_asset_ids"],
                        "freeze_status": candidate["task01_freeze"]["status"],
                    },
                ),
                _adapter(
                    "TASK-02",
                    "written-contract-2026-09-04",
                    common,
                    "fixture_only" if candidate["data_origin"] == "synthetic_fixture" else "blocked",
                    ["TARGET_IMPLEMENTATION_NOT_AVAILABLE_AT_CHECKPOINT"]
                    + (["SYNTHETIC_FIXTURE"] if candidate["data_origin"] == "synthetic_fixture" else []),
                    [
                        "C1-C5 proxies remain within_script_only or protocol_dependent.",
                        "Raw measurements cannot be modified to match expert expectations.",
                    ],
                    {
                        "preferred_representations": ["B_shape", "B_shape_mask", "C_ink"],
                        "representation_asset_ids": candidate["representation_asset_ids"],
                        "normalization_profile": candidate["render_profile"],
                        "comparability": ["within_script_only", "protocol_dependent"],
                        "target_implementation_verified": False,
                    },
                ),
                _adapter(
                    "TASK-03",
                    "written-contract-2026-09-04",
                    common,
                    "blocked",
                    sorted(set(candidate["task01_freeze"]["blockers"] + ["TASK01_STIMULUS_ID_UNASSIGNED", "TARGET_IMPLEMENTATION_NOT_AVAILABLE_AT_CHECKPOINT"])),
                    [
                        "Blind and contextual label conditions must remain separate.",
                        "Expert terminology and attribution answers stay hidden from ordinary participants.",
                        "Assignment groups by work, font instance, and exemplar cluster to prevent pseudoreplication.",
                    ],
                    {
                        "content_set_id": candidate["content_set_id"],
                        "label_conditions": candidate["label_conditions"],
                        "group_ids": {
                            "work_ids": candidate["work_ids"],
                            "font_ids": candidate["font_ids"],
                            "exemplar_cluster_ids": candidate["exemplar_cluster_ids"],
                        },
                        "hidden_fields": ["style_attribution", "expert_reviews", "historical_claims"],
                        "target_implementation_verified": False,
                    },
                ),
            ]
        )
    for style in ontology:
        canonical_label = WP2_CANONICAL_LABELS.get(style["target_code"], style["target_code"])
        registry_present = style["target_code"] in WP2_CANONICAL_LABELS
        aliases = [
            {"term": alias["term"], "language_bcp47": alias["language_bcp47"]}
            for alias in style["aliases"]
        ]
        aliases.extend(
            {"term": term, "language_bcp47": language}
            for language, term in style["canonical_names"].items()
        )
        records.append(
            _adapter(
                "WP2",
                "social-object-map-0.1.0",
                {
                    "style_id": style["style_id"],
                    "candidate_id": None,
                    "stimulus_id": None,
                    "data_origin": "registry_projection",
                },
                "fixture_only" if registry_present else "blocked",
                [] if registry_present else ["WP2_OBJECT_MAP_EXTENSION_REQUIRED"],
                [
                    "Canonical style_id and observed raw term remain separate.",
                    "A style-word hit cannot confirm the style of an image.",
                    "Association claims remain cultural narratives, not historical facts.",
                ],
                {
                    "object_type": "style_family",
                    "canonical_label": canonical_label,
                    "style_id": style["style_id"],
                    "aliases": aliases,
                    "existing_registry_match": registry_present,
                },
            )
        )
    for record in records:
        errors = validate_record(record, schema_path)
        if errors:
            raise ValueError("HAN_ADAPTER_SCHEMA_INVALID: " + "; ".join(errors))
    return sorted(records, key=lambda record: record["adapter_id"])


def integration_requests(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: dict[str, set[str]] = {}
    for record in records:
        for reason in record["blocking_reasons"]:
            requests.setdefault(record["target_system"], set()).add(reason)
    return [
        {
            "target_system": target,
            "status": "blocked",
            "blocking_reasons": sorted(reasons),
        }
        for target, reasons in sorted(requests.items())
    ]


def _adapter(
    target_system: str,
    target_contract: str,
    common: dict[str, Any],
    status: str,
    blocking_reasons: list[str],
    assumptions: list[str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "target_system": target_system,
        "style_id": common["style_id"],
        "candidate_id": common["candidate_id"],
        "payload_key": payload.get("normalization_profile") or payload.get("canonical_label") or "default",
    }
    return {
        "schema_version": "1.0.0",
        "adapter_id": stable_id("han_adapter", identity),
        "source_task": "TASK-04",
        "target_system": target_system,
        "target_contract": target_contract,
        **common,
        "status": status,
        "blocking_reasons": sorted(set(blocking_reasons)),
        "assumptions": assumptions,
        "payload": payload,
    }

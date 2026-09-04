"""Machine-readable module descriptors and compatibility projection."""

from __future__ import annotations

from typing import Any, Iterable


MODULE_SURFACES = {
    "assets": {
        "capabilities": ["source_registry", "rights_audit", "stimulus_freeze"],
        "read_endpoints": ["glyph-assets validate-handoff"],
        "command_endpoints": ["glyph-assets"],
        "data_classifications": ["open_fixture", "restricted_asset_pointer"],
    },
    "vision": {
        "capabilities": ["feature_extraction", "visual_qc", "sensitivity_audit"],
        "read_endpoints": ["glyph-vision validate-handoff"],
        "command_endpoints": ["glyph-vision"],
        "data_classifications": ["protocol_measurement", "synthetic_fixture"],
    },
    "experiment": {
        "capabilities": ["assignment", "deidentified_export", "quality_audit"],
        "read_endpoints": ["glyph-experiment validate-handoff"],
        "command_endpoints": ["glyph-experiment"],
        "data_classifications": ["synthetic_participant", "deidentified_research"],
    },
    "han_style": {
        "capabilities": ["style_ontology", "knowledge_claims", "expert_review"],
        "read_endpoints": ["glyph-han validate-handoff"],
        "command_endpoints": ["glyph-han"],
        "data_classifications": ["registry_projection", "synthetic_fixture"],
    },
}


def _upstream_descriptor(result: dict[str, Any]) -> dict[str, Any]:
    surface = MODULE_SURFACES[result["module_id"]]
    return {
        "descriptor_schema_version": "1.0.0",
        "module_id": result["module_id"],
        "module_version": result.get("producer_version") or result["handoff_schema_version"],
        "contract_versions": result.get("contract_versions") or {},
        "capabilities": surface["capabilities"],
        "health": "ready" if result["compatible"] else "blocked",
        "read_endpoints": surface["read_endpoints"],
        "command_endpoints": surface["command_endpoints"],
        "handoff_schema_version": result["handoff_schema_version"],
        "data_classifications": surface["data_classifications"],
        "human_gates": [
            gate["gate_id"]
            for gate in result.get("blocked_gates", [])
            if gate["gate_id"].startswith("GATE-")
        ],
        "readiness": result["readiness"],
        "flow_status": "fixture_validated" if result["compatible"] else "release_blocked",
    }


def build_module_descriptors(
    handoff_results: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project validated contracts into descriptors without copying domain rows."""

    descriptors = [_upstream_descriptor(result) for result in handoff_results]
    descriptors.extend(
        [
            {
                "descriptor_schema_version": "1.0.0",
                "module_id": "social",
                "module_version": "sqlite-v17",
                "contract_versions": {
                    "social_observation": "0.2.0",
                    "social_database": "17",
                },
                "capabilities": [
                    "bounded_collection",
                    "human_review",
                    "validated_export",
                    "sqlite_backup",
                ],
                "health": "ready",
                "read_endpoints": ["validated export", "glyph-social monitoring"],
                "command_endpoints": ["glyph-social"],
                "handoff_schema_version": "validated-export-v17",
                "data_classifications": ["synthetic_fixture", "human_verified_evidence"],
                "human_gates": ["GATE-TERMS", "GATE-RELEASE"],
                "readiness": {
                    "engineering_ready": True,
                    "pilot_ready": False,
                    "research_validated": False,
                },
                "flow_status": "fixture_validated",
            },
            {
                "descriptor_schema_version": "1.0.0",
                "module_id": "workbench",
                "module_version": "0.1.0",
                "contract_versions": {"catalog": "1.0.0", "module_descriptor": "1.0.0"},
                "capabilities": ["handoff_registry", "joint_analysis", "release_gate"],
                "health": "ready" if all(item["compatible"] for item in handoff_results) else "blocked",
                "read_endpoints": ["/api/overview", "/api/audit"],
                "command_endpoints": ["glyph-workbench"],
                "handoff_schema_version": "1.0.0",
                "data_classifications": ["pointer_metadata", "analysis_snapshot"],
                "human_gates": ["GATE-RELEASE"],
                "readiness": {
                    "engineering_ready": True,
                    "pilot_ready": False,
                    "research_validated": False,
                },
                "flow_status": "fixture_validated",
            },
        ]
    )
    return descriptors
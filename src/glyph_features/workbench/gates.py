"""Mechanical publication gates with no user-interface bypass."""

from __future__ import annotations

from typing import Any

from glyph_features.asset_system.catalog import stable_id, validate_record

from .catalog import Catalog, CatalogError


class ReleaseBlocked(RuntimeError):
    def __init__(self, candidate: dict[str, Any]):
        self.candidate = candidate
        codes = ",".join(item["code"] for item in candidate["formal_blockers"])
        super().__init__(f"FORMAL_RELEASE_BLOCKED:{codes}")


def _blocker(
    code: str,
    scope: str,
    message: str,
    *,
    gate_id: str | None = None,
) -> dict[str, Any]:
    result = {"code": code, "scope": scope, "message": message}
    if gate_id is not None:
        result["gate_id"] = gate_id
    return result


def formal_release_blockers(
    analysis_run: dict[str, Any],
    overview: dict[str, Any],
) -> list[dict[str, Any]]:
    result = analysis_run["result"]
    snapshot = analysis_run["snapshot"]
    blockers: list[dict[str, Any]] = []
    if result["data_origin"] == "synthetic":
        blockers.append(
            _blocker(
                "RELEASE_SYNTHETIC_DATA_FORBIDDEN",
                analysis_run["analysis_run_id"],
                "Synthetic ratings and evidence are restricted to engineering demo output.",
            )
        )
    if not overview["readiness"]["pilot_ready"]:
        blockers.append(
            _blocker(
                "PILOT_READINESS_REQUIRED",
                "system",
                "The system has not passed pilot readiness gates.",
            )
        )
    if not overview["readiness"]["research_validated"]:
        blockers.append(
            _blocker(
                "RESEARCH_VALIDATION_REQUIRED",
                "system",
                "No validated real-participant research result is available.",
            )
        )
    for gate in snapshot["gate_state"]:
        blockers.append(
            _blocker(
                f"HUMAN_GATE_UNRESOLVED:{gate['gate_id']}",
                gate["module_id"],
                f"Human gate {gate['gate_id']} is unresolved for {gate['module_id']}.",
                gate_id=gate["gate_id"],
            )
        )
    if not result["model_diagnostics"]["research_model_eligible"]:
        blockers.append(
            _blocker(
                "RESEARCH_MODEL_NOT_ELIGIBLE",
                analysis_run["analysis_run_id"],
                "The fixture approximation does not satisfy the preregistered research hierarchy.",
            )
        )
    for package in ("WP3", "WP4"):
        package_result = result["work_packages"][package]
        if package_result.get("status") in {"blocked", "instance_level_only"}:
            blockers.append(
                _blocker(
                    f"{package}_INFERENCE_BLOCKED",
                    package,
                    f"{package} has not reached its declared inference threshold.",
                )
            )
    if (
        overview["social"]["health"] != "ready"
        or overview["social"].get("validated_export_count", 0) < 1
    ):
        blockers.append(
            _blocker(
                "SOCIAL_VALIDATED_EXPORT_REQUIRED",
                "social",
                "A schema-v17 validated social export has not been attached.",
            )
        )
    blockers.append(
        _blocker(
            "HUMAN_GATE_UNRESOLVED:GATE-RELEASE",
            "system",
            "External release requires a scoped human GATE-RELEASE decision.",
            gate_id="GATE-RELEASE",
        )
    )
    unique = {
        (item["code"], item["scope"], item.get("gate_id")): item for item in blockers
    }
    return sorted(
        unique.values(),
        key=lambda item: (item.get("gate_id", ""), item["code"], item["scope"]),
    )


def evaluate_release_candidate(
    catalog: Catalog,
    workspace_root,
    analysis_run: dict[str, Any],
    overview: dict[str, Any],
    *,
    purpose: str,
) -> dict[str, Any]:
    if purpose not in {"demo_export", "formal_release"}:
        raise CatalogError("RELEASE_PURPOSE_INVALID")
    blockers = formal_release_blockers(analysis_run, overview)
    core = {
        "analysis_run_id": analysis_run["analysis_run_id"],
        "purpose": purpose,
        "data_origin": analysis_run["result"]["data_origin"],
        "formal_blockers": blockers,
    }
    candidate = {
        "schema_version": "1.0.0",
        "release_candidate_id": stable_id("release", core),
        **core,
        "status": "demo_ready" if purpose == "demo_export" else "blocked",
        "formal_release_eligible": not blockers,
        "created_at": analysis_run["snapshot"]["created_at"],
    }
    errors = validate_record(
        candidate,
        workspace_root / "schema/release_candidate.schema.json",
    )
    if errors:
        raise CatalogError("RELEASE_CANDIDATE_INVALID:" + " | ".join(errors))
    candidate = catalog.register_release_candidate(candidate)
    if purpose == "formal_release" and blockers:
        raise ReleaseBlocked(candidate)
    return candidate
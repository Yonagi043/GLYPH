"""Preregistered quality flags that preserve source records and decision history."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schema import canonical_sha256, validate_record


PRIMARY_CONSTRUCTS = {"aesthetic", "premium", "modern", "trustworthy"}


def build_quality_decision(
    profile: dict[str, Any],
    consent: dict[str, Any],
    events: list[dict[str, Any]],
    ratings: list[dict[str, Any]],
    *,
    previous_decision_id: str | None = None,
    decided_at: str = "2026-09-04T00:00:00Z",
) -> dict[str, Any]:
    reasons: set[str] = set()
    if consent.get("status") != "consented":
        reasons.add("CONSENT_MISSING")
    if not consent.get("age_eligible"):
        reasons.add("INELIGIBLE")
    loaded_events = [event for event in events if event.get("load_status") == "loaded"]
    if len({event.get("presentation_id") for event in loaded_events}) < 6:
        reasons.add("INCOMPLETE")
    if any(event.get("load_status") != "loaded" for event in events):
        reasons.add("ASSET_FAILURE")
    if loaded_events and sum(event.get("response_ms", 0) < 350 for event in loaded_events) * 2 >= len(loaded_events):
        reasons.add("TOO_FAST")
    if loaded_events and sum(
        event.get("viewport", {}).get("css_width", 0) < 320
        or event.get("viewport", {}).get("css_height", 0) < 480
        for event in loaded_events
    ) * 2 >= len(loaded_events):
        reasons.add("VIEWPORT_UNUSABLE")
    if any(rating.get("attention_check") is False for rating in ratings):
        reasons.add("ATTENTION_FAILED")
    if not profile.get("language_understood"):
        reasons.add("LANGUAGE_NOT_UNDERSTOOD")
    if not profile.get("native_scripts") or len(profile.get("script_proficiencies", [])) < 4:
        reasons.add("BACKGROUND_MISSING")
    primary = [
        rating
        for rating in ratings
        if rating.get("construct") in PRIMARY_CONSTRUCTS and rating.get("response", {}).get("value") is not None
    ]
    if len({rating.get("presentation_id") for rating in primary}) >= 6 and len({rating["response"]["value"] for rating in primary}) == 1:
        reasons.add("STRAIGHTLINING")
    reason_codes = sorted(reasons)
    identity = {
        "study_id": profile["study_id"],
        "participant_id": profile["participant_id"],
        "rule_version": "1.0.0",
        "reason_codes": reason_codes,
        "previous_decision_id": previous_decision_id,
        "decided_at": decided_at,
    }
    decision = {
        "schema_version": "1.0.0",
        "decision_id": f"quality_{canonical_sha256(identity)[:24]}",
        "study_id": profile["study_id"],
        "participant_id": profile["participant_id"],
        "data_origin": profile["data_origin"],
        "rule_version": "1.0.0",
        "exclude_from_analysis": bool(reason_codes),
        "reason_codes": reason_codes,
        "source_presentation_ids": sorted({event["presentation_id"] for event in events}),
        "previous_decision_id": previous_decision_id,
        "decided_at": decided_at,
        "decision_basis": "preregistered_rules_not_outcome_values",
    }
    errors = validate_record(decision, "quality_decision.schema.json")
    if errors:
        raise ValueError("QUALITY_DECISION_INVALID: " + "; ".join(errors))
    return decision


def audit_exclusion_parity(
    decisions: list[dict[str, Any]],
    participant_groups: dict[str, str],
    *,
    warning_threshold: float = 0.10,
) -> dict[str, Any]:
    totals: dict[str, int] = defaultdict(int)
    excluded: dict[str, int] = defaultdict(int)
    for decision in decisions:
        group = participant_groups[decision["participant_id"]]
        totals[group] += 1
        excluded[group] += int(decision["exclude_from_analysis"])
    rates = {group: excluded[group] / total for group, total in sorted(totals.items())}
    spread = max(rates.values(), default=0.0) - min(rates.values(), default=0.0)
    return {
        "group_rates": rates,
        "max_rate_difference": spread,
        "warning": "GROUP_EXCLUSION_RATE_DIFFERENCE" if spread > warning_threshold else None,
    }
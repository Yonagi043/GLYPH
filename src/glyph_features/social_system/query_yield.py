"""Deterministic per-query retrieval-yield evaluation."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any


POLICY_VERSION = "query_yield_v0.1.0"
DEFAULT_POLICY = {
    "policy_version": POLICY_VERSION,
    "evaluation_k": 20,
    "min_included_at_k": 5,
    "min_precision_at_k": 0.25,
    "min_precision_lower_bound": 0.10,
    "confidence_level": 0.95,
}


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "policy_version": str(policy.get("policy_version") or POLICY_VERSION),
        "evaluation_k": int(policy.get("evaluation_k", 0)),
        "min_included_at_k": int(policy.get("min_included_at_k", 0)),
        "min_precision_at_k": float(policy.get("min_precision_at_k", -1)),
        "min_precision_lower_bound": float(
            policy.get("min_precision_lower_bound", -1)
        ),
        "confidence_level": float(policy.get("confidence_level", 0)),
    }
    if normalized["policy_version"] != POLICY_VERSION:
        raise ValueError("不支持的 query-yield policy 版本")
    if normalized["evaluation_k"] < 1:
        raise ValueError("query-yield evaluation_k 必须大于 0")
    if not 0 <= normalized["min_included_at_k"] <= normalized["evaluation_k"]:
        raise ValueError("query-yield 最低纳入数必须位于 0 和 evaluation_k 之间")
    for key in ("min_precision_at_k", "min_precision_lower_bound"):
        if not 0 <= normalized[key] <= 1:
            raise ValueError(f"query-yield {key} 必须位于 0 和 1 之间")
    if not 0 < normalized["confidence_level"] < 1:
        raise ValueError("query-yield confidence_level 必须位于 0 和 1 之间")
    return normalized


def wilson_interval(
    successes: int,
    total: int,
    *,
    confidence_level: float = 0.95,
) -> dict[str, float] | None:
    if total == 0:
        return None
    if successes < 0 or successes > total:
        raise ValueError("successes 必须位于 0 和 total 之间")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level 必须位于 0 和 1 之间")
    z_score = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    proportion = successes / total
    denominator = 1 + z_score**2 / total
    center = (proportion + z_score**2 / (2 * total)) / denominator
    margin = (
        z_score
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z_score**2 / (4 * total**2)
        )
        / denominator
    )
    return {
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
        "confidence_level": confidence_level,
    }


def _retrieval_rank(match: dict[str, Any]) -> int | None:
    context = match.get("context")
    if not isinstance(context, dict):
        return None
    retrieval = context.get("retrieval")
    if not isinstance(retrieval, dict):
        return None
    rank = retrieval.get("candidate_rank")
    return rank if isinstance(rank, int) and rank > 0 else None


def _latest_manual_screenings(
    screening_history: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in sorted(
        screening_history, key=lambda row: int(row.get("screening_id", 0))
    ):
        signals = event.get("signals")
        if not isinstance(signals, dict) or signals.get("manual_review") is not True:
            continue
        observation_id = event.get("observation_id")
        if isinstance(observation_id, str):
            latest[observation_id] = event
    return latest


def _query_result(
    query: dict[str, Any],
    matches: list[dict[str, Any]],
    screenings: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    query_id = query["query_id"]
    query_matches = [
        row
        for row in matches
        if row.get("query_id") == query_id
        and isinstance(row.get("context"), dict)
        and row["context"].get("kind") == "video"
    ]
    decisions = {
        row["observation_id"]: screenings.get(row["observation_id"])
        for row in query_matches
    }
    counts = {decision: 0 for decision in ("include", "exclude", "uncertain")}
    for event in decisions.values():
        if event is not None and event.get("decision") in counts:
            counts[event["decision"]] += 1
    resolved_count = counts["include"] + counts["exclude"]
    overall_precision = counts["include"] / resolved_count if resolved_count else None
    ranked = [
        (rank, row["observation_id"])
        for row in query_matches
        if (rank := _retrieval_rank(row)) is not None
    ]
    ranked.sort()
    ranks = [rank for rank, _ in ranked]
    evaluation_k = policy["evaluation_k"]
    top_k = ranked[:evaluation_k]
    top_k_ranks_complete = (
        len(top_k) == evaluation_k
        and [rank for rank, _ in top_k] == list(range(1, evaluation_k + 1))
    )
    top_k_decisions = [
        decisions[observation_id].get("decision")
        if decisions.get(observation_id) is not None
        else None
        for _, observation_id in top_k
    ]
    top_k_screening_complete = top_k_ranks_complete and all(
        decision in {"include", "exclude"} for decision in top_k_decisions
    )
    included_at_k = (
        sum(decision == "include" for decision in top_k_decisions)
        if top_k_screening_complete
        else None
    )
    precision_at_k = (
        included_at_k / evaluation_k if included_at_k is not None else None
    )
    interval = (
        wilson_interval(
            included_at_k,
            evaluation_k,
            confidence_level=policy["confidence_level"],
        )
        if included_at_k is not None
        else None
    )

    inconclusive_reasons = []
    if len(query_matches) < evaluation_k:
        inconclusive_reasons.append("retrieved_below_evaluation_k")
    if len(ranked) != len(query_matches) or len(set(ranks)) != len(ranks):
        inconclusive_reasons.append("rank_metadata_incomplete")
    if len(query_matches) >= evaluation_k and not top_k_screening_complete:
        inconclusive_reasons.append("top_k_screening_incomplete")

    failure_reasons = []
    if not inconclusive_reasons:
        assert included_at_k is not None
        assert precision_at_k is not None
        assert interval is not None
        if included_at_k < policy["min_included_at_k"]:
            failure_reasons.append("included_at_k_below_minimum")
        if precision_at_k < policy["min_precision_at_k"]:
            failure_reasons.append("precision_at_k_below_minimum")
        if interval["lower"] < policy["min_precision_lower_bound"]:
            failure_reasons.append("precision_lower_bound_below_minimum")

    status = (
        "inconclusive"
        if inconclusive_reasons
        else "failed"
        if failure_reasons
        else "passed"
    )
    return {
        "query_id": query_id,
        "query_family": query.get("query_family"),
        "phase": query.get("phase"),
        "exact_query": query.get("exact_query") or query.get("query_text"),
        "retrieved_count": len(query_matches),
        "ranked_count": len(ranked),
        "human_screened_count": sum(event is not None for event in decisions.values()),
        "resolved_count": resolved_count,
        "included_count": counts["include"],
        "excluded_count": counts["exclude"],
        "uncertain_count": counts["uncertain"],
        "screening_missing_count": sum(event is None for event in decisions.values()),
        "overall_precision": overall_precision,
        "overall_precision_interval": wilson_interval(
            counts["include"],
            resolved_count,
            confidence_level=policy["confidence_level"],
        ),
        "evaluation_k": evaluation_k,
        "included_at_k": included_at_k,
        "precision_at_k": precision_at_k,
        "precision_at_k_interval": interval,
        "status": status,
        "inconclusive_reasons": inconclusive_reasons,
        "failure_reasons": failure_reasons,
    }


def build_query_yield_report(
    *,
    collection_run_id: str,
    run_status: str,
    queries: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    screening_history: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
    assessment_mode: str = "retrospective",
) -> dict[str, Any]:
    normalized_policy = validate_policy(policy or DEFAULT_POLICY)
    if assessment_mode not in {"preregistered", "retrospective"}:
        raise ValueError("无效的 query-yield assessment mode")
    screenings = _latest_manual_screenings(screening_history)
    query_results = [
        _query_result(query, matches, screenings, normalized_policy)
        for query in queries
    ]
    global_reasons = []
    if run_status != "completed":
        global_reasons.append("run_not_completed")
    if not query_results:
        global_reasons.append("no_queries")
    statuses = {row["status"] for row in query_results}
    status = (
        "inconclusive"
        if global_reasons or "inconclusive" in statuses
        else "failed"
        if "failed" in statuses
        else "passed"
    )
    unique_candidates = {
        row["observation_id"]
        for row in matches
        if isinstance(row.get("observation_id"), str)
        and isinstance(row.get("context"), dict)
        and row["context"].get("kind") == "video"
    }
    candidate_matches = [
        row
        for row in matches
        if isinstance(row.get("context"), dict)
        and row["context"].get("kind") == "video"
    ]
    passed_query_ids = [
        row["query_id"]
        for row in query_results
        if row["status"] == "passed"
        and assessment_mode == "preregistered"
        and not global_reasons
    ]
    return {
        "collection_run_id": collection_run_id,
        "status": status,
        "assessment_mode": assessment_mode,
        "policy": normalized_policy,
        "unique_candidate_count": len(unique_candidates),
        "candidate_query_match_count": len(candidate_matches),
        "global_inconclusive_reasons": global_reasons,
        "query_results": query_results,
        "calibration_passed_query_ids": passed_query_ids,
        "calibration_passed": status == "passed" and assessment_mode == "preregistered",
    }
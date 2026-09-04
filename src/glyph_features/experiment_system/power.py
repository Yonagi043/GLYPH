"""Transparent planning scenarios; never an approved sample-size decision."""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any


def power_scenarios(
    protocol: dict[str, Any],
    *,
    alpha: float = 0.05,
    target_power: float = 0.80,
) -> dict[str, Any]:
    if not 0 < alpha < 1 or not 0 < target_power < 1:
        raise ValueError("POWER_PROBABILITY_INVALID")
    trials = int(protocol["design"]["block_size"])
    group_count = len(protocol["design"]["target_script_groups"])
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_power = NormalDist().inv_cdf(target_power)
    rows = []
    for scenario in protocol["sampling_plan"]["power_scenarios"]:
        effect = float(scenario["standardized_effect"])
        participant_icc = float(scenario["participant_icc"])
        stimulus_icc = float(scenario["stimulus_icc"])
        independent_per_group = 2 * ((z_alpha + z_power) / effect) ** 2
        design_effect = (1 + (trials - 1) * participant_icc) * (1 + stimulus_icc)
        required_per_group = math.ceil(independent_per_group * design_effect)
        rows.append({
            **scenario,
            "trials_per_participant": trials,
            "design_effect": round(design_effect, 4),
            "required_per_group_approx": required_per_group,
            "required_total_approx": required_per_group * group_count,
        })
    totals = [row["required_total_approx"] for row in rows]
    return {
        "method": "normal_approximation_with_crossed_clustering_design_effect",
        "status": "planning_scenarios_not_approved_sample_size",
        "alpha_two_sided": alpha,
        "target_power": target_power,
        "scenario_total_range": [min(totals), max(totals)],
        "limitations": [
            "Effect sizes are hypothetical planning inputs, not observed GLYPH effects.",
            "Crossed participant/stimulus clustering is approximated and must be replaced by model-based simulation before recruitment.",
            "Multiplicity, attrition, measurement non-invariance and quota availability require separate sensitivity analyses.",
        ],
        "scenarios": rows,
    }
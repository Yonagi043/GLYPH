"""Engineering-only ordinal model recovery with explicit research boundaries."""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from statsmodels.miscmodels.ordinal_model import OrderedModel
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant

from glyph_features.asset_system.catalog import canonical_json


class AnalysisError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def model_family_for_scales(scales: Iterable[str]) -> str:
    unique = set(scales)
    if unique and unique.issubset({"likert_1_5", "likert_1_7"}):
        return "ordinal"
    if unique == {"continuous_0_100"}:
        return "continuous"
    raise AnalysisError("RATING_SCALE_ROUTE_AMBIGUOUS", repr(sorted(unique)))


def _design(frame: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    design = pd.get_dummies(
        frame[["stimulus_script", "native_script"]],
        drop_first=True,
        dtype=float,
    )
    design["native_match"] = frame["native_match"].astype(float)
    if columns is not None:
        design = design.reindex(columns=columns, fill_value=0.0)
    return design


def _ordered_fit(frame: pd.DataFrame, columns: list[str] | None = None):
    design = _design(frame, columns)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = OrderedModel(
            frame["response_value"],
            design,
            distr="logit",
        ).fit(method="bfgs", disp=False, maxiter=300)
    return fit, design, [str(item.message) for item in caught]


def _double_group_holdout(frame: pd.DataFrame) -> list[dict[str, Any]]:
    participant_number = frame["participant_id"].str.rsplit("_", n=1).str[-1].astype(int)
    stimulus_number = frame["stimulus_id"].str.rsplit("_", n=1).str[-1].astype(int)
    participant_fold = ((participant_number - 1) // 4) % 4
    stimulus_fold = (stimulus_number - 1) % 4
    full_columns = list(_design(frame).columns)
    diagnostics = []
    for fold in range(4):
        train = frame[(participant_fold != fold) & (stimulus_fold != fold)]
        test = frame[(participant_fold == fold) & (stimulus_fold == fold)]
        train_participants = set(train["participant_id"])
        test_participants = set(test["participant_id"])
        train_stimuli = set(train["stimulus_id"])
        test_stimuli = set(test["stimulus_id"])
        fit, _, caught = _ordered_fit(train, full_columns)
        test_design = _design(test, full_columns)
        probabilities = np.asarray(fit.model.predict(fit.params, exog=test_design))
        labels = np.asarray(fit.model.labels, dtype=float)
        expected = probabilities @ labels
        diagnostics.append(
            {
                "fold": fold,
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
                "participant_overlap": len(train_participants & test_participants),
                "stimulus_overlap": len(train_stimuli & test_stimuli),
                "converged": bool(fit.mle_retvals.get("converged")),
                "mean_absolute_error": float(
                    np.mean(np.abs(test["response_value"].to_numpy() - expected))
                ),
                "warnings": caught,
                "scaling_fit_scope": "training_fold_only",
            }
        )
    return diagnostics


def _effect_estimate(fit, parameter: str) -> dict[str, Any]:
    interval = fit.conf_int().loc[parameter]
    estimate = float(fit.params[parameter])
    return {
        "estimand_id": "estimand_native_match",
        "parameter": parameter,
        "estimate_log_odds": estimate,
        "standard_error": float(fit.bse[parameter]),
        "confidence_interval_95": [float(interval.iloc[0]), float(interval.iloc[1])],
        "odds_ratio": float(math.exp(estimate)),
        "p_value": float(fit.pvalues[parameter]),
        "data_origin": "synthetic",
        "interpretation": "Engineering recovery only; not a scientific effect estimate.",
    }


def _continuous_sensitivity(frame: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    design = add_constant(_design(frame, columns), has_constant="add")
    fit = OLS(frame["response_value"].astype(float), design).fit(cov_type="HC3")
    interval = fit.conf_int().loc["native_match"]
    return {
        "specification": "continuous_ols_hc3_sensitivity_only",
        "native_match_estimate": float(fit.params["native_match"]),
        "standard_error": float(fit.bse["native_match"]),
        "confidence_interval_95": [float(interval.iloc[0]), float(interval.iloc[1])],
        "r_squared": float(fit.rsquared),
        "status": "sensitivity_only",
    }


def _han_inference_boundary(root: Path) -> dict[str, Any]:
    path = root / (
        "data/fixtures/han_style_system/reference_run_v1/"
        "candidate_bundle/stimulus_candidates.jsonl"
    )
    candidates = [json.loads(line) for line in path.read_text().splitlines() if line]
    independent_counts = [
        candidate["inference_scope"]["independent_exemplar_count"]
        for candidate in candidates
    ]
    thresholds = [
        candidate["inference_scope"]["minimum_for_category"]
        for candidate in candidates
    ]
    return {
        "status": "instance_level_only",
        "candidate_count": len(candidates),
        "maximum_independent_exemplars": max(independent_counts, default=0),
        "minimum_required_for_category": max(thresholds, default=3),
        "category_effect_allowed": False,
        "blockers": ["INSUFFICIENT_INDEPENDENT_EXEMPLARS", "GATE-EXPERT"],
    }


def run_fixture_analysis(
    workspace_root: str | Path,
    rows: list[dict[str, Any]],
    join_audit: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Run a synthetic recovery model without upgrading research readiness."""

    if not rows:
        raise AnalysisError("ANALYSIS_ROWS_EMPTY", "no eligible analysis units")
    if {row["data_origin"] for row in rows} != {"synthetic"}:
        raise AnalysisError("FIXTURE_ANALYSIS_REQUIRES_SYNTHETIC", "origin is not synthetic-only")
    family = model_family_for_scales(row["rating_scale"] for row in rows)
    if family != plan["model"]["family"]:
        raise AnalysisError(
            "PLAN_MODEL_FAMILY_MISMATCH",
            f"plan={plan['model']['family']} routed={family}",
        )
    frame = pd.DataFrame(rows)
    fit, design, caught = _ordered_fit(frame)
    converged = bool(fit.mle_retvals.get("converged"))
    if not converged:
        raise AnalysisError("MODEL_DID_NOT_CONVERGE", repr(fit.mle_retvals))
    probabilities = np.asarray(fit.model.predict(fit.params, exog=design))
    probability_sums = probabilities.sum(axis=1)
    feature_columns = join_audit["feature_columns"]
    zero_variance_features = [
        column
        for column in feature_columns
        if frame[column].dropna().nunique() <= 1
    ]
    holdouts = _double_group_holdout(frame)
    hierarchy_fitted = False
    effect = _effect_estimate(fit, "native_match")
    result = {
        "schema_version": "1.0.0",
        "status": "completed_with_research_limits",
        "data_origin": "synthetic",
        "analysis_unit": join_audit["analysis_unit"],
        "model_specification": {
            "planned_formula": plan["model"]["formula"],
            "fitted_family": family,
            "fitted_link": plan["model"]["link"],
            "backend": "statsmodels.miscmodels.ordinal_model.OrderedModel",
            "backend_version": __import__("statsmodels").__version__,
            "optimizer": "bfgs",
            "predictors": list(design.columns),
            "crossed_random_effects_planned": plan["model"]["random_effects"],
            "crossed_random_effects_fitted": hierarchy_fitted,
            "fixture_approximation": plan["model"]["fixture_approximation"],
        },
        "effect_estimates": [effect],
        "model_diagnostics": {
            "converged": converged,
            "iterations": int(fit.mle_retvals.get("iterations", 0)),
            "nobs": int(fit.nobs),
            "log_likelihood": float(fit.llf),
            "aic": float(fit.aic),
            "bic": float(fit.bic),
            "probability_rows_sum_to_one": bool(
                np.allclose(probability_sums, 1.0, atol=1e-10)
            ),
            "optimizer_warnings": caught,
            "double_group_holdout": holdouts,
            "zero_variance_features": zero_variance_features,
            "feature_scaling": "training_fold_only",
            "missing_feature_values": {
                column: int(frame[column].isna().sum()) for column in feature_columns
            },
            "research_model_eligible": False,
        },
        "sensitivity_results": [
            _continuous_sensitivity(frame, list(design.columns))
        ],
        "work_packages": {
            "WP1": {
                "status": "synthetic_recovery_only",
                "ordinal_route_verified": True,
                "hierarchical_research_model_fitted": hierarchy_fitted,
            },
            "WP2": {
                "status": "hypothesis_context_only",
                "participant_exposure_attached": False,
                "causal_claim_allowed": False,
            },
            "WP3": {
                "status": "blocked",
                "incremental_visual_model_fitted": False,
                "blockers": ["VISUAL_FEATURE_VARIATION_INSUFFICIENT"],
            },
            "WP4": _han_inference_boundary(Path(workspace_root).resolve()),
        },
        "inclusion_exclusion_flow": {
            "generated": join_audit["input_rows"]["generated_ratings"],
            "excluded_by_quality": join_audit["filters"]["excluded_by_quality"],
            "missing_response": join_audit["filters"]["missing_response"],
            "analyzed": join_audit["final_rows"],
        },
        "limitations": [
            "SYNTHETIC / DEMO responses are generated and are not human evidence.",
            "All experiment stimuli resolve to one source stimulus, so visual increment is not identifiable.",
            "The fixture fit is ordered logit without crossed random effects; the preregistered hierarchy remains required for real data.",
            "WP2 is not participant exposure and cannot support a causal preference claim.",
            "WP4 has no independent real exemplars or approved expert review and remains instance-level.",
        ],
        "join_audit_sha256": hashlib.sha256(canonical_json(join_audit)).hexdigest(),
    }
    result["result_sha256"] = hashlib.sha256(canonical_json(result)).hexdigest()
    return result
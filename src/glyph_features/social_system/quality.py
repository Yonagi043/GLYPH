"""Field-level agreement calculations for social-narrative release gates."""

from __future__ import annotations

import math
from typing import Any, Callable

import krippendorff
import numpy as np


ALPHA_THRESHOLD = 0.80


def _nominal_alpha(
    annotations: list[dict[str, Any]],
    observation_ids: list[str],
    value: Callable[[dict[str, Any]], Any],
) -> float | None:
    coder_ids = sorted({row["coder_id"] for row in annotations})
    value_domain = sorted({value(row) for row in annotations}, key=str)
    if len(coder_ids) < 2 or len(observation_ids) < 2 or len(value_domain) < 2:
        return None
    encoded = {candidate: index for index, candidate in enumerate(value_domain)}
    coder_index = {coder_id: index for index, coder_id in enumerate(coder_ids)}
    observation_index = {
        observation_id: index for index, observation_id in enumerate(observation_ids)
    }
    reliability_data = np.full((len(coder_ids), len(observation_ids)), np.nan)
    for row in annotations:
        observation_id = row["observation_id"]
        if observation_id not in observation_index:
            continue
        reliability_data[
            coder_index[row["coder_id"]], observation_index[observation_id]
        ] = encoded[value(row)]
    alpha = float(
        krippendorff.alpha(
            reliability_data=reliability_data,
            level_of_measurement="nominal",
        )
    )
    return alpha if math.isfinite(alpha) else None


def build_agreement_report(annotations: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for annotation in annotations:
        grouped.setdefault(annotation["observation_id"], []).append(annotation)
    observation_ids = sorted(
        observation_id
        for observation_id, rows in grouped.items()
        if len({row["coder_id"] for row in rows}) >= 2
    )
    sampled = [
        row for row in annotations if row["observation_id"] in observation_ids
    ]
    report: dict[str, Any] = {
        "object_label": {
            "alpha": _nominal_alpha(
                sampled,
                observation_ids,
                lambda row: f"{row['object_type']}/{row['object_label']}",
            ),
            "unit_count": len(observation_ids),
        },
        "stance": {
            "alpha": _nominal_alpha(
                sampled, observation_ids, lambda row: row["stance"]
            ),
            "unit_count": len(observation_ids),
        },
        "aesthetic_terms": {},
    }
    terms = sorted(
        {
            term
            for row in sampled
            for term in row.get("aesthetic_terms") or []
        }
    )
    for term in terms:
        report["aesthetic_terms"][term] = {
            "alpha": _nominal_alpha(
                sampled,
                observation_ids,
                lambda row, term=term: int(term in (row.get("aesthetic_terms") or [])),
            ),
            "unit_count": len(observation_ids),
        }
    return report


def agreement_passes(report: dict[str, Any]) -> bool:
    results = [
        report["object_label"]["alpha"],
        report["stance"]["alpha"],
        *(
            item["alpha"]
            for item in report["aesthetic_terms"].values()
        ),
    ]
    return bool(results) and all(
        alpha is not None and alpha >= ALPHA_THRESHOLD for alpha in results
    )

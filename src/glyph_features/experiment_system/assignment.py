"""Deterministic constrained assignments for synthetic experiment dry-runs."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from itertools import permutations
from typing import Any, Iterable

from .schema import canonical_sha256


SCRIPTS = ("latin", "han", "kana", "hangul")
ANCHOR_SCRIPT_PAIRS = (
    (0, 1),
    (2, 3),
    (0, 2),
    (1, 3),
    (2, 3),
    (0, 1),
    (1, 3),
    (0, 2),
)


class AssignmentError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def _rank(seed: str, *parts: object) -> str:
    payload = "\x1f".join((seed, *(str(part) for part in parts)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_assignments(
    participants: Iterable[dict[str, str]],
    stimuli: list[dict[str, Any]],
    *,
    study_id: str,
    questionnaire_version: str,
    seed: str,
    block_size: int = 8,
    minimum_anchor_count: int = 1,
    required_anchor_count: int | None = None,
    created_at: str = "2026-09-04T00:00:00Z",
) -> list[dict[str, Any]]:
    if block_size % len(SCRIPTS) != 0:
        raise AssignmentError("BLOCK_SIZE_NOT_SCRIPT_BALANCED", str(block_size))
    per_script = block_size // len(SCRIPTS)
    by_script = {script: [item for item in stimuli if item["writing_system"] == script] for script in SCRIPTS}
    if any(len(items) < per_script for items in by_script.values()):
        raise AssignmentError("INSUFFICIENT_SCRIPT_STIMULI", f"need {per_script} per script")
    anchor_threshold = required_anchor_count if required_anchor_count is not None else minimum_anchor_count
    if sum(bool(item["is_anchor"]) for item in stimuli) < anchor_threshold:
        raise AssignmentError("INSUFFICIENT_ANCHOR_STIMULI", f"need {anchor_threshold} anchors")
    anchor_scripts = [script for script in SCRIPTS if any(item["is_anchor"] for item in by_script[script])]
    exact_four_item_design = (
        per_script == 2
        and all(len(by_script[script]) == 4 for script in SCRIPTS)
        and all(sum(bool(item["is_anchor"]) for item in by_script[script]) == 1 for script in SCRIPTS)
        and len({item["work_id"] for item in stimuli}) == len(stimuli)
    )
    participant_rows = sorted(participants, key=lambda item: item["participant_id"])
    if len({item["participant_id"] for item in participant_rows}) != len(participant_rows):
        raise AssignmentError("DUPLICATE_PARTICIPANT_ID", "participant IDs must be unique")

    exposure: dict[str, Counter[str]] = defaultdict(Counter)
    positions: dict[str, Counter[tuple[str, int]]] = defaultdict(Counter)
    group_sequences: Counter[str] = Counter()
    anchor_event_counts: Counter[tuple[str, str]] = Counter()
    nonanchor_event_counts: Counter[tuple[str, str]] = Counter()
    assignments: list[dict[str, Any]] = []
    for participant in participant_rows:
        participant_id = participant["participant_id"]
        group = participant["participant_group"]
        group_sequence = group_sequences[group]
        rotation = (group_sequence + int(_rank(seed, group)[:4], 16)) % len(SCRIPTS)
        script_order = [SCRIPTS[(rotation + offset) % len(SCRIPTS)] for offset in range(block_size)]
        slots = {script: [index + 1 for index, value in enumerate(script_order) if value == script] for script in SCRIPTS}
        selected_by_script: dict[str, list[dict[str, Any]]] = {}
        selected_work_ids: set[str] = set()
        for script in SCRIPTS:
            candidate_slots = slots[script]
            candidates = [item for item in by_script[script] if item["work_id"] not in selected_work_ids]
            if len(anchor_scripts) == len(SCRIPTS):
                anchor_required = anchor_scripts.index(script) in ANCHOR_SCRIPT_PAIRS[group_sequence % len(ANCHOR_SCRIPT_PAIRS)]
            else:
                anchor_required = script in anchor_scripts and (
                    len(anchor_scripts) == 1
                    or (group_sequence + anchor_scripts.index(script)) % 2 == 0
                )
            if exact_four_item_design:
                anchor = next(item for item in by_script[script] if item["is_anchor"])
                nonanchors = sorted(
                    (item for item in by_script[script] if not item["is_anchor"]),
                    key=lambda item: _rank(seed, script, item["stimulus_id"], "nonanchor-order"),
                )
                event_key = (group, script)
                if anchor_required:
                    nonanchor_index = (anchor_event_counts[event_key] + 1) % len(nonanchors)
                    chosen = [anchor, nonanchors[nonanchor_index]]
                    anchor_event_counts[event_key] += 1
                else:
                    rotation_cycle = group_sequence // len(SCRIPTS)
                    omitted_index = (nonanchor_event_counts[event_key] + 2 * rotation_cycle) % len(nonanchors)
                    chosen = [item for index, item in enumerate(nonanchors) if index != omitted_index]
                    nonanchor_event_counts[event_key] += 1
                direct = sum(
                    positions[group][(item["stimulus_id"], position)]
                    for item, position in zip(chosen, candidate_slots, strict=True)
                )
                swapped = sum(
                    positions[group][(item["stimulus_id"], position)]
                    for item, position in zip(reversed(chosen), candidate_slots, strict=True)
                )
                if swapped < direct:
                    chosen.reverse()
                selected_by_script[script] = chosen
                selected_work_ids.update(item["work_id"] for item in chosen)
                continue
            ordered_options = [
                option
                for option in permutations(candidates, per_script)
                if len({item["work_id"] for item in option}) == per_script
                and (
                    any(item["is_anchor"] for item in option)
                    if anchor_required
                    else not any(item["is_anchor"] for item in option)
                )
            ]
            if not ordered_options:
                raise AssignmentError("WORK_CONSTRAINT_UNSATISFIABLE", f"{participant_id}:{script}")
            chosen = min(
                ordered_options,
                key=lambda option: _projected_balance_score(
                    option,
                    candidate_slots,
                    by_script[script],
                    exposure[group],
                    positions[group],
                    block_size,
                    seed,
                    participant_id,
                    script,
                ),
            )
            selected_by_script[script] = list(chosen)
            selected_work_ids.update(item["work_id"] for item in chosen)

        selected_anchor_count = sum(bool(item["is_anchor"]) for chosen in selected_by_script.values() for item in chosen)
        if required_anchor_count is not None and selected_anchor_count != required_anchor_count:
            raise AssignmentError(
                "ANCHOR_COUNT_UNSATISFIABLE",
                f"{participant_id}: {selected_anchor_count} != {required_anchor_count}",
            )
        if selected_anchor_count < minimum_anchor_count:
            raise AssignmentError("ANCHOR_CONSTRAINT_UNSATISFIABLE", participant_id)

        ordered: list[dict[str, Any] | None] = [None] * block_size
        for script in SCRIPTS:
            chosen = selected_by_script[script]
            candidate_slots = slots[script]
            for trial_index, item in zip(candidate_slots, chosen, strict=True):
                ordered[trial_index - 1] = item

        trials: list[dict[str, Any]] = []
        for trial_index, item in enumerate(ordered, start=1):
            if item is None:
                raise AssignmentError("ASSIGNMENT_INTERNAL_GAP", participant_id)
            exposure[group][item["stimulus_id"]] += 1
            positions[group][(item["stimulus_id"], trial_index)] += 1
            trials.append({
                "presentation_id": f"presentation_{_rank(seed, participant_id, trial_index, item['stimulus_id'])[:24]}",
                "trial_index": trial_index,
                "stimulus_id": item["stimulus_id"],
                "source_stimulus_id": item["source_stimulus_id"],
                "work_id": item["work_id"],
                "writing_system": item["writing_system"],
                "is_anchor": item["is_anchor"],
                "asset_path": item["asset"]["path"],
                "asset_sha256": item["asset"]["sha256"],
                "condition": "visual_blind",
            })
        group_sequences[group] += 1
        assignments.append({
            "schema_version": "1.0.0",
            "assignment_id": f"assignment_{_rank(seed, study_id, participant_id)[:24]}",
            "study_id": study_id,
            "protocol_version": "1.0.0",
            "questionnaire_version": questionnaire_version,
            "participant_id": participant_id,
            "data_origin": participant["data_origin"],
            "participant_group": group,
            "block_id": f"block_{_rank(seed, participant_id, 'block')[:24]}",
            "seed_sha256": canonical_sha256({"namespace": seed, "participant_id": participant_id}),
            "assignment_probability": block_size / len(stimuli),
            "quota_snapshot": {"group_sequence": group_sequence, "group_assignment_count_before": group_sequence},
            "trials": trials,
            "status": "assigned",
            "resume_next_trial": 1,
            "created_at": created_at,
        })
    return assignments


def _projected_balance_score(
    option: tuple[dict[str, Any], ...],
    candidate_slots: list[int],
    script_stimuli: list[dict[str, Any]],
    exposure: Counter[str],
    positions: Counter[tuple[str, int]],
    block_size: int,
    seed: str,
    participant_id: str,
    script: str,
) -> tuple[int, int, int, int, str]:
    option_ids = {item["stimulus_id"] for item in option}
    projected_positions = {
        (item["stimulus_id"], position)
        for item, position in zip(option, candidate_slots, strict=True)
    }
    exposure_values: list[int] = []
    maximum_position_spread = 0
    exposure_square_sum = 0
    position_square_sum = 0
    for item in script_stimuli:
        stimulus_id = item["stimulus_id"]
        projected_exposure = exposure[stimulus_id] + int(stimulus_id in option_ids)
        exposure_values.append(projected_exposure)
        exposure_square_sum += projected_exposure * projected_exposure
        position_values = [
            positions[(stimulus_id, position)] + int((stimulus_id, position) in projected_positions)
            for position in range(1, block_size + 1)
        ]
        maximum_position_spread = max(maximum_position_spread, max(position_values) - min(position_values))
        position_square_sum += sum(value * value for value in position_values)
    return (
        max(exposure_values) - min(exposure_values),
        maximum_position_spread,
        exposure_square_sum,
        position_square_sum,
        _rank(seed, participant_id, script, *(item["stimulus_id"] for item in option)),
    )


def audit_assignments(
    assignments: list[dict[str, Any]],
    stimuli: list[dict[str, Any]],
    *,
    block_size: int,
    balance_tolerance: int,
    minimum_anchor_count: int = 1,
    required_anchor_count: int | None = None,
    study_id: str | None = None,
    catalog_study_id: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if study_id is not None:
        if catalog_study_id != study_id:
            errors.append(f"STUDY_ID_MISMATCH:catalog:{catalog_study_id!r}")
        errors.extend(
            f"STUDY_ID_MISMATCH:{assignment.get('assignment_id', 'unknown')}:{assignment.get('study_id')!r}"
            for assignment in assignments
            if assignment.get("study_id") != study_id
        )
    assignment_ids = [row["assignment_id"] for row in assignments]
    participant_ids = [row["participant_id"] for row in assignments]
    if len(assignment_ids) != len(set(assignment_ids)):
        errors.append("DUPLICATE_ASSIGNMENT_ID")
    if len(participant_ids) != len(set(participant_ids)):
        errors.append("DUPLICATE_PARTICIPANT_ID")
    catalog_by_id = {item["stimulus_id"]: item for item in stimuli}
    expected_ids = set(catalog_by_id)
    if len(catalog_by_id) != len(stimuli):
        errors.append("DUPLICATE_CATALOG_STIMULUS_ID")
    group_exposure: dict[str, Counter[str]] = defaultdict(Counter)
    group_positions: dict[str, Counter[tuple[str, int]]] = defaultdict(Counter)
    presentation_ids: set[str] = set()
    for assignment in assignments:
        trials = assignment["trials"]
        if len(trials) != block_size:
            errors.append(f"BLOCK_SIZE_MISMATCH:{assignment['assignment_id']}")
        trial_indices = [trial["trial_index"] for trial in trials]
        if sorted(trial_indices) != list(range(1, block_size + 1)):
            errors.append(f"TRIAL_INDEX_SET_MISMATCH:{assignment['assignment_id']}")
        stimulus_ids = [trial["stimulus_id"] for trial in trials]
        work_ids = [trial["work_id"] for trial in trials]
        if len(stimulus_ids) != len(set(stimulus_ids)):
            errors.append(f"DUPLICATE_STIMULUS:{assignment['assignment_id']}")
        if len(work_ids) != len(set(work_ids)):
            errors.append(f"DUPLICATE_WORK:{assignment['assignment_id']}")
        selected_anchor_count = sum(bool(trial["is_anchor"]) for trial in trials)
        if required_anchor_count is not None and selected_anchor_count != required_anchor_count:
            errors.append(
                f"ANCHOR_COUNT_MISMATCH:{assignment['assignment_id']}:{selected_anchor_count}"
            )
        elif selected_anchor_count < minimum_anchor_count:
            errors.append(f"MISSING_ANCHOR:{assignment['assignment_id']}")
        scripts = [trial["writing_system"] for trial in trials]
        if any(left == right for left, right in zip(scripts, scripts[1:])):
            errors.append(f"SCRIPT_RUN_EXCEEDED:{assignment['assignment_id']}")
        for trial in trials:
            catalog_item = catalog_by_id.get(trial["stimulus_id"])
            if catalog_item is None:
                errors.append(f"UNKNOWN_STIMULUS:{assignment['assignment_id']}:{trial['stimulus_id']}")
            else:
                expected_metadata = {
                    "source_stimulus_id": catalog_item["source_stimulus_id"],
                    "work_id": catalog_item["work_id"],
                    "writing_system": catalog_item["writing_system"],
                    "is_anchor": catalog_item["is_anchor"],
                    "asset_path": catalog_item["asset"]["path"],
                    "asset_sha256": catalog_item["asset"]["sha256"],
                }
                errors.extend(
                    f"CATALOG_METADATA_MISMATCH:{assignment['assignment_id']}:{trial['presentation_id']}:{field}"
                    for field, expected in expected_metadata.items()
                    if trial.get(field) != expected
                )
            if trial["presentation_id"] in presentation_ids:
                errors.append(f"DUPLICATE_PRESENTATION_ID:{trial['presentation_id']}")
            presentation_ids.add(trial["presentation_id"])
            group = assignment["participant_group"]
            group_exposure[group][trial["stimulus_id"]] += 1
            group_positions[group][(trial["stimulus_id"], trial["trial_index"])] += 1
    max_exposure_spread = 0
    max_position_spread = 0
    for group, counts in group_exposure.items():
        values = [counts[stimulus_id] for stimulus_id in sorted(expected_ids)]
        spread = max(values) - min(values)
        max_exposure_spread = max(max_exposure_spread, spread)
        if spread > balance_tolerance:
            errors.append(f"EXPOSURE_IMBALANCE:{group}:{spread}")
        for stimulus_id in expected_ids:
            position_values = [group_positions[group][(stimulus_id, position)] for position in range(1, block_size + 1)]
            position_spread = max(position_values) - min(position_values)
            max_position_spread = max(max_position_spread, position_spread)
            if position_spread > balance_tolerance:
                errors.append(f"POSITION_IMBALANCE:{group}:{stimulus_id}:{position_spread}")
    result = {
        "valid": not errors,
        "errors": errors,
        "assignment_count": len(assignments),
        "trial_count": sum(len(row["trials"]) for row in assignments),
        "unique_presentation_count": len(presentation_ids),
        "max_group_stimulus_exposure_spread": max_exposure_spread,
        "max_stimulus_position_spread": max_position_spread,
        "summary_sha256": canonical_sha256(assignments),
    }
    if study_id is not None:
        result["study_id"] = study_id
    return result
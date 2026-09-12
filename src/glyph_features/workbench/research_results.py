"""Descriptive comparisons and traceable evidence for actual persona calls."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
import zipfile
from itertools import combinations
from pathlib import Path

from fontTools.ttLib import TTFont

from glyph_features.asset_system.catalog import canonical_json, sha256_file

from .personas import PersonaExecutor, write_once
from .research import QUESTIONNAIRE_SCALES, ResearchService
from .releases import _csv_safe


def evidence_for_run(research: ResearchService, run: dict) -> dict:
    route = research.materials.root / "AUTORESEARCH.md"
    literature = []
    if route.is_file():
        for line_number, line in enumerate(route.read_text(encoding="utf-8").splitlines(), 1):
            if any(line.startswith(f"| E-{number:03d} /") for number in range(1, 7)):
                literature.append({
                    "evidence_id": line.split(" /", 1)[0].strip("| "),
                    "source_document": "AUTORESEARCH.md", "line": line_number,
                    "source_document_sha256": sha256_file(route), "original_record": line,
                    "use": "Previously verified contextual evidence, not new full-text verification or evidence of this model's causal mechanism.",
                })
    han_path = research.workspace_root / "data/fixtures/han_style_system/reference_run_v1/candidate_bundle/stimulus_candidates.jsonl"
    candidates = [json.loads(line) for line in han_path.read_text(encoding="utf-8").splitlines() if line]
    instances = []
    for record in run["snapshot"]["materials"]:
        material = record["material"]
        sample = material.get("sample_provenance")
        matches = [candidate for candidate in candidates if material["material_id"] in candidate.get("representation_asset_ids", {}).values()]
        entry = {
            "material_id": material["material_id"],
            "task04_matches": matches,
            "gaps": ["NO_ASSET_SPECIFIC_VERIFIED_CULTURAL_NARRATIVE"],
        }
        if not matches:
            entry["gaps"].append("NO_MATCHED_TASK04_EXPERT_REVIEWED_GLYPH_INSTANCE")
        if sample:
            font_path = research.materials.safe_path(sample["font_ref"]["path"])
            if sha256_file(font_path) == sample["font_ref"]["sha256"]:
                with TTFont(font_path) as font:
                    cmap = font.getBestCmap()
                    entry["character_mapping"] = [{"character": character, "unicode": f"U+{ord(character):04X}", "glyph_name": cmap.get(ord(character))} for character in dict.fromkeys(sample["content"]) if not character.isspace()]
                entry["font_ref"] = sample["font_ref"]
                entry["scope"] = "Current font cmap and rendered sample instance; not historical calligraphic classification."
            else:
                entry["gaps"].append("FONT_CHANGED_SINCE_STUDY")
        elif record["selection"].get("foreground", "unconfirmed") == "unconfirmed":
            entry["gaps"].append("COMMERCIAL_GLYPH_REGION_NOT_VERIFIED")
        else:
            entry["region_observation"] = {"foreground": record["selection"]["foreground"], "note": record["selection"]["foreground_note"], "scope": "Agent visual observation, not historical or expert verification."}
        instances.append(entry)
    return {
        "literature": literature,
        "specific_sources": run["snapshot"].get("specific_evidence", {"entries": []}),
        "instances": instances,
        "task04_source": {"path": str(han_path), "sha256": sha256_file(han_path), "candidate_count": len(candidates), "matched_by": "exact representation asset ID only"},
        "social_evidence": {"status": "no_applicable_validated_export_selected", "production_database_accessed": False, "gap": "No asset-specific cultural source or measured individual exposure; model associations remain post-rating descriptions."},
    }


def eligible_rows(tasks: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    rows = []
    excluded = []
    attempts = []
    for task in tasks:
        attempts.extend(task["attempts"])
        accepted = [attempt for attempt in task["attempts"] if attempt["evidence"].get("analysis_eligible") is True and attempt["status"] in {"completed", "completed_with_missing"}]
        if len(accepted) != 1:
            excluded.append({"task_id": task["task_id"], "status": task["status"], "reason": "NO_UNAMBIGUOUS_PROTOCOL_ELIGIBLE_RETURN", "actual_attempts": len(task["attempts"])})
            continue
        attempt = accepted[0]
        for rating in attempt["ratings"]:
            sequence = [image["material_id"] for image in task.get("inputs", [])]
            rows.append({"task_id": task["task_id"], "host_call_id": attempt["host_call_id"], "data_type": "synthetic_persona", **task["condition"], "presentation_sequence": sequence, "presentation_position": sequence.index(rating["material_id"]) + 1 if rating["material_id"] in sequence else None, "set_size": len(sequence) if sequence else None, "model_display_name": attempt["evidence"]["model_display_name"], **rating})
    return rows, excluded, attempts


def representation_comparison(run: dict, rows: list[dict], reference: dict | None, reference_tasks: list[dict]) -> dict:
    if reference is None:
        return {"reference_run_id": None, "pairs": [], "unmatched": []}
    reference_rows, reference_excluded, reference_attempts = eligible_rows(reference_tasks)
    input_by_id = {record["selection"]["material_id"]: record for record in run["snapshot"]["materials"]}
    reference_by_id = {record["selection"]["material_id"]: record for record in reference["snapshot"]["materials"]}
    fields = ("material_id", "role", "order", "repetition", "language", "wording", "model_display_name")
    pairs, unmatched = [], []
    for row in rows:
        matches = [other for other in reference_rows if all(other[field] == row[field] for field in fields) and other.get("questionnaire_mode", "q2") == row.get("questionnaire_mode", "q2")]
        if len(matches) != 1 or row.get("aesthetic") is None or matches[0].get("aesthetic") is None:
            unmatched.append({"task_id": row["task_id"], "material_id": row["material_id"], "reason": "NO_UNIQUE_OBSERVED_REFERENCE"})
            continue
        current_input = input_by_id[row["material_id"]]
        previous_input = reference_by_id[row["material_id"]]
        same_parent = current_input.get("source_input_sha256") == previous_input.get("source_input_sha256")
        if not same_parent or current_input["input_sha256"] == previous_input["input_sha256"]:
            unmatched.append({"task_id": row["task_id"], "material_id": row["material_id"], "reason": "NOT_A_DIFFERENT_REPRESENTATION_OF_SAME_INPUT"})
            continue
        pairs.append({**{field: row[field] for field in fields}, "task_id": row["task_id"], "reference_task_id": matches[0]["task_id"],
                      "input_sha256": current_input["input_sha256"], "reference_input_sha256": previous_input["input_sha256"],
                      "aesthetic": row["aesthetic"], "reference_aesthetic": matches[0]["aesthetic"], "difference": row["aesthetic"] - matches[0]["aesthetic"],
                      "questionnaire_mode": row.get("questionnaire_mode", "q2"), "premium_positioning": row.get("premium_positioning"), "reference_premium_positioning": matches[0].get("premium_positioning"),
                      "premium_difference": row["premium_positioning"] - matches[0]["premium_positioning"] if row.get("premium_positioning") is not None and matches[0].get("premium_positioning") is not None else None})
    return {"reference_run_id": reference["run_id"], "reference_actual_calls": len(reference_attempts), "reference_planned_tasks": len(reference_tasks),
            "reference_excluded_tasks": reference_excluded, "reference_rows": reference_rows, "reference_tasks_and_raw_returns": reference_tasks,
            "pairs": pairs, "unmatched": unmatched,
            "scope": "Current minus reference under recorded matched prompt conditions; representation, crop/content, displayed scale and separate-call/batch variation remain confounded. Auto labels do not establish identical models."}


def summarize_representation_pairs(comparison: dict, materials: list[dict]) -> dict:
    work_by_material = {record["selection"]["material_id"]: record["material"].get("work_id") for record in materials}
    grouped = {}
    ungrouped = []
    for pair in comparison["pairs"]:
        work_id = work_by_material.get(pair["material_id"])
        if not work_id:
            ungrouped.append(pair)
            continue
        grouped.setdefault(work_id, []).append(pair)
    works = []
    for work_id, pairs in grouped.items():
        conditions = {}
        for pair in pairs:
            key = tuple(pair.get(field) for field in ("role", "order", "repetition", "language", "wording", "model_display_name"))
            conditions.setdefault(key, []).append(pair["difference"])
        differences = [statistics.mean(values) for values in conditions.values()]
        works.append({
            "work_id": work_id, "material_ids": sorted({pair["material_id"] for pair in pairs}),
            "paired_rows": len(pairs), "matched_conditions": len(conditions),
            "mean_difference": statistics.mean(differences), "median_difference": statistics.median(differences),
            "range_difference": [min(differences), max(differences)],
            "negative_conditions": sum(value < 0 for value in differences),
            "tied_conditions": sum(value == 0 for value in differences),
            "positive_conditions": sum(value > 0 for value in differences),
            "pairs": pairs,
        })
    means = [work["mean_difference"] for work in works]
    leave_one_out = [{"omitted_work_id": work["work_id"], "mean_difference": statistics.mean(other["mean_difference"] for other in works if other["work_id"] != work["work_id"])} for work in works] if len(works) > 1 else []
    return {
        "works": works, "observed_work_count": len(works), "ungrouped_pairs": ungrouped,
        "equal_work_mean_difference": statistics.mean(means) if means else None,
        "negative_works": sum(value < 0 for value in means), "tied_works": sum(value == 0 for value in means),
        "positive_works": sum(value > 0 for value in means), "leave_one_work_out": leave_one_out,
        "scope": "Descriptive current minus reference. First average inputs within each work and matched condition, then conditions, then give each observed work equal weight. Missing work IDs are not invented. Leave-one-work-out is sensitivity, not a confidence interval; works are selected cases, calls are shared-model repetitions, not humans.",
    }


def summarize_font_pairs(pairs: list[dict], materials: list[dict]) -> list[dict]:
    by_material = {record["selection"]["material_id"]: record["material"] for record in materials}
    groups = {}
    fields = ("reference_material_id", "comparison_material_id", "role", "language", "wording", "model_display_name")
    for pair in pairs:
        groups.setdefault(tuple(pair[field] for field in fields), []).append(pair)
    summaries = []
    for key, matched in groups.items():
        differences = [pair["differences"]["aesthetic"] for pair in matched if pair["differences"]["aesthetic"] is not None]
        clarity = [pair["differences"]["visual_clarity"] for pair in matched if pair["differences"]["visual_clarity"] is not None]
        order_means = {}
        for order in dict.fromkeys(["forward", "reverse", *[pair["order"] for pair in matched]]):
            values = [pair["differences"]["aesthetic"] for pair in matched if pair["order"] == order and pair["differences"]["aesthetic"] is not None]
            order_means[order] = statistics.mean(values) if values else None
        summaries.append({**dict(zip(fields, key)), "content": by_material[key[0]]["sample_provenance"]["content"],
                          "reference_title": by_material[key[0]]["source"].get("title", key[0]), "comparison_title": by_material[key[1]]["source"].get("title", key[1]),
                          "matched_pairs": len(differences), "mean_aesthetic_difference": statistics.mean(differences) if differences else None,
                          "aesthetic_differences": differences, "negative_pairs": sum(value < 0 for value in differences), "tied_pairs": sum(value == 0 for value in differences), "positive_pairs": sum(value > 0 for value in differences),
                          "mean_clarity_difference": statistics.mean(clarity) if clarity else None, "order_mean_differences": order_means, "pairs": matched})
    return summaries


def summarize_presentation_pairs(pairs: list[dict]) -> dict:
    explicit = [pair for pair in pairs if pair.get("group_id") is not None]
    matched_sets = []
    for pair in explicit:
        if pair["set_size"] != 3:
            continue
        fields = ("group_id", "reference_material_id", "comparison_material_id", "reference_position", "comparison_position", "role", "repetition", "language", "wording", "model_display_name")
        matches = [other for other in explicit if other["set_size"] == 2 and all(other.get(field) == pair.get(field) for field in fields)]
        if len(matches) == 1:
            reference = matches[0]
            left, right = reference["differences"]["aesthetic"], pair["differences"]["aesthetic"]
            matched_sets.append({**{field: pair.get(field) for field in fields}, "triple_task_id": pair["task_id"], "pair_task_id": reference["task_id"], "triple_difference": right, "pair_difference": left, "difference_of_differences": right - left if right is not None and left is not None else None})
    return {"pairs": explicit, "matched_slot_set_contrasts": matched_sets, "scope": "Exact focal positions and relative order matched. Set size, third image and call variation still co-vary; no pure third-font effect. Other slots have no two-item match."}


def summarize_measurement_bridge(rows: list[dict]) -> dict:
    bridge = [row for row in rows if row.get("questionnaire_mode", "q2") != "q2"]
    contrasts, unmatched = [], []
    fields = ("material_id", "role", "repetition", "language", "wording", "model_display_name", "presentation_sequence", "presentation_position")
    for row in bridge:
        mode = row["questionnaire_mode"]
        for scale, reference_mode in (("aesthetic", "aesthetic_only"), ("premium_positioning", "premium_only"), ("aesthetic", "aesthetic_premium"), ("premium_positioning", "aesthetic_premium")):
            if mode not in {"aesthetic_premium", "premium_aesthetic"} or mode == reference_mode or not any(other["questionnaire_mode"] == reference_mode for other in bridge):
                continue
            matches = [other for other in bridge if other["questionnaire_mode"] == reference_mode and all(other.get(field) == row.get(field) for field in fields)]
            base = {**{field: row.get(field) for field in fields}, "task_id": row["task_id"], "outcome": scale, "condition": mode, "reference_condition": reference_mode}
            if len(matches) != 1 or row.get(scale) is None or matches[0].get(scale) is None:
                unmatched.append({**base, "reason": "NO_UNIQUE_OBSERVED_REFERENCE"})
                continue
            reference = matches[0]
            contrasts.append({**base, "reference_task_id": reference["task_id"], "value": row[scale], "reference_value": reference[scale], "difference": row[scale] - reference[scale]})
    return {"rows": bridge, "contrasts": contrasts, "unmatched": unmatched,
            "joint_rows": [row for row in bridge if row.get("aesthetic") is not None and row.get("premium_positioning") is not None],
            "scope": "Paired by material, presentation and recorded prompt conditions; separate calls still vary. Only joint_rows contain same-call measurements of both outcomes. No pooling with q2 or treating unasked outcomes as missing."}


def analyze_research(research: ResearchService, executor: PersonaExecutor, run_id: str) -> dict:
    run = research.get(run_id)
    tasks = executor.tasks(run_id)
    rows, excluded, attempts = eligible_rows(tasks)
    material_summaries = []
    for record in run["snapshot"]["materials"]:
        material_id = record["selection"]["material_id"]
        material_tasks = [task for task in tasks if any(image["material_id"] == material_id for image in task["inputs"])]
        planned = sum("aesthetic" in QUESTIONNAIRE_SCALES[task["condition"].get("questionnaire_mode", "q2")] for task in material_tasks)
        observed = [row["aesthetic"] for row in rows if row["material_id"] == material_id and row.get("aesthetic") is not None]
        outcome_summaries = []
        for mode in dict.fromkeys(task["condition"].get("questionnaire_mode", "q2") for task in material_tasks):
            condition_tasks = [task for task in material_tasks if task["condition"].get("questionnaire_mode", "q2") == mode]
            for scale in ("aesthetic", "premium_positioning", "visual_clarity"):
                asked = scale in QUESTIONNAIRE_SCALES[mode]
                values = [row[scale] for row in rows if row["material_id"] == material_id and row.get("questionnaire_mode", "q2") == mode and row.get(scale) is not None]
                outcome_summaries.append({"questionnaire_mode": mode, "outcome": scale, "status": "collected_or_pending" if asked else "not_collected", "planned": len(condition_tasks) if asked else 0, "observed": len(values), "missing_or_unexecuted": len(condition_tasks) - len(values) if asked else 0, "values": values, "median": statistics.median(values) if values else None, "range": [min(values), max(values)] if values else None})
        measurement = next((item for item in run["measurements"] or [] if item["material_id"] == material_id), None)
        sensitivity = []
        if measurement and measurement["status"] == "measured":
            for code in measurement["thresholds"][0]["metrics"]:
                values = [entry["metrics"][code]["value"] for entry in measurement["thresholds"]]
                numeric = [value for value in values if isinstance(value, (int, float))]
                sensitivity.append({"feature": code, "thresholds": [entry["threshold"] for entry in measurement["thresholds"]], "values": values, "range": max(numeric) - min(numeric) if numeric else None})
        material_summaries.append({
            "material_id": material_id, "title": record["material"]["source"].get("title", material_id),
            "planned_observations": planned, "observed_aesthetic": len(observed),
            "total_presentations": len(material_tasks), "outcomes_by_condition": outcome_summaries,
            "missing_or_unexecuted": planned - len(observed),
            "median_aesthetic": statistics.median(observed) if observed else None,
            "range_aesthetic": [min(observed), max(observed)] if observed else None,
            "measurement": measurement, "threshold_sensitivity": sensitivity,
        })
    identity_differences = []
    repeat_differences = []
    order_differences = []
    for row in rows:
        if row.get("aesthetic") is None:
            continue
        match_fields = ("material_id", "order", "repetition", "language", "wording", "model_display_name")
        if row["role"] != "baseline":
            baselines = [other for other in rows if other["role"] == "baseline" and all(other[field] == row[field] for field in match_fields) and other.get("aesthetic") is not None]
            if len(baselines) == 1:
                identity_differences.append({"material_id": row["material_id"], "task_id": row["task_id"], "reference_task_id": baselines[0]["task_id"], "role": row["role"], "difference": row["aesthetic"] - baselines[0]["aesthetic"], "order": row["order"], "repetition": row["repetition"]})
        if row["repetition"] > 0:
            repeat_fields = ("material_id", "order", "role", "language", "wording", "model_display_name")
            references = [other for other in rows if other["repetition"] == 0 and all(other[field] == row[field] for field in repeat_fields) and other.get("aesthetic") is not None]
            if len(references) == 1:
                repeat_differences.append({"material_id": row["material_id"], "task_id": row["task_id"], "reference_task_id": references[0]["task_id"], "difference": row["aesthetic"] - references[0]["aesthetic"]})
        if row["order"] == "reverse":
            order_fields = ("material_id", "role", "repetition", "language", "wording", "model_display_name")
            references = [other for other in rows if other["order"] == "forward" and all(other[field] == row[field] for field in order_fields) and other.get("aesthetic") is not None]
            if len(references) == 1:
                order_differences.append({"material_id": row["material_id"], "task_id": row["task_id"], "reference_task_id": references[0]["task_id"], "difference": row["aesthetic"] - references[0]["aesthetic"]})
    font_pairs = []
    for first, second in combinations(run["snapshot"]["materials"], 2):
        first_sample = first["material"].get("sample_provenance", {})
        second_sample = second["material"].get("sample_provenance", {})
        if not first_sample.get("content") or first_sample.get("content") != second_sample.get("content"):
            continue
        for task in tasks:
            first_rows = [row for row in rows if row["task_id"] == task["task_id"] and row["material_id"] == first["selection"]["material_id"]]
            second_rows = [row for row in rows if row["task_id"] == task["task_id"] and row["material_id"] == second["selection"]["material_id"]]
            if len(first_rows) != 1 or len(second_rows) != 1:
                continue
            differences = {}
            for scale in ("aesthetic", "visual_clarity"):
                left, right = first_rows[0].get(scale), second_rows[0].get(scale)
                differences[scale] = right - left if left is not None and right is not None else None
            font_pairs.append({"task_id": task["task_id"], **{field: first_rows[0][field] for field in ("role", "order", "repetition", "language", "wording", "model_display_name")}, "group_id": task["condition"].get("group_id"), "set_size": len(task["inputs"]), "reference_position": first_rows[0]["presentation_position"], "comparison_position": second_rows[0]["presentation_position"], "reference_material_id": first["selection"]["material_id"], "comparison_material_id": second["selection"]["material_id"], "differences": differences})
    paired_choices = []
    mapping = run["config"].get("design_contract", {}).get("board_mapping", {})
    for row in rows:
        if "preference_choice" not in row:
            continue
        board = mapping.get(row["material_id"], {})
        selected = next((member["material_id"] for member in board.get("members", []) if member["label"] == row["preference_choice"]), None)
        paired_choices.append({**row, "content": board.get("content"), "contrast": board.get("contrast"), "positive_label": board.get("positive_label"), "selected_material_id": selected})
    result = {
        "schema_version": "exploratory_persona_result_1", "run_id": run_id,
        "analysis_implementation_sha256": sha256_file(Path(__file__)),
        "data_type": "synthetic_persona", "primary_outcome": "aesthetic", "status": run["status"],
        "config": run["config"], "snapshot": run["snapshot"],
        "actual_calls": len(attempts), "planned_tasks": len(tasks),
        "protocol_deviation_calls": sum(attempt["status"] == "protocol_deviation" for attempt in attempts),
        "failed_calls": sum(attempt["status"] == "failed" for attempt in attempts),
        "retries": sum(max(0, len(task["attempts"]) - 1) for task in tasks),
        "visible_credits": [attempt["evidence"]["visible_credits"] for attempt in attempts],
        "credits_unit": "unknown; not currency or token count", "tokens": "unknown",
        "rows": rows, "paired_choices": paired_choices, "materials": material_summaries, "identity_differences": identity_differences,
        "repeat_differences": repeat_differences, "within_content_font_pairs": font_pairs,
        "font_comparison_summaries": summarize_font_pairs(font_pairs, run["snapshot"]["materials"]),
        "presentation_comparison": summarize_presentation_pairs(font_pairs),
        "measurement_bridge": summarize_measurement_bridge(rows),
        "order_and_call_differences": order_differences,
        "representation_comparison": representation_comparison(run, rows, run["snapshot"].get("reference_run"), executor.tasks(run["config"]["reference_run_id"]) if run["config"].get("reference_run_id") else []),
        "excluded_or_unexecuted_tasks": excluded, "tasks_and_raw_returns": tasks,
        "four_line_evidence": evidence_for_run(research, run),
        "research_assessments": [{key: value for key, value in assessment.items() if key != "basis_result"} for assessment in research.assessments(run_id)],
        "limits": [
            "Actual model responses, not human observations; multiple personas are not independent people.",
            "Comparisons match recorded host display labels only. Auto does not establish a fixed underlying model or model build.",
            "Ordinal score differences and medians are descriptive, not population effects or causal contributions.",
            "Identity, familiarity and cultural associations are not independently identified by these prompts.",
            "Order contrasts also include call variation; tool use does not establish gaze or complete inherited-context isolation.",
            "Existing font samples are controls, not substitutes for commercial material coverage. Composition measurements are not isolated glyph structure.",
            "No aesthetic composite score, historical style effect or human native-language advantage is inferred.",
        ],
    }
    result["representation_comparison"]["work_summary"] = summarize_representation_pairs(result["representation_comparison"], run["snapshot"]["materials"])
    result["result_sha256"] = hashlib.sha256(canonical_json(result)).hexdigest()
    return result


def export_research(result: dict, export_root: Path) -> dict:
    result_bytes = canonical_json(result)
    export_id = f"{result['run_id']}-{result['result_sha256'][:16]}"
    csv_buffer = io.StringIO()
    fields = ["task_id", "host_call_id", "material_id", "data_type", "role", "order", "repetition", "group_id", "design_version", "questionnaire_version", "questionnaire_mode", "presentation_position", "set_size", "language", "wording", "model_display_name", "aesthetic", "premium_positioning", "visual_clarity", "aesthetic_status", "premium_positioning_status", "visual_clarity_status", "preference_choice", "heavier_choice", "missing_reason", "visible_detail", "reason", "associations"]
    writer = csv.DictWriter(csv_buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in result["rows"]:
        scales = QUESTIONNAIRE_SCALES[row.get("questionnaire_mode", "q2")]
        statuses = {f"{scale}_status": "not_collected" if scale not in scales else "observed" if row.get(scale) is not None else "missing" for scale in ("aesthetic", "premium_positioning", "visual_clarity")}
        writer.writerow({key: _csv_safe(value) for key, value in {**row, **statuses}.items()})
    csv_bytes = csv_buffer.getvalue().encode("utf-8")
    manifest = {
        "schema_version": "internal_persona_export_1", "export_id": export_id,
        "run_id": result["run_id"], "data_type": "synthetic_persona", "purpose": "internal_research_audit",
        "formal_release": False, "images_included": False,
        "csv_formula_escaping": "existing workbench _csv_safe; unmodified values retained in result.json",
        "files": {"result.json": hashlib.sha256(result_bytes).hexdigest(), "ratings.csv": hashlib.sha256(csv_bytes).hexdigest()},
    }
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in (("result.json", result_bytes), ("ratings.csv", csv_bytes), ("manifest.json", canonical_json(manifest))):
            info = zipfile.ZipInfo(filename, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    destination = export_root / "research" / f"{export_id}.zip"
    write_once(destination, archive_buffer.getvalue())
    return {"export_id": export_id, "path": str(destination), "sha256": sha256_file(destination), "manifest": manifest}
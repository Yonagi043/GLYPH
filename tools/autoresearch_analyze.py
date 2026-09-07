"""Describe the actual persona responses and retain minimal visual-call evidence."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import numpy as np

from glyph_features.render import sha256


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/processed/autoresearch/2026-09-07-b01"
SESSION = Path.home() / "Library/Application Support/Code/User/workspaceStorage/a30f4b464838931720a428bc9b6d0362/chatSessions/81c27ae9-2185-42bd-9038-0479ddb1312e.jsonl"


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def write_json(filename: str, value: object) -> None:
    (RUN / filename).write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def collect_visual_evidence(calls: list[dict], manifest: dict, session: Path) -> list[dict]:
    events = {}
    with session.open(encoding="utf-8") as source:
        for line in source:
            for event in objects(json.loads(line)):
                if "toolId" in event and "toolCallId" in event:
                    identifier = event["toolCallId"]
                    events[identifier] = {**events.get(identifier, {}), **event}
    evidence = []
    (RUN / "raw_returns").mkdir(exist_ok=True)
    for call in calls:
        parents = [event for event in events.values() if event.get("toolId") == "runSubagent" and f"/prompts/{call['call_id']}.txt" in event.get("toolSpecificData", {}).get("prompt", "")]
        assert len(parents) == 1, (call["call_id"], "missing or ambiguous parent trace")
        parent = parents[0]
        details = parent["toolSpecificData"]
        children = [event for event in events.values() if event.get("subAgentInvocationId") == parent["toolCallId"]]
        board = manifest["boards"][call["order"]]
        views = [event for event in children if event.get("toolId") == "copilot_viewImage" and event.get("isComplete") and board["path"] in json.dumps(event.get("invocationMessage"))]
        assert views, (call["call_id"], "no completed image tool trace")
        raw = details.get("result")
        assert isinstance(raw, str), (call["call_id"], "raw tool result not persisted yet")
        parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        response_file = RUN / call["response"]
        assert parsed == json.loads(response_file.read_text()), (call["call_id"], "saved response differs from raw return")
        raw_file = RUN / "raw_returns" / f"{call['call_id']}.txt"
        raw_file.write_text(raw, encoding="utf-8")
        assert sha256(RUN / call["prompt"]) == call["prompt_sha256"]
        assert sha256(RUN / board["path"]) == call["image_sha256"]
        evidence.append({
            "call_id": call["call_id"], "subagent_tool_call_id": parent["toolCallId"],
            "completed": parent.get("isComplete"), "image_tool_call_ids": [event["toolCallId"] for event in views],
            "image_tool_completed": True, "image_path": board["path"], "image_sha256": call["image_sha256"],
            "prompt_sha256": call["prompt_sha256"], "outer_task_prompt": details["prompt"],
            "raw_return_sha256": sha256(raw_file), "response_sha256": sha256(response_file),
            "model_display_name": details.get("modelName", "not exposed"),
            "visible_credits_field": details.get("credits", "not exposed"),
            "tokens": "not exposed", "model_build_effort_sampling": "not exposed",
            "response_file_mtime_utc": datetime.fromtimestamp(response_file.stat().st_mtime, timezone.utc).isoformat(),
            "call_start_end_time": "not exposed in tool record",
            "child_tool_ids": [event["toolId"] for event in children],
        })
    write_json("call_evidence.json", {"source_session": str(session), "verified_at": datetime.now(timezone.utc).isoformat(), "calls": evidence})
    return evidence


def analyze(session: Path) -> None:
    manifest = json.loads((RUN / "manifest.json").read_text())
    protocol = json.loads((RUN / "protocol.json").read_text())
    calls = protocol["calls_planned"]
    followup = RUN / "followup_protocol.json"
    if followup.exists():
        calls += json.loads(followup.read_text())["calls_planned"]
    evidence = collect_visual_evidence(calls, manifest, session)
    identifiers = [record["stimulus_id"] for record in manifest["stimuli"]]
    rows = []
    scores = {}
    for call in calls:
        response = json.loads((RUN / call["response"]).read_text())
        expected = manifest["boards"][call["order"]]["row_major_ids"]
        assert response["visual_input_received"] is True
        assert response["data_type"] == "synthetic_persona" and response["call_id"] == call["call_id"]
        assert [row["stimulus_id"] for row in response["ratings"]] == expected
        assert response["visual_check"]["top_left_id"] == expected[0]
        assert response["visual_check"]["bottom_right_id"] == expected[-1]
        scores[call["call_id"]] = {}
        for rating in response["ratings"]:
            for key in ("aesthetic", "visual_clarity"):
                assert type(rating[key]) is int and 1 <= rating[key] <= 7, (call["call_id"], rating)
            scores[call["call_id"]][rating["stimulus_id"]] = rating
            rows.append({"call_id": call["call_id"], "role": call["role"], "order": call["order"], "questionnaire_language": call["questionnaire_language"], "data_type": "synthetic_persona", **rating})
    with (RUN / "ratings.csv").open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    comparisons = []
    for call in calls:
        baseline_id = call.get("comparison_call_id", f"b01-baseline-{call['order']}")
        differences = {identifier: scores[call["call_id"]][identifier]["aesthetic"] - scores[baseline_id][identifier]["aesthetic"] for identifier in identifiers}
        comparisons.append({"call_id": call["call_id"], "reference_call_id": baseline_id, "aesthetic_differences": differences, "mean_absolute_difference": float(np.mean(np.abs(list(differences.values()))))})
    font_differences = []
    for call in calls:
        for content, sans, serif, wenkai in (("tea", "M01", "M02", "M03"), ("moon", "M04", "M05", "M06")):
            for family, identifier in (("NotoSerifSC", serif), ("LXGWWenKai", wenkai)):
                score = scores[call["call_id"]]
                font_differences.append({"call_id": call["call_id"], "content": content, "family_vs_NotoSansCJKsc": family, "aesthetic_difference": score[identifier]["aesthetic"] - score[sans]["aesthetic"], "clarity_difference": score[identifier]["visual_clarity"] - score[sans]["visual_clarity"]})
    order_differences = {}
    for role in protocol["roles"]:
        differences = {identifier: scores[f"b01-{role}-reverse"][identifier]["aesthetic"] - scores[f"b01-{role}-forward"][identifier]["aesthetic"] for identifier in identifiers}
        order_differences[role] = {"differences": differences, "mean_absolute_difference": float(np.mean(np.abs(list(differences.values()))))}
    measurements = json.loads((RUN / "measurements.json").read_text())
    sensitivity = []
    for stimulus in manifest["stimuli"]:
        selected = [record for record in measurements if record["stimulus_id"] == stimulus["stimulus_id"]]
        mid = next(record for record in selected if record["threshold"] == 128)
        assert mid["metrics"]["ink_coverage_ratio"]["value"] == stimulus["ink_pixels"] / 96000
        for feature in ("ink_coverage_ratio", "bbox_fill_ratio", "connected_component_count", "closure_count", "stroke_width_mean_norm"):
            values = [record["metrics"][feature]["value"] for record in selected]
            assert all(value is not None for value in values)
            sensitivity.append({"stimulus_id": stimulus["stimulus_id"], "feature": feature, "thresholds": [record["threshold"] for record in selected], "values": values, "range": max(values) - min(values)})
    summary = {
        "data_type": "synthetic_persona", "calls": len(calls), "unique_stimuli": len(identifiers), "ratings": len(rows),
        "successful_visual_calls": len(evidence), "failed_calls": 0, "retries": 0,
        "model_display_names": sorted({entry["model_display_name"] for entry in evidence}),
        "visible_credits_fields": [entry["visible_credits_field"] for entry in evidence], "tokens": "not exposed",
        "comparisons": comparisons, "spatial_order_plus_call_variation": order_differences,
        "within_content_font_differences": font_differences, "threshold_sensitivity": sensitivity,
        "stimulus_score_ranges": {identifier: {"minimum": min(score[identifier]["aesthetic"] for score in scores.values()), "maximum": max(score[identifier]["aesthetic"] for score in scores.values())} for identifier in identifiers},
        "limits": protocol["analysis_limits"] + ["Some English-questionnaire explanations returned in Chinese; output language not fixed", "Visual-call completion plus image-specific checks verify delivery, not human gaze or role fidelity"],
        "analysis_script_sha256": sha256(__file__), "protocol_sha256": sha256(RUN / "protocol.json"),
    }
    write_json("analysis.json", summary)
    print(json.dumps({key: summary[key] for key in ("calls", "ratings", "successful_visual_calls", "model_display_names", "visible_credits_fields")}, indent=2))
    print("font differences", {str(value): sum(row["aesthetic_difference"] == value for row in font_differences) for value in (-2, -1, 0, 1, 2)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, default=SESSION)
    arguments = parser.parse_args()
    analyze(arguments.session)

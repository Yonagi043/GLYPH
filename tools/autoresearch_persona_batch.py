"""Prepare isolated persona questionnaires without ratings or expected rankings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from glyph_features.render import sha256


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/processed/autoresearch/2026-09-07-b01"
ROLES = {
    "baseline": "No fictional language identity is assigned. Answer without adopting a demographic persona.",
    "zh": "Adopt this fictional background: an adult whose first language is Mandarin Chinese, who reads simplified Chinese daily and English proficiently, with little experience reading Japanese or Korean. No professional typography or calligraphy training.",
    "en": "Adopt this fictional background: an adult whose first language is English, who reads English daily, with little experience reading Chinese, Japanese or Korean. No professional typography or calligraphy training.",
    "ja": "Adopt this fictional background: an adult whose first language is Japanese, who reads Japanese daily and English proficiently, recognizes some shared Han characters but has little experience reading Chinese sentences or Korean. No professional typography or calligraphy training.",
    "ko": "Adopt this fictional background: an adult whose first language is Korean, who reads Korean daily and English proficiently, with little experience reading Chinese or Japanese. No professional typography or calligraphy training.",
}


def prepare() -> None:
    manifest = json.loads((RUN / "manifest.json").read_text())
    prompts = RUN / "prompts"
    prompts.mkdir(exist_ok=False)
    (RUN / "responses").mkdir(exist_ok=False)
    calls = []
    for role, identity in ROLES.items():
        for order in ("forward", "reverse"):
            call_id = f"b01-{role}-{order}"
            board = manifest["boards"][order]
            board_path = RUN / board["path"]
            assert sha256(board_path) == board["sha256"]
            response = RUN / "responses" / f"{call_id}.json"
            prompt = f"""Questionnaire: GLYPH synthetic_persona exploratory visual responses, q1-en-v1.
Call ID: {call_id}
Identity prompt version: identity-v1.
{identity}

This is a fictional model response, not a human participant. Identity instructions do not change your actual language knowledge. All conditions can understand this English questionnaire.
Open the actual image with the image-viewing tool: {board_path}
Expected image SHA256: {board['sha256']}
Do not read any other questionnaire output, research log, source code, stimulus metadata, or numerical features. Do not browse or delegate. Read only this assigned prompt and view its image.
If the image cannot actually be viewed, return visual_input_received=false and no ratings. Do not infer scores from filenames, text descriptions, known fonts, or missing visual input.

The image contains twelve labelled candidate wordmarks. View them in row-major order (left to right, top to bottom). They are candidate lettering for commercial signage, logos, or packaging, not existing brands to identify. Evaluate the lettering as displayed, excluding the ID labels. There is no requirement to rank them or to use all scale values.
For each ID, answer the following items in this order:
1. aesthetic: Overall, is this visual form aesthetically pleasing?
2. visual_clarity: Regardless of whether you recognize the writing, are the form's contours and structure visually clear?
Use integers 1 to 7: 1 = Not at all, 4 = Neutral, 7 = Very much. Use null if unable to judge, with a missing_reason. A low reading ability alone does not make a visible form impossible to rate aesthetically.
After recording all scores, add an optional short reason per item and any associations you noticed. These are post-rating descriptions, not causal explanations. Do not revise scores to match explanations.

Return a single JSON object with this structure (the example contains no scores):
{{"call_id":"{call_id}","data_type":"synthetic_persona","visual_input_received":true,"image_tool_used":"actual tool name","visual_check":{{"top_left_id":"observed ID","bottom_right_id":"observed ID","visible_detail":"one concrete visual detail"}},"ratings":[{{"stimulus_id":"observed ID","aesthetic":null,"visual_clarity":null,"missing_reason":null,"reason":"optional","associations":"optional"}}],"limitations":"any viewing or role limitations"}}
List ratings in the displayed row-major order. Include exactly the twelve observed IDs if visible. Do not claim to be a human or report an invented model version, seed, temperature, effort or token usage.
Use apply_patch to save this exact JSON response to {response}. The file must not already exist. Your final response should reproduce the same JSON. Do not edit other files.
"""
            prompt_file = prompts / f"{call_id}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            calls.append({"call_id": call_id, "role": role, "order": order, "questionnaire_language": "en", "identity_version": "identity-v1", "questionnaire_version": "q1-en-v1", "prompt": prompt_file.relative_to(RUN).as_posix(), "prompt_sha256": sha256(prompt_file), "image_sha256": board["sha256"], "response": response.relative_to(RUN).as_posix()})
    protocol = {
        "batch_id": "b01", "status_at_creation": "before_any_questionnaire_call",
        "question": "Are fixed-image aesthetic differences associated with assigned language identity, and how do they compare with font-instance differences and spatial-order sensitivity?",
        "calls_planned": calls, "user_call_limit": None,
        "primary": "per-stimulus aesthetic difference from no-identity baseline under matched spatial order; no pooled human inference",
        "secondary": "within-Chinese matched-content font differences; clarity distinct from aesthetics",
        "roles": ROLES, "materials": "12 controlled_generated stimuli; manifest.json; no actual commercial images or human data",
        "model_control": {"tool": "runSubagent", "agentName_argument": None, "model_argument": None, "requested_route": "same current-agent default for every call", "resolved_model": "not exposed; do not infer from parent", "model_version": "unknown", "effort": "unknown", "temperature": "unknown", "seed": "unknown", "tokens": "not exposed", "context_isolation": "fresh tool invocation; no prior answers in task prompt; inherited host context cannot be independently ruled out"},
        "exclusion": ["No successful image-view tool evidence => invalid visual questionnaire", "Missing/duplicate/wrong ID or out-of-scale item => preserve raw, mark affected answer missing", "Unexpected scores or failure to reflect persona expectations never justify exclusion", "M08 retained for fixed-image identity contrasts but not size-matched cross-script comparison"],
        "continuation": "After the ten coverage calls, inspect missingness, same-image differences and order sensitivity. Add exact repeats or prompt/language contrasts only to resolve a stated uncertainty; no fixed total call cap and no outcome-seeking resampling.",
        "analysis_limits": ["Shared model and repeated stimuli, not independent people", "One forward and reverse per role cannot separate order from call noise", "Only Chinese has three font families; no global script ranking", "Contact sheet spatial order does not enforce gaze or sequential viewing", "Scores are ordinal; mean differences are descriptive conventions only", "No confirmatory human hypothesis or new paid service"],
        "prepare_script_sha256": sha256(__file__), "manifest_sha256": sha256(RUN / "manifest.json"),
    }
    (RUN / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    assert len(calls) == 10 and len({entry["prompt_sha256"] for entry in calls}) == 10
    print(json.dumps({"prepared_calls": len(calls), "protocol": str(RUN / "protocol.json"), "responses_present": len(list((RUN / 'responses').glob('*.json')))}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    prepare()

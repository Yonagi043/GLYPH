"""Prepare paired repeats, identity wording, and item-language sensitivity checks."""
from __future__ import annotations

import json
from pathlib import Path

from glyph_features.render import sha256
from tools.autoresearch_persona_batch import ROLES


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/processed/autoresearch/2026-09-07-b01"
PARAPHRASES = {
    "baseline": "Answer without assuming any fictional participant's language background. No demographic identity is specified.",
    "ko": "For this response, use a fictional adult profile: Korean is the first and daily reading language; English reading is proficient; experience reading Chinese and Japanese is limited. The profile has no professional training in typography or calligraphy.",
}
TRANSLATIONS = {
    "baseline": "\u4e0d\u8d4b\u4e88\u4efb\u4f55\u865a\u6784\u8bed\u8a00\u8eab\u4efd\u3002\u4e0d\u4ee3\u5165\u4eba\u53e3\u7edf\u8ba1\u89d2\u8272\u4f5c\u7b54\u3002",
    "ko": "\u8bf7\u4ee3\u5165\u4ee5\u4e0b\u865a\u6784\u80cc\u666f\uff1a\u4e00\u4f4d\u6210\u5e74\u4eba\uff0c\u6bcd\u8bed\u662f\u97e9\u8bed\uff0c\u6bcf\u5929\u9605\u8bfb\u97e9\u6587\uff0c\u80fd\u719f\u7ec3\u9605\u8bfb\u82f1\u8bed\uff0c\u9605\u8bfb\u4e2d\u6587\u548c\u65e5\u6587\u7684\u7ecf\u9a8c\u5f88\u5c11\u3002\u6ca1\u6709\u4e13\u4e1a\u5b57\u4f53\u6392\u5370\u6216\u4e66\u6cd5\u8bad\u7ec3\u3002",
}


def prepare() -> None:
    original = json.loads((RUN / "protocol.json").read_text())
    calls = []
    for variant in ("repeat", "paraphrase", "zhitems"):
        for role in ("baseline", "ko"):
            source_id = f"b01-{role}-forward"
            call_id = f"b02-{role}-{variant}"
            source = next(call for call in original["calls_planned"] if call["call_id"] == source_id)
            prompt = (RUN / source["prompt"]).read_text().replace(source_id, call_id)
            if variant == "paraphrase":
                prompt = prompt.replace(ROLES[role], PARAPHRASES[role]).replace("identity-v1", "identity-v2")
            if variant == "zhitems":
                prompt = prompt.replace("q1-en-v1", "q1-zhitems-v1")
                prompt = prompt.replace("Overall, is this visual form aesthetically pleasing?", "\u6574\u4f53\u4e0a\uff0c\u8fd9\u4e2a\u89c6\u89c9\u5f62\u5f0f\u7f8e\u89c2\u5417\uff1f")
                prompt = prompt.replace("Regardless of whether you recognize the writing, are the form's contours and structure visually clear?", "\u4e0d\u8003\u8651\u662f\u5426\u8ba4\u8bc6\u6587\u5b57\uff0c\u8fd9\u4e2a\u89c6\u89c9\u5f62\u5f0f\u7684\u8f6e\u5ed3\u548c\u7ed3\u6784\u6e05\u695a\u5417\uff1f")
                prompt = prompt.replace("1 = Not at all, 4 = Neutral, 7 = Very much", "1 = \u5b8c\u5168\u4e0d, 4 = \u4e2d\u7acb, 7 = \u975e\u5e38")
                prompt = prompt.replace("All conditions can understand this English questionnaire.", "All conditions can understand the questionnaire items, which are in Chinese in this condition. This instruction is a task-language assumption, not a change to the fictional reading background.")
            prompt_file = RUN / "prompts" / f"{call_id}.txt"
            assert not prompt_file.exists()
            prompt_file.write_text(prompt, encoding="utf-8")
            reference = f"b02-baseline-{variant}" if role == "ko" else "b01-baseline-forward"
            calls.append({**source, "call_id": call_id, "prompt": prompt_file.relative_to(RUN).as_posix(), "prompt_sha256": sha256(prompt_file), "response": f"responses/{call_id}.json", "questionnaire_language": "zh-Hans-items/en-instructions" if variant == "zhitems" else "en", "questionnaire_version": "q1-zhitems-v1" if variant == "zhitems" else "q1-en-v1", "identity_version": "identity-v2" if variant == "paraphrase" else "identity-v1", "variant": variant, "comparison_call_id": reference, "repeat_or_variant_of": source_id})
    protocol = {
        "batch_id": "b02", "created_before_calls": True, "calls_planned": calls,
        "question": "Is the B01 Korean-identity response on M11/M12 distinguishable from exact-repeat variation and robust to paraphrasing the identity or translating only the rating items?",
        "motivation_observed": "B01 Korean M11=6 in both orders versus baseline=5; M12=6 then 5 versus baseline=5; order and invocation noise not yet separated.",
        "predetermined_analysis": "Compare each ko response with its paired baseline. Compare same-condition repeats with b01 forward, then compare paired identity deltas across variants. Inspect all twelve items, not only the motivating two.",
        "language_manipulation": "Only the two existing questionnaire items and three scale anchors are translated to Chinese using configs/questionnaire_v1.json wording. Surrounding instructions and identity stay English. This is item-language sensitivity, not a fully translated questionnaire or native-language ability test.",
        "same_model_route": original["model_control"], "user_call_limit": None,
        "stopping": "After the paired checks, do not repeat merely to stabilize a desired result. If identity differences are modest, item-specific or variable, report limits and redirect to more diverse/legal commercial stimuli rather than adding personas.",
        "exclusions": original["exclusion"], "prepare_script_sha256": sha256(__file__),
    }
    destination = RUN / "followup_protocol.json"
    assert not destination.exists()
    destination.write_text(json.dumps(protocol, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": len(calls), "batch": "b02", "questionnaire_calls_so_far": 10}, indent=2))


if __name__ == "__main__":
    prepare()

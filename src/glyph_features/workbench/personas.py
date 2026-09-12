"""Host-executed visual questionnaires with persistent tasks and raw returns."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from glyph_features.asset_system.catalog import canonical_json, sha256_file, stable_id

from .catalog import CatalogError
from .research import ResearchService, QUESTIONNAIRE_SCALES


IDENTITIES = {
    "baseline": "No fictional language identity is assigned. Answer without adopting a demographic persona.",
    "zh": "An adult whose first language is Mandarin Chinese, who reads simplified Chinese daily and English proficiently, with little experience reading Japanese or Korean. No professional typography or calligraphy training.",
    "en": "An adult whose first language is English, who reads English daily, with little experience reading Chinese, Japanese or Korean. No professional typography or calligraphy training.",
    "ja": "An adult whose first language is Japanese, who reads Japanese daily and English proficiently, recognizes some shared Han characters but has little experience reading Chinese sentences or Korean. No professional typography or calligraphy training.",
    "ko": "An adult whose first language is Korean, who reads Korean daily and English proficiently, with little experience reading Chinese or Japanese. No professional typography or calligraphy training.",
}


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def host_events(session: Path) -> dict:
    events = {}
    with session.open(encoding="utf-8") as source:
        for line in source:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            for event in objects(value):
                if "toolId" in event and "toolCallId" in event:
                    previous = events.get(event["toolCallId"], {})
                    merged = {**previous, **event}
                    if previous.get("toolSpecificData") and event.get("toolSpecificData"):
                        merged["toolSpecificData"] = {**previous["toolSpecificData"], **event["toolSpecificData"]}
                    events[event["toolCallId"]] = merged
    return events


def write_once(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != content:
            raise CatalogError("QUESTIONNAIRE_ARTIFACT_CHANGED")
        return
    with destination.open("xb") as handle:
        handle.write(content)


class PersonaExecutor:
    def __init__(self, research: ResearchService):
        self.research = research
        with research.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS persona_tasks (
                    task_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, condition_json TEXT NOT NULL,
                    status TEXT NOT NULL, prompt_path TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
                    inputs_json TEXT NOT NULL, lease_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS persona_attempts (
                    host_call_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, status TEXT NOT NULL,
                    raw_return TEXT, evidence_json TEXT NOT NULL, ratings_json TEXT NOT NULL
                );
            """)

    def prepare(self, run_id: str) -> list[dict]:
        existing = self.tasks(run_id)
        if existing:
            return existing
        run = self.research.measure(run_id)
        if run["snapshot"]["blockers"]:
            raise CatalogError("QUESTIONNAIRE_USE_OR_MATERIAL_BLOCKED")
        questionnaire_path = Path(run["snapshot"]["questionnaire_path"])
        if sha256_file(questionnaire_path) != run["snapshot"]["questionnaire_sha256"]:
            raise CatalogError("QUESTIONNAIRE_SOURCE_CHANGED")
        questionnaire = json.loads(questionnaire_path.read_text(encoding="utf-8"))
        config = run["config"]
        language = config["questionnaire_language"]
        aesthetic_item = next(item for item in questionnaire["items"] if item["item_id"] == "item_aesthetic")
        aesthetic = aesthetic_item["translations"][language]["text"]
        clarity = "Regardless of whether you recognize the writing, are the form's contours and structure visually clear?" if language == "en" else "无论是否认识这些文字，其轮廓和结构在视觉上是否清晰？"
        directory = self.research.output_root / run_id
        inputs = []
        for record in run["snapshot"]["materials"]:
            source = Path(record["input_path"])
            if sha256_file(source) != record["input_sha256"]:
                raise CatalogError("QUESTIONNAIRE_INPUT_CHANGED")
            material_id = record["selection"]["material_id"]
            alias = self.research.output_root / "inputs" / f"{record['input_sha256']}{source.suffix.lower()}" if config.get("task_path_layout", "nested_v1") == "flat_v1" else directory / "inputs" / f"{material_id}{source.suffix.lower()}"
            write_once(alias, source.read_bytes())
            inputs.append({"material_id": material_id, "path": str(alias), "sha256": record["input_sha256"]})
        if config.get("presentation_plan"):
            by_id = {image["material_id"]: image for image in inputs}
            for entry in config["presentation_plan"]:
                for role in config["roles"]:
                    condition = {"group_id": entry["group_id"], "design_version": config["design_version"], "sequence_policy": "exact_once"}
                    mode = entry.get("questionnaire_mode") or config.get("questionnaire_mode", "q2")
                    if mode != "q2":
                        condition["questionnaire_mode"] = mode
                    self._prepare_task(run_id, config, directory, [by_id[material_id] for material_id in entry["material_ids"]], role, entry["condition_id"], entry["repetition"], language, aesthetic, clarity, None, condition)
        for repetition in range(config["repetitions"] if not config.get("presentation_plan") else 0):
            for order in config["orders"]:
                ordered = inputs if order == "forward" else list(reversed(inputs))
                for role in config["roles"]:
                    block_size = config.get("task_size") or len(inputs)
                    blocks = [inputs[offset:offset + block_size] for offset in range(0, len(inputs), block_size)]
                    for block_index, block in enumerate(blocks):
                        self._prepare_task(run_id, config, directory, block if order == "forward" else list(reversed(block)), role, order, repetition, language, aesthetic, clarity, block_index if config.get("task_size") else None)
        with self.research.connect() as connection:
            connection.execute("UPDATE research_studies SET status = 'questionnaire_ready' WHERE run_id = ? AND status = 'measured'", (run_id,))
        return self.tasks(run_id)

    def _prepare_task(self, run_id, config, directory, ordered, role, order, repetition, language, aesthetic, clarity, block_index, extra_condition=None):
                    condition = {"role": role, "order": order, "repetition": repetition, "language": language, "wording": config["wording"]}
                    condition.update(extra_condition or {})
                    if block_index is not None:
                        condition["block"] = block_index
                    mode = condition.get("questionnaire_mode", config.get("questionnaire_mode", "q2"))
                    if mode != "q2":
                        condition.update(questionnaire_mode=mode, questionnaire_version="synthetic_persona-q3")
                    task_id = stable_id("persona", {"run_id": run_id, "condition": condition})
                    identity = IDENTITIES[role]
                    if role != "baseline":
                        identity = ("Adopt this fictional background: " if config["wording"] == "background" else "Fictional profile for this response: ") + identity
                    prompt = f"""GLYPH visual questionnaire, synthetic_persona-q2. Task ID: {task_id}
{identity}
This is a model simulation, not a human participant. Prompted identity does not erase actual multilingual knowledge. All conditions can understand the questionnaire.
Read only this prompt and view the listed images, in the listed order, using the image-viewing tool. Do not browse, delegate, inspect source records, measurements, other answers or research logs. Do not write files.
Images are existing visual design or controlled font samples used in research about commercial signage, logos and packaging. Judge the actual displayed form; a font sample is not itself an existing brand. Do not score from filenames, known font names, text descriptions or expected rankings.
Inputs in presentation order:
{json.dumps(ordered, ensure_ascii=False, indent=2)}
For each image, first score aesthetic: {aesthetic}
Then score visual_clarity: {clarity}
Both use integers 1 to 7: 1 Not at all, 4 Neutral, 7 Very much. No need to rank the images or use all scale values. Use null with missing_reason if unable to judge. Low reading ability alone does not prevent aesthetic judgment of a visible form.
After scores, optionally add a short reason and association. Do not revise scores to match the reason. These are post-rating descriptions, not causal explanations. Write reasons in the questionnaire language ({language}).
Return only one JSON object: {{"task_id":"{task_id}","data_type":"synthetic_persona","visual_input_received":true,"ratings":[{{"material_id":"listed ID","aesthetic":null,"visual_clarity":null,"missing_reason":null,"visible_detail":"one detail actually seen","reason":"optional","associations":"optional"}}],"limitations":"viewing or role limitations"}}.
Return one row for each listed image in order. If actual viewing fails, set visual_input_received=false and leave ratings empty. Never invent a model version, effort, temperature, seed or usage.
"""
                    if mode != "q2":
                        premium = "Based only on the visible design, how high-end does the brand positioning appear?" if language == "en" else "仅根据当前可见设计，它传达的品牌定位有多高端？"
                        questions = {"aesthetic": f"{aesthetic} (1 Not at all, 4 Neutral, 7 Very much)", "premium_positioning": f"{premium} (1 Not at all high-end, 4 Mid-range, 7 Very high-end)"}
                        scales = QUESTIONNAIRE_SCALES[mode]
                        example = {"material_id": "listed ID", **{scale: None for scale in scales}, "missing_reason": None, "visible_detail": "one detail actually seen", "reason": "optional", "associations": "optional"}
                        prompt = f"""GLYPH visual questionnaire, synthetic_persona-q3. Task ID: {task_id}
{identity}
This is a model simulation, not a human participant. Prompted identity does not erase multilingual knowledge.
Read only this prompt and view every listed image exactly once, sequentially in listed order, using the image-viewing tool. Do not browse, delegate, inspect repository rules, memory, source records, measurements, other answers or research logs. Do not write files.
Judge the actual visible design as a whole. A controlled font sample is not an existing brand. Do not score from filenames, font names, descriptions or expected rankings.
Inputs in presentation order:
{json.dumps(ordered, ensure_ascii=False, indent=2)}
For each image, answer these items in exactly this order, and keep score keys in this order:
{chr(10).join(f'{index + 1}. {scale}: {questions[scale]}' for index, scale in enumerate(scales))}
Use integers 1 to 7. Use null with missing_reason if unable to judge. Do not provide scores for unasked items. No need to rank images or use all values.
After scores, optionally give a short reason and association in the questionnaire language ({language}); do not revise scores to fit the reason. Reasons are post-rating descriptions, not causal evidence.
Return only one JSON object: {{"task_id":"{task_id}","data_type":"synthetic_persona","visual_input_received":true,"ratings":[{json.dumps(example)}],"limitations":"viewing or role limitations"}}.
Return one row per image in order. If viewing fails, set visual_input_received=false and ratings=[]. Never invent model settings or usage.
"""
                    if mode in {"aesthetic_pair", "aesthetic_pair_only"}:
                        if len(ordered) != 1:
                            raise CatalogError("PAIRED_BOARD_REQUIRES_ONE_IMAGE")
                        condition["questionnaire_version"] = "synthetic_persona-q4-pair" if mode == "aesthetic_pair" else "synthetic_persona-q5-pair-only"
                        weight_question = "Only after making that choice, answer heavier_choice: Which wordmark has visibly thicker strokes, A or B? Choose A, B, same, or unable. Do not revise the aesthetic choice based on this check.\n" if mode == "aesthetic_pair" else ""
                        choice_example = {"material_id": ordered[0]["material_id"], "preference_choice": "tie", **({"heavier_choice": "unable"} if mode == "aesthetic_pair" else {}), "visible_detail": "actual wording and visual difference", "missing_reason": None, "reason": "optional"}
                        choice_order = "Keep preference_choice before heavier_choice in the JSON. " if mode == "aesthetic_pair" else ""
                        prompt = f"""GLYPH visual questionnaire, {condition['questionnaire_version']}. Task ID: {task_id}
{identity}
This is a model simulation, not a human participant. Prompted identity does not erase multilingual knowledge.
Read only this prompt and view the assigned image exactly once using the image-viewing tool. Do not browse, delegate, inspect repository rules, memory, source records, measurements, other answers or research logs. Do not write files.
The image presents two candidate wordmarks labelled A and B. The labels are not part of the wordmarks. These are controlled design candidates for commercial lettering, not existing brands. Judge the visible forms, not filenames or expected rankings.
Input:
{json.dumps(ordered, ensure_ascii=False, indent=2)}
First answer preference_choice: Which wordmark is more aesthetically pleasing, A or B? Choose A, B, tie (no preference), or unable. There is no correct preference and no requirement to choose a winner.
{weight_question}Then record visible_detail: transcribe the visible wording and describe one actual visual difference; if unable, say so. Reasons are optional post-choice descriptions, not causal evidence. Do not provide numerical ratings or high-end/clarity scores.
Return only one JSON object: {{"task_id":"{task_id}","data_type":"synthetic_persona","visual_input_received":true,"ratings":[{json.dumps(choice_example)}],"limitations":"viewing limitations"}}.
{choice_order}If viewing fails set visual_input_received=false and ratings=[]. Never invent model settings or usage.
"""
                    prompt_root = self.research.output_root if config.get("task_path_layout", "nested_v1") == "flat_v1" else directory
                    prompt_path = prompt_root / "prompts" / f"{task_id}.txt"
                    prompt_bytes = prompt.encode("utf-8")
                    write_once(prompt_path, prompt_bytes)
                    with self.research.connect() as connection:
                        connection.execute(
                            "INSERT OR IGNORE INTO persona_tasks VALUES (?, ?, ?, 'queued', ?, ?, ?, 0)",
                            (task_id, run_id, json.dumps(condition), str(prompt_path), hashlib.sha256(prompt_bytes).hexdigest(), json.dumps(ordered)),
                        )
    def tasks(self, run_id: str) -> list[dict]:
        self.research.get(run_id)
        with self.research.connect() as connection:
            rows = connection.execute("SELECT * FROM persona_tasks WHERE run_id = ? ORDER BY rowid", (run_id,)).fetchall()
            attempts = connection.execute("SELECT persona_attempts.* FROM persona_attempts JOIN persona_tasks USING(task_id) WHERE run_id = ? ORDER BY persona_attempts.rowid", (run_id,)).fetchall()
        result = []
        for row in rows:
            task = dict(row)
            task["condition"] = json.loads(task.pop("condition_json"))
            task["inputs"] = json.loads(task.pop("inputs_json"))
            task["attempts"] = []
            for attempt in attempts:
                if attempt["task_id"] == task["task_id"]:
                    parsed = dict(attempt)
                    parsed["evidence"] = json.loads(parsed.pop("evidence_json"))
                    parsed["ratings"] = json.loads(parsed.pop("ratings_json"))
                    task["attempts"].append(parsed)
            result.append(task)
        return result

    def claim(self, run_id: str) -> dict | None:
        config = self.research.get(run_id)["config"]
        tasks = self.tasks(run_id)
        for task in tasks:
            if task["status"] != "queued":
                continue
            if sha256_file(task["prompt_path"]) != task["prompt_sha256"]:
                raise CatalogError("QUESTIONNAIRE_PROMPT_CHANGED")
            for image in task["inputs"]:
                if sha256_file(image["path"]) != image["sha256"]:
                    raise CatalogError("QUESTIONNAIRE_IMAGE_CHANGED")
            with self.research.connect() as connection:
                changed = connection.execute("UPDATE persona_tasks SET status = 'leased', lease_count = lease_count + 1 WHERE task_id = ? AND status = 'queued'", (task["task_id"],)).rowcount
            if changed:
                return self.invocation(task, config)
        return None

    @staticmethod
    def invocation(task: dict, config: dict) -> dict:
        return {"task_id": task["task_id"], "prompt_path": task["prompt_path"], "prompt_sha256": task["prompt_sha256"], "executor": "VS Code runSubagent", "agent_name": config.get("executor_agent", "default"), "invocation_prompt": f"Execute GLYPH task {task['task_id']}. This is an isolated visual questionnaire, not project exploration or resumption. Read only the complete task prompt at {task['prompt_path']} and the images it assigns. Do not read repository rules, research logs, memory, source code or other responses. Actually view every assigned image. Return the requested JSON only. Do not edit files."}

    def pending(self, run_id: str) -> list[dict]:
        config = self.research.get(run_id)["config"]
        return [self.invocation(task, config) for task in self.tasks(run_id) if task["status"] == "leased"]

    def suspend(self, run_id: str) -> None:
        self.research.get(run_id)
        with self.research.connect() as connection:
            connection.execute("UPDATE persona_tasks SET status = 'suspended' WHERE run_id = ? AND status = 'queued'", (run_id,))
            connection.execute("UPDATE research_studies SET status = 'suspended' WHERE run_id = ?", (run_id,))

    def resume(self, run_id: str) -> None:
        self.research.get(run_id)
        with self.research.connect() as connection:
            connection.execute("UPDATE persona_tasks SET status = 'queued' WHERE run_id = ? AND status = 'suspended'", (run_id,))
            connection.execute("UPDATE research_studies SET status = 'questionnaire_partial' WHERE run_id = ? AND status = 'suspended'", (run_id,))

    def retry(self, run_id: str, task_id: str) -> None:
        task = next((item for item in self.tasks(run_id) if item["task_id"] == task_id), None)
        if task is None or task["status"] != "failed":
            raise CatalogError("ONLY_FAILED_TASKS_CAN_RETRY")
        if self.research.get(run_id)["status"] == "suspended":
            raise CatalogError("RESUME_STUDY_BEFORE_RETRY")
        with self.research.connect() as connection:
            connection.execute("UPDATE persona_tasks SET status = 'queued' WHERE task_id = ? AND status = 'failed'", (task_id,))

    @staticmethod
    def validate_return(task: dict, raw: str) -> tuple[list[dict], list[str]]:
        try:
            parsed = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        except (ValueError, TypeError):
            return [], ["RAW_RETURN_NOT_JSON"]
        if not isinstance(parsed, dict) or parsed.get("task_id") != task["task_id"] or parsed.get("data_type") != "synthetic_persona":
            return [], ["RESPONSE_ID_OR_TYPE_INVALID"]
        if parsed.get("visual_input_received") is not True:
            return [], ["VISUAL_INPUT_NOT_RECEIVED"]
        expected = [image["material_id"] for image in task["inputs"]]
        rows = parsed.get("ratings")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return [], ["RATINGS_NOT_RECORDS"]
        issues = []
        if [row.get("material_id") for row in rows] != expected:
            issues.append("RATING_ID_ORDER_OR_COVERAGE_MISMATCH")
        normalized = []
        mode = task.get("condition", {}).get("questionnaire_mode", "q2")
        scales = QUESTIONNAIRE_SCALES[mode]
        for material_id in expected:
            matches = [row for row in rows if row.get("material_id") == material_id]
            row = dict(matches[0]) if len(matches) == 1 else {"material_id": material_id, "missing_reason": "MISSING_OR_DUPLICATE_ROW"}
            if mode != "q2":
                if [key for key in row if key in scales] != list(scales):
                    issues.append("QUESTION_ITEM_ORDER_OR_COVERAGE_MISMATCH")
                if any(row.get(scale) is not None for scale in {"aesthetic", "visual_clarity", "premium_positioning"} - set(scales)):
                    issues.append("UNPRESENTED_OUTCOME_SCORED")
            for scale in scales:
                value = row.get(scale)
                if mode != "q2" and value is None and row.get("missing_reason"):
                    continue
                if type(value) is not int or not 1 <= value <= 7:
                    row[scale] = None
                    row["missing_reason"] = row.get("missing_reason") or "MISSING_OR_INVALID_SCORE"
                    issues.append(f"{material_id}:{scale}:MISSING_OR_INVALID")
            if not row.get("visible_detail"):
                issues.append(f"{material_id}:VISIBLE_DETAIL_MISSING")
            record = {key: row.get(key) for key in ("material_id", "aesthetic", "visual_clarity", "missing_reason", "visible_detail", "reason", "associations")}
            if mode != "q2":
                record["premium_positioning"] = row.get("premium_positioning")
                record["outcome_status"] = {scale: "not_collected" if scale not in scales else "observed" if row.get(scale) is not None else "missing" for scale in ("aesthetic", "visual_clarity", "premium_positioning")}
            if mode in {"aesthetic_pair", "aesthetic_pair_only"}:
                choices = ("preference_choice", "heavier_choice") if mode == "aesthetic_pair" else ("preference_choice",)
                if [key for key in row if key in {"preference_choice", "heavier_choice"}] != list(choices):
                    return [], ["QUESTION_ITEM_ORDER_OR_COVERAGE_MISMATCH"]
                if row["preference_choice"] not in {"A", "B", "tie", "unable"} or (mode == "aesthetic_pair" and row["heavier_choice"] not in {"A", "B", "same", "unable"}):
                    return [], ["PAIR_CHOICE_INVALID"]
                if "unable" in (row[key] for key in choices) and not row.get("missing_reason"):
                    return [], ["PAIR_MISSING_REASON_REQUIRED"]
                record.update({key: row[key] for key in choices})
                record["outcome_status"]["aesthetic_preference"] = "missing" if row["preference_choice"] == "unable" else "observed"
            normalized.append(record)
        return normalized, issues

    def ingest(self, run_id: str, session: Path, *, finalize_evidence: bool = False) -> dict:
        events = host_events(session)
        pending = []
        imported = []
        for task in self.tasks(run_id):
            parents = [event for event in events.values() if event.get("toolId") == "runSubagent" and task["prompt_path"] in event.get("toolSpecificData", {}).get("prompt", "")]
            for parent in parents:
                details = parent.get("toolSpecificData", {})
                raw = details.get("result")
                missing_return = not isinstance(raw, str)
                if not parent.get("isComplete") or (missing_return and not finalize_evidence):
                    pending.append(task["task_id"])
                    continue
                if missing_return:
                    raw = ""
                children = [event for event in events.values() if event.get("subAgentInvocationId") == parent["toolCallId"]]
                image_evidence = []
                for image in task["inputs"]:
                    views = [event for event in children if event.get("toolId") in {"copilot_viewImage", "view_image"} and event.get("isComplete") and image["path"] in json.dumps(event.get("invocationMessage"), ensure_ascii=False)]
                    image_evidence.append({**image, "tool_call_ids": [event["toolCallId"] for event in views]})
                missing_images = any(not image["tool_call_ids"] for image in image_evidence)
                with self.research.connect() as connection:
                    prior = connection.execute("SELECT evidence_json FROM persona_attempts WHERE host_call_id = ?", (parent["toolCallId"],)).fetchone()
                finalized = finalize_evidence or bool(prior and json.loads(prior["evidence_json"]).get("evidence_finalized_by_operator"))
                if missing_images and not finalized:
                    pending.append(task["task_id"])
                if sha256_file(task["prompt_path"]) != task["prompt_sha256"] or any(sha256_file(image["path"]) != image["sha256"] for image in task["inputs"]):
                    raise CatalogError("QUESTIONNAIRE_INPUT_CHANGED_AFTER_CALL")
                ratings, issues = self.validate_return(task, raw)
                if missing_return:
                    issues.append("HOST_RAW_RETURN_NOT_PERSISTED")
                attempt_status = "completed_with_missing" if ratings and issues else "completed" if ratings else "failed"
                if missing_images:
                    issues.append("HOST_VISUAL_EVIDENCE_INCOMPLETE")
                    attempt_status = "failed" if finalized else "awaiting_evidence"
                unexpected_reads = []
                for child in children:
                    tool_id = child.get("toolId")
                    message = json.dumps(child.get("invocationMessage"), ensure_ascii=False)
                    if tool_id in {"copilot_readFile", "read_file"} and task["prompt_path"] not in message:
                        unexpected_reads.append({"tool_call_id": child["toolCallId"], "tool": tool_id, "invocation": child.get("invocationMessage")})
                    elif tool_id not in {"copilot_readFile", "read_file", "copilot_viewImage", "view_image", "tool_search", "tool_search_tool", "task_complete"}:
                        unexpected_reads.append({"tool_call_id": child["toolCallId"], "tool": tool_id, "invocation": child.get("invocationMessage")})
                if unexpected_reads:
                    attempt_status = "protocol_deviation"
                actual_sequence = []
                for child in children:
                    if child.get("toolId") in {"copilot_viewImage", "view_image"} and child.get("isComplete"):
                        message = json.dumps(child.get("invocationMessage"), ensure_ascii=False)
                        matches = [image["material_id"] for image in task["inputs"] if image["path"] in message]
                        actual_sequence.append(matches[0] if len(matches) == 1 else "UNASSIGNED_IMAGE")
                sequence_mismatch = task["condition"].get("sequence_policy") == "exact_once" and actual_sequence != [image["material_id"] for image in task["inputs"]]
                rating_order_mismatch = task["condition"].get("sequence_policy") == "exact_once" and "RATING_ID_ORDER_OR_COVERAGE_MISMATCH" in issues
                rating_order_mismatch = rating_order_mismatch or any(issue in issues for issue in ("QUESTION_ITEM_ORDER_OR_COVERAGE_MISMATCH", "UNPRESENTED_OUTCOME_SCORED"))
                if rating_order_mismatch:
                    attempt_status = "protocol_deviation"
                if sequence_mismatch and not missing_images:
                    issues.append("HOST_IMAGE_SEQUENCE_MISMATCH")
                    attempt_status = "protocol_deviation"
                evidence = {
                    "session": str(session), "host_call_id": parent["toolCallId"], "outer_prompt": details.get("prompt"),
                    "prompt_sha256": task["prompt_sha256"], "images": image_evidence,
                    "model_display_name": details.get("modelName", "unknown"), "visible_credits": details.get("credits", "unknown"),
                    "tokens": "unknown", "model_build": "unknown", "effort": "unknown", "temperature": "unknown", "seed": "unknown",
                    "raw_return_sha256": hashlib.sha256(raw.encode()).hexdigest(), "validation_issues": issues,
                    "unexpected_context_reads": unexpected_reads,
                    "actual_image_sequence": actual_sequence,
                    "analysis_eligible": not unexpected_reads and not missing_images and not sequence_mismatch and not rating_order_mismatch and bool(ratings),
                    "evidence_finalized_by_operator": finalized,
                    "requested_executor_agent": self.research.get(run_id)["config"].get("executor_agent", "default"),
                    "inherited_host_context": "unknown; tool trace does not establish complete model-context isolation",
                }
                with self.research.connect() as connection:
                    previous = connection.execute("SELECT status FROM persona_attempts WHERE host_call_id = ?", (parent["toolCallId"],)).fetchone()
                    connection.execute("INSERT INTO persona_attempts VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(host_call_id) DO UPDATE SET status=excluded.status, evidence_json=excluded.evidence_json, ratings_json=excluded.ratings_json", (parent["toolCallId"], task["task_id"], attempt_status, raw, json.dumps(evidence), json.dumps(ratings)))
                    latest = connection.execute("SELECT host_call_id FROM persona_attempts WHERE task_id = ? ORDER BY rowid DESC LIMIT 1", (task["task_id"],)).fetchone()[0]
                    if latest == parent["toolCallId"] and (previous is None or previous["status"] != attempt_status or task["status"] not in {"queued", "leased"}):
                        connection.execute("UPDATE persona_tasks SET status = ? WHERE task_id = ?", (attempt_status, task["task_id"]))
                imported.append(parent["toolCallId"])
        tasks = self.tasks(run_id)
        if tasks:
            completed = all(task["status"] in {"completed", "completed_with_missing"} for task in tasks)
            with self.research.connect() as connection:
                connection.execute("UPDATE research_studies SET status = ? WHERE run_id = ? AND status != 'suspended'", ("responses_complete" if completed else "questionnaire_partial", run_id))
        return {"imported_host_call_ids": imported, "awaiting_host_evidence": sorted(set(pending)), "tasks": tasks}
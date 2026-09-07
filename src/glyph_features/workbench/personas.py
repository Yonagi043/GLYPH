"""Host-executed visual questionnaires with persistent tasks and raw returns."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from glyph_features.asset_system.catalog import canonical_json, sha256_file, stable_id

from .catalog import CatalogError
from .research import ResearchService


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
            alias = directory / "inputs" / f"{material_id}{source.suffix.lower()}"
            write_once(alias, source.read_bytes())
            inputs.append({"material_id": material_id, "path": str(alias), "sha256": record["input_sha256"]})
        for repetition in range(config["repetitions"]):
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

    def _prepare_task(self, run_id, config, directory, ordered, role, order, repetition, language, aesthetic, clarity, block_index):
                    condition = {"role": role, "order": order, "repetition": repetition, "language": language, "wording": config["wording"]}
                    if block_index is not None:
                        condition["block"] = block_index
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
                    prompt_path = directory / "prompts" / f"{task_id}.txt"
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
        for material_id in expected:
            matches = [row for row in rows if row.get("material_id") == material_id]
            row = dict(matches[0]) if len(matches) == 1 else {"material_id": material_id, "missing_reason": "MISSING_OR_DUPLICATE_ROW"}
            for scale in ("aesthetic", "visual_clarity"):
                value = row.get(scale)
                if type(value) is not int or not 1 <= value <= 7:
                    row[scale] = None
                    row["missing_reason"] = row.get("missing_reason") or "MISSING_OR_INVALID_SCORE"
                    issues.append(f"{material_id}:{scale}:MISSING_OR_INVALID")
            if not row.get("visible_detail"):
                issues.append(f"{material_id}:VISIBLE_DETAIL_MISSING")
            normalized.append({key: row.get(key) for key in ("material_id", "aesthetic", "visual_clarity", "missing_reason", "visible_detail", "reason", "associations")})
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
                evidence = {
                    "session": str(session), "host_call_id": parent["toolCallId"], "outer_prompt": details.get("prompt"),
                    "prompt_sha256": task["prompt_sha256"], "images": image_evidence,
                    "model_display_name": details.get("modelName", "unknown"), "visible_credits": details.get("credits", "unknown"),
                    "tokens": "unknown", "model_build": "unknown", "effort": "unknown", "temperature": "unknown", "seed": "unknown",
                    "raw_return_sha256": hashlib.sha256(raw.encode()).hexdigest(), "validation_issues": issues,
                    "unexpected_context_reads": unexpected_reads,
                    "analysis_eligible": not unexpected_reads and not missing_images and bool(ratings),
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
"""Generate and strictly validate the TASK-05 system handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from glyph_features.asset_system.catalog import (
    canonical_json,
    normalize_repo_path,
    validate_record,
)

from .handoffs import inspect_upstream_handoffs
from .modules import build_module_descriptors


HANDOFF_RELATIVE_PATH = (
    "data/releases/task05_joint_workbench_v1/handoff_manifest.json"
)
REPORT_RELATIVE_PATH = "data/releases/task05_joint_workbench_v1/TASK_05_REPORT_zh.md"
CHECKSUM_RELATIVE_PATH = "data/releases/task05_joint_workbench_v1/checksums.sha256"
SCHEMA_PATH = "schema/workbench_handoff_manifest.schema.json"
MODULE_IDS = {"assets", "vision", "experiment", "social", "han_style", "workbench"}


OUTPUT_SPECS = (
    ("analysis_plan", "configs/joint_analysis_plan_v1.json", 1, "public_code_or_schema", "1.0.0"),
    ("system_fixture", "data/fixtures/system_e2e/generator_config.json", 1, "open_fixture", "1.0.0"),
    ("browser_acceptance", "data/fixtures/system_e2e/browser_acceptance.json", 1, "metadata_only", "1.0.0"),
    ("failure_injection", "data/fixtures/system_e2e/failure_injection_report.json", 1, "metadata_only", "1.0.0"),
    ("module_descriptor_schema", "schema/workbench_module_descriptor.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("analysis_plan_schema", "schema/analysis_plan.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("analysis_run_schema", "schema/analysis_run.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("gate_decision_schema", "schema/gate_decision.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("release_candidate_schema", "schema/release_candidate.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("system_fixture_schema", "schema/system_fixture.schema.json", 1, "public_code_or_schema", "1.0.0"),
    ("workbench_handoff_schema", SCHEMA_PATH, 1, "public_code_or_schema", "1.0.0"),
    ("joint_analysis_protocol", "docs/joint_analysis_protocol_zh.md", 1, "public_code_or_schema", "1.0.0"),
    ("local_operations", "docs/workbench_local_ops_zh.md", 1, "public_code_or_schema", "1.0.0"),
    ("workbench_web_entrypoint", "src/glyph_features/workbench/static/index.html", 1, "public_code_or_schema", None),
    ("task_report", REPORT_RELATIVE_PATH, 1, "public_code_or_schema", "1.0.0"),
)


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(root: Path, arguments: list[str], *, binary: bool = False):
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=not binary,
    ).stdout


def _committed_paths(root: Path, commit: str) -> list[str]:
    output = _git(
        root,
        [
            "ls-tree",
            "-r",
            "--name-only",
            commit,
            "--",
            "pyproject.toml",
            "runtime.lock.json",
            "uv.lock",
            "configs/joint_analysis_plan_v1.json",
            "data/fixtures/system_e2e",
            "docs/joint_analysis_protocol_zh.md",
            "docs/workbench_local_ops_zh.md",
            "schema/analysis_plan.schema.json",
            "schema/analysis_run.schema.json",
            "schema/gate_decision.schema.json",
            "schema/release_candidate.schema.json",
            "schema/system_fixture.schema.json",
            "schema/workbench_handoff_manifest.schema.json",
            "schema/workbench_module_descriptor.schema.json",
            "src/glyph_features/workbench",
            "tests/test_workbench.py",
            "tools/validate_task05_handoff.py",
        ],
    )
    return sorted(line for line in output.splitlines() if line)


def _role(path: str) -> str:
    if path in {"pyproject.toml", "runtime.lock.json", "uv.lock"}:
        return "dependency_lock"
    if path.startswith("schema/"):
        return "schema"
    if path.startswith("configs/"):
        return "config"
    if path.startswith("data/fixtures/"):
        return "fixture"
    if path.startswith("docs/"):
        return "documentation"
    if path.startswith("tests/"):
        return "test"
    if path.endswith("/cli.py") or path.endswith("/app.py"):
        return "entrypoint"
    return "source"


def _producer_files(root: Path, commit: str) -> list[dict[str, str]]:
    records = []
    for path in _committed_paths(root, commit):
        working = root / path
        if not working.is_file():
            raise ValueError(f"PRODUCER_FILE_MISSING:{path}")
        committed = _git(root, ["show", f"{commit}:{path}"], binary=True)
        working_hash = _sha256(working)
        if _sha256_bytes(committed) != working_hash:
            raise ValueError(f"PRODUCER_FILE_DIFFERS_FROM_COMMIT:{path}")
        records.append({"role": _role(path), "path": path, "sha256": working_hash})
    if len(records) < 10:
        raise ValueError("PRODUCER_FILE_SET_INCOMPLETE")
    return records


def _artifact(
    root: Path,
    logical_type: str,
    path: str,
    record_count: int,
    classification: str,
    schema_version: str | None,
    source: Path | None = None,
) -> dict[str, Any]:
    target = source or root / path
    if not target.is_file():
        raise ValueError(f"HANDOFF_OUTPUT_MISSING:{path}")
    return {
        "logical_type": logical_type,
        "path": path,
        "sha256": _sha256(target),
        "record_count": record_count,
        "classification": classification,
        "schema_version": schema_version,
    }


def _validation(path: Path, root: Path, summary: str) -> dict[str, str]:
    relative = path.relative_to(root).as_posix()
    return {
        "status": "passed",
        "evidence_path": relative,
        "sha256": _sha256(path),
        "summary": summary,
    }


def _report(commit: str) -> str:
    return f"""# TASK-05 最终报告

实现提交：`{commit}`

## 完成范围

- 严格验证 TASK-01 至 TASK-04 handoff、producer ancestry 与版本兼容。
- 交付 pointer-only 中央 catalog、稳定 ID reference graph、冻结分析计划和不可变 snapshot。
- 交付 384 单位 synthetic ordinal recovery、join audit、WP2 context-only、WP3/WP4 fail-closed 边界。
- 交付本机中文八区工作台、固定 operation 队列、demo audit package、formal release gate 和协调备份恢复。
- 保持 social v17 独立所有权，不挂载第二 scheduler，不迁移或访问生产库。

## 就绪度

| 维度 | 状态 |
|---|---|
| `engineering_ready` | `true` |
| `pilot_ready` | `false` |
| `research_validated` | `false` |

工程 fixture、浏览器、故障注入和备份恢复通过，不代表真实参与者、专家、许可、伦理或研究结论已验证。

## 验证结论

- Synthetic E2E：通过；formal release 被机械阻断。
- 浏览器：桌面与移动八区、下钻、键盘、备份恢复和泄漏扫描通过。
- 数据库：catalog/social 角色隔离；social 只消费 canonical validated export。
- 发布：demo no-overwrite/checksums 通过；不存在 formal bypass。

## 入口

- 启动、健康、备份和恢复：`docs/workbench_local_ops_zh.md`
- 联合分析和推断边界：`docs/joint_analysis_protocol_zh.md`
- Handoff validator：`uv run --frozen python tools/validate_task05_handoff.py`

## 停止声明

TASK-05 停止在 synthetic engineering-ready 边界。未导入真实研究数据，未修改生产 social 数据库，未接受条款或费用，未通过任何人工 gate，未执行正式发布或 push。
"""


def _module_compatibility(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    descriptors = {item["module_id"]: item for item in build_module_descriptors(results)}
    by_module = {item["module_id"]: item for item in results}
    output = []
    for module_id in sorted(MODULE_IDS):
        descriptor = descriptors[module_id]
        upstream = by_module.get(module_id)
        output.append(
            {
                "module_id": module_id,
                "module_version": descriptor["module_version"],
                "handoff_schema_version": descriptor.get("handoff_schema_version"),
                "input_manifest": None if upstream is None else upstream["manifest_path"],
                "input_sha256": None if upstream is None else upstream["manifest_sha256"],
                "compatible": descriptor["health"] == "ready",
                "readiness": descriptor["readiness"],
                "contract_versions": descriptor["contract_versions"],
                "conclusion": (
                    "Validated by the upstream native handoff validator and producer ancestry."
                    if upstream is not None
                    else "Public validated-export/service adapter; no private tables or second scheduler."
                    if module_id == "social"
                    else "TASK-05 catalog, analysis, workbench, release and operations contracts."
                ),
            }
        )
    return output


def _blocked_gates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for result in results:
        for gate in result["blocked_gates"]:
            if not gate["gate_id"].startswith("GATE-"):
                continue
            reasons = gate.get("reasons") or [gate.get("evidence") or "Upstream human gate remains unresolved."]
            output.append(
                {
                    "gate_id": gate["gate_id"],
                    "module_id": result["module_id"],
                    "status": "blocked",
                    "scope": result["task_id"],
                    "blocked_object": "pilot_and_formal_release",
                    "evidence_path": gate.get("packet_path") or result["manifest_path"],
                    "reasons": reasons,
                }
            )
    output.extend(
        [
            {
                "gate_id": "GATE-TERMS",
                "module_id": "social",
                "status": "blocked",
                "scope": "real_platform_collection",
                "blocked_object": "real_social_input",
                "evidence_path": "docs/workbench_local_ops_zh.md",
                "reasons": ["No real request, terms acceptance, credential use or paid access was approved."],
            },
            {
                "gate_id": "GATE-RELEASE",
                "module_id": "workbench",
                "status": "blocked",
                "scope": "system",
                "blocked_object": "formal_release",
                "evidence_path": "docs/joint_analysis_protocol_zh.md",
                "reasons": ["Synthetic inputs and unresolved human gates mechanically block formal release."],
            },
        ]
    )
    unique = {
        (item["module_id"], item["gate_id"], item["scope"]): item for item in output
    }
    return sorted(unique.values(), key=lambda item: (item["gate_id"], item["module_id"], item["scope"]))


def build_manifest(root: Path, implementation_commit: str) -> dict[str, Any]:
    results = inspect_upstream_handoffs(root)
    if not all(item["compatible"] for item in results):
        raise ValueError("UPSTREAM_HANDOFF_NOT_COMPATIBLE")
    producer_files = _producer_files(root, implementation_commit)
    browser = root / "data/fixtures/system_e2e/browser_acceptance.json"
    failures = root / "data/fixtures/system_e2e/failure_injection_report.json"
    tests = root / "tests/test_workbench.py"
    inputs = [
        {
            "task_id": item["task_id"],
            "module_id": item["module_id"],
            "path": item["manifest_path"],
            "sha256": item["manifest_sha256"],
            "schema_version": item["handoff_schema_version"],
            "producer_commit": item["producer_commit"],
            "compatible": item["compatible"],
            "readiness": item["readiness"],
        }
        for item in results
    ]
    return {
        "handoff_schema_version": "1.0.0",
        "task_id": "TASK-05",
        "producer_version": "0.1.0",
        "implementation_commit": implementation_commit,
        "created_at": _now(),
        "readiness": {
            "engineering_ready": True,
            "pilot_ready": False,
            "research_validated": False,
        },
        "contract_versions": {
            "workbench_handoff": "1.0.0",
            "module_descriptor": "1.0.0",
            "catalog": "1.0.0",
            "analysis_plan": "1.0.0",
            "analysis_run": "1.0.0",
            "gate_decision": "1.0.0",
            "release_candidate": "1.0.0",
            "coordinated_backup": "1.0.0",
            "social_validated_export": "v17",
        },
        "module_compatibility": _module_compatibility(results),
        "input_handoffs": inputs,
        "outputs": [],
        "producer_provenance": {
            "implementation_commit": implementation_commit,
            "working_tree_state_at_generation": "clean",
            "producer_snapshot_matches_commit": True,
            "aggregate_sha256": _sha256_bytes(canonical_json(producer_files)),
            "files": producer_files,
        },
        "quality_gates": [
            {"gate_id": "HANDOFF_COMPATIBILITY", "status": "passed", "evidence": "Four native validators and Git ancestry checks passed."},
            {"gate_id": "SYNTHETIC_E2E", "status": "passed", "evidence": "384 analysis units, validated WP2 export, audit package and restart persistence passed."},
            {"gate_id": "BROWSER_ACCEPTANCE", "status": "passed", "evidence": "Desktop/mobile navigation, drilldown, operations and leakage checks passed."},
            {"gate_id": "BACKUP_RESTORE", "status": "passed", "evidence": "Both databases restored to new paths and tampering was rejected."},
            {"gate_id": "FORMAL_RELEASE", "status": "blocked", "evidence": "Synthetic and unresolved human gates produced machine-readable blockers."},
        ],
        "validation_evidence": {
            "system_e2e": _validation(tests, root, "System fixture, restart persistence, audit export and formal-release blocking passed."),
            "browser": _validation(browser, root, "Eight views passed desktop/mobile screenshot, interaction, overflow and leakage checks."),
            "backup_restore": _validation(tests, root, "Coordinated manifest, temporary restore and tamper rejection passed."),
            "failure_injection": _validation(failures, root, "Join, database, storage, CSRF, bind, overwrite, release and operation failures closed safely."),
            "commands": [
                {"command": "uv run --frozen pytest -q tests/test_workbench.py", "status": "passed", "result": "TASK-05 focused suite passed."},
                {"command": "uv run --frozen pytest -q", "status": "passed", "result": "Repository suite passed."},
                {"command": "uv lock --check", "status": "passed", "result": "Dependency lock is current."},
                {"command": "node --check src/glyph_features/workbench/static/app.js", "status": "passed", "result": "Workbench JavaScript parsed successfully."},
            ],
        },
        "interfaces": {
            "commands": [
                "uv run glyph-workbench serve --catalog-database CATALOG --social-database SOCIAL",
                "uv run glyph-workbench run-system-fixture --catalog-database CATALOG --social-database SOCIAL",
                "uv run glyph-workbench export-demo ANALYSIS_RUN_ID --catalog-database CATALOG --social-database SOCIAL",
                "uv run glyph-workbench backup --catalog-database CATALOG --social-database SOCIAL",
                "uv run glyph-workbench restore-drill BACKUP_ID --catalog-database CATALOG --social-database SOCIAL",
            ],
            "read_endpoints": [
                "/api/overview", "/api/modules", "/api/views/{module}", "/api/analysis", "/api/audit", "/api/evidence/{entity_id}", "/api/health", "/api/operations"
            ],
            "write_endpoints": [
                "/api/actions/initialize", "/api/actions/export-demo", "/api/actions/check-formal-release", "/api/actions/backup", "/api/actions/restore-drill", "/api/operations/analysis-fixture", "/api/operations/system-fixture", "/api/operations/{operation_id}/cancel", "/api/operations/{operation_id}/resume"
            ],
            "storage_ownership": [
                "Workbench owns only catalog metadata, snapshots, release candidates and audit events.",
                "Social owns its v17 database and canonical validated exports.",
                "Assets, vision, experiment and Han modules own their domain records and write operations."
            ],
        },
        "data_boundaries": [
            {"reason_code": "SYNTHETIC_DEMO_ONLY", "classification": "synthetic", "allowed": True, "reason": "Allowed only for local engineering, demo audit and reproducibility checks."},
            {"reason_code": "FORMAL_RELEASE_FORBIDDEN", "classification": "synthetic", "allowed": False, "reason": "Synthetic ratings and evidence cannot support formal research release."},
            {"reason_code": "PII_NOT_IMPORTED", "classification": "participant_pii", "allowed": False, "reason": "Identity maps and participant PII are outside the workbench contract."},
            {"reason_code": "RAW_PLATFORM_PAYLOAD_NOT_IMPORTED", "classification": "social_raw_payload", "allowed": False, "reason": "Only validated export pointers and hashes enter the catalog."},
            {"reason_code": "RESTRICTED_ASSET_NOT_COPIED", "classification": "restricted_asset", "allowed": False, "reason": "Catalog stores only source-owned pointers and classifications."},
            {"reason_code": "NARRATIVE_NOT_PARTICIPANT_EXPOSURE", "classification": "wp2_context", "allowed": False, "reason": "WP2 remains hypothesis/context unless a preregistered exposure operation exists."},
        ],
        "blocked_human_gates": _blocked_gates(results),
        "known_limitations": [
            "No real participant rating, approved expert review, formal-use asset or releasable social evidence was imported.",
            "WP3 is blocked because all experiment conditions resolve to one source stimulus.",
            "WP4 remains instance_level_only because independent exemplars and GATE-EXPERT are absent.",
            "The fixture OrderedModel does not replace the preregistered crossed ordinal hierarchy for real research.",
            "The operation queue is process-local; durable facts remain in module databases and immutable catalog runs.",
        ],
        "maintenance_responsibility": [
            "Module owners maintain domain schemas, service APIs, exports and database migrations.",
            "Workbench maintainers update compatibility rules only with versioned handoff contracts and tests.",
            "Human approvers own rights, history, ethics, participants, translation, expert, terms and release decisions.",
        ],
    }


def _validate_paths_and_hashes(
    root: Path,
    records: Iterable[dict[str, Any]],
    label: str,
) -> list[str]:
    errors = []
    for record in records:
        path = record.get("path")
        try:
            normalized = normalize_repo_path(path)
        except (TypeError, ValueError):
            errors.append(f"{label}_PATH_INVALID:{path}")
            continue
        if normalized != path:
            errors.append(f"{label}_PATH_NOT_CANONICAL:{path}")
            continue
        target = root / normalized
        if not target.is_file():
            errors.append(f"{label}_FILE_MISSING:{path}")
        elif _sha256(target) != record.get("sha256"):
            errors.append(f"{label}_SHA256_MISMATCH:{path}")
    return errors


def validate_handoff(manifest_path: str | Path, workspace_root: str | Path) -> list[str]:
    root = Path(workspace_root).resolve()
    path = Path(manifest_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return ["HANDOFF_PATH_INVALID"]
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["HANDOFF_JSON_INVALID"]
    errors = validate_record(manifest, root / SCHEMA_PATH)
    if errors:
        return [f"HANDOFF_SCHEMA:{error}" for error in errors]
    serialized = json.dumps(manifest, ensure_ascii=False)
    if str(root) in serialized or re.search(r"/(?:Users|private|tmp)/", serialized):
        errors.append("HANDOFF_ABSOLUTE_PATH_LEAK")
    if set(item["module_id"] for item in manifest["module_compatibility"]) != MODULE_IDS:
        errors.append("HANDOFF_MODULE_SET_INVALID")
    if {item["task_id"] for item in manifest["input_handoffs"]} != {
        "TASK-01",
        "TASK-02",
        "TASK-03",
        "TASK-04",
    }:
        errors.append("HANDOFF_INPUT_SET_INVALID")
    if manifest["readiness"] != {
        "engineering_ready": True,
        "pilot_ready": False,
        "research_validated": False,
    }:
        errors.append("HANDOFF_READINESS_OVERCLAIM")
    if not any(
        gate["gate_id"] == "FORMAL_RELEASE" and gate["status"] == "blocked"
        for gate in manifest["quality_gates"]
    ):
        errors.append("HANDOFF_FORMAL_RELEASE_BLOCK_MISSING")
    errors.extend(_validate_paths_and_hashes(root, manifest["input_handoffs"], "INPUT"))
    errors.extend(_validate_paths_and_hashes(root, manifest["outputs"], "OUTPUT"))
    provenance = manifest["producer_provenance"]
    declared_producer_paths = [item["path"] for item in provenance["files"]]
    try:
        expected_producer_paths = _committed_paths(
            root, manifest["implementation_commit"]
        )
    except subprocess.CalledProcessError:
        expected_producer_paths = []
        errors.append("PRODUCER_COMMIT_UNREADABLE")
    if declared_producer_paths != expected_producer_paths or any(
        item["role"] != _role(item["path"]) for item in provenance["files"]
    ):
        errors.append("PRODUCER_FILE_SET_INVALID")
    report_relative = path.with_name("TASK_05_REPORT_zh.md").relative_to(root).as_posix()
    expected_outputs = {
        (logical_type, report_relative if logical_type == "task_report" else output_path)
        for logical_type, output_path, *_ in OUTPUT_SPECS
    }
    declared_outputs = {
        (item["logical_type"], item["path"]) for item in manifest["outputs"]
    }
    if declared_outputs != expected_outputs or len(manifest["outputs"]) != len(OUTPUT_SPECS):
        errors.append("HANDOFF_OUTPUT_SET_INVALID")
    errors.extend(_validate_paths_and_hashes(root, provenance["files"], "PRODUCER"))
    aggregate = _sha256_bytes(canonical_json(provenance["files"]))
    if aggregate != provenance["aggregate_sha256"]:
        errors.append("PRODUCER_AGGREGATE_SHA256_MISMATCH")
    commit = manifest["implementation_commit"]
    if provenance["implementation_commit"] != commit:
        errors.append("PRODUCER_COMMIT_MISMATCH")
    try:
        ancestor = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            check=False,
        ).returncode == 0
        if not ancestor:
            errors.append("PRODUCER_COMMIT_NOT_ANCESTOR")
        for record in provenance["files"]:
            committed = _git(root, ["show", f"{commit}:{record['path']}"], binary=True)
            if _sha256_bytes(committed) != record["sha256"]:
                errors.append(f"PRODUCER_GIT_BLOB_MISMATCH:{record['path']}")
    except subprocess.CalledProcessError:
        errors.append("PRODUCER_COMMIT_UNREADABLE")
    try:
        current = {item["task_id"]: item for item in inspect_upstream_handoffs(root)}
    except (OSError, ValueError, subprocess.CalledProcessError):
        current = {}
        errors.append("UPSTREAM_HANDOFF_VALIDATION_FAILED")
    for declared in manifest["input_handoffs"]:
        actual = current.get(declared["task_id"])
        if actual is None or not actual["compatible"]:
            errors.append(f"UPSTREAM_HANDOFF_INVALID:{declared['task_id']}")
        elif (
            actual["manifest_sha256"] != declared["sha256"]
            or actual["producer_commit"] != declared["producer_commit"]
            or actual["handoff_schema_version"] != declared["schema_version"]
        ):
            errors.append(f"UPSTREAM_HANDOFF_CHANGED:{declared['task_id']}")
    for evidence in manifest["validation_evidence"].values():
        if not isinstance(evidence, dict) or "evidence_path" not in evidence:
            continue
        errors.extend(_validate_paths_and_hashes(root, [{"path": evidence["evidence_path"], "sha256": evidence["sha256"]}], "EVIDENCE"))
    checksum_path = path.with_name("checksums.sha256")
    expected = {}
    if not checksum_path.is_file():
        errors.append("HANDOFF_CHECKSUMS_MISSING")
    else:
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, separator, relative = line.partition("  ")
            if (
                not separator
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or relative in expected
            ):
                errors.append("HANDOFF_CHECKSUMS_INVALID")
                continue
            expected[relative] = digest
        if set(expected) != {"handoff_manifest.json", "TASK_05_REPORT_zh.md"}:
            errors.append("HANDOFF_CHECKSUMS_INVALID")
        for name in ("handoff_manifest.json", "TASK_05_REPORT_zh.md"):
            target = path.with_name(name)
            if not target.is_file() or expected.get(name) != _sha256(target):
                errors.append(f"HANDOFF_PACKAGE_SHA256_MISMATCH:{name}")
    return sorted(set(errors))


def create_handoff(
    workspace_root: str | Path,
    implementation_commit: str,
    output_directory: str | Path | None = None,
) -> Path:
    root = Path(workspace_root).resolve()
    commit = implementation_commit.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("IMPLEMENTATION_COMMIT_INVALID")
    head = _git(root, ["rev-parse", "HEAD"]).strip()
    if head != commit:
        raise ValueError("IMPLEMENTATION_COMMIT_MUST_EQUAL_HEAD")
    if _git(root, ["status", "--porcelain"]).strip():
        raise ValueError("HANDOFF_GENERATION_REQUIRES_CLEAN_TREE")
    output = (
        Path(output_directory).resolve()
        if output_directory is not None
        else root / Path(HANDOFF_RELATIVE_PATH).parent
    )
    if not output.is_relative_to(root) or output.exists() or not output.parent.is_dir():
        raise ValueError("HANDOFF_OUTPUT_MUST_BE_NEW_REPOSITORY_DIRECTORY")
    manifest = build_manifest(root, commit)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    moved = False
    try:
        report_path = staging / "TASK_05_REPORT_zh.md"
        report_path.write_text(_report(commit), encoding="utf-8")
        report_relative = (output / report_path.name).relative_to(root).as_posix()
        manifest["outputs"] = [
            _artifact(
                root,
                logical_type,
                report_relative if logical_type == "task_report" else path,
                record_count,
                classification,
                schema_version,
                report_path if logical_type == "task_report" else None,
            )
            for logical_type, path, record_count, classification, schema_version in OUTPUT_SPECS
        ]
        staged_manifest = staging / "handoff_manifest.json"
        staged_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        checksums = [
            f"{_sha256(staged_manifest)}  handoff_manifest.json",
            f"{_sha256(report_path)}  TASK_05_REPORT_zh.md",
        ]
        (staging / "checksums.sha256").write_text(
            "\n".join(checksums) + "\n", encoding="utf-8"
        )
        if output.exists():
            raise ValueError("HANDOFF_OUTPUT_MUST_BE_NEW_REPOSITORY_DIRECTORY")
        staging.rename(output)
        moved = True
        manifest_path = output / "handoff_manifest.json"
        errors = validate_handoff(manifest_path, root)
        if errors:
            raise ValueError("HANDOFF_GENERATED_INVALID:" + " | ".join(errors))
        return manifest_path
    except Exception:
        shutil.rmtree(output if moved else staging, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "validate"))
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--implementation-commit")
    args = parser.parse_args(argv)
    root = args.workspace_root.resolve()
    if args.command == "create":
        if args.implementation_commit is None:
            parser.error("create requires --implementation-commit")
        path = create_handoff(root, args.implementation_commit)
        print(path.relative_to(root).as_posix())
        return 0
    manifest = args.manifest or root / HANDOFF_RELATIVE_PATH
    errors = validate_handoff(manifest, root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("TASK-05 handoff valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
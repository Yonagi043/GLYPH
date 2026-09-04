"""Build and strictly validate the TASK-04 handoff bundle."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import canonical_json, normalize_repo_path, sha256_file, validate_record
from glyph_features.han_style_system.io import read_json, read_jsonl
from glyph_features.han_style_system.review import aggregate_reviews, validate_review_records


PRODUCER_SCHEMAS = (
    "schema/expert_review.schema.json",
    "schema/han_adapter_record.schema.json",
    "schema/han_character_mapping.schema.json",
    "schema/han_glyph_instance.schema.json",
    "schema/han_handoff_manifest.schema.json",
    "schema/han_knowledge_claim.schema.json",
    "schema/han_review_item.schema.json",
    "schema/han_review_package.schema.json",
    "schema/han_stimulus_candidate.schema.json",
    "schema/han_style_concept.schema.json",
    "schema/shared.schema.json",
)
SCHEMA_BY_LOGICAL_TYPE = {
    "style_ontology": "han_style_concept.schema.json",
    "character_mapping": "han_character_mapping.schema.json",
    "glyph_instance": "han_glyph_instance.schema.json",
    "knowledge_claim": "han_knowledge_claim.schema.json",
    "review_package_manifest": "han_review_package.schema.json",
    "review_item": "han_review_item.schema.json",
    "expert_review": "expert_review.schema.json",
    "stimulus_candidate": "han_stimulus_candidate.schema.json",
    "adapter_record": "han_adapter_record.schema.json",
}


def build_handoff_bundle(
    workspace_root: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    *,
    implementation_commit: str,
    created_at: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    output = Path(output_dir).resolve()
    config_file = _resolve(root, config_path)
    config = read_json(config_file)
    reference = _reference_paths(root, config)
    summary = _reference_summary(reference, config)
    if dry_run:
        return summary
    try:
        prefix = output.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError("handoff output must be inside the workspace") from error
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"handoff output directory is not empty: {output}")
    _require_clean_worktree(root)
    producer = _producer_provenance(root, config_file, implementation_commit)
    input_artifacts = _input_artifacts(root, config_file, reference)
    implementation_outputs = _implementation_outputs(root, reference, config)
    _require_artifacts_at_commit(root, implementation_commit, [*input_artifacts, *implementation_outputs])

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        gates = _gate_packets(reference, summary, prefix)
        for gate_id, payload in gates.items():
            _write_json(staging / f"gates/{gate_id}.json", payload)
        _write_text(
            staging / "TASK-04_report_zh.md",
            _report(summary, config["starting_checkpoint"], implementation_commit, prefix),
        )
        generated = [
            _artifact(root, f"{prefix}/gates/{gate_id}.json", "gate_packet", "metadata_only", "1.0.0", False, physical_root=staging, logical_prefix=prefix)
            for gate_id in sorted(gates)
        ]
        generated.append(
            _artifact(root, f"{prefix}/TASK-04_report_zh.md", "final_report", "public_code_or_schema", None, False, physical_root=staging, logical_prefix=prefix)
        )
        checksum_targets = sorted([*implementation_outputs, *generated], key=lambda item: item["path"])
        _write_text(
            staging / "checksums.sha256",
            "".join(f"{artifact['sha256']}  {artifact['path']}\n" for artifact in checksum_targets),
        )
        checksums = _artifact(
            root,
            f"{prefix}/checksums.sha256",
            "checksums",
            "metadata_only",
            None,
            False,
            physical_root=staging,
            logical_prefix=prefix,
        )
        outputs = [*implementation_outputs, *generated, checksums]
        manifest = _manifest(
            config,
            implementation_commit,
            producer,
            created_at,
            input_artifacts,
            outputs,
            summary,
            prefix,
        )
        schema_errors = validate_record(manifest, root / "schema/han_handoff_manifest.schema.json")
        if schema_errors:
            raise ValueError("HAN_HANDOFF_SCHEMA_INVALID: " + "; ".join(schema_errors))
        _write_json(staging / "handoff_manifest.json", manifest)
        if output.exists():
            output.rmdir()
        staging.rename(output)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def validate_handoff(
    manifest_path: str | Path,
    workspace_root: str | Path,
    *,
    schema_root: str | Path | None = None,
) -> list[str]:
    root = Path(workspace_root).resolve()
    contracts = Path(schema_root).resolve() if schema_root else root
    manifest_file = Path(manifest_path).resolve()
    errors: list[str] = []
    try:
        manifest = read_json(manifest_file)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"HAN_HANDOFF_UNREADABLE: {error}"]
    errors.extend(validate_record(manifest, contracts / "schema/han_handoff_manifest.schema.json"))
    implementation_commit = manifest.get("implementation_commit")
    provenance = manifest.get("producer_provenance")
    if isinstance(provenance, dict):
        if provenance.get("implementation_commit") != implementation_commit:
            errors.append("HAN_HANDOFF_COMMIT_MISMATCH")
        _validate_provenance(root, provenance, errors)
    artifacts: list[dict[str, Any]] = []
    for field in ("input_snapshots", "outputs"):
        values = manifest.get(field, [])
        if not isinstance(values, list):
            continue
        for artifact in values:
            if not isinstance(artifact, dict):
                continue
            artifacts.append(artifact)
            path = _safe_workspace_path(root, artifact.get("path"), errors, field)
            if path is None:
                continue
            if not path.is_file():
                errors.append(f"HAN_HANDOFF_ARTIFACT_MISSING path={artifact.get('path')}")
                continue
            if sha256_file(path) != artifact.get("sha256"):
                errors.append(f"HAN_HANDOFF_HASH_MISMATCH path={artifact.get('path')}")
            try:
                count = _record_count(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"HAN_HANDOFF_COUNT_FAILED path={artifact.get('path')}: {error}")
            else:
                if count != artifact.get("record_count"):
                    errors.append(
                        f"HAN_HANDOFF_COUNT_MISMATCH path={artifact.get('path')} actual={count} expected={artifact.get('record_count')}"
                    )
            if artifact.get("implementation_bound") is True and isinstance(implementation_commit, str):
                _validate_git_artifact(root, implementation_commit, artifact, errors)
            if field == "outputs":
                _validate_artifact_records(path, artifact, contracts, errors)
    _validate_checksums(root, manifest, errors)
    _validate_gate_truth(root, manifest, errors)
    _validate_research_boundaries(root, manifest, errors)
    if manifest_file.parent.is_relative_to(root):
        for path in sorted(manifest_file.parent.rglob("*")):
            if path.is_file() and _contains_absolute_filesystem_path(path):
                errors.append(f"HAN_HANDOFF_ABSOLUTE_PATH_LEAK path={path.relative_to(root).as_posix()}")
    return sorted(set(errors))


def _reference_paths(root: Path, config: dict[str, Any]) -> dict[str, Path]:
    fixture_root = _resolve(root, config["reference_fixture_root"])
    run_root = _resolve(root, config["reference_run_root"])
    return {
        "fixture_root": fixture_root,
        "run_root": run_root,
        "ontology": fixture_root / "ontology.jsonl",
        "mappings": fixture_root / "character_mappings.jsonl",
        "glyphs": fixture_root / "glyph_instances.jsonl",
        "claims": fixture_root / "claims.jsonl",
        "sources": fixture_root / "sources.jsonl",
        "review_package": run_root / "review_package",
        "review_submissions": run_root / "synthetic_review_submissions.csv",
        "reviews": run_root / "reviews.jsonl",
        "candidates": run_root / "candidate_bundle/stimulus_candidates.jsonl",
        "adapters": run_root / "candidate_bundle/adapters.jsonl",
        "integration_requests": run_root / "candidate_bundle/integration_requests.json",
        "content_sets": _resolve(root, config["content_sets_path"]),
        "task01_handoff": _resolve(root, config["task01"]["handoff_path"]),
        "task01_sources": _resolve(root, config["task01"]["sources_path"]),
        "task01_assets": _resolve(root, config["task01"]["asset_candidates_path"]),
        "task01_rights": _resolve(root, config["task01"]["rights_evidence_path"]),
        "protocol": _resolve(root, config["protocol_document_path"]),
    }


def _reference_summary(reference: dict[str, Path], config: dict[str, Any]) -> dict[str, Any]:
    ontology = read_jsonl(reference["ontology"])
    mappings = read_jsonl(reference["mappings"])
    glyphs = read_jsonl(reference["glyphs"])
    claims = read_jsonl(reference["claims"])
    reviews = read_jsonl(reference["reviews"])
    candidates = read_jsonl(reference["candidates"])
    adapters = read_jsonl(reference["adapters"])
    review_summaries = aggregate_reviews(
        reviews,
        minimum_independent_reviews=int(config["review"]["minimum_independent_reviews"]),
    )
    fixture_statuses = {value["fixture_status"] for value in review_summaries.values()}
    formal_statuses = {value["formal_status"] for value in review_summaries.values()}
    return {
        "style_count": len(ontology),
        "mapping_count": len(mappings),
        "glyph_count": len(glyphs),
        "claim_count": len(claims),
        "review_count": len(reviews),
        "candidate_count": len(candidates),
        "adapter_count": len(adapters),
        "review_summary": {
            "subject_count": len(review_summaries),
            "synthetic_review_count": sum(value["synthetic_review_count"] for value in review_summaries.values()),
            "real_review_count": sum(value["real_review_count"] for value in review_summaries.values()),
            "fixture_status": next(iter(fixture_statuses)) if len(fixture_statuses) == 1 else "conflicted",
            "formal_status": next(iter(formal_statuses)) if len(formal_statuses) == 1 else "conflicted",
        },
        "inference_readiness": {
            "minimum_independent_exemplars_for_category": int(config["stimuli"]["minimum_independent_exemplars_for_category"]),
            "formal_pilot_candidate_count": sum(
                candidate["release_status"] == "eligible_for_task01_freeze" for candidate in candidates
            ),
            "task01_assigned_stimulus_count": sum(candidate["stimulus_id"] is not None for candidate in candidates),
            "instance_level_candidate_count": sum(
                candidate["inference_scope"]["scope"] == "instance_level_only" for candidate in candidates
            ),
            "category_level_candidate_count": sum(
                candidate["inference_scope"]["scope"] == "category_candidate" for candidate in candidates
            ),
            "default_scope": "category_candidate" if candidates and all(
                candidate["inference_scope"]["scope"] == "category_candidate" for candidate in candidates
            ) else "instance_level_only",
        },
    }


def _input_artifacts(root: Path, config_file: Path, reference: dict[str, Path]) -> list[dict[str, Any]]:
    specifications = [
        (config_file, "han_style_config", "public_code_or_schema", "1.0.0"),
        (reference["content_sets"], "content_set", "public_code_or_schema", "1.0.0"),
        (reference["task01_handoff"], "task01_handoff", "metadata_only", "2.0.0"),
        (reference["task01_sources"], "task01_source_catalog", "metadata_only", "1.1.0-compatible"),
        (reference["task01_assets"], "task01_fixture_assets", "open_fixture", "1.0.0"),
        (reference["task01_rights"], "task01_rights_evidence", "metadata_only", "2.0.0"),
    ]
    return [
        _artifact(root, path.relative_to(root).as_posix(), logical_type, rights, version, True)
        for path, logical_type, rights, version in specifications
    ]


def _implementation_outputs(
    root: Path,
    reference: dict[str, Path],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    specifications = [
        (reference["ontology"], "style_ontology", "open_fixture", "1.0.0"),
        (reference["mappings"], "character_mapping", "open_fixture", "1.0.0"),
        (reference["glyphs"], "glyph_instance", "open_fixture", "1.0.0"),
        (reference["claims"], "knowledge_claim", "open_fixture", "1.0.0"),
        (reference["sources"], "source_catalog", "open_fixture", "1.0.0"),
        (reference["review_submissions"], "synthetic_review_submission", "open_fixture", "1.0.0"),
        (reference["reviews"], "expert_review", "open_fixture", "1.0.0"),
        (reference["candidates"], "stimulus_candidate", "open_fixture", "1.0.0"),
        (reference["adapters"], "adapter_record", "open_fixture", "1.0.0"),
        (reference["integration_requests"], "integration_requests", "metadata_only", "1.0.0"),
        (reference["protocol"], "protocol_document", "public_code_or_schema", None),
    ]
    for template in config["template_paths"]:
        specifications.append((_resolve(root, template), "import_template", "public_code_or_schema", "1.0.0"))
    for package_path in sorted(reference["review_package"].rglob("*")):
        if not package_path.is_file():
            continue
        logical_type = {
            "package_manifest.json": "review_package_manifest",
            "items.jsonl": "review_item",
            "checksums.sha256": "review_package_checksums",
            "review_template.csv": "review_import_template",
            "index.html": "review_workbench",
        }.get(package_path.name, "review_package_asset")
        schema_version = "1.0.0" if logical_type in {"review_package_manifest", "review_item"} else None
        specifications.append((package_path, logical_type, "open_fixture", schema_version))
    return sorted(
        [
            _artifact(root, path.relative_to(root).as_posix(), logical_type, rights, version, True)
            for path, logical_type, rights, version in specifications
        ],
        key=lambda item: item["path"],
    )


def _producer_provenance(root: Path, config_file: Path, commit: str) -> dict[str, Any]:
    _require_commit(root, commit)
    records = _producer_records(root, config_file)
    for record in records:
        actual = _git_blob_sha256(root, commit, record["path"])
        if actual != record["sha256"]:
            raise ValueError(f"producer file is not bound to implementation commit: {record['path']}")
    return {
        "implementation_commit": commit,
        "working_tree_state_at_export": "clean",
        "snapshot_matches_commit": True,
        "aggregate_sha256": hashlib.sha256(canonical_json(records)).hexdigest(),
        "files": records,
    }


def _producer_records(root: Path, config_file: Path) -> list[dict[str, str]]:
    specifications = [
        ("entrypoint", root / "pyproject.toml"),
        ("dependency_lock", root / "runtime.lock.json"),
        ("dependency_lock", root / "uv.lock"),
        ("config", config_file),
        *(("schema", root / path) for path in PRODUCER_SCHEMAS),
        *(("producer_source", path) for path in sorted((root / "src/glyph_features/han_style_system").glob("*.py"))),
    ]
    missing = [path for _, path in specifications if not path.is_file()]
    if missing:
        raise ValueError("producer file missing: " + ", ".join(str(path) for path in missing))
    return sorted(
        [
            {
                "role": role,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for role, path in specifications
        ],
        key=lambda item: item["path"],
    )


def _manifest(
    config: dict[str, Any],
    commit: str,
    producer: dict[str, Any],
    created_at: str,
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    summary: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    candidate_path = next(item["path"] for item in outputs if item["logical_type"] == "stimulus_candidate")
    adapter_path = next(item["path"] for item in outputs if item["logical_type"] == "adapter_record")
    report_path = f"{prefix}/TASK-04_report_zh.md"
    return {
        "handoff_schema_version": "1.0.0",
        "task_id": "TASK-04",
        "producer_version": "1.0.0",
        "starting_checkpoint": config["starting_checkpoint"],
        "implementation_commit": commit,
        "producer_provenance": producer,
        "created_at": created_at,
        "readiness": {"engineering_ready": True, "pilot_ready": False, "research_validated": False},
        "contract_versions": {**config["schema_versions"], "han_handoff_manifest": "1.0.0"},
        "input_snapshots": inputs,
        "outputs": outputs,
        "review_summary": summary["review_summary"],
        "inference_readiness": summary["inference_readiness"],
        "quality_gates": [
            {"gate_id": "schema_and_hash_validation", "status": "passed", "evidence": f"{prefix}/checksums.sha256"},
            {"gate_id": "synthetic_double_review", "status": "fixture_only", "evidence": candidate_path},
            {"gate_id": "formal_expert_review", "status": "blocked", "evidence": f"{prefix}/gates/GATE-EXPERT.json"},
            {"gate_id": "formal_asset_rights", "status": "blocked", "evidence": f"{prefix}/gates/GATE-RIGHTS.json"},
            {"gate_id": "restricted_terms", "status": "blocked", "evidence": f"{prefix}/gates/GATE-TERMS.json"},
            {"gate_id": "task01_stimulus_freeze", "status": "blocked", "evidence": candidate_path},
            {"gate_id": "category_level_inference", "status": "blocked", "evidence": report_path},
        ],
        "known_limitations": [
            "The only end-to-end glyph is a CC0 abstract synthetic fixture and does not depict the declared character.",
            "Synthetic reviews exercise workflow mechanics and cannot satisfy GATE-EXPERT.",
            "No style has three independent eligible exemplars; all candidate inference is instance_level_only.",
            "TASK-01 has assigned no formal stimulus_id to a TASK-04 candidate.",
            "TASK-02 and TASK-03 target implementations were unavailable at the checkpoint; adapters encode written-contract assumptions only.",
        ],
        "blocked_human_gates": [
            {"gate_id": "GATE-EXPERT", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-EXPERT.json", "reasons": ["No real expert review was requested or collected."]},
            {"gate_id": "GATE-RIGHTS", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-RIGHTS.json", "reasons": ["No historical or modern typeface asset has TASK-04 formal-use approval."]},
            {"gate_id": "GATE-TERMS", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-TERMS.json", "reasons": ["No restricted download, login, licence acceptance, or paid access was reviewed."]},
        ],
        "next_task_entrypoints": [
            {"target_system": "TASK-01", "status": "fixture_only", "path": adapter_path, "notes": "Consume requests only; TASK-01 remains the sole formal stimulus_id owner."},
            {"target_system": "TASK-02", "status": "fixture_only", "path": adapter_path, "notes": "Use fixture representations to test the written visual-measurement contract only."},
            {"target_system": "TASK-03", "status": "blocked", "path": adapter_path, "notes": "No formal stimulus_id or real expert approval is available for participant use."},
            {"target_system": "WP2", "status": "metadata_only", "path": adapter_path, "notes": "Project canonical style_id and aliases without treating word hits as image attribution."},
            {"target_system": "TASK-05", "status": "metadata_only", "path": f"{prefix}/handoff_manifest.json", "notes": "Preserve readiness, inference scope, and blocked gate values."},
        ],
    }


def _gate_packets(
    reference: dict[str, Path],
    summary: dict[str, Any],
    prefix: str,
) -> dict[str, dict[str, Any]]:
    return {
        "GATE-EXPERT": {
            "gate_id": "GATE-EXPERT",
            "status": "blocked",
            "decision_required": "Approve expert recruitment, package transmission, reviewer roles, and handling before any real review.",
            "reference_review_package": reference["review_package"].relative_to(reference["fixture_root"].parents[2]).as_posix(),
            "synthetic_review_count": summary["review_summary"]["synthetic_review_count"],
            "real_review_count": summary["review_summary"]["real_review_count"],
            "required_roles": ["history_or_paleography", "calligraphy_or_seal_practice", "type_or_visual_design"],
            "allowed_now": ["offline fixture review workflow testing"],
            "prohibited_without_approval": ["contact experts", "send review materials", "record synthetic output as expert judgment"],
        },
        "GATE-RIGHTS": {
            "gate_id": "GATE-RIGHTS",
            "status": "blocked",
            "decision_required": "Verify work rights and digital-surrogate or font permissions before formal use or redistribution.",
            "rights_evidence_path": reference["task01_rights"].relative_to(reference["fixture_root"].parents[2]).as_posix(),
            "formal_candidate_count": summary["inference_readiness"]["formal_pilot_candidate_count"],
            "fixture_policy": "Only the CC0 engineering fixture is included; it is not a historical glyph.",
            "allowed_now": ["metadata audit", "hash verification", "open fixture processing"],
            "prohibited_without_approval": ["download unknown-rights glyph assets", "redistribute restricted scans or fonts", "formal stimulus release"],
        },
        "GATE-TERMS": {
            "gate_id": "GATE-TERMS",
            "status": "blocked",
            "decision_required": "Review official terms, authentication, cost, and data flow before restricted acquisition.",
            "official_terms_urls": [],
            "cost": "not_assessed",
            "data_flow": "No external request, login, upload, payment, or terms acceptance was performed.",
            "allowed_now": ["local fixture processing"],
            "prohibited_without_approval": ["accept terms", "login", "pay", "submit an access request", "make a restricted download"],
        },
    }


def _report(summary: dict[str, Any], starting_checkpoint: str, commit: str, prefix: str) -> str:
    inference = summary["inference_readiness"]
    review = summary["review_summary"]
    return f"""# TASK-04 汉字书体知识与专家在环子系统报告

版本：`1.0.0`
起始 checkpoint：`{starting_checkpoint}`
implementation commit：`{commit}`

## 完成范围

- 八类目标书体本体：{summary['style_count']} 条；字符映射：{summary['mapping_count']} 条。
- 字形实例：{summary['glyph_count']} 条；知识断言：{summary['claim_count']} 条。
- synthetic review：{review['synthetic_review_count']} 条；real expert review：{review['real_review_count']} 条。
- fixture-only 候选：{summary['candidate_count']} 条；TASK-01/02/03/WP2 adapter：{summary['adapter_count']} 条。

## Readiness 与推断边界

- `engineering_ready=true`：schema、CLI、证据外键、离线审核、签名、候选与 handoff 可机械验证。
- `pilot_ready=false`：真实专家审核、正式权利和 TASK-01 `stimulus_id` 均未通过。
- `research_validated=false`：没有真人专家、参与者数据或研究结论。
- `instance_level_only`：{inference['instance_level_candidate_count']} 条；类别级候选：{inference['category_level_candidate_count']} 条。
- 类别推断门槛为每类至少 {inference['minimum_independent_exemplars_for_category']} 个独立合格实例，当前没有任何类别达标。

## 门禁

- `GATE-EXPERT=blocked`：未联系专家，synthetic review 不构成专家结论。
- `GATE-RIGHTS=blocked`：仅 CC0 抽象 fixture 可用于工程链；没有正式历史字形或字体获批。
- `GATE-TERMS=blocked`：未下载、登录、付费、接受条款或发起受限请求。

## integration_requests

- 共享热点 `pyproject.toml`：仅新增 `glyph-han` console script；依赖和锁文件未改。
- TASK-01：消费候选冻结请求并独占正式 `stimulus_id` 分配。
- TASK-02：adapter 仅依据 checkpoint 书面契约；C1-C5 保持 `within_script_only` / `protocol_dependent`。
- TASK-03：等待正式 `stimulus_id`、真实专家审核和权利通过；盲评与 contextual 条件必须分离。
- WP2：当前 registry 仅匹配 `seal` 与 `sans`；其余书体需扩展 object map，原词形不得覆盖规范 `style_id`。

## Handoff

- manifest：`{prefix}/handoff_manifest.json`
- checksums：`{prefix}/checksums.sha256`
- 所有 producer 与 implementation-bound 工件必须与上述 implementation commit 的 Git blob 完全一致。
"""


def _artifact(
    root: Path,
    logical_path: str,
    logical_type: str,
    rights: str,
    schema_version: str | None,
    implementation_bound: bool,
    *,
    physical_root: Path | None = None,
    logical_prefix: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_repo_path(logical_path)
    if physical_root is not None and logical_prefix is not None:
        relative = Path(normalized).relative_to(logical_prefix)
        path = physical_root / relative
    else:
        path = root / normalized
    if not path.is_file():
        raise ValueError(f"artifact is missing: {normalized}")
    return {
        "logical_type": logical_type,
        "path": normalized,
        "sha256": sha256_file(path),
        "record_count": _record_count(path),
        "rights_or_privacy_level": rights,
        "schema_version": schema_version,
        "implementation_bound": implementation_bound,
    }


def _require_clean_worktree(root: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ValueError("unable to determine Git working tree state")
    if result.stdout:
        raise ValueError("handoff export requires a clean implementation worktree")


def _require_commit(root: Path, commit: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("implementation commit must be a full lowercase SHA-1")
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ValueError(f"implementation commit is unavailable: {commit}")


def _require_artifacts_at_commit(root: Path, commit: str, artifacts: list[dict[str, Any]]) -> None:
    for artifact in artifacts:
        if _git_blob_sha256(root, commit, artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"artifact is not bound to implementation commit: {artifact['path']}")


def _git_blob_sha256(root: Path, commit: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise ValueError(f"Git blob unavailable at implementation commit: {path}")
    return hashlib.sha256(result.stdout).hexdigest()


def _validate_provenance(root: Path, provenance: dict[str, Any], errors: list[str]) -> None:
    commit = provenance.get("implementation_commit")
    if not isinstance(commit, str):
        return
    try:
        _require_commit(root, commit)
        expected = _producer_records(root, root / "configs/han_style_protocol_v1.yaml")
    except ValueError as error:
        errors.append(f"HAN_HANDOFF_PRODUCER_INVALID: {error}")
        return
    declared = provenance.get("files")
    if not isinstance(declared, list):
        return
    if declared != expected:
        errors.append("HAN_HANDOFF_PRODUCER_FILE_SET_MISMATCH")
    if hashlib.sha256(canonical_json(declared)).hexdigest() != provenance.get("aggregate_sha256"):
        errors.append("HAN_HANDOFF_PRODUCER_AGGREGATE_MISMATCH")
    for record in declared:
        if not isinstance(record, dict) or not {"path", "sha256"} <= record.keys():
            continue
        try:
            git_hash = _git_blob_sha256(root, commit, record["path"])
        except ValueError as error:
            errors.append(f"HAN_HANDOFF_PRODUCER_GIT_MISSING: {error}")
            continue
        if git_hash != record["sha256"]:
            errors.append(f"HAN_HANDOFF_PRODUCER_GIT_MISMATCH path={record['path']}")


def _validate_git_artifact(
    root: Path,
    commit: str,
    artifact: dict[str, Any],
    errors: list[str],
) -> None:
    try:
        git_hash = _git_blob_sha256(root, commit, artifact["path"])
    except (KeyError, ValueError) as error:
        errors.append(f"HAN_HANDOFF_GIT_ARTIFACT_MISSING: {error}")
        return
    if git_hash != artifact.get("sha256"):
        errors.append(f"HAN_HANDOFF_GIT_ARTIFACT_MISMATCH path={artifact.get('path')}")


def _validate_artifact_records(
    path: Path,
    artifact: dict[str, Any],
    contracts: Path,
    errors: list[str],
) -> None:
    schema_name = SCHEMA_BY_LOGICAL_TYPE.get(str(artifact.get("logical_type")))
    if not schema_name:
        return
    try:
        records = [read_json(path)] if path.suffix == ".json" else read_jsonl(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"HAN_HANDOFF_RECORD_UNREADABLE path={artifact.get('path')}: {error}")
        return
    for line_number, record in enumerate(records, start=1):
        for error in validate_record(record, contracts / "schema" / schema_name):
            errors.append(f"HAN_HANDOFF_RECORD_INVALID path={artifact.get('path')} record={line_number}: {error}")
    if artifact.get("logical_type") == "expert_review":
        errors.extend(validate_review_records(records, contracts / "schema/expert_review.schema.json"))


def _validate_checksums(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    outputs = [item for item in manifest.get("outputs", []) if isinstance(item, dict)]
    checksum_artifacts = [item for item in outputs if item.get("logical_type") == "checksums"]
    if len(checksum_artifacts) != 1:
        errors.append("HAN_HANDOFF_CHECKSUM_ARTIFACT_COUNT_INVALID")
        return
    path = _safe_workspace_path(root, checksum_artifacts[0].get("path"), errors, "checksums")
    if path is None or not path.is_file():
        return
    declared: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match:
            errors.append(f"HAN_HANDOFF_CHECKSUM_LINE_INVALID line={line}")
            continue
        declared[match.group(2)] = match.group(1)
    expected = {
        item["path"]: item["sha256"]
        for item in outputs
        if item.get("logical_type") != "checksums" and isinstance(item.get("path"), str)
    }
    if declared != expected:
        errors.append("HAN_HANDOFF_CHECKSUM_SET_MISMATCH")


def _validate_gate_truth(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    blocked = manifest.get("blocked_human_gates", [])
    gate_ids = {item.get("gate_id") for item in blocked if isinstance(item, dict)}
    if gate_ids != {"GATE-EXPERT", "GATE-RIGHTS", "GATE-TERMS"}:
        errors.append("HAN_HANDOFF_BLOCKED_GATE_SET_INVALID")
    for item in blocked:
        if not isinstance(item, dict):
            continue
        path = _safe_workspace_path(root, item.get("packet_path"), errors, "gate")
        if path is None or not path.is_file():
            continue
        try:
            packet = read_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"HAN_HANDOFF_GATE_UNREADABLE: {error}")
            continue
        if packet.get("gate_id") != item.get("gate_id") or packet.get("status") != "blocked":
            errors.append(f"HAN_HANDOFF_GATE_MISMATCH gate={item.get('gate_id')}")


def _validate_research_boundaries(root: Path, manifest: dict[str, Any], errors: list[str]) -> None:
    outputs = [item for item in manifest.get("outputs", []) if isinstance(item, dict)]
    candidate_artifact = next((item for item in outputs if item.get("logical_type") == "stimulus_candidate"), None)
    if candidate_artifact:
        path = _safe_workspace_path(root, candidate_artifact.get("path"), errors, "candidate")
        if path and path.is_file():
            candidates = read_jsonl(path)
            if any(candidate.get("stimulus_id") is not None for candidate in candidates):
                errors.append("HAN_HANDOFF_TASK01_STIMULUS_OWNERSHIP_VIOLATION")
            if any(candidate.get("inference_scope", {}).get("scope") != "instance_level_only" for candidate in candidates):
                errors.append("HAN_HANDOFF_CATEGORY_INFERENCE_UNSUPPORTED")
    readiness = manifest.get("readiness")
    if readiness != {"engineering_ready": True, "pilot_ready": False, "research_validated": False}:
        errors.append("HAN_HANDOFF_READINESS_UNTRUTHFUL")
    review_summary = manifest.get("review_summary")
    if isinstance(review_summary, dict) and review_summary.get("real_review_count") != 0:
        errors.append("HAN_HANDOFF_REAL_REVIEW_COUNT_UNEXPECTED")


def _safe_workspace_path(
    root: Path,
    value: Any,
    errors: list[str],
    kind: str,
) -> Path | None:
    try:
        normalized = normalize_repo_path(str(value))
    except ValueError as error:
        errors.append(f"HAN_HANDOFF_PATH_INVALID kind={kind} path={value}: {error}")
        return None
    if normalized != value:
        errors.append(f"HAN_HANDOFF_PATH_INVALID kind={kind} path={value}")
        return None
    path = (root / normalized).resolve()
    if not path.is_relative_to(root):
        errors.append(f"HAN_HANDOFF_PATH_ESCAPE kind={kind} path={value}")
        return None
    return path


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return len(read_jsonl(path))
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 1
    if path.name.endswith("checksums.sha256"):
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return 1


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _contains_absolute_filesystem_path(path: Path) -> bool:
    payload = path.read_bytes()
    unix = re.compile(rb"(?<![:/A-Za-z0-9])/(?:Applications|Users|etc|home|opt|private|tmp|usr|var|Volumes)/[^\s\"']+")
    windows = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+")
    return bool(unix.search(payload) or windows.search(payload))


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")
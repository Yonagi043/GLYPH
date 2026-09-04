"""Build and validate an immutable TASK-01 handoff bundle."""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from . import PROTOCOL_VERSION
from .catalog import (
    build_open_fixture,
    build_repository_inventory,
    canonical_json,
    load_json_config,
    migrate_award_sources,
    normalize_repo_path,
    sha256_file,
    validate_record,
)
from .curation import build_review_queue, freeze_ecological_stimulus
from .rights import build_rights_evidence
from .transform import config_sha256, transform_candidate


SCHEMA_BY_LOGICAL_TYPE = {
    "source_catalog": "source.schema.json",
    "repository_asset_candidates": "asset_candidate.schema.json",
    "fixture_asset_candidates": "asset_candidate.schema.json",
    "rights_evidence": "rights_evidence.schema.json",
    "fixture_stimuli": "ecological_stimulus.schema.json",
}

SOURCE_MIGRATION_FIELDS = [
    "source_id", "award", "year", "edition", "work_id", "local_path", "recorded_file",
    "asset_url", "source_page_url", "bytes_reported", "award_status", "title", "creator",
    "category", "fetched_at", "legacy_source_path", "legacy_source_sha256", "legacy_row_number",
    "repair_codes",
]
SOURCE_ISSUE_FIELDS = ["award", "source_path", "row_number", "code", "detail"]
REVIEW_QUEUE_FIELDS = [
    "asset_id", "asset_path", "source_id", "work_id", "candidate_kind", "rights_tier",
    "automated_qc_status", "automated_suggestion", "width_px", "height_px", "human_decision",
    "curation_status", "target_bbox_json", "target_polygon_json", "reviewer_id", "reviewed_at", "exclusion_codes", "notes",
]
PRODUCER_SCHEMA_FILES = [
    "schema/asset_candidate.schema.json",
    "schema/ecological_stimulus.schema.json",
    "schema/handoff_manifest.schema.json",
    "schema/rights_evidence.schema.json",
    "schema/shared.schema.json",
    "schema/source.schema.json",
]


def build_handoff_bundle(
    repo_root: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    *,
    git_commit: str,
    created_at: str,
    artifact_path_prefix: str | None = None,
    inventory_data: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"handoff output directory is non-empty: {output}")
    prefix = normalize_repo_path(artifact_path_prefix) if artifact_path_prefix else output.relative_to(root).as_posix()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = root / config_file
    config = load_json_config(config_file)
    if inventory_data is None:
        source_audit = migrate_award_sources(root, config)
        inventory = build_repository_inventory(root, config, source_audit)
    else:
        inventory = inventory_data
    fixture = build_open_fixture(root, config)
    summary = {
        "repository": inventory["summary"],
        "fixture_original_count": 1,
        "planned_fixture_representation_count": 4,
        "readiness": {"engineering_ready": True, "pilot_ready": False, "research_validated": False},
    }
    if dry_run:
        return summary

    producer_provenance = _producer_provenance(root, config_file, git_commit)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        fixture_derived: list[dict[str, Any]] = []
        source_path = root / fixture["candidate"]["asset_ref"]["path"]
        for representation in ("A_layout", "B_shape", "C_ink"):
            fixture_derived.extend(
                transform_candidate(
                    fixture["candidate"],
                    source_path,
                    staging / "fixture/derived",
                    representation,
                    config,
                    logical_output_root=f"{prefix}/fixture/derived",
                )
            )
        sources = sorted(inventory["sources"] + [fixture["source"]], key=lambda item: item["source_id"])
        rights_evidence = build_rights_evidence(
            sources,
            checked_at=config["inventory"]["snapshot_date"],
            fixture_source_id=fixture["source"]["source_id"],
        )
        fixture_rights = next(item for item in rights_evidence if item["source_id"] == fixture["source"]["source_id"])
        fixture_stimulus = freeze_ecological_stimulus(
            fixture["candidate"],
            fixture_derived,
            created_at=created_at,
            fixture_only=True,
            rights_evidence=fixture_rights,
        )
        _validate_bundle_records(root, inventory["candidates"], sources, rights_evidence, fixture["candidate"], fixture_derived, fixture_stimulus)

        _write_jsonl(staging / "sources.jsonl", sources)
        _write_jsonl(staging / "repository_asset_candidates.jsonl", inventory["candidates"])
        _write_jsonl(staging / "rights_evidence.jsonl", rights_evidence)
        _write_jsonl(staging / "fixture/asset_candidates.jsonl", [fixture["candidate"], *fixture_derived])
        _write_jsonl(staging / "fixture/stimuli.jsonl", [fixture_stimulus])
        _write_csv(
            staging / "source_migration.csv",
            inventory["source_audit"]["normalized_rows"],
            SOURCE_MIGRATION_FIELDS,
        )
        _write_csv(staging / "source_issues.csv", inventory["source_audit"]["issues"], SOURCE_ISSUE_FIELDS)
        _write_csv(staging / "review_queue.csv", build_review_queue(inventory["candidates"]), REVIEW_QUEUE_FIELDS)
        _write_json(staging / "inventory_summary.json", summary)
        run_manifest = _run_manifest(root, config_file, config, inventory, fixture, producer_provenance, created_at)
        _write_json(staging / "run_manifest.json", run_manifest)
        _write_text(staging / "quality_report.md", _quality_report(summary, inventory["source_audit"]["issues"]))
        gate_packets = _gate_packets(summary, prefix)
        for gate_id, payload in gate_packets.items():
            _write_json(staging / f"gates/{gate_id}.json", payload)

        preliminary_files = sorted(path for path in staging.rglob("*") if path.is_file())
        checksum_lines = [f"{sha256_file(path)}  {path.relative_to(staging).as_posix()}" for path in preliminary_files]
        _write_text(staging / "checksums.sha256", "\n".join(checksum_lines) + "\n")
        artifacts = _output_artifacts(staging, prefix, inventory, sources, rights_evidence, fixture_derived)
        handoff = _handoff_manifest(
            root,
            prefix,
            config_file,
            config,
            inventory,
            fixture,
            artifacts,
            producer_provenance,
            created_at,
        )
        handoff_errors = validate_record(handoff, root / "schema/handoff_manifest.schema.json")
        if handoff_errors:
            raise ValueError("invalid handoff manifest: " + "; ".join(handoff_errors))
        _write_json(staging / "handoff_manifest.json", handoff)
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
    input_root: str | Path | None = None,
) -> list[str]:
    manifest_file = Path(manifest_path)
    root = Path(workspace_root).resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    contracts = Path(schema_root).resolve() if schema_root else root
    inputs = Path(input_root).resolve() if input_root else root
    errors = validate_record(manifest, contracts / "schema/handoff_manifest.schema.json")
    _validate_producer_provenance(manifest, manifest_file, inputs, errors)
    for artifact in manifest.get("input_snapshots", []):
        if not isinstance(artifact, dict) or not {"path", "sha256", "record_count"} <= artifact.keys():
            continue
        path = _artifact_path(inputs, artifact["path"], errors, "input")
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"missing input: {artifact['path']}")
            continue
        if sha256_file(path) != artifact["sha256"]:
            errors.append(f"input hash mismatch: {artifact['path']}")
        actual_count = _record_count(path)
        if actual_count != artifact["record_count"]:
            errors.append(f"input record count mismatch: {artifact['path']}: {actual_count} != {artifact['record_count']}")
    output_paths: list[tuple[str, Path]] = []
    for artifact in manifest.get("outputs", []):
        if not isinstance(artifact, dict) or not {"path", "sha256", "record_count", "logical_type"} <= artifact.keys():
            continue
        path = _artifact_path(root, artifact["path"], errors, "output")
        if path is None:
            continue
        if not path.is_file():
            errors.append(f"missing output: {artifact['path']}")
            continue
        output_paths.append((artifact["path"], path))
        if sha256_file(path) != artifact["sha256"]:
            errors.append(f"hash mismatch: {artifact['path']}")
        actual_count = _record_count(path)
        if actual_count != artifact["record_count"]:
            errors.append(f"record count mismatch: {artifact['path']}: {actual_count} != {artifact['record_count']}")
        schema_name = SCHEMA_BY_LOGICAL_TYPE.get(artifact["logical_type"])
        if schema_name:
            for line_number, record in enumerate(_read_jsonl(path), start=1):
                for error in validate_record(record, contracts / "schema" / schema_name):
                    errors.append(f"{artifact['path']} line {line_number}: {error}")
    bundle_files = sorted(path for path in manifest_file.parent.rglob("*") if path.is_file())
    for path in bundle_files:
        logical_path = path.relative_to(manifest_file.parent).as_posix()
        if _contains_absolute_filesystem_path(path):
            errors.append(f"absolute filesystem path leak: {logical_path}")
    return errors


def _artifact_path(root: Path, value: str, errors: list[str], kind: str) -> Path | None:
    try:
        relative = normalize_repo_path(value)
    except ValueError as error:
        errors.append(f"unsafe {kind} path: {value}: {error}")
        return None
    return root / relative


def _validate_bundle_records(
    root: Path,
    candidates: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    rights: list[dict[str, Any]],
    fixture_original: dict[str, Any],
    fixture_derived: list[dict[str, Any]],
    fixture_stimulus: dict[str, Any],
) -> None:
    groups = [
        (sources, "source.schema.json"),
        ([*candidates, fixture_original, *fixture_derived], "asset_candidate.schema.json"),
        (rights, "rights_evidence.schema.json"),
        ([fixture_stimulus], "ecological_stimulus.schema.json"),
    ]
    errors: list[str] = []
    for records, schema_name in groups:
        for index, record in enumerate(records):
            errors.extend(f"{schema_name}[{index}]: {error}" for error in validate_record(record, root / "schema" / schema_name))
    if errors:
        raise ValueError("bundle schema validation failed: " + "; ".join(errors[:20]))


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    rows = list(records)
    _write_text(path, "".join(canonical_json(record).decode("utf-8") + "\n" for record in rows))


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    values = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in values:
            writer.writerow({key: _csv_value(row.get(key)) for key in writer.fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return value


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _run_manifest(
    root: Path,
    config_file: Path,
    config: dict[str, Any],
    inventory: dict[str, Any],
    fixture: dict[str, Any],
    producer_provenance: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "run_type": "TASK-01_asset_inventory_and_fixture",
        "protocol_version": PROTOCOL_VERSION,
        "created_at": created_at,
        "base_commit": producer_provenance["base_commit"],
        "working_tree_state": producer_provenance["working_tree_state"],
        "producer_snapshot_matches_base": producer_provenance["producer_snapshot_matches_base"],
        "producer_source_snapshot_sha256": producer_provenance["aggregate_sha256"],
        "config_path": config_file.relative_to(root).as_posix(),
        "config_sha256": config_sha256(config),
        "source_table_snapshots": inventory["source_audit"]["source_table_snapshots"],
        "fixture_sha256": fixture["candidate"]["asset_ref"]["sha256"],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pillow": version("Pillow"),
            "fonttools": version("fonttools"),
            "jsonschema": version("jsonschema"),
            "python_implementation": platform.python_implementation(),
        },
    }


def _quality_report(summary: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    repository = summary["repository"]
    lines = [
        "# TASK-01 asset quality report",
        "",
        "This report describes ecological candidates and an open engineering fixture. Award images are not clean logos or aesthetic ground truth.",
        "",
        "## Inventory",
        "",
        f"- Candidate records: {repository['candidate_count']}",
        f"- Award image files: {repository['image_file_count']}",
        f"- Unique award-image SHA-256 values: {repository['image_unique_sha256_count']}",
        f"- Unique works: {repository['unique_work_count']}",
        f"- Font files / primary families: {repository['font_file_count']} / {repository['font_family_count']}",
        f"- Curation passed: {repository['curation_passed_count']}",
        f"- Oversize images: {repository['oversize_image_count']}",
        f"- Exact-duplicate files: {repository['exact_duplicate_file_count']}",
        f"- Near-duplicate suggestions: {repository['near_duplicate_file_count']}",
        "",
        "| Award | Files | Unique binaries | Unique works | Curated |",
        "|---|---:|---:|---:|---:|",
    ]
    for award, values in repository["awards"].items():
        lines.append(f"| {award} | {values['file_count']} | {values['unique_binary_count']} | {values['unique_work_count']} | {values['curation_passed_count']} |")
    lines.extend(
        [
            "",
            "## Award-year coverage",
            "",
            "| Award | Year | Files | Unique binaries | Unique works | Curated |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for award, years in repository.get("award_years", {}).items():
        for year, values in years.items():
            lines.append(
                f"| {award} | {year} | {values['file_count']} | {values['unique_binary_count']} | "
                f"{values['unique_work_count']} | {values['curation_passed_count']} |"
            )
    lines.extend(["", "## Automated content suggestions", "", "These labels are triage suggestions, not human gold.", ""])
    for content_class, count in repository.get("content_suggestions", {}).items():
        lines.append(f"- `{content_class}`: {count}")
    lines.extend(["", "## Rights and QC", ""])
    for rights_tier, count in repository["rights_tiers"].items():
        lines.append(f"- Rights `{rights_tier}`: {count}")
    for qc_status, count in repository.get("qc_statuses", {}).items():
        lines.append(f"- QC `{qc_status}`: {count}")
    lines.extend(
        [
            "",
            "## Font families",
            "",
            "Internal font metadata is descriptive only and does not establish redistribution rights.",
            "",
            "| Family | Files | Subfamilies | Regional glyph metadata | Rights |",
            "|---|---:|---|---|---|",
        ]
    )
    for family in repository.get("font_families", []):
        subfamilies = ", ".join(family["subfamily_names"]) or "unknown"
        regions = ", ".join(family["regional_glyphs"]) or "unknown"
        rights = ", ".join(f"{key}:{value}" for key, value in family["rights_tiers"].items())
        lines.append(f"| {family['family_name']} | {family['file_count']} | {subfamilies} | {regions} | {rights} |")
    issue_counts: dict[str, int] = {}
    for issue in issues:
        issue_counts[issue["code"]] = issue_counts.get(issue["code"], 0) + 1
    lines.extend(["", "## Source migration", ""])
    for code, count in sorted(issue_counts.items()):
        lines.append(f"- `{code}`: {count}")
    lines.extend(
        [
            "",
            "## Readiness",
            "",
            "- `engineering_ready=true`: schema, inventory, source migration, A/B/C fixture, checksums, and mechanical gates are executable.",
            "- `pilot_ready=false`: no award image or font has verified rights plus human curation.",
            "- `research_validated=false`: no real participant, expert, or outcome validation was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def _gate_packets(summary: dict[str, Any], prefix: str) -> dict[str, dict[str, Any]]:
    repository = summary["repository"]
    return {
        "GATE-RIGHTS": {
            "gate_id": "GATE-RIGHTS",
            "status": "blocked",
            "decision_required": "Human review of licence evidence and allowed research/redistribution uses.",
            "blocked_candidate_count": repository["candidate_count"],
            "evidence_path": f"{prefix}/rights_evidence.jsonl",
            "review_queue_path": f"{prefix}/review_queue.csv",
            "protocol_path": "docs/asset_curation_protocol_zh.md",
            "allowed_now": ["metadata audit", "local hashing", "open fixture processing"],
            "prohibited_without_approval": ["public redistribution", "formal stimulus release", "upload to third-party storage"],
        },
        "GATE-HISTORY": {
            "gate_id": "GATE-HISTORY",
            "status": "blocked",
            "decision_required": "Choose a large-file history remediation strategy after reviewing the documented trade-offs.",
            "remediation_plan_path": "docs/asset_history_remediation_plan_zh.md",
            "prohibited_without_approval": ["filter-repo", "force push", "remote asset deletion", "history replacement"],
        },
        "GATE-TERMS": {
            "gate_id": "GATE-TERMS",
            "status": "blocked",
            "decision_required": "Review official terms, cost, authentication, and data flow before any restricted request.",
            "official_terms_urls": [],
            "cost": "not_assessed",
            "data_flow": "No login, upload, payment, or restricted network request was performed.",
            "protocol_path": "docs/asset_curation_protocol_zh.md",
            "prohibited_without_approval": ["accept terms", "login", "pay", "submit access request", "make first restricted request"],
        },
        "GATE-RELEASE": {
            "gate_id": "GATE-RELEASE",
            "status": "blocked",
            "decision_required": "Approve a release candidate only after rights, human curation, QC, and downstream protocol gates pass.",
            "fixture_path": f"{prefix}/fixture/stimuli.jsonl",
            "fixture_release_status": "fixture_only",
            "formal_curation_passed_count": repository["curation_passed_count"],
            "required_gates": ["GATE-RIGHTS", "human_curation", "automated_qc", "GATE-RELEASE"],
        },
    }


def _output_artifacts(
    staging: Path,
    prefix: str,
    inventory: dict[str, Any],
    sources: list[dict[str, Any]],
    rights: list[dict[str, Any]],
    fixture_derived: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    specifications = [
        ("source_catalog", "sources.jsonl", len(sources), "metadata_only", "1.1.0-compatible"),
        ("repository_asset_candidates", "repository_asset_candidates.jsonl", len(inventory["candidates"]), "metadata_only", "1.0.0"),
        ("rights_evidence", "rights_evidence.jsonl", len(rights), "metadata_only", "2.0.0"),
        ("source_migration", "source_migration.csv", len(inventory["source_audit"]["normalized_rows"]), "metadata_only", "1.0.0"),
        ("source_issues", "source_issues.csv", len(inventory["source_audit"]["issues"]), "metadata_only", "1.0.0"),
        ("review_queue", "review_queue.csv", len(build_review_queue(inventory["candidates"])), "metadata_only", "1.0.0"),
        ("inventory_summary", "inventory_summary.json", 1, "metadata_only", "1.0.0"),
        ("run_manifest", "run_manifest.json", 1, "metadata_only", "1.0.0"),
        ("quality_report", "quality_report.md", 1, "metadata_only", None),
        ("fixture_asset_candidates", "fixture/asset_candidates.jsonl", 1 + len(fixture_derived), "open_fixture", "1.0.0"),
        ("fixture_stimuli", "fixture/stimuli.jsonl", 1, "open_fixture", "2.0.0"),
        ("gate_packet", "gates/GATE-RIGHTS.json", 1, "metadata_only", "1.0.0"),
        ("gate_packet", "gates/GATE-HISTORY.json", 1, "metadata_only", "1.0.0"),
        ("gate_packet", "gates/GATE-TERMS.json", 1, "metadata_only", "1.0.0"),
        ("gate_packet", "gates/GATE-RELEASE.json", 1, "metadata_only", "1.0.0"),
        ("checksums", "checksums.sha256", _record_count(staging / "checksums.sha256"), "metadata_only", None),
    ]
    artifacts = [_artifact(staging, prefix, *specification) for specification in specifications]
    for record in fixture_derived:
        relative = str(PurePosixPath(record["asset_ref"]["path"]).relative_to(prefix))
        artifacts.append(_artifact(staging, prefix, "fixture_representation", relative, 1, "open_fixture", "1.0.0"))
    return artifacts


def _artifact(
    staging: Path,
    prefix: str,
    logical_type: str,
    relative_path: str,
    record_count: int,
    rights_level: str,
    schema_version: str | None,
) -> dict[str, Any]:
    path = staging / relative_path
    return {
        "logical_type": logical_type,
        "path": str(PurePosixPath(prefix) / relative_path),
        "sha256": sha256_file(path),
        "record_count": record_count,
        "rights_or_privacy_level": rights_level,
        "schema_version": schema_version,
    }


def _handoff_manifest(
    root: Path,
    prefix: str,
    config_file: Path,
    config: dict[str, Any],
    inventory: dict[str, Any],
    fixture: dict[str, Any],
    outputs: list[dict[str, Any]],
    producer_provenance: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    input_snapshots = [
        {
            "logical_type": "asset_curation_config",
            "path": config_file.relative_to(root).as_posix(),
            "sha256": sha256_file(config_file),
            "record_count": 1,
            "rights_or_privacy_level": "public_code_or_schema",
            "schema_version": PROTOCOL_VERSION,
        },
        {
            "logical_type": "open_fixture_source",
            "path": fixture["candidate"]["asset_ref"]["path"],
            "sha256": fixture["candidate"]["asset_ref"]["sha256"],
            "record_count": 1,
            "rights_or_privacy_level": "open_fixture",
            "schema_version": None,
        },
    ]
    for snapshot in inventory["source_audit"]["source_table_snapshots"]:
        input_snapshots.append(
            {
                "logical_type": "legacy_source_table",
                "path": snapshot["path"],
                "sha256": snapshot["sha256"],
                "record_count": snapshot["row_count"],
                "rights_or_privacy_level": "metadata_only",
                "schema_version": None,
            }
        )
    return {
        "handoff_schema_version": "2.0.0",
        "task_id": "TASK-01",
        "producer_version": PROTOCOL_VERSION,
        "contract_compatibility": {
            "previous_version": "1.0.0",
            "backward_compatible": False,
            "reason": "2.0.0 requires a validated producer source snapshot; 1.0.0 recorded only a base commit.",
        },
        "producer_provenance": producer_provenance,
        "created_at": created_at,
        "readiness": {"engineering_ready": True, "pilot_ready": False, "research_validated": False},
        "contract_versions": config["schema_versions"],
        "input_snapshots": input_snapshots,
        "outputs": outputs,
        "quality_gates": [
            {"gate_id": "schema_validation", "status": "passed", "evidence": f"{prefix}/checksums.sha256"},
            {"gate_id": "repository_inventory", "status": "passed", "evidence": f"{prefix}/inventory_summary.json"},
            {"gate_id": "fixture_A_B_C", "status": "fixture_only", "evidence": f"{prefix}/fixture/stimuli.jsonl"},
            {"gate_id": "formal_rights", "status": "blocked", "evidence": f"{prefix}/gates/GATE-RIGHTS.json"},
            {"gate_id": "restricted_terms", "status": "blocked", "evidence": f"{prefix}/gates/GATE-TERMS.json"},
            {"gate_id": "formal_human_curation", "status": "blocked", "evidence": f"{prefix}/review_queue.csv"},
            {"gate_id": "public_release", "status": "blocked", "evidence": f"{prefix}/gates/GATE-RELEASE.json"},
        ],
        "known_limitations": [
            "All 375 award images and 13 font files remain blocked_unknown until human rights review.",
            "Automated content classes are suggestions; no repository asset has human curation gold.",
            "The A/B/C stimulus is a generated CC0 fixture and cannot support pilot or research claims.",
            "No Git history rewrite, external upload, login, terms acceptance, or public release was performed.",
        ],
        "blocked_human_gates": [
            {"gate_id": "GATE-RIGHTS", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-RIGHTS.json", "reasons": ["licence pages and redistribution permissions are unverified"]},
            {"gate_id": "GATE-HISTORY", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-HISTORY.json", "reasons": ["large tracked assets require a user-selected history strategy"]},
            {"gate_id": "GATE-TERMS", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-TERMS.json", "reasons": ["official terms, authentication, cost, and data flow have not been reviewed"]},
            {"gate_id": "GATE-RELEASE", "status": "blocked", "packet_path": f"{prefix}/gates/GATE-RELEASE.json", "reasons": ["formal rights and human curation gates are not passed"]},
        ],
        "next_task_entrypoints": [
            {"task_id": "TASK-02", "status": "fixture_only", "path": f"{prefix}/fixture/asset_candidates.jsonl", "notes": "Use A/B/C fixture records and transform config hash only."},
            {"task_id": "TASK-03", "status": "blocked", "path": f"{prefix}/fixture/stimuli.jsonl", "notes": "Formal presentable stimuli are unavailable; fixture is synthetic."},
            {"task_id": "TASK-04", "status": "metadata_only", "path": f"{prefix}/repository_asset_candidates.jsonl", "notes": "Font metadata are available, but rights and expert gates remain blocked."},
            {"task_id": "TASK-05", "status": "metadata_only", "path": f"{prefix}/handoff_manifest.json", "notes": "Catalog and fixture contracts may be integrated with blocked readiness shown explicitly."},
        ],
    }


def _producer_file_specs(root: Path, config_file: Path) -> list[tuple[str, Path]]:
    specs = [
        ("entrypoint", root / "pyproject.toml"),
        ("dependency_lock", root / "runtime.lock.json"),
        ("config", config_file),
        *(("schema", root / path) for path in PRODUCER_SCHEMA_FILES),
        *(("producer_source", path) for path in sorted((root / "src/glyph_features/asset_system").glob("*.py"))),
    ]
    missing = [str(path) for _, path in specs if not path.is_file()]
    if missing:
        raise ValueError("producer snapshot file missing: " + ", ".join(missing))
    return specs


def _producer_file_records(root: Path, config_file: Path) -> list[dict[str, str]]:
    return sorted(
        [
            {
                "role": role,
                "path": path.resolve().relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for role, path in _producer_file_specs(root, config_file)
        ],
        key=lambda item: item["path"],
    )


def _producer_file_records_at_commit(
    root: Path,
    config_file: Path,
    commit: str,
) -> list[dict[str, str]]:
    try:
        config_path = config_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError("producer config must be inside the workspace") from error
    source_root = "src/glyph_features/asset_system"
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", source_root],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("unable to enumerate producer files at snapshot commit")
    source_paths = sorted(
        path
        for path in result.stdout.splitlines()
        if Path(path).parent.as_posix() == source_root and Path(path).suffix == ".py"
    )
    specifications = [
        ("entrypoint", "pyproject.toml"),
        ("dependency_lock", "runtime.lock.json"),
        ("config", config_path),
        *(("schema", path) for path in PRODUCER_SCHEMA_FILES),
        *(("producer_source", path) for path in source_paths),
    ]
    records: list[dict[str, str]] = []
    for role, path in specifications:
        blob = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if blob.returncode != 0:
            raise ValueError(f"producer file unavailable at snapshot commit: {path}")
        records.append(
            {
                "role": role,
                "path": path,
                "sha256": hashlib.sha256(blob.stdout).hexdigest(),
            }
        )
    return sorted(records, key=lambda item: item["path"])


def _historical_producer_file_records(
    root: Path,
    manifest_file: Path,
    config_file: Path,
    base_commit: str | None,
) -> list[dict[str, str]] | None:
    try:
        manifest_path = manifest_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    history = subprocess.run(
        ["git", "log", "--format=%H", "HEAD", "--", manifest_path],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if history.returncode != 0:
        return None
    manifest_sha256 = sha256_file(manifest_file)
    for commit in history.stdout.splitlines():
        if base_commit:
            ancestry = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base_commit, commit],
                cwd=root,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if ancestry.returncode != 0:
                continue
        blob = subprocess.run(
            ["git", "show", f"{commit}:{manifest_path}"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if blob.returncode != 0 or hashlib.sha256(blob.stdout).hexdigest() != manifest_sha256:
            continue
        return _producer_file_records_at_commit(root, config_file, commit)
    return None


def _producer_aggregate(records: list[dict[str, str]]) -> str:
    normalized = sorted(
        ({"role": item["role"], "path": item["path"], "sha256": item["sha256"]} for item in records),
        key=lambda item: item["path"],
    )
    return hashlib.sha256(canonical_json(normalized)).hexdigest()


def _git_blob_matches(root: Path, base_commit: str, records: list[dict[str, str]]) -> bool:
    for record in records:
        result = subprocess.run(
            ["git", "show", f"{base_commit}:{record['path']}"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0 or hashlib.sha256(result.stdout).hexdigest() != record["sha256"]:
            return False
    return True


def _producer_provenance(root: Path, config_file: Path, base_commit: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{40}", base_commit):
        raise ValueError("base commit must be a full lowercase SHA-1")
    commit = subprocess.run(
        ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if commit.returncode != 0:
        raise ValueError(f"base commit is unavailable: {base_commit}")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if status.returncode != 0:
        raise ValueError("unable to determine Git working tree state")
    files = _producer_file_records(root, config_file)
    return {
        "base_commit": base_commit,
        "working_tree_state": "dirty" if status.stdout else "clean",
        "producer_snapshot_matches_base": _git_blob_matches(root, base_commit, files),
        "aggregate_sha256": _producer_aggregate(files),
        "files": files,
    }


def _validate_producer_provenance(
    manifest: dict[str, Any],
    manifest_file: Path,
    input_root: Path,
    errors: list[str],
) -> None:
    provenance = manifest.get("producer_provenance")
    if not isinstance(provenance, dict):
        return
    files = provenance.get("files")
    if not isinstance(files, list):
        return
    config_artifact = next(
        (
            artifact
            for artifact in manifest.get("input_snapshots", [])
            if isinstance(artifact, dict) and artifact.get("logical_type") == "asset_curation_config"
        ),
        None,
    )
    if not config_artifact:
        errors.append("producer snapshot cannot locate asset curation config")
        return
    try:
        config_path = input_root / normalize_repo_path(config_artifact["path"])
        historical = _historical_producer_file_records(
            input_root,
            manifest_file,
            config_path,
            provenance.get("base_commit"),
        )
        expected = historical or _producer_file_records(input_root, config_path)
    except (KeyError, ValueError) as error:
        errors.append(f"producer snapshot expected-file error: {error}")
        return
    expected_paths = {item["path"] for item in expected}
    expected_roles = {item["path"]: item["role"] for item in expected}
    declared_paths = {item.get("path") for item in files if isinstance(item, dict)}
    if declared_paths != expected_paths:
        errors.append(
            "producer snapshot file set mismatch: "
            f"missing={sorted(expected_paths - declared_paths)}, extra={sorted(declared_paths - expected_paths)}"
        )
    declared_records: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict) or not {"role", "path", "sha256"} <= item.keys():
            continue
        if expected_roles.get(item["path"]) != item["role"]:
            errors.append(
                f"producer role mismatch: {item['path']}: {item['role']} != {expected_roles.get(item['path'])}"
            )
        expected_hash = next(
            (record["sha256"] for record in expected if record["path"] == item["path"]),
            None,
        )
        if expected_hash != item["sha256"]:
            errors.append(f"producer hash mismatch: {item['path']}")
        declared_records.append({"role": item["role"], "path": item["path"], "sha256": item["sha256"]})
    if len(declared_records) == len(files) and _producer_aggregate(declared_records) != provenance.get("aggregate_sha256"):
        errors.append("producer aggregate hash mismatch")
    base_commit = provenance.get("base_commit")
    if isinstance(base_commit, str) and re.fullmatch(r"[a-f0-9]{40}", base_commit):
        commit = subprocess.run(
            ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"],
            cwd=input_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if commit.returncode != 0:
            errors.append(f"base commit is unavailable: {base_commit}")
        elif len(declared_records) == len(files):
            matches = _git_blob_matches(input_root, base_commit, declared_records)
            if matches != provenance.get("producer_snapshot_matches_base"):
                errors.append("producer snapshot/base-commit match flag is incorrect")


def _contains_absolute_filesystem_path(path: Path) -> bool:
    payload = path.read_bytes()
    unix = re.compile(
        rb"(?<![:/A-Za-z0-9])/(?:Applications|Users|etc|home|opt|private|tmp|usr|var|Volumes)/[^\s\"']+"
    )
    windows = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+")
    return bool(unix.search(payload) or windows.search(payload))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return len(_read_jsonl(path))
    if path.suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    if path.name == "checksums.sha256":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return 1
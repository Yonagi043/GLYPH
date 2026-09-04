"""Command-line interface for governed GLYPH asset processing."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .catalog import (
        AssetSystemError,
    build_repository_inventory,
    load_json_config,
    migrate_award_sources,
    normalize_repo_path,
    resolve_workspace_asset,
    validate_record,
)
from .curation import apply_curation_decisions, build_review_queue, freeze_ecological_stimulus
from .export import (
    REVIEW_QUEUE_FIELDS,
    SOURCE_ISSUE_FIELDS,
    SOURCE_MIGRATION_FIELDS,
    _write_csv,
    _write_json,
    _write_jsonl,
    build_handoff_bundle,
    validate_handoff,
)
from .transform import transform_candidate
from .rights import select_rights_evidence
from .qc import inspect_image


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/asset_curation_v1.yaml"
EXIT_OK = 0
EXIT_RECORD_FAILURE = 1
EXIT_OPERATION_ERROR = 2
EXIT_NO_OVERWRITE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    audit = subcommands.add_parser("audit-sources", help="normalize five-award source tables without changing them")
    _add_common(audit)
    audit.add_argument("--output-dir", type=Path, required=True)

    inventory = subcommands.add_parser("inventory", help="inventory all repository award images and fonts")
    _add_common(inventory)
    inventory.add_argument("--output-dir", type=Path, required=True)

    qc = subcommands.add_parser("qc", help="write per-candidate automated QC records")
    _add_common(qc)
    qc.add_argument("--output-dir", type=Path, required=True)

    review = subcommands.add_parser("build-review-queue", help="write a human curation CSV template")
    _add_common(review)
    review.add_argument("--output", type=Path, required=True)

    curation = subcommands.add_parser("import-curation", help="import human curation decisions and rerun physical QC")
    _add_common(curation)
    curation.add_argument("--candidates", type=Path, required=True)
    curation.add_argument("--decisions", type=Path, required=True)
    curation.add_argument("--output", type=Path, required=True)

    transform = subcommands.add_parser("transform", help="build one A/B/C representation for candidate JSONL")
    _add_common(transform)
    transform.add_argument("--candidates", type=Path, required=True)
    transform.add_argument("--representation", choices=["A_layout", "B_shape", "C_ink"], required=True)
    transform.add_argument("--output-dir", type=Path, required=True)
    transform.add_argument("--logical-output-root")

    freeze = subcommands.add_parser("freeze-stimuli", help="freeze eligible originals and derived representations")
    _add_common(freeze)
    freeze.add_argument("--originals", type=Path, required=True)
    freeze.add_argument("--derived", type=Path, required=True)
    freeze.add_argument("--rights-evidence", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--created-at", required=True)
    freeze.add_argument("--fixture-only", action="store_true")

    validate = subcommands.add_parser("validate-handoff", help="validate output schemas, counts, and SHA-256 values")
    _add_common(validate, include_config=False)
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--schema-root", type=Path)
    validate.add_argument("--input-root", type=Path)

    export = subcommands.add_parser("export-handoff", help="build the immutable TASK-01 fixture and metadata handoff")
    _add_common(export)
    export.add_argument("--output-dir", type=Path, required=True)
    export.add_argument("--git-commit", required=True)
    export.add_argument("--created-at", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.failure_output and args.failure_output.exists() and not args.dry_run:
        failure = _failure(args.command, "NO_OVERWRITE", f"failure output exists: {args.failure_output}")
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return EXIT_NO_OVERWRITE
    try:
        result, failures = _dispatch(args)
        if failures:
            _emit_failures(failures, args.failure_output, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_RECORD_FAILURE
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return EXIT_OK
    except FileExistsError as error:
        failure = _failure(args.command, "NO_OVERWRITE", str(error))
        _emit_failures([failure], args.failure_output, dry_run=args.dry_run)
        return EXIT_NO_OVERWRITE
    except Exception as error:
        failure = _failure(args.command, getattr(error, "code", "COMMAND_FAILED"), str(error))
        _emit_failures([failure], args.failure_output, dry_run=args.dry_run)
        return EXIT_OPERATION_ERROR


def _add_common(parser: argparse.ArgumentParser, *, include_config: bool = True) -> None:
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    if include_config:
        parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--failure-output", type=Path)


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = args.workspace_root.resolve()
    if args.command == "validate-handoff":
        errors = validate_handoff(
            args.manifest,
            root,
            schema_root=args.schema_root,
            input_root=args.input_root,
        )
        failures = [_failure(args.command, "HANDOFF_INVALID", error) for error in errors]
        return {"command": args.command, "failure_count": len(failures), "valid": not failures}, failures

    config_path = args.config if args.config.is_absolute() else root / args.config
    config = load_json_config(config_path)
    schema_root = config_path.resolve().parent.parent
    if args.command == "audit-sources":
        audit = migrate_award_sources(root, config)
        if not args.dry_run:
            _publish_directory(
                args.output_dir,
                lambda directory: _write_source_audit(directory, audit),
            )
        return {
            "command": args.command,
            "dry_run": args.dry_run,
            "normalized_row_count": len(audit["normalized_rows"]),
            "issue_count": len(audit["issues"]),
        }, []
    if args.command in {"inventory", "qc", "build-review-queue"}:
        audit = migrate_award_sources(root, config)
        inventory = build_repository_inventory(root, config, audit)
        if args.command == "inventory":
            if not args.dry_run:
                _publish_directory(args.output_dir, lambda directory: _write_inventory(directory, inventory))
            return {"command": args.command, "dry_run": args.dry_run, **inventory["summary"]}, []
        if args.command == "qc":
            qc_records = [
                {
                    "asset_id": record["asset_id"],
                    "asset_ref": record["asset_ref"],
                    "automated_qc": record["automated_qc"],
                }
                for record in inventory["candidates"]
            ]
            if not args.dry_run:
                _publish_directory(
                    args.output_dir,
                    lambda directory: (
                        _write_jsonl(directory / "qc_records.jsonl", qc_records),
                        _write_json(directory / "qc_summary.json", inventory["summary"]),
                    ),
                )
            return {"command": args.command, "dry_run": args.dry_run, "record_count": len(qc_records)}, []
        queue = build_review_queue(inventory["candidates"])
        if not args.dry_run:
            _require_absent(args.output)
            _write_csv(args.output, queue, REVIEW_QUEUE_FIELDS)
        return {"command": args.command, "dry_run": args.dry_run, "record_count": len(queue)}, []
    if args.command == "transform":
        return _transform_records(args, root, schema_root, config)
    if args.command == "import-curation":
        return _import_curation_records(args, root, schema_root, config)
    if args.command == "freeze-stimuli":
        return _freeze_records(args, root, schema_root)
    if args.command == "export-handoff":
        summary = build_handoff_bundle(
            root,
            args.output_dir,
            config_path,
            git_commit=args.git_commit,
            created_at=args.created_at,
            dry_run=args.dry_run,
        )
        return {"command": args.command, "dry_run": args.dry_run, **summary}, []
    raise ValueError(f"unsupported command: {args.command}")


def _transform_records(
    args: argparse.Namespace,
    root: Path,
    schema_root: Path,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _read_jsonl(args.candidates)
    failures: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    if not candidates:
        failures.append(_failure(args.command, "EMPTY_INPUT", str(args.candidates)))
    output = args.output_dir.resolve()
    logical_root = args.logical_output_root
    if logical_root is None:
        try:
            logical_root = (output / "derived").relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("--logical-output-root is required when output is outside workspace") from error
    logical_root = normalize_repo_path(logical_root)
    if args.dry_run:
        physical_output = output / "derived"
    else:
        _require_new_directory(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
        physical_output = staging / "derived"
    try:
        for candidate in candidates:
            try:
                schema_errors = validate_record(candidate, schema_root / "schema/asset_candidate.schema.json")
                if schema_errors:
                    raise ValueError("CANDIDATE_SCHEMA_INVALID: " + "; ".join(schema_errors))
                source_path = resolve_workspace_asset(root, candidate["asset_ref"])
                records.extend(
                    transform_candidate(
                        candidate,
                        source_path,
                        physical_output,
                        args.representation,
                        config,
                        logical_output_root=logical_root,
                        dry_run=args.dry_run,
                    )
                )
            except Exception as error:
                failures.append(_failure(args.command, getattr(error, "code", "RECORD_FAILED"), str(error), candidate.get("asset_id")))
        if not args.dry_run and records:
            _write_jsonl(staging / "asset_candidates.jsonl", records)
            _finish_directory(staging, output)
        elif not args.dry_run:
            shutil.rmtree(staging, ignore_errors=True)
    except Exception:
        if not args.dry_run:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "command": args.command,
        "dry_run": args.dry_run,
        "input_count": len(candidates),
        "output_record_count": len(records),
        "failure_count": len(failures),
    }, failures


def _import_curation_records(
    args: argparse.Namespace,
    root: Path,
    schema_root: Path,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _read_jsonl(args.candidates)
    with args.decisions.open("r", encoding="utf-8-sig", newline="") as handle:
        decisions = list(csv.DictReader(handle))
    for candidate in candidates:
        errors = validate_record(candidate, schema_root / "schema/asset_candidate.schema.json")
        if errors:
            raise AssetSystemError("CANDIDATE_SCHEMA_INVALID", "; ".join(errors))
    curated = apply_curation_decisions(candidates, decisions)
    decided_ids = {decision.get("asset_id", "").strip() for decision in decisions}
    for record in curated:
        if record["asset_id"] not in decided_ids:
            continue
        source_path = resolve_workspace_asset(root, record["asset_ref"])
        inspection = inspect_image(
            source_path,
            max_pixels=int(config["qc"]["max_pixels"]),
            target_geometry=record.get("target_geometry"),
            assume_srgb_without_profile=bool(config["qc"]["assume_srgb_without_profile"]),
        )
        previous_qc = record["automated_qc"]
        qc = inspection["automated_qc"]
        qc["hash_duplicate_status"] = previous_qc["hash_duplicate_status"]
        qc["perceptual_duplicate_status"] = previous_qc["perceptual_duplicate_status"]
        duplicate_codes = {"QC_EXACT_DUPLICATE", "QC_NEAR_DUPLICATE"} & set(previous_qc["failure_codes"])
        qc["failure_codes"] = sorted(set(qc["failure_codes"]) | duplicate_codes)
        if duplicate_codes:
            qc["status"] = "failed"
        record["pixel_metadata"] = inspection["pixel_metadata"]
        record["automated_qc"] = qc
        if record["curation_status"] == "passed" and qc["status"] != "passed":
            raise AssetSystemError("CURATION_QC_NOT_PASSED", record["asset_id"])
        errors = validate_record(record, schema_root / "schema/asset_candidate.schema.json")
        if errors:
            raise AssetSystemError("CURATED_CANDIDATE_SCHEMA_INVALID", "; ".join(errors))
    if not args.dry_run:
        _require_absent(args.output)
        _write_jsonl(args.output, curated)
    return {
        "command": args.command,
        "dry_run": args.dry_run,
        "candidate_count": len(curated),
        "decision_count": len(decisions),
    }, []


def _freeze_records(args: argparse.Namespace, root: Path, schema_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    originals = _read_jsonl(args.originals)
    derived = _read_jsonl(args.derived)
    rights_evidence = _read_jsonl(args.rights_evidence)
    by_parent: dict[str, list[dict[str, Any]]] = {}
    stimuli: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    invalid_parents: set[str] = set()
    for record in derived:
        try:
            errors = validate_record(record, schema_root / "schema/asset_candidate.schema.json")
            if errors:
                raise AssetSystemError("CANDIDATE_SCHEMA_INVALID", "; ".join(errors))
            resolve_workspace_asset(root, record["asset_ref"])
            by_parent.setdefault(record.get("parent_asset_id", ""), []).append(record)
        except Exception as error:
            invalid_parents.add(str(record.get("parent_asset_id", "")))
            failures.append(
                _failure(args.command, getattr(error, "code", "RECORD_FAILED"), str(error), record.get("asset_id"))
            )
    if not originals:
        failures.append(_failure(args.command, "EMPTY_INPUT", str(args.originals)))
    for original in originals:
        try:
            original_errors = validate_record(original, schema_root / "schema/asset_candidate.schema.json")
            if original_errors:
                raise AssetSystemError("CANDIDATE_SCHEMA_INVALID", "; ".join(original_errors))
            if original["asset_id"] in invalid_parents:
                continue
            resolve_workspace_asset(root, original["asset_ref"])
            child_records = by_parent.get(original["asset_id"], [])
            matching_evidence = [
                evidence for evidence in rights_evidence if evidence.get("source_id") == original.get("source_id")
            ]
            for evidence in matching_evidence:
                evidence_errors = validate_record(evidence, schema_root / "schema/rights_evidence.schema.json")
                if evidence_errors:
                    raise AssetSystemError("RIGHTS_EVIDENCE_SCHEMA_INVALID", "; ".join(evidence_errors))
            intended_use = "engineering_fixture" if args.fixture_only else "research_stimulus_local"
            evidence = select_rights_evidence(original, rights_evidence, intended_use=intended_use)
            stimulus = freeze_ecological_stimulus(
                original,
                child_records,
                created_at=args.created_at,
                fixture_only=args.fixture_only,
                rights_evidence=evidence,
            )
            schema_errors = validate_record(stimulus, schema_root / "schema/ecological_stimulus.schema.json")
            if schema_errors:
                raise ValueError("; ".join(schema_errors))
            stimuli.append(stimulus)
        except Exception as error:
            failures.append(_failure(args.command, getattr(error, "code", "RECORD_FAILED"), str(error), original.get("asset_id")))
    if not args.dry_run and stimuli:
        _require_absent(args.output)
        _write_jsonl(args.output, stimuli)
    return {
        "command": args.command,
        "dry_run": args.dry_run,
        "input_count": len(originals),
        "stimulus_count": len(stimuli),
        "failure_count": len(failures),
    }, failures


def _write_source_audit(directory: Path, audit: dict[str, Any]) -> None:
    _write_csv(directory / "source_migration.csv", audit["normalized_rows"], SOURCE_MIGRATION_FIELDS)
    _write_csv(directory / "source_issues.csv", audit["issues"], SOURCE_ISSUE_FIELDS)
    _write_json(directory / "source_table_snapshots.json", audit["source_table_snapshots"])


def _write_inventory(directory: Path, inventory: dict[str, Any]) -> None:
    _write_jsonl(directory / "asset_candidates.jsonl", inventory["candidates"])
    _write_jsonl(directory / "sources.jsonl", inventory["sources"])
    _write_json(directory / "inventory_summary.json", inventory["summary"])


def _publish_directory(output: Path, writer: Callable[[Path], Any]) -> None:
    destination = output.resolve()
    _require_new_directory(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        writer(staging)
        _finish_directory(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _finish_directory(staging: Path, destination: Path) -> None:
    if destination.exists():
        destination.rmdir()
    staging.rename(destination)


def _require_new_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise FileExistsError(f"output directory is not empty: {path}")


def _require_absent(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"output exists: {path}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _failure(command: str, code: str, message: str, record_id: str | None = None) -> dict[str, Any]:
    return {"command": command, "code": code, "record_id": record_id, "message": message}


def _emit_failures(records: list[dict[str, Any]], path: Path | None, *, dry_run: bool) -> None:
    if path is not None and not dry_run:
        _require_absent(path)
        _write_jsonl(path, records)
    for record in records:
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
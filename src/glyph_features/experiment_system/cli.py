"""Command-line interface for the synthetic-first cross-cultural experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import uvicorn

from .assignment import audit_assignments, build_assignments
from .export import ExportBlocked, write_deidentified_export
from .fixtures import build_synthetic_catalog
from .handoff import DEFAULT_HANDOFF_ROOT, build_handoff, validate_handoff
from .power import power_scenarios
from .quality import build_quality_decision
from .schema import ROOT, require_frozen_study_id, validate_record
from .storage import ExperimentStore
from .web import create_app


EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_OPERATION = 2
EXIT_NO_OVERWRITE = 3
DEFAULT_DATABASE = ROOT / "data/raw/participants/task03-experiment.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate-study", help="validate the frozen protocol, questionnaire and TASK-01 fixture")
    validate.add_argument("--protocol", type=Path, default=ROOT / "configs/cross_cultural_study_v1.json")
    validate.add_argument("--questionnaire", type=Path, default=ROOT / "configs/questionnaire_v1.json")

    blocks = subcommands.add_parser("build-blocks", help="build deterministic synthetic balanced incomplete blocks")
    blocks.add_argument("--study-id", required=True)
    blocks.add_argument("--participants", type=int, default=1000)
    blocks.add_argument("--seed", default="task03-cross-cultural-v1")
    blocks.add_argument("--output-dir", type=Path, required=True)

    audit = subcommands.add_parser("audit-assignments", help="audit an assignment JSONL against its catalog")
    audit.add_argument("--study-id", required=True)
    audit.add_argument("--assignments", type=Path, required=True)
    audit.add_argument("--catalog", type=Path, required=True)

    dry_run = subcommands.add_parser("synthetic-dry-run", help="run the 1000-participant fixture allocation and response-count audit")
    dry_run.add_argument("--participants", type=int, default=1000)
    dry_run.add_argument("--seed", default="task03-cross-cultural-v1")
    dry_run.add_argument("--output", type=Path)

    reference = subcommands.add_parser("build-reference", help="build a schema-valid synthetic reference record bundle")
    reference.add_argument("--output-dir", type=Path, required=True)
    reference.add_argument("--seed", default="task03-reference-records")

    power = subcommands.add_parser("power", help="emit hypothetical planning scenarios")
    power.add_argument("--output", type=Path)

    serve = subcommands.add_parser("serve", help="serve the local synthetic questionnaire")
    serve.add_argument("--study-id", required=True)
    serve.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    serve.add_argument("--port", type=int, default=8023)
    serve.add_argument("--synthetic-only", action="store_true")

    export = subcommands.add_parser("export", help="export schema-validated deidentified item ratings")
    export.add_argument("--study-id", required=True)
    export.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--purpose", choices=["engineering_fixture", "formal_analysis", "release"], required=True)
    export.add_argument("--deidentified", action="store_true")

    handoff = subcommands.add_parser("validate-handoff", help="strictly validate a TASK-03 handoff manifest")
    handoff.add_argument("manifest", type=Path)
    handoff.add_argument("--workspace-root", type=Path, default=ROOT)

    build_handoff_parser = subcommands.add_parser("build-handoff", help="atomically build and strictly validate the TASK-03 handoff bundle")
    build_handoff_parser.add_argument("--implementation-commit", required=True)
    build_handoff_parser.add_argument("--created-at", required=True)
    build_handoff_parser.add_argument("--evidence-dir", type=Path, required=True)
    build_handoff_parser.add_argument("--validation-summary", type=Path, required=True)
    build_handoff_parser.add_argument("--output-dir", type=Path, default=DEFAULT_HANDOFF_ROOT)
    build_handoff_parser.add_argument("--workspace-root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-study":
            result = _validate_study(args.protocol, args.questionnaire)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK if result["valid"] else EXIT_VALIDATION
        if args.command == "build-blocks":
            result = _build_blocks(args.study_id, args.participants, args.seed, args.output_dir)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK if result["valid"] else EXIT_VALIDATION
        if args.command == "audit-assignments":
            protocol = _load_frozen_protocol(args.study_id)
            assignments = _read_jsonl(args.assignments)
            catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
            result = audit_assignments(
                assignments,
                catalog["items"],
                block_size=protocol["design"]["block_size"],
                balance_tolerance=protocol["randomization"]["balance_tolerance"],
                required_anchor_count=protocol["design"]["anchor_count"],
                study_id=args.study_id,
                catalog_study_id=catalog.get("study_id"),
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK if result["valid"] else EXIT_VALIDATION
        if args.command == "synthetic-dry-run":
            result = _synthetic_dry_run(args.participants, args.seed)
            if args.output:
                _write_json_no_overwrite(args.output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK if result["valid"] else EXIT_VALIDATION
        if args.command == "build-reference":
            result = _build_reference(args.output_dir, args.seed)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK
        if args.command == "power":
            protocol = _load_json(ROOT / "configs/cross_cultural_study_v1.json")
            result = power_scenarios(protocol)
            if args.output:
                _write_json_no_overwrite(args.output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK
        if args.command == "serve":
            if not args.synthetic_only:
                print(json.dumps({"code": "REAL_COLLECTION_LOCKED", "synthetic_only_required": True}), file=sys.stderr)
                return EXIT_OPERATION
            _load_frozen_protocol(args.study_id)
            uvicorn.run(
                create_app(args.database.resolve(), study_id=args.study_id),
                host="127.0.0.1",
                port=args.port,
                log_level="info",
            )
            return EXIT_OK
        if args.command == "export":
            if not args.deidentified:
                print(json.dumps({"code": "RAW_EXPORT_NOT_SUPPORTED", "deidentified_required": True}), file=sys.stderr)
                return EXIT_OPERATION
            _load_frozen_protocol(args.study_id)
            store = ExperimentStore(args.database.resolve(), study_id=args.study_id)
            result = write_deidentified_export(
                store.deidentified_ratings(study_id=args.study_id),
                args.output,
                purpose=args.purpose,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK
        if args.command == "validate-handoff":
            errors = validate_handoff(args.manifest, args.workspace_root)
            result = {"valid": not errors, "failure_count": len(errors), "errors": errors}
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK if not errors else EXIT_VALIDATION
        if args.command == "build-handoff":
            result = build_handoff(
                args.workspace_root,
                args.output_dir,
                implementation_commit=args.implementation_commit,
                created_at=args.created_at,
                evidence_dir=args.evidence_dir,
                validation_summary_path=args.validation_summary,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return EXIT_OK
    except FileExistsError as error:
        print(json.dumps({"code": "NO_OVERWRITE", "detail": str(error)}), file=sys.stderr)
        return EXIT_NO_OVERWRITE
    except (ExportBlocked, ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"code": getattr(error, "code", "COMMAND_FAILED"), "detail": str(error)}), file=sys.stderr)
        return EXIT_OPERATION
    return EXIT_OPERATION


def _validate_study(protocol_path: Path, questionnaire_path: Path) -> dict[str, Any]:
    protocol = _load_json(protocol_path)
    questionnaire = _load_json(questionnaire_path)
    errors = [
        *(f"protocol: {error}" for error in validate_record(protocol, "study_protocol.schema.json")),
        *(f"questionnaire: {error}" for error in validate_record(questionnaire, "questionnaire_definition.schema.json")),
    ]
    if questionnaire.get("study_id") != protocol.get("study_id"):
        errors.append("STUDY_ID_MISMATCH")
    catalog = build_synthetic_catalog(study_id=protocol["study_id"])
    return {
        "valid": not errors,
        "errors": errors,
        "study_id": protocol["study_id"],
        "questionnaire_version": questionnaire["questionnaire_version"],
        "language_count": len(questionnaire["supported_languages"]),
        "item_count": len(questionnaire["items"]),
        "stimulus_count": len(catalog["items"]),
        "synthetic_only": protocol["synthetic_only"],
    }


def _build_blocks(study_id: str, participant_count: int, seed: str, output_dir: Path) -> dict[str, Any]:
    if participant_count < 1:
        raise ValueError("PARTICIPANT_COUNT_INVALID")
    if output_dir.exists():
        raise FileExistsError(f"output directory exists: {output_dir}")
    protocol = _load_frozen_protocol(study_id)
    questionnaire = _load_json(ROOT / "configs/questionnaire_v1.json")
    catalog = build_synthetic_catalog(study_id=study_id)
    assignments = build_assignments(
        _synthetic_participants(participant_count),
        catalog["items"],
        study_id=study_id,
        questionnaire_version=questionnaire["questionnaire_version"],
        seed=seed,
        block_size=protocol["design"]["block_size"],
        required_anchor_count=protocol["design"]["anchor_count"],
        created_at=protocol["created_at"],
    )
    audit = audit_assignments(
        assignments,
        catalog["items"],
        block_size=protocol["design"]["block_size"],
        balance_tolerance=protocol["randomization"]["balance_tolerance"],
        required_anchor_count=protocol["design"]["anchor_count"],
        study_id=study_id,
        catalog_study_id=catalog["study_id"],
    )
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "stimulus_catalog.json", catalog)
    _write_jsonl(output_dir / "assignments.jsonl", assignments)
    _write_json(output_dir / "assignment_audit.json", audit)
    return audit


def _synthetic_dry_run(participant_count: int, seed: str) -> dict[str, Any]:
    protocol = _load_json(ROOT / "configs/cross_cultural_study_v1.json")
    questionnaire = _load_json(ROOT / "configs/questionnaire_v1.json")
    catalog = build_synthetic_catalog(study_id=protocol["study_id"])
    assignments = build_assignments(
        _synthetic_participants(participant_count),
        catalog["items"],
        study_id=protocol["study_id"],
        questionnaire_version=questionnaire["questionnaire_version"],
        seed=seed,
        block_size=protocol["design"]["block_size"],
        required_anchor_count=protocol["design"]["anchor_count"],
        created_at=protocol["created_at"],
    )
    audit = audit_assignments(
        assignments,
        catalog["items"],
        block_size=protocol["design"]["block_size"],
        balance_tolerance=protocol["randomization"]["balance_tolerance"],
        required_anchor_count=protocol["design"]["anchor_count"],
    )
    response_ids = {
        f"response_{trial['presentation_id']}"
        for assignment in assignments
        for trial in assignment["trials"]
    }
    expected = participant_count * protocol["design"]["block_size"]
    return {
        **audit,
        "synthetic_participant_count": participant_count,
        "simulated_response_count": len(response_ids),
        "lost_trial_count": expected - len(response_ids),
        "duplicate_response_count": audit["trial_count"] - len(response_ids),
        "formal_analysis_allowed": False,
        "release_allowed": False,
        "valid": audit["valid"] and len(response_ids) == expected,
    }


def _build_reference(output_dir: Path, seed: str) -> dict[str, Any]:
    if output_dir.exists():
        raise FileExistsError(f"output directory exists: {output_dir}")
    staging = output_dir.with_name(f".{output_dir.name}.staging")
    if staging.exists():
        raise FileExistsError(f"staging directory exists: {staging}")
    protocol = _load_json(ROOT / "configs/cross_cultural_study_v1.json")
    questionnaire = _load_json(ROOT / "configs/questionnaire_v1.json")
    catalog = build_synthetic_catalog(study_id=protocol["study_id"])
    participant = {
        "schema_version": "1.0.0",
        "study_id": protocol["study_id"],
        "participant_id": "synp_reference_001",
        "data_origin": "synthetic",
        "questionnaire_language": "en",
        "mother_tongues": [{"bcp47": "en", "dominance": "primary"}],
        "native_scripts": ["latin"],
        "script_proficiencies": [
            {"script": script, "reading": 4, "writing": 4, "exposure_frequency": 4}
            for script in ("latin", "han", "kana", "hangul")
        ],
        "region_category": "prefer_not_to_say",
        "cross_cultural_exposure": "moderate",
        "training": {"design": "none", "typography": "none", "calligraphy": "none"},
        "age_band": "25_34",
        "education_level": "prefer_not_to_say",
        "language_understood": True,
        "created_at": protocol["created_at"],
    }
    consent = {
        "schema_version": "1.0.0",
        "study_id": protocol["study_id"],
        "participant_id": participant["participant_id"],
        "data_origin": "synthetic",
        "consent_version": "1.0.0",
        "status": "consented",
        "age_eligible": True,
        "recorded_at": protocol["created_at"],
    }
    assignment = build_assignments(
        [{"participant_id": participant["participant_id"], "participant_group": "latin", "data_origin": "synthetic"}],
        catalog["items"],
        study_id=protocol["study_id"],
        questionnaire_version=questionnaire["questionnaire_version"],
        seed=seed,
        block_size=protocol["design"]["block_size"],
        required_anchor_count=protocol["design"]["anchor_count"],
        created_at=protocol["created_at"],
    )[0]
    trial = assignment["trials"][0]
    event = {
        "schema_version": "1.0.0",
        "event_id": "event_reference_001",
        "request_id": "request_reference_001",
        "study_id": protocol["study_id"],
        "assignment_id": assignment["assignment_id"],
        "presentation_id": trial["presentation_id"],
        "participant_id": participant["participant_id"],
        "data_origin": "synthetic",
        "stimulus_id": trial["stimulus_id"],
        "expected_asset_sha256": trial["asset_sha256"],
        "displayed_asset_sha256": trial["asset_sha256"],
        "load_status": "loaded",
        "trial_index": trial["trial_index"],
        "started_at": protocol["created_at"],
        "ended_at": "2026-09-04T00:00:02Z",
        "preload_ms": 12,
        "response_ms": 1800,
        "viewport": {"css_width": 1280, "css_height": 800, "stimulus_css_width": 512, "stimulus_css_height": 512, "device_pixel_ratio": 2},
        "focus_loss_count": 0,
        "zoom_anomaly": False,
        "quality_signals": [],
    }
    rating_definitions = [
        item
        for item in questionnaire["items"]
        if item["response_type"] == "likert_1_7" and item["item_id"] != "item_brand_fit"
    ]
    ratings = [
        {
            "schema_version": "2.0.0",
            "rating_id": f"rating_reference_{index:02d}",
            "study_id": protocol["study_id"],
            "questionnaire_version": questionnaire["questionnaire_version"],
            "assignment_id": assignment["assignment_id"],
            "block_id": assignment["block_id"],
            "presentation_id": trial["presentation_id"],
            "stimulus_id": trial["stimulus_id"],
            "participant_id": participant["participant_id"],
            "data_origin": "synthetic",
            "respondent_language_bcp47": "en",
            "native_scripts": ["latin"],
            "item_id": definition["item_id"],
            "construct": definition["construct"],
            "rating_scale": definition["response_type"],
            "response": {"value": 4, "missing_reason": None},
            "displayed_asset_sha256": trial["asset_sha256"],
            "trial_index": trial["trial_index"],
            "response_time_ms": 1800,
            "attention_check": True,
            "quality": {"rule_version": "1.0.0", "exclude_from_analysis": False, "reason_codes": []},
            "collected_at": "2026-09-04T00:00:02Z",
        }
        for index, definition in enumerate(rating_definitions, start=1)
    ]
    decision = build_quality_decision(participant, consent, [event], ratings)
    records = {
        "study_protocol.json": (protocol, "study_protocol.schema.json"),
        "questionnaire_definition.json": (questionnaire, "questionnaire_definition.schema.json"),
        "participant_profile.json": (participant, "participant_profile.schema.json"),
        "consent_receipt.json": (consent, "consent_receipt.schema.json"),
        "stimulus_catalog.json": (catalog, "experiment_stimulus_catalog.schema.json"),
        "assignment.json": (assignment, "experiment_assignment.schema.json"),
        "presentation_event.json": (event, "presentation_event.schema.json"),
        "quality_decision.json": (decision, "quality_decision.schema.json"),
    }
    try:
        staging.mkdir(parents=True)
        for filename, (record, schema_name) in records.items():
            errors = validate_record(record, schema_name)
            if errors:
                raise ValueError(f"REFERENCE_SCHEMA_INVALID:{filename}: {'; '.join(errors)}")
            _write_json(staging / filename, record)
        for index, rating in enumerate(ratings, start=1):
            errors = validate_record(rating, "experiment_rating.schema.json")
            if errors:
                raise ValueError(f"REFERENCE_SCHEMA_INVALID:ratings.jsonl:{index}: {'; '.join(errors)}")
        _write_jsonl(staging / "ratings.jsonl", ratings)
        artifacts = []
        for filename, (_, schema_name) in records.items():
            artifact = staging / filename
            artifacts.append({"path": filename, "schema": schema_name, "record_count": 1, "sha256": _sha256_file(artifact)})
        artifacts.append({"path": "ratings.jsonl", "schema": "experiment_rating.schema.json", "record_count": len(ratings), "sha256": _sha256_file(staging / "ratings.jsonl")})
        _write_json(staging / "reference_manifest.json", {"schema_version": "1.0.0", "data_origin": "synthetic", "artifacts": artifacts})
        staging.rename(output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"output_dir": str(output_dir), "artifact_count": len(records) + 1, "rating_count": len(ratings), "data_origin": "synthetic"}


def _synthetic_participants(count: int) -> list[dict[str, str]]:
    groups = ("latin", "han", "kana", "hangul")
    return [
        {"participant_id": f"synp_{index:06d}", "participant_group": groups[index % 4], "data_origin": "synthetic"}
        for index in range(count)
    ]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _load_frozen_protocol(study_id: str) -> dict[str, Any]:
    protocol = _load_json(ROOT / "configs/cross_cultural_study_v1.json")
    require_frozen_study_id(study_id, protocol["study_id"])
    return protocol


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
        newline="\n",
    )


def _write_json_no_overwrite(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, value)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
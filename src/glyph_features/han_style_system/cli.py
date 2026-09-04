"""Command-line interface for governed Han style knowledge and review."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import validate_record
from glyph_features.han_style_system.adapters import build_adapter_records, integration_requests
from glyph_features.han_style_system.claims import import_claim_rows, validate_claims
from glyph_features.han_style_system.glyphs import (
    load_content_sets,
    validate_character_mappings,
    validate_glyph_instances,
)
from glyph_features.han_style_system.handoff import build_handoff_bundle, validate_handoff
from glyph_features.han_style_system.io import (
    publish_directory,
    read_csv,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)
from glyph_features.han_style_system.ontology import validate_ontology
from glyph_features.han_style_system.review import (
    ReviewError,
    build_review_package,
    import_review_rows,
    validate_review_records,
    write_reviews,
)
from glyph_features.han_style_system.stimuli import build_stimulus_candidates


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/han_style_protocol_v1.yaml"
EXIT_OK = 0
EXIT_RECORD_FAILURE = 1
EXIT_OPERATION_ERROR = 2
EXIT_NO_OVERWRITE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    ontology = subcommands.add_parser("validate-ontology")
    _common(ontology)
    ontology.add_argument("--ontology", type=Path, required=True)
    ontology.add_argument("--sources", type=Path, action="append", default=[])

    claims = subcommands.add_parser("import-claims")
    _common(claims)
    claims.add_argument("--input", type=Path, required=True)
    claims.add_argument("--ontology", type=Path, required=True)
    claims.add_argument("--glyphs", type=Path, required=True)
    claims.add_argument("--assets", type=Path)
    claims.add_argument("--candidates", type=Path)
    claims.add_argument("--sources", type=Path, action="append", required=True)
    claims.add_argument("--output", type=Path, required=True)

    glyphs = subcommands.add_parser("validate-glyphs")
    _common(glyphs)
    glyphs.add_argument("--ontology", type=Path, required=True)
    glyphs.add_argument("--mappings", type=Path, required=True)
    glyphs.add_argument("--glyphs", type=Path, required=True)
    glyphs.add_argument("--claims", type=Path, required=True)
    glyphs.add_argument("--sources", type=Path, action="append", required=True)
    glyphs.add_argument("--assets", type=Path, required=True)
    glyphs.add_argument("--content-sets", type=Path, required=True)

    package = subcommands.add_parser("build-review-package")
    _common(package)
    package.add_argument("--glyphs", type=Path, required=True)
    package.add_argument("--mappings", type=Path, required=True)
    package.add_argument("--assets", type=Path, required=True)
    package.add_argument("--output-dir", type=Path, required=True)
    package.add_argument("--created-at", required=True)
    package.add_argument("--ordering-seed", required=True)
    package.add_argument("--access-level", choices=["open_fixture", "research_local_only"], default="open_fixture")
    package.add_argument("--access-authorization-id")
    package.add_argument("--task01-handoff", type=Path)
    package.add_argument("--rights-evidence", type=Path)

    reviews = subcommands.add_parser("import-reviews")
    _common(reviews)
    reviews.add_argument("--package-dir", type=Path, required=True)
    reviews.add_argument("--input", type=Path, required=True)
    reviews.add_argument("--output", type=Path, required=True)
    reviews.add_argument("--gate-approval", type=Path)

    candidates = subcommands.add_parser("build-stimulus-candidates")
    _common(candidates)
    candidates.add_argument("--ontology", type=Path, required=True)
    candidates.add_argument("--mappings", type=Path, required=True)
    candidates.add_argument("--glyphs", type=Path, required=True)
    candidates.add_argument("--reviews", type=Path, required=True)
    candidates.add_argument("--rights-evidence", type=Path, required=True)
    candidates.add_argument("--sources", type=Path, action="append", default=[])
    candidates.add_argument("--assets", type=Path)
    candidates.add_argument("--claims", type=Path)
    candidates.add_argument("--content-sets", type=Path)
    candidates.add_argument("--review-package-dir", type=Path)
    candidates.add_argument("--task01-handoff", type=Path)
    candidates.add_argument("--output-dir", type=Path, required=True)
    candidates.add_argument("--created-at", required=True)

    handoff = subcommands.add_parser("export-handoff")
    _common(handoff)
    handoff.add_argument("--output-dir", type=Path, required=True)
    handoff.add_argument("--implementation-commit", required=True)
    handoff.add_argument("--created-at", required=True)

    validate = subcommands.add_parser("validate-handoff")
    _common(validate, include_config=False)
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--schema-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.failure_output is not None and args.failure_output.exists() and not args.dry_run:
        print(
            json.dumps(
                _failure("NO_OVERWRITE", f"failure output exists: {args.failure_output}"),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_NO_OVERWRITE
    try:
        result, failures = _dispatch(args)
        _emit_result(result, failures, args.failure_output, args.dry_run)
        return EXIT_RECORD_FAILURE if failures else EXIT_OK
    except FileExistsError as error:
        print(json.dumps(_failure("NO_OVERWRITE", str(error)), sort_keys=True), file=sys.stderr)
        return EXIT_NO_OVERWRITE
    except (OSError, ValueError, ReviewError, json.JSONDecodeError) as error:
        code = getattr(error, "code", "COMMAND_FAILED")
        print(json.dumps(_failure(code, str(error)), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return EXIT_OPERATION_ERROR


def _common(parser: argparse.ArgumentParser, *, include_config: bool = True) -> None:
    parser.add_argument("--workspace-root", type=Path, default=ROOT)
    if include_config:
        parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--failure-output", type=Path)


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = args.workspace_root.resolve()
    if args.command == "validate-handoff":
        errors = validate_handoff(args.manifest, root, schema_root=args.schema_root)
        return {"command": args.command, "valid": not errors}, _error_failures(errors)
    config = read_json(_resolve(root, args.config))
    schema_root = root / "schema"
    if args.command == "validate-ontology":
        ontology = read_jsonl(args.ontology)
        sources = _records_from_paths(args.sources)
        source_ids = {record["source_id"] for record in sources} if sources else None
        errors = validate_ontology(ontology, schema_root / "han_style_concept.schema.json", source_ids)
        return {"command": args.command, "record_count": len(ontology), "valid": not errors}, _error_failures(errors)
    if args.command == "import-claims":
        ontology = read_jsonl(args.ontology)
        glyphs = read_jsonl(args.glyphs)
        sources = _records_from_paths(args.sources)
        assets = read_jsonl(args.assets) if args.assets else []
        candidates = read_jsonl(args.candidates) if args.candidates else []
        records, failures = import_claim_rows(
            read_csv(args.input),
            schema_root / "han_knowledge_claim.schema.json",
            style_ids={record["style_id"] for record in ontology},
            glyph_ids={record["glyph_instance_id"] for record in glyphs},
            source_ids={record["source_id"] for record in sources},
            work_ids={record["work_id"] for record in glyphs}
            | {record["work_id"] for record in assets if record.get("work_id")},
            font_ids={record["font_id"] for record in glyphs if record.get("font_id")}
            | {
                record["font_metadata"]["font_id"]
                for record in assets
                if isinstance(record.get("font_metadata"), dict)
                and record["font_metadata"].get("font_id")
            },
            stimulus_candidate_ids={record["candidate_id"] for record in candidates},
        )
        if not args.dry_run and records:
            write_jsonl(args.output, records)
        return {"command": args.command, "input_count": len(read_csv(args.input)), "output_count": len(records)}, failures
    if args.command == "validate-glyphs":
        ontology = read_jsonl(args.ontology)
        mappings = read_jsonl(args.mappings)
        glyphs = read_jsonl(args.glyphs)
        claims = read_jsonl(args.claims)
        sources = _records_from_paths(args.sources)
        assets = read_jsonl(args.assets)
        source_ids = {record["source_id"] for record in sources}
        style_ids = {record["style_id"] for record in ontology}
        mapping_ids = {record["mapping_id"] for record in mappings}
        glyph_ids = {record["glyph_instance_id"] for record in glyphs}
        claim_ids = {record["claim_id"] for record in claims}
        errors = validate_ontology(ontology, schema_root / "han_style_concept.schema.json", source_ids)
        errors += validate_character_mappings(
            mappings,
            schema_root / "han_character_mapping.schema.json",
            load_content_sets(args.content_sets),
            source_ids,
        )
        errors += validate_claims(
            claims,
            schema_root / "han_knowledge_claim.schema.json",
            style_ids=style_ids,
            glyph_ids=glyph_ids,
            source_ids=source_ids,
            work_ids={record["work_id"] for record in glyphs},
            font_ids={record["font_id"] for record in glyphs if record.get("font_id")},
        )
        errors += validate_glyph_instances(
            glyphs,
            schema_root / "han_glyph_instance.schema.json",
            workspace_root=root,
            style_ids=style_ids,
            mapping_ids=mapping_ids,
            source_ids=source_ids,
            asset_records=assets,
            claim_ids=claim_ids,
        )
        return {"command": args.command, "record_count": len(glyphs), "valid": not errors}, _error_failures(errors)
    if args.command == "build-review-package":
        output_dir = args.output_dir
        if args.dry_run:
            with tempfile.TemporaryDirectory(prefix="glyph-han-review-") as temporary:
                manifest = build_review_package(
                    read_jsonl(args.glyphs),
                    read_jsonl(args.mappings),
                    read_jsonl(args.assets),
                    workspace_root=root,
                    output_dir=Path(temporary) / "package",
                    created_at=args.created_at,
                    ordering_seed=args.ordering_seed,
                    access_level=args.access_level,
                    access_authorization_id=args.access_authorization_id,
                    task01_handoff_path=args.task01_handoff,
                    rights_evidence_path=args.rights_evidence,
                )
        else:
            manifest = build_review_package(
                read_jsonl(args.glyphs),
                read_jsonl(args.mappings),
                read_jsonl(args.assets),
                workspace_root=root,
                output_dir=output_dir,
                created_at=args.created_at,
                ordering_seed=args.ordering_seed,
                access_level=args.access_level,
                access_authorization_id=args.access_authorization_id,
                task01_handoff_path=args.task01_handoff,
                rights_evidence_path=args.rights_evidence,
            )
        return {"command": args.command, "package_id": manifest["package_id"], "item_count": manifest["item_count"], "dry_run": args.dry_run}, []
    if args.command == "import-reviews":
        reviews = import_review_rows(
            args.package_dir,
            read_csv(args.input),
            schema_path=schema_root / "expert_review.schema.json",
            gate_approval=read_json(args.gate_approval) if args.gate_approval else None,
        )
        if not args.dry_run:
            write_reviews(args.output, reviews)
        return {"command": args.command, "review_count": len(reviews), "dry_run": args.dry_run}, []
    if args.command == "build-stimulus-candidates":
        fixture_root = _resolve(root, config["reference_fixture_root"])
        run_root = _resolve(root, config["reference_run_root"])
        ontology = read_jsonl(args.ontology)
        mappings = read_jsonl(args.mappings)
        glyphs = read_jsonl(args.glyphs)
        reviews = read_jsonl(args.reviews)
        source_paths = args.sources or [
            fixture_root / "sources.jsonl",
            _resolve(root, config["task01"]["sources_path"]),
        ]
        sources = _records_from_paths(source_paths)
        assets_path = args.assets or _resolve(root, config["task01"]["asset_candidates_path"])
        claims_path = args.claims or fixture_root / "claims.jsonl"
        content_sets_path = args.content_sets or _resolve(root, config["content_sets_path"])
        review_package_dir = args.review_package_dir or run_root / "review_package"
        task01_handoff_path = args.task01_handoff or _resolve(root, config["task01"]["handoff_path"])
        assets = read_jsonl(assets_path)
        claims = read_jsonl(claims_path)
        source_ids = {record["source_id"] for record in sources}
        style_ids = {record["style_id"] for record in ontology}
        mapping_ids = {record["mapping_id"] for record in mappings}
        glyph_ids = {record["glyph_instance_id"] for record in glyphs}
        input_errors = validate_ontology(
            ontology,
            schema_root / "han_style_concept.schema.json",
            source_ids,
        )
        input_errors += validate_character_mappings(
            mappings,
            schema_root / "han_character_mapping.schema.json",
            load_content_sets(content_sets_path),
            source_ids,
        )
        input_errors += validate_claims(
            claims,
            schema_root / "han_knowledge_claim.schema.json",
            style_ids=style_ids,
            glyph_ids=glyph_ids,
            source_ids=source_ids,
            work_ids={record["work_id"] for record in glyphs},
            font_ids={record["font_id"] for record in glyphs if record.get("font_id")},
        )
        input_errors += validate_glyph_instances(
            glyphs,
            schema_root / "han_glyph_instance.schema.json",
            workspace_root=root,
            style_ids=style_ids,
            mapping_ids=mapping_ids,
            source_ids=source_ids,
            asset_records=assets,
            claim_ids={record["claim_id"] for record in claims},
        )
        input_errors += [
            f"HAN_ASSET_SCHEMA_INVALID record={index}: {error}"
            for index, asset in enumerate(assets, start=1)
            for error in validate_record(asset, schema_root / "asset_candidate.schema.json")
        ]
        input_errors += validate_review_records(
            reviews,
            schema_root / "expert_review.schema.json",
            package_dir=review_package_dir,
            review_records_path=args.reviews,
        )
        if input_errors:
            return {"command": args.command, "candidate_count": 0}, _error_failures(input_errors)
        rights = read_jsonl(args.rights_evidence)
        candidates = build_stimulus_candidates(
            glyphs,
            mappings,
            reviews,
            rights,
            schema_path=schema_root / "han_stimulus_candidate.schema.json",
            render_profiles=config["stimuli"]["render_profiles"],
            minimum_independent_reviews=int(config["review"]["minimum_independent_reviews"]),
            minimum_independent_exemplars=int(config["stimuli"]["minimum_independent_exemplars_for_category"]),
            created_at=args.created_at,
            review_package_dir=review_package_dir,
            review_records_path=args.reviews,
            task01_handoff_path=task01_handoff_path,
            rights_evidence_path=args.rights_evidence,
            workspace_root=root,
            ontology_records=ontology,
            source_records=sources,
            asset_records=assets,
            claim_records=claims,
            content_sets_path=content_sets_path,
            minimum_substantive_dimensions=int(config["review"]["minimum_substantive_dimensions_per_review"]),
            required_dimensions=tuple(config["review"]["required_dimension_coverage"]),
            required_role_groups=tuple(
                frozenset(group) for group in config["review"]["required_role_groups"]
            ),
        )
        adapters = build_adapter_records(
            ontology,
            candidates,
            schema_path=schema_root / "han_adapter_record.schema.json",
        )
        if not args.dry_run:
            publish_directory(
                args.output_dir,
                lambda directory: (
                    write_jsonl(directory / "stimulus_candidates.jsonl", candidates),
                    write_jsonl(directory / "adapters.jsonl", adapters),
                    write_json(directory / "integration_requests.json", integration_requests(adapters)),
                ),
            )
        return {"command": args.command, "candidate_count": len(candidates), "adapter_count": len(adapters), "dry_run": args.dry_run}, []
    if args.command == "export-handoff":
        summary = build_handoff_bundle(
            root,
            args.output_dir,
            _resolve(root, args.config),
            implementation_commit=args.implementation_commit,
            created_at=args.created_at,
            dry_run=args.dry_run,
        )
        return {"command": args.command, "dry_run": args.dry_run, **summary}, []
    raise ValueError(f"unsupported command: {args.command}")


def _resolve(root: Path, path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def _records_from_paths(paths: list[Path]) -> list[dict[str, Any]]:
    return [record for path in paths for record in read_jsonl(path)]


def _error_failures(errors: list[str]) -> list[dict[str, Any]]:
    return [_failure("VALIDATION_FAILED", error) for error in sorted(set(errors))]


def _failure(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def _emit_result(
    result: dict[str, Any],
    failures: list[dict[str, Any]],
    failure_output: Path | None,
    dry_run: bool,
) -> None:
    if failure_output is not None and failures and not dry_run:
        write_jsonl(failure_output, failures)
    for failure in failures:
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    print(json.dumps({**result, "failure_count": len(failures)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())

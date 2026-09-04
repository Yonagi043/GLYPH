"""Command-line interface for GLYPH TASK-02 visual measurements."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from .definitions import load_registry
from .extract import VisionSystemError, extract_handoff
from .handoff import build_handoff_bundle, validate_handoff
from .qc import qc_run, representation_comparison, verify_checksums


EXIT_OK = 0
EXIT_RECORD_FAILURE = 1
EXIT_OPERATION_ERROR = 2
EXIT_NO_OVERWRITE = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glyph-vision", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    definitions = commands.add_parser("validate-definitions")
    _common(definitions)
    definitions.add_argument("--registry", type=Path, required=True)

    extract = commands.add_parser("extract")
    _common(extract)
    extract.add_argument("--registry", type=Path, required=True)
    extract.add_argument("--asset-handoff", type=Path, required=True)
    extract.add_argument("--output-dir", type=Path, required=True)
    extract.add_argument("--run-id", required=True)
    extract.add_argument("--computed-at", required=True)
    extract.add_argument("--allow-fixture", action="store_true")

    qc = commands.add_parser("qc")
    _common(qc)
    qc.add_argument("--run-dir", type=Path, required=True)

    compare = commands.add_parser("compare-representations")
    _common(compare)
    compare.add_argument("--run-dir", type=Path, required=True)

    export = commands.add_parser("export")
    _common(export)
    export.add_argument("--run-dir", type=Path, required=True)
    export.add_argument("--format", choices=["long", "v1-wide"], required=True)
    export.add_argument("--output", type=Path, required=True)

    handoff = commands.add_parser("export-handoff")
    _common(handoff)
    handoff.add_argument("--run-dir", type=Path, required=True)
    handoff.add_argument("--output-dir", type=Path, required=True)
    handoff.add_argument("--git-commit", required=True)
    handoff.add_argument("--created-at", required=True)

    validate_handoff_parser = commands.add_parser("validate-handoff")
    _common(validate_handoff_parser)
    validate_handoff_parser.add_argument("manifest", type=Path)
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--schema-root", type=Path, default=Path("schema"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.workspace_root.resolve()
    schema_root = _path(root, args.schema_root)
    try:
        if args.command == "validate-definitions":
            registry = load_registry(_path(root, args.registry), schema_root)
            return _emit({"valid": True, "registry_version": registry.version, "feature_count": len(registry.active_feature_codes)})
        if args.command == "extract":
            summary = extract_handoff(
                workspace_root=root,
                handoff_path=_path(root, args.asset_handoff),
                registry_path=_path(root, args.registry),
                schema_root=schema_root,
                output_dir=_path(root, args.output_dir),
                extraction_run_id=args.run_id,
                computed_at=args.computed_at,
                allow_fixture=args.allow_fixture,
            )
            _print(summary)
            return EXIT_RECORD_FAILURE if summary["failure_count"] else EXIT_OK
        if args.command == "qc":
            report = qc_run(_path(root, args.run_dir), root, schema_root)
            _print({"extraction_run_id": report["extraction_run_id"], "readiness": report["readiness"], "qc_error_count": report["qc_error_count"]})
            return EXIT_OK if report["readiness"]["engineering_ready"] else EXIT_RECORD_FAILURE
        if args.command == "compare-representations":
            run = _path(root, args.run_dir)
            comparison_file = run / "representation_comparison.json"
            if comparison_file.exists():
                comparison = json.loads(comparison_file.read_text(encoding="utf-8"))
            else:
                records = _read_jsonl(run / "measurements.jsonl")
                comparison = representation_comparison(records)
            return _emit(comparison)
        if args.command == "export":
            run = _path(root, args.run_dir)
            checksum_errors = verify_checksums(run)
            if checksum_errors:
                raise VisionSystemError("RUN_CHECKSUM_INVALID", "; ".join(checksum_errors))
            if args.format == "v1-wide":
                raise VisionSystemError("EXPORT_INCOMPATIBLE_V1", "A/B/C v2 measurements cannot be projected into the frozen v1.1 wide contract")
            output = _path(root, args.output)
            if output.exists():
                raise FileExistsError(f"export output exists: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(run / "measurements.jsonl", output)
            return _emit({"format": "long", "output": output.name, "sha256_verified": True})
        if args.command == "export-handoff":
            summary = build_handoff_bundle(
                workspace_root=root,
                reference_run_dir=_path(root, args.run_dir),
                output_dir=_path(root, args.output_dir),
                git_commit=args.git_commit,
                created_at=args.created_at,
            )
            return _emit(summary)
        if args.command == "validate-handoff":
            errors = validate_handoff(_path(root, args.manifest), root, schema_root=schema_root)
            _print({"failure_count": len(errors), "valid": not errors})
            if errors:
                for error in errors:
                    _print_error("HANDOFF_INVALID", error)
                return EXIT_RECORD_FAILURE
            return EXIT_OK
    except FileExistsError as error:
        _print_error("NO_OVERWRITE", str(error))
        return EXIT_NO_OVERWRITE
    except (VisionSystemError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        _print_error(getattr(error, "code", "OPERATION_FAILED"), str(error))
        return EXIT_OPERATION_ERROR
    return EXIT_OPERATION_ERROR


def _path(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _emit(value: dict) -> int:
    _print(value)
    return EXIT_OK


def _print(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _print_error(code: str, message: str) -> None:
    print(json.dumps({"code": code, "message": message}, ensure_ascii=False, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
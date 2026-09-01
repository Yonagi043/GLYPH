#!/usr/bin/env python3
"""Validate a normalized GLYPH social-observation JSONL file.

The normalizer checks each row while it is being created.  This command is the
release gate: it checks the complete file, duplicate platform items, the
record hash, optional query/object/source registries, and (when supplied) the
collection-run manifest.  It is deliberately offline and never changes the
input.  A non-zero exit code means that the file is not ready for analysis or
publication.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from social_io import canonical_json, schema_validator, sha256_file, validator as observation_validator
except ImportError:  # pragma: no cover - supports package-style imports
    from tools.social_io import canonical_json, schema_validator, sha256_file, validator as observation_validator


ROOT = Path(__file__).resolve().parents[1]
ZERO_HASH = "0" * 64
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
QUERY_RE = re.compile(r"^q_[a-z0-9][a-z0-9_-]{2,127}$")
RUN_RE = re.compile(r"^social_run_[a-z0-9][a-z0-9_-]{2,127}$")


def _portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def _add(messages: list[dict[str, Any]], severity: str, code: str, message: str, line: int | None = None) -> None:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if line is not None:
        item["line"] = line
    messages.append(item)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path, messages: list[dict[str, Any]], label: str) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                _add(messages, "error", f"{label}_empty", f"{label} has no header: {_portable_path(path)}")
                return []
            return [dict(row) for row in reader]
    except OSError as error:
        _add(messages, "error", f"{label}_read_error", f"could not read {label}: {error}")
        return []


def _registry(rows: list[dict[str, str]], key: str, messages: list[dict[str, Any]], label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        value = (row.get(key) or "").strip()
        if not value:
            _add(messages, "error", f"{label}_missing_key", f"row {index} has no {key}")
            continue
        if value in result:
            _add(messages, "error", f"{label}_duplicate_key", f"duplicate {key} {value!r} in {label}")
            continue
        result[value] = row
    return result


def _split_pipe(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.replace(",", "|").replace(";", "|").split("|") if part.strip()}


def _hash_payload(record: dict[str, Any]) -> dict[str, Any]:
    # This is intentionally the same projection used by the normalizer.
    copy = json.loads(canonical_json(record))
    copy.pop("normalization", None)
    return copy


def _expected_record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_hash_payload(record)).encode("utf-8")).hexdigest()


def _load_observations(path: Path, messages: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    _add(messages, "error", "invalid_json", f"invalid JSON at line {line_number}: {error.msg}", line_number)
                    continue
                if not isinstance(value, dict):
                    _add(messages, "error", "row_not_object", "each JSONL row must be an object", line_number)
                    continue
                rows.append((line_number, value))
    except OSError as error:
        _add(messages, "error", "input_read_error", f"could not read input: {error}")
    return rows


def _manifest_validator(path: Path) -> Draft202012Validator:
    schema_path = (ROOT / "schema" / "social_run_manifest.schema.json").resolve()
    return schema_validator(schema_path)


def _validate_manifest(path: Path, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        manifest = _read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        _add(messages, "error", "manifest_read_error", f"could not read run manifest: {error}")
        return None
    try:
        errors = sorted(_manifest_validator(path).iter_errors(manifest), key=lambda error: list(error.path))
    except (OSError, json.JSONDecodeError, KeyError) as error:
        _add(messages, "error", "manifest_schema_error", f"could not load run-manifest schema: {error}")
        return None
    for error in errors:
        location = ".".join(str(part) for part in error.path) or "<root>"
        _add(messages, "error", "manifest_invalid", f"{location}: {error.message}")
    return manifest if not errors and isinstance(manifest, dict) else None


def validate(
    input_path: Path,
    *,
    queries_path: Path | None = None,
    codebook_path: Path | None = None,
    objects_path: Path | None = None,
    sources_path: Path | None = None,
    run_manifest_path: Path | None = None,
    allow_zero_hash: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    rows = _load_observations(input_path, messages)
    check = observation_validator()

    query_registry: dict[str, dict[str, str]] = {}
    if queries_path:
        query_registry = _registry(_read_csv(queries_path, messages, "query registry"), "query_id", messages, "query registry")
    source_registry: dict[str, dict[str, str]] = {}
    if sources_path:
        source_registry = _registry(_read_csv(sources_path, messages, "source registry"), "source_id", messages, "source registry")

    code_sets: dict[str, set[str]] = {}
    if codebook_path:
        code_rows = _read_csv(codebook_path, messages, "codebook")
        for index, row in enumerate(code_rows, start=2):
            code_type = (row.get("code_type") or "").strip()
            code = (row.get("code") or "").strip()
            if not code_type or not code:
                _add(messages, "error", "codebook_missing_code", f"codebook row {index} needs code_type and code")
                continue
            code_sets.setdefault(code_type, set()).add(code)

    object_registry: dict[str, dict[str, str]] = {}
    object_aliases: dict[str, str] = {}
    if objects_path:
        object_rows = _read_csv(objects_path, messages, "object map")
        object_registry = _registry(object_rows, "canonical_label", messages, "object map")
        for index, row in enumerate(object_rows, start=2):
            canonical = (row.get("canonical_label") or "").strip()
            if not canonical:
                continue
            for alias in _split_pipe(row.get("aliases")):
                folded = alias.casefold()
                previous = object_aliases.get(folded)
                if previous and previous != canonical:
                    _add(messages, "error", "object_alias_collision", f"alias {alias!r} maps to both {previous!r} and {canonical!r}")
                object_aliases[folded] = canonical

    manifest: dict[str, Any] | None = None
    if run_manifest_path:
        manifest = _validate_manifest(run_manifest_path, messages)

    seen_ids: set[str] = set()
    seen_items: set[tuple[str, str, str]] = set()
    run_ids: Counter[str] = Counter()
    source_ids: Counter[str] = Counter()
    input_hashes: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    platform_counts: Counter[str] = Counter()
    referenced_items: list[tuple[int, str]] = []

    for line_number, record in rows:
        schema_errors = sorted(check.iter_errors(record), key=lambda error: list(error.path))
        for error in schema_errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            _add(messages, "error", "schema_invalid", f"{location}: {error.message}", line_number)

        observation_id = record.get("observation_id")
        if isinstance(observation_id, str):
            if observation_id in seen_ids:
                _add(messages, "error", "duplicate_observation_id", f"duplicate observation_id {observation_id!r}", line_number)
            seen_ids.add(observation_id)
        platform = record.get("platform")
        item_id = record.get("platform_item_id")
        if isinstance(platform, str) and isinstance(item_id, str):
            run_id_for_item = record.get("collection_run_id")
            item_key = (platform, str(run_id_for_item), item_id)
            if item_key in seen_items:
                _add(messages, "error", "duplicate_platform_item", f"duplicate platform item in run {run_id_for_item}: {platform}:{item_id}", line_number)
            seen_items.add(item_key)
            platform_counts[platform] += 1
        run_id = record.get("collection_run_id")
        if isinstance(run_id, str):
            run_ids[run_id] += 1
        source_id = record.get("source_id")
        if isinstance(source_id, str):
            source_ids[source_id] += 1
        status = record.get("annotation_status")
        if isinstance(status, str):
            status_counts[status] += 1

        normalization = record.get("normalization")
        if isinstance(normalization, dict):
            input_hash = normalization.get("input_sha256")
            if isinstance(input_hash, str):
                input_hashes[input_hash] += 1
                if input_hash == ZERO_HASH:
                    severity = "warning" if allow_zero_hash else "error"
                    _add(messages, severity, "zero_input_hash", "input_sha256 is a template placeholder", line_number)
            actual = normalization.get("record_sha256")
            if actual == ZERO_HASH:
                severity = "warning" if allow_zero_hash else "error"
                _add(messages, severity, "zero_record_hash", "record_sha256 is a template placeholder", line_number)
            elif isinstance(actual, str):
                expected = _expected_record_hash(record)
                if actual != expected:
                    _add(messages, "error", "record_hash_mismatch", f"record_sha256 does not match canonical record (expected {expected})", line_number)

        if queries_path:
            query_id = record.get("query_id")
            if query_id is None:
                _add(messages, "warning", "missing_query_id", "record has no query_id while a query registry was supplied", line_number)
            elif query_id not in query_registry:
                _add(messages, "error", "unknown_query_id", f"query_id {query_id!r} is not in the query registry", line_number)

        if sources_path:
            source_id = record.get("source_id")
            source_row = source_registry.get(str(source_id))
            if source_row is None:
                _add(messages, "error", "unknown_source_id", f"source_id {source_id!r} is not in the source registry", line_number)
            else:
                registry_url = (source_row.get("url") or "").strip()
                if registry_url and registry_url != record.get("url"):
                    _add(messages, "error", "source_url_mismatch", f"source registry URL differs for {source_id!r}", line_number)

        if codebook_path:
            object_type = record.get("object_type")
            if isinstance(object_type, str) and code_sets.get("object_type") and object_type not in code_sets["object_type"]:
                _add(messages, "error", "unknown_object_type", f"object_type {object_type!r} is not in the codebook", line_number)
            terms = record.get("aesthetic_terms") or []
            if isinstance(terms, list) and code_sets.get("aesthetic_term"):
                for term in terms:
                    if term not in code_sets["aesthetic_term"]:
                        _add(messages, "error", "unknown_aesthetic_term", f"aesthetic term {term!r} is not in the codebook", line_number)
            contexts = record.get("brand_context") or []
            if isinstance(contexts, list) and code_sets.get("brand_context"):
                for context in contexts:
                    if context not in code_sets["brand_context"]:
                        _add(messages, "error", "unknown_brand_context", f"brand context {context!r} is not in the codebook", line_number)

        if objects_path:
            label = record.get("object_label")
            if isinstance(label, str) and label:
                if label not in object_registry:
                    canonical = object_aliases.get(label.casefold())
                    if canonical:
                        _add(messages, "error", "noncanonical_object_label", f"use canonical object_label {canonical!r}, not alias {label!r}", line_number)
                    else:
                        _add(messages, "error", "unknown_object_label", f"object_label {label!r} is not in the object map", line_number)

        governance = record.get("governance") or {}
        if isinstance(governance, dict):
            author_handling = governance.get("author_handling")
            if record.get("author_ref") is not None and author_handling != "opaque_hash":
                _add(messages, "error", "author_governance_conflict", "author_ref is present but author_handling is not opaque_hash", line_number)
            if governance.get("raw_payload_status") == "stored" and governance.get("redistribution_status") == "permitted":
                _add(messages, "warning", "raw_payload_release_review", "stored raw payload marked permitted; verify rights before release", line_number)

        if status == "human_verified":
            if not record.get("annotator_ref"):
                _add(messages, "error", "missing_annotator_ref", "human_verified record needs annotator_ref", line_number)
            if not record.get("evidence_span"):
                _add(messages, "error", "missing_evidence_span", "human_verified record needs evidence_span", line_number)
        elif status == "candidate":
            _add(messages, "warning", "candidate_not_final", "candidate record is excluded from the default evidence summary", line_number)

        for reference in record.get("references") or []:
            if isinstance(reference, dict) and isinstance(reference.get("target_item_id"), str):
                referenced_items.append((line_number, reference["target_item_id"]))

    if len(input_hashes) > 1:
        _add(messages, "warning", "mixed_input_hashes", "records contain more than one input_sha256; confirm that multiple inputs were intentionally merged")

    if manifest:
        expected_run = manifest.get("collection_run_id")
        expected_platform = manifest.get("platform")
        expected_source_kind = manifest.get("source_kind")
        for run_id in run_ids:
            if run_id != expected_run:
                _add(messages, "error", "manifest_run_mismatch", f"record run {run_id!r} differs from manifest {expected_run!r}")
        for platform in platform_counts:
            if platform != expected_platform:
                _add(messages, "error", "manifest_platform_mismatch", f"record platform {platform!r} differs from manifest {expected_platform!r}")
        declared_queries = set(manifest.get("query_ids") or [])
        for line_number, record in rows:
            source_kind = record.get("source_kind")
            if expected_source_kind and source_kind != expected_source_kind:
                _add(messages, "error", "manifest_source_kind_mismatch", f"record source_kind {source_kind!r} differs from manifest {expected_source_kind!r}", line_number)
            query_id = record.get("query_id")
            if query_id is not None and query_id not in declared_queries:
                _add(messages, "error", "manifest_query_mismatch", f"record query_id {query_id!r} is not declared by the run manifest", line_number)

        # Verify the raw export when the manifest points to a file available in
        # the local checkout.  Missing raw files are normal on a clean public
        # clone, so they are reported only as a warning for completed runs.
        manifest_inputs = manifest.get("input_files") or []
        expected_input_hashes: set[str] = set()
        for entry in manifest_inputs:
            if not isinstance(entry, dict):
                continue
            declared = str(entry.get("sha256") or "")
            if declared and declared != ZERO_HASH:
                expected_input_hashes.add(declared)
            raw_path = Path(str(entry.get("path") or ""))
            if not raw_path.is_absolute():
                raw_path = ROOT / raw_path
            if not raw_path.exists():
                if manifest.get("status") in {"collected", "normalized", "reviewed", "closed"}:
                    _add(messages, "warning", "manifest_input_not_local", f"raw input is not present locally: {entry.get('path')!r}")
                continue
            actual_hash = sha256_file(raw_path)
            if declared == ZERO_HASH:
                _add(messages, "warning", "manifest_zero_input_hash", f"raw input has a placeholder SHA-256: {entry.get('path')!r}")
            elif declared and actual_hash != declared:
                _add(messages, "error", "manifest_input_hash_mismatch", f"raw input SHA-256 differs: {entry.get('path')!r}")
            declared_size = entry.get("byte_size")
            if declared_size is not None and int(declared_size) != raw_path.stat().st_size:
                _add(messages, "error", "manifest_input_size_mismatch", f"raw input byte size differs: {entry.get('path')!r}")
        if expected_input_hashes and not expected_input_hashes.intersection(input_hashes):
            _add(messages, "error", "normalization_input_hash_mismatch", "observation normalization hashes do not match the manifest input file")

        declared_counts = manifest.get("counts") or {}
        normalized_declared = declared_counts.get("normalized") if isinstance(declared_counts, dict) else None
        if normalized_declared is not None and int(normalized_declared) != len(rows):
            severity = "error" if manifest.get("status") in {"normalized", "reviewed", "closed"} else "warning"
            _add(messages, severity, "manifest_count_mismatch", f"manifest normalized count {normalized_declared} != file row count {len(rows)}")

    item_ids = {item_id for _, _, item_id in seen_items}
    missing_targets = sum(1 for _, target in referenced_items if target not in item_ids)
    if missing_targets:
        _add(messages, "warning", "external_reference_targets", f"{missing_targets} reference target(s) are outside this bounded sample")

    if strict:
        for item in messages:
            if item["severity"] == "warning":
                item["severity"] = "error"
                item["code"] = "strict_" + item["code"]

    errors = [item for item in messages if item["severity"] == "error"]
    warnings = [item for item in messages if item["severity"] == "warning"]
    return {
        "validator_version": "social_validate_v0.1.1",
        "input_path": _portable_path(input_path),
        "input_sha256": sha256_file(input_path) if input_path.exists() else None,
        "schema_version": "0.1.0",
        "valid": not errors,
        "record_count": len(rows),
        "counts": {
            "errors": len(errors),
            "warnings": len(warnings),
            "annotation_status": dict(sorted(status_counts.items())),
            "platform": dict(sorted(platform_counts.items())),
            "collection_run": dict(sorted(run_ids.items())),
        },
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="normalized social-observation JSONL")
    parser.add_argument("--queries", type=Path, help="optional social_queries.csv registry")
    parser.add_argument("--codebook", type=Path, help="optional social_codebook.csv registry")
    parser.add_argument("--objects", type=Path, help="optional social_object_map.csv registry")
    parser.add_argument("--sources", type=Path, help="optional source registry CSV")
    parser.add_argument("--run-manifest", type=Path, help="optional social_run_manifest.json")
    parser.add_argument("--report", type=Path, help="write a JSON validation report")
    parser.add_argument("--allow-zero-hash", action="store_true", help="allow template placeholder hashes (never use for release data)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    parser.add_argument("--force", action="store_true", help="replace an existing report")
    args = parser.parse_args()
    input_path = args.input.resolve()
    if not input_path.exists():
        print(f"input does not exist: {input_path}", file=sys.stderr)
        return 2
    if args.report and args.report.exists() and not args.force:
        print(f"report exists; choose another path or pass --force: {args.report}", file=sys.stderr)
        return 2
    result = validate(
        input_path,
        queries_path=args.queries,
        codebook_path=args.codebook,
        objects_path=args.objects,
        sources_path=args.sources,
        run_manifest_path=args.run_manifest,
        allow_zero_hash=args.allow_zero_hash,
        strict=args.strict,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"valid": result["valid"], "record_count": result["record_count"], **result["counts"]}, ensure_ascii=False, sort_keys=True))
    for item in result["messages"]:
        location = f"line {item['line']}: " if "line" in item else ""
        print(f"{item['severity']}: {location}{item['code']}: {item['message']}", file=sys.stderr)
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

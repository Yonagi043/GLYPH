#!/usr/bin/env python3
"""Project reviewed social observations into the shared narrative schema.

This is an explicit hand-off between the collection layer and
``cultural_narrative.schema.json``.  It never promotes ``candidate`` or
``unannotated`` rows, and it emits one narrative record per verified
object--term pair.  The command is offline: it does not fetch, enrich, or
rewrite the input observations.

The social-observation schema deliberately does not require a confidence
value, because confidence is a reviewer decision.  Supply ``--default-
confidence`` only when the team has agreed that a fixed value is appropriate;
otherwise add ``annotation_confidence`` to the local observation export before
running this hand-off.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from social_io import canonical_json, iter_jsonl, schema_validator, validation_errors
except ImportError:  # pragma: no cover - package-style invocation
    from tools.social_io import canonical_json, iter_jsonl, schema_validator, validation_errors


ROOT = Path(__file__).resolve().parents[1]
METHOD_MAP = {
    "official_api": "api",
    "public_web": "public_web",
    "manual_capture": "manual",
    "browser_capture": "manual",
    "imported_export": "corpus_export",
}
STATUS = {"human_verified"}
TARGET_AUTHOR_ROLES = {
    "brand", "design_studio", "designer", "design_media", "researcher",
    "ordinary_user", "unknown", None,
}


def _target_author_role(record: dict[str, Any]) -> str | None:
    """Map the collection role to the unchanged cultural-narrative schema.

    The collection schema distinguishes a ``creator`` from an ordinary user,
    while the frozen cultural schema does not.  Dropping that distinction is
    safer than relabelling a creator as a designer or user; the source social
    record remains the authoritative place for the original role.
    """

    role = record.get("author_role")
    if role in TARGET_AUTHOR_ROLES:
        return role
    if role == "creator":
        return "unknown"
    return None


def _narrative_validator() -> Draft202012Validator:
    schema_path = (ROOT / "schema" / "cultural_narrative.schema.json").resolve()
    return schema_validator(schema_path)


def _confidence(record: dict[str, Any], default: float | None) -> float:
    value = record.get("annotation_confidence")
    if value is None:
        extra = record.get("extra")
        if isinstance(extra, dict):
            value = extra.get("annotation_confidence")
    if value is None:
        if default is None:
            raise ValueError("missing_annotation_confidence")
        value = default
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_annotation_confidence") from error
    if not 0 <= number <= 1:
        raise ValueError("annotation_confidence_out_of_range")
    return number


def _evidence_id(record: dict[str, Any], term: str) -> str:
    payload = "\0".join(
        [
            str(record.get("observation_id", "")),
            str(record.get("object_type", "")),
            str(record.get("object_label", "")),
            term,
            str(record.get("evidence_span", "")),
        ]
    )
    return "ev_social_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _brand_context(record: dict[str, Any]) -> str | None:
    values = record.get("brand_context") or []
    if isinstance(values, str):
        values = [values]
    values = sorted({str(value).strip() for value in values if str(value).strip()}, key=str.casefold)
    return "|".join(values) if values else None


def project_record(record: dict[str, Any], *, default_confidence: float | None, check: Draft202012Validator) -> list[dict[str, Any]]:
    if record.get("annotation_status") not in STATUS:
        return []
    object_type = record.get("object_type")
    object_label = record.get("object_label")
    evidence_span = record.get("evidence_span")
    if not isinstance(object_type, str) or not object_type:
        raise ValueError("human_verified_requires_object_type")
    if not isinstance(object_label, str) or not object_label:
        raise ValueError("human_verified_requires_object_label")
    if not isinstance(evidence_span, str) or not evidence_span:
        raise ValueError("human_verified_requires_evidence_span")
    terms = record.get("aesthetic_terms") or []
    if isinstance(terms, str):
        terms = [terms]
    terms = sorted({str(term).strip() for term in terms if str(term).strip()}, key=lambda value: (value.casefold(), value))
    if not terms:
        raise ValueError("human_verified_requires_aesthetic_terms")
    method = METHOD_MAP.get(str(record.get("source_kind")), "corpus_export")
    confidence = _confidence(record, default_confidence)
    output: list[dict[str, Any]] = []
    for term in terms:
        narrative = {
            "evidence_id": _evidence_id(record, term),
            "stimulus_id": record.get("stimulus_id"),
            "source_id": record["source_id"],
            "object_type": object_type,
            "object_label": object_label,
            "aesthetic_term": term,
            "brand_context": _brand_context(record),
            "stance": record.get("stance") or "unclear",
            "mechanism_claim": record.get("mechanism_claim"),
            "evidence_span": evidence_span,
            "language_bcp47": record.get("language_bcp47"),
            "region_hint": record.get("region_hint"),
            "author_role": _target_author_role(record),
            "collection_method": method,
            "annotator_id": record.get("annotator_ref"),
            "confidence": confidence,
            "human_verified": True,
            "collected_at": record["collected_at"],
        }
        errors = list(check.iter_errors(narrative))
        if errors:
            detail = " | ".join(error.message for error in errors)
            raise ValueError("narrative_schema_invalid: " + detail)
        output.append(narrative)
    return output


def _write_failures(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_index", "error_code", "message"])
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if not input_path.exists():
        print(f"input does not exist: {input_path}", file=sys.stderr)
        return 2
    if output_path.exists() and not args.force:
        print(f"output exists; choose another path or pass --force: {output_path}", file=sys.stderr)
        return 2
    if args.default_confidence is not None and not 0 <= args.default_confidence <= 1:
        print("--default-confidence must be between 0 and 1", file=sys.stderr)
        return 2
    check = _narrative_validator()
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    try:
        iterator = iter_jsonl(input_path)
        for row_index, record in enumerate(iterator, start=1):
            try:
                # Validate the source row before projecting it.  This prevents
                # a malformed record from becoming apparently valid evidence.
                social_errors = validation_errors(record)
                if social_errors:
                    raise ValueError("social_schema_invalid: " + " | ".join(social_errors))
                records.extend(project_record(record, default_confidence=args.default_confidence, check=check))
            except (TypeError, ValueError, KeyError) as error:
                code, _, detail = str(error).partition(": ")
                failures.append({"row_index": str(row_index), "error_code": code, "message": detail or str(error)})
    except (OSError, ValueError) as error:
        print(f"could not read input: {error}", file=sys.stderr)
        return 2
    records.sort(key=lambda row: row["evidence_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(canonical_json(record) + "\n")
    failures_path = args.failures.resolve() if args.failures else output_path.with_suffix(output_path.suffix + ".failures.csv")
    _write_failures(failures_path, failures)
    print(f"projected {len(records)} narrative records; failures {len(failures)}")
    print(f"records: {output_path}")
    print(f"failures: {failures_path}")
    return 2 if failures and not args.allow_failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="normalized social-observation JSONL")
    parser.add_argument("--output", type=Path, required=True, help="cultural-narrative JSONL")
    parser.add_argument("--failures", type=Path, help="failure CSV path")
    parser.add_argument("--default-confidence", type=float, help="explicit fallback for reviewed rows (0..1)")
    parser.add_argument("--allow-failures", action="store_true", help="return success while preserving failure rows")
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

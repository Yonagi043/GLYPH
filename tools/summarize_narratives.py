#!/usr/bin/env python3
"""Build auditable narrative matrices from normalized social observations.

The command computes, for a fixed sample and optional platform/language
filters, both directions of the association:

    P(term | object) and P(object | term)

It also writes ``Lift = P(term | object) / P(term)``.  Counts are the default
unit.  A visible-engagement weighted view is available for descriptive
comparison, but is never mixed with the record-count view.  The output keeps
the input hash and exact options so a table can be regenerated later.

No causal or population-level interpretation is made by this tool.  The
objects, terms, and stance labels must have been manually verified before a
result is used as evidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from social_io import iter_jsonl, sha256_file, validation_errors, validator
except ImportError:
    from tools.social_io import iter_jsonl, sha256_file, validation_errors, validator


STATUS_ORDER = ("human_verified", "candidate")
INTERACTION_FIELDS = ("like_count", "comment_count", "share_count", "quote_count", "score")
EXPLORATORY_MIN_DENOMINATOR = 20
METRIC_FIELDS = {
    "likes": "like_count",
    "comments": "comment_count",
    "shares": "share_count",
    "quotes": "quote_count",
    "views": "view_count",
    "score": "score",
}


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return max(0.0, float(value))
    return 0.0


def visible_engagement(record: dict[str, Any]) -> float:
    metrics = record.get("engagement") or {}
    # This is a platform-local descriptive unit.  Views are deliberately not
    # added to interactions: they measure a different process and can be
    # orders of magnitude larger.  A row with no reported interaction has
    # weight zero in a weighted run rather than an invented count of one.
    observed = [metrics.get(key) for key in INTERACTION_FIELDS if metrics.get(key) is not None]
    return sum(_as_number(value) for value in observed) if observed else 0.0


def metric_weight(record: dict[str, Any], weight_mode: str) -> float:
    """Return one row's weight for a declared, platform-local metric."""

    if weight_mode == "records":
        return 1.0
    if weight_mode in {"engagement", "interactions"}:
        return visible_engagement(record)
    field = METRIC_FIELDS.get(weight_mode)
    if field is None:
        raise ValueError(f"unknown weight mode: {weight_mode}")
    value = (record.get("engagement") or {}).get(field)
    return _as_number(value) if value is not None else 0.0


def _object_label(record: dict[str, Any]) -> str | None:
    value = record.get("object_label")
    if isinstance(value, str) and value.strip():
        return value.strip()
    # These fallbacks make unambiguous API imports useful while retaining a
    # single column in the matrix.  Prefer an explicit object_label whenever
    # one is available.
    for key in ("font_id", "stimulus_id", "style_family", "writing_system"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _terms(record: dict[str, Any]) -> list[str]:
    values = record.get("aesthetic_terms") or []
    if isinstance(values, str):
        values = [values]
    clean = {str(value).strip() for value in values if str(value).strip()}
    return sorted(clean, key=lambda value: (value.casefold(), value))


def _included(record: dict[str, Any], statuses: set[str], platform: str | None, language: str | None, collection_run_id: str | None) -> bool:
    if record.get("annotation_status") not in statuses:
        return False
    if platform and record.get("platform") != platform:
        return False
    if language and record.get("language_bcp47") != language:
        return False
    if collection_run_id and record.get("collection_run_id") != collection_run_id:
        return False
    return True


def load_records(path: Path, *, statuses: set[str], platform: str | None, language: str | None, collection_run_id: str | None = None, validate: bool = True) -> tuple[list[dict[str, Any]], dict[str, int]]:
    check = validator() if validate else None
    records: list[dict[str, Any]] = []
    stats = defaultdict(int)
    seen: set[str] = set()
    for line_number, record in enumerate(iter_jsonl(path), start=1):
        stats["input_records"] += 1
        if validate:
            errors = validation_errors(record, check)
            if errors:
                raise ValueError(f"line {line_number} schema errors: {' | '.join(errors)}")
        observation_id = record.get("observation_id")
        if observation_id in seen:
            raise ValueError(f"duplicate observation_id at line {line_number}: {observation_id}")
        seen.add(observation_id)
        if not _included(record, statuses, platform, language, collection_run_id):
            stats["excluded_by_filter"] += 1
            continue
        object_label = _object_label(record)
        terms = _terms(record)
        if object_label is None:
            stats["missing_object"] += 1
            continue
        if not terms:
            # Keep the object in the denominator for P(term | object); a
            # missing annotation is not silently converted into a positive
            # term.  The row contributes zero to every pair.
            stats["missing_terms"] += 1
        record = dict(record)
        record["_matrix_object"] = object_label
        record["_matrix_terms"] = terms
        records.append(record)
    return records, dict(stats)


def _fmt(value: float) -> str:
    # Fixed precision makes diffs stable while retaining enough information for
    # small exploratory samples.
    return f"{value:.8f}"


def _exploration_flag(object_weight: float, term_weight: float) -> tuple[str, str]:
    """Flag cells whose object or term denominator is too small for ranking."""

    reasons = []
    if object_weight < EXPLORATORY_MIN_DENOMINATOR:
        reasons.append("object_denominator_lt_20")
    if term_weight < EXPLORATORY_MIN_DENOMINATOR:
        reasons.append("term_denominator_lt_20")
    return ("true" if reasons else "false", "|".join(reasons))


def build_matrices(records: Iterable[dict[str, Any]], weight_mode: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = list(records)
    total = sum(metric_weight(row, weight_mode) for row in rows)
    object_totals: defaultdict[str, float] = defaultdict(float)
    term_totals: defaultdict[str, float] = defaultdict(float)
    pairs: defaultdict[tuple[str, str], float] = defaultdict(float)
    for row in rows:
        weight = metric_weight(row, weight_mode)
        if weight <= 0:
            continue
        obj = row["_matrix_object"]
        terms = row["_matrix_terms"]
        object_totals[obj] += weight
        for term in terms:
            term_totals[term] += weight
            pairs[(obj, term)] += weight

    matrix_a: list[dict[str, Any]] = []
    matrix_b: list[dict[str, Any]] = []
    lift: list[dict[str, Any]] = []
    for (obj, term), pair_count in sorted(pairs.items()):
        obj_count = object_totals[obj]
        term_count = term_totals[term]
        p_term_given_object = pair_count / obj_count if obj_count else 0.0
        p_object_given_term = pair_count / term_count if term_count else 0.0
        p_term = term_count / total if total else 0.0
        p_object = obj_count / total if total else 0.0
        exploratory, exploratory_reason = _exploration_flag(obj_count, term_count)
        matrix_a.append({
            "object_label": obj,
            "term": term,
            "pair_weight": _fmt(pair_count),
            "object_weight": _fmt(obj_count),
            "p_term_given_object": _fmt(p_term_given_object),
            "weight_mode": weight_mode,
            "exploratory": exploratory,
            "exploratory_reason": exploratory_reason,
        })
        matrix_b.append({
            "term": term,
            "object_label": obj,
            "pair_weight": _fmt(pair_count),
            "term_weight": _fmt(term_count),
            "p_object_given_term": _fmt(p_object_given_term),
            "weight_mode": weight_mode,
            "exploratory": exploratory,
            "exploratory_reason": exploratory_reason,
        })
        lift.append({
            "object_label": obj,
            "term": term,
            "pair_weight": _fmt(pair_count),
            "object_weight": _fmt(obj_count),
            "term_weight": _fmt(term_count),
            "total_weight": _fmt(total),
            "p_term_given_object": _fmt(p_term_given_object),
            "p_object_given_term": _fmt(p_object_given_term),
            "p_term": _fmt(p_term),
            "p_object": _fmt(p_object),
            "lift": _fmt((p_term_given_object / p_term) if p_term else 0.0),
            "weight_mode": weight_mode,
            "exploratory": exploratory,
            "exploratory_reason": exploratory_reason,
        })
    return matrix_a, matrix_b, lift


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _portable_path(path: Path) -> str:
    """Avoid writing a researcher's absolute home path into a public summary."""

    try:
        return str(path.relative_to(Path(__file__).resolve().parents[1]))
    except ValueError:
        return path.name


def _quantile(values: list[int], probability: float) -> float | None:
    """Deterministic linear-interpolated quantile for a finite integer list."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return round(ordered[lower] + fraction * (ordered[upper] - ordered[lower]), 8)


def _engagement_summary(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, int | float | None]]:
    fields = ("like_count", "comment_count", "share_count", "quote_count", "view_count", "score")
    output: dict[str, dict[str, int | None]] = {}
    for field in fields:
        values = []
        for record in records:
            value = (record.get("engagement") or {}).get(field)
            # Reddit's score can be negative.  Preserve that observed value in
            # the descriptive summary; interaction weighting itself clamps
            # negative contributions to zero.
            lower_bound = -2147483648 if field == "score" else 0
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and value >= lower_bound:
                values.append(int(value))
        output[field] = {
            "non_null": len(values),
            "sum": sum(values) if values else 0,
            "max": max(values) if values else None,
            "median": _quantile(values, 0.50),
            "q1": _quantile(values, 0.25),
            "q3": _quantile(values, 0.75),
            "p90": _quantile(values, 0.90),
            "p99": _quantile(values, 0.99),
        }
    return output


def _timestamp(record: dict[str, Any]) -> str | None:
    value = record.get("published_at") or record.get("collected_at")
    return value if isinstance(value, str) and value else None


def _time_bucket(value: str | None, granularity: str) -> str:
    """Return a deterministic UTC day/week/month bucket for an ISO timestamp."""

    if not value:
        return "unknown"
    try:
        stamp = value[:-1] + "+00:00" if value.endswith("Z") else value
        from datetime import datetime, timezone, timedelta
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    except ValueError:
        return "unknown"
    if granularity == "day":
        return parsed.date().isoformat()
    if granularity == "month":
        return parsed.strftime("%Y-%m")
    # ISO weeks are represented by the Monday date, avoiding locale-specific
    # week numbers at year boundaries.
    monday = (parsed - timedelta(days=parsed.weekday())).date()
    return monday.isoformat()


def build_context_outputs(records: Iterable[dict[str, Any]], time_granularity: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build role, reference, evidence, and time-index tables.

    These are descriptive indexes.  They expose no author names and never
    infer a causal direction from an observed reference.
    """

    rows = list(records)
    role_counts: defaultdict[tuple[str, str, str, str, str], int] = defaultdict(int)
    role_first: dict[tuple[str, str, str, str, str], str] = {}
    role_last: dict[tuple[str, str, str, str, str], str] = {}
    time_counts: defaultdict[tuple[str, str, str, str, str], int] = defaultdict(int)
    edge_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for row in rows:
        obj = row.get("_matrix_object")
        terms = row.get("_matrix_terms") or []
        platform = str(row.get("platform") or "unknown")
        language = str(row.get("language_bcp47") or "unknown")
        role = str(row.get("author_role") or "unknown")
        stamp = _timestamp(row)
        if obj and terms:
            for term in terms:
                key = (platform, language, obj, term, role)
                role_counts[key] += 1
                if stamp:
                    role_first[key] = min(stamp, role_first.get(key, stamp))
                    role_last[key] = max(stamp, role_last.get(key, stamp))
                time_key = (platform, language, _time_bucket(stamp, time_granularity), obj, term)
                time_counts[time_key] += 1
        for reference in row.get("references") or []:
            if not isinstance(reference, dict):
                continue
            edge_rows.append({
                "source_observation_id": row.get("observation_id"),
                "source_platform": platform,
                "source_item_id": row.get("platform_item_id"),
                "target_item_id": reference.get("target_item_id"),
                "relation": reference.get("relation"),
                "source_published_at": stamp,
                "target_url": reference.get("target_url"),
            })
        if row.get("evidence_span") and obj and terms:
            evidence_rows.append({
                "observation_id": row.get("observation_id"),
                "annotation_status": row.get("annotation_status"),
                "source_id": row.get("source_id"),
                "url": row.get("url"),
                "platform": platform,
                "object_label": row.get("_matrix_object"),
                "terms": "|".join(row.get("_matrix_terms") or []),
                "stance": row.get("stance"),
                "mechanism_claim": row.get("mechanism_claim"),
                "evidence_span": row.get("evidence_span"),
                "annotator_ref": row.get("annotator_ref"),
            })
    role_rows = [
        {"platform": key[0], "language_bcp47": key[1], "object_label": key[2], "term": key[3], "author_role": key[4], "record_count": count, "first_published_at": role_first.get(key), "last_published_at": role_last.get(key)}
        for key, count in sorted(role_counts.items())
    ]
    time_rows = [
        {"platform": key[0], "language_bcp47": key[1], "time_bucket": key[2], "object_label": key[3], "term": key[4], "record_count": count, "time_granularity": time_granularity}
        for key, count in sorted(time_counts.items())
    ]
    edge_rows.sort(key=lambda row: (str(row["source_observation_id"]), str(row["relation"]), str(row["target_item_id"])))
    evidence_rows.sort(key=lambda row: str(row["observation_id"]))
    return role_rows, edge_rows, evidence_rows, time_rows


def run(args: argparse.Namespace) -> int:
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    if not input_path.exists():
        print(f"input does not exist: {input_path}", file=sys.stderr)
        return 2
    statuses = set(args.status or ["human_verified"])
    if args.weight != "records" and not args.platform:
        print("a non-record weight is platform-local; pass --platform to prevent cross-platform metric mixing", file=sys.stderr)
        return 2
    try:
        records, stats = load_records(input_path, statuses=statuses, platform=args.platform, language=args.language, collection_run_id=args.collection_run_id)
    except (OSError, ValueError) as error:
        print(f"could not load observations: {error}", file=sys.stderr)
        return 2
    try:
        matrix_a, matrix_b, lift = build_matrices(records, args.weight)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    role_rows, edge_rows, evidence_rows, time_rows = build_context_outputs(records, args.time_granularity)
    output_names = ["matrix_a_term_given_object.csv", "matrix_b_object_given_term.csv", "lift.csv", "role_timeline.csv", "reference_edges.csv", "evidence_index.csv", "time_series.csv", "summary.json"]
    existing = [output_dir / name for name in output_names if (output_dir / name).exists()]
    if existing and not args.force:
        print("output exists; choose a new directory or pass --force: " + ", ".join(str(path) for path in existing), file=sys.stderr)
        return 2
    _write_csv(output_dir / "matrix_a_term_given_object.csv", matrix_a, ["object_label", "term", "pair_weight", "object_weight", "p_term_given_object", "weight_mode", "exploratory", "exploratory_reason"])
    _write_csv(output_dir / "matrix_b_object_given_term.csv", matrix_b, ["term", "object_label", "pair_weight", "term_weight", "p_object_given_term", "weight_mode", "exploratory", "exploratory_reason"])
    _write_csv(output_dir / "lift.csv", lift, ["object_label", "term", "pair_weight", "object_weight", "term_weight", "total_weight", "p_term_given_object", "p_object_given_term", "p_term", "p_object", "lift", "weight_mode", "exploratory", "exploratory_reason"])
    _write_csv(output_dir / "role_timeline.csv", role_rows, ["platform", "language_bcp47", "object_label", "term", "author_role", "record_count", "first_published_at", "last_published_at"])
    _write_csv(output_dir / "reference_edges.csv", edge_rows, ["source_observation_id", "source_platform", "source_item_id", "target_item_id", "relation", "source_published_at", "target_url"])
    _write_csv(output_dir / "evidence_index.csv", evidence_rows, ["observation_id", "annotation_status", "source_id", "url", "platform", "object_label", "terms", "stance", "mechanism_claim", "evidence_span", "annotator_ref"])
    _write_csv(output_dir / "time_series.csv", time_rows, ["platform", "language_bcp47", "time_bucket", "object_label", "term", "record_count", "time_granularity"])
    weighted_records = sum(1 for row in records if metric_weight(row, args.weight) > 0)
    summary = {
        "summary_version": "0.1.0",
        "input_path": _portable_path(input_path),
        "input_sha256": sha256_file(input_path),
        "output_files": ["matrix_a_term_given_object.csv", "matrix_b_object_given_term.csv", "lift.csv", "role_timeline.csv", "reference_edges.csv", "evidence_index.csv", "time_series.csv", "summary.json"],
        "protocol_version": "social_narrative_v0.1.0",
        "filters": {"platform": args.platform, "language_bcp47": args.language, "collection_run_id": args.collection_run_id, "annotation_status": sorted(statuses)},
        "weight_mode": args.weight,
        "metric_definition": "records=one row; interactions=like+comment+share+quote+score within one platform (negative score contributes zero to a weight); individual modes select one visible metric; views are never added to interactions",
        "included_records": len(records),
        "weighted_records": weighted_records,
        "zero_weight_records": sum(1 for row in records if metric_weight(row, args.weight) <= 0),
        "exploratory_denominator_threshold": EXPLORATORY_MIN_DENOMINATOR,
        "exploratory_pair_count": sum(1 for row in lift if row["exploratory"] == "true"),
        "objects": sorted({row["_matrix_object"] for row in records}),
        "terms": sorted({term for row in records for term in row["_matrix_terms"]}),
        "engagement": _engagement_summary(records),
        "counts": stats,
        "interpretation": "Descriptive co-occurrence in the supplied sample; lift is not a causal or population estimate.",
        "time_granularity": args.time_granularity,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"included {len(records)} records; wrote {len(lift)} object-term pairs to {output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="canonical social-observation JSONL")
    parser.add_argument("--output-dir", type=Path, required=True, help="directory for matrix CSVs and summary.json")
    parser.add_argument("--status", action="append", choices=["human_verified", "candidate"], help="annotation status to include (repeat for more; default: human_verified)")
    parser.add_argument("--platform", choices=["reddit", "youtube", "x", "bluesky", "instagram", "tiktok", "douyin", "xiaohongshu", "pinterest", "bilibili", "telegram", "public_web", "manual_capture", "google_trends", "other"])
    parser.add_argument("--language", help="exact BCP-47 language filter, e.g. zh-CN")
    parser.add_argument("--collection-run-id", help="restrict analysis to one collection run")
    parser.add_argument("--weight", choices=["records", "interactions", "engagement", "likes", "comments", "shares", "quotes", "views", "score"], default="records", help="records or one platform-local visible metric; non-record modes require --platform")
    parser.add_argument("--time-granularity", choices=["day", "week", "month"], default="week", help="bucket for time_series.csv (UTC)")
    parser.add_argument("--force", action="store_true", help="replace existing matrix files")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

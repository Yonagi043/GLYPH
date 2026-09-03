#!/usr/bin/env python3
"""Normalize bounded public-platform exports into GLYPH social observations.

This command is intentionally offline.  It accepts JSON/JSONL/CSV exports from
an approved source (official API, public web capture, or a manual export),
removes direct author identifiers, applies one stable field mapping, validates
every output record against ``schema/social_observation.schema.json``, and
records failures instead of silently dropping rows.

It does not fetch a platform, bypass a login, or evade rate limits.  Keep raw
exports in the ignored ``data/raw/social/`` tree and publish only records whose
rights and privacy status have been reviewed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

try:  # Running as ``python tools/normalize_social_records.py``
    from social_io import (
        as_int,
        as_string,
        canonical_json,
        first_nonempty,
        nested_dict,
        read_input_rows,
        sha256_file,
        split_labels,
        validation_errors,
        validator,
        write_jsonl,
    )
except ImportError:  # Imported as ``tools.normalize_social_records``
    from tools.social_io import (
        as_int,
        as_string,
        canonical_json,
        first_nonempty,
        nested_dict,
        read_input_rows,
        sha256_file,
        split_labels,
        validation_errors,
        validator,
        write_jsonl,
    )


LEGACY_SCHEMA_VERSION = "0.1.0"
MASTODON_SCHEMA_VERSION = "0.2.0"
NORMALIZER_VERSION = "social_normalize_v0.1.0"
PLATFORMS = {
    "reddit", "youtube", "x", "bluesky", "mastodon", "instagram", "tiktok", "douyin",
    "xiaohongshu", "pinterest", "bilibili", "telegram", "public_web",
    "manual_capture", "google_trends", "other",
}
SOURCE_KINDS = {"official_api", "public_web", "manual_capture", "browser_capture", "imported_export"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
RUN_RE = re.compile(r"^social_run_[a-z0-9][a-z0-9_-]{2,127}$")
QUERY_RE = re.compile(r"^q_[a-z0-9][a-z0-9_-]{2,127}$")
MIN_AUTHOR_SALT_LENGTH = 16
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "msclkid", "igshid",
    "ref_src", "ref_url", "si",
}


def _canonical_url(value: Any) -> str | None:
    """Return a stable, privacy-conscious URL without making a network call.

    Only widely-recognised campaign/tracking parameters and fragments are
    removed.  The offline core never follows redirects, resolves short links,
    or guesses that two different paths are the same resource.
    """

    supplied = first_nonempty(value)
    if supplied is None:
        return None
    text = str(supplied).strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    # Credentials in a URL are both unnecessary and unsafe for a public
    # research record.  Reject them rather than copying them into output.
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{netloc}:{port}"
    pairs = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        folded = key.casefold()
        if folded.startswith("utm_") or folded in TRACKING_QUERY_KEYS:
            continue
        pairs.append((key, item))
    # Sorting retained pairs makes equivalent query orderings hash alike while
    # preserving repeated parameters.
    pairs.sort(key=lambda pair: (pair[0].casefold(), pair[0], pair[1]))
    query = urlencode(pairs, doseq=True)
    return urlunparse((parsed.scheme.lower(), netloc, parsed.path, parsed.params, query, ""))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_datetime(value: Any) -> str | None:
    """Return an ISO-8601 instant, preserving timezone information where given."""

    value = first_nonempty(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # API exports frequently use a trailing Z; datetime.fromisoformat accepts
    # the normalized +00:00 spelling on all supported Python versions.
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _url_for(platform: str, item_id: str, value: Any) -> str | None:
    supplied = first_nonempty(value)
    if supplied is not None:
        return _canonical_url(supplied)
    encoded = quote(item_id, safe="")
    if platform == "x":
        return f"https://x.com/i/status/{encoded}"
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={encoded}"
    if platform == "reddit":
        clean_id = item_id[3:] if item_id.startswith("t3_") else item_id
        return f"https://www.reddit.com/comments/{quote(clean_id, safe='')}"
    return None


def _metric(metrics: dict[str, Any], row: dict[str, Any], *keys: str, allow_negative: bool = False) -> int | None:
    values = [metrics.get(key) for key in keys] + [row.get(key) for key in keys]
    for value in values:
        result = as_int(value, allow_negative=allow_negative)
        if result is not None:
            return result
    return None


def _engagement(row: dict[str, Any], collected_at: str) -> dict[str, Any]:
    # Accept both platform-native ``public_metrics`` and an already grouped
    # ``engagement`` object from a hand-written/exported adapter.
    metrics = nested_dict(row, "public_metrics")
    if not metrics:
        metrics = nested_dict(row, "engagement")
    # YouTube uses camelCase; Reddit and X generally use snake_case.
    observed = _as_datetime(first_nonempty(row.get("engagement_observed_at"), row.get("updated_at"), collected_at))
    public_value = first_nonempty(row.get("engagement_is_public"), True)
    if isinstance(public_value, str):
        public_value = public_value.strip().lower() not in {"0", "false", "no", "n", "private"}
    else:
        public_value = bool(public_value)
    return {
        "like_count": _metric(metrics, row, "like_count", "likeCount", "likes", "ups"),
        "comment_count": _metric(metrics, row, "comment_count", "commentCount", "comments", "num_comments", "reply_count"),
        "share_count": _metric(metrics, row, "share_count", "shareCount", "shares", "repost_count", "retweet_count"),
        "quote_count": _metric(metrics, row, "quote_count", "quoteCount", "quotes"),
        "view_count": _metric(metrics, row, "view_count", "viewCount", "views"),
        "score": _metric(metrics, row, "score", allow_negative=True),
        "observed_at": observed,
        "is_public": public_value,
    }


def _text_and_title(row: dict[str, Any]) -> tuple[str, str | None]:
    snippet = nested_dict(row, "snippet")
    title = first_nonempty(row.get("title"), snippet.get("title"), row.get("name"))
    text = first_nonempty(
        row.get("text"),
        row.get("full_text"),
        row.get("body"),
        row.get("selftext"),
        row.get("description"),
        snippet.get("description"),
        default="",
    )
    # A Reddit export commonly has a title and body.  Preserve both without
    # pretending that the title was part of the body.
    if not text and title:
        text = title
    return str(text), (str(title) if title is not None else None)


def _content_status(row: dict[str, Any], text: str) -> str:
    """Classify availability without guessing what an image depicts."""

    explicit = first_nonempty(row.get("content_status"))
    allowed = {"available", "image_only", "video_only", "deleted", "private", "unreachable", "unknown"}
    if explicit is not None:
        value = str(explicit).strip()
        if value not in allowed:
            raise ValueError("invalid_content_status")
        return value
    deleted = row.get("is_deleted")
    if isinstance(deleted, str):
        deleted = deleted.strip().lower() in {"1", "true", "yes", "y"}
    if deleted:
        return "deleted"
    media = str(first_nonempty(row.get("media_type"), row.get("mime_type"), default="")).strip().lower()
    raw_text = first_nonempty(row.get("text"), row.get("full_text"), row.get("body"), row.get("selftext"), row.get("description"), default="")
    # A title is sometimes copied into ``text`` for discoverability.  It does
    # not make an image-only/video-only item text-bearing, so inspect the raw
    # text fields as well.
    has_raw_text = bool(str(raw_text).strip())
    if not has_raw_text and "image" in media:
        return "image_only"
    if not has_raw_text and "video" in media:
        return "video_only"
    if text.strip():
        return "available"
    return "unknown"


def _canonical_value(value: Any, aliases: dict[str, str]) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return aliases.get(text.casefold(), text)


WRITING_SYSTEM_ALIASES = {
    "latn": "latin", "hani": "han", "kana": "kana", "hang": "hangul",
    "latin alphabet": "latin", "latin script": "latin", "拉丁字母": "latin", "拉丁": "latin",
    "汉字": "han", "漢字": "han", "hanzi": "han", "chinese characters": "han",
    "假名": "kana", "japanese kana": "kana",
    "韩文": "hangul", "韓文": "hangul", "korean script": "hangul",
}
STYLE_ALIASES = {
    "小篆": "seal", "篆书": "seal", "seal script": "seal", "楷书": "regular", "regular script": "regular",
    "行书": "running", "草书": "cursive", "隶书": "clerical", "黑体": "sans", "无衬线": "sans",
    "sans-serif": "sans", "sans serif": "sans", "serif": "serif", "宋体": "song", "衬线": "serif", "手写": "handwritten",
}


def _references(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("references", row.get("referenced_tweets", []))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        return []
    relation_map = {
        "replied_to": "reply", "reply": "reply", "parent": "parent",
        "retweeted": "repost", "reposted": "repost", "repost": "repost",
        "quoted": "quote", "quote": "quote", "mention": "mention", "link": "link",
    }
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        target = first_nonempty(item.get("target_item_id"), item.get("id"), item.get("target_id"))
        if target is None:
            continue
        relation = relation_map.get(str(first_nonempty(item.get("relation"), item.get("type"), default="unknown")), "unknown")
        target = str(target)
        key = (relation, target)
        if key in seen:
            continue
        seen.add(key)
        target_url = _url_for("other", target, item.get("target_url"))
        output.append({"relation": relation, "target_item_id": target, "target_url": target_url})
    return sorted(output, key=lambda item: (item["relation"], item["target_item_id"]))


def _author_ref(row: dict[str, Any], salt: str | None) -> str | None:
    # Never copy a username/display name into the canonical record.  A caller
    # may opt into a stable opaque reference by supplying a private salt.
    if not salt:
        return None
    raw = first_nonempty(row.get("author_id"), row.get("authorId"), row.get("author_ref"), row.get("user_id"))
    if raw is None:
        return None
    digest = hashlib.sha256((salt + "\0" + str(raw)).encode("utf-8")).hexdigest()[:32]
    return "author_" + digest


def _annotation_confidence(row: dict[str, Any]) -> float | None:
    """Read an optional reviewer confidence without inventing one."""

    value = first_nonempty(row.get("annotation_confidence"))
    if value is None:
        extra = nested_dict(row, "extra")
        value = first_nonempty(extra.get("annotation_confidence"))
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_annotation_confidence") from error
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("annotation_confidence_out_of_range")
    return number


def _source_id(url: str, supplied: Any) -> str:
    candidate = first_nonempty(supplied)
    if candidate is not None:
        if not ID_RE.fullmatch(str(candidate)):
            raise ValueError("invalid_source_id")
        return str(candidate)
    return "src_social_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _observation_id(platform: str, collection_run_id: str, item_id: str, supplied: Any) -> str:
    candidate = first_nonempty(supplied)
    if candidate is not None:
        if not re.fullmatch(r"^obs_[a-z0-9][a-z0-9_-]{2,127}$", str(candidate)):
            raise ValueError("invalid_observation_id")
        return str(candidate)
    # An observation is an item *as seen in one run*.  Including the run keeps
    # repeated captures of the same platform item distinct so that changing
    # visible metrics are never overwritten or silently collapsed.
    digest = hashlib.sha256((platform + "\0" + collection_run_id + "\0" + item_id).encode("utf-8")).hexdigest()[:32]
    return "obs_" + digest


def _normalization_hash_payload(record: dict[str, Any]) -> dict[str, Any]:
    copy = json.loads(canonical_json(record))
    copy.pop("normalization", None)
    return copy


def normalize_row(
    row: dict[str, Any],
    *,
    platform: str,
    source_kind: str,
    collection_run_id: str,
    input_sha256: str,
    normalized_at: str,
    query_id: str | None,
    query_text: str | None,
    author_salt: str | None,
) -> dict[str, Any]:
    snippet = nested_dict(row, "snippet")
    item_id = first_nonempty(row.get("platform_item_id"), row.get("item_id"), row.get("id"), row.get("video_id"), row.get("post_id"))
    if item_id is None or not str(item_id).strip():
        raise ValueError("missing_item_id")
    item_id = str(item_id).strip()
    url = _url_for(platform, item_id, first_nonempty(row.get("url"), row.get("permalink"), row.get("link")))
    if url is None:
        raise ValueError("missing_or_invalid_url")
    collected = _as_datetime(first_nonempty(row.get("collected_at"), normalized_at))
    if collected is None:
        raise ValueError("invalid_collected_at")
    published = _as_datetime(first_nonempty(row.get("published_at"), row.get("created_at"), row.get("createdAt"), snippet.get("publishedAt")))
    text, title = _text_and_title(row)
    content_status = _content_status(row, text)
    terms = split_labels(first_nonempty(row.get("aesthetic_terms"), row.get("aesthetic_term"), []))
    contexts = split_labels(first_nonempty(row.get("brand_context"), row.get("brand_contexts"), []))
    human_flag = first_nonempty(row.get("human_verified"))
    if isinstance(human_flag, str):
        human_flag = human_flag.strip().lower() in {"1", "true", "yes", "y"}
    annotation_status = as_string(first_nonempty(
        row.get("annotation_status"),
        "human_verified" if bool(human_flag) else None,
        default="unannotated",
    ))
    if annotation_status not in {"unannotated", "candidate", "human_verified", "excluded"}:
        raise ValueError("invalid_annotation_status")
    human_verified_at = _as_datetime(row.get("human_verified_at"))
    if annotation_status == "human_verified" and human_verified_at is None:
        # Do not invent a review timestamp.  The row remains a failure until a
        # reviewer supplies it explicitly.
        raise ValueError("human_verified_requires_timestamp")
    annotator_ref = first_nonempty(row.get("annotator_ref"), row.get("annotator_id"))
    if annotation_status == "human_verified" and annotator_ref is None:
        raise ValueError("human_verified_requires_annotator_ref")
    effective_query_id = first_nonempty(query_id, row.get("query_id"))
    if effective_query_id is not None and not QUERY_RE.fullmatch(str(effective_query_id)):
        raise ValueError("invalid_query_id")
    effective_query_text = first_nonempty(query_text, row.get("query_text"))
    source_id = _source_id(url, row.get("source_id"))
    record: dict[str, Any] = {
        "schema_version": (
            MASTODON_SCHEMA_VERSION if platform == "mastodon" else LEGACY_SCHEMA_VERSION
        ),
        "observation_id": _observation_id(platform, collection_run_id, item_id, row.get("observation_id")),
        "collection_run_id": collection_run_id,
        "platform": platform,
        "platform_item_id": item_id,
        "source_id": source_id,
        "url": url,
        "source_kind": source_kind,
        "query_id": str(effective_query_id) if effective_query_id is not None else None,
        "query_text": str(effective_query_text) if effective_query_text is not None else None,
        "published_at": published,
        "collected_at": collected,
        "language_bcp47": first_nonempty(row.get("language_bcp47"), row.get("lang"), row.get("language")),
        "region_hint": first_nonempty(row.get("region_hint"), row.get("region")),
        "title": title,
        "text": text,
        "content_status": content_status,
        "author_ref": _author_ref(row, author_salt),
        "author_role": first_nonempty(row.get("author_role"), row.get("role")),
        "writing_system": _canonical_value(first_nonempty(row.get("writing_system"), row.get("script")), WRITING_SYSTEM_ALIASES),
        "style_family": _canonical_value(first_nonempty(row.get("style_family"), row.get("style")), STYLE_ALIASES),
        "object_type": first_nonempty(row.get("object_type")),
        "object_label": first_nonempty(row.get("object_label")),
        "stimulus_id": first_nonempty(row.get("stimulus_id")),
        "font_id": first_nonempty(row.get("font_id")),
        "aesthetic_terms": terms,
        "brand_context": contexts,
        "stance": first_nonempty(row.get("stance")),
        "mechanism_claim": first_nonempty(row.get("mechanism_claim")),
        "evidence_span": first_nonempty(row.get("evidence_span")),
        "engagement": _engagement(row, collected),
        "references": _references(row),
        "annotation_status": annotation_status,
        "annotator_ref": annotator_ref,
        "human_verified_at": human_verified_at,
        "annotation_confidence": _annotation_confidence(row),
        "exclusion_reason": first_nonempty(row.get("exclusion_reason")),
        "governance": {
            "author_handling": "opaque_hash" if author_salt else "not_collected",
            "raw_payload_status": first_nonempty(nested_dict(row, "governance").get("raw_payload_status"), "local_only"),
            "redistribution_status": first_nonempty(nested_dict(row, "governance").get("redistribution_status"), "derived_only"),
            "terms_checked_at": first_nonempty(nested_dict(row, "governance").get("terms_checked_at")),
            "notes": first_nonempty(nested_dict(row, "governance").get("notes")),
        },
        "normalization": {
            "normalizer_version": NORMALIZER_VERSION,
            "input_sha256": input_sha256,
            "record_sha256": "0" * 64,
            "normalized_at": normalized_at,
        },
        "extra": {
            "adapter_fields": sorted(str(key) for key in row.keys() if str(key) not in {
                "id", "platform_item_id", "item_id", "item_id", "url", "permalink", "link", "text", "full_text", "body", "selftext", "description", "title", "snippet", "created_at", "published_at"
            })[:100],
            "media_type": str(first_nonempty(row.get("media_type"), row.get("mime_type"))) if first_nonempty(row.get("media_type"), row.get("mime_type")) is not None else None,
            "is_deleted": row.get("is_deleted") if isinstance(row.get("is_deleted"), bool) else None,
        },
    }
    # Remove None-valued adapter metadata only where the schema allows null;
    # keeping the keys makes the canonical projection self-describing.
    record["normalization"]["record_sha256"] = hashlib.sha256(canonical_json(_normalization_hash_payload(record)).encode("utf-8")).hexdigest()
    return record


def source_row(record: dict[str, Any], source_license: str | None = None) -> dict[str, Any]:
    platform = record["platform"]
    source_type = (
        "video"
        if platform in {"youtube", "tiktok"}
        and record["platform_item_id"].startswith("video:")
        else "social_post"
    )
    return {
        "source_id": record["source_id"],
        "source_type": source_type,
        "title": record.get("title") or record["platform_item_id"],
        "publisher_or_creator": platform,
        "url": record["url"],
        "published_at": record.get("published_at") or "",
        "accessed_at": record["collected_at"][:10],
        "language_bcp47": record.get("language_bcp47") or "",
        "region": record.get("region_hint") or "",
        "license_status": source_license or "unknown",
        "license_text_or_id": "",
        "redistribution_allowed": "",
        # This is a CSV projection of source.schema.json.  A non-empty value
        # must be a JSON object in downstream tooling; an empty cell means null.
        "local_archive": "",
        "notes": "Generated from normalized social observation; verify platform terms before release.",
    }


def _write_failures(path: Path, failures: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["row_index", "error_code", "message", "row_sha256"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(failures)


def _write_sources(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_id", "source_type", "title", "publisher_or_creator", "url", "published_at", "accessed_at", "language_bcp47", "region", "license_status", "license_text_or_id", "redistribution_allowed", "local_archive", "notes"]
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        unique.setdefault(record["source_id"], source_row(record))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source_id in sorted(unique):
            writer.writerow(unique[source_id])


def run(args: argparse.Namespace) -> int:
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if not input_path.exists():
        print(f"input does not exist: {input_path}", file=sys.stderr)
        return 2
    if args.platform not in PLATFORMS:
        print(f"unsupported platform: {args.platform}", file=sys.stderr)
        return 2
    if args.source_kind not in SOURCE_KINDS:
        print(f"unsupported source kind: {args.source_kind}", file=sys.stderr)
        return 2
    if not RUN_RE.fullmatch(args.collection_run_id):
        print("collection-run-id must match social_run_<lowercase-id>", file=sys.stderr)
        return 2
    if args.query_id is not None and not QUERY_RE.fullmatch(args.query_id):
        print("query-id must match q_<lowercase-id>", file=sys.stderr)
        return 2
    if args.author_salt is not None and (len(args.author_salt) < MIN_AUTHOR_SALT_LENGTH or not args.author_salt.strip()):
        print(f"--author-salt must contain at least {MIN_AUTHOR_SALT_LENGTH} non-whitespace characters", file=sys.stderr)
        return 2
    normalized_at = _as_datetime(args.normalized_at or now_iso())
    if normalized_at is None:
        print("invalid --normalized-at", file=sys.stderr)
        return 2
    input_sha = sha256_file(input_path)
    failures_path = (args.failures or output_path.with_suffix(output_path.suffix + ".failures.csv")).resolve()
    planned_paths = [output_path, failures_path]
    if args.sources_output:
        planned_paths.append(args.sources_output.resolve())
    existing = [path for path in planned_paths if path.exists()]
    if existing and not args.force:
        print("output exists; choose new paths or pass --force: " + ", ".join(str(path) for path in existing), file=sys.stderr)
        return 2
    try:
        rows = read_input_rows(input_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _write_failures(failures_path, [{
            "row_index": "",
            "error_code": "input_parse_error",
            "message": str(error),
            "row_sha256": input_sha,
        }])
        print(f"could not read input: {error}", file=sys.stderr)
        print(f"failures: {failures_path}", file=sys.stderr)
        return 2
    check = validator()
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_items: set[tuple[str, str, str]] = set()
    for row_index, row in enumerate(rows, start=1):
        row_hash = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()
        try:
            record = normalize_row(
                row,
                platform=args.platform,
                source_kind=args.source_kind,
                collection_run_id=args.collection_run_id,
                input_sha256=input_sha,
                normalized_at=normalized_at,
                query_id=args.query_id,
                query_text=args.query_text,
                author_salt=args.author_salt,
            )
            item_key = (record["platform"], record["collection_run_id"], record["platform_item_id"])
            if item_key in seen_items:
                raise ValueError("duplicate_platform_item")
            if record["observation_id"] in seen_ids:
                raise ValueError("duplicate_observation_id")
            errors = validation_errors(record, check)
            if errors:
                raise ValueError("schema_invalid: " + " | ".join(errors))
            seen_ids.add(record["observation_id"])
            seen_items.add(item_key)
            records.append(record)
        except (ValueError, TypeError, KeyError) as error:
            message = str(error)
            code, _, detail = message.partition(": ")
            failures.append({"row_index": row_index, "error_code": code, "message": detail or message, "row_sha256": row_hash})
        except Exception as error:  # keep one malformed adapter row from aborting the run
            failures.append({
                "row_index": row_index,
                "error_code": "unexpected_error",
                "message": f"{type(error).__name__}: {error}",
                "row_sha256": row_hash,
            })
    records.sort(key=lambda record: record["observation_id"])
    write_jsonl(output_path, records)
    _write_failures(failures_path, failures)
    if args.sources_output:
        _write_sources(args.sources_output.resolve(), records)
    print(f"normalized {len(records)} records; failures {len(failures)}")
    print(f"records: {output_path}")
    print(f"failures: {failures_path.resolve()}")
    if failures and not args.allow_failures:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON, JSONL, or CSV export")
    parser.add_argument("--output", type=Path, required=True, help="canonical social-observation JSONL")
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--source-kind", default="imported_export", choices=sorted(SOURCE_KINDS))
    parser.add_argument("--collection-run-id", required=True, help="stable run label, e.g. social_run_20260901_x_demo")
    parser.add_argument("--query-id", help="optional registered query id, e.g. q_typography_en")
    parser.add_argument("--query-text", help="optional exact query text")
    parser.add_argument("--normalized-at", help="fixed UTC timestamp for reproducible output")
    parser.add_argument("--author-salt", help="private salt; enables opaque author_ref hashes (never publish the salt)")
    parser.add_argument("--failures", type=Path, help="failure CSV path (default: output + .failures.csv)")
    parser.add_argument("--sources-output", type=Path, help="optional CSV projection of the source.schema.json registry")
    parser.add_argument("--allow-failures", action="store_true", help="return success while preserving failure records")
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))

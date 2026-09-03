"""Bluesky Jetstream v2 adapter for bounded social-narrative collection."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from tools.normalize_social_records import normalize_row
from tools.social_io import canonical_json


JETSTREAM_ENDPOINT = (
    "wss://jetstream.us-east.bsky.network/"
    "xrpc/network.bsky.jetstream.subscribeEvents"
)
POST_COLLECTION = "app.bsky.feed.post"


def _instant(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ResearchScope:
    query_id: str
    object_type: str
    object_label: str
    keywords: tuple[str, ...]
    languages: tuple[str, ...]
    window_start: str
    window_end: str
    exact_query: str | None = None

    def matches(self, text: str, languages: list[str], published_at: str) -> bool:
        folded = text.casefold()
        if not any(
            re.search(r"(?<!\w)" + re.escape(keyword.casefold()) + r"(?!\w)", folded)
            for keyword in self.keywords
        ):
            return False
        wanted = {language.casefold() for language in self.languages}
        observed = {language.casefold() for language in languages}
        if wanted and not any(
            value == target or value.startswith(target + "-")
            for value in observed
            for target in wanted
        ):
            return False
        published = _instant(published_at)
        return _instant(self.window_start) <= published <= _instant(self.window_end)


def event_cursor(event: dict[str, Any]) -> int:
    payload = event.get("payload")
    if isinstance(payload, dict) and isinstance(payload.get("seq"), int):
        return payload["seq"]
    if isinstance(event.get("time_us"), int):
        return event["time_us"]
    raise ValueError("jetstream event has no integer cursor")


def subscription_url(cursor: int | None = None) -> str:
    parameters: list[tuple[str, str]] = [
        ("collections", POST_COLLECTION),
        ("kinds", "commit"),
    ]
    if cursor is not None:
        parameters.append(("cursor", str(cursor)))
    return JETSTREAM_ENDPOINT + "?" + urlencode(parameters)


def _post_url(did: str, rkey: str) -> str:
    return f"https://bsky.app/profile/{did}/post/{rkey}"


def _reference_rows(record: dict[str, Any]) -> list[dict[str, str]]:
    reply = record.get("reply")
    if not isinstance(reply, dict):
        return []
    output = []
    for key, relation in (("parent", "reply"), ("root", "parent")):
        target = reply.get(key)
        if not isinstance(target, dict) or not isinstance(target.get("uri"), str):
            continue
        uri = target["uri"]
        parts = uri.split("/")
        row = {"relation": relation, "target_item_id": uri}
        if len(parts) >= 5 and parts[0] == "at:":
            row["target_url"] = _post_url(parts[2], parts[-1])
        output.append(row)
    return output


def normalize_jetstream_event(
    event: dict[str, Any],
    *,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any] | None:
    """Return one candidate observation, or ``None`` when outside the scope."""

    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("$type") != "network.bsky.jetstream.subscribeEvents#commit":
        return None
    if payload.get("collection") != POST_COLLECTION:
        return None
    if payload.get("operation") not in {"create", "update"}:
        return None
    record = payload.get("record")
    did = payload.get("did")
    rkey = payload.get("rkey")
    if not isinstance(record, dict) or not isinstance(did, str) or not isinstance(rkey, str):
        raise ValueError("invalid Bluesky post commit")
    text = record.get("text")
    created_at = record.get("createdAt")
    languages = record.get("langs") or []
    if not isinstance(text, str) or not isinstance(created_at, str):
        raise ValueError("Bluesky post is missing text or createdAt")
    if not isinstance(languages, list) or not all(isinstance(value, str) for value in languages):
        raise ValueError("Bluesky post langs must be an array of strings")
    if not scope.matches(text, languages, created_at):
        return None

    uri = f"at://{did}/{POST_COLLECTION}/{rkey}"
    raw_hash = hashlib.sha256(canonical_json(event).encode("utf-8")).hexdigest()
    adapter_row = {
        "id": uri,
        "url": _post_url(did, rkey),
        "text": text,
        "created_at": created_at,
        "collected_at": normalized_at,
        "language_bcp47": languages[0] if languages else None,
        "annotation_status": "candidate",
        "references": _reference_rows(record),
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": "Bluesky public Jetstream v2 bounded query sample.",
        },
    }
    return normalize_row(
        adapter_row,
        platform="bluesky",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=raw_hash,
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )
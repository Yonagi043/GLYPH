"""TikTok Research API adapter primitives for bounded offline-verified collection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from tools.normalize_social_records import normalize_row
from tools.social_io import canonical_json

from .bluesky import ResearchScope


TIKTOK_PLAYER_ORIGIN = "https://www.tiktok.com/player/v1"
TIKTOK_API_ORIGIN = "https://open.tiktokapis.com"
TIKTOK_TOKEN_URL = f"{TIKTOK_API_ORIGIN}/v2/oauth/token/"
TIKTOK_VIDEO_QUERY_URL = f"{TIKTOK_API_ORIGIN}/v2/research/video/query/"
TIKTOK_COMMENT_LIST_URL = (
    f"{TIKTOK_API_ORIGIN}/v2/research/video/comment/list/"
)
REQUIRED_OUTBOUND_PROXY = "http://127.0.0.1:7897"
TIKTOK_VIDEO_FIELDS = (
    "id",
    "video_description",
    "create_time",
    "region_code",
    "hashtag_names",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "favorites_count",
)
TIKTOK_COMMENT_FIELDS = (
    "id",
    "video_id",
    "text",
    "like_count",
    "reply_count",
    "parent_comment_id",
    "create_time",
)
TIKTOK_ID_RE = re.compile(r"^[0-9]{1,32}$")
TIKTOK_QUERY_OPERATIONS = {
    "keyword": {"EQ"},
    "region_code": {"EQ", "IN"},
    "video_id": {"EQ", "IN"},
    "hashtag_name": {"EQ", "IN"},
    "create_date": {"EQ", "GT", "GTE", "LT", "LTE"},
    "music_id": {"EQ", "IN"},
    "effect_id": {"EQ", "IN"},
    "video_length": {"EQ", "GT", "GTE", "LT", "LTE"},
}


class TikTokApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        api_code: str | None,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.api_code = api_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _header_number(headers: Any, name: str) -> float | None:
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None and hasattr(headers, "items"):
        value = next(
            (
                candidate
                for key, candidate in headers.items()
                if str(key).casefold() == name.casefold()
            ),
            None,
        )
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


class TikTokResearchClient:
    """Minimal client-token adapter for approved TikTok Research API clients."""

    def __init__(
        self,
        *,
        client_key: str,
        client_secret: str,
        proxy_url: str,
        timeout_seconds: float = 30.0,
        opener: OpenerDirector | Any | None = None,
        clock: Any | None = None,
    ):
        if not client_key or not client_secret:
            raise ValueError("TikTok Research API client credentials are required")
        if proxy_url != REQUIRED_OUTBOUND_PROXY:
            raise ValueError("TikTok requests must use the configured outbound proxy")
        self.client_key = client_key
        self.client_secret = client_secret
        self.timeout_seconds = timeout_seconds
        self.opener = opener or build_opener(ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        }))
        self.clock = clock or __import__("time").monotonic
        self._access_token_value: str | None = None
        self._access_token_expires_at = 0.0

    async def query_videos(self, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._query_videos, body)

    async def list_comments(self, body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._list_comments, body)

    def _query_videos(self, body: dict[str, Any]) -> dict[str, Any]:
        self._validate_video_body(body)
        payload = self._api_payload(
            TIKTOK_VIDEO_QUERY_URL,
            TIKTOK_VIDEO_FIELDS,
            body,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TikTokApiError(
                "TikTok video query response has no data object",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        items = data.get("videos")
        cursor = data.get("cursor")
        has_more = data.get("has_more")
        search_id = data.get("search_id")
        if not isinstance(items, list) or not all(
            isinstance(item, dict) for item in items
        ):
            raise TikTokApiError(
                "TikTok video query response has no videos array",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise TikTokApiError(
                "TikTok video query cursor is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if not isinstance(has_more, bool):
            raise TikTokApiError(
                "TikTok video query has_more is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if not isinstance(search_id, str) or not search_id:
            raise TikTokApiError(
                "TikTok video query search_id is missing",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        return {
            "items": items,
            "cursor": cursor,
            "has_more": has_more,
            "search_id": search_id,
        }

    def _list_comments(self, body: dict[str, Any]) -> dict[str, Any]:
        self._validate_comment_body(body)
        payload = self._api_payload(
            TIKTOK_COMMENT_LIST_URL,
            TIKTOK_COMMENT_FIELDS,
            body,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TikTokApiError(
                "TikTok comment response has no data object",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        items = data.get("comments")
        cursor = data.get("cursor")
        has_more = data.get("has_more")
        if not isinstance(items, list) or not all(
            isinstance(item, dict) for item in items
        ):
            raise TikTokApiError(
                "TikTok comment response has no comments array",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise TikTokApiError(
                "TikTok comment cursor is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if not isinstance(has_more, bool):
            raise TikTokApiError(
                "TikTok comment has_more is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        return {"items": items, "cursor": cursor, "has_more": has_more}

    @staticmethod
    def _validate_video_body(body: dict[str, Any]) -> None:
        if not isinstance(body, dict):
            raise ValueError("TikTok video query body must be an object")
        required = {"query", "start_date", "end_date", "max_count", "cursor"}
        if not required.issubset(body) or set(body) - (required | {"search_id"}):
            raise ValueError("TikTok video query body has invalid fields")
        normalize_tiktok_query(body["query"])
        for field in ("start_date", "end_date"):
            value = body[field]
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
                raise ValueError(f"TikTok {field} must be YYYYMMDD")
            try:
                datetime.strptime(value, "%Y%m%d")
            except ValueError as error:
                raise ValueError(f"TikTok {field} is invalid") from error
        start = datetime.strptime(body["start_date"], "%Y%m%d").date()
        end = datetime.strptime(body["end_date"], "%Y%m%d").date()
        if not 1 <= (end - start).days + 1 <= 30:
            raise ValueError("TikTok video query must span 1 to 30 days")
        max_count = body["max_count"]
        cursor = body["cursor"]
        if isinstance(max_count, bool) or not isinstance(max_count, int) or not 1 <= max_count <= 100:
            raise ValueError("TikTok max_count must be between 1 and 100")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("TikTok cursor must be a non-negative integer")
        search_id = body.get("search_id")
        if search_id is not None and (
            not isinstance(search_id, str) or not search_id
        ):
            raise ValueError("TikTok search_id must be a non-empty string")

    @staticmethod
    def _validate_comment_body(body: dict[str, Any]) -> None:
        if not isinstance(body, dict):
            raise ValueError("TikTok comment request body must be an object")
        targets = [field for field in ("video_id", "comment_id") if field in body]
        if len(targets) != 1:
            raise ValueError("TikTok comment request requires exactly one video_id or comment_id")
        required = {targets[0], "max_count", "cursor"}
        if set(body) != required:
            raise ValueError("TikTok comment request body has invalid fields")
        _tiktok_id(body[targets[0]], resource=targets[0])
        max_count = body["max_count"]
        cursor = body["cursor"]
        if isinstance(max_count, bool) or not isinstance(max_count, int) or not 1 <= max_count <= 100:
            raise ValueError("TikTok max_count must be between 1 and 100")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("TikTok cursor must be a non-negative integer")

    def _api_payload(
        self,
        url: str,
        fields: tuple[str, ...],
        body: dict[str, Any],
    ) -> dict[str, Any]:
        token = self._access_token()
        try:
            return self._post_json(url, fields, body, token)
        except TikTokApiError as error:
            if error.status_code != 401:
                raise
        return self._post_json(
            url, fields, body, self._access_token(force_refresh=True)
        )

    def _access_token(self, *, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._access_token_value is not None
            and self.clock() < self._access_token_expires_at
        ):
            return self._access_token_value
        request = Request(
            TIKTOK_TOKEN_URL,
            data=urlencode([
                ("client_key", self.client_key),
                ("client_secret", self.client_secret),
                ("grant_type", "client_credentials"),
            ]).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        payload = self._open_json(request, context="OAuth")
        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        token_type = payload.get("token_type")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(token_type, str)
            or token_type.casefold() != "bearer"
        ):
            raise TikTokApiError(
                "TikTok OAuth response has invalid token fields",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError) as error:
            raise TikTokApiError(
                "TikTok OAuth response has invalid expires_in",
                status_code=None,
                api_code=None,
                retryable=False,
            ) from error
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise TikTokApiError(
                "TikTok OAuth response has invalid expires_in",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        self._access_token_value = token
        self._access_token_expires_at = self.clock() + max(0.0, lifetime - 60.0)
        return token

    def _post_json(
        self,
        url: str,
        fields: tuple[str, ...],
        body: dict[str, Any],
        token: str,
    ) -> dict[str, Any]:
        request = Request(
            url + "?" + urlencode({"fields": ",".join(fields)}),
            data=json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        payload = self._open_json(request, context="Research API")
        error = payload.get("error")
        if not isinstance(error, dict):
            raise TikTokApiError(
                "TikTok Research API response has no error envelope",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        code = error.get("code")
        if code != "ok":
            api_code = str(code) if code is not None else "unknown"
            raise TikTokApiError(
                f"TikTok Research API error: {api_code}",
                status_code=None,
                api_code=api_code,
                retryable=api_code in {"internal_error", "rate_limit_exceeded"},
            )
        return payload

    def _open_json(self, request: Request, *, context: str) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise TikTokApiError(
                f"TikTok {context} HTTP {error.code}",
                status_code=error.code,
                api_code=None,
                retryable=error.code == 429 or error.code >= 500,
                retry_after_seconds=_header_number(error.headers, "Retry-After"),
            ) from None
        except (OSError, URLError) as error:
            raise TikTokApiError(
                f"TikTok {context} connection failed: {type(error).__name__}",
                status_code=None,
                api_code=None,
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise TikTokApiError(
                f"TikTok {context} returned invalid JSON",
                status_code=None,
                api_code=None,
                retryable=False,
            ) from None
        if not isinstance(payload, dict):
            raise TikTokApiError(
                f"TikTok {context} response is not an object",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        return payload


def normalize_tiktok_query(query: dict[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the documented, non-nested video query AST."""

    if not isinstance(query, dict) or not query:
        raise ValueError("TikTok Research API query AST is required")
    if set(query) - {"and", "or", "not"}:
        raise ValueError("TikTok query contains an unsupported logical group")
    output: dict[str, Any] = {}
    clause_count = 0
    for group in ("and", "or", "not"):
        clauses = query.get(group)
        if clauses is None:
            continue
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(f"TikTok query group {group} must be a non-empty array")
        normalized_clauses = []
        for clause in clauses:
            clause_count += 1
            if not isinstance(clause, dict) or set(clause) != {
                "operation", "field_name", "field_values"
            }:
                raise ValueError("TikTok query clause has invalid fields")
            field_name = clause["field_name"]
            operation = clause["operation"]
            values = clause["field_values"]
            if (
                not isinstance(field_name, str)
                or field_name not in TIKTOK_QUERY_OPERATIONS
                or not isinstance(operation, str)
                or operation not in TIKTOK_QUERY_OPERATIONS[field_name]
            ):
                raise ValueError("TikTok query field or operation is not allowed")
            if not isinstance(values, list) or not 1 <= len(values) <= 100:
                raise ValueError("TikTok query field_values must contain 1 to 100 values")
            normalized_values: list[str | int] = []
            for value in values:
                if isinstance(value, bool):
                    raise ValueError("TikTok query values cannot be boolean")
                if field_name == "region_code":
                    text = str(value).strip().upper()
                    if not re.fullmatch(r"[A-Z]{2}", text):
                        raise ValueError("TikTok region_code query value is invalid")
                    normalized: str | int = text
                elif field_name in {"video_id", "music_id", "effect_id"}:
                    normalized = _tiktok_id(value, resource=field_name)
                elif field_name == "create_date":
                    text = str(value).strip()
                    if not re.fullmatch(r"[0-9]{8}", text):
                        raise ValueError("TikTok create_date query value must be YYYYMMDD")
                    try:
                        datetime.strptime(text, "%Y%m%d")
                    except ValueError as error:
                        raise ValueError("TikTok create_date query value is invalid") from error
                    normalized = text
                elif field_name == "video_length":
                    if not isinstance(value, int) or value < 0:
                        raise ValueError("TikTok video_length query value must be non-negative")
                    normalized = value
                else:
                    text = str(value).strip()
                    if not text or len(text) > 500:
                        raise ValueError("TikTok text query value is invalid")
                    normalized = text
                if normalized not in normalized_values:
                    normalized_values.append(normalized)
            normalized_clauses.append({
                "operation": operation,
                "field_name": field_name,
                "field_values": normalized_values,
            })
        output[group] = normalized_clauses
    if not 1 <= clause_count <= 20:
        raise ValueError("TikTok query must contain 1 to 20 clauses")
    return output


def tiktok_date_window(window_start: str, window_end: str) -> tuple[str, str]:
    """Map an exact UTC whole-day window to inclusive API date parameters."""

    def parse(value: str) -> datetime:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise ValueError("TikTok window must be an ISO-8601 datetime") from error
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("TikTok window must use UTC")
        return parsed.astimezone(timezone.utc)

    start = parse(window_start)
    end = parse(window_end)
    if start.time() != datetime.min.time() or end.time() != datetime.max.replace(
        microsecond=0
    ).time():
        raise ValueError("TikTok window must span whole UTC days (00:00:00 to 23:59:59)")
    days = (end.date() - start.date()).days + 1
    if not 1 <= days <= 30:
        raise ValueError("TikTok Research API window must contain 1 to 30 UTC days")
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _tiktok_id(value: Any, *, resource: str) -> str:
    if isinstance(value, bool):
        raise ValueError(f"TikTok {resource} id is invalid")
    text = str(value).strip() if value is not None else ""
    if not TIKTOK_ID_RE.fullmatch(text):
        raise ValueError(f"TikTok {resource} is missing a numeric id")
    return text


def _tiktok_instant(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("TikTok create_time must be an epoch timestamp")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("TikTok resource is missing create_time") from error
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("TikTok create_time is invalid")
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _video_url(video_id: str) -> str:
    return f"{TIKTOK_PLAYER_ORIGIN}/{video_id}"


def _resource_hash(resource: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(resource).encode("utf-8")).hexdigest()


def normalize_tiktok_video(
    resource: dict[str, Any],
    *,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any]:
    """Normalize one Research API video without retaining creator identity."""

    video_id = _tiktok_id(resource.get("id"), resource="video")
    description = resource.get("video_description")
    if description is not None and not isinstance(description, str):
        raise ValueError("TikTok video_description must be text")
    region_code = resource.get("region_code")
    if region_code is not None and (
        not isinstance(region_code, str)
        or not re.fullmatch(r"[A-Z]{2}", region_code)
    ):
        raise ValueError("TikTok region_code must be an ISO alpha-2 code")
    adapter_row = {
        "platform_item_id": f"video:{video_id}",
        "url": _video_url(video_id),
        "description": description or "",
        "published_at": _tiktok_instant(resource.get("create_time")),
        "collected_at": normalized_at,
        "region_hint": region_code,
        "public_metrics": {
            "view_count": resource.get("view_count"),
            "like_count": resource.get("like_count"),
            "comment_count": resource.get("comment_count"),
            "share_count": resource.get("share_count"),
        },
        "media_type": "video",
        "annotation_status": "candidate",
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": (
                "TikTok bounded Research API video query; direct creator metadata "
                "omitted; not a TikTok-wide sample."
            ),
        },
    }
    return normalize_row(
        adapter_row,
        platform="tiktok",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=_resource_hash(resource),
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )


def normalize_tiktok_comment(
    resource: dict[str, Any],
    *,
    video_id: str,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
    parent_comment_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a top-level comment or reply while preserving its parent edge."""

    clean_video_id = _tiktok_id(video_id, resource="video")
    comment_id = _tiktok_id(resource.get("id"), resource="comment")
    observed_video_id = _tiktok_id(resource.get("video_id"), resource="video")
    if observed_video_id != clean_video_id:
        raise ValueError("TikTok comment video_id does not match collection context")
    observed_parent = resource.get("parent_comment_id")
    observed_parent = (
        _tiktok_id(observed_parent, resource="parent comment")
        if observed_parent not in {None, "", 0, "0"}
        else None
    )
    clean_parent = (
        _tiktok_id(parent_comment_id, resource="parent comment")
        if parent_comment_id is not None
        else None
    )
    if observed_parent != clean_parent:
        raise ValueError("TikTok parent_comment_id does not match collection context")
    text = resource.get("text")
    if not isinstance(text, str):
        raise ValueError("TikTok comment text must be a string")
    if clean_parent is None:
        relation = "parent"
        target_item_id = f"video:{clean_video_id}"
    else:
        relation = "reply"
        target_item_id = f"comment:{clean_parent}"
    adapter_row = {
        "platform_item_id": f"comment:{comment_id}",
        "url": _video_url(clean_video_id),
        "text": text,
        "published_at": _tiktok_instant(resource.get("create_time")),
        "collected_at": normalized_at,
        "public_metrics": {
            "like_count": resource.get("like_count"),
            "reply_count": resource.get("reply_count"),
        },
        "media_type": "comment",
        "annotation_status": "candidate",
        "references": [{
            "relation": relation,
            "target_item_id": target_item_id,
            "target_url": _video_url(clean_video_id),
        }],
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": (
                "TikTok Research API public comment; direct creator metadata "
                "omitted; hierarchy retained from API identifiers."
            ),
        },
    }
    return normalize_row(
        adapter_row,
        platform="tiktok",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=_resource_hash(resource),
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )
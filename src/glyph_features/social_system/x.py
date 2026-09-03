"""X API v2 primitives for bounded, offline-verified recent search."""

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


X_API_ORIGIN = "https://api.x.com"
X_RECENT_SEARCH_URL = f"{X_API_ORIGIN}/2/tweets/search/recent"
REQUIRED_OUTBOUND_PROXY = "http://127.0.0.1:7897"
X_POST_FIELDS = "created_at,lang,public_metrics,referenced_tweets"
X_ID_RE = re.compile(r"^[0-9]{1,32}$")
X_REFERENCE_TYPES = {
    "replied_to": "reply",
    "quoted": "quote",
    "retweeted": "repost",
}


class XApiError(RuntimeError):
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


def _header_integer(headers: Any, name: str) -> int | None:
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
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


class XRecentSearchClient:
    """Minimal app-only client for X API v2 recent search."""

    def __init__(
        self,
        *,
        bearer_token: str,
        proxy_url: str,
        timeout_seconds: float = 30.0,
        opener: OpenerDirector | Any | None = None,
    ):
        if not bearer_token:
            raise ValueError("X API bearer token is required")
        if proxy_url != REQUIRED_OUTBOUND_PROXY:
            raise ValueError("X API requests must use the configured outbound proxy")
        self.bearer_token = bearer_token
        self.timeout_seconds = timeout_seconds
        self.opener = opener or build_opener(ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        }))

    async def search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._search, parameters)

    def _search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self._validate_parameters(parameters)
        request = Request(
            X_RECENT_SEARCH_URL + "?" + urlencode(parameters),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "GLYPH-social-research/0.1",
            },
            method="GET",
        )
        payload, headers = self._open_json(request)
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            api_code = str(
                first.get("title") or first.get("type") or "unknown"
            )
            raise XApiError(
                f"X API error: {api_code}",
                status_code=None,
                api_code=api_code,
                retryable=api_code.casefold() in {
                    "overcapacity",
                    "serviceunavailable",
                    "toomanyrequests",
                },
            )
        data = payload.get("data", [])
        meta = payload.get("meta")
        if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data
        ):
            raise XApiError(
                "X recent-search response has invalid data",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        if not isinstance(meta, dict):
            raise XApiError(
                "X recent-search response has no meta object",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        result_count = meta.get("result_count")
        if (
            isinstance(result_count, bool)
            or not isinstance(result_count, int)
            or result_count < 0
            or result_count != len(data)
        ):
            raise XApiError(
                "X recent-search result_count is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        next_token = meta.get("next_token")
        if next_token is not None and (
            not isinstance(next_token, str) or not next_token
        ):
            raise XApiError(
                "X recent-search next_token is invalid",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        return {
            "items": [sanitize_x_post(item) for item in data],
            "next_token": next_token,
            "result_count": result_count,
            "rate_limit": {
                "limit": _header_integer(headers, "x-rate-limit-limit"),
                "remaining": _header_integer(headers, "x-rate-limit-remaining"),
                "reset": _header_integer(headers, "x-rate-limit-reset"),
            },
        }

    @staticmethod
    def _validate_parameters(parameters: dict[str, Any]) -> None:
        if not isinstance(parameters, dict):
            raise ValueError("X recent-search parameters must be an object")
        required = {"query", "max_results", "start_time", "end_time", "tweet.fields"}
        allowed = required | {"pagination_token"}
        if not required.issubset(parameters) or set(parameters) - allowed:
            raise ValueError("X recent-search parameters have invalid fields")
        query = parameters["query"]
        if not isinstance(query, str) or not 1 <= len(query) <= 1024:
            raise ValueError("X recent-search query is invalid")
        max_results = parameters["max_results"]
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not (
            10 <= max_results <= 100
        ):
            raise ValueError("X recent-search max_results must be between 10 and 100")
        if parameters["tweet.fields"] != X_POST_FIELDS:
            raise ValueError("X recent-search tweet.fields exceeds the approved field set")
        start = _x_instant(parameters["start_time"])
        end = _x_instant(parameters["end_time"])
        if datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(
            start.replace("Z", "+00:00")
        ) > __import__("datetime").timedelta(days=7):
            raise ValueError("X recent-search window must not exceed seven days")
        token = parameters.get("pagination_token")
        if token is not None and (not isinstance(token, str) or not token):
            raise ValueError("X pagination_token must be a non-empty string")

    def _open_json(self, request: Request) -> tuple[dict[str, Any], Any]:
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = response.headers
        except HTTPError as error:
            raise XApiError(
                f"X API HTTP {error.code}",
                status_code=error.code,
                api_code=None,
                retryable=error.code == 429 or error.code >= 500,
                retry_after_seconds=_header_integer(error.headers, "Retry-After"),
            ) from None
        except (OSError, URLError) as error:
            raise XApiError(
                f"X API connection failed: {type(error).__name__}",
                status_code=None,
                api_code=None,
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise XApiError(
                "X API returned invalid JSON",
                status_code=None,
                api_code=None,
                retryable=False,
            ) from None
        if not isinstance(payload, dict):
            raise XApiError(
                "X API response is not an object",
                status_code=None,
                api_code=None,
                retryable=False,
            )
        return payload, headers


def _x_id(value: Any, *, resource: str = "post") -> str:
    if isinstance(value, bool):
        raise ValueError(f"X {resource} id is invalid")
    text = str(value).strip() if value is not None else ""
    if not X_ID_RE.fullmatch(text):
        raise ValueError(f"X {resource} is missing a numeric id")
    return text


def _x_instant(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("X post is missing created_at")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ValueError("X created_at is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("X created_at must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _public_metrics(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("X post public_metrics must be an object")
    output: dict[str, int] = {}
    for field in ("like_count", "reply_count", "retweet_count", "quote_count"):
        metric = value.get(field)
        if isinstance(metric, bool) or not isinstance(metric, int) or metric < 0:
            raise ValueError(f"X public metric {field} is invalid")
        output[field] = metric
    return output


def sanitize_x_post(post: dict[str, Any]) -> dict[str, Any]:
    """Retain only fields requested by the bounded collector."""

    if not isinstance(post, dict):
        raise ValueError("X post must be an object")
    post_id = _x_id(post.get("id"))
    text = post.get("text")
    if not isinstance(text, str):
        raise ValueError("X post text must be a string")
    language = post.get("lang")
    if language is not None and (
        not isinstance(language, str)
        or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language)
    ):
        raise ValueError("X post lang is invalid")
    references = post.get("referenced_tweets", [])
    if not isinstance(references, list):
        raise ValueError("X referenced_tweets must be an array")
    clean_references = []
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("X post reference must be an object")
        reference_type = reference.get("type")
        if reference_type not in X_REFERENCE_TYPES:
            raise ValueError("X post reference type is invalid")
        target_id = _x_id(reference.get("id"), resource="referenced post")
        clean_references.append({"type": reference_type, "id": target_id})
    return {
        "id": post_id,
        "text": text,
        "created_at": _x_instant(post.get("created_at")),
        "lang": language,
        "public_metrics": _public_metrics(post.get("public_metrics")),
        "referenced_tweets": clean_references,
    }


def normalize_x_post(
    post: dict[str, Any],
    *,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any]:
    """Normalize one recent-search post without retaining account identity."""

    resource = sanitize_x_post(post)
    post_id = resource["id"]
    references = [
        {
            "relation": X_REFERENCE_TYPES[reference["type"]],
            "target_item_id": reference["id"],
            "target_url": f"https://x.com/i/status/{reference['id']}",
        }
        for reference in resource["referenced_tweets"]
    ]
    adapter_row = {
        "platform_item_id": post_id,
        "url": f"https://x.com/i/status/{post_id}",
        "text": resource["text"],
        "published_at": resource["created_at"],
        "collected_at": normalized_at,
        "language_bcp47": resource["lang"],
        "public_metrics": resource["public_metrics"],
        "references": references,
        "annotation_status": "candidate",
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": (
                "X API v2 bounded recent-search post; account identity omitted; "
                "not an X-wide sample."
            ),
        },
    }
    return normalize_row(
        adapter_row,
        platform="x",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=hashlib.sha256(
            canonical_json(resource).encode("utf-8")
        ).hexdigest(),
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )
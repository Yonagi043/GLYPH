"""Reddit Data API adapter primitives for bounded offline-verified collection."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from tools.normalize_social_records import normalize_row
from tools.social_io import canonical_json

from .bluesky import ResearchScope


REDDIT_ORIGIN = "https://www.reddit.com"
REDDIT_API_ORIGIN = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REQUIRED_OUTBOUND_PROXY = "http://127.0.0.1:7897"
REDDIT_ACCESS_METHODS = {"subreddit_search", "subreddit_new"}
REDDIT_CONTENT_MARKERS = {"[deleted]", "[removed]"}
REDDIT_USER_AGENT_RE = re.compile(
    r"^[^:\s]+:[^:\s]+:[^\s]+ \(by /u/[A-Za-z0-9_-]{2,20}\)$"
)


class RedditApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is not None:
        return str(value)
    if hasattr(headers, "items"):
        for key, candidate in headers.items():
            if str(key).casefold() == name.casefold():
                return str(candidate)
    return None


def _header_number(headers: Any, name: str) -> float | None:
    value = _header(headers, name)
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


class RedditApiClient:
    """Minimal OAuth2 client for bounded Reddit Data API listings."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        user_agent: str,
        proxy_url: str,
        refresh_token: str | None = None,
        timeout_seconds: float = 30.0,
        opener: OpenerDirector | Any | None = None,
        clock: Any | None = None,
    ):
        if not client_id or not client_secret:
            raise ValueError("Reddit OAuth client credentials are required")
        if not REDDIT_USER_AGENT_RE.fullmatch(user_agent):
            raise ValueError("Reddit User-Agent must be unique and identify a contact account")
        if proxy_url != REQUIRED_OUTBOUND_PROXY:
            raise ValueError("Reddit requests must use the configured outbound proxy")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.opener = opener or build_opener(ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        }))
        self.clock = clock or __import__("time").monotonic
        self._access_token_value: str | None = None
        self._access_token_expires_at = 0.0

    async def request(
        self, endpoint: str, parameters: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, float | None]]:
        return await asyncio.to_thread(self._request, endpoint, parameters)

    def _request(
        self, endpoint: str, parameters: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, float | None]]:
        if not endpoint.startswith("/r/") or "?" in endpoint or "#" in endpoint:
            raise ValueError("Reddit API endpoint must be a subreddit-relative path")
        token = self._access_token()
        try:
            return self._request_listing(endpoint, parameters, token)
        except RedditApiError as error:
            if error.status_code != 401:
                raise
        return self._request_listing(
            endpoint, parameters, self._access_token(force_refresh=True)
        )

    def _access_token(self, *, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._access_token_value is not None
            and self.clock() < self._access_token_expires_at
        ):
            return self._access_token_value
        if self.refresh_token:
            form = [
                ("grant_type", "refresh_token"),
                ("refresh_token", self.refresh_token),
            ]
        else:
            form = [("grant_type", "client_credentials")]
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            REDDIT_TOKEN_URL,
            data=urlencode(form).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        payload = self._open_json(request, context="OAuth")
        token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        if not isinstance(token, str) or not token:
            raise RedditApiError(
                "Reddit OAuth response has no access_token",
                status_code=None,
                retryable=False,
            )
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError) as error:
            raise RedditApiError(
                "Reddit OAuth response has invalid expires_in",
                status_code=None,
                retryable=False,
            ) from error
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise RedditApiError(
                "Reddit OAuth response has invalid expires_in",
                status_code=None,
                retryable=False,
            )
        rotated_refresh = payload.get("refresh_token")
        if isinstance(rotated_refresh, str) and rotated_refresh:
            self.refresh_token = rotated_refresh
        self._access_token_value = token
        self._access_token_expires_at = self.clock() + max(0.0, lifetime - 30.0)
        return token

    def _request_listing(
        self,
        endpoint: str,
        parameters: dict[str, Any],
        token: str,
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, float | None]]:
        query = urlencode([
            (key, str(value).lower() if isinstance(value, bool) else str(value))
            for key, value in parameters.items()
            if value is not None
        ])
        request = Request(
            f"{REDDIT_API_ORIGIN}{endpoint}" + (f"?{query}" if query else ""),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": self.user_agent,
            },
        )
        payload, headers = self._open_json_with_headers(request, context="API")
        data = payload.get("data")
        if payload.get("kind") != "Listing" or not isinstance(data, dict):
            raise RedditApiError(
                "Reddit API response is not a Listing",
                status_code=None,
                retryable=False,
            )
        children = data.get("children")
        after = data.get("after")
        if not isinstance(children, list) or not all(
            isinstance(item, dict) for item in children
        ):
            raise RedditApiError(
                "Reddit Listing has no children array",
                status_code=None,
                retryable=False,
            )
        if after is not None and not isinstance(after, str):
            raise RedditApiError(
                "Reddit Listing after cursor is invalid",
                status_code=None,
                retryable=False,
            )
        rate_limit = {
            "used": _header_number(headers, "X-Ratelimit-Used"),
            "remaining": _header_number(headers, "X-Ratelimit-Remaining"),
            "reset": _header_number(headers, "X-Ratelimit-Reset"),
        }
        return children, after, rate_limit

    def _open_json(self, request: Request, *, context: str) -> dict[str, Any]:
        payload, _headers = self._open_json_with_headers(request, context=context)
        return payload

    def _open_json_with_headers(
        self, request: Request, *, context: str
    ) -> tuple[dict[str, Any], Any]:
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                headers = response.headers
        except HTTPError as error:
            retry_after = _header_number(error.headers, "Retry-After")
            raise RedditApiError(
                f"Reddit {context} HTTP {error.code}",
                status_code=error.code,
                retryable=error.code == 429 or error.code >= 500,
                retry_after_seconds=retry_after,
            ) from None
        except (OSError, URLError) as error:
            raise RedditApiError(
                f"Reddit {context} connection failed: {type(error).__name__}",
                status_code=None,
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise RedditApiError(
                f"Reddit {context} returned invalid JSON",
                status_code=None,
                retryable=False,
            ) from None
        if not isinstance(payload, dict):
            raise RedditApiError(
                f"Reddit {context} response is not an object",
                status_code=None,
                retryable=False,
            )
        return payload, headers


def normalize_subreddit(value: str) -> str:
    """Return a lowercase subreddit name without an r/ prefix."""

    text = value.strip()
    if text.startswith("/r/"):
        text = text[3:]
    elif text.casefold().startswith("r/"):
        text = text[2:]
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", text):
        raise ValueError("Reddit subreddit must contain 2 to 21 letters, digits, or underscores")
    return text.casefold()


def _thing_data(thing: dict[str, Any]) -> dict[str, Any] | None:
    if thing.get("kind") != "t3":
        return None
    data = thing.get("data")
    return data if isinstance(data, dict) else None


def reddit_content_status(thing: dict[str, Any]) -> str:
    """Classify a Reddit post before canonical normalization."""

    if not isinstance(thing, dict):
        return "unavailable"
    data = _thing_data(thing)
    if data is None:
        return "unavailable"
    if data.get("removed_by_category") not in {None, ""}:
        return "removed"
    text_values = {
        str(data.get(key, "")).strip().casefold()
        for key in ("title", "selftext")
    }
    if "[removed]" in text_values:
        return "removed"
    if "[deleted]" in text_values:
        return "deleted"
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        return "unavailable"
    if not any(value and value not in REDDIT_CONTENT_MARKERS for value in text_values):
        return "unavailable"
    return "available"


def reddit_created_utc(thing: dict[str, Any]) -> float:
    data = _thing_data(thing)
    if data is None:
        raise ValueError("Reddit listing child is not a post")
    value = data.get("created_utc")
    if isinstance(value, bool):
        raise ValueError("Reddit post created_utc must be an epoch timestamp")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Reddit post is missing created_utc") from error
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Reddit post created_utc is invalid")
    return timestamp


def _reddit_instant(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("Reddit post created_utc must be an epoch timestamp")
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Reddit post is missing created_utc") from error
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Reddit post created_utc is invalid")
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _reddit_post_url(data: dict[str, Any], post_id: str) -> str:
    permalink = data.get("permalink")
    if isinstance(permalink, str) and permalink.startswith("/"):
        parsed = urlparse(permalink)
        if not parsed.netloc and not parsed.query and not parsed.fragment:
            return REDDIT_ORIGIN + permalink
    return f"{REDDIT_ORIGIN}/comments/{post_id}"


def normalize_reddit_post(
    thing: dict[str, Any],
    *,
    subreddit: str,
    access_method: str,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any] | None:
    """Normalize one available Reddit post without retaining author identity."""

    if access_method not in REDDIT_ACCESS_METHODS:
        raise ValueError("Invalid Reddit access method")
    if reddit_content_status(thing) != "available":
        return None
    data = _thing_data(thing)
    if data is None:
        raise ValueError("Reddit listing child is not a post")
    observed_subreddit = data.get("subreddit")
    if not isinstance(observed_subreddit, str) or (
        observed_subreddit.casefold() != subreddit.casefold()
    ):
        raise ValueError("Reddit post subreddit does not match its collection context")
    post_id = str(data["id"]).strip()
    fullname = data.get("name")
    platform_item_id = (
        fullname.strip()
        if isinstance(fullname, str) and fullname.strip()
        else f"t3_{post_id}"
    )
    if not platform_item_id.startswith("t3_"):
        raise ValueError("Reddit post fullname must use the t3_ prefix")
    notes = (
        f"Reddit Data API bounded {'subreddit search' if access_method == 'subreddit_search' else 'new listing'}; "
        f"subreddit=r/{subreddit}; query={scope.exact_query or ' OR '.join(scope.keywords)}; "
        "direct author metadata omitted; not a Reddit-wide sample."
    )
    adapter_row = {
        "platform_item_id": platform_item_id,
        "url": _reddit_post_url(data, post_id),
        "title": data.get("title"),
        "selftext": data.get("selftext"),
        "published_at": _reddit_instant(data.get("created_utc")),
        "collected_at": normalized_at,
        "public_metrics": {
            "ups": data.get("ups"),
            "score": data.get("score"),
            "num_comments": data.get("num_comments"),
        },
        "media_type": "social_post",
        "annotation_status": "candidate",
        "governance": {
            "author_handling": "omitted",
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": notes,
        },
    }
    raw_hash = hashlib.sha256(canonical_json(thing).encode("utf-8")).hexdigest()
    return normalize_row(
        adapter_row,
        platform="reddit",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=raw_hash,
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )

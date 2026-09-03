"""YouTube Data API v3 adapter for bounded social-narrative collection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from tools.normalize_social_records import normalize_row
from tools.social_io import canonical_json

from .bluesky import ResearchScope


YOUTUBE_API_ENDPOINT = "https://www.googleapis.com/youtube/v3"
YOUTUBE_QUOTA_COSTS = {
    "search.list": 1,
    "videos.list": 1,
    "channels.list": 1,
    "commentThreads.list": 1,
    "comments.list": 1,
}
LEGACY_YOUTUBE_QUOTA_COSTS = {**YOUTUBE_QUOTA_COSTS, "search.list": 100}


class YouTubeApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        reason: str | None,
        retryable: bool,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.retryable = retryable


class YouTubeApiClient:
    """Minimal async YouTube Data API v3 client with no credential logging."""

    def __init__(
        self,
        api_key: str,
        *,
        proxy_url: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        if not api_key.strip():
            raise ValueError("GLYPH_YOUTUBE_API_KEY 未配置")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        self.opener = build_opener(ProxyHandler(proxies))

    async def request(self, resource: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._request, resource, parameters)

    def _request(self, resource: str, parameters: dict[str, Any]) -> dict[str, Any]:
        query = urlencode([
            (key, str(value)) for key, value in parameters.items() if value is not None
        ])
        request = Request(
            f"{YOUTUBE_API_ENDPOINT}/{resource}?{query}",
            headers={
                "Accept": "application/json",
                "X-Goog-Api-Key": self.api_key,
            },
        )
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            reason = None
            message = f"YouTube API HTTP {error.code}"
            try:
                error_payload = json.loads(body).get("error", {})
                if isinstance(error_payload, dict):
                    message = str(error_payload.get("message") or message)
                    details = error_payload.get("errors") or []
                    if details and isinstance(details[0], dict):
                        reason = str(details[0].get("reason") or "") or None
            except (AttributeError, json.JSONDecodeError):
                pass
            raise YouTubeApiError(
                message,
                status_code=error.code,
                reason=reason,
                retryable=error.code == 429 or error.code >= 500,
            ) from None
        except (OSError, URLError) as error:
            raise YouTubeApiError(
                f"YouTube API connection failed: {type(error).__name__}",
                status_code=None,
                reason=None,
                retryable=True,
            ) from None
        except json.JSONDecodeError as error:
            raise YouTubeApiError(
                "YouTube API returned invalid JSON",
                status_code=None,
                reason=None,
                retryable=False,
            ) from None
        if not isinstance(payload, dict):
            raise YouTubeApiError(
                "YouTube API response is not an object",
                status_code=None,
                reason=None,
                retryable=False,
            )
        return payload


def _resource_hash(resource: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(resource).encode("utf-8")).hexdigest()


def _video_url(video_id: str, comment_id: str | None = None) -> str:
    parameters = [("v", video_id)]
    if comment_id is not None:
        parameters.append(("lc", comment_id))
    return "https://www.youtube.com/watch?" + urlencode(parameters)


def _snippet(resource: dict[str, Any]) -> dict[str, Any]:
    snippet = resource.get("snippet")
    if not isinstance(snippet, dict):
        raise ValueError("YouTube resource is missing snippet")
    return snippet


def normalize_youtube_video(
    resource: dict[str, Any],
    *,
    channel: dict[str, Any] | None,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any]:
    """Normalize one videos.list resource without retaining channel identity."""

    video_id = resource.get("id")
    if not isinstance(video_id, str) or not video_id:
        raise ValueError("YouTube video is missing id")
    snippet = _snippet(resource)
    statistics = resource.get("statistics")
    if not isinstance(statistics, dict):
        statistics = {}
    adapter_row = {
        "platform_item_id": f"video:{video_id}",
        "url": _video_url(video_id),
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "published_at": snippet.get("publishedAt"),
        "collected_at": normalized_at,
        "language_bcp47": snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage"),
        "public_metrics": statistics,
        "media_type": "video",
        "annotation_status": "candidate",
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": (
                "YouTube Data API v3 bounded query sample; channel metadata "
                f"{'is' if channel is not None else 'is not'} retained in local raw evidence."
            ),
        },
    }
    return normalize_row(
        adapter_row,
        platform="youtube",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=_resource_hash(resource),
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )


def normalize_youtube_comment(
    resource: dict[str, Any],
    *,
    video_id: str,
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
    parent_comment_id: str | None = None,
    reply_count: int | None = None,
) -> dict[str, Any]:
    """Normalize one comment resource while omitting direct author metadata."""

    comment_id = resource.get("id")
    if not isinstance(comment_id, str) or not comment_id:
        raise ValueError("YouTube comment is missing id")
    snippet = _snippet(resource)
    observed_video_id = snippet.get("videoId")
    if isinstance(observed_video_id, str) and observed_video_id != video_id:
        raise ValueError("YouTube comment videoId does not match its collection context")
    if parent_comment_id is None:
        target_id = f"video:{video_id}"
        target_url = _video_url(video_id)
        relation = "parent"
    else:
        target_id = f"comment:{parent_comment_id}"
        target_url = _video_url(video_id, parent_comment_id)
        relation = "reply"
    metrics = {"likeCount": snippet.get("likeCount")}
    if reply_count is not None:
        metrics["commentCount"] = reply_count
    adapter_row = {
        "platform_item_id": f"comment:{comment_id}",
        "url": _video_url(video_id, comment_id),
        "text": snippet.get("textOriginal") or snippet.get("textDisplay") or "",
        "published_at": snippet.get("publishedAt"),
        "updated_at": snippet.get("updatedAt"),
        "collected_at": normalized_at,
        "public_metrics": metrics,
        "media_type": "comment",
        "annotation_status": "candidate",
        "references": [{
            "relation": relation,
            "target_item_id": target_id,
            "target_url": target_url,
        }],
        "governance": {
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": "YouTube Data API v3 public comment; direct author metadata omitted.",
        },
    }
    return normalize_row(
        adapter_row,
        platform="youtube",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=_resource_hash(resource),
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or " OR ".join(scope.keywords),
        author_salt=None,
    )
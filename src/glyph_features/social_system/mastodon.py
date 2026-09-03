"""Mastodon REST API adapter primitives for bounded public collection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

from tools.normalize_social_records import _normalization_hash_payload, normalize_row
from tools.social_io import canonical_json

from .bluesky import ResearchScope


PUBLIC_VISIBILITIES = {"public", "unlisted"}
_BLOCK_TAGS = {
    "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre",
}


class MastodonApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        retryable: bool,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _next_max_id(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        match = re.match(r'\s*<([^>]+)>\s*;\s*rel="?next"?', part)
        if match is None:
            continue
        values = parse_qs(urlparse(match.group(1)).query).get("max_id")
        if values and values[0]:
            return values[0]
    return None


class MastodonApiClient:
    """Minimal async client for bounded public instance API requests."""

    def __init__(
        self,
        *,
        access_tokens: dict[str, str] | None = None,
        proxy_url: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.access_tokens = {
            normalize_instance(instance): token
            for instance, token in (access_tokens or {}).items()
            if token
        }
        self.timeout_seconds = timeout_seconds
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        self.opener = build_opener(ProxyHandler(proxies))

    async def request(
        self, instance: str, endpoint: str, parameters: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        return await asyncio.to_thread(
            self._request, normalize_instance(instance), endpoint, parameters
        )

    def _request(
        self, instance: str, endpoint: str, parameters: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not endpoint.startswith("/api/") or "?" in endpoint or "#" in endpoint:
            raise ValueError("Mastodon API endpoint must be an instance-relative API path")
        query = urlencode([
            (key, str(value).lower() if isinstance(value, bool) else str(value))
            for key, value in parameters.items()
            if value is not None
        ])
        headers = {"Accept": "application/json"}
        token = self.access_tokens.get(instance)
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"https://{instance}{endpoint}" + (f"?{query}" if query else ""),
            headers=headers,
        )
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
                next_page_token = _next_max_id(response.headers.get("Link"))
        except HTTPError as error:
            message = f"Mastodon API HTTP {error.code}"
            try:
                payload = json.loads(error.read().decode("utf-8", errors="replace"))
                if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                    message = payload["error"]
            except json.JSONDecodeError:
                pass
            raise MastodonApiError(
                message,
                status_code=error.code,
                retryable=error.code == 429 or error.code >= 500,
            ) from None
        except (OSError, URLError) as error:
            raise MastodonApiError(
                f"Mastodon API connection failed: {type(error).__name__}",
                status_code=None,
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise MastodonApiError(
                "Mastodon API returned invalid JSON",
                status_code=None,
                retryable=False,
            ) from None
        if endpoint == "/api/v2/search":
            if not isinstance(payload, dict) or not isinstance(payload.get("statuses"), list):
                raise MastodonApiError(
                    "Mastodon search response has no statuses list",
                    status_code=None,
                    retryable=False,
                )
            payload = payload["statuses"]
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise MastodonApiError(
                "Mastodon API response is not a status list",
                status_code=None,
                retryable=False,
            )
        return payload, next_page_token


class _MastodonHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        folded = tag.casefold()
        if folded in {"script", "style"}:
            self.suppressed_depth += 1
        elif self.suppressed_depth == 0 and folded in _BLOCK_TAGS | {"br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        folded = tag.casefold()
        if folded in {"script", "style"} and self.suppressed_depth:
            self.suppressed_depth -= 1
        elif self.suppressed_depth == 0 and folded in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.suppressed_depth == 0:
            self.parts.append(data)


def clean_mastodon_html(value: Any) -> str:
    """Convert API-visible status HTML to stable plain text without link targets."""

    if not isinstance(value, str):
        raise ValueError("Mastodon status content must be HTML text")
    parser = _MastodonHtmlParser()
    parser.feed(value)
    parser.close()
    lines = [
        re.sub(r"[\t\f\v ]+", " ", line).strip()
        for line in "".join(parser.parts).replace("\r", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line)


def normalize_instance(value: str) -> str:
    """Return a lowercase instance authority without paths, queries, or credentials."""

    text = value.strip()
    if not text:
        raise ValueError("Mastodon instance is required")
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Mastodon instance must be an HTTPS hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Mastodon instance must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Mastodon instance must not contain a path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Mastodon instance has an invalid port") from error
    host = parsed.hostname.casefold().rstrip(".")
    return f"{host}:{port}" if port is not None and port != 443 else host


def _public_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return value.strip()


def canonical_federated_account(account: dict[str, Any]) -> str:
    """Normalize an API account to ``username@origin`` for local raw audit only."""

    acct = account.get("acct")
    if not isinstance(acct, str) or not acct.strip():
        raise ValueError("Mastodon account is missing acct")
    clean_acct = acct.strip().lstrip("@").casefold()
    if "@" in clean_acct:
        username, instance = clean_acct.rsplit("@", 1)
        if not username or not instance:
            raise ValueError("Mastodon account acct is invalid")
        return f"{username}@{normalize_instance(instance)}"
    account_url = _public_url(account.get("url"))
    if account_url is None:
        raise ValueError("local Mastodon account is missing its origin URL")
    origin = urlparse(account_url).hostname
    if origin is None:
        raise ValueError("Mastodon account URL is invalid")
    return f"{clean_acct}@{origin.casefold().rstrip('.')}"


def _canonical_status_identity(status: dict[str, Any], observed_instance: str) -> str:
    canonical = _public_url(status.get("uri")) or _public_url(status.get("url"))
    if canonical is None:
        local_id = status.get("id")
        if not isinstance(local_id, str) or not local_id:
            raise ValueError("Mastodon status is missing canonical URL and id")
        return f"status:{normalize_instance(observed_instance)}:{local_id}"
    parsed = urlparse(canonical)
    status_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not status_id:
        raise ValueError("Mastodon status canonical URL has no status id")
    return f"status:{parsed.hostname.casefold().rstrip('.')}:{status_id}"


def _reply_reference(
    status: dict[str, Any], observed_instance: str
) -> list[dict[str, Any]]:
    parent_id = status.get("in_reply_to_id")
    if not isinstance(parent_id, str) or not parent_id:
        return []
    return [{
        "relation": "reply",
        "target_item_id": f"status:{normalize_instance(observed_instance)}:{parent_id}",
        "target_url": None,
    }]


def normalize_mastodon_status(
    status: dict[str, Any],
    *,
    observed_instance: str,
    hashtag: str,
    access_method: str = "hashtag_timeline",
    scope: ResearchScope,
    collection_run_id: str,
    normalized_at: str,
) -> dict[str, Any] | None:
    """Normalize one public status while keeping account identity in raw evidence."""

    instance = normalize_instance(observed_instance)
    visibility = status.get("visibility")
    if visibility not in PUBLIC_VISIBILITIES:
        return None
    content = clean_mastodon_html(status.get("content"))
    spoiler = clean_mastodon_html(status.get("spoiler_text") or "")
    text = "\n".join(part for part in (spoiler, content) if part)
    created_at = status.get("created_at")
    language = status.get("language")
    languages = [language] if isinstance(language, str) and language else []
    if not isinstance(created_at, str):
        raise ValueError("Mastodon status is missing created_at")
    if not scope.matches(text, languages, created_at):
        return None
    account = status.get("account")
    if not isinstance(account, dict):
        raise ValueError("Mastodon status is missing account")
    canonical_federated_account(account)
    canonical_url = _public_url(status.get("url")) or _public_url(status.get("uri"))
    if canonical_url is None:
        raise ValueError("Mastodon status is missing a public URL")

    platform_item_id = _canonical_status_identity(status, instance)
    if access_method == "hashtag_timeline":
        access_note = (
            "bounded hashtag timeline; "
            f"hashtag=#{hashtag.lstrip('#')}"
        )
    elif access_method == "search_statuses":
        access_note = (
            "bounded status search; "
            f"query={scope.exact_query or hashtag}; "
            "availability and ranking are instance-dependent"
        )
    else:
        raise ValueError("Invalid Mastodon access method")

    adapter_row = {
        "platform_item_id": platform_item_id,
        "url": canonical_url,
        "text": text,
        "published_at": created_at,
        "updated_at": status.get("edited_at"),
        "collected_at": normalized_at,
        "language_bcp47": language,
        "public_metrics": {
            "like_count": status.get("favourites_count"),
            "comment_count": status.get("replies_count"),
            "share_count": status.get("reblogs_count"),
        },
        "engagement_is_public": True,
        "media_type": "social_post",
        "annotation_status": "candidate",
        "references": _reply_reference(status, instance),
        "governance": {
            "author_handling": "local_only",
            "raw_payload_status": "local_only",
            "redistribution_status": "derived_only",
            "terms_checked_at": None,
            "notes": (
                f"Mastodon REST API {access_note}; "
                f"observed_instance={instance}; "
                f"visibility={visibility}; not a Mastodon-wide sample."
            ),
        },
    }
    raw_envelope = {
        "observed_instance": instance,
        "hashtag": hashtag.lstrip("#"),
        "status": status,
    }
    raw_hash = hashlib.sha256(
        canonical_json(raw_envelope).encode("utf-8")
    ).hexdigest()
    record = normalize_row(
        adapter_row,
        platform="mastodon",
        source_kind="official_api",
        collection_run_id=collection_run_id,
        input_sha256=raw_hash,
        normalized_at=normalized_at,
        query_id=scope.query_id,
        query_text=scope.exact_query or f"#{hashtag.lstrip('#')}",
        author_salt=None,
    )
    record["governance"]["author_handling"] = "local_only"
    record["normalization"]["record_sha256"] = hashlib.sha256(
        canonical_json(_normalization_hash_payload(record)).encode("utf-8")
    ).hexdigest()
    return record
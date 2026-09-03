"""Resumable Bluesky Jetstream collection loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from websockets.asyncio.client import connect as websocket_connect

from .bluesky import event_cursor, subscription_url
from .mastodon import MastodonApiClient, MastodonApiError
from .reddit import (
    RedditApiClient,
    RedditApiError,
    reddit_content_status,
    reddit_created_utc,
)
from .service import SocialNarrativeService
from .storage import XBillingGateError, XBudgetExceeded
from .tiktok import TikTokApiError, TikTokResearchClient
from .youtube import YouTubeApiClient, YouTubeApiError
from .x import XApiError, XRecentSearchClient


class TikTokQuotaExhausted(RuntimeError):
    pass


class BlueskyCollector:
    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        proxy_url: str | None = None,
        connection_factory: Callable[..., Any] = websocket_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.service = service
        self.proxy_url = proxy_url
        self.connection_factory = connection_factory
        self.sleep = sleep

    async def run(self, collection_run_id: str, *, max_items: int) -> dict[str, Any]:
        inserted = 0
        retry_attempt = 0
        try:
            while inserted < max_items:
                cursor = self.service.cursor()
                url = subscription_url(cursor)
                try:
                    connection_options = {
                        "open_timeout": 15,
                        "ping_interval": 20,
                        "ping_timeout": 20,
                        "max_size": 2 * 1024 * 1024,
                    }
                    if self.proxy_url is not None:
                        connection_options["proxy"] = self.proxy_url
                    async with self.connection_factory(url, **connection_options) as stream:
                        retry_attempt = 0
                        async for message in stream:
                            try:
                                event = json.loads(message)
                                if not isinstance(event, dict):
                                    raise ValueError("Jetstream message is not a JSON object")
                                if self.service.process_event(collection_run_id, event):
                                    inserted += 1
                                    if inserted >= max_items:
                                        self.service.finish_run(collection_run_id, "completed")
                                        return {"status": "completed", "inserted": inserted}
                            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                                payload = message.encode("utf-8") if isinstance(message, str) else bytes(message)
                                parsed_cursor = None
                                if "event" in locals() and isinstance(event, dict):
                                    try:
                                        parsed_cursor = event_cursor(event)
                                    except ValueError:
                                        pass
                                self.service.record_error(
                                    collection_run_id,
                                    cursor=parsed_cursor,
                                    error_code="event_error",
                                    message=f"{type(error).__name__}: {error}",
                                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                                    retryable=False,
                                )
                    raise ConnectionError("Jetstream connection closed")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.service.record_error(
                        collection_run_id,
                        cursor=self.service.cursor(),
                        error_code="connection_error",
                        message=f"{type(error).__name__}: {error}",
                        payload_sha256=None,
                        retryable=True,
                    )
                    delay = min(30.0, float(2**retry_attempt))
                    retry_attempt = min(retry_attempt + 1, 5)
                    await self.sleep(delay)
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            return {"status": "stopped", "inserted": inserted}
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise

        self.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": inserted}


class MastodonCollector:
    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        access_tokens: dict[str, str] | None = None,
        proxy_url: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
    ):
        self.service = service
        self.client = client or MastodonApiClient(
            access_tokens=access_tokens,
            proxy_url=proxy_url,
        )
        self.sleep = sleep
        self.max_retries = max_retries

    async def _request(
        self,
        instance: str,
        endpoint: str,
        parameters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.client.request(instance, endpoint, parameters)
            except MastodonApiError as error:
                if not error.retryable or attempt >= self.max_retries:
                    raise
                await self.sleep(min(30.0, float(2**attempt)))
        raise RuntimeError("unreachable Mastodon retry state")

    @staticmethod
    def _error_code(error: MastodonApiError) -> str:
        if error.status_code in {401, 403}:
            return "mastodon_instance_authentication"
        if error.status_code == 429:
            return "mastodon_instance_rate_limited"
        if error.status_code is not None:
            return f"mastodon_instance_http_{error.status_code}"
        return "mastodon_instance_connection"

    async def run(
        self, collection_run_id: str, *, max_items: int
    ) -> dict[str, Any]:
        inserted = 0
        sightings = 0
        instances_completed = 0
        instances_failed = 0
        try:
            run = self.service.get_run(collection_run_id)
            scope_id = run.get("scope_id")
            if run.get("platform") != "mastodon" or not isinstance(scope_id, str):
                raise KeyError(collection_run_id)
            scope_rows = self.service.run_scope_snapshots(collection_run_id)
            if not scope_rows:
                raise ValueError("Mastodon run 没有冻结 query")
            saved_states = {
                (row["query_id"], row["observed_instance"]): row
                for row in self.service.mastodon_instance_states(collection_run_id)
            }
            for scope_row in scope_rows:
                query_id = scope_row["query_id"]
                options = scope_row.get("platform_options")
                if not isinstance(options, dict):
                    raise ValueError("Mastodon query 缺少冻结平台配置")
                access_method = options["access_method"]
                page_size = int(options["page_size"])
                max_pages = int(options["max_pages_per_instance"])
                request_delay = float(options["request_delay_seconds"])
                query_text = str(scope_row["exact_query"])
                hashtag = query_text.lstrip("#")
                if access_method == "hashtag_timeline":
                    endpoint = f"/api/v1/timelines/tag/{quote(hashtag, safe='')}"
                else:
                    endpoint = "/api/v2/search"
                for instance in options["instances"]:
                    if inserted >= max_items:
                        break
                    saved_state = saved_states.get((query_id, instance))
                    if saved_state is not None and saved_state["status"] == "completed":
                        instances_completed += 1
                        continue
                    pages_fetched = int(
                        saved_state["pages_fetched"] if saved_state is not None else 0
                    )
                    statuses_seen = int(
                        saved_state["statuses_seen"] if saved_state is not None else 0
                    )
                    instance_sightings = int(
                        saved_state["sightings_count"] if saved_state is not None else 0
                    )
                    next_page_token = (
                        saved_state["next_page_token"] if saved_state is not None else None
                    )
                    max_status_id_candidate = (
                        saved_state["max_status_id_candidate"]
                        if saved_state is not None else None
                    )
                    self.service.save_mastodon_instance_state(
                        collection_run_id,
                        query_id,
                        instance,
                        access_method=access_method,
                        next_page_token=next_page_token,
                        max_status_id_candidate=max_status_id_candidate,
                        pages_fetched=pages_fetched,
                        statuses_seen=statuses_seen,
                        sightings_count=instance_sightings,
                        status="running",
                    )
                    instance_truncated = False
                    try:
                        while pages_fetched < max_pages and inserted < max_items:
                            parameters: dict[str, Any] = {
                                "limit": page_size,
                                "max_id": next_page_token,
                            }
                            since_id = self.service.mastodon_scope_high_watermark(
                                scope_id, query_id, instance
                            )
                            if since_id is not None and next_page_token is None:
                                parameters["since_id"] = since_id
                            if access_method == "search_statuses":
                                parameters.update({
                                    "q": query_text,
                                    "type": "statuses",
                                    "resolve": False,
                                })
                            statuses, next_page_token = await self._request(
                                instance, endpoint, parameters
                            )
                            pages_fetched += 1
                            statuses_seen += len(statuses)
                            for status_index, status in enumerate(statuses):
                                local_status_id = status.get("id")
                                if isinstance(local_status_id, str) and local_status_id:
                                    if max_status_id_candidate is None:
                                        max_status_id_candidate = local_status_id
                                    else:
                                        try:
                                            max_status_id_candidate = str(max(
                                                int(max_status_id_candidate),
                                                int(local_status_id),
                                            ))
                                        except ValueError:
                                            max_status_id_candidate = max(
                                                max_status_id_candidate, local_status_id
                                            )
                                try:
                                    was_inserted, sighting_inserted = (
                                        self.service.process_mastodon_status(
                                            collection_run_id,
                                            status,
                                            observed_instance=instance,
                                            hashtag=hashtag,
                                            query_id=query_id,
                                        )
                                    )
                                except (TypeError, ValueError) as error:
                                    self.service.record_error(
                                        collection_run_id,
                                        cursor=None,
                                        error_code="mastodon_status_invalid",
                                        message=f"{instance}: {error}",
                                        retryable=False,
                                    )
                                    continue
                                inserted += int(was_inserted)
                                sightings += int(sighting_inserted)
                                instance_sightings += int(sighting_inserted)
                                if inserted >= max_items:
                                    instance_truncated = (
                                        status_index < len(statuses) - 1
                                        or next_page_token is not None
                                    )
                                    break
                            self.service.save_mastodon_instance_state(
                                collection_run_id,
                                query_id,
                                instance,
                                access_method=access_method,
                                next_page_token=next_page_token,
                                max_status_id_candidate=max_status_id_candidate,
                                pages_fetched=pages_fetched,
                                statuses_seen=statuses_seen,
                                sightings_count=instance_sightings,
                                status="running",
                            )
                            if not next_page_token or inserted >= max_items:
                                break
                            if request_delay:
                                await self.sleep(request_delay)
                        if (
                            max_status_id_candidate is not None
                            and not instance_truncated
                        ):
                            self.service.save_mastodon_scope_high_watermark(
                                scope_id,
                                query_id,
                                instance,
                                max_status_id_candidate,
                            )
                        self.service.save_mastodon_instance_state(
                            collection_run_id,
                            query_id,
                            instance,
                            access_method=access_method,
                            next_page_token=next_page_token,
                            max_status_id_candidate=max_status_id_candidate,
                            pages_fetched=pages_fetched,
                            statuses_seen=statuses_seen,
                            sightings_count=instance_sightings,
                            status="completed",
                        )
                        instances_completed += 1
                    except MastodonApiError as error:
                        error_code = self._error_code(error)
                        message = f"{instance}: {error}"
                        self.service.save_mastodon_instance_state(
                            collection_run_id,
                            query_id,
                            instance,
                            access_method=access_method,
                            next_page_token=next_page_token,
                            max_status_id_candidate=max_status_id_candidate,
                            pages_fetched=pages_fetched,
                            statuses_seen=statuses_seen,
                            sightings_count=instance_sightings,
                            status="failed",
                            error_code=error_code,
                            error_message=message,
                        )
                        self.service.record_error(
                            collection_run_id,
                            cursor=None,
                            error_code=error_code,
                            message=message,
                            retryable=error.retryable,
                        )
                        instances_failed += 1
            final_status = "completed" if instances_completed else "failed"
            self.service.finish_run(collection_run_id, final_status)
            return {
                "status": final_status,
                "inserted": inserted,
                "instances_completed": instances_completed,
                "instances_failed": instances_failed,
                "sightings": sightings,
            }
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            return {
                "status": "stopped",
                "inserted": inserted,
                "instances_completed": instances_completed,
                "instances_failed": instances_failed,
                "sightings": sightings,
            }
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise


class RedditCollector:
    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        user_agent: str | None = None,
        proxy_url: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
    ):
        self.service = service
        if client is None:
            self.client = RedditApiClient(
                client_id=client_id or "",
                client_secret=client_secret or "",
                refresh_token=refresh_token,
                user_agent=user_agent or "",
                proxy_url=proxy_url or "",
            )
        else:
            self.client = client
        self.sleep = sleep
        self.max_retries = max_retries

    async def _request(
        self, endpoint: str, parameters: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], str | None, dict[str, float | None]]:
        for attempt in range(self.max_retries + 1):
            try:
                return await self.client.request(endpoint, parameters)
            except RedditApiError as error:
                if not error.retryable or attempt >= self.max_retries:
                    raise
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else min(30.0, float(2**attempt))
                )
                await self.sleep(delay)
        raise RuntimeError("unreachable Reddit retry state")

    @staticmethod
    def _error_code(error: RedditApiError) -> str:
        if error.status_code in {401, 403}:
            return "reddit_authentication"
        if error.status_code == 404:
            return "reddit_subreddit_unavailable"
        if error.status_code == 429:
            return "reddit_rate_limited"
        if error.status_code is not None:
            return f"reddit_http_{error.status_code}"
        return "reddit_connection"

    async def run(
        self, collection_run_id: str, *, max_items: int
    ) -> dict[str, Any]:
        inserted = 0
        unavailable = 0
        pages_fetched_total = 0
        subreddits_completed = 0
        subreddits_failed = 0
        try:
            run = self.service.get_run(collection_run_id)
            if run.get("platform") != "reddit" or not isinstance(run.get("scope_id"), str):
                raise KeyError(collection_run_id)
            saved_states = {
                (row["query_id"], row["partition_key"]): row
                for row in self.service.api_collection_states(collection_run_id)
            }
            for scope_row in self.service.run_scope_snapshots(collection_run_id):
                query_id = scope_row["query_id"]
                options = scope_row.get("platform_options")
                if not isinstance(options, dict):
                    raise ValueError("Reddit query 缺少冻结平台配置")
                access_method = options["access_method"]
                max_pages = int(options["max_pages_per_subreddit"])
                page_size = int(options["page_size"])
                request_delay = float(options["request_delay_seconds"])
                for subreddit in options["subreddits"]:
                    if inserted >= max_items:
                        break
                    saved = saved_states.get((query_id, subreddit))
                    if saved is not None and saved["status"] == "completed":
                        subreddits_completed += 1
                        continue
                    state = dict(saved["state"] if saved is not None else {})
                    pages_fetched = int(state.get("pages_fetched", 0))
                    items_seen = int(state.get("items_seen", 0))
                    unavailable_count = int(state.get("unavailable_count", 0))
                    next_page_token = state.get("next_page_token")
                    incremental = options["sort"] == "new"
                    scope_state = self.service.api_scope_state(
                        run["scope_id"], query_id, subreddit
                    ) if incremental else None
                    previous_high_watermark = (
                        float(scope_state["max_created_utc"])
                        if isinstance(scope_state, dict)
                        and isinstance(scope_state.get("max_created_utc"), (int, float))
                        else None
                    )
                    max_created_utc = previous_high_watermark
                    reached_high_watermark = False
                    truncated_within_page = False
                    self.service.save_api_collection_state(
                        collection_run_id,
                        "reddit",
                        query_id,
                        subreddit,
                        {
                            "items_seen": items_seen,
                            "last_rate_limit": state.get("last_rate_limit"),
                            "next_page_token": next_page_token,
                            "pages_fetched": pages_fetched,
                            "unavailable_count": unavailable_count,
                        },
                        status="running",
                    )
                    try:
                        while pages_fetched < max_pages and inserted < max_items:
                            endpoint = (
                                f"/r/{quote(subreddit, safe='')}/search"
                                if access_method == "subreddit_search"
                                else f"/r/{quote(subreddit, safe='')}/new"
                            )
                            parameters: dict[str, Any] = {
                                "after": next_page_token,
                                "limit": page_size,
                            }
                            if access_method == "subreddit_search":
                                parameters.update({
                                    "q": scope_row["exact_query"],
                                    "restrict_sr": True,
                                    "sort": options["sort"],
                                    "t": options["time_filter"],
                                })
                            children, next_page_token, rate_limit = await self._request(
                                endpoint, parameters
                            )
                            pages_fetched += 1
                            pages_fetched_total += 1
                            items_seen += len(children)
                            for item_index, thing in enumerate(children):
                                status = reddit_content_status(thing)
                                if status != "available":
                                    unavailable += 1
                                    unavailable_count += 1
                                created_utc = None
                                try:
                                    created_utc = reddit_created_utc(thing)
                                except ValueError:
                                    pass
                                if status == "available" and created_utc is not None:
                                    max_created_utc = (
                                        created_utc
                                        if max_created_utc is None
                                        else max(max_created_utc, created_utc)
                                    )
                                at_or_before_high_watermark = (
                                    incremental
                                    and previous_high_watermark is not None
                                    and created_utc is not None
                                    and created_utc <= previous_high_watermark
                                )
                                try:
                                    was_inserted = self.service.process_reddit_post(
                                        collection_run_id,
                                        thing,
                                        subreddit=subreddit,
                                        query_id=query_id,
                                        minimum_created_utc=(
                                            previous_high_watermark if incremental else None
                                        ),
                                    )
                                except (TypeError, ValueError) as error:
                                    self.service.record_error(
                                        collection_run_id,
                                        cursor=None,
                                        error_code="reddit_item_invalid",
                                        message=f"r/{subreddit}: {error}",
                                        payload_sha256=hashlib.sha256(
                                            json.dumps(
                                                thing,
                                                ensure_ascii=False,
                                                sort_keys=True,
                                                separators=(",", ":"),
                                            ).encode("utf-8")
                                        ).hexdigest(),
                                        retryable=False,
                                    )
                                    continue
                                inserted += int(was_inserted)
                                if at_or_before_high_watermark:
                                    reached_high_watermark = True
                                    next_page_token = None
                                    break
                                if inserted >= max_items:
                                    truncated_within_page = (
                                        item_index < len(children) - 1
                                        or next_page_token is not None
                                    )
                                    break
                            state = {
                                "items_seen": items_seen,
                                "last_rate_limit": rate_limit,
                                "next_page_token": next_page_token,
                                "pages_fetched": pages_fetched,
                                "unavailable_count": unavailable_count,
                            }
                            self.service.save_api_collection_state(
                                collection_run_id,
                                "reddit",
                                query_id,
                                subreddit,
                                state,
                                status="running",
                            )
                            if (
                                reached_high_watermark
                                or not next_page_token
                                or inserted >= max_items
                            ):
                                break
                            if request_delay:
                                await self.sleep(request_delay)
                        if (
                            incremental
                            and max_created_utc is not None
                            and not truncated_within_page
                            and (reached_high_watermark or next_page_token is None)
                        ):
                            self.service.save_api_scope_state(
                                run["scope_id"],
                                "reddit",
                                query_id,
                                subreddit,
                                {"max_created_utc": max_created_utc},
                            )
                        self.service.save_api_collection_state(
                            collection_run_id,
                            "reddit",
                            query_id,
                            subreddit,
                            state,
                            status="completed",
                        )
                        subreddits_completed += 1
                    except RedditApiError as error:
                        error_code = self._error_code(error)
                        message = f"r/{subreddit}: {error}"
                        self.service.save_api_collection_state(
                            collection_run_id,
                            "reddit",
                            query_id,
                            subreddit,
                            state,
                            status="failed",
                            error_code=error_code,
                            error_message=message,
                        )
                        self.service.record_error(
                            collection_run_id,
                            cursor=None,
                            error_code=error_code,
                            message=message,
                            retryable=error.retryable,
                        )
                        subreddits_failed += 1
            final_status = "completed" if subreddits_completed else "failed"
            self.service.finish_run(collection_run_id, final_status)
            return {
                "status": final_status,
                "inserted": inserted,
                "pages_fetched": pages_fetched_total,
                "subreddits_completed": subreddits_completed,
                "subreddits_failed": subreddits_failed,
                "unavailable": unavailable,
            }
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            return {
                "status": "stopped",
                "inserted": inserted,
                "pages_fetched": pages_fetched_total,
                "subreddits_completed": subreddits_completed,
                "subreddits_failed": subreddits_failed,
                "unavailable": unavailable,
            }
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise


class TikTokCollector:
    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        client_key: str | None = None,
        client_secret: str | None = None,
        proxy_url: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
        now: Callable[[], datetime] | None = None,
    ):
        self.service = service
        self.client = client or TikTokResearchClient(
            client_key=client_key or "",
            client_secret=client_secret or "",
            proxy_url=proxy_url or "",
        )
        self.sleep = sleep
        self.max_retries = max_retries
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _quota_date(self) -> str:
        instant = self.now()
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return instant.astimezone(timezone.utc).date().isoformat()

    @staticmethod
    def _error_code(error: TikTokApiError) -> str:
        if error.api_code:
            return f"tiktok_api_{error.api_code}"
        if error.status_code in {401, 403}:
            return "tiktok_authentication"
        if error.status_code == 429:
            return "tiktok_rate_limited"
        if error.status_code is not None:
            return f"tiktok_http_{error.status_code}"
        return "tiktok_connection"

    async def _request(
        self,
        collection_run_id: str,
        operation: str,
        call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                event_id = self.service.reserve_tiktok_request(
                    collection_run_id, operation, quota_date=self._quota_date()
                )
            except ValueError as error:
                if str(error).startswith("TikTok daily request budget exceeded:"):
                    raise TikTokQuotaExhausted(str(error)) from error
                raise
            try:
                result = await call()
            except TikTokApiError as error:
                error_code = self._error_code(error)
                self.service.finish_tiktok_request(
                    event_id, outcome="failed", error_code=error_code
                )
                self.service.record_error(
                    collection_run_id,
                    cursor=None,
                    error_code=error_code,
                    message=f"{operation}: {error}",
                    retryable=error.retryable,
                )
                if not error.retryable or attempt >= self.max_retries:
                    raise
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else min(30.0, float(2**attempt))
                )
                await self.sleep(delay)
            except Exception as error:
                self.service.finish_tiktok_request(
                    event_id,
                    outcome="failed",
                    error_code=f"local_{type(error).__name__}",
                )
                raise
            else:
                self.service.finish_tiktok_request(event_id, outcome="succeeded")
                return result
        raise RuntimeError("unreachable TikTok retry state")

    def _record_invalid_item(
        self,
        collection_run_id: str,
        partition_key: str,
        resource: dict[str, Any],
        error: Exception,
    ) -> None:
        self.service.record_error(
            collection_run_id,
            cursor=None,
            error_code="tiktok_item_invalid",
            message=f"{partition_key}: {error}",
            payload_sha256=hashlib.sha256(
                json.dumps(
                    resource,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            retryable=False,
        )

    def _mark_partition_failed(
        self,
        collection_run_id: str,
        query_id: str,
        partition_key: str,
        error: TikTokApiError,
    ) -> None:
        existing = next(
            (
                row
                for row in self.service.api_collection_states(collection_run_id)
                if row["query_id"] == query_id
                and row["partition_key"] == partition_key
            ),
            None,
        )
        self.service.save_api_collection_state(
            collection_run_id,
            "tiktok",
            query_id,
            partition_key,
            existing["state"] if existing is not None else {},
            status="failed",
            error_code=self._error_code(error),
            error_message=str(error),
        )

    async def _collect_videos(
        self,
        collection_run_id: str,
        query_id: str,
        options: dict[str, Any],
        layer_quotas: dict[str, Any],
        saved: dict[str, Any] | None,
        *,
        max_items: int,
        counters: dict[str, int],
    ) -> tuple[list[str], int]:
        if saved is not None and saved["status"] == "completed":
            return list(saved["state"].get("item_ids", [])), 0
        state = dict(saved["state"] if saved is not None else {})
        cursor = int(state.get("cursor", 0))
        search_id = state.get("search_id")
        pages_fetched = int(state.get("pages_fetched", 0))
        items_seen = int(state.get("items_seen", 0))
        item_ids = list(state.get("item_ids", []))
        has_more = bool(state.get("has_more", True))
        max_videos = int(layer_quotas["max_videos"])
        inserted_here = 0
        while (
            has_more
            and pages_fetched < int(options["max_video_pages"])
            and len(item_ids) < max_videos
            and counters["inserted"] < max_items
        ):
            requested = min(
                int(options["video_page_size"]), max_videos - len(item_ids)
            )
            body: dict[str, Any] = {
                "query": options["query"],
                "start_date": options["start_date"],
                "end_date": options["end_date"],
                "max_count": requested,
                "cursor": cursor,
            }
            if search_id is not None:
                body["search_id"] = search_id
            result = await self._request(
                collection_run_id,
                "video.query",
                lambda body=body: self.client.query_videos(body),
            )
            returned_search_id = result["search_id"]
            if search_id is not None and returned_search_id != search_id:
                error = TikTokApiError(
                    "TikTok search_id changed during pagination",
                    status_code=None,
                    api_code="search_id_changed",
                    retryable=False,
                )
                self.service.record_error(
                    collection_run_id,
                    cursor=None,
                    error_code=self._error_code(error),
                    message=f"video.query: {error}",
                    retryable=False,
                )
                raise error
            search_id = returned_search_id
            cursor = int(result["cursor"])
            has_more = bool(result["has_more"])
            pages_fetched += 1
            items_seen += len(result["items"])
            for resource in result["items"][: max_videos - len(item_ids)]:
                try:
                    resource_id = str(resource["id"])
                    was_inserted = self.service.process_tiktok_resource(
                        collection_run_id,
                        resource,
                        resource_type="video",
                        query_id=query_id,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    self._record_invalid_item(
                        collection_run_id, "videos", resource, error
                    )
                    continue
                if resource_id not in item_ids:
                    item_ids.append(resource_id)
                    counters["videos"] += 1
                counters["inserted"] += int(was_inserted)
                inserted_here += int(was_inserted)
                if counters["inserted"] >= max_items:
                    break
            state = {
                "cursor": cursor,
                "has_more": has_more,
                "item_ids": item_ids,
                "pages_fetched": pages_fetched,
                "search_id": search_id,
                "items_seen": items_seen,
            }
            self.service.save_api_collection_state(
                collection_run_id,
                "tiktok",
                query_id,
                "videos",
                state,
                status="running",
            )
            if has_more and counters["inserted"] < max_items:
                delay = float(options["request_delay_seconds"])
                if delay:
                    await self.sleep(delay)
        self.service.save_api_collection_state(
            collection_run_id,
            "tiktok",
            query_id,
            "videos",
            state,
            status="completed",
        )
        return item_ids, inserted_here

    async def _collect_comments(
        self,
        collection_run_id: str,
        query_id: str,
        options: dict[str, Any],
        saved_states: dict[tuple[str, str], dict[str, Any]],
        *,
        video_id: str,
        parent_comment_id: str | None,
        item_limit: int,
        page_size: int,
        max_pages: int,
        max_items: int,
        counters: dict[str, int],
    ) -> list[str]:
        partition_key = (
            f"comment:{parent_comment_id}:replies"
            if parent_comment_id is not None
            else f"video:{video_id}:comments"
        )
        saved = saved_states.get((query_id, partition_key))
        if saved is not None and saved["status"] == "completed":
            return list(saved["state"].get("item_ids", []))
        state = dict(saved["state"] if saved is not None else {})
        cursor = int(state.get("cursor", 0))
        pages_fetched = int(state.get("pages_fetched", 0))
        items_seen = int(state.get("items_seen", 0))
        item_ids = list(state.get("item_ids", []))
        has_more = bool(state.get("has_more", True))
        resource_type = "reply" if parent_comment_id is not None else "comment"
        while (
            has_more
            and pages_fetched < max_pages
            and len(item_ids) < item_limit
            and counters["inserted"] < max_items
        ):
            requested = min(page_size, item_limit - len(item_ids))
            body = {
                ("comment_id" if parent_comment_id is not None else "video_id"): (
                    parent_comment_id if parent_comment_id is not None else video_id
                ),
                "max_count": requested,
                "cursor": cursor,
            }
            result = await self._request(
                collection_run_id,
                "comment.list",
                lambda body=body: self.client.list_comments(body),
            )
            cursor = int(result["cursor"])
            has_more = bool(result["has_more"])
            pages_fetched += 1
            items_seen += len(result["items"])
            if not has_more and len(result["items"]) < requested:
                self.service.record_audit(
                    "tiktok_comment_page_shortfall",
                    "collection_run",
                    collection_run_id,
                    {
                        "partition_key": partition_key,
                        "query_id": query_id,
                        "requested": requested,
                        "returned": len(result["items"]),
                        "possible_unavailable_items": True,
                    },
                )
            for resource in result["items"][: item_limit - len(item_ids)]:
                try:
                    resource_id = str(resource["id"])
                    was_inserted = self.service.process_tiktok_resource(
                        collection_run_id,
                        resource,
                        resource_type=resource_type,
                        query_id=query_id,
                        video_id=video_id,
                        parent_comment_id=parent_comment_id,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    self._record_invalid_item(
                        collection_run_id, partition_key, resource, error
                    )
                    continue
                if resource_id not in item_ids:
                    item_ids.append(resource_id)
                    counters["replies" if parent_comment_id else "comments"] += 1
                counters["inserted"] += int(was_inserted)
                if counters["inserted"] >= max_items:
                    break
            state = {
                "cursor": cursor,
                "has_more": has_more,
                "item_ids": item_ids,
                "pages_fetched": pages_fetched,
                "items_seen": items_seen,
            }
            self.service.save_api_collection_state(
                collection_run_id,
                "tiktok",
                query_id,
                partition_key,
                state,
                status="running",
            )
            if has_more and counters["inserted"] < max_items:
                delay = float(options["request_delay_seconds"])
                if delay:
                    await self.sleep(delay)
        self.service.save_api_collection_state(
            collection_run_id,
            "tiktok",
            query_id,
            partition_key,
            state,
            status="completed",
        )
        return item_ids

    async def run(
        self, collection_run_id: str, *, max_items: int
    ) -> dict[str, Any]:
        counters = {"inserted": 0, "videos": 0, "comments": 0, "replies": 0}
        partitions_completed = 0
        partitions_failed = 0
        starting_requests = len(
            self.service.tiktok_request_events(collection_run_id)
        )
        try:
            run = self.service.get_run(collection_run_id)
            if run.get("platform") != "tiktok" or not isinstance(run.get("scope_id"), str):
                raise KeyError(collection_run_id)
            saved_states = {
                (row["query_id"], row["partition_key"]): row
                for row in self.service.api_collection_states(collection_run_id)
            }
            for scope_row in self.service.run_scope_snapshots(collection_run_id):
                if counters["inserted"] >= max_items:
                    break
                query_id = scope_row["query_id"]
                options = scope_row.get("platform_options")
                layer_quotas = scope_row.get("layer_quotas")
                if not isinstance(options, dict) or not isinstance(layer_quotas, dict):
                    raise ValueError("TikTok query 缺少冻结平台或分层配置")
                try:
                    video_ids, _inserted = await self._collect_videos(
                        collection_run_id,
                        query_id,
                        options,
                        layer_quotas,
                        saved_states.get((query_id, "videos")),
                        max_items=max_items,
                        counters=counters,
                    )
                    partitions_completed += 1
                except TikTokApiError as error:
                    self._mark_partition_failed(
                        collection_run_id,
                        query_id,
                        "videos",
                        error,
                    )
                    partitions_failed += 1
                    continue
                for video_id in video_ids:
                    if counters["inserted"] >= max_items:
                        break
                    try:
                        comment_ids = await self._collect_comments(
                            collection_run_id,
                            query_id,
                            options,
                            saved_states,
                            video_id=video_id,
                            parent_comment_id=None,
                            item_limit=int(layer_quotas["max_comment_threads_per_video"]),
                            page_size=int(options["comment_page_size"]),
                            max_pages=int(options["max_comment_pages_per_video"]),
                            max_items=max_items,
                            counters=counters,
                        )
                        partitions_completed += 1
                    except TikTokApiError as error:
                        self._mark_partition_failed(
                            collection_run_id,
                            query_id,
                            f"video:{video_id}:comments",
                            error,
                        )
                        partitions_failed += 1
                        continue
                    for comment_id in comment_ids:
                        if counters["inserted"] >= max_items:
                            break
                        try:
                            await self._collect_comments(
                                collection_run_id,
                                query_id,
                                options,
                                saved_states,
                                video_id=video_id,
                                parent_comment_id=comment_id,
                                item_limit=int(layer_quotas["max_replies_per_thread"]),
                                page_size=int(options["reply_page_size"]),
                                max_pages=int(options["max_reply_pages_per_comment"]),
                                max_items=max_items,
                                counters=counters,
                            )
                            partitions_completed += 1
                        except TikTokApiError as error:
                            self._mark_partition_failed(
                                collection_run_id,
                                query_id,
                                f"comment:{comment_id}:replies",
                                error,
                            )
                            partitions_failed += 1
            final_status = "completed" if partitions_completed else "failed"
            self.service.finish_run(collection_run_id, final_status)
            requests = len(self.service.tiktok_request_events(collection_run_id)) - starting_requests
            return {
                "status": final_status,
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except TikTokQuotaExhausted:
            self.service.finish_run(collection_run_id, "stopped")
            requests = len(self.service.tiktok_request_events(collection_run_id)) - starting_requests
            return {
                "status": "quota_exhausted",
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            requests = len(self.service.tiktok_request_events(collection_run_id)) - starting_requests
            return {
                "status": "stopped",
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise


class XCollector:
    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        bearer_token: str | None = None,
        proxy_url: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
    ):
        self.service = service
        self.client = client or XRecentSearchClient(
            bearer_token=bearer_token or "",
            proxy_url=proxy_url or "",
        )
        self.sleep = sleep
        self.max_retries = max_retries

    @staticmethod
    def _error_code(error: XApiError) -> str:
        if error.api_code:
            normalized = "_".join(
                part for part in re.split(r"[^a-z0-9]+", error.api_code.casefold())
                if part
            )
            return f"x_api_{normalized or 'unknown'}"
        if error.status_code in {401, 403}:
            return "x_authentication"
        if error.status_code == 429:
            return "x_rate_limited"
        if error.status_code is not None:
            return f"x_http_{error.status_code}"
        return "x_connection"

    async def _request(
        self,
        collection_run_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        max_resources = int(parameters["max_results"])
        for attempt in range(self.max_retries + 1):
            event_id = self.service.reserve_x_request(
                collection_run_id, max_resources=max_resources
            )
            try:
                result = await self.client.search(parameters)
            except asyncio.CancelledError:
                self.service.finish_x_request(
                    event_id,
                    outcome="indeterminate",
                    actual_resources=max_resources,
                    error_code="local_cancelled",
                )
                raise
            except XApiError as error:
                error_code = self._error_code(error)
                self.service.finish_x_request(
                    event_id,
                    outcome="failed",
                    actual_resources=0,
                    error_code=error_code,
                )
                self.service.record_error(
                    collection_run_id,
                    cursor=None,
                    error_code=error_code,
                    message=f"recent.search: {error}",
                    retryable=error.retryable,
                )
                if not error.retryable or attempt >= self.max_retries:
                    raise
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else min(30.0, float(2**attempt))
                )
                await self.sleep(delay)
            except Exception as error:
                self.service.finish_x_request(
                    event_id,
                    outcome="failed",
                    actual_resources=0,
                    error_code=f"local_{type(error).__name__}",
                )
                raise
            else:
                result_count = result.get("result_count")
                if (
                    isinstance(result_count, bool)
                    or not isinstance(result_count, int)
                    or not 0 <= result_count <= max_resources
                ):
                    self.service.finish_x_request(
                        event_id,
                        outcome="failed",
                        actual_resources=0,
                        error_code="x_result_count_invalid",
                    )
                    raise ValueError("X result_count exceeds reserved resources")
                self.service.finish_x_request(
                    event_id,
                    outcome="succeeded",
                    actual_resources=result_count,
                )
                return result
        raise RuntimeError("unreachable X retry state")

    def _record_invalid_item(
        self,
        collection_run_id: str,
        query_id: str,
        post: dict[str, Any],
        error: Exception,
    ) -> None:
        self.service.record_error(
            collection_run_id,
            cursor=None,
            error_code="x_item_invalid",
            message=f"{query_id}: {error}",
            payload_sha256=hashlib.sha256(
                json.dumps(
                    post,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            retryable=False,
        )

    async def run(
        self, collection_run_id: str, *, max_items: int
    ) -> dict[str, Any]:
        counters = {"inserted": 0, "items_seen": 0, "pages_fetched": 0}
        partitions_completed = 0
        partitions_failed = 0
        starting_requests = len(self.service.x_request_events(collection_run_id))
        try:
            run = self.service.get_run(collection_run_id)
            if run.get("platform") != "x" or not isinstance(run.get("scope_id"), str):
                raise KeyError(collection_run_id)
            saved_states = {
                (row["query_id"], row["partition_key"]): row
                for row in self.service.api_collection_states(collection_run_id)
            }
            for scope_row in self.service.run_scope_snapshots(collection_run_id):
                if counters["inserted"] >= max_items:
                    break
                query_id = scope_row["query_id"]
                options = scope_row.get("platform_options")
                if not isinstance(options, dict):
                    raise ValueError("X query 缺少冻结平台配置")
                partition_key = "recent_search"
                saved = saved_states.get((query_id, partition_key))
                if saved is not None and saved["status"] == "completed":
                    partitions_completed += 1
                    continue
                state = dict(saved["state"] if saved is not None else {})
                pages_fetched = int(state.get("pages_fetched", 0))
                items_seen = int(state.get("items_seen", 0))
                next_token = state.get("next_token")
                last_rate_limit = state.get("last_rate_limit")
                self.service.save_api_collection_state(
                    collection_run_id,
                    "x",
                    query_id,
                    partition_key,
                    {
                        "items_seen": items_seen,
                        "last_rate_limit": last_rate_limit,
                        "next_token": next_token,
                        "pages_fetched": pages_fetched,
                    },
                    status="running",
                )
                try:
                    while (
                        pages_fetched < int(options["max_pages"])
                        and counters["inserted"] < max_items
                    ):
                        parameters = {
                            "query": options["query"],
                            "max_results": int(options["page_size"]),
                            "start_time": options["start_time"],
                            "end_time": options["end_time"],
                            "tweet.fields": options["post_fields"],
                        }
                        if next_token is not None:
                            parameters["pagination_token"] = next_token
                        result = await self._request(
                            collection_run_id, parameters
                        )
                        pages_fetched += 1
                        counters["pages_fetched"] += 1
                        next_token = result["next_token"]
                        last_rate_limit = result["rate_limit"]
                        items = result["items"]
                        items_seen += len(items)
                        counters["items_seen"] += len(items)
                        for post in items:
                            try:
                                was_inserted = self.service.process_x_post(
                                    collection_run_id,
                                    post,
                                    query_id=query_id,
                                )
                            except (KeyError, TypeError, ValueError) as error:
                                self._record_invalid_item(
                                    collection_run_id, query_id, post, error
                                )
                                continue
                            counters["inserted"] += int(was_inserted)
                            if counters["inserted"] >= max_items:
                                break
                        state = {
                            "items_seen": items_seen,
                            "last_rate_limit": last_rate_limit,
                            "next_token": next_token,
                            "pages_fetched": pages_fetched,
                        }
                        self.service.save_api_collection_state(
                            collection_run_id,
                            "x",
                            query_id,
                            partition_key,
                            state,
                            status="running",
                        )
                        if next_token is None or counters["inserted"] >= max_items:
                            break
                        delay = float(options["request_delay_seconds"])
                        if delay:
                            await self.sleep(delay)
                    self.service.save_api_collection_state(
                        collection_run_id,
                        "x",
                        query_id,
                        partition_key,
                        state,
                        status="completed",
                    )
                    partitions_completed += 1
                except XApiError as error:
                    error_code = self._error_code(error)
                    self.service.save_api_collection_state(
                        collection_run_id,
                        "x",
                        query_id,
                        partition_key,
                        state,
                        status="failed",
                        error_code=error_code,
                        error_message=str(error),
                    )
                    partitions_failed += 1
            final_status = "completed" if partitions_completed else "failed"
            self.service.finish_run(collection_run_id, final_status)
            requests = (
                len(self.service.x_request_events(collection_run_id))
                - starting_requests
            )
            return {
                "status": final_status,
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except (XBudgetExceeded, XBillingGateError):
            self.service.finish_run(collection_run_id, "stopped")
            requests = (
                len(self.service.x_request_events(collection_run_id))
                - starting_requests
            )
            return {
                "status": "budget_exhausted",
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            requests = (
                len(self.service.x_request_events(collection_run_id))
                - starting_requests
            )
            return {
                "status": "stopped",
                **counters,
                "requests": requests,
                "partitions_failed": partitions_failed,
            }
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise


class YouTubeCollector:
    OPERATION_BY_RESOURCE = {
        "search": "search.list",
        "videos": "videos.list",
        "channels": "channels.list",
        "commentThreads": "commentThreads.list",
        "comments": "comments.list",
    }

    def __init__(
        self,
        service: SocialNarrativeService,
        *,
        api_key: str | None = None,
        proxy_url: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
    ):
        self.service = service
        self.client = client or YouTubeApiClient(api_key or "", proxy_url=proxy_url)
        self.sleep = sleep
        self.max_retries = max_retries

    async def _request(
        self,
        collection_run_id: str,
        resource: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        operation = self.OPERATION_BY_RESOURCE[resource]
        for attempt in range(self.max_retries + 1):
            quota_event_id = self.service.consume_youtube_quota(
                collection_run_id, operation
            )
            try:
                payload = await self.client.request(resource, parameters)
                self.service.finish_youtube_quota_event(quota_event_id, "success")
                return payload
            except YouTubeApiError as error:
                self.service.finish_youtube_quota_event(quota_event_id, "error")
                self.service.record_error(
                    collection_run_id,
                    cursor=None,
                    error_code=f"youtube_api_{error.status_code or 'connection'}",
                    message=f"{operation}: {error}",
                    retryable=error.retryable,
                )
                if not error.retryable or attempt >= self.max_retries:
                    raise
                await self.sleep(min(30.0, float(2**attempt)))
        raise RuntimeError("unreachable YouTube retry state")

    @staticmethod
    def _scope(scope_row: dict[str, Any]):
        from .bluesky import ResearchScope

        return ResearchScope(
            query_id=scope_row["query_id"],
            object_type=scope_row["object_type"],
            object_label=scope_row["object_label"],
            keywords=tuple(scope_row["keywords"]),
            languages=tuple(scope_row["languages"]),
            window_start=scope_row["window_start"],
            window_end=scope_row["window_end"],
            exact_query=scope_row.get("exact_query"),
        )

    @staticmethod
    def _in_window(value: Any, start: str, end: str) -> bool:
        if not isinstance(value, str):
            return False

        def parse(candidate: str) -> datetime:
            candidate = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        return parse(start) <= parse(value) <= parse(end)

    async def _collect_comments(
        self,
        collection_run_id: str,
        video_id: str,
        scope_row: dict[str, Any],
        query_ids: list[str],
        remaining: int,
        metrics: dict[str, int],
    ) -> int:
        inserted = 0
        quotas = scope_row["layer_quotas"]
        max_threads = int(quotas["max_comment_threads_per_video"])
        max_replies = int(quotas["max_replies_per_thread"])
        if max_threads == 0:
            return 0
        threads_seen = 0
        page_token = None
        while inserted < remaining and threads_seen < max_threads:
            try:
                response = await self._request(collection_run_id, "commentThreads", {
                    "part": "snippet,replies",
                    "videoId": video_id,
                    "maxResults": min(100, max_threads - threads_seen),
                    "order": "time",
                    "textFormat": "plainText",
                    "pageToken": page_token,
                })
            except YouTubeApiError as error:
                if error.reason in {"commentsDisabled", "videoNotFound"}:
                    return inserted
                raise
            for thread in response.get("items") or []:
                if not isinstance(thread, dict) or threads_seen >= max_threads:
                    continue
                threads_seen += 1
                metrics["comment_threads_seen"] += 1
                snippet = thread.get("snippet") or {}
                top_level = snippet.get("topLevelComment")
                if isinstance(top_level, dict):
                    published = (top_level.get("snippet") or {}).get("publishedAt")
                    if self._in_window(
                        published, scope_row["window_start"], scope_row["window_end"]
                    ) and self._process_for_queries(
                        collection_run_id, query_ids, top_level,
                        {"kind": "comment", "thread": thread, "comment": top_level},
                        video_id=video_id, reply_count=snippet.get("totalReplyCount"),
                    ):
                        inserted += 1
                        metrics["top_comments_inserted"] += 1
                        if inserted >= remaining:
                            return inserted
                replies = (thread.get("replies") or {}).get("comments") or []
                replies_seen = 0
                for reply in replies[:max_replies]:
                    if not isinstance(reply, dict):
                        continue
                    replies_seen += 1
                    metrics["replies_seen"] += 1
                    reply_snippet = reply.get("snippet") or {}
                    if not self._in_window(
                        reply_snippet.get("publishedAt"),
                        scope_row["window_start"],
                        scope_row["window_end"],
                    ):
                        continue
                    parent_id = reply_snippet.get("parentId")
                    if self._process_for_queries(
                        collection_run_id, query_ids, reply,
                        {"kind": "comment_reply", "thread_id": thread.get("id"), "comment": reply},
                        video_id=video_id,
                        parent_comment_id=parent_id if isinstance(parent_id, str) else None,
                    ):
                        inserted += 1
                        metrics["replies_inserted"] += 1
                        if inserted >= remaining:
                            return inserted
                total_reply_count = snippet.get("totalReplyCount")
                if (
                    isinstance(total_reply_count, int)
                    and total_reply_count > len(replies)
                    and replies_seen < max_replies
                    and isinstance(top_level, dict)
                    and isinstance(top_level.get("id"), str)
                ):
                    reply_page_token = None
                    while inserted < remaining and replies_seen < max_replies:
                        reply_response = await self._request(
                            collection_run_id,
                            "comments",
                            {
                                "part": "snippet",
                                "parentId": top_level["id"],
                                "maxResults": min(100, max_replies - replies_seen),
                                "textFormat": "plainText",
                                "pageToken": reply_page_token,
                            },
                        )
                        for reply in reply_response.get("items") or []:
                            if not isinstance(reply, dict) or replies_seen >= max_replies:
                                continue
                            replies_seen += 1
                            metrics["replies_seen"] += 1
                            reply_snippet = reply.get("snippet") or {}
                            if not self._in_window(
                                reply_snippet.get("publishedAt"),
                                scope_row["window_start"],
                                scope_row["window_end"],
                            ):
                                continue
                            parent_id = reply_snippet.get("parentId")
                            if self._process_for_queries(
                                collection_run_id, query_ids, reply,
                                {
                                    "kind": "comment_reply",
                                    "thread_id": thread.get("id"),
                                    "comment": reply,
                                },
                                video_id=video_id,
                                parent_comment_id=(
                                    parent_id if isinstance(parent_id, str) else top_level["id"]
                                ),
                            ):
                                inserted += 1
                                metrics["replies_inserted"] += 1
                                if inserted >= remaining:
                                    return inserted
                        reply_page_token = reply_response.get("nextPageToken")
                        if not isinstance(reply_page_token, str) or not reply_page_token:
                            break
            page_token = response.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                return inserted
        return inserted

    def _process_for_queries(
        self,
        collection_run_id: str,
        query_ids: list[str],
        resource: dict[str, Any],
        raw_event: dict[str, Any],
        **kwargs: Any,
    ) -> bool:
        inserted = False
        for query_id in query_ids:
            matched_event = {**raw_event, "matched_query_id": query_id}
            inserted = self.service.process_youtube_resource(
                collection_run_id,
                resource,
                matched_event,
                query_id=query_id,
                **kwargs,
            ) or inserted
        return inserted

    async def _collect_screened_video_comments(
        self,
        collection_run_id: str,
        scope_id: str,
        scope_rows: list[dict[str, Any]],
        state: dict[str, Any],
        max_items: int,
    ) -> dict[str, Any]:
        inserted = 0
        metrics = state["metrics"]
        completed_video_ids = set(state.get("completed_video_ids") or [])
        included_video_ids = set(state.get("included_video_ids") or [])
        scopes_by_query = {row["query_id"]: row for row in scope_rows}
        pending_candidates = []
        for candidate in state.get("video_candidates") or []:
            video_id = candidate["video_id"]
            if video_id in completed_video_ids:
                continue
            screening = self.service.latest_screening(candidate["observation_id"])
            decision = screening["decision"] if screening is not None else "uncertain"
            pending_candidates.append((candidate, decision))
        if any(decision == "uncertain" for _, decision in pending_candidates):
            self.service.save_youtube_run_state(collection_run_id, {
                **state,
                "metrics": metrics,
                "completed_video_ids": sorted(completed_video_ids),
                "included_video_ids": sorted(included_video_ids),
            })
            self.service.finish_run(collection_run_id, "awaiting_screening")
            return {"status": "awaiting_screening", "inserted": 0}

        remaining_included = sum(
            decision == "include" for _, decision in pending_candidates
        )
        for candidate, decision in pending_candidates:
            video_id = candidate["video_id"]
            if decision == "include":
                if video_id not in included_video_ids:
                    metrics["videos_screening_included"] += 1
                    included_video_ids.add(video_id)
                if inserted < max_items:
                    remaining_budget = max_items - inserted
                    video_budget = max(1, remaining_budget // remaining_included)
                    query_ids = candidate.get("query_ids") or [scope_rows[0]["query_id"]]
                    scope_row = scopes_by_query.get(query_ids[0], scope_rows[0])
                    inserted += await self._collect_comments(
                        collection_run_id,
                        video_id,
                        scope_row,
                        query_ids,
                        video_budget,
                        metrics,
                    )
                remaining_included -= 1
            else:
                metrics["videos_screening_excluded"] += 1
            completed_video_ids.add(video_id)
            self.service.save_youtube_run_state(collection_run_id, {
                **state,
                "metrics": metrics,
                "completed_video_ids": sorted(completed_video_ids),
                "included_video_ids": sorted(included_video_ids),
            })

        final_state = {
            **state,
            "metrics": metrics,
            "completed_video_ids": sorted(completed_video_ids),
            "included_video_ids": sorted(included_video_ids),
        }
        final_state["stage"] = "completed"
        self.service.save_youtube_run_state(collection_run_id, final_state)
        latest_published = final_state.get("latest_published")
        if final_state.get("discovery_exhausted") and isinstance(latest_published, str):
            self.service.save_youtube_published_after(scope_id, latest_published)
        self.service.finish_run(collection_run_id, "completed")
        return {"status": "completed", "inserted": inserted}

    async def run(self, collection_run_id: str, *, max_items: int) -> dict[str, Any]:
        inserted = 0
        try:
            run = self.service.get_run(collection_run_id)
            scope_id = run.get("scope_id")
            if run.get("platform") != "youtube" or not scope_id:
                raise KeyError(collection_run_id)
            scope_rows = self.service.run_scope_snapshots(collection_run_id)
            if not scope_rows:
                raise ValueError("YouTube run 没有冻结 query")
            state = self.service.youtube_run_state(collection_run_id) or {
                "query_index": 0,
                "language_index": 0,
                "search_page_token": None,
            }
            if state.get("stage") == "awaiting_video_screening":
                return await self._collect_screened_video_comments(
                    collection_run_id,
                    scope_id,
                    scope_rows,
                    state,
                    max_items,
                )
            metric_names = (
                "search_results",
                "video_details",
                "video_candidates",
                "videos_inserted",
                "videos_screening_included",
                "videos_screening_excluded",
                "comment_threads_seen",
                "top_comments_inserted",
                "replies_seen",
                "replies_inserted",
            )
            previous_metrics = state.get("metrics")
            metrics = {
                name: int(previous_metrics.get(name, 0)) if isinstance(previous_metrics, dict) else 0
                for name in metric_names
            }
            published_after = (
                self.service.youtube_published_after(scope_id)
                or scope_rows[0]["window_start"]
            )
            latest_published = state.get("latest_published")
            discovery_exhausted = True
            query_metrics = state.get("query_metrics") or {}
            video_query_ids = state.get("video_query_ids") or {}
            start_query_index = int(state.get("query_index", 0))
            for query_index in range(start_query_index, len(scope_rows)):
                scope_row = scope_rows[query_index]
                query_id = scope_row["query_id"]
                languages = scope_row["languages"] or [None]
                query_state = query_metrics.get(query_id) or {"video_candidates": 0}
                max_videos = min(
                    int(scope_row["layer_quotas"]["max_videos"]), max_items
                )
                videos_selected = int(query_state.get("video_candidates", 0))
                start_language_index = (
                    int(state.get("language_index", 0))
                    if query_index == start_query_index else 0
                )
                for language_index in range(start_language_index, len(languages)):
                    page_token = (
                        state.get("search_page_token")
                        if query_index == start_query_index
                        and language_index == start_language_index
                        else None
                    )
                    while videos_selected < max_videos:
                        remaining_videos = max_videos - videos_selected
                        search = await self._request(collection_run_id, "search", {
                            "part": "snippet",
                            "type": "video",
                            "q": scope_row["exact_query"],
                            "maxResults": min(50, remaining_videos),
                            "publishedAfter": published_after,
                            "publishedBefore": scope_row["window_end"],
                            "relevanceLanguage": languages[language_index],
                            "pageToken": page_token,
                        })
                        search_items = [
                            item for item in (search.get("items") or [])
                            if isinstance(item, dict)
                            and isinstance(item.get("id"), dict)
                            and isinstance(item["id"].get("videoId"), str)
                        ]
                        metrics["search_results"] += len(search_items)
                        video_ids = [
                            item["id"]["videoId"]
                            for item in search_items[:remaining_videos]
                        ]
                        if video_ids:
                            videos_response = await self._request(collection_run_id, "videos", {
                                "part": "snippet,statistics",
                                "id": ",".join(video_ids),
                                "maxResults": 50,
                            })
                            videos = {
                                item["id"]: item for item in (videos_response.get("items") or [])
                                if isinstance(item, dict) and isinstance(item.get("id"), str)
                            }
                            metrics["video_details"] += len(videos)
                            channel_ids = sorted({
                                snippet["channelId"]
                                for video in videos.values()
                                if isinstance((snippet := video.get("snippet")), dict)
                                and isinstance(snippet.get("channelId"), str)
                            })
                            channels = {}
                            if channel_ids:
                                channel_response = await self._request(collection_run_id, "channels", {
                                    "part": "snippet", "id": ",".join(channel_ids), "maxResults": 50,
                                })
                                channels = {
                                    item["id"]: item for item in (channel_response.get("items") or [])
                                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                                }
                            for search_item in search_items:
                                if videos_selected >= max_videos:
                                    break
                                video_id = search_item["id"]["videoId"]
                                video = videos.get(video_id)
                                if video is None:
                                    continue
                                snippet = video.get("snippet") or {}
                                published_at = snippet.get("publishedAt")
                                if not self._in_window(published_at, scope_row["window_start"], scope_row["window_end"]):
                                    continue
                                videos_selected += 1
                                metrics["video_candidates"] += 1
                                query_state["video_candidates"] = videos_selected
                                query_ids = video_query_ids.setdefault(video_id, [])
                                if query_id not in query_ids:
                                    query_ids.append(query_id)
                                if self.service.process_youtube_resource(
                                    collection_run_id,
                                    video,
                                    {"kind": "video", "search_result": search_item, "video": video, "channel": channels.get(snippet.get("channelId")), "matched_query_id": query_id},
                                    channel=channels.get(snippet.get("channelId")),
                                    query_id=query_id,
                                    candidate_rank=videos_selected,
                                ):
                                    inserted += 1
                                    metrics["videos_inserted"] += 1
                                if isinstance(published_at, str):
                                    latest_published = max(latest_published or published_at, published_at)
                        page_token = search.get("nextPageToken")
                        if videos_selected >= max_videos and (
                            len(search_items) > len(video_ids)
                            or isinstance(page_token, str) and bool(page_token)
                            or language_index + 1 < len(languages)
                        ):
                            discovery_exhausted = False
                        query_metrics[query_id] = query_state
                        self.service.save_youtube_run_state(collection_run_id, {
                            "query_index": query_index,
                            "language_index": language_index,
                            "search_page_token": page_token,
                            "metrics": metrics,
                            "query_metrics": query_metrics,
                            "video_query_ids": video_query_ids,
                            "latest_published": latest_published,
                        })
                        if videos_selected >= max_videos or not isinstance(page_token, str) or not page_token:
                            break
                    if videos_selected >= max_videos:
                        break
                    self.service.save_youtube_run_state(collection_run_id, {
                        "query_index": query_index,
                        "language_index": language_index + 1,
                        "search_page_token": None,
                        "metrics": metrics,
                        "query_metrics": query_metrics,
                        "video_query_ids": video_query_ids,
                        "latest_published": latest_published,
                    })
                self.service.save_youtube_run_state(collection_run_id, {
                    "query_index": query_index + 1,
                    "language_index": 0,
                    "search_page_token": None,
                    "metrics": metrics,
                    "query_metrics": query_metrics,
                    "video_query_ids": video_query_ids,
                    "latest_published": latest_published,
                })
            self.service.save_youtube_run_state(collection_run_id, {
                "query_index": len(scope_rows),
                "language_index": 0,
                "search_page_token": None,
                "metrics": metrics,
                "query_metrics": query_metrics,
                "video_query_ids": video_query_ids,
                "latest_published": latest_published,
            })
            query_matches = self.service.observation_query_matches(collection_run_id)
            matched_queries_by_observation: dict[str, list[str]] = {}
            for match in query_matches:
                matched_queries_by_observation.setdefault(match["observation_id"], []).append(match["query_id"])
            video_candidates = [
                {
                    "video_id": row["platform_item_id"].removeprefix("video:"),
                    "observation_id": row["observation_id"],
                    "query_ids": matched_queries_by_observation.get(
                        row["observation_id"], [row["query_id"]]
                    ),
                }
                for row in self.service.observations()
                if row["collection_run_id"] == collection_run_id
                and row["platform_item_id"].startswith("video:")
            ]
            if (
                video_candidates
                and any(
                    int(scope_row["layer_quotas"]["max_comment_threads_per_video"]) > 0
                    for scope_row in scope_rows
                )
            ):
                self.service.save_youtube_run_state(collection_run_id, {
                    "stage": "awaiting_video_screening",
                    "query_index": len(scope_rows),
                    "language_index": 0,
                    "search_page_token": None,
                    "metrics": metrics,
                    "video_candidates": video_candidates,
                    "completed_video_ids": [],
                    "included_video_ids": [],
                    "latest_published": latest_published,
                    "discovery_exhausted": discovery_exhausted,
                })
                self.service.finish_run(collection_run_id, "awaiting_screening")
                return {"status": "awaiting_screening", "inserted": inserted}
            if discovery_exhausted and latest_published is not None:
                self.service.save_youtube_published_after(scope_id, latest_published)
            self.service.finish_run(collection_run_id, "completed")
            return {"status": "completed", "inserted": inserted}
        except asyncio.CancelledError:
            self.service.finish_run(collection_run_id, "stopped")
            return {"status": "stopped", "inserted": inserted}
        except ValueError as error:
            self.service.record_error(
                collection_run_id,
                cursor=None,
                error_code=(
                    "youtube_quota_budget"
                    if "配额" in str(error)
                    else "youtube_collection_error"
                ),
                message=str(error),
                retryable=False,
            )
            self.service.finish_run(collection_run_id, "failed")
            raise
        except Exception:
            self.service.finish_run(collection_run_id, "failed")
            raise
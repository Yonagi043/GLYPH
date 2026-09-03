"""FastAPI application for the local single-researcher workflow."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .collector import (
    BlueskyCollector,
    MastodonCollector,
    RedditCollector,
    TikTokCollector,
    XCollector,
    YouTubeCollector,
)
from .service import SocialNarrativeService
from .storage import ResearchStore
from .tiktok import REQUIRED_OUTBOUND_PROXY


STATIC_DIR = Path(__file__).with_name("static")
MAX_COLLECTION_RUNTIME_SECONDS = 30 * 60


class ScopeInput(BaseModel):
    platform: str = "bluesky"
    name: str
    object_type: str
    object_label: str
    keywords: list[str]
    languages: list[str]
    window_start: str
    window_end: str
    max_items: int = Field(ge=1, le=1000)
    query_family: str = "legacy_scope_keywords"
    phase: str = "exploratory"
    exact_query: str | None = None
    max_videos: int | None = Field(default=None, ge=1, le=100)
    max_comment_threads_per_video: int = Field(default=100, ge=0, le=100)
    max_replies_per_thread: int = Field(default=100, ge=0, le=100)
    query_yield_evaluation_k: int = Field(default=20, ge=1, le=50)
    query_yield_min_included_at_k: int = Field(default=5, ge=0, le=50)
    query_yield_min_precision_at_k: float = Field(default=0.25, ge=0, le=1)
    query_yield_min_precision_lower_bound: float = Field(default=0.10, ge=0, le=1)
    query_yield_confidence_level: float = Field(default=0.95, gt=0, lt=1)
    mastodon_instances: list[str] | None = None
    mastodon_access_method: str = "hashtag_timeline"
    mastodon_page_size: int = Field(default=40, ge=1, le=40)
    mastodon_max_pages_per_instance: int = Field(default=1, ge=1, le=20)
    mastodon_request_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    reddit_subreddits: list[str] | None = None
    reddit_access_method: str = "subreddit_search"
    reddit_sort: str = "relevance"
    reddit_time_filter: str = "all"
    reddit_page_size: int = Field(default=100, ge=1, le=100)
    reddit_max_pages_per_subreddit: int = Field(default=1, ge=1, le=20)
    reddit_request_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    tiktok_query: dict[str, Any] | None = None
    tiktok_video_page_size: int = Field(default=100, ge=1, le=100)
    tiktok_max_video_pages: int = Field(default=1, ge=1, le=20)
    tiktok_comment_page_size: int = Field(default=100, ge=1, le=100)
    tiktok_max_comment_pages_per_video: int = Field(default=1, ge=1, le=20)
    tiktok_reply_page_size: int = Field(default=100, ge=1, le=100)
    tiktok_max_reply_pages_per_comment: int = Field(default=1, ge=1, le=20)
    tiktok_request_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    x_page_size: int = Field(default=100, ge=10, le=100)
    x_max_pages: int = Field(default=1, ge=1, le=20)
    x_request_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    x_local_run_budget_microusd: int = Field(default=500_000, ge=1)


class ScopeUpdateInput(ScopeInput):
    active: bool


class ScopeQueryInput(BaseModel):
    query_family: str
    phase: str
    exact_query: str


class StartRunInput(BaseModel):
    scope_id: str
    youtube_run_search_call_budget: int | None = Field(default=None, ge=1, le=100)
    youtube_run_shared_unit_budget: int | None = Field(
        default=None, ge=1, le=1_000_000_000
    )


class ScheduleInput(BaseModel):
    scope_id: str
    interval_minutes: int = Field(ge=1, le=10080)
    enabled: bool = True


class ScheduleUpdateInput(BaseModel):
    interval_minutes: int = Field(ge=1, le=10080)
    enabled: bool


class ReviewInput(BaseModel):
    status: str
    object_type: str
    object_label: str
    aesthetic_terms: list[str]
    evidence_span: str | None = None
    stance: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    exclusion_reason: str | None = None
    author_role: str | None = None


class IndependentAnnotationInput(BaseModel):
    coder_id: str
    object_type: str
    object_label: str
    aesthetic_terms: list[str]
    evidence_span: str
    stance: str
    language_confirmed: bool
    author_role: str


class AdjudicationInput(BaseModel):
    adjudicator_id: str
    object_type: str
    object_label: str
    aesthetic_terms: list[str]
    evidence_span: str
    stance: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    author_role: str


class ReleaseInput(BaseModel):
    release_allowed: bool
    reason: str = Field(min_length=1)


class ScreeningInput(BaseModel):
    decision: str
    reason: str


class QueryPromotionInput(BaseModel):
    query_ids: list[str] | None = None
    name: str = Field(min_length=1)
    window_start: str
    window_end: str
    max_items: int = Field(ge=1, le=1000)
    max_videos: int = Field(ge=1, le=50)
    max_comment_threads_per_video: int = Field(ge=0, le=100)
    max_replies_per_thread: int = Field(ge=0, le=100)


class YouTubeQuotaInput(BaseModel):
    daily_budget: int = Field(ge=1, le=1_000_000_000)
    search_daily_call_budget: int | None = Field(default=None, ge=1, le=100)


class CollectorManager:
    def __init__(
        self,
        service: SocialNarrativeService,
        outbound_proxy: str | None = None,
        youtube_api_key: str | None = None,
        mastodon_access_tokens: dict[str, str] | None = None,
        reddit_client_id: str | None = None,
        reddit_client_secret: str | None = None,
        reddit_refresh_token: str | None = None,
        reddit_user_agent: str | None = None,
        tiktok_client_key: str | None = None,
        tiktok_client_secret: str | None = None,
        x_bearer_token: str | None = None,
    ):
        self.service = service
        self.outbound_proxy = outbound_proxy
        self.youtube_api_key = youtube_api_key
        self.mastodon_access_tokens = mastodon_access_tokens or {}
        self.reddit_client_id = reddit_client_id
        self.reddit_client_secret = reddit_client_secret
        self.reddit_refresh_token = reddit_refresh_token
        self.reddit_user_agent = reddit_user_agent
        self.tiktok_client_key = tiktok_client_key
        self.tiktok_client_secret = tiktok_client_secret
        self.x_bearer_token = x_bearer_token
        self.tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    def _task_done(
        self, run_id: str, task: asyncio.Task[dict[str, Any]]
    ) -> None:
        self.tasks.pop(run_id, None)
        if not task.cancelled():
            task.exception()

    async def startup(self) -> None:
        self.service.recover_interrupted_runs()
        self.scheduler.start()
        for schedule in self.service.list_schedules():
            self.sync_schedule(schedule)

    def sync_schedule(self, schedule: dict[str, Any]) -> None:
        schedule_id = schedule["schedule_id"]
        existing = self.scheduler.get_job(schedule_id)
        if existing is not None:
            self.scheduler.remove_job(schedule_id)
        if not schedule["enabled"]:
            return
        next_run_time = _parse_datetime(schedule["next_run_at"])
        self.scheduler.add_job(
            self._run_schedule,
            trigger=IntervalTrigger(minutes=schedule["interval_minutes"], timezone="UTC"),
            args=[schedule_id],
            id=schedule_id,
            next_run_time=next_run_time,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
            replace_existing=True,
        )

    async def _run_schedule(self, schedule_id: str) -> dict[str, Any]:
        schedule = self.service.get_schedule(schedule_id)
        if not schedule["enabled"]:
            return {"status": "disabled", "schedule_id": schedule_id}
        scope = self.service.get_scope(schedule["scope_id"])
        if not scope["active"] or _parse_datetime(scope["window_end"]) < datetime.now(timezone.utc):
            disabled = self.service.update_schedule(
                schedule_id,
                interval_minutes=schedule["interval_minutes"],
                enabled=False,
            )
            self.sync_schedule(disabled)
            return {"status": "window_closed", "schedule_id": schedule_id}
        manifest = await self.start(
            schedule["scope_id"], trigger_type="scheduled", schedule_id=schedule_id
        )
        self.service.record_schedule_run(schedule_id, manifest["collection_run_id"])
        return manifest

    async def _collect(
        self,
        collector: Any,
        run_id: str,
        max_items: int,
    ) -> dict[str, Any]:
        return await asyncio.wait_for(
            collector.run(run_id, max_items=max_items),
            timeout=MAX_COLLECTION_RUNTIME_SECONDS,
        )

    async def start(
        self,
        scope_id: str,
        *,
        trigger_type: str = "manual",
        parent_collection_run_id: str | None = None,
        schedule_id: str | None = None,
        youtube_run_search_call_budget: int | None = None,
        youtube_run_shared_unit_budget: int | None = None,
    ) -> dict[str, Any]:
        scope = self.service.get_scope(scope_id)
        if scope["platform"] == "youtube":
            collector = YouTubeCollector(
                self.service,
                api_key=self.youtube_api_key,
                proxy_url=self.outbound_proxy,
            )
        elif scope["platform"] == "mastodon":
            collector = MastodonCollector(
                self.service,
                access_tokens=self.mastodon_access_tokens,
                proxy_url=self.outbound_proxy,
            )
        elif scope["platform"] == "reddit":
            collector = RedditCollector(
                self.service,
                client_id=self.reddit_client_id,
                client_secret=self.reddit_client_secret,
                refresh_token=self.reddit_refresh_token,
                user_agent=self.reddit_user_agent,
                proxy_url=self.outbound_proxy,
            )
        elif scope["platform"] == "tiktok":
            if not (
                self.tiktok_client_key
                and self.tiktok_client_secret
                and self.outbound_proxy == REQUIRED_OUTBOUND_PROXY
            ):
                raise ValueError(
                    "TikTok Research API 凭证或固定出站代理未配置"
                )
            collector = TikTokCollector(
                self.service,
                client_key=self.tiktok_client_key,
                client_secret=self.tiktok_client_secret,
                proxy_url=self.outbound_proxy,
            )
        elif scope["platform"] == "x":
            if not (
                self.x_bearer_token
                and self.outbound_proxy == REQUIRED_OUTBOUND_PROXY
            ):
                raise ValueError("X API bearer token 或固定出站代理未配置")
            collector = XCollector(
                self.service,
                bearer_token=self.x_bearer_token,
                proxy_url=self.outbound_proxy,
            )
        elif scope["platform"] == "bluesky":
            collector = BlueskyCollector(self.service, proxy_url=self.outbound_proxy)
        else:
            raise ValueError(f"不支持的采集平台：{scope['platform']}")
        manifest = self.service.start_run(
            scope_id,
            trigger_type=trigger_type,
            parent_collection_run_id=parent_collection_run_id,
            schedule_id=schedule_id,
            youtube_run_search_call_budget=youtube_run_search_call_budget,
            youtube_run_shared_unit_budget=youtube_run_shared_unit_budget,
        )
        run_id = manifest["collection_run_id"]
        task = asyncio.create_task(
            self._collect(collector, run_id, manifest["sampling"]["max_items"]),
            name=run_id,
        )
        self.tasks[run_id] = task
        task.add_done_callback(lambda completed: self._task_done(run_id, completed))
        return {**manifest, "runtime_status": "running"}

    async def retry(self, collection_run_id: str) -> dict[str, Any]:
        run = self.service.get_run(collection_run_id)
        scope_id = run.get("scope_id")
        if not scope_id:
            raise KeyError(collection_run_id)
        return await self.start(
            scope_id,
            trigger_type="retry",
            parent_collection_run_id=collection_run_id,
        )

    async def continue_after_screening(self, collection_run_id: str) -> dict[str, Any]:
        run = self.service.get_run(collection_run_id)
        if run.get("platform") != "youtube" or run.get("status") != "awaiting_screening":
            raise ValueError("只有等待视频筛选的 YouTube 运行可以继续")
        if collection_run_id in self.tasks:
            raise ValueError("该运行已经在采集中")
        scopes = self.service.run_scope_snapshots(collection_run_id)
        if not scopes:
            raise ValueError("YouTube run 没有冻结 query")
        collector = YouTubeCollector(
            self.service,
            api_key=self.youtube_api_key,
            proxy_url=self.outbound_proxy,
        )
        task = asyncio.create_task(
            self._collect(collector, collection_run_id, int(scopes[0]["max_items"])),
            name=collection_run_id,
        )
        self.tasks[collection_run_id] = task
        task.add_done_callback(
            lambda completed: self._task_done(collection_run_id, completed)
        )
        return {
            "collection_run_id": collection_run_id,
            "platform": "youtube",
            "runtime_status": "running",
        }

    async def stop(self, collection_run_id: str) -> dict[str, Any]:
        task = self.tasks.get(collection_run_id)
        if task is None:
            raise KeyError(collection_run_id)
        task.cancel()
        return await task

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _x_credentials_configured(manager: CollectorManager) -> bool:
    return bool(
        manager.x_bearer_token
        and manager.outbound_proxy == REQUIRED_OUTBOUND_PROXY
    )


def _x_public_billing(status: dict[str, Any]) -> dict[str, Any]:
    price = status.get("active_price")
    public_price = None
    if isinstance(price, dict):
        public_price = {
            key: price.get(key)
            for key in (
                "resource_type",
                "unit_price_microusd",
                "unit_price_usd",
                "currency",
                "effective_date",
                "pricing_policy_version",
            )
        }
    return {
        "local_cycle_spending_cap_microusd": status.get(
            "local_cycle_spending_cap_microusd"
        ),
        "console_hard_spending_limit_microusd": status.get(
            "console_hard_spending_limit_microusd"
        ),
        "billing_cycle_start": status.get("billing_cycle_start"),
        "billing_cycle_end": status.get("billing_cycle_end"),
        "console_limit_confirmed": bool(status.get("console_limit_confirmed")),
        "circuit_breaker_open": bool(status.get("circuit_breaker_open")),
        "circuit_breaker_reason": status.get("circuit_breaker_reason"),
        "accrued_cost_microusd": status.get("accrued_cost_microusd"),
        "reserved_exposure_microusd": status.get(
            "reserved_exposure_microusd"
        ),
        "remaining_local_cycle_microusd": status.get(
            "remaining_local_cycle_microusd"
        ),
        "active_price": public_price,
    }


def _x_collection_ready(
    manager: CollectorManager, status: dict[str, Any]
) -> bool:
    start = _parse_datetime(status.get("billing_cycle_start"))
    end = _parse_datetime(status.get("billing_cycle_end"))
    now = datetime.now(timezone.utc)
    return bool(
        _x_credentials_configured(manager)
        and status.get("console_limit_confirmed")
        and not status.get("circuit_breaker_open")
        and isinstance(start, datetime)
        and isinstance(end, datetime)
        and start <= now < end
        and isinstance(status.get("remaining_local_cycle_microusd"), int)
        and status["remaining_local_cycle_microusd"] > 0
        and isinstance(status.get("active_price"), dict)
    )


def create_app(
    database_path: Path | str,
    *,
    outbound_proxy: str | None = None,
    export_root: Path | str | None = None,
    backup_root: Path | str | None = None,
    youtube_api_key: str | None = None,
    mastodon_access_tokens: dict[str, str] | None = None,
    reddit_client_id: str | None = None,
    reddit_client_secret: str | None = None,
    reddit_refresh_token: str | None = None,
    reddit_user_agent: str | None = None,
    tiktok_client_key: str | None = None,
    tiktok_client_secret: str | None = None,
    x_bearer_token: str | None = None,
) -> FastAPI:
    database_path = Path(database_path)
    resolved_export_root = Path(export_root) if export_root else database_path.parent / "exports"
    resolved_backup_root = Path(backup_root) if backup_root else database_path.parent / "backups"
    service = SocialNarrativeService(database_path)
    if mastodon_access_tokens is None:
        raw_tokens = os.environ.get("GLYPH_MASTODON_ACCESS_TOKENS_JSON", "").strip()
        if raw_tokens:
            try:
                parsed_tokens = json.loads(raw_tokens)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "GLYPH_MASTODON_ACCESS_TOKENS_JSON 必须是有效 JSON 对象"
                ) from error
            if not isinstance(parsed_tokens, dict) or not all(
                isinstance(instance, str) and isinstance(token, str)
                for instance, token in parsed_tokens.items()
            ):
                raise ValueError(
                    "GLYPH_MASTODON_ACCESS_TOKENS_JSON 必须是实例到令牌的 JSON 对象"
                )
            mastodon_access_tokens = parsed_tokens
    manager = CollectorManager(
        service,
        outbound_proxy,
        youtube_api_key if youtube_api_key is not None else os.environ.get("GLYPH_YOUTUBE_API_KEY"),
        mastodon_access_tokens,
        reddit_client_id=(
            reddit_client_id
            if reddit_client_id is not None
            else os.environ.get("GLYPH_REDDIT_CLIENT_ID")
        ),
        reddit_client_secret=(
            reddit_client_secret
            if reddit_client_secret is not None
            else os.environ.get("GLYPH_REDDIT_CLIENT_SECRET")
        ),
        reddit_refresh_token=(
            reddit_refresh_token
            if reddit_refresh_token is not None
            else os.environ.get("GLYPH_REDDIT_REFRESH_TOKEN")
        ),
        reddit_user_agent=(
            reddit_user_agent
            if reddit_user_agent is not None
            else os.environ.get("GLYPH_REDDIT_USER_AGENT")
        ),
        tiktok_client_key=(
            tiktok_client_key
            if tiktok_client_key is not None
            else os.environ.get("GLYPH_TIKTOK_CLIENT_KEY")
        ),
        tiktok_client_secret=(
            tiktok_client_secret
            if tiktok_client_secret is not None
            else os.environ.get("GLYPH_TIKTOK_CLIENT_SECRET")
        ),
        x_bearer_token=(
            x_bearer_token
            if x_bearer_token is not None
            else os.environ.get("GLYPH_X_BEARER_TOKEN")
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await manager.startup()
        yield
        await manager.shutdown()

    app = FastAPI(title="GLYPH 社会叙事", version="0.6.0", lifespan=lifespan)
    app.state.service = service
    app.state.collectors = manager
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/scopes")
    def list_scopes() -> list[dict[str, Any]]:
        return service.list_scopes()

    @app.get("/api/registries")
    def registries() -> dict[str, Any]:
        try:
            return service.registries()
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/scopes", status_code=201)
    def create_scope(data: ScopeInput) -> dict[str, Any]:
        try:
            return service.create_scope(**data.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/scopes/{scope_id}")
    def update_scope(scope_id: str, data: ScopeUpdateInput) -> dict[str, Any]:
        try:
            scope = service.update_scope(scope_id, **data.model_dump())
            for schedule in service.list_schedules():
                if schedule["scope_id"] == scope_id:
                    manager.sync_schedule(schedule)
            return scope
        except KeyError as error:
            raise HTTPException(status_code=404, detail="研究范围不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/scopes/{scope_id}/queries")
    def scope_queries(scope_id: str) -> list[dict[str, Any]]:
        try:
            return service.get_scope(scope_id)["queries"]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="研究范围不存在") from error

    @app.post("/api/scopes/{scope_id}/queries", status_code=201)
    def add_scope_query(scope_id: str, data: ScopeQueryInput) -> dict[str, Any]:
        try:
            return service.add_scope_query(scope_id, **data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="研究范围不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        active = set(manager.tasks)
        rows = service.list_runs()
        for row in rows:
            row["runtime_status"] = "running" if row["collection_run_id"] in active else row["status"]
        return rows

    @app.post("/api/runs", status_code=202)
    async def start_run(data: StartRunInput) -> dict[str, Any]:
        try:
            return await manager.start(**data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="研究范围不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/runs/{collection_run_id}/stop")
    async def stop_run(collection_run_id: str) -> dict[str, Any]:
        try:
            return await manager.stop(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行任务不存在或已经结束") from error

    @app.post("/api/runs/{collection_run_id}/retry", status_code=202)
    async def retry_run(collection_run_id: str) -> dict[str, Any]:
        try:
            return await manager.retry(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行任务不存在或无法重跑") from error

    @app.post("/api/runs/{collection_run_id}/continue", status_code=202)
    async def continue_run(collection_run_id: str) -> dict[str, Any]:
        try:
            return await manager.continue_after_screening(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/schedules")
    def list_schedules() -> list[dict[str, Any]]:
        return service.list_schedules()

    @app.post("/api/schedules", status_code=201)
    def create_schedule(data: ScheduleInput) -> dict[str, Any]:
        try:
            schedule = service.create_schedule(**data.model_dump())
            manager.sync_schedule(schedule)
            return schedule
        except KeyError as error:
            raise HTTPException(status_code=404, detail="研究范围不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/schedules/{schedule_id}/run", status_code=202)
    async def run_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return await manager._run_schedule(schedule_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="调度任务或研究范围不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put("/api/schedules/{schedule_id}")
    def update_schedule(schedule_id: str, data: ScheduleUpdateInput) -> dict[str, Any]:
        try:
            schedule = service.update_schedule(schedule_id, **data.model_dump())
            manager.sync_schedule(schedule)
            return schedule
        except KeyError as error:
            raise HTTPException(status_code=404, detail="调度任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/review-queue")
    def review_queue(
        collection_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return service.review_queue(collection_run_id)

    @app.get("/api/screening-queue")
    def screening_queue(
        collection_run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return service.screening_queue(collection_run_id)

    @app.get("/api/observations")
    def observations(status: str | None = None) -> list[dict[str, Any]]:
        return service.observations(status)

    @app.get("/api/observations/{observation_id}/registry")
    def observation_registry(observation_id: str) -> dict[str, Any]:
        try:
            return service.observation_registry(observation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="观察记录不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/observations/{observation_id}/review")
    def review(observation_id: str, data: ReviewInput) -> dict[str, Any]:
        try:
            return service.review_observation(observation_id, **data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="观察记录不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/observations/{observation_id}/independent-annotations", status_code=201)
    def submit_independent_annotation(
        observation_id: str, data: IndependentAnnotationInput
    ) -> dict[str, Any]:
        try:
            return service.submit_independent_annotation(
                observation_id, **data.model_dump()
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="观察记录不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/observations/{observation_id}/adjudicate", status_code=201)
    def adjudicate(
        observation_id: str, data: AdjudicationInput
    ) -> dict[str, Any]:
        try:
            return service.adjudicate_observation(observation_id, **data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="观察记录不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/runs/{collection_run_id}/quality")
    def evaluate_quality(collection_run_id: str) -> dict[str, Any]:
        try:
            return service.evaluate_run_quality(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error

    @app.get("/api/runs/{collection_run_id}/quality")
    def quality_reports(collection_run_id: str) -> list[dict[str, Any]]:
        try:
            return service.quality_reports(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error

    @app.get("/api/runs/{collection_run_id}/quality-workspace")
    def quality_workspace(collection_run_id: str) -> dict[str, Any]:
        try:
            return service.quality_workspace(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error

    @app.post("/api/runs/{collection_run_id}/query-yield")
    def evaluate_query_yield(collection_run_id: str) -> dict[str, Any]:
        try:
            return service.evaluate_query_yield(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/runs/{collection_run_id}/query-yield")
    def query_yield_workspace(collection_run_id: str) -> dict[str, Any]:
        try:
            return service.query_yield_workspace(collection_run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/runs/{collection_run_id}/query-yield/promote")
    def promote_query_yield(
        collection_run_id: str,
        data: QueryPromotionInput,
    ) -> dict[str, Any]:
        try:
            return service.promote_calibrated_queries(
                collection_run_id, **data.model_dump()
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/runs/{collection_run_id}/independent-annotations")
    def independent_annotations(collection_run_id: str) -> list[dict[str, Any]]:
        return service.independent_annotations(collection_run_id)

    @app.get("/api/runs/{collection_run_id}/adjudications")
    def adjudications(collection_run_id: str) -> list[dict[str, Any]]:
        return service.adjudications(collection_run_id)

    @app.post("/api/runs/{collection_run_id}/release")
    def set_release(
        collection_run_id: str, data: ReleaseInput
    ) -> dict[str, Any]:
        try:
            return service.set_run_release(collection_run_id, **data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/observations/{observation_id}/screen")
    def screen(observation_id: str, data: ScreeningInput) -> dict[str, Any]:
        try:
            return service.screen_observation(observation_id, **data.model_dump())
        except KeyError as error:
            raise HTTPException(status_code=404, detail="观察记录不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/screening-history")
    def screening_history(observation_id: str | None = None) -> list[dict[str, Any]]:
        return service.screening_history(observation_id)

    @app.get("/api/review-history")
    def review_history(observation_id: str | None = None) -> list[dict[str, Any]]:
        return service.review_history(observation_id)

    @app.get("/api/analysis")
    def analysis() -> dict[str, Any]:
        return service.analysis()

    @app.get("/api/evidence/{observation_id}")
    def evidence(observation_id: str) -> dict[str, Any]:
        try:
            return service.evidence(observation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="证据记录不存在") from error

    @app.get("/api/errors")
    def errors(collection_run_id: str | None = None) -> list[dict[str, Any]]:
        return service.errors(collection_run_id)

    @app.get("/api/audit")
    def audit(limit: int = 100) -> list[dict[str, Any]]:
        return service.audit(max(1, min(limit, 500)))

    @app.post("/api/runs/{collection_run_id}/export")
    def export_run(collection_run_id: str) -> dict[str, Any]:
        try:
            result = service.export_run(collection_run_id, resolved_export_root)
            result["download_url"] = f"/api/exports/{collection_run_id}"
            return result
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行任务不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/exports/{collection_run_id}")
    def download_export(collection_run_id: str) -> FileResponse:
        archive = resolved_export_root / f"{collection_run_id}.zip"
        if not archive.is_file():
            raise HTTPException(status_code=404, detail="导出包不存在")
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=archive.name,
        )

    @app.get("/api/backups")
    def backups() -> list[dict[str, Any]]:
        return service.list_backups(resolved_backup_root)

    @app.post("/api/backups", status_code=201)
    def backup() -> dict[str, Any]:
        return service.create_backup(resolved_backup_root)

    @app.post("/api/backups/{backup_id}/restore")
    def restore(backup_id: str) -> dict[str, Any]:
        if manager.tasks:
            raise HTTPException(status_code=409, detail="请先停止所有活动采集任务")
        manager.scheduler.pause()
        try:
            result = service.restore_backup(resolved_backup_root, backup_id)
            service.recover_interrupted_runs()
            manager.scheduler.remove_all_jobs()
            for schedule in service.list_schedules():
                manager.sync_schedule(schedule)
            return result
        except KeyError as error:
            raise HTTPException(status_code=404, detail="备份不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            manager.scheduler.resume()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        with ResearchStore(database_path) as store:
            observation_count = store.table_count("observations")
        x_billing = service.x_billing_status()
        return {
            "database": "ok",
            "platforms": ["bluesky", "youtube", "mastodon", "reddit", "tiktok", "x"],
            "active_runs": len(manager.tasks),
            "scheduler_running": manager.scheduler.running,
            "enabled_schedules": sum(
                1 for schedule in service.list_schedules() if schedule["enabled"]
            ),
            "cursor": service.cursor(),
            "youtube_quota": service.youtube_quota_status(),
            "youtube_api_key_configured": bool(manager.youtube_api_key),
            "mastodon_access_token_count": len(manager.mastodon_access_tokens),
            "reddit_credentials_configured": bool(
                manager.reddit_client_id
                and manager.reddit_client_secret
                and manager.reddit_user_agent
                and manager.outbound_proxy
            ),
            "reddit_authorization_mode": (
                "refresh_token" if manager.reddit_refresh_token else "app_only"
            ),
            "tiktok_credentials_configured": bool(
                manager.tiktok_client_key
                and manager.tiktok_client_secret
                and manager.outbound_proxy == REQUIRED_OUTBOUND_PROXY
            ),
            "tiktok_quota": service.tiktok_quota_status(),
            "x_credentials_configured": _x_credentials_configured(manager),
            "x_collection_ready": _x_collection_ready(manager, x_billing),
            "x_billing": _x_public_billing(x_billing),
            "observations": observation_count,
            "errors": len(service.errors()),
            "outbound_proxy_configured": outbound_proxy is not None,
        }

    @app.get("/api/monitoring")
    def monitoring() -> dict[str, Any]:
        status = service.monitoring(resolved_backup_root)
        x_billing = service.x_billing_status()
        status["active_runs"] = len(manager.tasks)
        status["scheduler_running"] = manager.scheduler.running
        status["youtube_api_key_configured"] = bool(manager.youtube_api_key)
        status["mastodon_access_token_count"] = len(manager.mastodon_access_tokens)
        status["reddit_credentials_configured"] = bool(
            manager.reddit_client_id
            and manager.reddit_client_secret
            and manager.reddit_user_agent
            and manager.outbound_proxy
        )
        status["reddit_authorization_mode"] = (
            "refresh_token" if manager.reddit_refresh_token else "app_only"
        )
        status["tiktok_credentials_configured"] = bool(
            manager.tiktok_client_key
            and manager.tiktok_client_secret
            and manager.outbound_proxy == REQUIRED_OUTBOUND_PROXY
        )
        status["x_credentials_configured"] = _x_credentials_configured(manager)
        status["x_collection_ready"] = _x_collection_ready(manager, x_billing)
        status["x_billing"] = _x_public_billing(x_billing)
        return status

    @app.get("/api/youtube/quota")
    def youtube_quota() -> dict[str, Any]:
        return service.youtube_quota_status()

    @app.put("/api/youtube/quota")
    def update_youtube_quota(data: YouTubeQuotaInput) -> dict[str, Any]:
        current = service.youtube_quota_status()
        service.set_youtube_quota_budgets(
            shared_unit_budget=data.daily_budget,
            search_call_budget=(
                data.search_daily_call_budget
                if data.search_daily_call_budget is not None
                else current["search_daily_call_budget"]
            ),
        )
        return service.youtube_quota_status()

    return app
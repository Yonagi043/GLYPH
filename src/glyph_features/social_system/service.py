"""Application service preserving the frozen social-narrative analysis rules."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.normalize_social_records import _normalization_hash_payload, source_row
from tools.social_io import canonical_json, schema_validator, validation_errors, validator
from tools.summarize_narratives import build_context_outputs, build_matrices

from .bluesky import JETSTREAM_ENDPOINT, ResearchScope, event_cursor, normalize_jetstream_event
from .backups import create_backup, list_backups, restore_backup
from .exports import build_export
from .mastodon import normalize_instance, normalize_mastodon_status
from .reddit import (
    normalize_reddit_post,
    normalize_subreddit,
    reddit_content_status,
    reddit_created_utc,
)
from .tiktok import (
    normalize_tiktok_comment,
    normalize_tiktok_query,
    normalize_tiktok_video,
    tiktok_date_window,
)
from .registries import (
    load_registry_snapshot,
    validate_registered_object,
    validate_registered_terms,
)
from .quality import agreement_passes, build_agreement_report
from .query_yield import DEFAULT_POLICY, build_query_yield_report, validate_policy
from .storage import LEGACY_YOUTUBE_QUOTA_POLICY, SCHEMA_VERSION, ResearchStore
from .youtube import (
    LEGACY_YOUTUBE_QUOTA_COSTS,
    YOUTUBE_QUOTA_COSTS,
    normalize_youtube_comment,
    normalize_youtube_video,
)
from .x import X_POST_FIELDS, normalize_x_post, sanitize_x_post


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_SCHEMA = ROOT / "schema" / "social_run_manifest.schema.json"
OBJECT_TYPES = {"writing_system", "script", "style_family", "font", "stimulus", "brand"}
STANCES = {"positive", "negative", "mixed", "descriptive", "counterexample", "unclear"}
AUTHOR_ROLES = {
    "brand", "design_studio", "designer", "design_media", "researcher",
    "ordinary_user", "creator",
}
REVIEWER_REF = "annotator_local01"
SUPPORTED_PLATFORMS = {"bluesky", "youtube", "mastodon", "reddit", "tiktok", "x"}
QUERY_FAMILIES = {
    "object_aesthetic",
    "object_context",
    "aesthetic_context",
    "legacy_scope_keywords",
}
QUERY_PHASES = {"exploratory", "calibration", "confirmatory"}
PLATFORM_RUN_CONFIG = {
    "bluesky": {
        "sampling_method": "realtime_stream",
        "page_size": None,
        "sort_order": "Jetstream v2 seq ascending",
        "collector_tool": "GLYPH Bluesky Jetstream collector",
        "endpoint": JETSTREAM_ENDPOINT,
        "api_version": "network.bsky.jetstream.subscribeEvents v2",
        "coverage": "公开 Jetstream 中符合登记条件的实时事件，不代表 Bluesky 全网样本。",
    },
    "youtube": {
        "sampling_method": "api_pagination",
        "page_size": 50,
        "sort_order": "YouTube relevance order; publishedAfter/publishedBefore bounded",
        "collector_tool": "GLYPH YouTube Data API collector",
        "endpoint": "https://www.googleapis.com/youtube/v3",
        "api_version": "v3",
        "coverage": "符合登记查询、语言与时间窗的 YouTube API 搜索结果及其公开评论，不代表 YouTube 全网样本。",
    },
    "mastodon": {
        "sampling_method": "api_pagination",
        "page_size": 40,
        "sort_order": "instance-local status id descending",
        "collector_tool": "GLYPH Mastodon REST API collector",
        "endpoint": "instance-relative Mastodon REST API",
        "api_version": "Mastodon REST API v1/v2",
        "coverage": "选定实例中符合冻结 hashtag 或搜索查询的公开状态，不代表 Mastodon 全网样本。",
    },
    "reddit": {
        "sampling_method": "api_pagination",
        "page_size": 100,
        "sort_order": "query-defined subreddit listing order",
        "collector_tool": "GLYPH Reddit Data API collector",
        "endpoint": "https://oauth.reddit.com",
        "api_version": "Reddit Data API OAuth2",
        "coverage": "选定 subreddit 中符合冻结查询与时间窗的 API listing，不代表 Reddit 全网样本。",
    },
    "tiktok": {
        "sampling_method": "api_pagination",
        "page_size": 100,
        "sort_order": "TikTok Research API query order",
        "collector_tool": "GLYPH TikTok Research API collector",
        "endpoint": "https://open.tiktokapis.com/v2/research",
        "api_version": "v2 Research API 2026-09-01",
        "coverage": "符合冻结条件 AST 与 UTC 日历窗口的视频及其有界评论/回复，不代表 TikTok 全网样本。",
    },
    "x": {
        "sampling_method": "api_pagination",
        "page_size": 100,
        "sort_order": "X API v2 recent-search recency order",
        "collector_tool": "GLYPH X API v2 recent-search collector",
        "endpoint": "https://api.x.com/2/tweets/search/recent",
        "api_version": "X API v2 2026-09-02 snapshot",
        "coverage": "符合冻结查询与最近七天窗口的有界公开 post，不代表 X 全网样本。",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mastodon_platform_options(
    *,
    platform: str,
    exact_query: str,
    instances: list[str] | None,
    access_method: str,
    page_size: int,
    max_pages_per_instance: int,
    request_delay_seconds: float,
) -> dict[str, Any] | None:
    if platform != "mastodon":
        if instances:
            raise ValueError("只有 Mastodon 范围可以配置实例")
        return None
    clean_instances = sorted(
        {normalize_instance(value) for value in instances or []}, key=str.casefold
    )
    if not 1 <= len(clean_instances) <= 10:
        raise ValueError("Mastodon 范围必须配置 1 到 10 个实例")
    if access_method not in {"hashtag_timeline", "search_statuses"}:
        raise ValueError("无效的 Mastodon 访问方式")
    if access_method == "hashtag_timeline" and not re.fullmatch(
        r"#[^\W_][\w]*", exact_query, flags=re.UNICODE
    ):
        raise ValueError("Mastodon hashtag timeline 的精确查询必须是单个 #hashtag")
    if not 1 <= page_size <= 40:
        raise ValueError("Mastodon 每页上限必须在 1 到 40 之间")
    if not 1 <= max_pages_per_instance <= 20:
        raise ValueError("Mastodon 每实例页数上限必须在 1 到 20 之间")
    if not 0 <= request_delay_seconds <= 60:
        raise ValueError("Mastodon 请求间隔必须在 0 到 60 秒之间")
    return {
        "access_method": access_method,
        "instances": clean_instances,
        "max_pages_per_instance": max_pages_per_instance,
        "page_size": page_size,
        "request_delay_seconds": float(request_delay_seconds),
    }


def _reddit_platform_options(
    *,
    platform: str,
    subreddits: list[str] | None,
    access_method: str,
    sort: str,
    time_filter: str,
    page_size: int,
    max_pages_per_subreddit: int,
    request_delay_seconds: float,
) -> dict[str, Any] | None:
    if platform != "reddit":
        if subreddits:
            raise ValueError("只有 Reddit 范围可以配置 subreddit")
        return None
    clean_subreddits = sorted(
        {normalize_subreddit(value) for value in subreddits or []}, key=str.casefold
    )
    if not 1 <= len(clean_subreddits) <= 10:
        raise ValueError("Reddit 范围必须配置 1 到 10 个 subreddit")
    if access_method not in {"subreddit_search", "subreddit_new"}:
        raise ValueError("无效的 Reddit 访问方式")
    if sort not in {"relevance", "hot", "top", "new", "comments"}:
        raise ValueError("无效的 Reddit 排序方式")
    if access_method == "subreddit_new" and sort != "new":
        raise ValueError("Reddit new listing 的排序方式必须是 new")
    if time_filter not in {"hour", "day", "week", "month", "year", "all"}:
        raise ValueError("无效的 Reddit 时间范围")
    if not 1 <= page_size <= 100:
        raise ValueError("Reddit 每页上限必须在 1 到 100 之间")
    if not 1 <= max_pages_per_subreddit <= 20:
        raise ValueError("Reddit 每 subreddit 页数上限必须在 1 到 20 之间")
    if not 0 <= request_delay_seconds <= 60:
        raise ValueError("Reddit 请求间隔必须在 0 到 60 秒之间")
    return {
        "access_method": access_method,
        "max_pages_per_subreddit": max_pages_per_subreddit,
        "page_size": page_size,
        "request_delay_seconds": float(request_delay_seconds),
        "sort": sort,
        "subreddits": clean_subreddits,
        "time_filter": time_filter,
    }


def _tiktok_platform_options(
    *,
    platform: str,
    window_start: str,
    window_end: str,
    query: dict[str, Any] | None,
    video_page_size: int,
    max_video_pages: int,
    comment_page_size: int,
    max_comment_pages_per_video: int,
    reply_page_size: int,
    max_reply_pages_per_comment: int,
    request_delay_seconds: float,
) -> dict[str, Any] | None:
    if platform != "tiktok":
        if query is not None:
            raise ValueError("只有 TikTok 范围可以配置 Research API query AST")
        return None
    start_date, end_date = tiktok_date_window(window_start, window_end)
    if not 1 <= video_page_size <= 100:
        raise ValueError("TikTok 每页视频数必须在 1 到 100 之间")
    if not 1 <= max_video_pages <= 20:
        raise ValueError("TikTok 视频页数必须在 1 到 20 之间")
    if not 1 <= comment_page_size <= 100:
        raise ValueError("TikTok 每页评论数必须在 1 到 100 之间")
    if not 1 <= max_comment_pages_per_video <= 20:
        raise ValueError("TikTok 每视频评论页数必须在 1 到 20 之间")
    if not 1 <= reply_page_size <= 100:
        raise ValueError("TikTok 每页回复数必须在 1 到 100 之间")
    if not 1 <= max_reply_pages_per_comment <= 20:
        raise ValueError("TikTok 每评论回复页数必须在 1 到 20 之间")
    if not 0 <= request_delay_seconds <= 60:
        raise ValueError("TikTok 请求间隔必须在 0 到 60 秒之间")
    return {
        "comment_page_size": comment_page_size,
        "daily_request_limit": 1000,
        "end_date": end_date,
        "max_comment_pages_per_video": max_comment_pages_per_video,
        "max_reply_pages_per_comment": max_reply_pages_per_comment,
        "max_video_pages": max_video_pages,
        "query": normalize_tiktok_query(query or {}),
        "quota_policy_version": "tiktok_research_api_2026-09-01",
        "reply_page_size": reply_page_size,
        "request_delay_seconds": float(request_delay_seconds),
        "start_date": start_date,
        "video_page_size": video_page_size,
    }


def _x_platform_options(
    *,
    platform: str,
    exact_query: str,
    window_start: str,
    window_end: str,
    page_size: int,
    max_pages: int,
    request_delay_seconds: float,
    local_run_budget_microusd: int,
) -> dict[str, Any] | None:
    if platform != "x":
        return None

    def parse_utc(value: str) -> datetime:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise ValueError("X recent-search 窗口必须是 ISO-8601 时间") from error
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("X recent-search 窗口必须使用 UTC")
        return parsed.astimezone(timezone.utc)

    start = parse_utc(window_start)
    end = parse_utc(window_end)
    if end < start or end - start > timedelta(days=7):
        raise ValueError("X recent-search 窗口不得超过 7 天")
    if not exact_query or len(exact_query) > 1024:
        raise ValueError("X recent-search query 长度必须在 1 到 1024 之间")
    if not 10 <= page_size <= 100:
        raise ValueError("X recent-search 每页数量必须在 10 到 100 之间")
    if not 1 <= max_pages <= 20:
        raise ValueError("X recent-search 页数必须在 1 到 20 之间")
    if not 0 <= request_delay_seconds <= 60:
        raise ValueError("X recent-search 请求间隔必须在 0 到 60 秒之间")
    if isinstance(local_run_budget_microusd, bool) or not (
        1 <= local_run_budget_microusd <= 1_000_000_000_000
    ):
        raise ValueError("X 本机 run 预算必须是正整数微美元")
    return {
        "access_method": "recent_search",
        "end_time": end.isoformat().replace("+00:00", "Z"),
        "local_run_budget_microusd": local_run_budget_microusd,
        "max_pages": max_pages,
        "page_size": page_size,
        "post_fields": X_POST_FIELDS,
        "query": exact_query,
        "request_delay_seconds": float(request_delay_seconds),
        "start_time": start.isoformat().replace("+00:00", "Z"),
    }


def _build_query(
    *,
    platform: str,
    object_type: str,
    object_label: str,
    keywords: list[str],
    languages: list[str],
    window_start: str,
    window_end: str,
    max_items: int,
    registry_snapshot: dict[str, Any],
    query_family: str,
    phase: str,
    exact_query: str,
    max_videos: int,
    max_comment_threads_per_video: int,
    max_replies_per_thread: int,
    query_yield_policy: dict[str, Any] | None = None,
    promotion_evidence: dict[str, Any] | None = None,
    supersedes_query_id: str | None = None,
    platform_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_config = PLATFORM_RUN_CONFIG[platform]
    layer_quotas = {
        "max_videos": max_videos,
        "max_comment_threads_per_video": max_comment_threads_per_video,
        "max_replies_per_thread": max_replies_per_thread,
    }
    yield_policy = validate_policy(query_yield_policy or DEFAULT_POLICY)
    snapshot = {
        "platform": platform,
        "object_type": object_type,
        "object_label": object_label,
        "keywords": keywords,
        "languages": languages,
        "window_start": window_start,
        "window_end": window_end,
        "max_items": max_items,
        "sampling_method": run_config["sampling_method"],
        "sort_order": run_config["sort_order"],
        "query_family": query_family,
        "phase": phase,
        "exact_query": exact_query,
        "layer_quotas": layer_quotas,
        "query_yield_policy": yield_policy,
        "promotion_evidence": promotion_evidence,
        "object_map_version": registry_snapshot["object_map_version"],
        "object_map_sha256": registry_snapshot["object_map_sha256"],
        "codebook_version": registry_snapshot["codebook_version"],
        "codebook_sha256": registry_snapshot["codebook_sha256"],
    }
    if platform_options is not None:
        snapshot["platform_options"] = platform_options
    config_sha256 = hashlib.sha256(
        canonical_json(snapshot).encode("utf-8")
    ).hexdigest()
    version_payload = {
        "config_sha256": config_sha256,
        "supersedes_query_id": supersedes_query_id,
    }
    digest = hashlib.sha256(
        canonical_json(version_payload).encode("utf-8")
    ).hexdigest()[:16]
    query = {
        "query_id": f"q_{platform}_{digest}",
        "platform": platform,
        "language_bcp47": "|".join(languages),
        "region_hint": "INTL",
        "object_group": object_label,
        "query_text": exact_query,
        "aesthetic_terms": "",
        "brand_context": "",
        "window_start": window_start,
        "window_end": window_end,
        "max_items": max_items,
        "sampling_method": run_config["sampling_method"],
        "deduplication_rule": "collection_run_id + platform_item_id",
        "inclusion_rule": "关键词、语言和发布时间均位于已登记范围内。",
        "exclusion_rule": "范围外、不可解析、删除或非公开记录。",
        "owner": "GLYPH local researcher",
        "status": "active",
        "notes": run_config["coverage"],
        "query_family": query_family,
        "phase": phase,
        "exact_query": exact_query,
        "sort_order": run_config["sort_order"],
        "object_type_target": object_type,
        "object_label_target": object_label,
        "keywords": keywords,
        "languages": languages,
        "query_config_sha256": config_sha256,
        "supersedes_query_id": supersedes_query_id,
        "object_map_version": registry_snapshot["object_map_version"],
        "object_map_sha256": registry_snapshot["object_map_sha256"],
        "codebook_version": registry_snapshot["codebook_version"],
        "codebook_sha256": registry_snapshot["codebook_sha256"],
        "registry_snapshot": registry_snapshot,
        "layer_quotas": layer_quotas,
        "query_yield_policy": yield_policy,
        "promotion_evidence": promotion_evidence,
    }
    if platform_options is not None:
        query["platform_options"] = platform_options
    return query


class SocialNarrativeService:
    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def create_scope(
        self,
        *,
        platform: str = "bluesky",
        name: str,
        object_type: str,
        object_label: str,
        keywords: list[str],
        languages: list[str],
        window_start: str,
        window_end: str,
        max_items: int,
        query_family: str = "legacy_scope_keywords",
        phase: str = "exploratory",
        exact_query: str | None = None,
        max_videos: int | None = None,
        max_comment_threads_per_video: int = 100,
        max_replies_per_thread: int = 100,
        query_yield_evaluation_k: int = 20,
        query_yield_min_included_at_k: int = 5,
        query_yield_min_precision_at_k: float = 0.25,
        query_yield_min_precision_lower_bound: float = 0.10,
        query_yield_confidence_level: float = 0.95,
        mastodon_instances: list[str] | None = None,
        mastodon_access_method: str = "hashtag_timeline",
        mastodon_page_size: int = 40,
        mastodon_max_pages_per_instance: int = 1,
        mastodon_request_delay_seconds: float = 1.0,
        reddit_subreddits: list[str] | None = None,
        reddit_access_method: str = "subreddit_search",
        reddit_sort: str = "relevance",
        reddit_time_filter: str = "all",
        reddit_page_size: int = 100,
        reddit_max_pages_per_subreddit: int = 1,
        reddit_request_delay_seconds: float = 1.0,
        tiktok_query: dict[str, Any] | None = None,
        tiktok_video_page_size: int = 100,
        tiktok_max_video_pages: int = 1,
        tiktok_comment_page_size: int = 100,
        tiktok_max_comment_pages_per_video: int = 1,
        tiktok_reply_page_size: int = 100,
        tiktok_max_reply_pages_per_comment: int = 1,
        tiktok_request_delay_seconds: float = 1.0,
        x_page_size: int = 100,
        x_max_pages: int = 1,
        x_request_delay_seconds: float = 1.0,
        x_local_run_budget_microusd: int = 500_000,
    ) -> dict[str, Any]:
        clean_keywords = sorted({value.strip() for value in keywords if value.strip()}, key=str.casefold)
        clean_languages = sorted({value.strip() for value in languages if value.strip()}, key=str.casefold)
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("当前系统不支持该采集平台")
        if not name.strip() or not object_label.strip() or object_type not in OBJECT_TYPES:
            raise ValueError("研究名称、对象类型和对象标签不能为空")
        if not clean_keywords or not clean_languages:
            raise ValueError("至少需要一个关键词和一种语言")
        registry_snapshot = load_registry_snapshot()
        validate_registered_object(
            registry_snapshot, object_type, object_label.strip()
        )
        if _parse_time(window_start) > _parse_time(window_end):
            raise ValueError("时间窗口开始时间不得晚于结束时间")
        if not 1 <= max_items <= 1000:
            raise ValueError("单次采集上限必须在 1 到 1000 之间")
        if query_family not in QUERY_FAMILIES or phase not in QUERY_PHASES:
            raise ValueError("无效的查询族或查询阶段")
        clean_exact_query = (exact_query or " OR ".join(clean_keywords)).strip()
        if not clean_exact_query:
            raise ValueError("精确平台查询不能为空")
        mastodon_options = _mastodon_platform_options(
            platform=platform,
            exact_query=clean_exact_query,
            instances=mastodon_instances,
            access_method=mastodon_access_method,
            page_size=mastodon_page_size,
            max_pages_per_instance=mastodon_max_pages_per_instance,
            request_delay_seconds=mastodon_request_delay_seconds,
        )
        reddit_options = _reddit_platform_options(
            platform=platform,
            subreddits=reddit_subreddits,
            access_method=reddit_access_method,
            sort=reddit_sort,
            time_filter=reddit_time_filter,
            page_size=reddit_page_size,
            max_pages_per_subreddit=reddit_max_pages_per_subreddit,
            request_delay_seconds=reddit_request_delay_seconds,
        )
        tiktok_options = _tiktok_platform_options(
            platform=platform,
            window_start=window_start,
            window_end=window_end,
            query=tiktok_query,
            video_page_size=tiktok_video_page_size,
            max_video_pages=tiktok_max_video_pages,
            comment_page_size=tiktok_comment_page_size,
            max_comment_pages_per_video=tiktok_max_comment_pages_per_video,
            reply_page_size=tiktok_reply_page_size,
            max_reply_pages_per_comment=tiktok_max_reply_pages_per_comment,
            request_delay_seconds=tiktok_request_delay_seconds,
        )
        x_options = _x_platform_options(
            platform=platform,
            exact_query=clean_exact_query,
            window_start=window_start,
            window_end=window_end,
            page_size=x_page_size,
            max_pages=x_max_pages,
            request_delay_seconds=x_request_delay_seconds,
            local_run_budget_microusd=x_local_run_budget_microusd,
        )
        platform_options = (
            mastodon_options or reddit_options or tiktok_options or x_options
        )
        if phase == "confirmatory" and query_family == "legacy_scope_keywords":
            raise ValueError("确认运行必须选择预登记查询族")
        effective_max_videos = max_videos if max_videos is not None else min(max_items, 50)
        max_video_limit = 100 if platform == "tiktok" else 50
        if not 1 <= effective_max_videos <= max_video_limit:
            raise ValueError(f"每 query 视频上限必须在 1 到 {max_video_limit} 之间")
        if not 0 <= max_comment_threads_per_video <= 100:
            raise ValueError("每视频评论线程上限必须在 0 到 100 之间")
        if not 0 <= max_replies_per_thread <= 100:
            raise ValueError("每线程回复上限必须在 0 到 100 之间")
        query_yield_policy = validate_policy({
            "policy_version": DEFAULT_POLICY["policy_version"],
            "evaluation_k": query_yield_evaluation_k,
            "min_included_at_k": query_yield_min_included_at_k,
            "min_precision_at_k": query_yield_min_precision_at_k,
            "min_precision_lower_bound": query_yield_min_precision_lower_bound,
            "confidence_level": query_yield_confidence_level,
        })
        if phase == "calibration":
            if effective_max_videos < query_yield_policy["evaluation_k"]:
                raise ValueError("校准 query 的视频上限不得低于 evaluation_k")
            if max_comment_threads_per_video or max_replies_per_thread:
                raise ValueError("query-yield 校准阶段不得采集评论或回复")
        query = _build_query(
            platform=platform,
            object_type=object_type,
            object_label=object_label.strip(),
            keywords=clean_keywords,
            languages=clean_languages,
            window_start=window_start,
            window_end=window_end,
            max_items=max_items,
            registry_snapshot=registry_snapshot,
            query_family=query_family,
            phase=phase,
            exact_query=clean_exact_query,
            max_videos=effective_max_videos,
            max_comment_threads_per_video=max_comment_threads_per_video,
            max_replies_per_thread=max_replies_per_thread,
            query_yield_policy=query_yield_policy,
            platform_options=platform_options,
        )
        digest = query["query_id"].rsplit("_", 1)[-1]
        scope = {
            "scope_id": f"scope_{platform}_{digest}",
            "name": name.strip(),
            "platform": platform,
            "object_type": object_type,
            "object_label": object_label.strip(),
            "keywords": clean_keywords,
            "languages": clean_languages,
            "window_start": window_start,
            "window_end": window_end,
            "max_items": max_items,
            "query_id": query["query_id"],
            "query_family": query_family,
            "phase": phase,
            "exact_query": clean_exact_query,
            "layer_quotas": query["layer_quotas"],
            "query_yield_policy": query_yield_policy,
            "platform_options": platform_options,
        }
        with ResearchStore(self.database_path) as store:
            store.create_scope(scope, query)
        return scope

    def list_scopes(self) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return [
                self._scope_with_queries(store, scope)
                for scope in store.list_scopes()
            ]

    @staticmethod
    def _scope_with_queries(
        store: ResearchStore, scope: dict[str, Any]
    ) -> dict[str, Any]:
        queries = store.list_scope_queries(scope["scope_id"])
        primary = store.get_query(scope["query_id"])
        if primary is None:
            raise RuntimeError(f"scope query is missing: {scope['query_id']}")
        return {
            **scope,
            "query_family": primary.get("query_family", "legacy_scope_keywords"),
            "phase": primary.get("phase", "exploratory"),
            "exact_query": primary.get("exact_query") or primary.get("query_text"),
            "layer_quotas": primary.get("layer_quotas") or {
                "max_videos": min(scope["max_items"], 50),
                "max_comment_threads_per_video": 100,
                "max_replies_per_thread": 100,
            },
            "query_yield_policy": primary.get("query_yield_policy") or DEFAULT_POLICY,
            "platform_options": primary.get("platform_options"),
            "queries": queries,
        }

    def add_scope_query(
        self,
        scope_id: str,
        *,
        query_family: str,
        phase: str,
        exact_query: str,
    ) -> dict[str, Any]:
        clean_exact_query = exact_query.strip()
        if query_family not in QUERY_FAMILIES or phase not in QUERY_PHASES:
            raise ValueError("无效的查询族或查询阶段")
        if not clean_exact_query:
            raise ValueError("精确平台查询不能为空")
        if phase == "confirmatory" and query_family == "legacy_scope_keywords":
            raise ValueError("确认运行必须选择预登记查询族")
        with ResearchStore(self.database_path) as store:
            scope = store.get_scope(scope_id)
            if scope is None:
                raise KeyError(scope_id)
            primary = store.get_query(scope["query_id"])
            if primary is None:
                raise RuntimeError(f"scope query is missing: {scope['query_id']}")
            registry_snapshot = primary.get("registry_snapshot")
            if not isinstance(registry_snapshot, dict):
                raise ValueError("当前 scope 缺少已锁定 registry")
            quotas = primary.get("layer_quotas") or {}
            query = _build_query(
                platform=scope["platform"],
                object_type=scope["object_type"],
                object_label=scope["object_label"],
                keywords=scope["keywords"],
                languages=scope["languages"],
                window_start=scope["window_start"],
                window_end=scope["window_end"],
                max_items=scope["max_items"],
                registry_snapshot=registry_snapshot,
                query_family=query_family,
                phase=phase,
                exact_query=clean_exact_query,
                max_videos=int(quotas.get("max_videos", min(scope["max_items"], 50))),
                max_comment_threads_per_video=int(
                    quotas.get("max_comment_threads_per_video", 100)
                ),
                max_replies_per_thread=int(quotas.get("max_replies_per_thread", 100)),
                query_yield_policy=primary.get("query_yield_policy") or DEFAULT_POLICY,
                platform_options=primary.get("platform_options"),
            )
            existing = store.list_scope_queries(scope_id, active_only=False)
            if any(row["query_id"] == query["query_id"] for row in existing):
                raise ValueError("该不可变 query 已登记")
            result = store.add_scope_query(scope_id, query)
            store.record_audit(
                "scope_query_registered", "query", query["query_id"],
                {"scope_id": scope_id},
            )
            return result

    def promote_calibrated_queries(
        self,
        collection_run_id: str,
        *,
        query_ids: list[str] | None = None,
        name: str,
        window_start: str,
        window_end: str,
        max_items: int,
        max_videos: int,
        max_comment_threads_per_video: int,
        max_replies_per_thread: int,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("确认范围名称不能为空")
        confirmation_start = _parse_time(window_start)
        confirmation_end = _parse_time(window_end)
        if confirmation_start >= confirmation_end:
            raise ValueError("确认窗口开始时间必须早于结束时间")
        if not 1 <= max_items <= 1000:
            raise ValueError("单次采集上限必须在 1 到 1000 之间")
        if not 1 <= max_videos <= 50:
            raise ValueError("每 query 视频上限必须在 1 到 50 之间")
        if not 0 <= max_comment_threads_per_video <= 100:
            raise ValueError("每视频评论线程上限必须在 0 到 100 之间")
        if not 0 <= max_replies_per_thread <= 100:
            raise ValueError("每线程回复上限必须在 0 到 100 之间")
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or not isinstance(run.get("scope_id"), str):
                raise KeyError(collection_run_id)
            current, policy_snapshot = self._current_query_yield_report(
                store, collection_run_id
            )
            reports = store.query_yield_reports(collection_run_id)
            latest = reports[-1] if reports else None
            if (
                latest is None
                or latest["evidence_revision"] != current["evidence_revision"]
                or latest.get("assessment_mode") != "preregistered"
            ):
                raise ValueError("必须先冻结当前的预登记 query-yield 报告")
            passed_query_ids = set(latest.get("calibration_passed_query_ids") or [])
            selected_query_ids = (
                set(query_ids) if query_ids is not None else passed_query_ids
            )
            if not selected_query_ids:
                raise ValueError("当前报告没有可晋级的 query")
            if not selected_query_ids <= passed_query_ids:
                raise ValueError("只能晋级当前报告中通过的 query")
            already_promoted = store.promoted_source_query_ids(
                collection_run_id, latest["query_yield_report_id"]
            )
            if selected_query_ids & already_promoted:
                raise ValueError("所选 calibration query 已从当前报告晋级")
            manifest = json.loads(run["manifest_json"])
            source_queries = []
            all_source_queries = []
            for query_id in manifest.get("query_ids") or []:
                query = store.get_query(query_id)
                if query is None:
                    raise ValueError(f"运行缺少冻结 query：{query_id}")
                if query.get("phase") != "calibration":
                    raise ValueError("只有 calibration query 可以晋级")
                all_source_queries.append(query)
                if query_id in selected_query_ids:
                    source_queries.append(query)
            if {row["query_id"] for row in source_queries} != selected_query_ids:
                raise ValueError("待晋级 query 不属于该校准运行")
            if any(
                confirmation_start < _parse_time(query["window_end"])
                and confirmation_end > _parse_time(query["window_start"])
                for query in all_source_queries
            ):
                raise ValueError("confirmatory 窗口不得与 calibration 窗口重叠")
            scope = store.get_scope(run["scope_id"])
            if scope is None:
                raise KeyError(run["scope_id"])
            promoted = []
            for source_query in source_queries:
                promotion_evidence = {
                    "collection_run_id": collection_run_id,
                    "source_query_id": source_query["query_id"],
                    "query_yield_report_id": latest["query_yield_report_id"],
                    "policy_version": policy_snapshot["policy"]["policy_version"],
                }
                query = _build_query(
                    platform=source_query["platform"],
                    object_type=source_query["object_type_target"],
                    object_label=source_query["object_label_target"],
                    keywords=source_query["keywords"],
                    languages=source_query["languages"],
                    window_start=window_start,
                    window_end=window_end,
                    max_items=max_items,
                    registry_snapshot=source_query["registry_snapshot"],
                    query_family=source_query["query_family"],
                    phase="confirmatory",
                    exact_query=source_query["exact_query"],
                    max_videos=max_videos,
                    max_comment_threads_per_video=max_comment_threads_per_video,
                    max_replies_per_thread=max_replies_per_thread,
                    query_yield_policy=policy_snapshot["policy"],
                    promotion_evidence=promotion_evidence,
                    supersedes_query_id=source_query["query_id"],
                )
                promoted.append(query)
            primary = next(
                (
                    query
                    for query in promoted
                    if query["supersedes_query_id"] == scope["query_id"]
                ),
                promoted[0],
            )
            digest = primary["query_id"].rsplit("_", 1)[-1]
            confirmatory_scope = {
                "scope_id": f"scope_{scope['platform']}_{digest}",
                "name": clean_name,
                "platform": scope["platform"],
                "object_type": scope["object_type"],
                "object_label": scope["object_label"],
                "keywords": scope["keywords"],
                "languages": scope["languages"],
                "window_start": window_start,
                "window_end": window_end,
                "max_items": max_items,
                "query_id": primary["query_id"],
                "query_family": primary["query_family"],
                "phase": "confirmatory",
                "exact_query": primary["exact_query"],
                "layer_quotas": primary["layer_quotas"],
                "query_yield_policy": primary["query_yield_policy"],
            }
            created_scope = store.create_promoted_scope(
                run["scope_id"], confirmatory_scope, promoted
            )
            store.record_audit(
                "calibrated_queries_promoted",
                "collection_run",
                collection_run_id,
                {
                    "query_yield_report_id": latest["query_yield_report_id"],
                    "source_query_ids": [row["query_id"] for row in source_queries],
                    "promoted_query_ids": [row["query_id"] for row in promoted],
                    "source_scope_id": run["scope_id"],
                    "confirmatory_scope_id": created_scope["scope_id"],
                    "window_start": window_start,
                    "window_end": window_end,
                    "layer_quotas": primary["layer_quotas"],
                },
            )
            return {
                "collection_run_id": collection_run_id,
                "query_yield_report_id": latest["query_yield_report_id"],
                "confirmatory_scope": self._scope_with_queries(
                    store, created_scope
                ),
                "promoted_queries": promoted,
            }

    def registries(self) -> dict[str, Any]:
        return load_registry_snapshot()

    def observation_registry(self, observation_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            observation = store.get_observation(observation_id)
            if observation is None:
                raise KeyError(observation_id)
            registry = store.get_run_registry(observation["collection_run_id"])
        if registry is None or registry["binding_status"] != "bound":
            raise ValueError("该 observation 的 run 没有已锁定 registry")
        return registry

    def get_scope(self, scope_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            scope = store.get_scope(scope_id)
            if scope is not None:
                scope = self._scope_with_queries(store, scope)
        if scope is None:
            raise KeyError(scope_id)
        return scope

    @staticmethod
    def _run_scope_snapshot(
        store: ResearchStore,
        run: dict[str, Any],
        query_id: str | None = None,
    ) -> dict[str, Any]:
        scope_id = run.get("scope_id")
        if not isinstance(scope_id, str):
            raise KeyError(run["collection_run_id"])
        scope = store.get_scope(scope_id)
        if scope is None:
            raise KeyError(scope_id)
        manifest = json.loads(run["manifest_json"])
        query_ids = manifest.get("query_ids") or []
        if not query_ids or not all(isinstance(value, str) for value in query_ids):
            raise ValueError("采集运行必须引用至少一个有效 query")
        selected_query_id = query_id
        if selected_query_id is None:
            if len(query_ids) != 1:
                raise ValueError("多 query 运行必须显式选择 query 快照")
            selected_query_id = query_ids[0]
        if selected_query_id not in query_ids:
            raise ValueError("query 不属于该运行的冻结快照")
        query = store.get_query(selected_query_id)
        if query is None:
            raise RuntimeError(f"run query snapshot is missing: {selected_query_id}")
        languages = query.get("languages")
        if not isinstance(languages, list):
            languages = [
                value for value in str(query.get("language_bcp47") or "").split("|")
                if value
            ]
        keywords = query.get("keywords")
        if not isinstance(keywords, list):
            exact_query = str(query.get("exact_query") or query.get("query_text") or "")
            keywords = [exact_query] if exact_query else []
        return {
            **scope,
            "query_id": selected_query_id,
            "object_type": query.get("object_type_target") or scope["object_type"],
            "object_label": query.get("object_label_target") or scope["object_label"],
            "keywords": keywords,
            "languages": languages,
            "window_start": query.get("window_start") or scope["window_start"],
            "window_end": query.get("window_end") or scope["window_end"],
            "max_items": query.get("max_items") or scope["max_items"],
            "query_family": query.get("query_family") or "legacy_scope_keywords",
            "phase": query.get("phase") or "exploratory",
            "exact_query": query.get("exact_query") or query.get("query_text"),
            "layer_quotas": query.get("layer_quotas") or {
                "max_videos": min(int(query.get("max_items") or scope["max_items"]), 50),
                "max_comment_threads_per_video": 100,
                "max_replies_per_thread": 100,
            },
            "registry_snapshot": query.get("registry_snapshot"),
            "platform_options": query.get("platform_options"),
        }

    @staticmethod
    def _validate_normalized_query_provenance(
        record: dict[str, Any], scope_row: dict[str, Any]
    ) -> None:
        expected_query = scope_row.get("exact_query") or scope_row.get("query_text")
        if (
            record.get("query_id") != scope_row["query_id"]
            or record.get("query_text") != expected_query
        ):
            raise ValueError("规范化记录与运行冻结 query 不一致")

    def run_scope_snapshot(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None:
                raise KeyError(collection_run_id)
            return self._run_scope_snapshot(store, run)

    def run_scope_snapshots(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None:
                raise KeyError(collection_run_id)
            manifest = json.loads(run["manifest_json"])
            return [
                self._run_scope_snapshot(store, run, query_id)
                for query_id in manifest.get("query_ids") or []
            ]

    def observation_query_matches(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            if store.get_run(collection_run_id) is None:
                raise KeyError(collection_run_id)
            return store.observation_query_matches(collection_run_id)

    def update_scope(
        self,
        scope_id: str,
        *,
        platform: str = "bluesky",
        name: str,
        object_type: str,
        object_label: str,
        keywords: list[str],
        languages: list[str],
        window_start: str,
        window_end: str,
        max_items: int,
        active: bool,
        query_family: str = "legacy_scope_keywords",
        phase: str = "exploratory",
        exact_query: str | None = None,
        max_videos: int | None = None,
        max_comment_threads_per_video: int = 100,
        max_replies_per_thread: int = 100,
        query_yield_evaluation_k: int = 20,
        query_yield_min_included_at_k: int = 5,
        query_yield_min_precision_at_k: float = 0.25,
        query_yield_min_precision_lower_bound: float = 0.10,
        query_yield_confidence_level: float = 0.95,
        mastodon_instances: list[str] | None = None,
        mastodon_access_method: str = "hashtag_timeline",
        mastodon_page_size: int = 40,
        mastodon_max_pages_per_instance: int = 1,
        mastodon_request_delay_seconds: float = 1.0,
        reddit_subreddits: list[str] | None = None,
        reddit_access_method: str = "subreddit_search",
        reddit_sort: str = "relevance",
        reddit_time_filter: str = "all",
        reddit_page_size: int = 100,
        reddit_max_pages_per_subreddit: int = 1,
        reddit_request_delay_seconds: float = 1.0,
        tiktok_query: dict[str, Any] | None = None,
        tiktok_video_page_size: int = 100,
        tiktok_max_video_pages: int = 1,
        tiktok_comment_page_size: int = 100,
        tiktok_max_comment_pages_per_video: int = 1,
        tiktok_reply_page_size: int = 100,
        tiktok_max_reply_pages_per_comment: int = 1,
        tiktok_request_delay_seconds: float = 1.0,
        x_page_size: int = 100,
        x_max_pages: int = 1,
        x_request_delay_seconds: float = 1.0,
        x_local_run_budget_microusd: int = 500_000,
    ) -> dict[str, Any]:
        clean_keywords = sorted({value.strip() for value in keywords if value.strip()}, key=str.casefold)
        clean_languages = sorted({value.strip() for value in languages if value.strip()}, key=str.casefold)
        if not name.strip() or not object_label.strip() or object_type not in OBJECT_TYPES:
            raise ValueError("研究名称、对象类型和对象标签不能为空")
        if not clean_keywords or not clean_languages:
            raise ValueError("至少需要一个关键词和一种语言")
        registry_snapshot = load_registry_snapshot()
        validate_registered_object(
            registry_snapshot, object_type, object_label.strip()
        )
        if _parse_time(window_start) > _parse_time(window_end):
            raise ValueError("时间窗口开始时间不得晚于结束时间")
        if not 1 <= max_items <= 1000:
            raise ValueError("单次采集上限必须在 1 到 1000 之间")
        if query_family not in QUERY_FAMILIES or phase not in QUERY_PHASES:
            raise ValueError("无效的查询族或查询阶段")
        clean_exact_query = (exact_query or " OR ".join(clean_keywords)).strip()
        mastodon_options = _mastodon_platform_options(
            platform=platform,
            exact_query=clean_exact_query,
            instances=mastodon_instances,
            access_method=mastodon_access_method,
            page_size=mastodon_page_size,
            max_pages_per_instance=mastodon_max_pages_per_instance,
            request_delay_seconds=mastodon_request_delay_seconds,
        )
        reddit_options = _reddit_platform_options(
            platform=platform,
            subreddits=reddit_subreddits,
            access_method=reddit_access_method,
            sort=reddit_sort,
            time_filter=reddit_time_filter,
            page_size=reddit_page_size,
            max_pages_per_subreddit=reddit_max_pages_per_subreddit,
            request_delay_seconds=reddit_request_delay_seconds,
        )
        tiktok_options = _tiktok_platform_options(
            platform=platform,
            window_start=window_start,
            window_end=window_end,
            query=tiktok_query,
            video_page_size=tiktok_video_page_size,
            max_video_pages=tiktok_max_video_pages,
            comment_page_size=tiktok_comment_page_size,
            max_comment_pages_per_video=tiktok_max_comment_pages_per_video,
            reply_page_size=tiktok_reply_page_size,
            max_reply_pages_per_comment=tiktok_max_reply_pages_per_comment,
            request_delay_seconds=tiktok_request_delay_seconds,
        )
        x_options = _x_platform_options(
            platform=platform,
            exact_query=clean_exact_query,
            window_start=window_start,
            window_end=window_end,
            page_size=x_page_size,
            max_pages=x_max_pages,
            request_delay_seconds=x_request_delay_seconds,
            local_run_budget_microusd=x_local_run_budget_microusd,
        )
        platform_options = (
            mastodon_options or reddit_options or tiktok_options or x_options
        )
        effective_max_videos = max_videos if max_videos is not None else min(max_items, 50)
        max_video_limit = 100 if platform == "tiktok" else 50
        if not 1 <= effective_max_videos <= max_video_limit:
            raise ValueError(f"每 query 视频上限必须在 1 到 {max_video_limit} 之间")
        if not 0 <= max_comment_threads_per_video <= 100:
            raise ValueError("每视频评论线程上限必须在 0 到 100 之间")
        if not 0 <= max_replies_per_thread <= 100:
            raise ValueError("每线程回复上限必须在 0 到 100 之间")
        query_yield_policy = validate_policy({
            "policy_version": DEFAULT_POLICY["policy_version"],
            "evaluation_k": query_yield_evaluation_k,
            "min_included_at_k": query_yield_min_included_at_k,
            "min_precision_at_k": query_yield_min_precision_at_k,
            "min_precision_lower_bound": query_yield_min_precision_lower_bound,
            "confidence_level": query_yield_confidence_level,
        })
        if phase == "calibration":
            if effective_max_videos < query_yield_policy["evaluation_k"]:
                raise ValueError("校准 query 的视频上限不得低于 evaluation_k")
            if max_comment_threads_per_video or max_replies_per_thread:
                raise ValueError("query-yield 校准阶段不得采集评论或回复")
        with ResearchStore(self.database_path) as store:
            previous = store.get_scope(scope_id)
            if previous is None:
                raise KeyError(scope_id)
            if platform != previous["platform"]:
                raise ValueError("已创建的研究范围不能变更平台")
            scope = {
                **previous,
                "name": name.strip(),
                "object_type": object_type,
                "object_label": object_label.strip(),
                "keywords": clean_keywords,
                "languages": clean_languages,
                "window_start": window_start,
                "window_end": window_end,
                "max_items": max_items,
                "active": active,
                "query_family": query_family,
                "phase": phase,
                "exact_query": clean_exact_query,
                "layer_quotas": {
                    "max_videos": effective_max_videos,
                    "max_comment_threads_per_video": max_comment_threads_per_video,
                    "max_replies_per_thread": max_replies_per_thread,
                },
                "query_yield_policy": query_yield_policy,
                "platform_options": platform_options,
            }
            previous_query = store.get_query(previous["query_id"])
            if previous_query is None:
                raise RuntimeError(f"scope query is missing: {previous['query_id']}")
            query_changed = any((
                object_type != previous["object_type"],
                object_label.strip() != previous["object_label"],
                clean_keywords != previous["keywords"],
                clean_languages != previous["languages"],
                window_start != previous["window_start"],
                window_end != previous["window_end"],
                max_items != previous["max_items"],
                previous_query.get("object_map_sha256") != registry_snapshot["object_map_sha256"],
                previous_query.get("codebook_sha256") != registry_snapshot["codebook_sha256"],
                previous_query.get("query_family") != query_family,
                previous_query.get("phase") != phase,
                previous_query.get("exact_query") != clean_exact_query,
                previous_query.get("layer_quotas") != {
                    "max_videos": effective_max_videos,
                    "max_comment_threads_per_video": max_comment_threads_per_video,
                    "max_replies_per_thread": max_replies_per_thread,
                },
                (previous_query.get("query_yield_policy") or DEFAULT_POLICY)
                != query_yield_policy,
                previous_query.get("platform_options") != platform_options,
            ))
            if query_changed and len(store.list_scope_queries(scope_id)) > 1:
                raise ValueError("多 query 范围不能原位改写查询条件；请归档后新建范围")
            query = None
            if query_changed:
                query = _build_query(
                    platform=scope["platform"],
                    object_type=object_type,
                    object_label=object_label.strip(),
                    keywords=clean_keywords,
                    languages=clean_languages,
                    window_start=window_start,
                    window_end=window_end,
                    max_items=max_items,
                    registry_snapshot=registry_snapshot,
                    query_family=query_family,
                    phase=phase,
                    exact_query=clean_exact_query,
                    max_videos=effective_max_videos,
                    max_comment_threads_per_video=max_comment_threads_per_video,
                    max_replies_per_thread=max_replies_per_thread,
                    query_yield_policy=query_yield_policy,
                    supersedes_query_id=previous["query_id"],
                    platform_options=platform_options,
                )
                scope["query_id"] = query["query_id"]
            updated = store.update_scope(scope, query, active=active)
            store.record_audit(
                "scope_updated",
                "research_scope",
                scope_id,
                {"active": active, "previous": previous},
            )
            return updated

    def create_schedule(
        self,
        scope_id: str,
        *,
        interval_minutes: int,
        enabled: bool,
    ) -> dict[str, Any]:
        if not 1 <= interval_minutes <= 10080:
            raise ValueError("调度间隔必须在 1 分钟到 7 天之间")
        next_run_at = (
            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z") if enabled else None
        schedule_id = f"schedule_{hashlib.sha256(scope_id.encode('utf-8')).hexdigest()[:16]}"
        with ResearchStore(self.database_path) as store:
            if store.get_scope(scope_id) is None:
                raise KeyError(scope_id)
            if enabled and any(
                query.get("phase") == "calibration"
                for query in store.list_scope_queries(scope_id)
            ):
                raise ValueError("calibration scope 不得启用调度")
            schedule = store.create_schedule(
                schedule_id,
                scope_id,
                interval_minutes=interval_minutes,
                enabled=enabled,
                next_run_at=next_run_at,
            )
            store.record_audit(
                "schedule_created", "schedule", schedule_id, {"scope_id": scope_id}
            )
            return schedule

    def list_schedules(self) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_schedules()

    def update_schedule(
        self,
        schedule_id: str,
        *,
        interval_minutes: int,
        enabled: bool,
    ) -> dict[str, Any]:
        if not 1 <= interval_minutes <= 10080:
            raise ValueError("调度间隔必须在 1 分钟到 7 天之间")
        next_run_at = (
            datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z") if enabled else None
        with ResearchStore(self.database_path) as store:
            current = store.get_schedule(schedule_id)
            if current is None:
                raise KeyError(schedule_id)
            if enabled and any(
                query.get("phase") == "calibration"
                for query in store.list_scope_queries(current["scope_id"])
            ):
                raise ValueError("calibration scope 不得启用调度")
            schedule = store.update_schedule(
                schedule_id,
                interval_minutes=interval_minutes,
                enabled=enabled,
                next_run_at=next_run_at,
            )
            store.record_audit(
                "schedule_updated", "schedule", schedule_id, {"enabled": enabled}
            )
            return schedule

    def start_run(
        self,
        scope_id: str,
        *,
        trigger_type: str = "manual",
        parent_collection_run_id: str | None = None,
        schedule_id: str | None = None,
        youtube_run_search_call_budget: int | None = None,
        youtube_run_shared_unit_budget: int | None = None,
    ) -> dict[str, Any]:
        if trigger_type not in {"manual", "scheduled", "retry"}:
            raise ValueError("invalid run trigger")
        with ResearchStore(self.database_path) as store:
            scope = store.get_scope(scope_id)
            if scope is None:
                raise KeyError(scope_id)
            if not scope["active"]:
                raise ValueError("已归档的研究范围不能启动采集")
            platform = scope["platform"]
            run_config = PLATFORM_RUN_CONFIG[platform]
            queries = store.list_scope_queries(scope_id)
            if not queries:
                raise RuntimeError(f"scope query is missing: {scope['query_id']}")
            if platform not in {"youtube", "mastodon", "reddit", "tiktok", "x"} and len(queries) > 1:
                raise ValueError("当前多 query 采集仅支持 YouTube、Mastodon、Reddit、TikTok 和 X")
            x_billing_binding = None
            if platform == "x":
                x_options = [query.get("platform_options") for query in queries]
                if not all(isinstance(options, dict) for options in x_options):
                    raise ValueError("X query 缺少冻结平台配置")
                run_budgets = {
                    int(options["local_run_budget_microusd"])
                    for options in x_options
                }
                page_sizes = {int(options["page_size"]) for options in x_options}
                if len(run_budgets) != 1 or len(page_sizes) != 1:
                    raise ValueError("同一 X run 的预算与页大小必须一致")
                x_billing_binding = store.preflight_x_billing(
                    local_run_budget_microusd=run_budgets.pop(),
                    page_size=page_sizes.pop(),
                )
            phases = {query.get("phase", "exploratory") for query in queries}
            if "calibration" in phases and phases != {"calibration"}:
                raise ValueError("calibration query 不得与其他研究阶段混合运行")
            query_yield_policy = validate_policy(
                queries[0].get("query_yield_policy") or DEFAULT_POLICY
            )
            if any(
                validate_policy(query.get("query_yield_policy") or DEFAULT_POLICY)
                != query_yield_policy
                for query in queries
            ):
                raise ValueError("同一运行的 query-yield 政策必须一致")
            if phases == {"calibration"}:
                if trigger_type != "manual":
                    raise ValueError("calibration run 只能手动启动")
                if store.count_scope_runs(scope_id):
                    raise ValueError("calibration scope 只能运行一次")
                if any(
                    int((query.get("layer_quotas") or {}).get("max_videos", 0))
                    < query_yield_policy["evaluation_k"]
                    for query in queries
                ):
                    raise ValueError("校准 query 的视频上限不得低于 evaluation_k")
                if any(
                    int((query.get("layer_quotas") or {}).get(
                        "max_comment_threads_per_video", 0
                    ))
                    or int((query.get("layer_quotas") or {}).get(
                        "max_replies_per_thread", 0
                    ))
                    for query in queries
                ):
                    raise ValueError("query-yield 校准阶段不得采集评论或回复")
            video_capacity = sum(
                int((query.get("layer_quotas") or {}).get("max_videos", 0))
                for query in queries
            )
            if any(
                int((query.get("layer_quotas") or {}).get(
                    "max_comment_threads_per_video", 0
                )) > 0
                for query in queries
            ) and scope["max_items"] < video_capacity:
                raise ValueError("评论/回复运行上限不得低于全部 query 的视频候选上限")
            for query in queries:
                promotion = query.get("promotion_evidence")
                if query.get("phase") != "confirmatory" or not isinstance(
                    promotion, dict
                ):
                    continue
                source_run_id = promotion.get("collection_run_id")
                source_report_id = promotion.get("query_yield_report_id")
                if not isinstance(source_run_id, str) or not isinstance(
                    source_report_id, int
                ):
                    raise ValueError("confirmatory query 的校准来源无效")
                current_source, _ = self._current_query_yield_report(
                    store, source_run_id
                )
                source_reports = store.query_yield_reports(source_run_id)
                source_report = next(
                    (
                        report
                        for report in source_reports
                        if report["query_yield_report_id"] == source_report_id
                    ),
                    None,
                )
                if (
                    source_report is None
                    or promotion.get("source_query_id")
                    not in set(source_report.get("calibration_passed_query_ids") or [])
                    or source_report["evidence_revision"]
                    != current_source["evidence_revision"]
                ):
                    raise ValueError("confirmatory query 的校准证据已变化或未通过")
            registry_snapshot = queries[0].get("registry_snapshot")
            if not isinstance(registry_snapshot, dict):
                raise ValueError("当前 query 缺少 registry 快照；请更新范围生成新 query")
            if any(
                query.get("object_map_sha256") != registry_snapshot["object_map_sha256"]
                or query.get("codebook_sha256") != registry_snapshot["codebook_sha256"]
                for query in queries
            ):
                raise ValueError("活动 query 的 registry 快照不一致")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            run_id = f"social_run_{platform}_{stamp}_{uuid.uuid4().hex[:8]}"
            manifest = {
                "schema_version": "0.2.0" if platform == "mastodon" else "0.1.0",
                "collection_run_id": run_id,
                "platform": platform,
                "source_kind": "official_api",
                "query_ids": [query["query_id"] for query in queries],
                "window": {
                    "start": scope["window_start"],
                    "end": scope["window_end"],
                    "timezone": "UTC",
                },
                "sampling": {
                    "method": run_config["sampling_method"],
                    "max_items": scope["max_items"],
                    "page_size": run_config["page_size"],
                    "sort_order": run_config["sort_order"],
                    "deduplication": "platform_item_id",
                    "inclusion_rule": "匹配已登记关键词、语言与发布时间窗的公开帖文。",
                    "exclusion_rule": "范围外、删除、非帖文或无法规范化的事件。",
                    "random_seed": None,
                },
                "collector": {
                    "tool": run_config["collector_tool"],
                    "tool_version": "0.1.0",
                    "endpoint": run_config["endpoint"],
                    "api_version": run_config["api_version"],
                    "adapter_commit": None,
                },
                "created_at": _now(),
                "completed_at": None,
                "input_files": [],
                "governance": {
                    "terms_checked_at": datetime.now(timezone.utc).date().isoformat(),
                    "license_status": "unknown",
                    "raw_storage": "ignored_local",
                    "release_decision": "pending_review",
                    "reviewer_ref": REVIEWER_REF,
                    "notes": "原始事件仅保存在本机数据库；发布前需另行权利审查。",
                },
                "status": "planned",
                "counts": {
                    "requested": None,
                    "received": 0,
                    "normalized": 0,
                    "failures": 0,
                    "human_verified": 0,
                },
                "notes": (
                    f"覆盖边界：{run_config['coverage']}"
                    + (
                        " 选定实例："
                        + ", ".join(
                            str(value)
                            for value in (queries[0].get("platform_options") or {}).get(
                                "instances", []
                            )
                        )
                        + "；不代表 Mastodon 全网样本。"
                        if platform == "mastodon"
                        else ""
                    )
                    + (
                        " 选定 subreddit："
                        + ", ".join(
                            f"r/{value}"
                            for value in (queries[0].get("platform_options") or {}).get(
                                "subreddits", []
                            )
                        )
                        + "；不代表 Reddit 全网样本。"
                        if platform == "reddit"
                        else ""
                    )
                    + (
                        " UTC 整日窗口最长 30 个 UTC 日历日；视频、评论和回复共用"
                        " 1000 requests/day 文档快照上限；不代表 TikTok 全网样本。"
                        if platform == "tiktok"
                        else ""
                    )
                    + (
                        " recent-search 窗口最长七天；按 run 启动时绑定的 post_read"
                        " 价格快照、本机 run/billing-cycle cap 与已确认的 Developer"
                        " Console hard spending limit 守卫；不代表 X 全网样本。"
                        if platform == "x"
                        else ""
                    )
                ),
            }
            errors = [error.message for error in schema_validator(MANIFEST_SCHEMA).iter_errors(manifest)]
            if errors:
                raise ValueError("run manifest invalid: " + " | ".join(errors))
            store.create_run(
                run_id,
                manifest,
                scope_id=scope_id,
                trigger_type=trigger_type,
                parent_collection_run_id=parent_collection_run_id,
                schedule_id=schedule_id,
                registry_snapshot=registry_snapshot,
                query_yield_policy=query_yield_policy,
                query_yield_assessment_mode=(
                    "preregistered"
                    if phases == {"calibration"}
                    else "retrospective"
                ),
                x_billing_binding=x_billing_binding,
            )
            if platform == "youtube":
                if trigger_type == "retry" and parent_collection_run_id is not None:
                    parent_policy = store.get_run_quota_policy(
                        parent_collection_run_id
                    )
                    if parent_policy is not None:
                        youtube_run_search_call_budget = (
                            youtube_run_search_call_budget
                            if youtube_run_search_call_budget is not None
                            else parent_policy["search_call_budget"]
                        )
                        youtube_run_shared_unit_budget = (
                            youtube_run_shared_unit_budget
                            if youtube_run_shared_unit_budget is not None
                            else parent_policy["shared_unit_budget"]
                        )
                quota_policy = store.bind_youtube_quota_policy(
                    run_id,
                    search_call_budget=youtube_run_search_call_budget,
                    shared_unit_budget=youtube_run_shared_unit_budget,
                )
            else:
                quota_policy = None
            store.record_audit(
                "run_started",
                "collection_run",
                run_id,
                {
                    "scope_id": scope_id,
                    "trigger_type": trigger_type,
                    "parent_collection_run_id": parent_collection_run_id,
                    "schedule_id": schedule_id,
                    "quota_policy_version": (
                        quota_policy["policy_version"]
                        if quota_policy is not None
                        else (
                            x_billing_binding["pricing_policy_version"]
                            if x_billing_binding is not None
                            else None
                        )
                    ),
                    "x_price_snapshot_id": (
                        x_billing_binding["price_snapshot_id"]
                        if x_billing_binding is not None
                        else None
                    ),
                },
            )
        return manifest

    def list_runs(self) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_runs()

    def get_run(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
        if run is None:
            raise KeyError(collection_run_id)
        return run

    def process_event(self, collection_run_id: str, event: dict[str, Any]) -> bool:
        cursor = event_cursor(event)
        payload = event.get("payload") or {}
        normalized_at = payload.get("time") if isinstance(payload, dict) else None
        normalized_at = normalized_at if isinstance(normalized_at, str) else _now()
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run)
            store.increment_received(collection_run_id)
            store.save_cursor("bluesky", cursor)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            record = normalize_jetstream_event(
                event,
                scope=scope,
                collection_run_id=collection_run_id,
                normalized_at=normalized_at,
            )
            if record is None:
                return False
            self._validate_normalized_query_provenance(record, scope_row)
            return store.ingest_observation(
                record,
                event,
                cursor=cursor,
                source=source_row(record),
            )

    def process_youtube_resource(
        self,
        collection_run_id: str,
        resource: dict[str, Any],
        raw_event: dict[str, Any],
        *,
        video_id: str | None = None,
        channel: dict[str, Any] | None = None,
        parent_comment_id: str | None = None,
        reply_count: int | None = None,
        query_id: str | None = None,
        candidate_rank: int | None = None,
    ) -> bool:
        if candidate_rank is not None and candidate_rank < 1:
            raise ValueError("YouTube query 候选排名必须大于 0")
        normalized_at = _now()
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or run.get("platform") != "youtube" or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run, query_id)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            store.increment_received(collection_run_id)
            if video_id is None:
                record = normalize_youtube_video(
                    resource,
                    channel=channel,
                    scope=scope,
                    collection_run_id=collection_run_id,
                    normalized_at=normalized_at,
                )
            else:
                record = normalize_youtube_comment(
                    resource,
                    video_id=video_id,
                    parent_comment_id=parent_comment_id,
                    reply_count=reply_count,
                    scope=scope,
                    collection_run_id=collection_run_id,
                    normalized_at=normalized_at,
                )
            self._validate_normalized_query_provenance(record, scope_row)
            cursor = int.from_bytes(
                hashlib.sha256(
                    (
                        f"youtube\0{collection_run_id}\0"
                        f"{record['platform_item_id']}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            ) & ((1 << 63) - 1)
            inserted = store.ingest_observation(
                record,
                raw_event,
                cursor=cursor,
                source=source_row(record),
            )
            store.record_observation_query_match(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                {
                    "kind": raw_event.get("kind"),
                    "matched_query_id": scope_row["query_id"],
                    "retrieval": {
                        "candidate_rank": candidate_rank,
                        "rank_basis": (
                            "query-local order after video detail and window validation"
                            if candidate_rank is not None else None
                        ),
                        "sort_order": scope_row.get("sort_order"),
                    },
                },
            )
            return inserted

    def process_mastodon_status(
        self,
        collection_run_id: str,
        status: dict[str, Any],
        *,
        observed_instance: str,
        hashtag: str,
        query_id: str | None = None,
        normalized_at: str | None = None,
    ) -> tuple[bool, bool]:
        instance = normalize_instance(observed_instance)
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or run.get("platform") != "mastodon" or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run, query_id)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            store.increment_received(collection_run_id)
            record = normalize_mastodon_status(
                status,
                observed_instance=instance,
                hashtag=hashtag,
                access_method=(
                    scope_row.get("platform_options") or {}
                ).get("access_method", "hashtag_timeline"),
                scope=scope,
                collection_run_id=collection_run_id,
                normalized_at=normalized_at or _now(),
            )
            if record is None:
                return False, False
            self._validate_normalized_query_provenance(record, scope_row)
            local_status_id = status.get("id")
            if not isinstance(local_status_id, str) or not local_status_id:
                raise ValueError("Mastodon status is missing local id")
            cursor = int.from_bytes(
                hashlib.sha256(
                    (
                        f"mastodon\0{collection_run_id}\0{scope_row['query_id']}\0"
                        f"{instance}\0{local_status_id}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            ) & ((1 << 63) - 1)
            raw_event = {
                "observed_instance": instance,
                "hashtag": hashtag.lstrip("#"),
                "matched_query_id": scope_row["query_id"],
                "status": status,
            }
            inserted = store.ingest_observation(
                record,
                raw_event,
                cursor=cursor,
                source=source_row(record),
            )
            store.record_observation_query_match(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                {
                    "kind": "mastodon_status",
                    "matched_query_id": scope_row["query_id"],
                    "observed_instance": instance,
                    "access_method": (
                        scope_row.get("platform_options") or {}
                    ).get("access_method"),
                },
            )
            sighting_inserted = store.record_mastodon_sighting(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                instance,
                local_status_id=local_status_id,
                platform_item_id=record["platform_item_id"],
                status_uri=status.get("uri") if isinstance(status.get("uri"), str) else None,
                visibility=str(status.get("visibility")),
                payload=raw_event,
            )
            return inserted, sighting_inserted

    def process_reddit_post(
        self,
        collection_run_id: str,
        thing: dict[str, Any],
        *,
        subreddit: str,
        query_id: str | None = None,
        normalized_at: str | None = None,
        minimum_created_utc: float | None = None,
    ) -> bool:
        clean_subreddit = normalize_subreddit(subreddit)
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or run.get("platform") != "reddit" or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run, query_id)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            store.increment_received(collection_run_id)
            content_status = reddit_content_status(thing)
            if content_status != "available":
                data = thing.get("data") if isinstance(thing, dict) else None
                item_id = data.get("name") if isinstance(data, dict) else None
                store.record_audit(
                    f"reddit_item_{content_status}",
                    "collection_run",
                    collection_run_id,
                    {
                        "platform_item_id": item_id if isinstance(item_id, str) else None,
                        "query_id": scope_row["query_id"],
                        "subreddit": clean_subreddit,
                        "payload_sha256": hashlib.sha256(
                            canonical_json(thing).encode("utf-8")
                        ).hexdigest(),
                    },
                )
                return False
            created_utc = reddit_created_utc(thing)
            if minimum_created_utc is not None and created_utc <= minimum_created_utc:
                data = thing.get("data")
                store.record_audit(
                    "reddit_item_at_or_before_high_watermark",
                    "collection_run",
                    collection_run_id,
                    {
                        "created_utc": created_utc,
                        "high_watermark": minimum_created_utc,
                        "platform_item_id": data.get("name") if isinstance(data, dict) else None,
                        "query_id": scope_row["query_id"],
                        "subreddit": clean_subreddit,
                    },
                )
                return False
            record = normalize_reddit_post(
                thing,
                subreddit=clean_subreddit,
                access_method=(scope_row.get("platform_options") or {}).get(
                    "access_method", "subreddit_search"
                ),
                scope=scope,
                collection_run_id=collection_run_id,
                normalized_at=normalized_at or _now(),
            )
            if record is None:
                return False
            published_at = record.get("published_at")
            if not isinstance(published_at, str) or not (
                _parse_time(scope_row["window_start"])
                <= _parse_time(published_at)
                <= _parse_time(scope_row["window_end"])
            ):
                store.record_audit(
                    "reddit_item_outside_window",
                    "collection_run",
                    collection_run_id,
                    {
                        "platform_item_id": record["platform_item_id"],
                        "query_id": scope_row["query_id"],
                        "subreddit": clean_subreddit,
                    },
                )
                return False
            self._validate_normalized_query_provenance(record, scope_row)
            cursor = int.from_bytes(
                hashlib.sha256(
                    (
                        f"reddit\0{collection_run_id}\0{scope_row['query_id']}\0"
                        f"{clean_subreddit}\0{record['platform_item_id']}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            ) & ((1 << 63) - 1)
            raw_event = {
                "kind": "reddit_post",
                "matched_query_id": scope_row["query_id"],
                "subreddit": clean_subreddit,
                "thing": thing,
            }
            inserted = store.ingest_observation(
                record,
                raw_event,
                cursor=cursor,
                source=source_row(record),
            )
            store.record_observation_query_match(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                {
                    "kind": "reddit_post",
                    "matched_query_id": scope_row["query_id"],
                    "subreddit": clean_subreddit,
                    "access_method": (
                        scope_row.get("platform_options") or {}
                    ).get("access_method"),
                },
            )
            return inserted

    def process_x_post(
        self,
        collection_run_id: str,
        post: dict[str, Any],
        *,
        query_id: str | None = None,
        normalized_at: str | None = None,
    ) -> bool:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or run.get("platform") != "x" or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run, query_id)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            clean_post = sanitize_x_post(post)
            store.increment_received(collection_run_id)
            record = normalize_x_post(
                clean_post,
                scope=scope,
                collection_run_id=collection_run_id,
                normalized_at=normalized_at or _now(),
            )
            published_at = record.get("published_at")
            if not isinstance(published_at, str) or not (
                _parse_time(scope_row["window_start"])
                <= _parse_time(published_at)
                <= _parse_time(scope_row["window_end"])
            ):
                store.record_audit(
                    "x_item_outside_window",
                    "collection_run",
                    collection_run_id,
                    {
                        "platform_item_id": record["platform_item_id"],
                        "query_id": scope_row["query_id"],
                    },
                )
                return False
            self._validate_normalized_query_provenance(record, scope_row)
            cursor = int.from_bytes(
                hashlib.sha256(
                    (
                        f"x\0{collection_run_id}\0{scope_row['query_id']}\0"
                        f"{record['platform_item_id']}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            ) & ((1 << 63) - 1)
            raw_event = {
                "kind": "x_post",
                "matched_query_id": scope_row["query_id"],
                "resource": clean_post,
            }
            inserted = store.ingest_observation(
                record,
                raw_event,
                cursor=cursor,
                source=source_row(record),
            )
            store.record_observation_query_match(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                {
                    "kind": "x_post",
                    "matched_query_id": scope_row["query_id"],
                    "access_method": (
                        scope_row.get("platform_options") or {}
                    ).get("access_method"),
                },
            )
            return inserted

    def process_tiktok_resource(
        self,
        collection_run_id: str,
        resource: dict[str, Any],
        *,
        resource_type: str,
        query_id: str | None = None,
        video_id: str | None = None,
        parent_comment_id: str | None = None,
        normalized_at: str | None = None,
    ) -> bool:
        if resource_type not in {"video", "comment", "reply"}:
            raise ValueError("无效的 TikTok resource_type")
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None or run.get("platform") != "tiktok" or not run.get("scope_id"):
                raise KeyError(collection_run_id)
            scope_row = self._run_scope_snapshot(store, run, query_id)
            scope = ResearchScope(
                query_id=scope_row["query_id"],
                object_type=scope_row["object_type"],
                object_label=scope_row["object_label"],
                keywords=tuple(scope_row["keywords"]),
                languages=tuple(scope_row["languages"]),
                window_start=scope_row["window_start"],
                window_end=scope_row["window_end"],
                exact_query=scope_row.get("exact_query"),
            )
            store.increment_received(collection_run_id)
            effective_normalized_at = normalized_at or _now()
            if resource_type == "video":
                record = normalize_tiktok_video(
                    resource,
                    scope=scope,
                    collection_run_id=collection_run_id,
                    normalized_at=effective_normalized_at,
                )
            else:
                if video_id is None:
                    raise ValueError("TikTok comment requires video_id context")
                record = normalize_tiktok_comment(
                    resource,
                    video_id=video_id,
                    parent_comment_id=(
                        parent_comment_id if resource_type == "reply" else None
                    ),
                    scope=scope,
                    collection_run_id=collection_run_id,
                    normalized_at=effective_normalized_at,
                )
            published_at = record.get("published_at")
            if not isinstance(published_at, str) or not (
                _parse_time(scope_row["window_start"])
                <= _parse_time(published_at)
                <= _parse_time(scope_row["window_end"])
            ):
                store.record_audit(
                    "tiktok_item_outside_window",
                    "collection_run",
                    collection_run_id,
                    {
                        "platform_item_id": record["platform_item_id"],
                        "query_id": scope_row["query_id"],
                        "resource_type": resource_type,
                    },
                )
                return False
            self._validate_normalized_query_provenance(record, scope_row)
            cursor = int.from_bytes(
                hashlib.sha256(
                    (
                        f"tiktok\0{collection_run_id}\0{scope_row['query_id']}\0"
                        f"{resource_type}\0{record['platform_item_id']}"
                    ).encode("utf-8")
                ).digest()[:8],
                "big",
            ) & ((1 << 63) - 1)
            raw_event = {
                "kind": f"tiktok_{resource_type}",
                "matched_query_id": scope_row["query_id"],
                "resource": resource,
                "video_id": video_id,
                "parent_comment_id": parent_comment_id,
            }
            inserted = store.ingest_observation(
                record,
                raw_event,
                cursor=cursor,
                source=source_row(record),
            )
            store.record_observation_query_match(
                record["observation_id"],
                collection_run_id,
                scope_row["query_id"],
                {
                    "kind": f"tiktok_{resource_type}",
                    "matched_query_id": scope_row["query_id"],
                    "video_id": video_id,
                    "parent_comment_id": parent_comment_id,
                },
            )
            return inserted

    def review_queue(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_review_candidates(collection_run_id)

    def screening_queue(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            records = store.list_screening_candidates(collection_run_id)
            policy_modes: dict[str, str | None] = {}
            output = []
            for index, record in enumerate(records):
                run_id = record["collection_run_id"]
                if run_id not in policy_modes:
                    policy = store.get_run_query_yield_policy(run_id)
                    policy_modes[run_id] = (
                        policy["assessment_mode"] if policy is not None else None
                    )
                if policy_modes[run_id] == "preregistered":
                    blinded = {
                        key: value
                        for key, value in record.items()
                        if key not in {"query_id", "query_text"}
                    }
                    order = hashlib.sha256(
                        f"query-yield-blind-v1\0{run_id}\0{record['observation_id']}".encode(
                            "utf-8"
                        )
                    ).hexdigest()
                    output.append(((run_id, 0, order), blinded))
                else:
                    output.append(((run_id, 1, f"{index:012d}"), record))
            return [record for _, record in sorted(output, key=lambda item: item[0])]

    def screening_history(self, observation_id: str | None = None) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.screening_history(observation_id)

    def latest_screening(self, observation_id: str) -> dict[str, Any] | None:
        with ResearchStore(self.database_path) as store:
            return store.latest_screening(observation_id)

    def screen_observation(
        self,
        observation_id: str,
        *,
        decision: str,
        reason: str,
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            observation = store.get_observation(observation_id)
            if observation is None:
                raise KeyError(observation_id)
            governance = store.get_run_governance(observation["collection_run_id"])
            registry = store.get_run_registry(observation["collection_run_id"])
            if governance is None or not governance["analysis_allowed"]:
                raise ValueError("engineering-only 运行不能进入相关性筛选")
            if registry is None or registry["binding_status"] != "bound":
                raise ValueError("运行缺少已锁定的 registry，不能进入相关性筛选")
            event = store.record_screening(
                observation_id,
                decision=decision,
                rule_version="social_screening_v0.1.0",
                signals={"manual_review": True},
                tool_name="GLYPH local review workbench",
                tool_version="0.1.0",
                decided_by=REVIEWER_REF,
                reason=reason,
            )
            store.record_audit(
                "observation_screened",
                "observation",
                observation_id,
                {
                    "collection_run_id": observation["collection_run_id"],
                    "decision": decision,
                    "screening_id": event["screening_id"],
                },
            )
            return event

    def observations(self, status: str | None = None) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_observations(status)

    def review_history(self, observation_id: str | None = None) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.review_history(observation_id)

    @staticmethod
    def _validate_coder_id(coder_id: str) -> str:
        clean = coder_id.strip()
        if not re.fullmatch(r"annotator_[A-Za-z0-9][A-Za-z0-9_-]{1,54}", clean):
            raise ValueError("编码员 ID 必须使用 annotator_ 前缀和字母、数字、下划线或连字符")
        return clean

    def submit_independent_annotation(
        self,
        observation_id: str,
        *,
        coder_id: str,
        object_type: str,
        object_label: str,
        aesthetic_terms: list[str],
        evidence_span: str,
        stance: str,
        language_confirmed: bool,
        author_role: str,
    ) -> dict[str, Any]:
        clean_coder_id = self._validate_coder_id(coder_id)
        clean_terms = sorted(
            {term.strip() for term in aesthetic_terms if term.strip()},
            key=str.casefold,
        )
        with ResearchStore(self.database_path) as store:
            row = store.get_observation(observation_id)
            if row is None:
                raise KeyError(observation_id)
            record = json.loads(row["record_json"])
            governance = store.get_run_governance(record["collection_run_id"])
            registry = store.get_run_registry(record["collection_run_id"])
            screening = store.latest_screening(observation_id)
            if governance is None or not governance["analysis_allowed"]:
                raise ValueError("engineering-only 运行不能进入独立编码")
            if registry is None or registry["binding_status"] != "bound":
                raise ValueError("运行缺少已锁定 registry，不能进入独立编码")
            if screening is None or screening["decision"] != "include":
                raise ValueError("独立编码前必须先通过 include 相关性筛选")
            validate_registered_object(
                registry["snapshot"], object_type, object_label.strip()
            )
            validate_registered_terms(registry["snapshot"], clean_terms)
            if not clean_terms or stance not in STANCES or author_role not in AUTHOR_ROLES:
                raise ValueError("独立编码需要审美术语、有效立场和已确认来源角色")
            if not evidence_span or evidence_span not in record["text"]:
                raise ValueError("独立编码证据片段必须逐字出现在原文中")
            annotation = {
                "object_type": object_type,
                "object_label": object_label.strip(),
                "aesthetic_terms": clean_terms,
                "evidence_span": evidence_span,
                "stance": stance,
                "language_confirmed": bool(language_confirmed),
                "author_role": author_role,
            }
            result = store.record_independent_annotation(
                observation_id,
                clean_coder_id,
                annotation,
                object_map_sha256=registry["object_map_sha256"],
                codebook_sha256=registry["codebook_sha256"],
            )
            store.record_audit(
                "independent_annotation_submitted",
                "observation",
                observation_id,
                {
                    "collection_run_id": record["collection_run_id"],
                    "annotation_id": result["annotation_id"],
                    "coder_id": clean_coder_id,
                },
            )
            return result

    def independent_annotations(self, collection_run_id: str) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.independent_annotations(collection_run_id)

    def adjudications(self, collection_run_id: str) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.adjudications(collection_run_id)

    def quality_reports(self, collection_run_id: str) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            if store.get_run(collection_run_id) is None:
                raise KeyError(collection_run_id)
            return store.quality_reports(collection_run_id)

    @staticmethod
    def _current_query_yield_report(
        store: ResearchStore,
        collection_run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        run = store.get_run(collection_run_id)
        if run is None:
            raise KeyError(collection_run_id)
        policy_snapshot = store.get_run_query_yield_policy(collection_run_id)
        if policy_snapshot is None:
            raise ValueError("运行缺少冻结的 query-yield 政策")
        manifest = json.loads(run["manifest_json"])
        queries = []
        for query_id in manifest.get("query_ids") or []:
            query = store.get_query(query_id)
            if query is None:
                raise ValueError(f"运行缺少冻结 query：{query_id}")
            queries.append(query)
        evidence_revision = store.query_yield_evidence_revision(collection_run_id)
        report = build_query_yield_report(
            collection_run_id=collection_run_id,
            run_status=run["status"],
            queries=queries,
            matches=store.observation_query_matches(collection_run_id),
            screening_history=store.screening_history(
                collection_run_id=collection_run_id
            ),
            policy=policy_snapshot["policy"],
            assessment_mode=policy_snapshot["assessment_mode"],
        )
        report["evidence_revision"] = evidence_revision
        return report, policy_snapshot

    def evaluate_query_yield(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            report, _ = self._current_query_yield_report(
                store, collection_run_id
            )
            recorded = store.record_query_yield_report(
                collection_run_id,
                report,
                report["evidence_revision"],
            )
            store.record_audit(
                "query_yield_evaluated",
                "collection_run",
                collection_run_id,
                {
                    "query_yield_report_id": recorded["query_yield_report_id"],
                    "status": recorded["status"],
                    "calibration_passed": recorded["calibration_passed"],
                },
            )
            return recorded

    def query_yield_reports(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            if store.get_run(collection_run_id) is None:
                raise KeyError(collection_run_id)
            return store.query_yield_reports(collection_run_id)

    def query_yield_workspace(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            report, policy = self._current_query_yield_report(
                store, collection_run_id
            )
            reports = store.query_yield_reports(collection_run_id)
            latest = reports[-1] if reports else None
            return {
                "policy_snapshot": policy,
                "current_report": report,
                "report_history": reports,
                "latest_report_is_current": (
                    latest is not None
                    and latest["evidence_revision"] == report["evidence_revision"]
                ),
            }

    def quality_workspace(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None:
                raise KeyError(collection_run_id)
            observations = [
                {
                    **row,
                    "screening": store.latest_screening(row["observation_id"]),
                }
                for row in store.list_observations()
                if row["collection_run_id"] == collection_run_id
            ]
            return {
                "run": run,
                "governance": store.get_run_governance(collection_run_id),
                "observations": observations,
                "independent_annotations": store.independent_annotations(
                    collection_run_id
                ),
                "adjudications": store.adjudications(collection_run_id),
                "quality_reports": store.quality_reports(collection_run_id),
            }

    def adjudicate_observation(
        self,
        observation_id: str,
        *,
        adjudicator_id: str,
        object_type: str,
        object_label: str,
        aesthetic_terms: list[str],
        evidence_span: str,
        stance: str,
        confidence: float,
        reason: str,
        author_role: str,
    ) -> dict[str, Any]:
        clean_adjudicator_id = self._validate_coder_id(adjudicator_id)
        clean_terms = sorted(
            {term.strip() for term in aesthetic_terms if term.strip()},
            key=str.casefold,
        )
        if not reason.strip():
            raise ValueError("裁决必须填写理由")
        if not 0 <= confidence <= 1:
            raise ValueError("裁决置信度必须在 0 到 1 之间")
        with ResearchStore(self.database_path) as store:
            row = store.get_observation(observation_id)
            if row is None:
                raise KeyError(observation_id)
            record = json.loads(row["record_json"])
            annotations = store.independent_annotations(
                record["collection_run_id"], observation_id
            )
            coder_ids = {annotation["coder_id"] for annotation in annotations}
            if len(coder_ids) < 2:
                raise ValueError("裁决前必须有两位不同编码员的独立编码")
            if clean_adjudicator_id in coder_ids:
                raise ValueError("裁决者必须独立于两位原编码员")
            registry = store.get_run_registry(record["collection_run_id"])
            if registry is None or registry["binding_status"] != "bound":
                raise ValueError("运行缺少已锁定 registry，不能裁决")
            validate_registered_object(
                registry["snapshot"], object_type, object_label.strip()
            )
            validate_registered_terms(registry["snapshot"], clean_terms)
            if not clean_terms or stance not in STANCES or author_role not in AUTHOR_ROLES:
                raise ValueError("裁决需要审美术语、有效立场和已确认来源角色")
            if not evidence_span or evidence_span not in record["text"]:
                raise ValueError("裁决证据片段必须逐字出现在原文中")
            adjudication = {
                "object_type": object_type,
                "object_label": object_label.strip(),
                "aesthetic_terms": clean_terms,
                "evidence_span": evidence_span,
                "stance": stance,
                "confidence": confidence,
                "author_role": author_role,
            }
            record.update({
                "annotation_status": "human_verified",
                **adjudication,
                "annotation_confidence": confidence,
                "annotator_ref": clean_adjudicator_id,
                "human_verified_at": _now(),
                "exclusion_reason": None,
            })
            record.pop("confidence", None)
            record["normalization"]["record_sha256"] = hashlib.sha256(
                canonical_json(_normalization_hash_payload(record)).encode("utf-8")
            ).hexdigest()
            errors = validation_errors(record, validator())
            if errors:
                raise ValueError("adjudicated observation invalid: " + " | ".join(errors))
            result = store.record_adjudication(
                observation_id,
                clean_adjudicator_id,
                adjudication,
                reason.strip(),
                record,
            )
            store.record_audit(
                "observation_adjudicated",
                "observation",
                observation_id,
                {
                    "collection_run_id": record["collection_run_id"],
                    "adjudication_id": result["adjudication_id"],
                    "adjudicator_id": clean_adjudicator_id,
                },
            )
            return result

    def evaluate_run_quality(self, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            run = store.get_run(collection_run_id)
            if run is None:
                raise KeyError(collection_run_id)
            manifest = json.loads(run["manifest_json"])
            scopes = [
                self._run_scope_snapshot(store, run, query_id)
                for query_id in manifest.get("query_ids") or []
            ]
            registry = store.get_run_registry(collection_run_id)
            governance = store.get_run_governance(collection_run_id)
            observations = [
                row
                for row in store.list_observations()
                if row["collection_run_id"] == collection_run_id
                and (screening := store.latest_screening(row["observation_id"])) is not None
                and screening["decision"] == "include"
            ]
            annotations = store.independent_annotations(collection_run_id)
            adjudications = store.adjudications(collection_run_id)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for annotation in annotations:
                grouped.setdefault(annotation["observation_id"], []).append(annotation)
            double_coded_ids = {
                observation_id
                for observation_id, rows in grouped.items()
                if len({row["coder_id"] for row in rows}) >= 2
            }
            eligible_count = len(observations)
            required_double_coded = (
                eligible_count
                if eligible_count < 30
                else math.ceil(eligible_count * 0.20)
            )
            agreement = build_agreement_report(annotations)
            blockers = []
            if not scopes or any(scope["phase"] != "confirmatory" for scope in scopes):
                blockers.append("run_not_confirmatory")
            if run["status"] != "completed":
                blockers.append("run_not_completed")
            if registry is None or registry["binding_status"] != "bound":
                blockers.append("registry_not_bound")
            elif (
                any(
                    scope["registry_snapshot"] is None
                    or scope["registry_snapshot"].get("object_map_sha256")
                    != registry["object_map_sha256"]
                    or scope["registry_snapshot"].get("codebook_sha256")
                    != registry["codebook_sha256"]
                    for scope in scopes
                )
            ):
                blockers.append("registry_hash_mismatch")
            if governance is None or not governance["analysis_allowed"]:
                blockers.append("governance_blocks_research")
            if eligible_count == 0:
                blockers.append("no_screening_includes")
            if len(double_coded_ids) < required_double_coded:
                blockers.append("double_coding_coverage_below_protocol")
            if not agreement_passes(agreement):
                blockers.append("agreement_below_0.80")
            if any(
                not row["language_confirmed"] or row["author_role"] not in AUTHOR_ROLES
                for row in annotations
            ):
                blockers.append("language_or_author_role_unconfirmed")
            disagreement_ids = {
                observation_id
                for observation_id, rows in grouped.items()
                if len({
                    (
                        row["object_type"],
                        row["object_label"],
                        tuple(row["aesthetic_terms"]),
                        row["stance"],
                    )
                    for row in rows
                }) > 1
            }
            adjudicated_ids = {row["observation_id"] for row in adjudications}
            if disagreement_ids - adjudicated_ids:
                blockers.append("unadjudicated_disagreements")
            if any(row["annotation_status"] != "human_verified" for row in observations):
                blockers.append("gold_projection_incomplete")
            if any(row.get("author_role") not in AUTHOR_ROLES for row in observations):
                blockers.append("gold_author_role_incomplete")
            blockers = sorted(set(blockers))
            report = {
                "collection_run_id": collection_run_id,
                "protocol_version": "social_narrative_v0.1.0",
                "status": "passed" if not blockers else "failed",
                "eligible_count": eligible_count,
                "required_double_coded": required_double_coded,
                "double_coded_count": len(double_coded_ids),
                "double_coded_ratio": (
                    len(double_coded_ids) / eligible_count if eligible_count else 0.0
                ),
                "agreement": agreement,
                "disagreement_count": len(disagreement_ids),
                "adjudicated_disagreement_count": len(
                    disagreement_ids & adjudicated_ids
                ),
                "blockers": blockers,
                "quality_gate_passed": not blockers,
                "governance_release_allowed": bool(
                    governance and governance["release_allowed"]
                ),
                "evidence_revision": store.quality_evidence_revision(
                    collection_run_id
                ),
            }
            result = store.record_quality_report(collection_run_id, report)
            store.record_audit(
                "run_quality_evaluated",
                "collection_run",
                collection_run_id,
                {
                    "quality_report_id": result["quality_report_id"],
                    "status": result["status"],
                    "blockers": blockers,
                },
            )
            return result

    def set_run_release(
        self,
        collection_run_id: str,
        *,
        release_allowed: bool,
        reason: str,
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            if release_allowed:
                reports = store.quality_reports(collection_run_id)
                if not reports or reports[-1]["status"] != "passed":
                    raise ValueError("最新质量报告未通过，不能授权研究发布")
                if reports[-1].get("evidence_revision") != store.quality_evidence_revision(
                    collection_run_id
                ):
                    raise ValueError("质量报告生成后证据已变化，请重新执行质量检查")
            governance = store.set_run_release(
                collection_run_id,
                release_allowed=release_allowed,
                reason=reason,
                decided_by=REVIEWER_REF,
            )
            store.record_audit(
                "run_release_decided",
                "collection_run",
                collection_run_id,
                governance,
            )
            return governance

    def review_observation(
        self,
        observation_id: str,
        *,
        status: str,
        object_type: str,
        object_label: str,
        aesthetic_terms: list[str],
        evidence_span: str | None,
        stance: str | None,
        confidence: float | None,
        exclusion_reason: str | None,
        author_role: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"human_verified", "excluded", "candidate"}:
            raise ValueError("无效审核状态")
        with ResearchStore(self.database_path) as store:
            row = store.get_observation(observation_id)
            if row is None:
                raise KeyError(observation_id)
            record = json.loads(row["record_json"])
            run_governance = store.get_run_governance(record["collection_run_id"])
            if (
                status == "human_verified"
                and run_governance is not None
                and not run_governance["analysis_allowed"]
            ):
                raise ValueError("engineering-only 运行不能进入人工确认或主分析")
            run_registry = store.get_run_registry(record["collection_run_id"])
            if status == "human_verified":
                screening = store.latest_screening(observation_id)
                if screening is None or screening["decision"] != "include":
                    raise ValueError("人工确认前必须先通过 include 相关性筛选")
                if run_registry is None or run_registry["binding_status"] != "bound":
                    raise ValueError("运行缺少已锁定的 object map/codebook registry 快照")
                validate_registered_object(
                    run_registry["snapshot"], object_type, object_label.strip()
                )
            terms = sorted({term.strip() for term in aesthetic_terms if term.strip()}, key=str.casefold)
            if status == "human_verified":
                validate_registered_terms(run_registry["snapshot"], terms)
                if object_type not in OBJECT_TYPES or not object_label.strip() or not terms:
                    raise ValueError("人工确认需要对象类型、对象标签和至少一个审美术语")
                if not evidence_span or evidence_span not in record["text"]:
                    raise ValueError("证据片段必须逐字出现在原文中")
                if stance not in STANCES:
                    raise ValueError("人工确认需要有效立场标签")
                if confidence is None or not 0 <= confidence <= 1:
                    raise ValueError("审核置信度必须在 0 到 1 之间")
                if author_role is not None and author_role not in AUTHOR_ROLES:
                    raise ValueError("人工确认来源角色无效")
                record.update({
                    "annotation_status": status,
                    "object_type": object_type,
                    "object_label": object_label.strip(),
                    "aesthetic_terms": terms,
                    "evidence_span": evidence_span,
                    "stance": stance,
                    "annotation_confidence": confidence,
                    "annotator_ref": REVIEWER_REF,
                    "human_verified_at": _now(),
                    "exclusion_reason": None,
                })
                if author_role is not None:
                    record["author_role"] = author_role
            elif status == "excluded":
                if not exclusion_reason or not exclusion_reason.strip():
                    raise ValueError("排除记录必须填写原因")
                record.update({
                    "annotation_status": status,
                    "annotator_ref": REVIEWER_REF,
                    "human_verified_at": None,
                    "annotation_confidence": confidence,
                    "exclusion_reason": exclusion_reason.strip(),
                })
            else:
                record.update({
                    "annotation_status": status,
                    "annotator_ref": None,
                    "human_verified_at": None,
                    "annotation_confidence": None,
                    "exclusion_reason": None,
                })
            record["normalization"]["record_sha256"] = hashlib.sha256(
                canonical_json(_normalization_hash_payload(record)).encode("utf-8")
            ).hexdigest()
            errors = validation_errors(record, validator())
            if errors:
                raise ValueError("reviewed observation invalid: " + " | ".join(errors))
            store.update_observation(record, REVIEWER_REF)
            return record

    def analysis(self) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            records = store.list_analysis_observations()
        prepared = []
        for record in records:
            item = dict(record)
            item["_matrix_object"] = record["object_label"]
            item["_matrix_terms"] = record["aesthetic_terms"]
            prepared.append(item)
        matrix_a, matrix_b, lift = build_matrices(prepared, "records")
        _, _, _, time_series = build_context_outputs(prepared, "week")
        platform_summary: dict[str, int] = {}
        for record in prepared:
            platform = str(record.get("platform") or "unknown")
            platform_summary[platform] = platform_summary.get(platform, 0) + 1
        return {
            "included_records": len(prepared),
            "matrix_a": matrix_a,
            "matrix_b": matrix_b,
            "lift": lift,
            "time_series": time_series,
            "platform_summary": [
                {"platform": platform, "record_count": count}
                for platform, count in sorted(platform_summary.items())
            ],
        }

    def evidence(self, observation_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            result = store.evidence(observation_id)
        if result is None:
            raise KeyError(observation_id)
        return result

    def record_error(
        self,
        collection_run_id: str,
        *,
        cursor: int | None,
        error_code: str,
        message: str,
        payload_sha256: str | None = None,
        retryable: bool,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.record_error(
                collection_run_id,
                cursor=cursor,
                error_code=error_code,
                message=message,
                payload_sha256=payload_sha256,
                retryable=retryable,
            )

    def record_audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.record_audit(
                event_type, entity_type, entity_id, details
            )

    def set_youtube_daily_quota_budget(self, daily_budget: int) -> None:
        with ResearchStore(self.database_path) as store:
            store.set_youtube_daily_quota_budget(daily_budget)
            store.record_audit(
                "youtube_quota_budget_updated",
                "youtube_quota",
                "daily_budget",
                {"daily_budget": daily_budget},
            )

    def set_tiktok_daily_request_budget(self, daily_request_budget: int) -> None:
        with ResearchStore(self.database_path) as store:
            store.set_tiktok_daily_request_budget(daily_request_budget)
            store.record_audit(
                "tiktok_daily_request_budget_updated",
                "tiktok_quota",
                "global",
                {"daily_request_budget": daily_request_budget},
            )

    def reserve_tiktok_request(
        self,
        collection_run_id: str,
        operation: str,
        *,
        quota_date: str | None = None,
    ) -> int:
        with ResearchStore(self.database_path) as store:
            return store.reserve_tiktok_request(
                collection_run_id, operation, quota_date=quota_date
            )

    def finish_tiktok_request(
        self,
        request_event_id: int,
        *,
        outcome: str,
        error_code: str | None = None,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.finish_tiktok_request(
                request_event_id, outcome=outcome, error_code=error_code
            )

    def tiktok_quota_status(
        self, quota_date: str | None = None
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            return store.tiktok_quota_status(quota_date)

    def tiktok_request_events(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.tiktok_request_events(collection_run_id)

    def x_billing_status(self) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            return store.x_billing_status()

    def configure_x_billing_guard(
        self,
        *,
        local_cycle_spending_cap_microusd: int,
        console_hard_spending_limit_microusd: int,
        billing_cycle_start: str,
        billing_cycle_end: str,
        console_limit_confirmed: bool,
        confirmed_by: str,
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            status = store.configure_x_billing_guard(
                local_cycle_spending_cap_microusd=(
                    local_cycle_spending_cap_microusd
                ),
                console_hard_spending_limit_microusd=(
                    console_hard_spending_limit_microusd
                ),
                billing_cycle_start=billing_cycle_start,
                billing_cycle_end=billing_cycle_end,
                console_limit_confirmed=console_limit_confirmed,
                confirmed_by=confirmed_by,
            )
            store.record_audit(
                "x_billing_guard_configured",
                "x_billing",
                "global",
                {
                    "local_cycle_spending_cap_microusd": (
                        local_cycle_spending_cap_microusd
                    ),
                    "console_hard_spending_limit_microusd": (
                        console_hard_spending_limit_microusd
                    ),
                    "billing_cycle_start": billing_cycle_start,
                    "billing_cycle_end": billing_cycle_end,
                    "console_limit_confirmed": console_limit_confirmed,
                    "confirmed_by": confirmed_by,
                },
            )
            return status

    def x_run_billing_snapshot(
        self, collection_run_id: str
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            snapshot = store.x_run_billing_snapshot(collection_run_id)
        if snapshot is None:
            raise KeyError(collection_run_id)
        return snapshot

    def record_x_price_snapshot(
        self,
        *,
        unit_price_microusd: int,
        effective_date: str,
        source_url: str,
        pricing_policy_version: str,
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            snapshot = store.record_x_price_snapshot(
                unit_price_microusd=unit_price_microusd,
                effective_date=effective_date,
                source_url=source_url,
                pricing_policy_version=pricing_policy_version,
            )
            store.open_x_circuit_breaker("active_price_snapshot_changed")
            store.record_audit(
                "x_price_snapshot_recorded",
                "x_price_snapshot",
                str(snapshot["price_snapshot_id"]),
                {
                    "resource_type": snapshot["resource_type"],
                    "unit_price_microusd": snapshot["unit_price_microusd"],
                    "effective_date": snapshot["effective_date"],
                    "source_url": snapshot["source_url"],
                    "pricing_policy_version": snapshot[
                        "pricing_policy_version"
                    ],
                },
            )
            return snapshot

    def reserve_x_request(
        self, collection_run_id: str, *, max_resources: int
    ) -> int:
        with ResearchStore(self.database_path) as store:
            return store.reserve_x_request(
                collection_run_id, max_resources=max_resources
            )

    def finish_x_request(
        self,
        request_event_id: int,
        *,
        outcome: str,
        actual_resources: int,
        error_code: str | None = None,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.finish_x_request(
                request_event_id,
                outcome=outcome,
                actual_resources=actual_resources,
                error_code=error_code,
            )

    def x_request_events(
        self, collection_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.x_request_events(collection_run_id)

    def open_x_circuit_breaker(self, reason: str) -> None:
        with ResearchStore(self.database_path) as store:
            store.open_x_circuit_breaker(reason)
            store.record_audit(
                "x_circuit_breaker_opened",
                "x_billing",
                "global",
                {"reason": reason},
            )

    def set_youtube_quota_budgets(
        self,
        *,
        shared_unit_budget: int,
        search_call_budget: int,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.set_youtube_quota_budgets(
                shared_unit_budget=shared_unit_budget,
                search_call_budget=search_call_budget,
            )
            store.record_audit(
                "youtube_quota_budgets_updated",
                "youtube_quota",
                "current_policy",
                {
                    "shared_unit_budget": shared_unit_budget,
                    "search_call_budget": search_call_budget,
                },
            )

    def consume_youtube_quota(
        self,
        collection_run_id: str,
        operation: str,
        *,
        now: datetime | None = None,
    ) -> int:
        units = YOUTUBE_QUOTA_COSTS.get(operation)
        with ResearchStore(self.database_path) as store:
            policy = store.get_run_quota_policy(collection_run_id)
            if policy is None:
                raise ValueError("YouTube 运行缺少配额政策快照")
            costs = (
                LEGACY_YOUTUBE_QUOTA_COSTS
                if policy["policy_version"] == LEGACY_YOUTUBE_QUOTA_POLICY
                else YOUTUBE_QUOTA_COSTS
            )
            units = costs.get(operation)
            if units is None:
                raise ValueError(f"未知 YouTube API 配额操作：{operation}")
            return store.consume_youtube_quota(
                collection_run_id, operation, units, now=now
            )

    def finish_youtube_quota_event(self, quota_event_id: int, outcome: str) -> None:
        with ResearchStore(self.database_path) as store:
            store.finish_youtube_quota_event(quota_event_id, outcome)

    def youtube_quota_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            return store.youtube_quota_status(now=now)

    def save_youtube_run_state(
        self, collection_run_id: str, state: dict[str, Any]
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_youtube_run_state(collection_run_id, state)

    def youtube_run_state(self, collection_run_id: str) -> dict[str, Any] | None:
        with ResearchStore(self.database_path) as store:
            return store.youtube_run_state(collection_run_id)

    def save_youtube_published_after(self, scope_id: str, published_after: str) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_youtube_published_after(scope_id, published_after)

    def youtube_published_after(self, scope_id: str) -> str | None:
        with ResearchStore(self.database_path) as store:
            return store.youtube_published_after(scope_id)

    def save_mastodon_instance_state(
        self,
        collection_run_id: str,
        query_id: str,
        observed_instance: str,
        **state: Any,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_mastodon_instance_state(
                collection_run_id,
                query_id,
                normalize_instance(observed_instance),
                **state,
            )

    def mastodon_instance_states(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.mastodon_instance_states(collection_run_id)

    def mastodon_sightings(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.mastodon_sightings(collection_run_id)

    def save_api_collection_state(
        self,
        collection_run_id: str,
        platform: str,
        query_id: str,
        partition_key: str,
        state: dict[str, Any],
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_api_collection_state(
                collection_run_id,
                platform,
                query_id,
                partition_key,
                state,
                status=status,
                error_code=error_code,
                error_message=error_message,
            )

    def api_collection_states(
        self, collection_run_id: str
    ) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.api_collection_states(collection_run_id)

    def save_api_scope_state(
        self,
        scope_id: str,
        platform: str,
        query_id: str,
        partition_key: str,
        state: dict[str, Any],
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_api_scope_state(
                scope_id, platform, query_id, partition_key, state
            )

    def api_scope_state(
        self, scope_id: str, query_id: str, partition_key: str
    ) -> dict[str, Any] | None:
        with ResearchStore(self.database_path) as store:
            return store.api_scope_state(scope_id, query_id, partition_key)

    def save_mastodon_scope_high_watermark(
        self,
        scope_id: str,
        query_id: str,
        observed_instance: str,
        max_status_id: str,
    ) -> None:
        with ResearchStore(self.database_path) as store:
            store.save_mastodon_scope_high_watermark(
                scope_id,
                query_id,
                normalize_instance(observed_instance),
                max_status_id,
            )

    def mastodon_scope_high_watermark(
        self, scope_id: str, query_id: str, observed_instance: str
    ) -> str | None:
        with ResearchStore(self.database_path) as store:
            return store.mastodon_scope_high_watermark(
                scope_id, query_id, normalize_instance(observed_instance)
            )

    def cursor(self, platform: str = "bluesky") -> int | None:
        with ResearchStore(self.database_path) as store:
            return store.get_cursor(platform)

    def finish_run(self, collection_run_id: str, status: str) -> None:
        if not re.fullmatch(r"completed|stopped|failed|awaiting_screening", status):
            raise ValueError("invalid internal run status")
        with ResearchStore(self.database_path) as store:
            store.finish_run(collection_run_id, status)
            store.record_audit(
                "run_finished", "collection_run", collection_run_id, {"status": status}
            )

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            schedule = store.get_schedule(schedule_id)
        if schedule is None:
            raise KeyError(schedule_id)
        return schedule

    def record_schedule_run(self, schedule_id: str, collection_run_id: str) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            schedule = store.record_schedule_run(schedule_id, collection_run_id)
            store.record_audit(
                "schedule_triggered",
                "schedule",
                schedule_id,
                {"collection_run_id": collection_run_id},
            )
            return schedule

    def recover_interrupted_runs(self) -> list[str]:
        recovered = []
        with ResearchStore(self.database_path) as store:
            for run in store.interrupted_runs():
                run_id = run["collection_run_id"]
                store.record_error(
                    run_id,
                    cursor=store.get_cursor(run["platform"]),
                    error_code="startup_interrupted",
                    message="服务重启时发现未正常结束的采集任务；可从保存游标重跑。",
                    payload_sha256=None,
                    retryable=True,
                )
                store.finish_run(run_id, "failed")
                store.record_audit(
                    "run_recovered", "collection_run", run_id, {"status": "failed"}
                )
                recovered.append(run_id)
        return recovered

    def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_audit(limit)

    def set_run_governance(
        self,
        collection_run_id: str,
        *,
        usage_classification: str,
        reason: str,
    ) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            governance = store.set_run_governance(
                collection_run_id,
                usage_classification=usage_classification,
                reason=reason,
                decided_by=REVIEWER_REF,
            )
            store.record_audit(
                "run_governance_decided",
                "collection_run",
                collection_run_id,
                governance,
            )
            return governance

    def export_run(self, collection_run_id: str, destination_root: Path) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            data = store.export_data(collection_run_id)
            current_query_yield, _ = self._current_query_yield_report(
                store, collection_run_id
            )
        if data["run"]["status"] == "running":
            raise ValueError("运行中的采集任务不能导出")
        result = build_export(
            destination_root,
            collection_run_id=collection_run_id,
            manifest=data["manifest"],
            observations=data["observations"],
            queries=data["queries"],
            sources=data["sources"],
            review_history=data["review_history"],
            screening_history=data["screening_history"],
            audit=data["audit"],
            youtube_quota_usage=data["youtube_quota_usage"],
            run_governance=data["run_governance"],
            run_registry=data["run_registry"],
            run_quota_policy=data["run_quota_policy"],
            independent_annotations=data["independent_annotations"],
            adjudications=data["adjudications"],
            quality_reports=data["quality_reports"],
            query_yield_policy=data["query_yield_policy"],
            query_yield_reports=data["query_yield_reports"],
            current_query_yield=current_query_yield,
            observation_query_matches=data["observation_query_matches"],
            mastodon_instance_states=data["mastodon_instance_states"],
            mastodon_sightings=data["mastodon_sightings"],
            api_collection_states=data["api_collection_states"],
            tiktok_request_events=data["tiktok_request_events"],
            tiktok_quota_snapshot=data["tiktok_quota_snapshot"],
            x_request_events=data["x_request_events"],
            x_run_billing_snapshot=data["x_run_billing_snapshot"],
            x_billing_status=data["x_billing_status"],
        )
        with ResearchStore(self.database_path) as store:
            store.record_audit(
                "run_exported",
                "collection_run",
                collection_run_id,
                {
                    "archive": Path(result["archive"]).name,
                    "record_count": result["record_count"],
                    "narrative_count": result["narrative_count"],
                },
            )
        return result

    def create_backup(self, backup_root: Path, *, reason: str = "manual") -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            store.record_audit(
                "backup_started", "database", self.database_path.name, {"reason": reason}
            )
        manifest = create_backup(self.database_path, backup_root, reason=reason)
        with ResearchStore(self.database_path) as store:
            store.record_audit(
                "backup_created",
                "backup",
                manifest["backup_id"],
                {"reason": reason, "sha256": manifest["sha256"]},
            )
        return manifest

    def list_backups(self, backup_root: Path) -> list[dict[str, Any]]:
        return list_backups(backup_root)

    def restore_backup(self, backup_root: Path, backup_id: str) -> dict[str, Any]:
        safety = self.create_backup(backup_root, reason=f"pre_restore:{backup_id}")
        result = restore_backup(self.database_path, backup_root, backup_id)
        source_schema_version = result["schema_version"]
        with ResearchStore(self.database_path) as store:
            store.record_audit(
                "database_restored",
                "backup",
                backup_id,
                {"pre_restore_backup_id": safety["backup_id"]},
            )
        result["pre_restore_backup_id"] = safety["backup_id"]
        result["source_schema_version"] = source_schema_version
        result["schema_version"] = SCHEMA_VERSION
        return result

    def monitoring(self, backup_root: Path) -> dict[str, Any]:
        with ResearchStore(self.database_path) as store:
            status = store.monitoring()
        x_billing = self.x_billing_status()
        x_cost_microusd = int(x_billing["accrued_cost_microusd"])
        status.update({
            "platforms": ["bluesky", "youtube", "mastodon", "reddit", "tiktok", "x"],
            "sources": [
                "Bluesky Jetstream public stream",
                "YouTube Data API v3",
                "Mastodon selected-instance REST APIs",
                "Reddit Data API",
                "TikTok Research API",
                "X API v2 recent search",
            ],
            "api_cost": x_cost_microusd / 1_000_000,
            "api_cost_microusd": x_cost_microusd,
            "cost_currency": "USD",
            "cost_basis": "Bluesky Jetstream 与 Mastodon 实例 API 无平台 API 账单；YouTube Data API 以配额单位计量而非美元计费；Reddit 访问资格、限额与可能费用以获批时有效条款和运行时响应为准；TikTok Research API 仅在获批后可用，本机未记录任何真实 Reddit 或 TikTok 费用；X 按 run 绑定的日期化 post_read 价格快照及实际返回资源数，以整数微美元记账。",
            "quota_basis": "Bluesky 由 max_items 约束；YouTube 2026-06-01 政策分别守卫每日 search.list 调用桶和其他端点共享单位桶；Mastodon 按冻结实例、每页数量、每实例页数、逐请求间隔与总 max_items 约束；Reddit 按冻结 subreddit、页数、每页数量、逐请求间隔、总 max_items 与 X-Ratelimit-* 响应头约束；TikTok 按冻结 query AST、最多 30 个 UTC 整日、分层页数与条数、总 max_items 及本机每日请求预算约束；X 在每次 GET 前按 max_results 预留最坏成本，并同时守卫 run 预算、本机 billing-cycle cap 与已确认的 Developer Console hard spending limit。",
            "youtube_quota": self.youtube_quota_status(),
            "tiktok_quota": self.tiktok_quota_status(),
            "x_billing": x_billing,
            "backup_count": len(self.list_backups(backup_root)),
            "checked_at": _now(),
        })
        return status

    def errors(self, collection_run_id: str | None = None) -> list[dict[str, Any]]:
        with ResearchStore(self.database_path) as store:
            return store.list_errors(collection_run_id)
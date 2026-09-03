"""Validated per-run exports for the local social-narrative system."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from tools.project_social_to_narratives import project_record
from tools.social_io import schema_validator, write_jsonl
from tools.summarize_narratives import run as summarize
from tools.validate_social_observations import validate


ROOT = Path(__file__).resolve().parents[3]
NARRATIVE_SCHEMA = ROOT / "schema" / "cultural_narrative.schema.json"
QUERY_FIELDS = [
    "query_id", "platform", "language_bcp47", "region_hint", "object_group",
    "query_text", "aesthetic_terms", "brand_context", "window_start",
    "window_end", "max_items", "sampling_method", "deduplication_rule",
    "inclusion_rule", "exclusion_rule", "owner", "status", "notes",
    "query_family", "phase", "exact_query", "sort_order",
    "object_type_target", "object_label_target", "query_config_sha256",
    "object_map_version", "object_map_sha256", "codebook_version",
    "codebook_sha256", "max_videos_per_query",
    "max_comment_threads_per_video", "max_replies_per_thread",
    "calibration_run_id", "calibration_source_query_id",
    "calibration_report_id", "calibration_policy_version",
    "platform_options_json", "mastodon_instances",
    "mastodon_access_method", "mastodon_page_size",
    "mastodon_max_pages_per_instance", "mastodon_request_delay_seconds",
    "reddit_subreddits", "reddit_access_method", "reddit_sort",
    "reddit_time_filter", "reddit_page_size",
    "reddit_max_pages_per_subreddit", "reddit_request_delay_seconds",
    "tiktok_query_json", "tiktok_video_page_size",
    "tiktok_max_video_pages", "tiktok_comment_page_size",
    "tiktok_max_comment_pages_per_video", "tiktok_reply_page_size",
    "tiktok_max_reply_pages_per_comment", "tiktok_request_delay_seconds",
    "x_query", "x_page_size", "x_max_pages",
    "x_request_delay_seconds", "x_local_run_budget_microusd",
    "x_post_fields",
]
SOURCE_FIELDS = [
    "source_id", "source_type", "title", "publisher_or_creator", "url",
    "published_at", "accessed_at", "language_bcp47", "region",
    "license_status", "license_text_or_id", "redistribution_allowed",
    "local_archive", "notes",
]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _query_rows(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for query in queries:
        quotas = query.get("layer_quotas") or {}
        promotion = query.get("promotion_evidence") or {}
        platform_options = query.get("platform_options") or {}
        tiktok_options = platform_options if query.get("platform") == "tiktok" else {}
        x_options = platform_options if query.get("platform") == "x" else {}
        rows.append({
            **query,
            "max_videos_per_query": quotas.get("max_videos"),
            "max_comment_threads_per_video": quotas.get(
                "max_comment_threads_per_video"
            ),
            "max_replies_per_thread": quotas.get("max_replies_per_thread"),
            "calibration_run_id": promotion.get("collection_run_id"),
            "calibration_source_query_id": promotion.get("source_query_id"),
            "calibration_report_id": promotion.get("query_yield_report_id"),
            "calibration_policy_version": promotion.get("policy_version"),
            "platform_options_json": json.dumps(
                platform_options, ensure_ascii=False, sort_keys=True
            ) if platform_options else None,
            "mastodon_instances": "|".join(platform_options.get("instances") or []),
            "mastodon_access_method": platform_options.get("access_method"),
            "mastodon_page_size": platform_options.get("page_size"),
            "mastodon_max_pages_per_instance": platform_options.get(
                "max_pages_per_instance"
            ),
            "mastodon_request_delay_seconds": platform_options.get(
                "request_delay_seconds"
            ),
            "reddit_subreddits": "|".join(platform_options.get("subreddits") or []),
            "reddit_access_method": platform_options.get("access_method"),
            "reddit_sort": platform_options.get("sort"),
            "reddit_time_filter": platform_options.get("time_filter"),
            "reddit_page_size": platform_options.get("page_size"),
            "reddit_max_pages_per_subreddit": platform_options.get(
                "max_pages_per_subreddit"
            ),
            "reddit_request_delay_seconds": platform_options.get(
                "request_delay_seconds"
            ),
            "tiktok_query_json": json.dumps(
                tiktok_options.get("query"), ensure_ascii=False, sort_keys=True
            ) if tiktok_options.get("query") else None,
            "tiktok_video_page_size": tiktok_options.get("video_page_size"),
            "tiktok_max_video_pages": tiktok_options.get("max_video_pages"),
            "tiktok_comment_page_size": tiktok_options.get("comment_page_size"),
            "tiktok_max_comment_pages_per_video": tiktok_options.get(
                "max_comment_pages_per_video"
            ),
            "tiktok_reply_page_size": tiktok_options.get("reply_page_size"),
            "tiktok_max_reply_pages_per_comment": tiktok_options.get(
                "max_reply_pages_per_comment"
            ),
            "tiktok_request_delay_seconds": tiktok_options.get(
                "request_delay_seconds"
            ),
            "x_query": x_options.get("query"),
            "x_page_size": x_options.get("page_size"),
            "x_max_pages": x_options.get("max_pages"),
            "x_request_delay_seconds": x_options.get(
                "request_delay_seconds"
            ),
            "x_local_run_budget_microusd": x_options.get(
                "local_run_budget_microusd"
            ),
            "x_post_fields": x_options.get("post_fields"),
        })
    return rows


def build_export(
    destination_root: Path,
    *,
    collection_run_id: str,
    manifest: dict[str, Any],
    observations: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    review_history: list[dict[str, Any]],
    screening_history: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    youtube_quota_usage: list[dict[str, Any]],
    run_governance: dict[str, Any] | None,
    run_registry: dict[str, Any] | None,
    run_quota_policy: dict[str, Any] | None,
    independent_annotations: list[dict[str, Any]],
    adjudications: list[dict[str, Any]],
    quality_reports: list[dict[str, Any]],
    query_yield_policy: dict[str, Any] | None,
    query_yield_reports: list[dict[str, Any]],
    current_query_yield: dict[str, Any],
    observation_query_matches: list[dict[str, Any]],
    mastodon_instance_states: list[dict[str, Any]],
    mastodon_sightings: list[dict[str, Any]],
    api_collection_states: list[dict[str, Any]],
    tiktok_request_events: list[dict[str, Any]],
    tiktok_quota_snapshot: dict[str, Any] | None,
    x_request_events: list[dict[str, Any]],
    x_run_billing_snapshot: dict[str, Any] | None,
    x_billing_status: dict[str, Any],
) -> dict[str, Any]:
    destination_root.mkdir(parents=True, exist_ok=True)
    staging = destination_root / f".{collection_run_id}.{uuid.uuid4().hex}.tmp"
    final_dir = destination_root / collection_run_id
    archive = destination_root / f"{collection_run_id}.zip"
    staging.mkdir()
    try:
        observations_path = staging / "observations.jsonl"
        manifest_path = staging / "run_manifest.json"
        queries_path = staging / "queries.csv"
        sources_path = staging / "sources.csv"
        narratives_path = staging / "narratives.jsonl"
        write_jsonl(observations_path, observations)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(queries_path, _query_rows(queries), QUERY_FIELDS)
        _write_csv(sources_path, sources, SOURCE_FIELDS)
        write_jsonl(staging / "review_history.jsonl", review_history)
        write_jsonl(staging / "screening_history.jsonl", screening_history)
        write_jsonl(staging / "independent_annotations.jsonl", independent_annotations)
        write_jsonl(staging / "adjudications.jsonl", adjudications)
        write_jsonl(staging / "quality_reports.jsonl", quality_reports)
        write_jsonl(staging / "query_yield_reports.jsonl", query_yield_reports)
        (staging / "query_yield_policy.json").write_text(
            json.dumps(
                query_yield_policy,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        (staging / "yield_calibration.json").write_text(
            json.dumps(
                current_query_yield,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        write_jsonl(
            staging / "observation_query_matches.jsonl",
            observation_query_matches,
        )
        (staging / "audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "run_governance.json").write_text(
            json.dumps(
                run_governance,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        (staging / "run_registry.json").write_text(
            json.dumps(
                run_registry,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        if manifest["platform"] == "youtube":
            (staging / "youtube_quota_policy.json").write_text(
                json.dumps(
                    run_quota_policy,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            (staging / "youtube_quota_usage.json").write_text(
                json.dumps(
                    youtube_quota_usage,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
        if manifest["platform"] == "mastodon":
            (staging / "mastodon_instance_states.json").write_text(
                json.dumps(
                    mastodon_instance_states,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            write_jsonl(staging / "mastodon_sightings.jsonl", mastodon_sightings)
        if manifest["platform"] == "tiktok":
            (staging / "tiktok_request_events.json").write_text(
                json.dumps(
                    tiktok_request_events,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            (staging / "tiktok_quota_snapshot.json").write_text(
                json.dumps(
                    tiktok_quota_snapshot,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
        if manifest["platform"] == "x":
            (staging / "x_request_events.json").write_text(
                json.dumps(
                    x_request_events,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            (staging / "x_run_billing_snapshot.json").write_text(
                json.dumps(
                    x_run_billing_snapshot,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            (staging / "x_billing_status.json").write_text(
                json.dumps(
                    x_billing_status,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
        if api_collection_states:
            (staging / "api_collection_states.json").write_text(
                json.dumps(
                    api_collection_states,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )

        validation = validate(
            observations_path,
            queries_path=queries_path,
            sources_path=sources_path,
            run_manifest_path=manifest_path,
        )
        (staging / "validation.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not validation["valid"]:
            codes = ", ".join(
                item["code"] for item in validation["messages"]
                if item["severity"] == "error"
            )
            raise ValueError(f"导出验证失败：{codes}")

        narrative_check = schema_validator(NARRATIVE_SCHEMA)
        analysis_observations = (
            observations
            if run_governance is not None and run_governance["analysis_allowed"]
            else []
        )
        narratives = []
        for observation in analysis_observations:
            narratives.extend(
                project_record(
                    observation,
                    default_confidence=None,
                    check=narrative_check,
                )
            )
        narratives.sort(key=lambda row: row["evidence_id"])
        write_jsonl(narratives_path, narratives)

        analysis_input_path = staging / ".analysis_observations.jsonl"
        write_jsonl(analysis_input_path, analysis_observations)
        exit_code = summarize(argparse.Namespace(
            input=analysis_input_path,
            output_dir=staging / "matrices",
            status=["human_verified"],
            platform=manifest["platform"],
            language=None,
            collection_run_id=collection_run_id,
            weight="records",
            time_granularity="week",
            force=False,
        ))
        if exit_code:
            raise ValueError("矩阵生成失败")
        analysis_input_path.unlink()

        if final_dir.exists():
            shutil.rmtree(final_dir)
        staging.replace(final_dir)
        archive.unlink(missing_ok=True)
        shutil.make_archive(str(archive.with_suffix("")), "zip", final_dir)
        return {
            "collection_run_id": collection_run_id,
            "directory": str(final_dir),
            "archive": str(archive),
            "record_count": len(observations),
            "narrative_count": len(narratives),
            "valid": True,
            "warnings": [
                item for item in validation["messages"]
                if item["severity"] == "warning"
            ],
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
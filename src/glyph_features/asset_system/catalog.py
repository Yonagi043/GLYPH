"""Portable identifiers, hashing, and schema validation for asset records."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class AssetSystemError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_id(prefix: str, value: Any, length: int = 24) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError(f"invalid ID prefix: {prefix}")
    return f"{prefix}_{hashlib.sha256(canonical_json(value)).hexdigest()[:length]}"


def normalize_repo_path(raw_path: str | Path) -> str:
    value = str(raw_path).strip().replace("\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise ValueError(f"asset path must be repository-relative: {raw_path}")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"asset path is not normalized: {raw_path}")
    return PurePosixPath(*parts).as_posix()


def resolve_workspace_asset(
    workspace_root: str | Path,
    asset_ref: dict[str, Any],
) -> Path:
    root = Path(workspace_root).resolve()
    raw_path = str(asset_ref.get("path", ""))
    try:
        relative_path = normalize_repo_path(raw_path)
    except ValueError as error:
        raise AssetSystemError("ASSET_PATH_NOT_CANONICAL", raw_path) from error
    if raw_path != relative_path:
        raise AssetSystemError("ASSET_PATH_NOT_CANONICAL", raw_path)
    unresolved = root / relative_path
    try:
        resolved = unresolved.resolve(strict=True)
    except FileNotFoundError as error:
        raise AssetSystemError("ASSET_FILE_MISSING", relative_path) from error
    except OSError as error:
        raise AssetSystemError("ASSET_PATH_UNRESOLVABLE", relative_path) from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise AssetSystemError("ASSET_PATH_OUTSIDE_WORKSPACE", relative_path) from error
    if not resolved.is_file():
        raise AssetSystemError("ASSET_NOT_REGULAR_FILE", relative_path)
    expected_size = asset_ref.get("byte_size")
    actual_size = resolved.stat().st_size
    if not isinstance(expected_size, int) or expected_size != actual_size:
        raise AssetSystemError(
            "ASSET_BYTE_SIZE_MISMATCH",
            f"{relative_path}: expected {expected_size}, got {actual_size}",
        )
    expected_sha256 = str(asset_ref.get("sha256", ""))
    actual_sha256 = sha256_file(resolved)
    if expected_sha256 != actual_sha256:
        raise AssetSystemError(
            "ASSET_SHA256_MISMATCH",
            f"{relative_path}: expected {expected_sha256}, got {actual_sha256}",
        )
    return resolved


def load_json_config(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("asset config must be JSON-compatible YAML") from exc
    if not isinstance(value, dict):
        raise ValueError("asset config root must be an object")
    return value


def validate_record(record: dict[str, Any], schema_path: str | Path) -> list[str]:
    schema_file = Path(schema_path).resolve()
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    registry = Registry()
    for candidate in schema_file.parent.glob("*.schema.json"):
        candidate_schema = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(candidate_schema)
        registry = registry.with_resource(candidate.name, resource).with_resource(candidate.as_uri(), resource)
    validator = Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )
    return [error.message for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path))]


def migrate_award_sources(repo_root: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    normalized_rows: list[dict[str, Any]] = []
    canonical_sources: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    asset_source_map: dict[str, dict[str, Any]] = {}

    for award in config["awards"]:
        award_dir = root / config["inventory"]["award_roots"][award]
        source_path = award_dir / "sources.csv"
        source_relative = source_path.relative_to(root).as_posix()
        source_hash = sha256_file(source_path)
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.reader(handle))
        header, rows = raw_rows[0], raw_rows[1:]
        files = sorted(
            path for path in award_dir.rglob("*")
            if path.is_file() and path.name != "sources.csv"
        )
        by_name: dict[str, list[Path]] = {}
        by_relative: dict[str, Path] = {}
        for path in files:
            by_name.setdefault(path.name, []).append(path)
            by_relative[path.relative_to(award_dir).as_posix()] = path
        used_paths: set[str] = set()
        width_counts = Counter(len(row) for row in rows)
        snapshots.append(
            {
                "award": award,
                "path": source_relative,
                "sha256": source_hash,
                "row_count": len(rows),
                "header": header,
                "row_widths": {str(key): value for key, value in sorted(width_counts.items())},
            }
        )

        for row_number, raw_row in enumerate(rows, start=2):
            repair_codes: list[str] = []
            if len(raw_row) == len(header):
                legacy = dict(zip(header, raw_row, strict=True))
            elif award == "GDC" and len(raw_row) == 9:
                legacy = dict(
                    zip(
                        ["award", "year", "bo", "work_id", "file", "url", "bytes", "page", "fetched"],
                        raw_row,
                        strict=True,
                    )
                )
                repair_codes.append("GDC_SHIFTED_COLUMNS")
                issues.append(_issue(award, source_relative, row_number, "GDC_SHIFTED_COLUMNS", legacy["file"]))
            else:
                issues.append(_issue(award, source_relative, row_number, "SOURCE_ROW_WIDTH_INVALID", ""))
                continue

            recorded_file = legacy.get("file", "").strip()
            year = _integer_or_none(legacy.get("year"))
            local_path, path_repair = _resolve_source_file(
                recorded_file,
                by_name,
                by_relative,
                award_dir=award_dir,
                year=year,
            )
            if path_repair:
                if path_repair == "SOURCE_FILENAME_EXTENSION_REPAIRED":
                    repair_codes.append(path_repair)
                issues.append(_issue(award, source_relative, row_number, path_repair, recorded_file))
            relative_path = local_path.relative_to(root).as_posix() if local_path else ""
            if not local_path and path_repair != "SOURCE_FILE_AMBIGUOUS":
                issues.append(_issue(award, source_relative, row_number, "SOURCE_WITHOUT_FILE", recorded_file))
            elif relative_path in used_paths:
                issues.append(_issue(award, source_relative, row_number, "SOURCE_DUPLICATE_FILE_ROW", relative_path))
                continue
            else:
                used_paths.add(relative_path)

            asset_url = legacy.get("url", "").strip()
            page_url = legacy.get("page", "").strip()
            for field, value in (("url", asset_url), ("page", page_url)):
                if urlparse(value).scheme not in {"http", "https"}:
                    issues.append(_issue(award, source_relative, row_number, "SOURCE_URL_INVALID", f"{field}:{value}"))
            source_id = stable_id("source", {"award": award, "asset_url": asset_url})
            work_id = _work_id(award, legacy, asset_url, page_url)
            title = (legacy.get("project") or legacy.get("title") or recorded_file).strip()
            creator = (legacy.get("company") or legacy.get("creator") or "").strip()
            fetched_at = legacy.get("fetched", "").strip()
            normalized = {
                "source_id": source_id,
                "award": award,
                "year": year,
                "edition": _edition(award, year, legacy),
                "work_id": work_id,
                "local_path": relative_path,
                "recorded_file": recorded_file,
                "asset_url": asset_url,
                "source_page_url": page_url,
                "bytes_reported": _integer_or_none(legacy.get("bytes")),
                "award_status": (legacy.get("tier") or "").strip() or None,
                "title": title,
                "creator": creator or None,
                "category": (legacy.get("sub_category") or legacy.get("category") or "").strip() or None,
                "fetched_at": fetched_at,
                "legacy_source_path": source_relative,
                "legacy_source_sha256": source_hash,
                "legacy_row_number": row_number,
                "repair_codes": sorted(set(repair_codes)),
            }
            normalized_rows.append(normalized)
            if relative_path:
                asset_source_map[relative_path] = normalized
            source_record = _source_schema_record(root, normalized, config["inventory"]["snapshot_date"])
            canonical_sources.setdefault(source_id, source_record)

        for path in files:
            relative_path = path.relative_to(root).as_posix()
            if relative_path not in used_paths:
                issues.append(_issue(award, source_relative, None, "FILE_WITHOUT_SOURCE", relative_path))

    return {
        "source_table_snapshots": snapshots,
        "normalized_rows": normalized_rows,
        "canonical_sources": [canonical_sources[key] for key in sorted(canonical_sources)],
        "issues": issues,
        "asset_source_map": asset_source_map,
    }


def build_repository_inventory(
    repo_root: str | Path,
    config: dict[str, Any],
    source_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .qc import duplicate_annotations, inspect_font, inspect_image

    root = Path(repo_root).resolve()
    audit = source_audit or migrate_award_sources(root, config)
    image_drafts: list[dict[str, Any]] = []
    for award in config["awards"]:
        award_dir = root / config["inventory"]["award_roots"][award]
        for path in sorted(item for item in award_dir.rglob("*") if item.is_file() and item.name != "sources.csv"):
            relative_path = path.relative_to(root).as_posix()
            source_row = audit["asset_source_map"].get(relative_path)
            inspection = inspect_image(
                path,
                max_pixels=int(config["qc"]["max_pixels"]),
                assume_srgb_without_profile=bool(config["qc"]["assume_srgb_without_profile"]),
            )
            source_id = source_row["source_id"] if source_row else stable_id("source_missing", {"path": relative_path})
            asset_id = stable_id(
                "asset",
                {"source_id": source_id, "sha256": inspection["sha256"], "path": relative_path},
            )
            image_drafts.append(
                {
                    "asset_id": asset_id,
                    "award": award,
                    "path": path,
                    "relative_path": relative_path,
                    "source": source_row,
                    **inspection,
                }
            )
    duplicate_input = [
        {
            "asset_id": draft["asset_id"],
            "sha256": draft["sha256"],
            "perceptual_hash": draft["perceptual_hash"],
        }
        for draft in image_drafts
    ]
    annotations = duplicate_annotations(
        duplicate_input,
        near_threshold=int(config["qc"]["near_duplicate_hamming_distance"]),
    )

    candidates: list[dict[str, Any]] = []
    for draft, annotation in zip(image_drafts, annotations, strict=True):
        qc = draft["automated_qc"]
        qc["hash_duplicate_status"] = annotation["hash_duplicate_status"]
        qc["perceptual_duplicate_status"] = annotation["perceptual_duplicate_status"]
        exclusion_codes = ["RIGHTS_BLOCKED"]
        if annotation["hash_duplicate_status"] == "duplicate_exact":
            qc["failure_codes"] = sorted(set(qc["failure_codes"] + ["QC_EXACT_DUPLICATE"]))
            exclusion_codes.append("DUPLICATE_EXACT")
        if annotation["perceptual_duplicate_status"] == "duplicate_near":
            qc["failure_codes"] = sorted(set(qc["failure_codes"] + ["QC_NEAR_DUPLICATE"]))
            exclusion_codes.append("DUPLICATE_NEAR")
        if "QC_PIXEL_LIMIT_EXCEEDED" in qc["failure_codes"]:
            exclusion_codes.append("PIXEL_LIMIT_EXCEEDED")
        if draft["source"] is None:
            qc["failure_codes"] = sorted(set(qc["failure_codes"] + ["QC_SOURCE_MISSING"]))
            exclusion_codes.append("SOURCE_MISSING")
        suggestion = _classification_suggestion(draft, annotation)
        source = draft["source"]
        candidates.append(
            {
                "schema_version": "1.0.0",
                "asset_id": draft["asset_id"],
                "record_origin": "repository_asset",
                "source_id": source["source_id"] if source else stable_id("source_missing", {"path": draft["relative_path"]}),
                "parent_asset_id": None,
                "work_id": source["work_id"] if source else None,
                "asset_role": "original",
                "candidate_kind": "ecological_award_image",
                "asset_ref": {
                    "path": draft["relative_path"],
                    "sha256": draft["sha256"],
                    "mime_type": draft["mime_type"],
                    "byte_size": draft["byte_size"],
                },
                "pixel_metadata": draft["pixel_metadata"],
                "rights_tier": "blocked_unknown",
                "transform": None,
                "automated_qc": qc,
                "classification": {
                    "automated_suggestion": suggestion,
                    "human_decision": None,
                    "fixture_decision": None,
                    "suggestion_method": "filename_and_qc_rules_v1",
                },
                "target_geometry": None,
                "curation_status": "needs_review",
                "exclusion_codes": sorted(set(exclusion_codes)),
                "review": {
                    "method": "none",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "decision": None,
                    "notes": None,
                },
                "award_context": {
                    "award": draft["award"],
                    "year": source["year"] if source else _year_from_path(draft["path"]),
                    "edition": source["edition"] if source else None,
                    "category": source["category"] if source else None,
                    "award_status": source["award_status"] if source else None,
                },
                "font_metadata": None,
            }
        )

    source_records = {record["source_id"]: record for record in audit["canonical_sources"]}
    font_root = root / config["inventory"]["font_root"]
    font_candidates: list[dict[str, Any]] = []
    for path in sorted(item for item in font_root.rglob("*") if item.suffix.lower() in {".otf", ".ttf", ".ttc"}):
        relative_path = path.relative_to(root).as_posix()
        inspection = inspect_font(path)
        if inspection["parse_error"] or inspection["font_metadata"] is None:
            raise ValueError(f"font parse failed: {relative_path}: {inspection['parse_error']}")
        source_id = stable_id("source_font", {"sha256": inspection["sha256"]})
        source_records[source_id] = _font_source_record(relative_path, inspection, source_id, config["inventory"]["snapshot_date"])
        font_candidates.append(
            {
                "schema_version": "1.0.0",
                "asset_id": stable_id("asset", {"source_id": source_id, "sha256": inspection["sha256"]}),
                "record_origin": "repository_asset",
                "source_id": source_id,
                "parent_asset_id": None,
                "work_id": None,
                "asset_role": "original",
                "candidate_kind": "font_file",
                "asset_ref": {
                    "path": relative_path,
                    "sha256": inspection["sha256"],
                    "mime_type": inspection["mime_type"],
                    "byte_size": inspection["byte_size"],
                },
                "pixel_metadata": None,
                "rights_tier": "blocked_unknown",
                "transform": None,
                "automated_qc": {
                    "status": "passed",
                    "decodable": None,
                    "pixel_limit_status": "not_applicable",
                    "hash_duplicate_status": "unique",
                    "perceptual_duplicate_status": "not_applicable",
                    "boundary_status": "not_applicable",
                    "format_status": "passed",
                    "failure_codes": [],
                },
                "classification": {
                    "automated_suggestion": None,
                    "human_decision": None,
                    "fixture_decision": None,
                    "suggestion_method": "not_applicable",
                },
                "target_geometry": None,
                "curation_status": "needs_review",
                "exclusion_codes": ["RIGHTS_BLOCKED"],
                "review": {
                    "method": "none",
                    "reviewer_id": None,
                    "reviewed_at": None,
                    "decision": None,
                    "notes": None,
                },
                "award_context": None,
                "font_metadata": inspection["font_metadata"],
            }
        )
    candidates.extend(font_candidates)
    return {
        "candidates": candidates,
        "sources": [source_records[key] for key in sorted(source_records)],
        "source_audit": audit,
        "summary": _inventory_summary(candidates, audit),
    }


def build_open_fixture(repo_root: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    from .qc import inspect_image

    root = Path(repo_root).resolve()
    fixture_config = config["open_fixture"]
    relative_path = normalize_repo_path(fixture_config["path"])
    path = root / relative_path
    bbox = [float(value) for value in fixture_config["target_bbox"]]
    inspection = inspect_image(
        path,
        max_pixels=int(config["qc"]["max_pixels"]),
        target_bbox=bbox,
        assume_srgb_without_profile=bool(config["qc"]["assume_srgb_without_profile"]),
    )
    if inspection["automated_qc"]["status"] != "passed":
        raise ValueError("open fixture failed QC")
    source_id = stable_id("source_fixture", {"sha256": inspection["sha256"], "license": fixture_config["license_id"]})
    work_id = stable_id("work_fixture", {"source_id": source_id, "shape": "nested_rectangles"})
    asset_id = stable_id("asset", {"source_id": source_id, "sha256": inspection["sha256"]})
    source = {
        "source_id": source_id,
        "source_type": "generated_asset",
        "title": "GLYPH synthetic grayscale asset-system fixture",
        "publisher_or_creator": "GLYPH contributors",
        "url": "urn:glyph:fixture:asset-system-v1",
        "published_at": None,
        "accessed_at": config["inventory"]["snapshot_date"],
        "language_bcp47": None,
        "region": None,
        "license_status": "open",
        "license_text_or_id": fixture_config["license_id"],
        "redistribution_allowed": True,
        "local_archive": {
            "path": relative_path,
            "sha256": inspection["sha256"],
            "mime_type": inspection["mime_type"],
            "byte_size": inspection["byte_size"],
        },
        "notes": "Project-generated non-logo shape; fixture protocol only.",
    }
    candidate = {
        "schema_version": "1.0.0",
        "asset_id": asset_id,
        "record_origin": "generated_fixture",
        "source_id": source_id,
        "parent_asset_id": None,
        "work_id": work_id,
        "asset_role": "original",
        "candidate_kind": "isolated_wordmark",
        "asset_ref": copy_asset_ref(source["local_archive"]),
        "pixel_metadata": inspection["pixel_metadata"],
        "rights_tier": "open",
        "transform": None,
        "automated_qc": inspection["automated_qc"],
        "classification": {
            "automated_suggestion": "isolated_wordmark_clean",
            "human_decision": None,
            "fixture_decision": "isolated_wordmark_clean",
            "suggestion_method": "fixture_protocol_v1",
        },
        "target_geometry": {
            "geometry_type": "bbox",
            "coordinates": bbox,
            "confirmed_by": "fixture_protocol_v1",
            "confirmed_at": fixture_config["reviewed_at"],
        },
        "curation_status": "passed",
        "exclusion_codes": [],
        "review": {
            "method": "fixture_protocol",
            "reviewer_id": "fixture_protocol_v1",
            "reviewed_at": fixture_config["reviewed_at"],
            "decision": "passed",
            "notes": "Protocol assertion for a synthetic fixture; not human review.",
        },
        "award_context": None,
        "font_metadata": None,
    }
    return {"source": source, "candidate": candidate}


def copy_asset_ref(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("path", "sha256", "mime_type", "byte_size")}


def _classification_suggestion(draft: dict[str, Any], annotation: dict[str, Any]) -> str:
    if annotation["hash_duplicate_status"] == "duplicate_exact":
        return "duplicate_exact"
    name = draft["path"].name.casefold()
    if "call-for-entries" in name or "preloader" in name:
        return "call_for_entries_or_non_winner" if "call-for-entries" in name else "award_header_or_navigation_asset"
    if draft["award"] == "WOLDA":
        return "project_board_or_poster"
    return "uncertain"


def _year_from_path(path: Path) -> int | None:
    for part in reversed(path.parts):
        if re.fullmatch(r"20\d{2}", part):
            return int(part)
    return None


def _font_source_record(relative_path: str, inspection: dict[str, Any], source_id: str, snapshot_date: str) -> dict[str, Any]:
    metadata = inspection["font_metadata"]
    notes = {
        "internal_license_text": metadata["license_hint"]["internal_text"],
        "internal_license_url": metadata["license_hint"]["internal_url"],
        "sidecar_files": metadata["license_hint"]["sidecar_files"],
        "retrieval_url": None,
        "rights_evidence": "internal name table is insufficient; GATE-RIGHTS",
    }
    return {
        "source_id": source_id,
        "source_type": "font_file",
        "title": f"Local font candidate: {metadata['family_name']} {metadata['subfamily_name'] or ''}".strip(),
        "publisher_or_creator": None,
        "url": f"urn:sha256:{inspection['sha256']}",
        "published_at": None,
        "accessed_at": snapshot_date,
        "language_bcp47": None,
        "region": metadata["regional_glyphs"],
        "license_status": "unknown",
        "license_text_or_id": None,
        "redistribution_allowed": None,
        "local_archive": {
            "path": relative_path,
            "sha256": inspection["sha256"],
            "mime_type": inspection["mime_type"],
            "byte_size": inspection["byte_size"],
        },
        "notes": json.dumps(notes, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }


def _inventory_summary(candidates: list[dict[str, Any]], audit: dict[str, Any]) -> dict[str, Any]:
    images = [record for record in candidates if record["candidate_kind"] == "ecological_award_image"]
    fonts = [record for record in candidates if record["candidate_kind"] == "font_file"]
    awards: dict[str, Any] = {}
    award_years: dict[str, Any] = {}
    for award in ("DFA", "Indigo", "WOLDA", "Golden Pin", "GDC"):
        rows = [record for record in images if record["award_context"]["award"] == award]
        awards[award] = {
            "file_count": len(rows),
            "unique_binary_count": len({record["asset_ref"]["sha256"] for record in rows}),
            "unique_work_count": len({record["work_id"] for record in rows if record["work_id"]}),
            "curation_passed_count": sum(record["curation_status"] == "passed" for record in rows),
            "rights_tiers": dict(sorted(Counter(record["rights_tier"] for record in rows).items())),
            "content_suggestions": dict(sorted(Counter(record["classification"]["automated_suggestion"] for record in rows).items())),
        }
        award_years[award] = {}
        years = sorted({record["award_context"]["year"] for record in rows}, key=lambda value: (value is None, value or 0))
        for year in years:
            year_rows = [record for record in rows if record["award_context"]["year"] == year]
            award_years[award][str(year) if year is not None else "unknown"] = {
                "file_count": len(year_rows),
                "unique_binary_count": len({record["asset_ref"]["sha256"] for record in year_rows}),
                "unique_work_count": len({record["work_id"] for record in year_rows if record["work_id"]}),
                "curation_passed_count": sum(record["curation_status"] == "passed" for record in year_rows),
            }
    font_families: list[dict[str, Any]] = []
    for family_id in sorted({record["font_metadata"]["family_id"] for record in fonts}):
        family_records = [record for record in fonts if record["font_metadata"]["family_id"] == family_id]
        font_families.append(
            {
                "family_id": family_id,
                "family_name": family_records[0]["font_metadata"]["family_name"],
                "file_count": len(family_records),
                "font_ids": sorted(record["font_metadata"]["font_id"] for record in family_records),
                "subfamily_names": sorted(
                    {record["font_metadata"]["subfamily_name"] for record in family_records if record["font_metadata"]["subfamily_name"]}
                ),
                "regional_glyphs": sorted(
                    {record["font_metadata"]["regional_glyphs"] for record in family_records if record["font_metadata"]["regional_glyphs"]}
                ),
                "rights_tiers": dict(sorted(Counter(record["rights_tier"] for record in family_records).items())),
            }
        )
    return {
        "candidate_count": len(candidates),
        "image_file_count": len(images),
        "image_unique_sha256_count": len({record["asset_ref"]["sha256"] for record in images}),
        "font_file_count": len(fonts),
        "font_family_count": len({record["font_metadata"]["family_id"] for record in fonts}),
        "unique_work_count": len({record["work_id"] for record in images if record["work_id"]}),
        "curation_passed_count": sum(record["curation_status"] == "passed" for record in candidates),
        "rights_tiers": dict(sorted(Counter(record["rights_tier"] for record in candidates).items())),
        "qc_statuses": dict(sorted(Counter(record["automated_qc"]["status"] for record in candidates).items())),
        "content_suggestions": dict(
            sorted(Counter(record["classification"]["automated_suggestion"] or "unclassified" for record in images).items())
        ),
        "oversize_image_count": sum("QC_PIXEL_LIMIT_EXCEEDED" in record["automated_qc"]["failure_codes"] for record in images),
        "exact_duplicate_file_count": sum(record["automated_qc"]["hash_duplicate_status"] == "duplicate_exact" for record in images),
        "near_duplicate_file_count": sum(record["automated_qc"]["perceptual_duplicate_status"] == "duplicate_near" for record in images),
        "source_issue_count": len(audit["issues"]),
        "awards": awards,
        "award_years": award_years,
        "font_families": sorted(font_families, key=lambda item: (item["family_name"].casefold(), item["family_id"])),
    }


def _resolve_source_file(
    recorded_file: str,
    by_name: dict[str, list[Path]],
    by_relative: dict[str, Path],
    *,
    award_dir: Path,
    year: int | None,
) -> tuple[Path | None, str | None]:
    normalized = recorded_file.replace("\\", "/")
    if normalized in by_relative:
        return by_relative[normalized], None

    basename = PurePosixPath(normalized).name
    exact_candidates = by_name.get(basename, [])
    selected, ambiguous = _select_source_candidate(exact_candidates, award_dir=award_dir, year=year)
    if selected is not None:
        return selected, None
    if ambiguous:
        return None, "SOURCE_FILE_AMBIGUOUS"

    extension_candidates = [
        path
        for name, paths in by_name.items()
        if name.startswith(basename + ".")
        for path in paths
    ]
    selected, ambiguous = _select_source_candidate(extension_candidates, award_dir=award_dir, year=year)
    if selected is not None:
        return selected, "SOURCE_FILENAME_EXTENSION_REPAIRED"
    if ambiguous:
        return None, "SOURCE_FILE_AMBIGUOUS"
    return None, None


def _select_source_candidate(
    candidates: list[Path],
    *,
    award_dir: Path,
    year: int | None,
) -> tuple[Path | None, bool]:
    if len(candidates) == 1:
        return candidates[0], False
    if year is not None:
        year_candidates = [
            path for path in candidates if str(year) in path.relative_to(award_dir).parts[:-1]
        ]
        if len(year_candidates) == 1:
            return year_candidates[0], False
    return None, len(candidates) > 1


def _work_id(award: str, legacy: dict[str, str], asset_url: str, page_url: str) -> str:
    official = (legacy.get("work_id") or "").strip()
    if not official and award == "GDC":
        official = (parse_qs(urlparse(page_url).query).get("id") or [""])[0]
    if not official and award == "Indigo":
        match = re.search(r"/cover/(\d+)/", asset_url)
        official = match.group(1) if match else ""
    if official:
        return stable_id("work", {"award": award, "official_id": official})
    title = (legacy.get("project") or legacy.get("title") or "").strip().casefold()
    creator = (legacy.get("company") or legacy.get("creator") or "").strip().casefold()
    identity = {"award": award, "title": title, "creator": creator} if title else {"award": award, "asset_url": asset_url}
    return stable_id("work", identity)


def _edition(award: str, year: int | None, legacy: dict[str, str]) -> str | None:
    if award == "GDC":
        value = (legacy.get("bo") or "").strip()
        return f"bo{value}" if value else ({2021: "bo7", 2023: "bo8", 2025: "bo9"}.get(year))
    if award == "WOLDA":
        return {2020: "12th", 2021: "13th", 2022: "14th", 2023: "15th", 2024: "16th"}.get(year)
    return None


def _integer_or_none(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _source_schema_record(root: Path, row: dict[str, Any], snapshot_date: str) -> dict[str, Any]:
    local_archive = None
    if row["local_path"]:
        local_path = root / row["local_path"]
        local_archive = {
            "path": row["local_path"],
            "sha256": sha256_file(local_path),
            "mime_type": _mime_type(local_path),
            "byte_size": local_path.stat().st_size,
        }
    accessed_at = row["fetched_at"][:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", row["fetched_at"]) else snapshot_date
    notes = {
        "award": row["award"],
        "asset_url": row["asset_url"],
        "edition": row["edition"],
        "work_id": row["work_id"],
        "legacy_source_path": row["legacy_source_path"],
        "legacy_source_sha256": row["legacy_source_sha256"],
        "legacy_row_number": row["legacy_row_number"],
        "repair_codes": row["repair_codes"],
        "rights_evidence": "not_verified; GATE-RIGHTS",
        "page_snapshot_sha256": None,
    }
    return {
        "source_id": row["source_id"],
        "source_type": "award_page",
        "title": row["title"],
        "publisher_or_creator": row["creator"] or row["award"],
        "url": row["source_page_url"] or row["asset_url"],
        "published_at": None,
        "accessed_at": accessed_at,
        "language_bcp47": None,
        "region": None,
        "license_status": "unknown",
        "license_text_or_id": None,
        "redistribution_allowed": None,
        "local_archive": local_archive,
        "notes": json.dumps(notes, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


def _issue(award: str, source_path: str, row_number: int | None, code: str, detail: str) -> dict[str, Any]:
    return {
        "award": award,
        "source_path": source_path,
        "row_number": row_number,
        "code": code,
        "detail": detail,
    }

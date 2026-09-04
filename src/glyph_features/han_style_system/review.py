"""Build blinded review packages and import immutable expert decisions."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from glyph_features.asset_system.catalog import (
    canonical_json,
    normalize_repo_path,
    resolve_workspace_asset,
    sha256_file,
    stable_id,
    validate_record,
)


RUBRIC_DIMENSIONS = (
    "character_identity",
    "style_or_font_attribution",
    "structure",
    "stroke_logic",
    "historical_fidelity",
    "source_fidelity",
    "experimental_suitability",
    "inference_scope",
)
REVIEW_TEMPLATE_FIELDS = [
    "package_id",
    "package_content_sha256",
    "review_item_id",
    "subject_id",
    "reviewer_id",
    "reviewer_role",
    "review_origin",
    "round",
    "review_round_type",
    "independence_attestation",
    "prior_review_visibility",
    *RUBRIC_DIMENSIONS,
    "overall_decision",
    "reason_codes",
    "notes",
    "reviewed_at",
    "conflict_review_ids",
    "supersedes_review_id",
]


class ReviewError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def build_review_package(
    glyph_records: list[dict[str, Any]],
    mapping_records: list[dict[str, Any]],
    asset_records: list[dict[str, Any]],
    *,
    workspace_root: str | Path,
    output_dir: str | Path,
    created_at: str,
    ordering_seed: str,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    destination = Path(output_dir).resolve()
    _require_new_directory(destination)
    mappings_by_id = {record["mapping_id"]: record for record in mapping_records}
    assets_by_id = {record["asset_id"]: record for record in asset_records}
    ordered_glyphs = sorted(
        glyph_records,
        key=lambda record: hashlib.sha256(
            f"{ordering_seed}:{record['glyph_instance_id']}".encode("utf-8")
        ).hexdigest(),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        items: list[dict[str, Any]] = []
        for display_order, glyph in enumerate(ordered_glyphs, start=1):
            if glyph["rights_tier"] != "open" or glyph["release_tier"] != "fixture_only":
                raise ReviewError("REVIEW_ASSET_NOT_AUTHORIZED", glyph["glyph_instance_id"])
            mapping = mappings_by_id[glyph["mapping_id"]]
            source_asset = assets_by_id[glyph["representation_asset_ids"]["original"]]
            candidate_asset = assets_by_id[glyph["representation_asset_ids"]["B_shape"]]
            copied_source = _copy_asset(root, staging, source_asset)
            copied_candidate = _copy_asset(root, staging, candidate_asset)
            subject_id = glyph["glyph_instance_id"]
            items.append(
                {
                    "schema_version": "1.0.0",
                    "review_item_id": stable_id("review_item", {"seed": ordering_seed, "subject_id": subject_id}),
                    "subject_type": "glyph_instance",
                    "subject_id": subject_id,
                    "blinded_subject_code": stable_id("blind", {"seed": ordering_seed, "subject_id": subject_id}, length=12),
                    "display_order": display_order,
                    "character_display": mapping["display_text"],
                    "fixture_disclaimer": glyph["notes"] if glyph["data_origin"] == "generated_fixture" else None,
                    "source_asset": copied_source,
                    "candidate_asset": copied_candidate,
                    "difference_overlay_available": True,
                    "disclosed_metadata": ["character_display", "source_locator", "fixture_disclaimer"],
                    "withheld_metadata": ["style_id", "prior_reviews", "reviewer_identity"],
                    "rights_tier": glyph["rights_tier"],
                    "access_status": "open_fixture",
                }
            )
        for item in items:
            errors = validate_record(item, root / "schema/han_review_item.schema.json")
            if errors:
                raise ReviewError("REVIEW_ITEM_SCHEMA_INVALID", "; ".join(errors))
        _write_jsonl(staging / "items.jsonl", items)
        item_manifest = _asset_ref(staging / "items.jsonl", "items.jsonl", "application/x-ndjson")
        package_content_sha256 = hashlib.sha256(
            canonical_json({"items": items, "rubric_dimensions": list(RUBRIC_DIMENSIONS)})
        ).hexdigest()
        package_id = stable_id(
            "review_package",
            {"package_content_sha256": package_content_sha256, "review_round": 1},
        )
        manifest = {
            "schema_version": "1.0.0",
            "package_id": package_id,
            "package_version": "1.0.0",
            "created_at": created_at,
            "review_round": 1,
            "subject_type": "glyph_instance",
            "item_manifest": item_manifest,
            "package_content_sha256": package_content_sha256,
            "item_count": len(items),
            "rubric_dimensions": list(RUBRIC_DIMENSIONS),
            "blinding": {
                "prior_reviews_hidden": True,
                "style_labels_withheld": True,
                "reviewer_answers_separate": True,
            },
            "asset_access_level": "open_fixture",
            "gate_status": "blocked",
            "gate_approval_id": None,
        }
        errors = validate_record(manifest, root / "schema/han_review_package.schema.json")
        if errors:
            raise ReviewError("REVIEW_PACKAGE_SCHEMA_INVALID", "; ".join(errors))
        _write_json(staging / "package_manifest.json", manifest)
        _write_review_template(staging / "review_template.csv", manifest, items)
        (staging / "index.html").write_text(_review_html(items), encoding="utf-8", newline="\n")
        checksum_paths = sorted(path for path in staging.rglob("*") if path.is_file())
        (staging / "checksums.sha256").write_text(
            "".join(f"{sha256_file(path)}  {path.relative_to(staging).as_posix()}\n" for path in checksum_paths),
            encoding="utf-8",
            newline="\n",
        )
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def import_review_rows(
    package_dir: str | Path,
    rows: list[dict[str, str]],
    *,
    schema_path: str | Path,
    gate_approval: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    package = Path(package_dir).resolve()
    manifest = json.loads((package / "package_manifest.json").read_text(encoding="utf-8"))
    item_manifest_path = _verify_package_asset(package, manifest["item_manifest"], "item manifest")
    _verify_package_checksums(package)
    items = _read_jsonl(item_manifest_path)
    expected_content_hash = hashlib.sha256(
        canonical_json({"items": items, "rubric_dimensions": manifest["rubric_dimensions"]})
    ).hexdigest()
    if expected_content_hash != manifest["package_content_sha256"]:
        raise ReviewError("REVIEW_PACKAGE_TAMPERED", "package content hash mismatch")
    if manifest.get("item_count") != len(items):
        raise ReviewError("REVIEW_PACKAGE_TAMPERED", "item count mismatch")
    for item in items:
        _verify_package_asset(package, item["source_asset"], f"source asset for {item.get('review_item_id')}")
        _verify_package_asset(package, item["candidate_asset"], f"candidate asset for {item.get('review_item_id')}")
    items_by_id = {item["review_item_id"]: item for item in items}
    reviews: list[dict[str, Any]] = []
    seen_independent: set[tuple[str, str, int]] = set()
    for row_number, row in enumerate(rows, start=2):
        if row.get("package_id") != manifest["package_id"] or row.get("package_content_sha256") != expected_content_hash:
            raise ReviewError("REVIEW_PACKAGE_SIGNATURE_MISMATCH", f"row {row_number}")
        item = items_by_id.get(row.get("review_item_id", ""))
        if item is None or row.get("subject_id") != item["subject_id"]:
            raise ReviewError("REVIEW_ITEM_UNKNOWN", f"row {row_number}")
        review_origin = row.get("review_origin", "").strip()
        reviewer_id = row.get("reviewer_id", "").strip()
        if review_origin == "real_expert":
            approval_id = _validate_gate_approval(gate_approval, manifest["package_id"])
        elif review_origin == "synthetic_fixture":
            if not reviewer_id.startswith("reviewer_fixture_"):
                raise ReviewError("SYNTHETIC_REVIEWER_ID_REQUIRED", f"row {row_number}")
            approval_id = None
        else:
            raise ReviewError("REVIEW_ORIGIN_INVALID", f"row {row_number}")
        round_number = _positive_integer(row.get("round"), "round", row_number)
        review_round_type = row.get("review_round_type", "").strip()
        key = (item["subject_id"], reviewer_id, round_number)
        if review_round_type == "independent" and key in seen_independent:
            raise ReviewError("REVIEW_NOT_INDEPENDENT", f"row {row_number}")
        seen_independent.add(key)
        dimensions = {dimension: row.get(dimension, "").strip() for dimension in RUBRIC_DIMENSIONS}
        payload: dict[str, Any] = {
            "schema_version": "1.0.0",
            "review_id": stable_id(
                "review",
                {
                    "package_id": manifest["package_id"],
                    "subject_id": item["subject_id"],
                    "reviewer_id": reviewer_id,
                    "round": round_number,
                    "review_round_type": review_round_type,
                },
            ),
            "package_id": manifest["package_id"],
            "package_version": manifest["package_version"],
            "source_package_sha256": expected_content_hash,
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "reviewer_id": reviewer_id,
            "reviewer_role": row.get("reviewer_role", "").strip(),
            "review_origin": review_origin,
            "gate_approval_id": approval_id,
            "round": round_number,
            "review_round_type": review_round_type,
            "independence_attestation": _boolean(row.get("independence_attestation"), row_number),
            "prior_review_visibility": row.get("prior_review_visibility", "").strip(),
            "dimensions": dimensions,
            "overall_decision": row.get("overall_decision", "").strip(),
            "reason_codes": _pipe_values(row.get("reason_codes")),
            "notes": row.get("notes") or None,
            "reviewed_at": row.get("reviewed_at", "").strip(),
            "conflict_review_ids": _pipe_values(row.get("conflict_review_ids")),
            "supersedes_review_id": row.get("supersedes_review_id") or None,
        }
        payload["signature_sha256"] = hashlib.sha256(canonical_json(payload)).hexdigest()
        errors = validate_record(payload, schema_path)
        if errors:
            raise ReviewError("REVIEW_SCHEMA_INVALID", f"row {row_number}: {'; '.join(errors)}")
        reviews.append(payload)
    review_ids = [review["review_id"] for review in reviews]
    if len(review_ids) != len(set(review_ids)):
        raise ReviewError("REVIEW_ID_DUPLICATE", "duplicate review identity")
    link_errors = _review_link_errors(reviews)
    if link_errors:
        raise ReviewError("REVIEW_REFERENCE_INVALID", "; ".join(link_errors))
    return reviews


def aggregate_reviews(
    reviews: list[dict[str, Any]],
    *,
    minimum_independent_reviews: int,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        grouped.setdefault(review["subject_id"], []).append(review)
    summaries: dict[str, dict[str, Any]] = {}
    for subject_id, subject_reviews in grouped.items():
        independent = [review for review in subject_reviews if review["review_round_type"] == "independent"]
        real = [review for review in independent if review["review_origin"] == "real_expert"]
        synthetic = [review for review in independent if review["review_origin"] == "synthetic_fixture"]
        decisions = Counter(review["overall_decision"] for review in independent)
        summaries[subject_id] = {
            "package_ids": sorted({review["package_id"] for review in subject_reviews}),
            "synthetic_review_count": len({review["reviewer_id"] for review in synthetic}),
            "real_review_count": len({review["reviewer_id"] for review in real}),
            "fixture_status": _decision_status(synthetic, minimum_independent_reviews),
            "formal_status": _decision_status(real, minimum_independent_reviews),
            "decision_counts": dict(sorted(decisions.items())),
        }
    return summaries


def validate_review_records(
    reviews: list[dict[str, Any]],
    schema_path: str | Path,
) -> list[str]:
    errors: list[str] = []
    review_ids: set[str] = set()
    independent_keys: set[tuple[str, str, int]] = set()
    for index, review in enumerate(reviews, start=1):
        errors.extend(
            f"HAN_REVIEW_SCHEMA_INVALID record={index}: {message}"
            for message in validate_record(review, schema_path)
        )
        review_id = review.get("review_id")
        if review_id in review_ids:
            errors.append(f"HAN_REVIEW_ID_DUPLICATE review_id={review_id}")
        if isinstance(review_id, str):
            review_ids.add(review_id)
        signature = review.get("signature_sha256")
        unsigned = {key: value for key, value in review.items() if key != "signature_sha256"}
        expected_signature = hashlib.sha256(canonical_json(unsigned)).hexdigest()
        if signature != expected_signature:
            errors.append(f"HAN_REVIEW_SIGNATURE_MISMATCH review_id={review_id}")
        if review.get("review_round_type") == "independent":
            round_value = review.get("round")
            round_number = round_value if isinstance(round_value, int) else 0
            key = (str(review.get("subject_id")), str(review.get("reviewer_id")), round_number)
            if key in independent_keys:
                errors.append(f"HAN_REVIEW_NOT_INDEPENDENT review_id={review_id}")
            independent_keys.add(key)
    errors.extend(_review_link_errors(reviews))
    return sorted(set(errors))


def write_reviews(path: str | Path, reviews: list[dict[str, Any]]) -> None:
    _write_jsonl(Path(path), reviews)


def _decision_status(reviews: list[dict[str, Any]], minimum: int) -> str:
    decisions = {review["overall_decision"] for review in reviews}
    substantive = decisions - {"outside_expertise", "not_applicable"}
    if "pass" in substantive and substantive & {"fail", "needs_revision"}:
        return "conflicted"
    if "fail" in substantive:
        return "failed"
    if "needs_revision" in substantive:
        return "needs_revision"
    distinct_reviewers = {review["reviewer_id"] for review in reviews if review["overall_decision"] == "pass"}
    return "passed" if len(distinct_reviewers) >= minimum else "blocked"


def _validate_gate_approval(approval: dict[str, Any] | None, package_id: str) -> str:
    if not isinstance(approval, dict):
        raise ReviewError("GATE_EXPERT_APPROVAL_REQUIRED", package_id)
    required = {"gate_id", "status", "approval_id", "package_id", "approved_by", "approved_at"}
    if not required <= approval.keys():
        raise ReviewError("GATE_EXPERT_APPROVAL_INVALID", package_id)
    if approval["gate_id"] != "GATE-EXPERT" or approval["status"] != "approved":
        raise ReviewError("GATE_EXPERT_APPROVAL_INVALID", package_id)
    if approval["package_id"] != package_id:
        raise ReviewError("GATE_EXPERT_PACKAGE_MISMATCH", package_id)
    return str(approval["approval_id"])


def _copy_asset(root: Path, staging: Path, asset: dict[str, Any]) -> dict[str, Any]:
    source = resolve_workspace_asset(root, asset["asset_ref"])
    mime_type = asset["asset_ref"].get("mime_type", "application/octet-stream")
    browser_mime_types = {"image/gif", "image/jpeg", "image/png", "image/webp"}
    convert_to_png = mime_type not in browser_mime_types
    extension = ".png" if convert_to_png else source.suffix.lower() or ".bin"
    relative = Path("assets") / f"{asset['asset_id']}{extension}"
    destination = staging / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        if convert_to_png:
            with Image.open(source) as image:
                image.save(destination, format="PNG")
        else:
            shutil.copyfile(source, destination)
    return _asset_ref(destination, relative.as_posix(), "image/png" if convert_to_png else mime_type)


def _verify_package_asset(package: Path, asset_ref: dict[str, Any], label: str) -> Path:
    raw_path = str(asset_ref.get("path", ""))
    try:
        relative = normalize_repo_path(raw_path)
    except ValueError as error:
        raise ReviewError("REVIEW_PACKAGE_PATH_INVALID", f"{label}: {raw_path}") from error
    if relative != raw_path:
        raise ReviewError("REVIEW_PACKAGE_PATH_INVALID", f"{label}: {raw_path}")
    path = (package / relative).resolve()
    if not path.is_relative_to(package):
        raise ReviewError("REVIEW_PACKAGE_PATH_INVALID", f"{label}: {raw_path}")
    if not path.is_file():
        raise ReviewError("REVIEW_PACKAGE_ASSET_MISSING", f"{label}: {raw_path}")
    if sha256_file(path) != asset_ref.get("sha256"):
        raise ReviewError("REVIEW_PACKAGE_TAMPERED", f"{label} hash mismatch")
    if path.stat().st_size != asset_ref.get("byte_size"):
        raise ReviewError("REVIEW_PACKAGE_TAMPERED", f"{label} byte size mismatch")
    return path


def _verify_package_checksums(package: Path) -> None:
    checksum_path = package / "checksums.sha256"
    if not checksum_path.is_file():
        raise ReviewError("REVIEW_PACKAGE_CHECKSUMS_MISSING", str(checksum_path.name))
    declared: dict[str, str] = {}
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if match is None:
            raise ReviewError("REVIEW_PACKAGE_CHECKSUMS_INVALID", f"line {line_number}")
        raw_path = match.group(2)
        try:
            relative = normalize_repo_path(raw_path)
        except ValueError as error:
            raise ReviewError("REVIEW_PACKAGE_PATH_INVALID", f"checksums line {line_number}: {raw_path}") from error
        if relative != raw_path or relative in declared:
            raise ReviewError("REVIEW_PACKAGE_CHECKSUMS_INVALID", f"line {line_number}")
        declared[relative] = match.group(1)
    actual_paths = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path != checksum_path
    }
    if set(declared) != actual_paths:
        raise ReviewError("REVIEW_PACKAGE_CHECKSUMS_INVALID", "file set mismatch")
    for relative, expected_hash in declared.items():
        path = (package / relative).resolve()
        if not path.is_relative_to(package):
            raise ReviewError("REVIEW_PACKAGE_PATH_INVALID", f"checksums: {relative}")
        if sha256_file(path) != expected_hash:
            raise ReviewError("REVIEW_PACKAGE_TAMPERED", f"checksum mismatch: {relative}")


def _review_link_errors(reviews: list[dict[str, Any]]) -> list[str]:
    by_id = {
        review["review_id"]: review
        for review in reviews
        if isinstance(review.get("review_id"), str)
    }
    errors: list[str] = []
    for review in reviews:
        review_id = review.get("review_id")
        if review.get("review_round_type") == "adjudication":
            linked = [by_id.get(value) for value in review.get("conflict_review_ids", [])]
            if any(value is None for value in linked):
                errors.append(f"HAN_REVIEW_CONFLICT_REFERENCE_UNKNOWN review_id={review_id}")
            elif any(
                value.get("review_round_type") != "independent"
                or value.get("package_id") != review.get("package_id")
                or value.get("subject_id") != review.get("subject_id")
                for value in linked
                if value is not None
            ):
                errors.append(f"HAN_REVIEW_CONFLICT_REFERENCE_INVALID review_id={review_id}")
            elif len({value.get("overall_decision") for value in linked if value is not None}) < 2:
                errors.append(f"HAN_REVIEW_CONFLICT_NOT_PRESENT review_id={review_id}")
        superseded_id = review.get("supersedes_review_id")
        if superseded_id is not None:
            superseded = by_id.get(superseded_id)
            if superseded is None:
                errors.append(f"HAN_REVIEW_SUPERSEDES_UNKNOWN review_id={review_id}")
            elif (
                superseded.get("package_id") != review.get("package_id")
                or superseded.get("subject_id") != review.get("subject_id")
            ):
                errors.append(f"HAN_REVIEW_SUPERSEDES_INVALID review_id={review_id}")
    return errors


def _asset_ref(path: Path, logical_path: str, mime_type: str) -> dict[str, Any]:
    return {
        "path": logical_path,
        "sha256": sha256_file(path),
        "mime_type": mime_type,
        "byte_size": path.stat().st_size,
    }


def _write_review_template(path: Path, manifest: dict[str, Any], items: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_TEMPLATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "package_id": manifest["package_id"],
                    "package_content_sha256": manifest["package_content_sha256"],
                    "review_item_id": item["review_item_id"],
                    "subject_id": item["subject_id"],
                    "round": manifest["review_round"],
                    "review_round_type": "independent",
                    "independence_attestation": "true",
                    "prior_review_visibility": "hidden",
                }
            )


def _review_html(items: list[dict[str, Any]]) -> str:
    sections = []
    for item in items:
        source = html.escape(item["source_asset"]["path"])
        candidate = html.escape(item["candidate_asset"]["path"])
        disclaimer = html.escape(item.get("fixture_disclaimer") or "")
        sections.append(
            f'<section class="review-item"><h2>{html.escape(item["blinded_subject_code"])}</h2>'
            f'<p>{disclaimer}</p><label>Zoom <input class="zoom" type="range" min="50" max="250" value="100"></label>'
            f'<label>Overlay <input class="opacity" type="range" min="0" max="100" value="50"></label>'
            f'<div class="pair"><img src="{source}" alt="Source fixture"><img src="{candidate}" alt="Candidate shape"></div>'
            f'<div class="overlay"><img src="{source}" alt=""><img class="top" src="{candidate}" alt=""></div></section>'
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GLYPH Han review package</title><style>
body{margin:0;background:#f3f1eb;color:#171713;font:16px Georgia,serif}main{max-width:1100px;margin:auto;padding:24px}.review-item{border-top:2px solid #171713;padding:20px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;overflow:auto}.pair img,.overlay img{width:100%;image-rendering:auto}.overlay{position:relative;max-width:520px;margin-top:16px}.overlay .top{position:absolute;inset:0;opacity:.5}label{display:inline-flex;gap:8px;margin:0 20px 12px 0}@media(max-width:700px){.pair{grid-template-columns:1fr}}
</style></head><body><main>""" + "".join(sections) + """</main><script>
document.querySelectorAll('.review-item').forEach(section=>{const pair=section.querySelector('.pair');const top=section.querySelector('.top');section.querySelector('.zoom').addEventListener('input',event=>{pair.querySelectorAll('img').forEach(image=>image.style.width=event.target.value+'%')});section.querySelector('.opacity').addEventListener('input',event=>{top.style.opacity=String(Number(event.target.value)/100)})});
</script></body></html>"""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _require_new_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise FileExistsError(f"output directory is not empty: {path}")


def _positive_integer(value: str | None, field: str, row_number: int) -> int:
    try:
        parsed = int(value or "")
    except ValueError as error:
        raise ReviewError("REVIEW_INTEGER_INVALID", f"row {row_number}: {field}") from error
    if parsed < 1:
        raise ReviewError("REVIEW_INTEGER_INVALID", f"row {row_number}: {field}")
    return parsed


def _boolean(value: str | None, row_number: int) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized not in {"true", "false"}:
        raise ReviewError("REVIEW_BOOLEAN_INVALID", f"row {row_number}")
    return normalized == "true"


def _pipe_values(value: str | None) -> list[str]:
    return sorted({item.strip() for item in (value or "").split("|") if item.strip()})

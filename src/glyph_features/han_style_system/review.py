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
from glyph_features.han_style_system.trust import (
    accepted_review_batch,
    fixture_reviewer_authorized,
    load_trust_root,
    trusted_expert_approval,
    fixture_local_access_authorized,
)
from glyph_features.han_style_system.rights import load_trusted_rights_snapshot


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
DEFAULT_ROLE_GROUPS = (
    frozenset({"history_or_paleography"}),
    frozenset({"calligraphy_or_seal_practice", "type_or_visual_design"}),
)
DEFAULT_MINIMUM_SUBSTANTIVE_DIMENSIONS = 2
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
    access_level: str = "open_fixture",
    access_authorization_id: str | None = None,
    task01_handoff_path: str | Path | None = None,
    rights_evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    destination = Path(output_dir).resolve()
    if access_level not in {"open_fixture", "research_local_only"}:
        raise ReviewError("REVIEW_ACCESS_LEVEL_INVALID", access_level)
    if access_level == "research_local_only" and (
        destination.is_relative_to(root / "data/releases")
        or destination.is_relative_to(root / "data/fixtures")
    ):
        raise ReviewError("REVIEW_LOCAL_PACKAGE_PUBLIC_PATH", str(destination))
    rights_snapshot = None
    if access_level == "research_local_only":
        if task01_handoff_path is None or rights_evidence_path is None:
            raise ReviewError("REVIEW_RIGHTS_TRUST_REQUIRED", access_level)
        rights_snapshot = load_trusted_rights_snapshot(
            root,
            task01_handoff_path,
            rights_evidence_path,
        )
    trust_root = load_trust_root(root)
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
            if access_level == "open_fixture":
                authorized = (
                    glyph["data_origin"] == "generated_fixture"
                    and glyph["rights_tier"] == "open"
                    and glyph["release_tier"] == "fixture_only"
                )
            else:
                assert rights_snapshot is not None
                matching_rights = [
                    record
                    for record in rights_snapshot.records
                    if record.get("source_id") == glyph.get("source_id")
                    and record.get("decision_status") == "passed"
                    and (
                        record.get("rights_tier") == glyph.get("rights_tier")
                        or (
                            record.get("rights_tier") == "open"
                            and glyph.get("rights_tier") == "research_local_only"
                        )
                    )
                    and set(record.get("permitted_uses", []))
                    & {"research_stimulus_local", "engineering_fixture"}
                ]
                fixture_authorized = fixture_local_access_authorized(
                    trust_root,
                    access_authorization_id,
                    str(glyph.get("source_id")),
                    str(glyph.get("rights_tier")),
                )
                authorized = (
                    glyph.get("data_origin") == "source_record"
                    and glyph.get("rights_tier") == "research_local_only"
                    and glyph.get("release_tier") == "research_local_only"
                    and bool(matching_rights)
                    and (rights_snapshot.formal_gate_passed or fixture_authorized)
                )
            if not authorized:
                raise ReviewError("REVIEW_ASSET_NOT_AUTHORIZED", glyph["glyph_instance_id"])
            mapping = mappings_by_id[glyph["mapping_id"]]
            source_asset = assets_by_id[glyph["representation_asset_ids"]["original"]]
            candidate_asset = assets_by_id[glyph["representation_asset_ids"]["B_shape"]]
            copied_source = _copy_asset(root, staging, source_asset)
            copied_candidate = _copy_asset(root, staging, candidate_asset)
            subject_id = glyph["glyph_instance_id"]
            items.append(
                {
                    "schema_version": "1.1.0",
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
                    "access_status": "open_fixture" if access_level == "open_fixture" else "local_authorized",
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
            "schema_version": "1.1.0",
            "package_id": package_id,
            "package_version": "1.1.0",
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
            "asset_access_level": access_level,
            "asset_copy_policy": (
                "copied_open_fixture" if access_level == "open_fixture" else "local_review_package_only"
            ),
            "redistribution_status": "fixture_only" if access_level == "open_fixture" else "prohibited",
            "access_authorization_id": access_authorization_id if access_level == "research_local_only" else None,
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
        if access_level == "research_local_only":
            for path in sorted(destination.rglob("*")):
                path.chmod(0o700 if path.is_dir() else 0o600)
            destination.chmod(0o700)
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
    trust_root = load_trust_root()
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
        reviewer_role = row.get("reviewer_role", "").strip()
        round_number = _positive_integer(row.get("round"), "round", row_number)
        review_round_type = row.get("review_round_type", "").strip()
        if review_origin == "real_expert":
            approval = _validate_gate_approval(gate_approval, manifest)
            _validate_real_reviewer_scope(
                approval,
                reviewer_id,
                reviewer_role,
                review_round_type,
                row_number,
            )
            approval_id = str(approval["approval_id"])
        elif review_origin == "synthetic_fixture":
            if not reviewer_id.startswith("reviewer_fixture_"):
                raise ReviewError("SYNTHETIC_REVIEWER_ID_REQUIRED", f"row {row_number}")
            if not fixture_reviewer_authorized(
                trust_root,
                reviewer_id,
                reviewer_role,
                review_round_type,
            ):
                code = (
                    "REVIEW_ADJUDICATOR_UNAUTHORIZED"
                    if review_round_type == "adjudication"
                    else "SYNTHETIC_REVIEWER_UNAUTHORIZED"
                )
                raise ReviewError(code, f"row {row_number}")
            approval_id = None
        else:
            raise ReviewError("REVIEW_ORIGIN_INVALID", f"row {row_number}")
        key = (item["subject_id"], reviewer_id, round_number)
        if review_round_type == "independent" and key in seen_independent:
            raise ReviewError("REVIEW_NOT_INDEPENDENT", f"row {row_number}")
        seen_independent.add(key)
        dimensions = {dimension: row.get(dimension, "").strip() for dimension in RUBRIC_DIMENSIONS}
        payload: dict[str, Any] = {
            "schema_version": "1.1.0",
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
            "review_item_id": item["review_item_id"],
            "subject_type": item["subject_type"],
            "subject_id": item["subject_id"],
            "reviewer_id": reviewer_id,
            "reviewer_role": reviewer_role,
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
    minimum_substantive_dimensions: int = DEFAULT_MINIMUM_SUBSTANTIVE_DIMENSIONS,
    required_dimensions: tuple[str, ...] = RUBRIC_DIMENSIONS,
    required_role_groups: tuple[frozenset[str], ...] = DEFAULT_ROLE_GROUPS,
) -> dict[str, dict[str, Any]]:
    trust_root = load_trust_root()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        grouped.setdefault(review["subject_id"], []).append(review)
    summaries: dict[str, dict[str, Any]] = {}
    for subject_id, subject_reviews in grouped.items():
        independent = [review for review in subject_reviews if review["review_round_type"] == "independent"]
        real = [review for review in independent if review["review_origin"] == "real_expert"]
        synthetic = [review for review in independent if review["review_origin"] == "synthetic_fixture"]
        fixture_status, fixture_blockers = _decision_status(
            subject_reviews,
            "synthetic_fixture",
            minimum_independent_reviews,
            minimum_substantive_dimensions,
            required_dimensions,
            required_role_groups,
            trust_root,
        )
        formal_status, formal_blockers = _decision_status(
            subject_reviews,
            "real_expert",
            minimum_independent_reviews,
            minimum_substantive_dimensions,
            required_dimensions,
            required_role_groups,
            trust_root,
        )
        decisions = Counter(review["overall_decision"] for review in subject_reviews)
        summaries[subject_id] = {
            "package_ids": sorted({review["package_id"] for review in subject_reviews}),
            "synthetic_review_count": len({review["reviewer_id"] for review in synthetic}),
            "real_review_count": len({review["reviewer_id"] for review in real}),
            "fixture_status": fixture_status,
            "formal_status": formal_status,
            "decision_counts": dict(sorted(decisions.items())),
            "fixture_policy_blockers": fixture_blockers,
            "formal_policy_blockers": formal_blockers,
            "adjudication_review_ids": sorted(
                review["review_id"]
                for review in subject_reviews
                if review["review_round_type"] == "adjudication"
            ),
        }
    return summaries


def validate_review_records(
    reviews: list[dict[str, Any]],
    schema_path: str | Path,
    *,
    package_dir: str | Path | None = None,
    review_records_path: str | Path | None = None,
) -> list[str]:
    errors: list[str] = []
    trust_root = load_trust_root()
    if review_records_path is not None:
        try:
            file_reviews = _read_jsonl(Path(review_records_path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"HAN_REVIEW_RECORDS_FILE_INVALID: {error}")
        else:
            if canonical_json(file_reviews) != canonical_json(reviews):
                errors.append("HAN_REVIEW_RECORDS_FILE_MISMATCH")
    package_manifest: dict[str, Any] | None = None
    package_items: dict[str, str] = {}
    if package_dir is not None:
        try:
            package_manifest, items, _ = verified_review_package(package_dir)
            package_items = {item["subject_id"]: item["review_item_id"] for item in items}
        except (OSError, ValueError, ReviewError, json.JSONDecodeError) as error:
            errors.append(f"HAN_REVIEW_PACKAGE_INVALID: {error}")
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
        origin = review.get("review_origin")
        reviewer_id = str(review.get("reviewer_id"))
        reviewer_role = str(review.get("reviewer_role"))
        round_type = str(review.get("review_round_type"))
        if origin == "synthetic_fixture":
            if not fixture_reviewer_authorized(
                trust_root,
                reviewer_id,
                reviewer_role,
                round_type,
            ):
                errors.append(f"HAN_REVIEW_REVIEWER_UNAUTHORIZED review_id={review_id}")
        elif origin == "real_expert":
            approval = next(
                (
                    item
                    for item in trust_root["expert_gate_approvals"]
                    if item.get("approval_id") == review.get("gate_approval_id")
                ),
                None,
            )
            if approval is None:
                errors.append(f"HAN_REVIEW_GATE_APPROVAL_UNTRUSTED review_id={review_id}")
            elif not _real_reviewer_in_scope(approval, reviewer_id, reviewer_role, round_type):
                errors.append(f"HAN_REVIEW_REVIEWER_OUT_OF_SCOPE review_id={review_id}")
            elif review_records_path is not None and not accepted_review_batch(
                trust_root,
                approval_id=str(review.get("gate_approval_id")),
                package_id=str(review.get("package_id")),
                package_content_sha256=str(review.get("source_package_sha256")),
                records_sha256=sha256_file(Path(review_records_path)),
            ):
                errors.append(f"HAN_REVIEW_BATCH_UNTRUSTED review_id={review_id}")
        if package_manifest is not None and (
            review.get("package_id") != package_manifest.get("package_id")
            or review.get("source_package_sha256") != package_manifest.get("package_content_sha256")
            or package_items.get(str(review.get("subject_id"))) != review.get("review_item_id")
        ):
            errors.append(f"HAN_REVIEW_PACKAGE_BINDING_MISMATCH review_id={review_id}")
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


def _decision_status(
    subject_reviews: list[dict[str, Any]],
    origin: str,
    minimum: int,
    minimum_substantive_dimensions: int,
    required_dimensions: tuple[str, ...],
    required_role_groups: tuple[frozenset[str], ...],
    trust_root: dict[str, Any],
) -> tuple[str, list[str]]:
    reviews = [
        review
        for review in subject_reviews
        if review["review_origin"] == origin and review["review_round_type"] == "independent"
    ]
    blockers: list[str] = []
    if origin == "real_expert" and any(
        not any(
            approval.get("approval_id") == review.get("gate_approval_id")
            for approval in trust_root["expert_gate_approvals"]
        )
        for review in reviews
    ):
        blockers.append("REVIEW_PROVENANCE_UNTRUSTED")
    decisions = {review["overall_decision"] for review in reviews}
    substantive = decisions - {"outside_expertise", "not_applicable"}
    if "pass" in substantive and substantive & {"fail", "needs_revision"}:
        adjudications = [
            review
            for review in subject_reviews
            if review["review_origin"] == origin and review["review_round_type"] == "adjudication"
        ]
        terminal_adjudication = _terminal_adjudication(adjudications, trust_root)
        if terminal_adjudication is not None:
            decision = terminal_adjudication["overall_decision"]
            if decision in {"pass", "fail", "needs_revision"}:
                status = "passed" if decision == "pass" else decision
                return status, sorted(set(blockers))
        return "conflicted", sorted(set([*blockers, "ADJUDICATION_REQUIRED"]))
    if "fail" in substantive:
        return "failed", sorted(set(blockers))
    if "needs_revision" in substantive:
        return "needs_revision", sorted(set(blockers))
    passing = [review for review in reviews if review["overall_decision"] == "pass"]
    if len({review["reviewer_id"] for review in passing}) < minimum:
        blockers.append("INSUFFICIENT_INDEPENDENT_REVIEWS")
    if any(
        review.get("round") != 1
        or review.get("independence_attestation") is not True
        or review.get("prior_review_visibility") != "hidden"
        for review in passing
    ):
        blockers.append("INDEPENDENCE_POLICY_NOT_MET")
    roles = {review["reviewer_role"] for review in passing}
    if any(not roles.intersection(group) for group in required_role_groups):
        blockers.append("REVIEW_ROLE_COVERAGE_INSUFFICIENT")
    covered_dimensions: set[str] = set()
    for review in passing:
        dimensions = review.get("dimensions", {})
        substantive_dimensions = {
            dimension
            for dimension, decision in dimensions.items()
            if decision not in {"outside_expertise", "not_applicable"}
        }
        if len(substantive_dimensions) < minimum_substantive_dimensions:
            blockers.append("REVIEW_SUBSTANTIVE_DIMENSIONS_INSUFFICIENT")
        if any(dimensions.get(dimension) != "pass" for dimension in substantive_dimensions):
            blockers.append("REVIEW_DIMENSION_DECISION_INCONSISTENT")
        covered_dimensions.update(
            dimension for dimension in required_dimensions if dimensions.get(dimension) == "pass"
        )
    if set(required_dimensions) - covered_dimensions:
        blockers.append("REVIEW_DIMENSION_COVERAGE_INSUFFICIENT")
    return ("blocked", sorted(set(blockers))) if blockers else ("passed", [])


def _validate_gate_approval(
    approval: dict[str, Any] | None,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(approval, dict):
        raise ReviewError("GATE_EXPERT_APPROVAL_REQUIRED", manifest["package_id"])
    trusted = trusted_expert_approval(load_trust_root(), approval)
    if trusted is None:
        raise ReviewError("GATE_EXPERT_APPROVAL_UNTRUSTED", manifest["package_id"])
    required = {
        "gate_id",
        "status",
        "approval_id",
        "package_id",
        "package_content_sha256",
        "approved_by",
        "approved_at",
        "reviewer_roles",
        "allowed_round_types",
        "adjudicator_ids",
    }
    if not required <= approval.keys():
        raise ReviewError("GATE_EXPERT_APPROVAL_INVALID", manifest["package_id"])
    if approval["gate_id"] != "GATE-EXPERT" or approval["status"] != "approved":
        raise ReviewError("GATE_EXPERT_APPROVAL_INVALID", manifest["package_id"])
    if (
        approval["package_id"] != manifest["package_id"]
        or approval["package_content_sha256"] != manifest["package_content_sha256"]
    ):
        raise ReviewError("GATE_EXPERT_PACKAGE_MISMATCH", manifest["package_id"])
    return trusted


def _validate_real_reviewer_scope(
    approval: dict[str, Any],
    reviewer_id: str,
    reviewer_role: str,
    round_type: str,
    row_number: int,
) -> None:
    if not _real_reviewer_in_scope(approval, reviewer_id, reviewer_role, round_type):
        code = "REVIEW_ADJUDICATOR_UNAUTHORIZED" if round_type == "adjudication" else "REVIEWER_SCOPE_UNAUTHORIZED"
        raise ReviewError(code, f"row {row_number}")


def _real_reviewer_in_scope(
    approval: dict[str, Any],
    reviewer_id: str,
    reviewer_role: str,
    round_type: str,
) -> bool:
    role_map = approval.get("reviewer_roles", {})
    return (
        reviewer_role in role_map.get(reviewer_id, [])
        and round_type in approval.get("allowed_round_types", [])
        and (round_type != "adjudication" or reviewer_id in approval.get("adjudicator_ids", []))
    )


def _adjudication_authorized(review: dict[str, Any], trust_root: dict[str, Any]) -> bool:
    if review["review_origin"] == "synthetic_fixture":
        return fixture_reviewer_authorized(
            trust_root,
            review["reviewer_id"],
            review["reviewer_role"],
            "adjudication",
        )
    approval = next(
        (
            item
            for item in trust_root["expert_gate_approvals"]
            if item.get("approval_id") == review.get("gate_approval_id")
        ),
        None,
    )
    return approval is not None and _real_reviewer_in_scope(
        approval,
        review["reviewer_id"],
        review["reviewer_role"],
        "adjudication",
    )


def _terminal_adjudication(
    adjudications: list[dict[str, Any]],
    trust_root: dict[str, Any],
) -> dict[str, Any] | None:
    if not adjudications or any(
        not _adjudication_authorized(review, trust_root) for review in adjudications
    ):
        return None
    by_id = {review["review_id"]: review for review in adjudications}
    superseded_ids = {
        review["supersedes_review_id"]
        for review in adjudications
        if review.get("supersedes_review_id") in by_id
    }
    terminals = [review for review in adjudications if review["review_id"] not in superseded_ids]
    if len(terminals) != 1:
        return None
    terminal = terminals[0]
    visited: set[str] = set()
    current: dict[str, Any] | None = terminal
    while current is not None:
        review_id = current["review_id"]
        if review_id in visited:
            return None
        visited.add(review_id)
        previous = by_id.get(current.get("supersedes_review_id"))
        if previous is not None and current.get("round", 0) <= previous.get("round", 0):
            return None
        current = previous
    return terminal if visited == set(by_id) else None


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
                or value.get("review_origin") != review.get("review_origin")
                for value in linked
                if value is not None
            ):
                errors.append(f"HAN_REVIEW_CONFLICT_REFERENCE_INVALID review_id={review_id}")
            elif len({value.get("overall_decision") for value in linked if value is not None}) < 2:
                errors.append(f"HAN_REVIEW_CONFLICT_NOT_PRESENT review_id={review_id}")
            else:
                independent = [
                    value
                    for value in reviews
                    if value.get("review_round_type") == "independent"
                    and value.get("package_id") == review.get("package_id")
                    and value.get("subject_id") == review.get("subject_id")
                    and value.get("review_origin") == review.get("review_origin")
                ]
                expected_ids = {value.get("review_id") for value in independent}
                if set(review.get("conflict_review_ids", [])) != expected_ids:
                    errors.append(f"HAN_REVIEW_CONFLICT_SET_INCOMPLETE review_id={review_id}")
                if review.get("round", 0) <= max(value.get("round", 0) for value in independent):
                    errors.append(f"HAN_REVIEW_ADJUDICATION_ROUND_INVALID review_id={review_id}")
                if review.get("reviewer_id") in {value.get("reviewer_id") for value in independent}:
                    errors.append(f"HAN_REVIEW_ADJUDICATOR_NOT_INDEPENDENT review_id={review_id}")
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


def verified_review_package(
    package_dir: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
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
    return manifest, items, expected_content_hash


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

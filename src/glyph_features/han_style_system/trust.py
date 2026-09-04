"""Load the repository-pinned TASK-04 trust root."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import canonical_json, sha256_file


ROOT = Path(__file__).resolve().parents[3]
TRUST_ROOT_PATH = "configs/han_style_trust_root_v1.json"
TRUST_ROOT_SHA256 = "e662bc3fc8ee3ac5c1d8aa9d167fdb123d4890f7a024ba9150961242153f60f8"


def load_trust_root(workspace_root: str | Path = ROOT) -> dict[str, Any]:
    path = Path(workspace_root).resolve() / TRUST_ROOT_PATH
    if not path.is_file() or sha256_file(path) != TRUST_ROOT_SHA256:
        raise ValueError("HAN_TRUST_ROOT_HASH_MISMATCH")
    policy = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "trust_root_id",
        "fixture_reviewers",
        "fixture_local_review_authorizations",
        "expert_gate_approvals",
        "accepted_review_batches",
        "claim_human_decisions",
    }
    if set(policy) != expected_keys or policy.get("schema_version") != "1.0.0":
        raise ValueError("HAN_TRUST_ROOT_FORMAT_INVALID")
    return policy


def fixture_reviewer_authorized(
    policy: dict[str, Any],
    reviewer_id: str,
    reviewer_role: str,
    round_type: str,
) -> bool:
    return any(
        item.get("reviewer_id") == reviewer_id
        and reviewer_role in item.get("allowed_roles", [])
        and round_type in item.get("allowed_round_types", [])
        for item in policy["fixture_reviewers"]
    )


def fixture_local_access_authorized(
    policy: dict[str, Any],
    authorization_id: str | None,
    source_id: str,
    rights_tier: str,
) -> bool:
    return any(
        item.get("authorization_id") == authorization_id
        and item.get("formal_effect") is False
        and source_id in item.get("source_ids", [])
        and rights_tier in item.get("allowed_rights_tiers", [])
        for item in policy["fixture_local_review_authorizations"]
    )


def trusted_expert_approval(
    policy: dict[str, Any],
    supplied: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(supplied, dict):
        return None
    approval = next(
        (
            item
            for item in policy["expert_gate_approvals"]
            if item.get("approval_id") == supplied.get("approval_id")
        ),
        None,
    )
    if approval is None or canonical_json(approval) != canonical_json(supplied):
        return None
    return approval


def accepted_review_batch(
    policy: dict[str, Any],
    *,
    approval_id: str,
    package_id: str,
    package_content_sha256: str,
    records_sha256: str,
) -> bool:
    return any(
        item.get("approval_id") == approval_id
        and item.get("package_id") == package_id
        and item.get("package_content_sha256") == package_content_sha256
        and item.get("review_records_sha256") == records_sha256
        for item in policy["accepted_review_batches"]
    )


def trusted_human_decisions(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["decision_id"]: item
        for item in policy["claim_human_decisions"]
        if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    }
"""Strict TASK-01 fixture intake for TASK-03 engineering runs."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import resolve_workspace_asset, validate_record as validate_asset_record
from glyph_features.asset_system.export import validate_handoff

from .schema import ROOT, validate_record


TASK01_HANDOFF = Path("data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json")
TASK01_CHECKPOINT = "af3820836a6ffa92c63016b0e308f624f9b42db0"


class FixtureIntakeError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def load_task01_fixture(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / TASK01_HANDOFF
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_checkpoint_provenance(root, manifest)
    errors = validate_handoff(manifest_path, root)
    errors = [error for error in errors if not error.startswith("producer hash mismatch: ")]
    if errors:
        raise FixtureIntakeError("TASK01_HANDOFF_INVALID", "; ".join(errors))
    entrypoints = [item for item in manifest["next_task_entrypoints"] if item["task_id"] == "TASK-03"]
    if len(entrypoints) != 1 or entrypoints[0]["status"] != "blocked":
        raise FixtureIntakeError("TASK01_FORMAL_ENTRYPOINT_STATE_UNEXPECTED", repr(entrypoints))
    artifact = next((item for item in manifest["outputs"] if item["logical_type"] == "fixture_stimuli"), None)
    if artifact is None or artifact["rights_or_privacy_level"] != "open_fixture":
        raise FixtureIntakeError("TASK01_OPEN_FIXTURE_MISSING", "fixture_stimuli output is absent")
    stimulus_path = root / artifact["path"]
    rows = [json.loads(line) for line in stimulus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise FixtureIntakeError("TASK01_FIXTURE_COUNT_UNEXPECTED", str(len(rows)))
    stimulus = rows[0]
    schema_errors = validate_asset_record(stimulus, root / "schema/ecological_stimulus.schema.json")
    if schema_errors:
        raise FixtureIntakeError("TASK01_FIXTURE_SCHEMA_INVALID", "; ".join(schema_errors))
    if (
        stimulus["stimulus_kind"] != "generated_fixture"
        or stimulus["intended_use"] != "engineering_fixture"
        or stimulus["rights_tier"] != "open"
        or stimulus["release_status"] != "fixture_only"
    ):
        raise FixtureIntakeError("TASK01_FIXTURE_USE_NOT_ALLOWED", stimulus["stimulus_id"])
    asset_ref = stimulus["representations"]["B_shape"]["asset_ref"]
    resolve_workspace_asset(root, asset_ref)
    return {
        "manifest": manifest,
        "manifest_path": TASK01_HANDOFF.as_posix(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "stimulus": stimulus,
        "asset_ref": asset_ref,
    }


def build_synthetic_catalog(
    *,
    study_id: str = "study_cross_cultural_v1",
    root: Path = ROOT,
) -> dict[str, Any]:
    upstream = load_task01_fixture(root)
    stimulus = upstream["stimulus"]
    items = []
    for script in ("latin", "han", "kana", "hangul"):
        for index in range(1, 5):
            items.append({
                "stimulus_id": f"stim_task03_{script}_{index:02d}",
                "source_stimulus_id": stimulus["stimulus_id"],
                "work_id": f"work_task03_{script}_{index:02d}",
                "writing_system": script,
                "is_anchor": index == 1,
                "asset": upstream["asset_ref"],
                "rights_tier": "open",
                "release_status": "fixture_only",
                "blind_metadata": {
                    "award_hidden": True,
                    "source_hidden": True,
                    "brand_hidden": True,
                    "filename_hidden": True,
                },
                "data_origin": "synthetic",
            })
    catalog = {
        "schema_version": "1.0.0",
        "study_id": study_id,
        "data_origin": "synthetic",
        "source_handoff": {
            "task_id": "TASK-01",
            "handoff_schema_version": upstream["manifest"]["handoff_schema_version"],
            "path": upstream["manifest_path"],
            "sha256": upstream["manifest_sha256"],
            "strict_validation": "passed",
        },
        "items": items,
    }
    errors = validate_record(catalog, "experiment_stimulus_catalog.schema.json")
    if errors:
        raise FixtureIntakeError("TASK03_SYNTHETIC_CATALOG_INVALID", "; ".join(errors))
    return catalog


def _validate_checkpoint_provenance(root: Path, manifest: dict[str, Any]) -> None:
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", TASK01_CHECKPOINT, "HEAD"],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise FixtureIntakeError("TASK01_CHECKPOINT_NOT_IN_HISTORY", TASK01_CHECKPOINT)
    manifest_blob = subprocess.run(
        ["git", "-C", str(root), "show", f"{TASK01_CHECKPOINT}:{TASK01_HANDOFF.as_posix()}"],
        capture_output=True,
        check=False,
    )
    if manifest_blob.returncode != 0:
        raise FixtureIntakeError("TASK01_CHECKPOINT_FILE_MISSING", TASK01_HANDOFF.as_posix())
    current_manifest_sha256 = hashlib.sha256(
        (root / TASK01_HANDOFF).read_bytes()
    ).hexdigest()
    checkpoint_manifest_sha256 = hashlib.sha256(manifest_blob.stdout).hexdigest()
    if current_manifest_sha256 != checkpoint_manifest_sha256:
        raise FixtureIntakeError(
            "TASK01_CHECKPOINT_HANDOFF_MISMATCH",
            f"{current_manifest_sha256} != {checkpoint_manifest_sha256}",
        )
    for entry in manifest["producer_provenance"]["files"]:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{TASK01_CHECKPOINT}:{entry['path']}"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise FixtureIntakeError("TASK01_CHECKPOINT_FILE_MISSING", entry["path"])
        actual = hashlib.sha256(result.stdout).hexdigest()
        if actual != entry["sha256"]:
            raise FixtureIntakeError(
                "TASK01_CHECKPOINT_PRODUCER_HASH_MISMATCH",
                f"{entry['path']}: {actual} != {entry['sha256']}",
            )
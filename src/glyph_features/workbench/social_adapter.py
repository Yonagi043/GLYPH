"""Validated-export adapter for the independent social-narrative service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from glyph_features.asset_system.catalog import stable_id
from glyph_features.social_system.exports import NARRATIVE_SCHEMA
from glyph_features.social_system.service import SocialNarrativeService
from tools.project_social_to_narratives import project_record
from tools.social_io import schema_validator
from tools.validate_social_observations import validate

from .catalog import Catalog, CatalogError


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SCHEMA = ROOT / "schema" / "social_export_package.schema.json"


def _event(index: int, text: str) -> dict[str, Any]:
    return {
        "$type": "message",
        "payload": {
            "$type": "network.bsky.jetstream.subscribeEvents#commit",
            "did": "did:plc:task05-synthetic-fixture",
            "seq": 50_000_000_000 + index,
            "time": "2026-09-04T08:00:00Z",
            "operation": "create",
            "collection": "app.bsky.feed.post",
            "rkey": f"task05fixture{index:02d}",
            "cid": f"bafytask05fixture{index:02d}",
            "record": {
                "$type": "app.bsky.feed.post",
                "createdAt": "2026-09-04T07:59:00Z",
                "langs": ["en"],
                "text": text,
            },
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path, error_code: str) -> list[dict[str, Any]]:
    try:
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(error_code) from error
    if not all(isinstance(row, dict) for row in rows):
        raise CatalogError(error_code)
    return rows


def _safe_package_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        value == path.as_posix()
        and not path.is_absolute()
        and bool(path.parts)
        and all(part not in {"", ".", ".."} for part in path.parts)
        and "\\" not in value
    )


class SocialExportAdapter:
    """Create and consume social exports without mounting its web scheduler."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).expanduser().resolve()

    def create_fixture_export(self, destination_root: str | Path) -> dict[str, Any]:
        if self.database_path.exists():
            raise CatalogError("SOCIAL_FIXTURE_REQUIRES_NEW_DATABASE")
        service = SocialNarrativeService(self.database_path)
        scope = service.create_scope(
            name="TASK-05 synthetic narrative fixture",
            object_type="style_family",
            object_label="seal",
            keywords=["typography"],
            languages=["en"],
            window_start="2026-09-04T00:00:00Z",
            window_end="2026-09-05T00:00:00Z",
            max_items=10,
            query_family="object_aesthetic",
            phase="confirmatory",
            exact_query='"seal" OR "sans" typography',
        )
        run = service.start_run(scope["scope_id"])
        cases = [
            ("Seal typography feels premium.", "seal", "premium", "positive"),
            ("Sans typography is modern, not traditional.", "sans", "modern", "negative"),
        ]
        for index, (text, _, _, _) in enumerate(cases, start=1):
            if not service.process_event(run["collection_run_id"], _event(index, text)):
                raise CatalogError("SOCIAL_FIXTURE_EVENT_REJECTED")
        service.finish_run(run["collection_run_id"], "completed")
        observations = {row["text"]: row for row in service.observations()}
        for text, object_label, term, stance in cases:
            observation_id = observations[text]["observation_id"]
            service.screen_observation(
                observation_id,
                decision="include",
                reason="Synthetic fixture contains an explicit object-term relation.",
            )
            for coder_id in ("annotator_fixture_a", "annotator_fixture_b"):
                service.submit_independent_annotation(
                    observation_id,
                    coder_id=coder_id,
                    object_type="style_family",
                    object_label=object_label,
                    aesthetic_terms=[term],
                    evidence_span=text,
                    stance=stance,
                    language_confirmed=True,
                    author_role="ordinary_user",
                )
            service.review_observation(
                observation_id,
                status="human_verified",
                object_type="style_family",
                object_label=object_label,
                aesthetic_terms=[term],
                evidence_span=text,
                stance=stance,
                confidence=1.0,
                exclusion_reason=None,
                author_role="ordinary_user",
            )
        quality = service.evaluate_run_quality(run["collection_run_id"])
        if quality["status"] != "passed":
            raise CatalogError(f"SOCIAL_FIXTURE_QUALITY_FAILED:{quality['blockers']}")
        exported = service.export_run(
            run["collection_run_id"],
            Path(destination_root).expanduser().resolve(),
            data_origin="synthetic",
        )
        return self.validate_export(
            Path(exported["directory"]), expected_data_origin="synthetic"
        )

    @staticmethod
    def validate_export(
        directory: str | Path,
        *,
        expected_data_origin: str = "real",
    ) -> dict[str, Any]:
        root = Path(directory).resolve()
        required = {
            "package_manifest.json",
            "validation.json",
            "run_manifest.json",
            "run_governance.json",
            "observations.jsonl",
            "queries.csv",
            "sources.csv",
            "narratives.jsonl",
            "quality_reports.jsonl",
        }
        if not root.is_dir() or not required.issubset(
            {path.name for path in root.iterdir() if path.is_file()}
        ):
            raise CatalogError("SOCIAL_VALIDATED_EXPORT_INCOMPLETE")
        package = json.loads(
            (root / "package_manifest.json").read_text(encoding="utf-8")
        )
        if list(schema_validator(PACKAGE_SCHEMA).iter_errors(package)):
            raise CatalogError("SOCIAL_EXPORT_PACKAGE_SCHEMA_INVALID")
        classifications = {
            "synthetic": "synthetic_fixture",
            "real": "restricted_real_data",
        }
        data_origin = package["data_origin"]
        if (
            data_origin != expected_data_origin
            or package["data_classification"] != classifications[data_origin]
        ):
            raise CatalogError("SOCIAL_EXPORT_DATA_ORIGIN_MISMATCH")
        package_files: dict[str, dict[str, Any]] = {}
        for item in package["files"]:
            relative = item["path"]
            if not _safe_package_path(relative) or relative in package_files:
                raise CatalogError("SOCIAL_EXPORT_PACKAGE_PATH_INVALID")
            package_files[relative] = item
        actual_files = {}
        for path in root.rglob("*"):
            if path.is_symlink():
                raise CatalogError("SOCIAL_EXPORT_PACKAGE_SYMLINK_FORBIDDEN")
            if path.is_file() and path.name != "package_manifest.json":
                actual_files[path.relative_to(root).as_posix()] = path
        if set(package_files) != set(actual_files):
            raise CatalogError("SOCIAL_EXPORT_PACKAGE_FILE_SET_MISMATCH")
        for relative, item in package_files.items():
            path = actual_files[relative]
            if (
                path.stat().st_size != item["byte_size"]
                or _sha256(path) != item["sha256"]
            ):
                raise CatalogError(f"SOCIAL_EXPORT_FILE_HASH_MISMATCH:{relative}")

        validation = json.loads((root / "validation.json").read_text())
        governance = json.loads((root / "run_governance.json").read_text())
        manifest = json.loads((root / "run_manifest.json").read_text())
        observations = _jsonl(
            root / "observations.jsonl", "SOCIAL_EXPORT_OBSERVATIONS_INVALID"
        )
        narratives = _jsonl(
            root / "narratives.jsonl", "SOCIAL_EXPORT_NARRATIVES_INVALID"
        )
        quality_reports = _jsonl(
            root / "quality_reports.jsonl", "SOCIAL_EXPORT_QUALITY_INVALID"
        )
        run_id = package["collection_run_id"]
        if (
            manifest.get("collection_run_id") != run_id
            or governance.get("collection_run_id") != run_id
            or not quality_reports
            or quality_reports[-1].get("collection_run_id") != run_id
        ):
            raise CatalogError("SOCIAL_EXPORT_RUN_ID_MISMATCH")
        fresh_validation = validate(
            root / "observations.jsonl",
            queries_path=root / "queries.csv",
            sources_path=root / "sources.csv",
            run_manifest_path=root / "run_manifest.json",
        )
        if validation.get("valid") is not True:
            raise CatalogError("SOCIAL_EXPORT_VALIDATION_FAILED")
        if (
            fresh_validation.get("valid") is not True
            or validation.get("input_sha256") != fresh_validation.get("input_sha256")
            or validation.get("record_count") != fresh_validation.get("record_count")
            or validation.get("counts") != fresh_validation.get("counts")
        ):
            raise CatalogError("SOCIAL_EXPORT_VALIDATION_STALE")
        if (
            package["record_count"] != len(observations)
            or package["record_count"] != validation.get("record_count")
            or package["narrative_count"] != len(narratives)
            or package["quality_report_count"] != len(quality_reports)
        ):
            raise CatalogError("SOCIAL_EXPORT_COUNT_MISMATCH")
        if (
            quality_reports[-1].get("status") != "passed"
            or quality_reports[-1].get("quality_gate_passed") is not True
        ):
            raise CatalogError("SOCIAL_EXPORT_QUALITY_FAILED")
        if data_origin == "synthetic" and governance.get("release_allowed") is not False:
            raise CatalogError("SOCIAL_FIXTURE_RELEASE_MUST_REMAIN_BLOCKED")
        if not narratives or not all(row.get("human_verified") is True for row in narratives):
            raise CatalogError("SOCIAL_EXPORT_HAS_NO_VERIFIED_NARRATIVES")
        narrative_check = schema_validator(NARRATIVE_SCHEMA)
        if any(
            error
            for row in narratives
            for error in narrative_check.iter_errors(row)
        ):
            raise CatalogError("SOCIAL_EXPORT_NARRATIVE_SCHEMA_INVALID")
        expected_narratives = []
        if governance.get("analysis_allowed") is True:
            try:
                for observation in observations:
                    expected_narratives.extend(
                        project_record(
                            observation,
                            default_confidence=None,
                            check=narrative_check,
                        )
                    )
            except (KeyError, TypeError, ValueError) as error:
                raise CatalogError(
                    "SOCIAL_EXPORT_NARRATIVE_SEMANTICS_INVALID"
                ) from error
        expected_narratives.sort(key=lambda row: row["evidence_id"])
        if narratives != expected_narratives:
            raise CatalogError("SOCIAL_EXPORT_NARRATIVE_SEMANTICS_INVALID")
        files = {
            relative: {
                "sha256": item["sha256"],
                "byte_size": item["byte_size"],
            }
            for relative, item in package_files.items()
        }
        files["package_manifest.json"] = {
            "sha256": _sha256(root / "package_manifest.json"),
            "byte_size": (root / "package_manifest.json").stat().st_size,
        }
        return {
            "data_origin": data_origin,
            "data_classification": classifications[data_origin],
            "distribution_label": (
                "SYNTHETIC / DEMO"
                if data_origin == "synthetic"
                else "RESTRICTED REAL DATA"
            ),
            "collection_run_id": run_id,
            "platform": manifest["platform"],
            "narrative_count": len(narratives),
            "quality_status": quality_reports[-1]["status"],
            "release_allowed": governance.get("release_allowed") is True,
            "files": files,
            "narratives": narratives,
        }


def register_social_export(catalog: Catalog, export: dict[str, Any]) -> dict[str, Any]:
    run_id = export["collection_run_id"]
    package_file = export["files"]["package_manifest.json"]
    classifications = {
        "synthetic": "synthetic_fixture",
        "real": "restricted_real_data",
    }
    try:
        data_classification = classifications[export["data_origin"]]
    except KeyError as error:
        raise CatalogError("SOCIAL_EXPORT_DATA_ORIGIN_INVALID") from error
    artifact_id = catalog.register_artifact(
        {
            "module_id": "social",
            "logical_type": "validated_narrative_export",
            "uri": f"social-export://{run_id}/package_manifest.json",
            "sha256": package_file["sha256"],
            "schema_version": "social-export-package-v1",
            "data_classification": data_classification,
            "record_count": export["narrative_count"],
        }
    )
    link_ids = []
    for narrative in export["narratives"]:
        object_id = stable_id(
            "object",
            {
                "object_type": narrative["object_type"],
                "canonical_label": narrative["object_label"],
                "registry_version": "0.1.0",
            },
        )
        link_ids.append(
            catalog.register_entity_link(
                {
                    "source_module": "social",
                    "source_type": "narrative_object",
                    "source_id": object_id,
                    "target_module": "social",
                    "target_type": "narrative_evidence",
                    "target_id": narrative["evidence_id"],
                    "relation": "context_evidence_for_object",
                    "evidence_artifact_id": artifact_id,
                    "cluster_id": narrative["source_id"],
                    "analysis_boundary": "context_only_not_participant_exposure",
                }
            )
        )
    return {
        "artifact_id": artifact_id,
        "link_ids": link_ids,
        "narrative_count": len(link_ids),
        "collection_run_id": run_id,
    }
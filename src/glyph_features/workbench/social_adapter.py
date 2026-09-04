"""Validated-export adapter for the independent social-narrative service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import stable_id
from glyph_features.social_system.service import SocialNarrativeService

from .catalog import Catalog, CatalogError


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
            run["collection_run_id"], Path(destination_root).expanduser().resolve()
        )
        return self.validate_export(Path(exported["directory"]), synthetic=True)

    @staticmethod
    def validate_export(directory: str | Path, *, synthetic: bool) -> dict[str, Any]:
        root = Path(directory).resolve()
        required = {
            "validation.json",
            "run_manifest.json",
            "run_governance.json",
            "narratives.jsonl",
            "quality_reports.jsonl",
        }
        if not root.is_dir() or not required.issubset(
            {path.name for path in root.iterdir() if path.is_file()}
        ):
            raise CatalogError("SOCIAL_VALIDATED_EXPORT_INCOMPLETE")
        validation = json.loads((root / "validation.json").read_text())
        governance = json.loads((root / "run_governance.json").read_text())
        manifest = json.loads((root / "run_manifest.json").read_text())
        narratives = [
            json.loads(line)
            for line in (root / "narratives.jsonl").read_text().splitlines()
            if line
        ]
        quality_reports = [
            json.loads(line)
            for line in (root / "quality_reports.jsonl").read_text().splitlines()
            if line
        ]
        if validation.get("valid") is not True:
            raise CatalogError("SOCIAL_EXPORT_VALIDATION_FAILED")
        if not quality_reports or quality_reports[-1].get("status") != "passed":
            raise CatalogError("SOCIAL_EXPORT_QUALITY_FAILED")
        if governance.get("release_allowed") is not False:
            raise CatalogError("SOCIAL_FIXTURE_RELEASE_MUST_REMAIN_BLOCKED")
        if not narratives or not all(row.get("human_verified") is True for row in narratives):
            raise CatalogError("SOCIAL_EXPORT_HAS_NO_VERIFIED_NARRATIVES")
        return {
            "data_origin": "synthetic" if synthetic else "real",
            "distribution_label": "SYNTHETIC / DEMO" if synthetic else "RESTRICTED REAL DATA",
            "collection_run_id": manifest["collection_run_id"],
            "platform": manifest["platform"],
            "narrative_count": len(narratives),
            "quality_status": quality_reports[-1]["status"],
            "release_allowed": False,
            "files": {
                name: {"sha256": _sha256(root / name), "byte_size": (root / name).stat().st_size}
                for name in sorted(required)
            },
            "narratives": narratives,
        }


def register_social_export(catalog: Catalog, export: dict[str, Any]) -> dict[str, Any]:
    run_id = export["collection_run_id"]
    narrative_file = export["files"]["narratives.jsonl"]
    artifact_id = catalog.register_artifact(
        {
            "module_id": "social",
            "logical_type": "validated_narrative_export",
            "uri": f"social-export://{run_id}/narratives.jsonl",
            "sha256": narrative_file["sha256"],
            "schema_version": "validated-export-v17",
            "data_classification": "synthetic_fixture",
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
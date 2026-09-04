"""Public orchestration service for the local GLYPH workbench."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from glyph_features.asset_system.catalog import canonical_json

from .analysis import run_fixture_analysis
from .assembly import import_reference_graph
from .catalog import Catalog
from .handoffs import inspect_upstream_handoffs
from .joins import build_synthetic_analysis_table
from .modules import build_module_descriptors
from .snapshots import freeze_analysis_plan, freeze_analysis_snapshot
from .gates import evaluate_release_candidate
from .gates import ReleaseBlocked
from .releases import export_demo_audit_package
from .social_adapter import SocialExportAdapter, register_social_export
from .backups import (
    BackupError,
    create_coordinated_backup,
    restore_coordinated_backup,
)


class DatabaseBoundaryError(ValueError):
    """Raised before opening a database when explicit roles are unsafe."""


class WorkbenchService:
    """Coordinate public module contracts without owning their domain state."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        catalog_database: str | Path,
        social_database: str | Path,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.catalog_database = Path(catalog_database).expanduser().resolve()
        self.social_database = Path(social_database).expanduser().resolve()
        production_social = (
            self.workspace_root / "data/raw/social/glyph-social.sqlite3"
        ).resolve()
        if self.catalog_database == self.social_database:
            raise DatabaseBoundaryError(
                "DATABASE_ROLES_MUST_BE_DISTINCT: catalog and social paths are equal"
            )
        if production_social in {self.catalog_database, self.social_database}:
            raise DatabaseBoundaryError(
                "PRODUCTION_SOCIAL_DATABASE_FORBIDDEN: explicit user approval is required"
            )
        self.catalog = Catalog(self.catalog_database)

    def social_status(self) -> dict[str, Any]:
        """Inspect an existing social database in read-only mode without migration."""

        if not self.social_database.is_file():
            return {
                "health": "absent",
                "schema_version": None,
                "expected_schema_version": 17,
                "migration_performed": False,
                "blockers": ["SOCIAL_DATABASE_NOT_INITIALIZED"],
            }
        uri = f"file:{self.social_database}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        except sqlite3.Error:
            return {
                "health": "blocked",
                "schema_version": None,
                "expected_schema_version": 17,
                "migration_performed": False,
                "blockers": ["SOCIAL_DATABASE_UNREADABLE"],
            }
        blockers = []
        if version != 17:
            blockers.append("SOCIAL_SCHEMA_MIGRATION_REQUIRES_SEPARATE_APPROVAL")
        if integrity != "ok":
            blockers.append("SOCIAL_DATABASE_INTEGRITY_FAILED")
        status = {
            "health": "ready" if not blockers else "blocked",
            "schema_version": version,
            "expected_schema_version": 17,
            "integrity_check": integrity,
            "migration_performed": False,
            "blockers": blockers,
        }
        status["validated_export_count"] = sum(
            row["logical_type"] == "validated_narrative_export"
            for row in self.catalog.rows("artifacts")
        )
        return status

    def initialize_catalog(self) -> dict[str, Any]:
        results = inspect_upstream_handoffs(self.workspace_root)
        descriptors = build_module_descriptors(results)
        self.catalog.register_modules(descriptors)
        graph = import_reference_graph(self.catalog, self.workspace_root, results)
        plan = freeze_analysis_plan(self.catalog, self.workspace_root)
        fixture_path = self.workspace_root / "data/fixtures/system_e2e/generator_config.json"
        fixture_artifact_id = self.catalog.register_artifact(
            {
                "module_id": "workbench",
                "logical_type": "system_fixture_generator",
                "path": "data/fixtures/system_e2e/generator_config.json",
                "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                "schema_version": "1.0.0",
                "data_classification": "synthetic_fixture",
                "record_count": 1,
                "validation_schema": "schema/system_fixture.schema.json",
            }
        )
        return {
            "handoffs": results,
            "modules": descriptors,
            "graph": graph,
            "plan": plan,
            "fixture_artifact_id": fixture_artifact_id,
            "social": self.social_status(),
        }

    def _analysis_input_artifacts(self) -> list[str]:
        required_paths = {
            "configs/joint_analysis_plan_v1.json",
            "data/fixtures/system_e2e/generator_config.json",
            "data/fixtures/asset_system/reference_handoff_v1/fixture/stimuli.jsonl",
            "data/fixtures/visual_measurements/reference_run_v2/measurements.jsonl",
            "data/fixtures/experiment_system/reference_v1/records/stimulus_catalog.json",
            "data/fixtures/experiment_system/reference_v1/records/ratings.jsonl",
            "data/fixtures/han_style_system/reference_run_v1/candidate_bundle/stimulus_candidates.jsonl",
            "data/fixtures/han_style_system/reference_run_v1/candidate_bundle/adapters.jsonl",
            "data/templates/social_object_map.csv",
        }
        rows = [row for row in self.catalog.rows("artifacts") if row["uri"] in required_paths]
        found = {row["uri"] for row in rows}
        if found != required_paths:
            missing = sorted(required_paths - found)
            raise ValueError(f"ANALYSIS_INPUT_ARTIFACT_MISSING:{missing}")
        return [row["artifact_id"] for row in rows]

    def run_fixture_analysis(self) -> dict[str, Any]:
        if not self.catalog.rows("handoff_imports"):
            initialized = self.initialize_catalog()
            plan_revision_id = initialized["plan"]["plan_revision_id"]
        else:
            plans = self.catalog.rows("analysis_plans")
            if not plans:
                plan_revision_id = freeze_analysis_plan(
                    self.catalog, self.workspace_root
                )["plan_revision_id"]
            else:
                plan_revision_id = plans[0]["plan_revision_id"]
        plan_row = self.catalog.analysis_plan(plan_revision_id)
        plan = plan_row["plan"]
        snapshot = freeze_analysis_snapshot(
            self.catalog,
            self.workspace_root,
            plan_revision_id=plan_revision_id,
            artifact_ids=self._analysis_input_artifacts(),
            data_origin="synthetic",
            random_seed=20260904,
        )
        existing = self.catalog.analysis_run(snapshot["analysis_run_id"])
        if existing["result"] is not None:
            return existing
        rows, join_audit, _ = build_synthetic_analysis_table(self.workspace_root, plan)
        result = run_fixture_analysis(self.workspace_root, rows, join_audit, plan)
        result.update(
            {
                "analysis_run_id": snapshot["analysis_run_id"],
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "join_audit": join_audit,
            }
        )
        result.pop("result_sha256", None)
        result["result_sha256"] = hashlib.sha256(canonical_json(result)).hexdigest()
        self.catalog.complete_analysis_run(
            snapshot["analysis_run_id"],
            status=result["status"],
            result=result,
        )
        return self.catalog.analysis_run(snapshot["analysis_run_id"])

    def overview(self) -> dict[str, Any]:
        modules = []
        for row in self.catalog.rows("modules"):
            descriptor = json.loads(row["descriptor_json"])
            modules.append(descriptor)
        runs = self.catalog.rows("analysis_runs")
        gates = sorted(
            {
                gate_id
                for module in modules
                for gate_id in module.get("human_gates", [])
            }
        )
        return {
            "system": "GLYPH",
            "mode": "SYNTHETIC / DEMO",
            "readiness": {
                "engineering_ready": bool(modules)
                and all(module["readiness"]["engineering_ready"] for module in modules),
                "pilot_ready": False,
                "research_validated": False,
            },
            "modules": sorted(modules, key=lambda item: item["module_id"]),
            "analysis_runs": runs,
            "blocked_human_gates": gates,
            "social": self.social_status(),
            "catalog_integrity": self.catalog.integrity_check(),
        }

    def evaluate_release(
        self,
        analysis_run_id: str,
        *,
        purpose: str,
    ) -> dict[str, Any]:
        return evaluate_release_candidate(
            self.catalog,
            self.workspace_root,
            self.catalog.analysis_run(analysis_run_id),
            self.overview(),
            purpose=purpose,
        )

    def export_demo(
        self,
        analysis_run_id: str,
        output_root: str | Path,
    ) -> dict[str, Any]:
        run = self.catalog.analysis_run(analysis_run_id)
        candidate = self.evaluate_release(analysis_run_id, purpose="demo_export")
        plan = self.catalog.analysis_plan(run["plan_revision_id"])["plan"]
        return export_demo_audit_package(
            output_root,
            analysis_run=run,
            plan=plan,
            release_candidate=candidate,
        )

    def run_social_fixture(self, export_root: str | Path) -> dict[str, Any]:
        exported = SocialExportAdapter(self.social_database).create_fixture_export(
            export_root
        )
        registered = register_social_export(self.catalog, exported)
        return {
            **registered,
            "distribution_label": exported["distribution_label"],
            "quality_status": exported["quality_status"],
            "release_allowed": exported["release_allowed"],
        }

    def create_backup(self, backup_root: str | Path) -> dict[str, Any]:
        return create_coordinated_backup(
            self.catalog_database,
            self.social_database,
            Path(backup_root).expanduser().resolve(),
        )

    def restore_backup_drill(
        self,
        backup_root: str | Path,
        backup_id: str,
        *,
        target_catalog_database: str | Path,
        target_social_database: str | Path,
    ) -> dict[str, Any]:
        catalog_target = Path(target_catalog_database).expanduser().resolve()
        social_target = Path(target_social_database).expanduser().resolve()
        production_social = (
            self.workspace_root / "data/raw/social/glyph-social.sqlite3"
        ).resolve()
        if catalog_target == social_target:
            raise BackupError("RESTORE_DATABASE_ROLES_MUST_BE_DISTINCT")
        if {catalog_target, social_target}.intersection(
            {self.catalog_database, self.social_database, production_social}
        ):
            raise BackupError("RESTORE_TARGET_MUST_BE_NEW_TEMPORARY_PATH")
        if catalog_target.exists() or social_target.exists():
            raise BackupError("RESTORE_TARGET_MUST_NOT_EXIST")
        result = restore_coordinated_backup(
            Path(backup_root).expanduser().resolve(),
            backup_id,
            target_catalog_database=catalog_target,
            target_social_database=social_target,
        )
        restored = WorkbenchService(
            self.workspace_root,
            catalog_database=catalog_target,
            social_database=social_target,
        )
        status = restored.overview()
        if status["catalog_integrity"] != "ok" or status["social"]["health"] != "ready":
            catalog_target.unlink(missing_ok=True)
            social_target.unlink(missing_ok=True)
            raise BackupError("RESTORE_DRILL_HEALTH_CHECK_FAILED")
        return {**result, "health": status}

    def run_system_fixture(
        self,
        *,
        export_root: str | Path,
        backup_root: str | Path,
        checkpoint: Callable[[str], None] | None = None,
        completed_steps: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        notify = checkpoint or (lambda _stage: None)
        steps = completed_steps if completed_steps is not None else {}

        def stage(name: str, operation: Callable[[], Any]) -> Any:
            notify(name)
            if name not in steps:
                steps[name] = operation()
            notify(f"{name}_completed")
            return steps[name]

        initialized = stage("initialize_catalog", self.initialize_catalog)

        def attach_social() -> dict[str, Any]:
            social_status = self.social_status()
            if social_status["health"] == "absent":
                return self.run_social_fixture(Path(export_root) / "social")
            if social_status.get("validated_export_count", 0) >= 1:
                return {
                    "quality_status": "passed",
                    "distribution_label": "SYNTHETIC / DEMO",
                    "release_allowed": False,
                }
            raise DatabaseBoundaryError(
                "SYSTEM_FIXTURE_REQUIRES_NEW_OR_ATTACHED_SOCIAL_DATABASE"
            )

        social = stage("attach_social_export", attach_social)
        run = stage("run_analysis", self.run_fixture_analysis)
        demo = stage(
            "export_demo",
            lambda: self.export_demo(
                run["analysis_run_id"], Path(export_root) / "audit"
            ),
        )

        def check_formal_release() -> dict[str, Any]:
            try:
                self.evaluate_release(run["analysis_run_id"], purpose="formal_release")
            except ReleaseBlocked as error:
                return error.candidate
            raise RuntimeError("SYNTHETIC_FORMAL_RELEASE_WAS_NOT_BLOCKED")

        formal = stage("check_formal_release", check_formal_release)
        backup = stage("create_coordinated_backup", lambda: self.create_backup(backup_root))
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "handoff_count": len(initialized["handoffs"]),
            "module_count": len(initialized["modules"]),
            "analysis_run_id": run["analysis_run_id"],
            "analysis_status": run["status"],
            "social_quality_status": social["quality_status"],
            "demo_archive_name": demo["archive_name"],
            "demo_archive_sha256": demo["archive_sha256"],
            "formal_release_status": formal["status"],
            "formal_blocker_codes": [
                item["code"] for item in formal["formal_blockers"]
            ],
            "backup_id": backup["backup_id"],
        }
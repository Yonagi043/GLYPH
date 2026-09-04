import copy
import json
import sqlite3
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glyph_features.workbench import (
    Catalog,
    CatalogConflict,
    CatalogError,
    CatalogRoleError,
    JoinAuditError,
    AnalysisError,
    BackupError,
    DatabaseBoundaryError,
    ExportError,
    ReleaseBlocked,
    build_synthetic_analysis_table,
    build_module_descriptors,
    freeze_analysis_plan,
    freeze_analysis_snapshot,
    import_reference_graph,
    inspect_upstream_handoffs,
    model_family_for_scales,
    require_narrative_exposure_operationalization,
    strict_many_to_one,
    run_fixture_analysis,
    WorkbenchService,
    SocialExportAdapter,
    create_app,
    OperationManager,
)
from glyph_features.asset_system.catalog import validate_record
from glyph_features.workbench.cli import main as workbench_main
import glyph_features.workbench.backups as backup_module
import glyph_features.workbench.handoff as handoff_module


ROOT = Path(__file__).resolve().parents[1]


def test_current_upstream_handoffs_are_strictly_compatible() -> None:
    results = inspect_upstream_handoffs(ROOT)

    assert [result["task_id"] for result in results] == [
        "TASK-01",
        "TASK-02",
        "TASK-03",
        "TASK-04",
    ]
    assert [result["handoff_schema_version"] for result in results] == [
        "2.0.0",
        "1.1.0",
        "2.0.0",
        "1.1.0",
    ]
    assert all(result["validation_status"] == "valid" for result in results)
    assert all(result["compatible"] for result in results)
    assert all(result["producer_is_ancestor"] for result in results)
    assert all(result["readiness"]["engineering_ready"] for result in results)
    assert not any(result["readiness"]["pilot_ready"] for result in results)
    assert not any(result["readiness"]["research_validated"] for result in results)
    assert all(result["task05_entrypoint"] for result in results)
    assert all(result["blocked_gates"] for result in results)


def test_catalog_registers_only_descriptors_and_immutable_handoff_pointers(
    tmp_path: Path,
) -> None:
    results = inspect_upstream_handoffs(ROOT)
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.register_modules(build_module_descriptors(results))

    first_ids = [catalog.register_handoff(result) for result in results]
    assert [catalog.register_handoff(result) for result in results] == first_ids
    assert len(catalog.rows("modules")) == 6
    assert len(catalog.rows("handoff_imports")) == 4
    assert catalog.integrity_check() == "ok"
    assert not {
        "observations",
        "ratings",
        "visual_measurements",
        "asset_candidates",
    }.intersection(catalog.table_names())

    changed = copy.deepcopy(results[0])
    changed["manifest_sha256"] = "f" * 64
    with pytest.raises(CatalogConflict, match="HANDOFF_IMMUTABLE_CONFLICT"):
        catalog.register_handoff(changed)


def test_catalog_refuses_to_migrate_a_database_with_another_role(tmp_path: Path) -> None:
    database = tmp_path / "social.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE social_scopes(scope_id TEXT PRIMARY KEY)")

    with pytest.raises(CatalogRoleError, match="CATALOG_DATABASE_ROLE_MISMATCH"):
        Catalog(database)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert tables == {"social_scopes"}


def test_catalog_rejects_unsupported_version_before_creating_tables(tmp_path: Path) -> None:
    database = tmp_path / "old-catalog.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE workbench_metadata(singleton INTEGER PRIMARY KEY, schema_version TEXT, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO workbench_metadata VALUES (1, '0.9.0', '2026-09-04T00:00:00Z')"
        )

    with pytest.raises(CatalogRoleError, match="CATALOG_SCHEMA_UNSUPPORTED"):
        Catalog(database)
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert tables == {"workbench_metadata"}


def test_artifacts_are_safe_pointers_and_links_use_explicit_stable_ids(tmp_path: Path) -> None:
    results = inspect_upstream_handoffs(ROOT)
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.register_modules(build_module_descriptors(results))
    pointer = {
        "module_id": "assets",
        "logical_type": "fixture_stimuli",
        "path": "data/fixtures/asset_system/reference_handoff_v1/fixture/stimuli.jsonl",
        "sha256": "a" * 64,
        "schema_version": "2.0.0",
        "data_classification": "open_fixture",
        "record_count": 1,
        "payload": {"must_not": "be copied into the catalog"},
    }
    artifact_id = catalog.register_artifact(pointer)
    assert catalog.register_artifact(pointer) == artifact_id
    stored_pointer = json.loads(catalog.rows("artifacts")[0]["pointer_json"])
    assert "payload" not in stored_pointer

    link = {
        "source_module": "assets",
        "source_type": "stimulus",
        "source_id": "stim_eco_fixture",
        "target_module": "experiment",
        "target_type": "experiment_stimulus",
        "target_id": "stim_task03_fixture",
        "relation": "source_stimulus_for",
        "evidence_artifact_id": artifact_id,
        "cluster_id": "work_fixture",
    }
    link_id = catalog.register_entity_link(link)
    assert catalog.register_entity_link(link) == link_id
    assert len(catalog.rows("entity_links")) == 1

    for invalid_path in ("../fixture.json", "/tmp/fixture.json"):
        invalid = {**pointer, "path": invalid_path}
        with pytest.raises(CatalogError, match="ARTIFACT_PATH_NOT_CANONICAL"):
            catalog.register_artifact(invalid)


def test_reference_graph_preserves_cross_module_ids_without_exposure_claims(
    tmp_path: Path,
) -> None:
    results = inspect_upstream_handoffs(ROOT)
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.register_modules(build_module_descriptors(results))

    summary = import_reference_graph(catalog, ROOT, results)
    assert summary["handoff_count"] == 4
    assert summary["artifact_count"] > 20
    assert summary["entity_link_count"] > 150
    assert summary["participant_exposure_links"] == 0
    assert import_reference_graph(catalog, ROOT, results) == summary

    task01_stimulus = "stim_eco_ed82ad5985adf0287b9a"
    links = catalog.entity_links(task01_stimulus)
    experiment_stimuli = {
        link["target_id"]
        for link in links
        if link["relation"] == "source_stimulus_for"
    }
    assert len(experiment_stimuli) == 16
    assert "stim_task03_latin_01" in experiment_stimuli

    wp2_links = [
        json.loads(link["link_json"])
        for link in catalog.rows("entity_links")
        if link["relation"] == "hypothesis_context_for"
    ]
    assert {link["source_id"] for link in wp2_links} == {"style_hs01", "style_hs07"}
    assert all(
        link["analysis_boundary"] == "context_only_not_participant_exposure"
        for link in wp2_links
    )


def test_workbench_descriptors_and_frozen_analysis_contracts_validate() -> None:
    results = inspect_upstream_handoffs(ROOT)
    for descriptor in build_module_descriptors(results):
        assert validate_record(
            descriptor,
            ROOT / "schema/workbench_module_descriptor.schema.json",
        ) == []

    plan = json.loads((ROOT / "configs/joint_analysis_plan_v1.json").read_text())
    assert validate_record(plan, ROOT / "schema/analysis_plan.schema.json") == []
    assert plan["model"]["family"] == "ordinal"
    assert plan["model"]["random_effects"] == ["participant_id", "stimulus_id"]
    assert plan["features"]["scaling"] == "training_fold_only"
    assert plan["features"]["deprecated_scores_allowed"] is False

    fixture = json.loads(
        (ROOT / "data/fixtures/system_e2e/generator_config.json").read_text()
    )
    assert validate_record(fixture, ROOT / "schema/system_fixture.schema.json") == []
    assert fixture["data_origin"] == "synthetic"


def test_analysis_snapshot_is_hash_verified_and_immutable(tmp_path: Path) -> None:
    results = inspect_upstream_handoffs(ROOT)
    catalog = Catalog(tmp_path / "catalog.sqlite3")
    catalog.register_modules(build_module_descriptors(results))
    import_reference_graph(catalog, ROOT, results)
    plan = freeze_analysis_plan(catalog, ROOT)
    fixture_path = ROOT / "data/fixtures/system_e2e/generator_config.json"
    fixture_artifact = catalog.register_artifact(
        {
            "module_id": "workbench",
            "logical_type": "system_fixture_generator",
            "path": "data/fixtures/system_e2e/generator_config.json",
            "sha256": __import__("hashlib").sha256(fixture_path.read_bytes()).hexdigest(),
            "schema_version": "1.0.0",
            "data_classification": "synthetic_fixture",
            "record_count": 1,
        }
    )
    selected = [
        row["artifact_id"]
        for row in catalog.rows("artifacts")
        if row["logical_type"] in {
            "analysis_plan",
            "system_fixture_generator",
            "long_measurements",
            "experiment_ratings",
            "stimulus_catalog",
            "stimulus_candidate",
            "adapter_record",
        }
    ]
    assert fixture_artifact in selected
    snapshot = freeze_analysis_snapshot(
        catalog,
        ROOT,
        plan_revision_id=plan["plan_revision_id"],
        artifact_ids=selected,
        data_origin="synthetic",
        random_seed=20260904,
    )
    repeated = freeze_analysis_snapshot(
        catalog,
        ROOT,
        plan_revision_id=plan["plan_revision_id"],
        artifact_ids=reversed(selected),
        data_origin="synthetic",
        random_seed=20260904,
    )
    assert repeated == snapshot
    assert validate_record(snapshot, ROOT / "schema/analysis_run.schema.json") == []
    assert len(catalog.rows("analysis_runs")) == 1
    assert len(snapshot["handoffs"]) == 4
    assert len(snapshot["module_descriptors"]) == 6

    changed_plan = json.loads((ROOT / "configs/joint_analysis_plan_v1.json").read_text())
    changed_plan["research_questions"].append("Outcome-informed mutation")
    with pytest.raises(CatalogConflict, match="ANALYSIS_PLAN_IMMUTABLE_CONFLICT"):
        catalog.register_analysis_plan(changed_plan)


def test_synthetic_join_has_one_declared_unit_and_no_cartesian_inflation() -> None:
    plan = json.loads((ROOT / "configs/joint_analysis_plan_v1.json").read_text())
    rows, audit, generated_ratings = build_synthetic_analysis_table(ROOT, plan)

    assert len(generated_ratings) == 24 * 16
    assert len(rows) == len(generated_ratings)
    assert audit["final_rows"] == audit["unique_analysis_units"]
    assert audit["cluster_counts"] == {
        "participant_id": 24,
        "stimulus_id": 16,
        "work_id": 16,
        "source_stimulus_id": 1,
    }
    assert all(step["inflation_factor"] == 1.0 for step in audit["join_steps"])
    assert audit["narrative_policy"]["participant_exposure_attached"] is False
    assert audit["anti_pseudoreplication"]["visual_increment_eligible"] is False
    assert all(
        validate_record(record, ROOT / "schema/experiment_rating.schema.json") == []
        for record in generated_ratings[::64]
    )


def test_join_and_narrative_guards_fail_closed() -> None:
    with pytest.raises(JoinAuditError) as duplicate:
        strict_many_to_one(
            [{"stimulus_id": "stim_one"}],
            [
                {"stimulus_id": "stim_one", "value": 1},
                {"stimulus_id": "stim_one", "value": 2},
            ],
            left_key="stimulus_id",
            right_key="stimulus_id",
            step="fixture_duplicate",
            right_prefix="feature__",
        )
    assert duplicate.value.code == "UNEXPECTED_MANY_TO_MANY"

    with pytest.raises(JoinAuditError) as exposure:
        require_narrative_exposure_operationalization(
            [{"evidence_id": "evidence_fixture"}]
        )
    assert exposure.value.code == "NARRATIVE_EXPOSURE_NOT_OPERATIONALIZED"
    require_narrative_exposure_operationalization(
        [{"evidence_id": "evidence_fixture"}], aggregate_context=True
    )


def test_ordinal_fixture_model_recovers_direction_and_reports_boundaries() -> None:
    plan = json.loads((ROOT / "configs/joint_analysis_plan_v1.json").read_text())
    rows, audit, _ = build_synthetic_analysis_table(ROOT, plan)
    result = run_fixture_analysis(ROOT, rows, audit, plan)

    assert result["status"] == "completed_with_research_limits"
    assert result["model_specification"]["fitted_family"] == "ordinal"
    assert result["model_diagnostics"]["converged"] is True
    assert result["model_diagnostics"]["probability_rows_sum_to_one"] is True
    assert result["effect_estimates"][0]["estimate_log_odds"] > 0
    assert result["effect_estimates"][0]["confidence_interval_95"][0] > 0
    assert all(
        fold["participant_overlap"] == 0 and fold["stimulus_overlap"] == 0
        for fold in result["model_diagnostics"]["double_group_holdout"]
    )
    assert result["work_packages"]["WP2"]["participant_exposure_attached"] is False
    assert result["work_packages"]["WP3"]["status"] == "blocked"
    assert result["work_packages"]["WP4"]["status"] == "instance_level_only"
    assert result["work_packages"]["WP4"]["category_effect_allowed"] is False


def test_rating_scale_routes_fail_on_mixed_semantics() -> None:
    assert model_family_for_scales(["likert_1_7", "likert_1_5"]) == "ordinal"
    assert model_family_for_scales(["continuous_0_100"]) == "continuous"
    with pytest.raises(AnalysisError) as caught:
        model_family_for_scales(["likert_1_7", "continuous_0_100"])
    assert caught.value.code == "RATING_SCALE_ROUTE_AMBIGUOUS"


def test_workbench_service_persists_fixture_run_across_restart(tmp_path: Path) -> None:
    catalog_database = tmp_path / "catalog.sqlite3"
    social_database = tmp_path / "social.sqlite3"
    service = WorkbenchService(
        ROOT,
        catalog_database=catalog_database,
        social_database=social_database,
    )
    initialized = service.initialize_catalog()
    assert initialized["graph"]["participant_exposure_links"] == 0
    first = service.run_fixture_analysis()
    assert first["status"] == "completed_with_research_limits"
    assert first["result"]["data_origin"] == "synthetic"
    assert service.social_status()["health"] == "absent"

    restarted = WorkbenchService(
        ROOT,
        catalog_database=catalog_database,
        social_database=social_database,
    )
    second = restarted.run_fixture_analysis()
    assert second["analysis_run_id"] == first["analysis_run_id"]
    assert second["snapshot"] == first["snapshot"]
    assert second["result"] == first["result"]
    assert len(restarted.catalog.rows("analysis_runs")) == 1


def test_workbench_never_migrates_or_aliases_social_database(tmp_path: Path) -> None:
    same = tmp_path / "same.sqlite3"
    with pytest.raises(DatabaseBoundaryError, match="DATABASE_ROLES_MUST_BE_DISTINCT"):
        WorkbenchService(ROOT, catalog_database=same, social_database=same)

    social = tmp_path / "legacy-social.sqlite3"
    with sqlite3.connect(social) as connection:
        connection.execute("PRAGMA user_version = 14")
        connection.execute("CREATE TABLE legacy_social(id TEXT)")
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=social,
    )
    status = service.social_status()
    assert status["schema_version"] == 14
    assert status["migration_performed"] is False
    with sqlite3.connect(social) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
        assert {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } == {"legacy_social"}

    production = ROOT / "data/raw/social/glyph-social.sqlite3"
    with pytest.raises(DatabaseBoundaryError, match="PRODUCTION_SOCIAL_DATABASE_FORBIDDEN"):
        WorkbenchService(
            ROOT,
            catalog_database=tmp_path / "other.sqlite3",
            social_database=production,
        )


def test_formal_release_is_mechanically_blocked_while_demo_remains_labeled(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    run = service.run_fixture_analysis()
    demo = service.evaluate_release(run["analysis_run_id"], purpose="demo_export")
    assert demo["status"] == "demo_ready"
    assert demo["formal_release_eligible"] is False
    assert demo["data_origin"] == "synthetic"
    assert validate_record(demo, ROOT / "schema/release_candidate.schema.json") == []
    codes = {item["code"] for item in demo["formal_blockers"]}
    assert "RELEASE_SYNTHETIC_DATA_FORBIDDEN" in codes
    assert "WP3_INFERENCE_BLOCKED" in codes
    assert "WP4_INFERENCE_BLOCKED" in codes
    assert "HUMAN_GATE_UNRESOLVED:GATE-RELEASE" in codes

    with pytest.raises(ReleaseBlocked) as blocked:
        service.evaluate_release(run["analysis_run_id"], purpose="formal_release")
    assert blocked.value.candidate["status"] == "blocked"
    assert len(service.catalog.rows("release_candidates")) == 2


def test_demo_audit_package_is_complete_labeled_and_no_overwrite(tmp_path: Path) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    run = service.run_fixture_analysis()
    exported = service.export_demo(run["analysis_run_id"], tmp_path / "exports")
    directory = tmp_path / "exports" / exported["package_name"]
    required = {
        "analysis_plan.json",
        "analysis_run_manifest.json",
        "input_artifacts.json",
        "join_audit.json",
        "inclusion_exclusion_flow.json",
        "model_specification.json",
        "model_diagnostics.json",
        "effect_estimates.csv",
        "effect_estimates.json",
        "sensitivity_results.csv",
        "sensitivity_results.json",
        "limitations_zh.md",
        "gate_report.json",
        "checksums.sha256",
        "software_environment.json",
        "README_zh.md",
        "figures/native_match_effect.png",
    }
    assert required.issubset(
        {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}
    )
    assert exported["distribution_label"] == "SYNTHETIC / DEMO"
    assert exported["formal_release_eligible"] is False
    assert str(ROOT) not in "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix != ".png"
    )
    checksums = (directory / "checksums.sha256").read_text().splitlines()
    assert len(checksums) == len(required) - 1
    with pytest.raises(ExportError, match="DEMO_EXPORT_NO_OVERWRITE"):
        service.export_demo(run["analysis_run_id"], tmp_path / "exports")


def test_social_adapter_uses_validated_export_without_participant_exposure(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    service.initialize_catalog()
    attached = service.run_social_fixture(tmp_path / "social-exports")
    assert attached["distribution_label"] == "SYNTHETIC / DEMO"
    assert attached["quality_status"] == "passed"
    assert attached["release_allowed"] is False
    assert attached["narrative_count"] == 2
    assert service.social_status()["schema_version"] == 17
    assert service.social_status()["validated_export_count"] == 1

    links = service.catalog.rows("entity_links")
    assert sum(link["relation"] == "context_evidence_for_object" for link in links) == 2
    assert not any(link["relation"] == "participant_exposed_to_narrative" for link in links)
    social_artifact = next(
        row for row in service.catalog.rows("artifacts")
        if row["logical_type"] == "validated_narrative_export"
    )
    pointer = json.loads(social_artifact["pointer_json"])
    assert pointer["uri"].startswith("social-export://")
    assert str(tmp_path) not in social_artifact["pointer_json"]

    with pytest.raises(CatalogError, match="ARTIFACT_URI_NOT_ALLOWED"):
        service.catalog.register_artifact(
            {
                "module_id": "social",
                "logical_type": "unsafe",
                "uri": "file:///tmp/raw.json",
                "sha256": "a" * 64,
                "data_classification": "unsafe",
            }
        )


def test_social_export_adapter_rejects_reusing_an_existing_database(tmp_path: Path) -> None:
    database = tmp_path / "social.sqlite3"
    database.touch()
    with pytest.raises(CatalogError, match="SOCIAL_FIXTURE_REQUIRES_NEW_DATABASE"):
        SocialExportAdapter(database).create_fixture_export(tmp_path / "exports")


def test_coordinated_backup_restores_both_databases_to_new_paths(tmp_path: Path) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "live/catalog.sqlite3",
        social_database=tmp_path / "live/social.sqlite3",
    )
    run = service.run_fixture_analysis()
    service.run_social_fixture(tmp_path / "social-exports")
    backup = service.create_backup(tmp_path / "backups")
    assert backup["components"]["catalog"]["integrity_check"] == "ok"
    assert backup["components"]["social"]["schema_version"] == 17

    restored = service.restore_backup_drill(
        tmp_path / "backups",
        backup["backup_id"],
        target_catalog_database=tmp_path / "restore/catalog.sqlite3",
        target_social_database=tmp_path / "restore/social.sqlite3",
    )
    assert restored["restore_mode"] == "temporary_drill"
    assert restored["health"]["catalog_integrity"] == "ok"
    assert restored["health"]["social"]["integrity_check"] == "ok"
    restored_service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "restore/catalog.sqlite3",
        social_database=tmp_path / "restore/social.sqlite3",
    )
    assert restored_service.catalog.analysis_run(run["analysis_run_id"])["result"] == run["result"]
    assert restored_service.social_status()["validated_export_count"] == 1

    with pytest.raises(BackupError, match="RESTORE_TARGET_MUST_BE_NEW_TEMPORARY_PATH"):
        service.restore_backup_drill(
            tmp_path / "backups",
            backup["backup_id"],
            target_catalog_database=service.catalog_database,
            target_social_database=tmp_path / "another-social.sqlite3",
        )


def test_coordinated_restore_rejects_component_tampering(tmp_path: Path) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    service.run_fixture_analysis()
    service.run_social_fixture(tmp_path / "social-exports")
    backup = service.create_backup(tmp_path / "backups")
    directory = tmp_path / "backups" / backup["backup_id"]
    social_database = next((directory / "social").glob("backup_*/glyph-social.sqlite3"))
    with social_database.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(BackupError, match="COORDINATED_COMPONENT_CHECKSUM_MISMATCH"):
        service.restore_backup_drill(
            tmp_path / "backups",
            backup["backup_id"],
            target_catalog_database=tmp_path / "restore/catalog.sqlite3",
            target_social_database=tmp_path / "restore/social.sqlite3",
        )


def test_workbench_api_is_local_csrf_guarded_and_path_bounded(tmp_path: Path) -> None:
    app = create_app(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
    )
    assert app.state.scheduler_started is False
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session = client.get("/api/session")
        assert session.status_code == 200
        token = session.json()["csrf_token"]
        rejected = client.post("/api/actions/initialize")
        assert rejected.status_code == 403
        rejected_origin = client.post(
            "/api/actions/initialize",
            headers={"x-glyph-csrf": token, "origin": "https://example.test"},
        )
        assert rejected_origin.status_code == 403
        initialized = client.post(
            "/api/actions/initialize",
            headers={"x-glyph-csrf": token, "origin": "http://127.0.0.1"},
        )
        assert initialized.status_code == 200
        assert initialized.json()["handoff_count"] == 4
        health = client.get("/api/health").json()
        assert health["scheduler_started"] is False
        assert health["social"]["migration_performed"] is False
        serialized = json.dumps(health)
        assert str(tmp_path) not in serialized
        assert "GLYPH_YOUTUBE_API_KEY" not in serialized


def test_system_fixture_e2e_persists_audit_and_blocks_formal_release(
    tmp_path: Path,
) -> None:
    catalog_database = tmp_path / "catalog.sqlite3"
    social_database = tmp_path / "social.sqlite3"
    service = WorkbenchService(
        ROOT,
        catalog_database=catalog_database,
        social_database=social_database,
    )
    result = service.run_system_fixture(
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
    )
    assert result["distribution_label"] == "SYNTHETIC / DEMO"
    assert result["handoff_count"] == 4
    assert result["module_count"] == 6
    assert result["analysis_status"] == "completed_with_research_limits"
    assert result["social_quality_status"] == "passed"
    assert result["formal_release_status"] == "blocked"
    assert "RELEASE_SYNTHETIC_DATA_FORBIDDEN" in result["formal_blocker_codes"]
    assert (tmp_path / "exports/audit" / result["demo_archive_name"]).is_file()
    assert (tmp_path / "backups" / result["backup_id"] / "coordinated_manifest.json").is_file()

    restarted = WorkbenchService(
        ROOT,
        catalog_database=catalog_database,
        social_database=social_database,
    )
    assert restarted.catalog.analysis_run(result["analysis_run_id"])["result"] is not None
    assert restarted.social_status()["validated_export_count"] == 1
    assert any(
        row["status"] == "blocked"
        for row in restarted.catalog.rows("release_candidates")
    )


def test_cli_rejects_external_binding_before_starting_server(capsys) -> None:
    assert workbench_main(["serve", "--host", "0.0.0.0"]) == 2
    assert "EXTERNAL_BIND_REQUIRES_SEPARATE_APPROVAL" in capsys.readouterr().err


def test_coordinated_backup_cleans_partial_bundle_on_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_database = tmp_path / "catalog.sqlite3"
    social_database = tmp_path / "social.sqlite3"
    catalog_database.touch()
    social_database.touch()

    def fail_catalog_backup(_database: Path, _root: Path) -> dict:
        raise OSError("simulated no space left")

    monkeypatch.setattr(backup_module, "create_catalog_backup", fail_catalog_backup)
    with pytest.raises(OSError, match="simulated no space left"):
        backup_module.create_coordinated_backup(
            catalog_database,
            social_database,
            tmp_path / "backups",
        )
    assert list((tmp_path / "backups").glob("coordinated_*")) == []


def test_handoff_generation_cleans_rejected_package_and_never_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    output = tmp_path / "handoff"

    def fake_git(_root: Path, arguments: list[str], *, binary: bool = False):
        del binary
        if arguments == ["rev-parse", "HEAD"]:
            return commit + "\n"
        if arguments == ["status", "--porcelain"]:
            return ""
        raise AssertionError(arguments)

    monkeypatch.setattr(handoff_module, "_git", fake_git)
    monkeypatch.setattr(handoff_module, "build_manifest", lambda _root, _commit: {"outputs": []})
    monkeypatch.setattr(
        handoff_module,
        "_artifact",
        lambda _root, logical_type, path, record_count, classification, schema_version, source=None: {
            "logical_type": logical_type,
            "path": path,
            "sha256": "b" * 64,
            "record_count": record_count,
            "classification": classification,
            "schema_version": schema_version,
        },
    )
    monkeypatch.setattr(handoff_module, "validate_handoff", lambda _path, _root: ["REJECTED"])

    with pytest.raises(ValueError, match="HANDOFF_GENERATED_INVALID:REJECTED"):
        handoff_module.create_handoff(tmp_path, commit, output)
    assert not output.exists()
    assert list(tmp_path.glob(".handoff.*")) == []

    output.mkdir()
    marker = output / "owned.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="HANDOFF_OUTPUT_MUST_BE_NEW"):
        handoff_module.create_handoff(tmp_path, commit, output)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_database_failure_returns_stable_error_without_internal_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
    )

    def fail_integrity() -> str:
        raise sqlite3.OperationalError(f"database locked at {tmp_path}")

    monkeypatch.setattr(app.state.service.catalog, "integrity_check", fail_integrity)
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "DATABASE_BUSY_OR_UNAVAILABLE"}
    assert str(tmp_path) not in response.text


def test_long_operation_cancel_and_resume_preserves_completed_context() -> None:
    entered = threading.Event()
    release = threading.Event()

    def runner(checkpoint, context):
        checkpoint("first_stage")
        if "first_stage" not in context:
            context["first_stage"] = "preserved"
        entered.set()
        assert release.wait(timeout=5)
        checkpoint("second_stage")
        return {"context": context["first_stage"]}

    manager = OperationManager({"fixture": runner})
    try:
        submitted = manager.submit("fixture")
        assert entered.wait(timeout=5)
        canceled = manager.cancel(submitted["operation_id"])
        assert canceled["status"] == "cancel_requested"
        release.set()
        stopped = manager.wait(submitted["operation_id"])
        assert stopped["status"] == "canceled"
        assert stopped["result"] is None

        resumed = manager.resume(submitted["operation_id"])
        assert resumed["status"] in {"queued", "running"}
        completed = manager.wait(submitted["operation_id"])
        assert completed["status"] == "completed"
        assert completed["attempts"] == 2
        assert completed["result"] == {"context": "preserved"}
    finally:
        manager.shutdown()
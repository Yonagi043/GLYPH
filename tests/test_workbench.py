import copy
import hashlib
import json
import shutil
import sqlite3
import stat
import tempfile
import threading
import zipfile
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
from glyph_features.workbench.handoff_import import inspect_handoff_package
from glyph_features.workbench.social_adapter import register_social_export
import glyph_features.workbench.backups as backup_module
import glyph_features.workbench.handoff as handoff_module
import glyph_features.workbench.service as service_module
import glyph_features.workbench.snapshots as snapshot_module


ROOT = Path(__file__).resolve().parents[1]
TASK01_HANDOFF = Path(
    "data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json"
)


def _handoff_package(directory: Path) -> Path:
    manifest = json.loads((ROOT / TASK01_HANDOFF).read_text(encoding="utf-8"))
    paths = {TASK01_HANDOFF}
    for field in ("input_snapshots", "outputs"):
        paths.update(Path(item["path"]) for item in manifest[field])
    paths.update(
        Path(item["path"])
        for item in manifest["producer_provenance"]["files"]
    )
    paths.update(
        Path(item["packet_path"]) for item in manifest["blocked_human_gates"]
    )
    paths.update(
        Path(item["path"]) for item in manifest["next_task_entrypoints"]
    )
    paths.update(
        path.relative_to(ROOT)
        for path in (ROOT / TASK01_HANDOFF.parent).rglob("*")
        if path.is_file()
    )
    for relative in sorted(paths):
        source = ROOT / relative
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return directory


def _zip_package(package: Path, destination: Path) -> Path:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package).as_posix())
    return destination


def _catalog_import_state(catalog: Catalog) -> dict[str, list[dict]]:
    return {
        table: catalog.rows(table)
        for table in ("modules", "handoff_imports", "artifacts", "entity_links")
    }


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


def test_controlled_handoff_import_accepts_directory_and_zip_idempotently(
    tmp_path: Path,
) -> None:
    package = _handoff_package(tmp_path / "package")
    archive = _zip_package(package, tmp_path / "package.zip")

    for index, source in enumerate((package, archive)):
        service = WorkbenchService(
            ROOT,
            catalog_database=tmp_path / f"catalog-{index}.sqlite3",
            social_database=tmp_path / f"social-{index}.sqlite3",
        )
        imported = service.import_handoff(source)
        assert imported["task_id"] == "TASK-01"
        assert imported["module_id"] == "assets"
        assert imported["artifact_count"] == len(
            json.loads((ROOT / TASK01_HANDOFF).read_text(encoding="utf-8"))["outputs"]
        )
        assert imported["entity_link_count"] == imported["artifact_count"]
        before = _catalog_import_state(service.catalog)
        assert service.import_handoff(source) == imported
        assert _catalog_import_state(service.catalog) == before


def test_controlled_handoff_import_rejects_archives_before_catalog_mutation(
    tmp_path: Path,
) -> None:
    package = _handoff_package(tmp_path / "package")
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    baseline = _catalog_import_state(service.catalog)

    slip = tmp_path / "slip.zip"
    with zipfile.ZipFile(slip, "w") as archive:
        archive.writestr("../escaped.json", "{}")
    with pytest.raises(CatalogError, match="HANDOFF_ZIP_PATH_INVALID"):
        service.import_handoff(slip)

    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("handoff_manifest.json", "{}")
            archive.writestr("handoff_manifest.json", "{}")
    with pytest.raises(CatalogError, match="HANDOFF_ZIP_DUPLICATE_MEMBER"):
        service.import_handoff(duplicate)

    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_FILE_COUNT_EXCEEDED"):
        service.import_handoff(package, max_files=1)
    assert _catalog_import_state(service.catalog) == baseline


def test_controlled_handoff_import_rejects_paths_links_and_size_limits(
    tmp_path: Path,
) -> None:
    package = _handoff_package(tmp_path / "package")
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    baseline = _catalog_import_state(service.catalog)

    absolute = tmp_path / "absolute.zip"
    with zipfile.ZipFile(absolute, "w") as archive:
        archive.writestr("/absolute/handoff_manifest.json", "{}")
    with pytest.raises(CatalogError, match="HANDOFF_ZIP_PATH_INVALID"):
        service.import_handoff(absolute)

    symlink_archive = tmp_path / "symlink.zip"
    symlink = zipfile.ZipInfo("handoff-link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink_archive, "w") as archive:
        archive.writestr(symlink, "handoff_manifest.json")
    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_SYMLINK_FORBIDDEN"):
        service.import_handoff(symlink_archive)

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    directory_symlink = package / "outside-link"
    directory_symlink.symlink_to(outside)
    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_SYMLINK_FORBIDDEN"):
        service.import_handoff(package)
    directory_symlink.unlink()

    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_FILE_SIZE_EXCEEDED"):
        service.import_handoff(package, max_file_size=1)
    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_TOTAL_SIZE_EXCEEDED"):
        service.import_handoff(package, max_file_size=2**30, max_total_size=1)
    assert _catalog_import_state(service.catalog) == baseline


def test_controlled_handoff_import_preserves_task_path_immutability(
    tmp_path: Path,
) -> None:
    package = _handoff_package(tmp_path / "package")
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    result, pointers = inspect_handoff_package(package, ROOT)
    descriptor = build_module_descriptors([result])[0]
    service.catalog.import_validated_handoff(descriptor, result, pointers)
    baseline = _catalog_import_state(service.catalog)

    conflicting = {**result, "manifest_sha256": "f" * 64}
    with pytest.raises(CatalogConflict, match="HANDOFF_IMMUTABLE_CONFLICT"):
        service.catalog.import_validated_handoff(descriptor, conflicting, pointers)
    assert _catalog_import_state(service.catalog) == baseline


def test_controlled_handoff_import_rejects_schema_and_rehashed_payload_tamper(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    baseline = _catalog_import_state(service.catalog)

    unsupported = _handoff_package(tmp_path / "unsupported")
    manifest_path = unsupported / TASK01_HANDOFF
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["handoff_schema_version"] = "999.0.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogError, match="HANDOFF_VERSION_UNSUPPORTED"):
        service.import_handoff(unsupported)

    tampered = _handoff_package(tmp_path / "tampered")
    manifest_path = tampered / TASK01_HANDOFF
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_path = tampered / manifest["outputs"][0]["path"]
    output_path.write_bytes(output_path.read_bytes() + b"\n")
    manifest["outputs"][0]["sha256"] = hashlib.sha256(
        output_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CatalogError, match="HANDOFF_PACKAGE_MANIFEST_NOT_TRUSTED"):
        service.import_handoff(tampered)
    assert _catalog_import_state(service.catalog) == baseline


def test_controlled_handoff_import_rolls_back_mid_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _handoff_package(tmp_path / "package")
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    baseline = _catalog_import_state(service.catalog)

    def fail_link(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected import failure")

    monkeypatch.setattr(service.catalog, "_insert_import_link", fail_link)
    with pytest.raises(sqlite3.OperationalError, match="injected import failure"):
        service.import_handoff(package)
    assert _catalog_import_state(service.catalog) == baseline


def test_controlled_handoff_import_is_available_through_cli_and_api(
    tmp_path: Path,
    capsys,
) -> None:
    package = _handoff_package(tmp_path / "package")
    catalog_database = tmp_path / "catalog.sqlite3"
    social_database = tmp_path / "social.sqlite3"
    assert workbench_main(
        [
            "import-handoff",
            str(package),
            "--catalog-database",
            str(catalog_database),
            "--social-database",
            str(social_database),
        ]
    ) == 0
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result["task_id"] == "TASK-01"
    assert cli_result["compatible"] is True

    app = create_app(
        ROOT,
        catalog_database=catalog_database,
        social_database=social_database,
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        token = client.get("/api/session").json()["csrf_token"]
        response = client.post(
            "/api/actions/import-handoff",
            headers={"x-glyph-csrf": token, "origin": "http://127.0.0.1"},
            json={"source": str(package)},
        )
    assert response.status_code == 200
    assert response.json()["task_id"] == "TASK-01"


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


def test_analysis_snapshot_rejects_origin_commit_and_dirty_producer(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    initialized = service.initialize_catalog()
    arguments = {
        "catalog": service.catalog,
        "workspace_root": ROOT,
        "plan_revision_id": initialized["plan"]["plan_revision_id"],
        "artifact_ids": service._analysis_input_artifacts(),
        "random_seed": 20260904,
    }

    with pytest.raises(CatalogError, match="SNAPSHOT_DATA_ORIGIN_MISMATCH"):
        freeze_analysis_snapshot(**arguments, data_origin="real")
    with pytest.raises(CatalogError, match="SNAPSHOT_GIT_COMMIT_INVALID"):
        freeze_analysis_snapshot(
            **arguments,
            data_origin="synthetic",
            git_commit="0" * 40,
        )
    with pytest.raises(CatalogError, match="SNAPSHOT_GIT_WORKTREE_DIRTY"):
        freeze_analysis_snapshot(**arguments, data_origin="synthetic")
    assert service.catalog.rows("analysis_runs") == []


def test_existing_v1_snapshot_is_retrieved_immutably_for_explicit_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    initialized = service.initialize_catalog()
    artifact_ids = service._analysis_input_artifacts()
    commit = snapshot_module._git_text(
        ROOT,
        "rev-parse",
        "HEAD",
        error_code="TEST_GIT_HEAD_INVALID",
    )
    original_provenance = snapshot_module._git_provenance
    monkeypatch.setattr(
        snapshot_module,
        "_git_provenance",
        lambda *_args, **_kwargs: {
            "git_commit": commit,
            "git_head": commit,
            "git_object_type": "commit",
            "git_clean": True,
            "repository_scope": "workspace_root",
        },
    )
    generated = freeze_analysis_snapshot(
        service.catalog,
        ROOT,
        plan_revision_id=initialized["plan"]["plan_revision_id"],
        artifact_ids=artifact_ids,
        data_origin="synthetic",
        random_seed=20260904,
    )
    legacy = copy.deepcopy(generated)
    legacy["schema_version"] = "1.0.0"
    legacy.pop("data_classifications")
    for key in ("git_head", "git_object_type", "git_clean", "repository_scope"):
        legacy["software_environment"].pop(key)
    core = {
        key: value
        for key, value in legacy.items()
        if key not in {"analysis_run_id", "created_at", "snapshot_sha256"}
    }
    legacy["snapshot_sha256"] = hashlib.sha256(
        snapshot_module.canonical_json(core)
    ).hexdigest()
    legacy["analysis_run_id"] = snapshot_module.stable_id("analysis", core)
    service.catalog.register_analysis_run(legacy)
    monkeypatch.setattr(snapshot_module, "_git_provenance", original_provenance)

    repeated = freeze_analysis_snapshot(
        service.catalog,
        ROOT,
        plan_revision_id=initialized["plan"]["plan_revision_id"],
        artifact_ids=reversed(artifact_ids),
        data_origin="synthetic",
        random_seed=20260904,
        git_commit=commit,
    )
    assert repeated == legacy
    assert len(service.catalog.rows("analysis_runs")) == 2


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


def test_social_export_package_binds_every_final_payload(tmp_path: Path) -> None:
    export_root = tmp_path / "exports"
    result = SocialExportAdapter(tmp_path / "social.sqlite3").create_fixture_export(
        export_root
    )
    export_directory = next(path for path in export_root.iterdir() if path.is_dir())
    package_manifest = json.loads(
        (export_directory / "package_manifest.json").read_text(encoding="utf-8")
    )
    payload_paths = {
        path.relative_to(export_directory).as_posix()
        for path in export_directory.rglob("*")
        if path.is_file() and path.name != "package_manifest.json"
    }
    assert package_manifest["schema_version"] == "social-export-package-v1"
    assert package_manifest["data_origin"] == "synthetic"
    assert package_manifest["collection_run_id"] == result["collection_run_id"]
    assert package_manifest["narrative_count"] == result["narrative_count"]
    assert {item["path"] for item in package_manifest["files"]} == payload_paths


def test_social_export_adapter_rejects_payload_and_rehashed_id_tamper(
    tmp_path: Path,
) -> None:
    export_root = tmp_path / "exports"
    adapter = SocialExportAdapter(tmp_path / "social.sqlite3")
    adapter.create_fixture_export(export_root)
    export_directory = next(path for path in export_root.iterdir() if path.is_dir())
    narratives_path = export_directory / "narratives.jsonl"
    original_narratives = narratives_path.read_text(encoding="utf-8")
    narratives = [json.loads(line) for line in original_narratives.splitlines()]
    narratives[0]["evidence_span"] += " tampered"
    narratives_path.write_text(
        "\n".join(json.dumps(item) for item in narratives) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="SOCIAL_EXPORT_FILE_HASH_MISMATCH"):
        adapter.validate_export(export_directory, expected_data_origin="synthetic")

    narratives_path.write_text(original_narratives, encoding="utf-8")
    narratives = [json.loads(line) for line in original_narratives.splitlines()]
    narratives[0]["evidence_id"] = "ev_social_" + "0" * 32
    narratives_path.write_text(
        "\n".join(json.dumps(item) for item in narratives) + "\n",
        encoding="utf-8",
    )
    package_path = export_directory / "package_manifest.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    narrative_record = next(
        item for item in package["files"] if item["path"] == "narratives.jsonl"
    )
    narrative_record["sha256"] = hashlib.sha256(narratives_path.read_bytes()).hexdigest()
    narrative_record["byte_size"] = narratives_path.stat().st_size
    package_path.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(CatalogError, match="SOCIAL_EXPORT_NARRATIVE_SEMANTICS_INVALID"):
        adapter.validate_export(export_directory, expected_data_origin="synthetic")


def test_register_social_export_preserves_real_data_classification(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    service.initialize_catalog()
    registered = register_social_export(
        service.catalog,
        {
            "data_origin": "real",
            "collection_run_id": "social_run_test_real",
            "narrative_count": 0,
            "files": {
                "narratives.jsonl": {"sha256": "a" * 64, "byte_size": 0},
                "package_manifest.json": {"sha256": "b" * 64, "byte_size": 1},
            },
            "narratives": [],
        },
    )
    artifact = next(
        row
        for row in service.catalog.rows("artifacts")
        if row["artifact_id"] == registered["artifact_id"]
    )
    assert json.loads(artifact["pointer_json"])["data_classification"] == (
        "restricted_real_data"
    )


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
    assert backup["components"]["catalog"]["counts"]["operations"] == 0
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
            json={"confirmation_phrase": "INITIALIZE CATALOG"},
        )
        assert initialized.status_code == 200
        assert initialized.json()["handoff_count"] == 4
        health = client.get("/api/health").json()
        assert health["scheduler_started"] is False
        assert health["social"]["migration_performed"] is False
        serialized = json.dumps(health)
        assert str(tmp_path) not in serialized
        assert "GLYPH_YOUTUBE_API_KEY" not in serialized


def test_csrf_token_is_single_use_and_expires(tmp_path: Path) -> None:
    current_time = [100.0]
    app = create_app(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
        csrf_ttl_seconds=5,
        csrf_clock=lambda: current_time[0],
    )
    origin = "http://127.0.0.1"
    with TestClient(app, base_url=origin) as client:
        token = client.get("/api/session").json()["csrf_token"]
        headers = {"x-glyph-csrf": token, "origin": origin}
        payload = {"confirmation_phrase": "INITIALIZE CATALOG"}
        assert client.post(
            "/api/actions/initialize", headers=headers, json=payload
        ).status_code == 200
        replay = client.post(
            "/api/actions/initialize", headers=headers, json=payload
        )
        assert replay.status_code == 403
        assert replay.json() == {"detail": "CSRF_TOKEN_INVALID"}

        expired = client.get("/api/session").json()["csrf_token"]
        current_time[0] += 6
        response = client.post(
            "/api/actions/initialize",
            headers={"x-glyph-csrf": expired, "origin": origin},
            json=payload,
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "CSRF_TOKEN_INVALID"}


def test_restore_drill_requires_server_verified_confirmation_phrase(
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
    monkeypatch.setattr(
        app.state.service,
        "restore_backup_drill",
        lambda *_args, **_kwargs: {
            "backup_id": "coordinated_20260904T000000Z_1234abcd",
            "restore_mode": "temporary_drill",
            "health": {
                "catalog_integrity": "ok",
                "social": {"integrity_check": "ok"},
            },
        },
    )
    origin = "http://127.0.0.1"
    backup_id = "coordinated_20260904T000000Z_1234abcd"
    with TestClient(app, base_url=origin) as client:
        def post(payload):
            token = client.get("/api/session").json()["csrf_token"]
            return client.post(
                "/api/actions/restore-drill",
                headers={"x-glyph-csrf": token, "origin": origin},
                json=payload,
            )

        assert post({"backup_id": backup_id}).status_code == 422
        assert post(
            {"backup_id": backup_id, "confirmation_phrase": "restore drill"}
        ).status_code == 422
        accepted = post(
            {"backup_id": backup_id, "confirmation_phrase": "RESTORE DRILL"}
        )
    assert accepted.status_code == 200
    assert accepted.json()["restore_mode"] == "temporary_drill"


def test_dangerous_actions_require_server_verified_confirmation_phrases(
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
    monkeypatch.setattr(
        app.state.service,
        "create_backup",
        lambda *_args, **_kwargs: {"backup_id": "confirmed-backup"},
    )
    monkeypatch.setattr(
        app.state.service,
        "initialize_catalog",
        lambda: {
            "handoffs": [],
            "modules": [],
            "graph": {"artifact_count": 0, "entity_link_count": 0},
        },
    )
    monkeypatch.setattr(
        app.state.service,
        "export_demo",
        lambda *_args, **_kwargs: {"status": "demo_exported"},
    )
    monkeypatch.setattr(
        app.state.service,
        "evaluate_release",
        lambda *_args, **_kwargs: {"status": "blocked", "formal_blockers": []},
    )
    monkeypatch.setattr(
        app.state.operations,
        "submit",
        lambda kind: {"operation_id": f"operation_{kind}", "status": "queued"},
    )
    monkeypatch.setattr(
        app.state.operations,
        "cancel",
        lambda operation_id: {
            "operation_id": operation_id,
            "status": "cancel_requested",
        },
    )
    monkeypatch.setattr(
        app.state.operations,
        "resume",
        lambda operation_id: {"operation_id": operation_id, "status": "queued"},
    )
    origin = "http://127.0.0.1"
    operation_id = "operation_" + "a" * 24

    with TestClient(app, base_url=origin) as client:
        def post(
            path: str,
            confirmation_phrase: str | None,
            extra: dict[str, str] | None = None,
        ):
            token = client.get("/api/session").json()["csrf_token"]
            payload = dict(extra or {})
            if confirmation_phrase is not None:
                payload["confirmation_phrase"] = confirmation_phrase
            return client.post(
                path,
                headers={"x-glyph-csrf": token, "origin": origin},
                json=payload,
            )

        analysis_run_id = "analysis_" + "b" * 24
        cases = (
            ("/api/actions/initialize", "INITIALIZE CATALOG", 200, {}),
            ("/api/actions/backup", "CREATE BACKUP", 200, {}),
            ("/api/operations/analysis-fixture", "RUN ANALYSIS FIXTURE", 202, {}),
            ("/api/operations/system-fixture", "RUN SYSTEM FIXTURE", 202, {}),
            (
                "/api/actions/export-demo",
                "EXPORT DEMO",
                200,
                {"analysis_run_id": analysis_run_id},
            ),
            (
                "/api/actions/check-formal-release",
                "CHECK FORMAL RELEASE",
                200,
                {"analysis_run_id": analysis_run_id},
            ),
            (
                f"/api/operations/{operation_id}/cancel",
                "STOP OPERATION",
                200,
                {},
            ),
            (
                f"/api/operations/{operation_id}/resume",
                "RESUME OPERATION",
                202,
                {},
            ),
        )
        for path, phrase, accepted_status, extra in cases:
            assert post(path, None, extra).status_code == 422
            rejected = post(path, "WRONG PHRASE", extra)
            assert rejected.status_code == 422
            assert rejected.json() == {"detail": "CONFIRMATION_PHRASE_INVALID"}
            assert post(path, phrase, extra).status_code == accepted_status


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


def test_coordinated_backup_never_migrates_v14_social_source(tmp_path: Path) -> None:
    catalog_database = tmp_path / "catalog.sqlite3"
    social_database = tmp_path / "social.sqlite3"
    Catalog(catalog_database)
    SocialExportAdapter(social_database).create_fixture_export(tmp_path / "exports")
    with sqlite3.connect(social_database) as connection:
        connection.execute("PRAGMA user_version = 14")
    before_sha256 = hashlib.sha256(social_database.read_bytes()).hexdigest()
    before_stat = social_database.stat()
    with sqlite3.connect(f"file:{social_database}?mode=ro", uri=True) as connection:
        before_version = connection.execute("PRAGMA user_version").fetchone()[0]
        before_tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

    assert not hasattr(backup_module, "SocialNarrativeService")
    with pytest.raises(
        BackupError, match="SOCIAL_BACKUP_SOURCE_SCHEMA_UNSUPPORTED"
    ):
        backup_module.create_coordinated_backup(
            catalog_database,
            social_database,
            tmp_path / "backups",
        )

    after_stat = social_database.stat()
    assert hashlib.sha256(social_database.read_bytes()).hexdigest() == before_sha256
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
    with sqlite3.connect(f"file:{social_database}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == before_version
        assert connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall() == before_tables
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


def test_handoff_reconstructs_compatibility_readiness_and_gate_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = handoff_module._git(ROOT, ["rev-parse", "HEAD"]).strip()
    producer_files = [
        {
            "role": handoff_module._role(relative),
            "path": relative,
            "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
        }
        for relative in handoff_module._committed_paths(ROOT, commit)
    ]
    monkeypatch.setattr(
        handoff_module,
        "_producer_files",
        lambda _root, _commit: producer_files,
    )
    manifest = handoff_module.build_manifest(ROOT, commit)
    with tempfile.TemporaryDirectory(
        prefix="task05-handoff-semantic-", dir=ROOT / "data/releases"
    ) as temporary:
        package = Path(temporary)
        report = package / "TASK_05_REPORT_zh.md"
        report.write_text("# Temporary TASK-05 semantic attack fixture\n", encoding="utf-8")
        report_relative = report.relative_to(ROOT).as_posix()
        manifest["outputs"] = [
            handoff_module._artifact(
                ROOT,
                logical_type,
                report_relative if logical_type == "task_report" else output_path,
                record_count,
                classification,
                schema_version,
                report if logical_type == "task_report" else None,
            )
            for (
                logical_type,
                output_path,
                record_count,
                classification,
                schema_version,
            ) in handoff_module.OUTPUT_SPECS
        ]

        next(
            item
            for item in manifest["module_compatibility"]
            if item["module_id"] == "assets"
        )["readiness"]["pilot_ready"] = True
        next(
            item
            for item in manifest["input_handoffs"]
            if item["task_id"] == "TASK-01"
        )["readiness"]["research_validated"] = True
        manifest["blocked_human_gates"] = [
            gate
            for gate in manifest["blocked_human_gates"]
            if not (gate["module_id"] == "assets" and gate["gate_id"] == "GATE-RIGHTS")
        ]
        next(
            gate
            for gate in manifest["quality_gates"]
            if gate["gate_id"] == "SYNTHETIC_E2E"
        )["evidence"] = "Claimed passing evidence without the required result."
        manifest["interfaces"]["write_endpoints"] = ["/api/actions/initialize"]
        manifest["validation_evidence"]["commands"][0]["result"] = (
            "Claimed success without the required suite result."
        )

        manifest_path = package / "handoff_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (package / "checksums.sha256").write_text(
            "\n".join(
                (
                    f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  handoff_manifest.json",
                    f"{hashlib.sha256(report.read_bytes()).hexdigest()}  TASK_05_REPORT_zh.md",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        errors = handoff_module.validate_handoff(manifest_path, ROOT)

    assert "HANDOFF_MODULE_COMPATIBILITY_SEMANTICS_INVALID" in errors
    assert "HANDOFF_INPUT_SEMANTICS_INVALID" in errors
    assert "HANDOFF_BLOCKED_GATES_SEMANTICS_INVALID" in errors
    assert "HANDOFF_QUALITY_GATE_SEMANTICS_INVALID" in errors
    assert "HANDOFF_INTERFACE_SEMANTICS_INVALID" in errors
    assert "HANDOFF_VALIDATION_EVIDENCE_SEMANTICS_INVALID" in errors
    assert not any(error.startswith("HANDOFF_PACKAGE_SHA256_MISMATCH") for error in errors)


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


def test_analysis_failure_persists_audit_and_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_database = tmp_path / "catalog.sqlite3"
    service = WorkbenchService(
        ROOT,
        catalog_database=catalog_database,
        social_database=tmp_path / "social.sqlite3",
    )
    service.initialize_catalog()

    def frozen_snapshot(catalog, _root, **arguments):
        snapshot = {
            "analysis_run_id": "analysis_" + "1" * 24,
            "plan_revision_id": arguments["plan_revision_id"],
            "snapshot_sha256": "a" * 64,
            "data_origin": arguments["data_origin"],
            "created_at": "2026-09-04T00:00:00Z",
        }
        catalog.register_analysis_run(snapshot)
        return snapshot

    monkeypatch.setattr(service_module, "freeze_analysis_snapshot", frozen_snapshot)
    monkeypatch.setattr(
        service_module,
        "build_synthetic_analysis_table",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("ANALYSIS_INJECTED_FAILURE: private detail")
        ),
    )
    with pytest.raises(RuntimeError, match="ANALYSIS_INJECTED_FAILURE"):
        service.run_fixture_analysis()

    failed = service.catalog.analysis_run("analysis_" + "1" * 24)
    assert failed["status"] == "failed"
    assert failed["failure"] == {
        "error_code": "ANALYSIS_INJECTED_FAILURE",
        "stage": "build_analysis_table",
        "diagnostic_summary": (
            "Analysis did not complete during build_analysis_table; "
            "no result was persisted."
        ),
    }
    assert any(
        row["event_type"] == "analysis_run_failed"
        for row in service.catalog.rows("audit_events")
    )

    app = create_app(
        ROOT,
        catalog_database=catalog_database,
        social_database=tmp_path / "social.sqlite3",
        export_root=tmp_path / "exports",
        backup_root=tmp_path / "backups",
        restore_root=tmp_path / "restores",
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").json()["failed_task_count"] == 1
        run = client.get("/api/analysis").json()["runs"][0]
    assert run["failure"] == failed["failure"]
    assert "private detail" not in json.dumps(run)


def test_operation_checkpoint_survives_restart_and_resume(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "catalog.sqlite3")

    def fail_after_attach(checkpoint, context):
        context["attach_social_export"] = {"quality_status": "passed"}
        checkpoint("attach_social_export_completed")
        raise RuntimeError("OPERATION_TEST_FAILURE")

    first = OperationManager({"system_fixture": fail_after_attach}, catalog=catalog)
    submitted = first.submit("system_fixture")
    failed = first.wait(submitted["operation_id"])
    first.shutdown()
    assert failed["status"] == "failed"
    assert failed["stage"] == "attach_social_export_completed"
    assert failed["error_code"] == "OPERATION_TEST_FAILURE"

    def recover(_checkpoint, context):
        return {"quality_status": context["attach_social_export"]["quality_status"]}

    restarted = OperationManager({"system_fixture": recover}, catalog=catalog)
    try:
        restored = restarted.get(submitted["operation_id"])
        assert restored["status"] == "failed"
        restarted.resume(submitted["operation_id"])
        completed = restarted.wait(submitted["operation_id"])
        assert completed["status"] == "completed"
        assert completed["attempts"] == 2
        assert completed["result"] == {"quality_status": "passed"}
    finally:
        restarted.shutdown()

    final = OperationManager({"system_fixture": recover}, catalog=catalog)
    try:
        assert final.get(submitted["operation_id"]) == completed
    finally:
        final.shutdown()


def test_social_attach_recovers_from_completed_public_export(tmp_path: Path) -> None:
    export_root = tmp_path / "exports" / "social"
    service = WorkbenchService(
        ROOT,
        catalog_database=tmp_path / "catalog.sqlite3",
        social_database=tmp_path / "social.sqlite3",
    )
    service.initialize_catalog()
    SocialExportAdapter(service.social_database).create_fixture_export(export_root)
    assert service.social_status()["validated_export_count"] == 0

    attached = service.attach_existing_social_fixture_export(export_root)
    assert attached["quality_status"] == "passed"
    assert attached["release_allowed"] is False
    assert attached["narrative_count"] == 2
    assert service.social_status()["validated_export_count"] == 1
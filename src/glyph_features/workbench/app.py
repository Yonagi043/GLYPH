"""Local-only FastAPI surface for the composed GLYPH workbench."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backups import BackupError
from .catalog import CatalogError
from .gates import ReleaseBlocked
from .releases import ExportError
from .service import DatabaseBoundaryError, WorkbenchService
from .operations import OperationError, OperationManager
from .materials import MaterialCatalog
from .research import FontSampleConfig, MaterialSelection, ResearchAssessment, ResearchService, StudyConfig
from .personas import PersonaExecutor
from .research_results import analyze_research, export_research


STATIC_DIR = Path(__file__).with_name("static")
SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,159}$"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ViewName(str, Enum):
    assets = "assets"
    vision = "vision"
    experiment = "experiment"
    social = "social"
    han_style = "han_style"


class RunInput(BaseModel):
    analysis_run_id: str = Field(pattern=SAFE_ID)
    confirmation_phrase: str | None = Field(default=None, max_length=64)


class ConfirmationInput(BaseModel):
    confirmation_phrase: str | None = Field(default=None, max_length=64)


class BackupInput(BaseModel):
    backup_id: str = Field(
        pattern=r"^coordinated_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$"
    )
    confirmation_phrase: Literal["RESTORE DRILL"]


class HandoffImportInput(BaseModel):
    source: str = Field(min_length=1, max_length=4096)


def _require_confirmation(
    payload: ConfirmationInput | RunInput | None, expected: str
) -> None:
    if payload is None or payload.confirmation_phrase != expected:
        raise HTTPException(status_code=422, detail="CONFIRMATION_PHRASE_INVALID")


class CsrfTokenStore:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        clock: Callable[[], float],
        max_tokens: int = 4096,
    ):
        if ttl_seconds <= 0 or max_tokens <= 0:
            raise ValueError("CSRF_TOKEN_STORE_CONFIGURATION_INVALID")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._max_tokens = max_tokens
        self._tokens: dict[str, float] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        expired = [token for token, deadline in self._tokens.items() if deadline < now]
        for token in expired:
            self._tokens.pop(token, None)

    def issue(self) -> str:
        now = self._clock()
        with self._lock:
            self._prune(now)
            while len(self._tokens) >= self._max_tokens:
                self._tokens.pop(next(iter(self._tokens)))
            token = secrets.token_urlsafe(32)
            self._tokens[token] = now + self._ttl_seconds
        return token

    def consume(self, token: str) -> bool:
        now = self._clock()
        with self._lock:
            self._prune(now)
            deadline = self._tokens.pop(token, None)
        return deadline is not None and deadline >= now


def _json_field(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key)
    return json.loads(value) if isinstance(value, str) else {}


def _module_descriptors(service: WorkbenchService) -> list[dict[str, Any]]:
    return sorted(
        (_json_field(row, "descriptor_json") for row in service.catalog.rows("modules")),
        key=lambda item: item["module_id"],
    )


def _artifact(row: dict[str, Any]) -> dict[str, Any]:
    pointer = _json_field(row, "pointer_json")
    return {
        "artifact_id": row["artifact_id"],
        "module_id": row["module_id"],
        "logical_type": row["logical_type"],
        "location": pointer.get("path") or pointer.get("uri"),
        "sha256": row["sha256"],
        "schema_version": row["schema_version"],
        "data_classification": row["data_classification"],
        "rights_tier": row["rights_tier"],
        "privacy_level": row["privacy_level"],
        "record_count": pointer.get("record_count"),
    }


def _link(row: dict[str, Any]) -> dict[str, Any]:
    link = _json_field(row, "link_json")
    return {"link_id": row["link_id"], **link}


def _module_view(service: WorkbenchService, module_id: str) -> dict[str, Any]:
    descriptor = next(
        (item for item in _module_descriptors(service) if item["module_id"] == module_id),
        None,
    )
    artifacts = [
        _artifact(row)
        for row in service.catalog.rows("artifacts")
        if row["module_id"] == module_id
    ]
    links = [
        _link(row)
        for row in service.catalog.rows("entity_links")
        if row["source_module"] == module_id or row["target_module"] == module_id
    ]
    return {
        "distribution_label": "SYNTHETIC / DEMO",
        "module": descriptor,
        "artifact_count": len(artifacts),
        "relationship_count": len(links),
        "artifacts": artifacts[:200],
        "relationships": links[:300],
    }


def _analysis_view(service: WorkbenchService) -> dict[str, Any]:
    plans = []
    for row in service.catalog.rows("analysis_plans"):
        plan = _json_field(row, "plan_json")
        plans.append(
            {
                "plan_revision_id": row["plan_revision_id"],
                "plan_id": row["plan_id"],
                "version": row["version"],
                "status": row["status"],
                "plan_sha256": row["plan_sha256"],
                "analysis_unit": plan.get("analysis_unit"),
                "model": plan.get("model"),
            }
        )
    runs = []
    for row in service.catalog.rows("analysis_runs"):
        result = _json_field(row, "result_json")
        failure = _json_field(row, "failure_json")
        runs.append(
            {
                "analysis_run_id": row["analysis_run_id"],
                "plan_revision_id": row["plan_revision_id"],
                "snapshot_sha256": row["snapshot_sha256"],
                "status": row["status"],
                "data_origin": row["data_origin"],
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
                "work_packages": result.get("work_packages"),
                "model_diagnostics": result.get("model_diagnostics"),
                "effect_estimates": result.get("effect_estimates"),
                "join_audit": result.get("join_audit"),
                "limitations": result.get("limitations"),
                "failure": failure or None,
            }
        )
    return {
        "distribution_label": "SYNTHETIC / DEMO",
        "plans": plans,
        "runs": runs,
    }


def _audit_view(service: WorkbenchService, backup_root: Path) -> dict[str, Any]:
    releases = [
        _json_field(row, "manifest_json")
        for row in service.catalog.rows("release_candidates")
    ]
    events = [
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "summary": _json_field(row, "summary_json"),
            "occurred_at": row["occurred_at"],
        }
        for row in reversed(service.catalog.rows("audit_events")[-200:])
    ]
    backups = []
    for path in sorted(
        backup_root.glob("coordinated_*/coordinated_manifest.json"), reverse=True
    ):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        backups.append(
            {
                "backup_id": manifest.get("backup_id"),
                "completed_at": manifest.get("completed_at"),
                "consistency_model": manifest.get("consistency_model"),
                "components": manifest.get("components"),
            }
        )
    return {
        "distribution_label": "SYNTHETIC / DEMO",
        "release_candidates": releases,
        "backups": backups,
        "audit_events": events,
    }


def _credential_status() -> dict[str, bool]:
    return {
        "youtube": bool(os.environ.get("GLYPH_YOUTUBE_API_KEY")),
        "mastodon": bool(os.environ.get("GLYPH_MASTODON_ACCESS_TOKENS_JSON")),
        "reddit": all(
            os.environ.get(name)
            for name in (
                "GLYPH_REDDIT_CLIENT_ID",
                "GLYPH_REDDIT_CLIENT_SECRET",
                "GLYPH_REDDIT_REFRESH_TOKEN",
                "GLYPH_REDDIT_USER_AGENT",
            )
        ),
        "tiktok": all(
            os.environ.get(name)
            for name in ("GLYPH_TIKTOK_CLIENT_KEY", "GLYPH_TIKTOK_CLIENT_SECRET")
        ),
        "x": bool(os.environ.get("GLYPH_X_BEARER_TOKEN")),
    }


def _is_local_origin(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
    )


def create_app(
    workspace_root: str | Path,
    *,
    catalog_database: str | Path,
    social_database: str | Path,
    export_root: str | Path,
    backup_root: str | Path,
    restore_root: str | Path,
    material_root: str | Path | None = None,
    csrf_ttl_seconds: float = 300,
    csrf_clock: Callable[[], float] | None = None,
) -> FastAPI:
    service = WorkbenchService(
        workspace_root,
        catalog_database=catalog_database,
        social_database=social_database,
    )
    exports = Path(export_root).expanduser().resolve()
    backups = Path(backup_root).expanduser().resolve()
    restores = Path(restore_root).expanduser().resolve()
    csrf_tokens = CsrfTokenStore(
        ttl_seconds=csrf_ttl_seconds,
        clock=csrf_clock or time.monotonic,
    )

    def analysis_operation(checkpoint, _context) -> dict[str, Any]:
        checkpoint("run_analysis")
        run = service.run_fixture_analysis()
        checkpoint("run_analysis_completed")
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "analysis_run_id": run["analysis_run_id"],
            "status": run["status"],
        }

    operations = OperationManager(
        {
            "analysis_fixture": analysis_operation,
            "system_fixture": lambda checkpoint, context: service.run_system_fixture(
                export_root=exports,
                backup_root=backups,
                checkpoint=checkpoint,
                completed_steps=context,
            ),
        },
        catalog=service.catalog,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        operations.shutdown()

    app = FastAPI(
        title="GLYPH 统一研究工作台",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.csrf_tokens = csrf_tokens
    app.state.scheduler_started = False
    app.state.operations = operations
    app.state.materials = MaterialCatalog(material_root) if material_root else None
    app.state.research = ResearchService(service.catalog, app.state.materials, service.workspace_root) if app.state.materials else None
    app.state.personas = PersonaExecutor(app.state.research) if app.state.research else None
    app.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR, check_dir=False),
        name="static",
    )

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-glyph-csrf", "")
            if not _is_local_origin(request.headers.get("origin")):
                return JSONResponse(
                    {"detail": "LOCAL_ORIGIN_REQUIRED"}, status_code=403
                )
            if not csrf_tokens.consume(supplied):
                return JSONResponse({"detail": "CSRF_TOKEN_INVALID"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(CatalogError)
    @app.exception_handler(BackupError)
    @app.exception_handler(ExportError)
    @app.exception_handler(DatabaseBoundaryError)
    @app.exception_handler(OperationError)
    async def contract_error(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "DATABASE_BUSY_OR_UNAVAILABLE"}, status_code=503)

    @app.exception_handler(OSError)
    async def storage_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "LOCAL_STORAGE_UNAVAILABLE"}, status_code=507)

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/session")
    def session() -> dict[str, Any]:
        return {
            "csrf_token": csrf_tokens.issue(),
            "csrf_expires_in_seconds": csrf_ttl_seconds,
            "distribution_label": "SYNTHETIC / DEMO",
            "write_policy": "local_origin_and_csrf_required",
            "material_catalog_configured": app.state.materials is not None,
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return service.overview()

    def material_catalog() -> MaterialCatalog:
        if app.state.materials is None:
            raise HTTPException(status_code=409, detail="MATERIAL_ROOT_NOT_CONFIGURED")
        return app.state.materials

    def research_service() -> ResearchService:
        material_catalog()
        return app.state.research

    @app.get("/api/research")
    def studies() -> dict[str, Any]:
        return {"runs": research_service().list()}

    @app.post("/api/research", status_code=201)
    def create_study(config: StudyConfig) -> dict[str, Any]:
        return research_service().create(config)

    @app.post("/api/research/font-samples", status_code=201)
    def render_study_fonts(config: FontSampleConfig) -> dict[str, Any]:
        return {"items": research_service().render_font_samples(config)}

    @app.get("/api/research/{run_id}")
    def study(run_id: str) -> dict[str, Any]:
        return research_service().get(run_id)

    @app.post("/api/research/{run_id}/measure")
    def measure_study(run_id: str) -> dict[str, Any]:
        return research_service().measure(run_id)

    @app.get("/api/research/{run_id}/results")
    def study_results(run_id: str) -> dict[str, Any]:
        return analyze_research(research_service(), app.state.personas, run_id)

    @app.get("/api/research/{run_id}/assessments")
    def study_assessments(run_id: str) -> dict[str, Any]:
        return {"assessments": research_service().assessments(run_id)}

    @app.post("/api/research/{run_id}/assessments", status_code=201)
    def save_study_assessment(run_id: str, payload: ResearchAssessment) -> dict[str, Any]:
        return research_service().save_assessment(run_id, payload, study_results(run_id))

    @app.get("/api/research-assessments/{assessment_id}/continue")
    def continue_study(assessment_id: str) -> dict[str, Any]:
        return {"config": research_service().continuation(assessment_id)}

    @app.post("/api/research/{run_id}/export")
    def export_study(run_id: str) -> dict[str, Any]:
        exported = export_research(study_results(run_id), exports)
        return {**exported, "download_url": f"/api/research-exports/{exported['export_id']}"}

    @app.get("/api/research-exports/{export_id}")
    def download_study(export_id: str) -> FileResponse:
        if not __import__("re").fullmatch(r"study_[0-9a-f]{24}-[0-9a-f]{16}", export_id):
            raise HTTPException(status_code=422, detail="RESEARCH_EXPORT_ID_INVALID")
        destination = exports / "research" / f"{export_id}.zip"
        if not destination.is_file():
            raise HTTPException(status_code=404, detail="RESEARCH_EXPORT_NOT_FOUND")
        return FileResponse(destination, filename=destination.name, media_type="application/zip")

    @app.get("/api/research/{run_id}/tasks")
    def persona_tasks(run_id: str) -> dict[str, Any]:
        research_service()
        return {"executor": "VS Code agent / runSubagent", "backend_can_call_subagent": False, "tasks": app.state.personas.tasks(run_id)}

    @app.post("/api/research/{run_id}/tasks")
    def prepare_persona_tasks(run_id: str) -> dict[str, Any]:
        research_service()
        return {"tasks": app.state.personas.prepare(run_id)}

    @app.post("/api/research/{run_id}/suspend")
    def suspend_study(run_id: str) -> dict[str, Any]:
        research_service()
        app.state.personas.suspend(run_id)
        return research_service().get(run_id)

    @app.post("/api/research/{run_id}/resume")
    def resume_study(run_id: str) -> dict[str, Any]:
        research_service()
        app.state.personas.resume(run_id)
        return research_service().get(run_id)

    @app.post("/api/research/{run_id}/tasks/{task_id}/retry")
    def retry_persona_task(run_id: str, task_id: str) -> dict[str, Any]:
        research_service()
        app.state.personas.retry(run_id, task_id)
        return {"tasks": app.state.personas.tasks(run_id)}

    @app.get("/api/research/{run_id}/inputs/{material_id}")
    def study_input(run_id: str, material_id: str) -> FileResponse:
        return FileResponse(research_service().input_image(run_id, material_id))

    @app.get("/api/materials")
    def materials(query: str = "", kind: str = "", award: str = "", offset: int = 0, limit: int = 50) -> dict[str, Any]:
        catalog = material_catalog()
        if offset < 0 or not 1 <= limit <= 500:
            raise HTTPException(status_code=422, detail="MATERIAL_PAGE_INVALID")
        items = catalog.search(query, kind, award)
        return {"summary": catalog.summary(), "total": len(items), "items": items[offset:offset + limit]}

    @app.get("/api/materials/{material_id}")
    def material(material_id: str) -> dict[str, Any]:
        try:
            return material_catalog().items[material_id]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="MATERIAL_NOT_FOUND") from error

    @app.get("/api/materials/{material_id}/image/{representation}")
    def material_image(material_id: str, representation: Literal["original", "standardized"]) -> FileResponse:
        try:
            return FileResponse(material_catalog().image_path(material_id, representation))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="MATERIAL_REPRESENTATION_NOT_FOUND") from error

    @app.get("/api/materials/{material_id}/preview/{representation}")
    def material_preview(material_id: str, representation: Literal["original", "standardized"],
                         left: int | None = None, top: int | None = None, right: int | None = None, bottom: int | None = None,
                         foreground: Literal["unconfirmed", "dark", "light"] = "unconfirmed",
                         color_mode: Literal["native", "grayscale"] = "native", max_edge: int | None = None,
                         layer: Literal["input", "mask", "overlay"] = "input") -> Response:
        edges = (left, top, right, bottom)
        if any(edge is not None for edge in edges) and not all(edge is not None for edge in edges):
            raise HTTPException(status_code=422, detail="STUDY_CROP_INCOMPLETE")
        selection = MaterialSelection(material_id=material_id, representation=representation, reason="preview only",
                                      crop_box=edges if left is not None else None, foreground=foreground,
                                      foreground_note="Preview only; not a saved confirmation.", color_mode=color_mode, max_edge=max_edge)
        return Response(research_service().preview(selection, layer), media_type="image/png")

    @app.get("/api/modules")
    def modules() -> dict[str, Any]:
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "modules": _module_descriptors(service),
        }

    @app.get("/api/views/{view_name}")
    def module_view(view_name: ViewName) -> dict[str, Any]:
        return _module_view(service, view_name.value)

    @app.get("/api/analysis")
    def analysis() -> dict[str, Any]:
        return _analysis_view(service)

    @app.get("/api/audit")
    def audit() -> dict[str, Any]:
        return _audit_view(service, backups)

    @app.get("/api/evidence/{entity_id}")
    def evidence(entity_id: str) -> dict[str, Any]:
        if len(entity_id) > 160 or not __import__("re").fullmatch(SAFE_ID, entity_id):
            raise HTTPException(status_code=422, detail="ENTITY_ID_INVALID")
        links = service.catalog.entity_links(entity_id)
        artifact_ids = {row["evidence_artifact_id"] for row in links if row["evidence_artifact_id"]}
        artifacts = [
            _artifact(row)
            for row in service.catalog.rows("artifacts")
            if row["artifact_id"] in artifact_ids
        ]
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "entity_id": entity_id,
            "relationships": [_link(row) for row in links],
            "evidence_artifacts": artifacts,
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        disk = shutil.disk_usage(service.catalog_database.parent)
        audit_data = _audit_view(service, backups)
        failed_runs = sum(
            row["status"].startswith("failed")
            for row in service.catalog.rows("analysis_runs")
        )
        return {
            "status": "ready" if service.catalog.integrity_check() == "ok" else "blocked",
            "distribution_label": "SYNTHETIC / DEMO",
            "catalog": {
                "integrity_check": service.catalog.integrity_check(),
                "schema_version": "1.0.0",
            },
            "social": service.social_status(),
            "disk": {"free_bytes": disk.free, "total_bytes": disk.total},
            "credentials_configured": _credential_status(),
            "latest_backup": audit_data["backups"][0] if audit_data["backups"] else None,
            "failed_task_count": failed_runs,
            "operation_counts": {
                status: sum(item["status"] == status for item in operations.list())
                for status in (
                    "queued",
                    "running",
                    "cancel_requested",
                    "completed",
                    "failed",
                    "canceled",
                )
            },
            "scheduler_started": False,
        }

    @app.get("/api/operations")
    def list_operations() -> dict[str, Any]:
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "operations": operations.list(),
        }

    @app.get("/api/operations/{operation_id}")
    def operation_status(operation_id: str) -> dict[str, Any]:
        if not __import__("re").fullmatch(r"operation_[0-9a-f]{24}", operation_id):
            raise HTTPException(status_code=422, detail="OPERATION_ID_INVALID")
        try:
            return operations.get(operation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="OPERATION_NOT_FOUND") from error

    @app.post("/api/operations/analysis-fixture", status_code=202)
    def start_analysis_operation(
        payload: ConfirmationInput | None = None,
    ) -> dict[str, Any]:
        _require_confirmation(payload, "RUN ANALYSIS FIXTURE")
        return operations.submit("analysis_fixture")

    @app.post("/api/operations/system-fixture", status_code=202)
    def start_system_operation(
        payload: ConfirmationInput | None = None,
    ) -> dict[str, Any]:
        _require_confirmation(payload, "RUN SYSTEM FIXTURE")
        return operations.submit("system_fixture")

    @app.post("/api/operations/{operation_id}/cancel")
    def cancel_operation(
        operation_id: str, payload: ConfirmationInput | None = None
    ) -> dict[str, Any]:
        _require_confirmation(payload, "STOP OPERATION")
        try:
            return operations.cancel(operation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="OPERATION_NOT_FOUND") from error

    @app.post("/api/operations/{operation_id}/resume", status_code=202)
    def resume_operation(
        operation_id: str, payload: ConfirmationInput | None = None
    ) -> dict[str, Any]:
        _require_confirmation(payload, "RESUME OPERATION")
        try:
            return operations.resume(operation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="OPERATION_NOT_FOUND") from error

    @app.post("/api/actions/initialize")
    def initialize(payload: ConfirmationInput | None = None) -> dict[str, Any]:
        _require_confirmation(payload, "INITIALIZE CATALOG")
        result = service.initialize_catalog()
        return {
            "status": "initialized",
            "handoff_count": len(result["handoffs"]),
            "module_count": len(result["modules"]),
            "artifact_count": result["graph"]["artifact_count"],
            "relationship_count": result["graph"]["entity_link_count"],
        }

    @app.post("/api/actions/import-handoff")
    def import_handoff(payload: HandoffImportInput) -> dict[str, Any]:
        return service.import_handoff(payload.source)

    @app.post("/api/actions/run-fixture")
    def run_fixture(payload: ConfirmationInput | None = None) -> dict[str, Any]:
        _require_confirmation(payload, "RUN ANALYSIS FIXTURE")
        run = service.run_fixture_analysis()
        return {
            "distribution_label": "SYNTHETIC / DEMO",
            "analysis_run_id": run["analysis_run_id"],
            "status": run["status"],
            "snapshot_sha256": run["snapshot_sha256"],
        }

    @app.post("/api/actions/run-system-fixture")
    def run_system_fixture(
        payload: ConfirmationInput | None = None,
    ) -> dict[str, Any]:
        _require_confirmation(payload, "RUN SYSTEM FIXTURE")
        return service.run_system_fixture(export_root=exports, backup_root=backups)

    @app.post("/api/actions/export-demo")
    def export_demo(payload: RunInput) -> dict[str, Any]:
        _require_confirmation(payload, "EXPORT DEMO")
        return service.export_demo(payload.analysis_run_id, exports / "audit")

    @app.post("/api/actions/check-formal-release")
    def check_formal_release(payload: RunInput) -> dict[str, Any]:
        _require_confirmation(payload, "CHECK FORMAL RELEASE")
        try:
            candidate = service.evaluate_release(
                payload.analysis_run_id, purpose="formal_release"
            )
        except ReleaseBlocked as error:
            candidate = error.candidate
        return candidate

    @app.post("/api/actions/backup")
    def create_backup_action(
        payload: ConfirmationInput | None = None,
    ) -> dict[str, Any]:
        _require_confirmation(payload, "CREATE BACKUP")
        return service.create_backup(backups)

    @app.post("/api/actions/restore-drill")
    def restore_drill(payload: BackupInput) -> dict[str, Any]:
        drill_id = uuid.uuid4().hex[:12]
        directory = restores / payload.backup_id / drill_id
        result = service.restore_backup_drill(
            backups,
            payload.backup_id,
            target_catalog_database=directory / "catalog.sqlite3",
            target_social_database=directory / "social.sqlite3",
        )
        return {
            "backup_id": result["backup_id"],
            "restore_mode": result["restore_mode"],
            "drill_id": drill_id,
            "catalog_integrity": result["health"]["catalog_integrity"],
            "social_integrity": result["health"]["social"]["integrity_check"],
        }

    return app
"""Local synthetic-only API for the cross-cultural experiment interface."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from glyph_features.asset_system.catalog import resolve_workspace_asset

from .fixtures import build_synthetic_catalog
from .schema import ROOT, canonical_sha256, require_frozen_study_id
from .storage import ExperimentStore, StoreError


STATIC_DIR = Path(__file__).with_name("static")


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["zh-Hans", "en", "ja", "ko"]
    session_nonce: str = Field(pattern=r"^[a-z0-9_-]{8,64}$")
    profile: dict[str, Any] | None = None
    consent: dict[str, Any] | None = None


class SubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: dict[str, Any]
    ratings: list[dict[str, Any]] = Field(min_length=1)


def create_app(database_path: str | Path, *, study_id: str, root: Path = ROOT) -> FastAPI:
    root = root.resolve()
    protocol = json.loads((root / "configs/cross_cultural_study_v1.json").read_text(encoding="utf-8"))
    require_frozen_study_id(study_id, protocol["study_id"])
    questionnaire = json.loads((root / "configs/questionnaire_v1.json").read_text(encoding="utf-8"))
    catalog = build_synthetic_catalog(study_id=protocol["study_id"], root=root)
    catalog_by_id = {item["stimulus_id"]: item for item in catalog["items"]}
    store = ExperimentStore(database_path, study_id=study_id, catalog=catalog["items"])
    app = FastAPI(title="GLYPH synthetic cross-cultural experiment", version="1.0.0")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/api/status")
    def public_status() -> dict[str, Any]:
        database_mode = store.system_status()
        return {
            "study_id": protocol["study_id"],
            "protocol_version": protocol["protocol_version"],
            "questionnaire_version": questionnaire["questionnaire_version"],
            "synthetic_only": database_mode["synthetic_only"],
            "database_mode": database_mode,
            "real_collection_locked": True,
            "translation_status": questionnaire["status"],
            "human_gates": protocol["human_gates"],
            "task01_handoff_validation": catalog["source_handoff"]["strict_validation"],
            "formal_stimulus_entrypoint": "blocked",
        }

    @app.get("/api/questionnaire")
    def questionnaire_definition() -> dict[str, Any]:
        return questionnaire

    @app.get("/api/practice")
    def practice_stimulus() -> dict[str, Any]:
        item = catalog["items"][0]
        return {
            "synthetic_only": True,
            "stimulus_id": item["stimulus_id"],
            "expected_asset_sha256": item["asset"]["sha256"],
            "asset_url": f"/api/assets/{item['stimulus_id']}",
        }

    @app.post("/api/session")
    def create_session(payload: SessionInput) -> dict[str, Any]:
        if payload.profile is None:
            raise HTTPException(status_code=422, detail={"code": "PROFILE_REQUIRED"})
        if payload.consent is None:
            raise HTTPException(status_code=422, detail={"code": "CONSENT_REQUIRED"})
        participant_id = f"synp_browser_{canonical_sha256({'study_id': study_id, 'session_nonce': payload.session_nonce})[:16]}"
        native_scripts = payload.profile.get("native_scripts", [])
        participant_group = native_scripts[0] if len(native_scripts) == 1 else "multiscript"
        participant = {
            "participant_id": participant_id,
            "participant_group": participant_group,
            "data_origin": "synthetic",
        }
        recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        profile = {
            **payload.profile,
            "schema_version": "1.0.0",
            "study_id": study_id,
            "participant_id": participant_id,
            "data_origin": "synthetic",
            "questionnaire_language": payload.language,
            "created_at": recorded_at,
        }
        consent = {
            **payload.consent,
            "schema_version": "1.1.0",
            "study_id": study_id,
            "protocol_version": protocol["protocol_version"],
            "questionnaire_version": questionnaire["questionnaire_version"],
            "participant_id": participant_id,
            "data_origin": "synthetic",
            "recorded_at": recorded_at,
        }
        try:
            saved, _ = store.allocate_assignment(
                participant,
                profile=profile,
                consent=consent,
                session_nonce=payload.session_nonce,
                request_payload=payload.model_dump(mode="json"),
                seed=protocol["randomization"]["seed_namespace"],
                block_size=protocol["design"]["block_size"],
                required_anchor_count=protocol["design"]["anchor_count"],
                created_at=protocol["created_at"],
            )
        except StoreError as error:
            _raise_store_error(error)
        return _public_session(store, saved["participant_id"])

    @app.get("/api/session/{participant_id}")
    def resume_session(participant_id: str) -> dict[str, Any]:
        try:
            return _public_session(store, participant_id)
        except StoreError as error:
            _raise_store_error(error)

    @app.get("/api/assets/{stimulus_id}")
    def stimulus_asset(stimulus_id: str) -> FileResponse:
        item = catalog_by_id.get(stimulus_id)
        if item is None:
            raise HTTPException(status_code=404, detail={"code": "STIMULUS_NOT_FOUND"})
        try:
            asset_path = resolve_workspace_asset(root, item["asset"])
        except ValueError as error:
            raise HTTPException(status_code=409, detail={"code": "ASSET_VERIFICATION_FAILED", "message": str(error)}) from error
        return FileResponse(asset_path, media_type=item["asset"].get("mime_type", "application/octet-stream"))

    @app.post("/api/submissions")
    def submit(payload: SubmissionInput) -> dict[str, Any]:
        try:
            return store.submit_trial(payload.event, payload.ratings)
        except StoreError as error:
            _raise_store_error(error)

    @app.get("/api/debug/counts")
    def synthetic_counts() -> dict[str, int]:
        return store.counts()

    return app


def _public_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    return {
        "study_id": assignment["study_id"],
        "assignment_id": assignment["assignment_id"],
        "block_id": assignment["block_id"],
        "participant_id": assignment["participant_id"],
        "questionnaire_version": assignment["questionnaire_version"],
        "synthetic_only": True,
        "status": assignment["status"],
        "resume_next_trial": assignment["resume_next_trial"],
        "trials": [
            {
                "presentation_id": trial["presentation_id"],
                "trial_index": trial["trial_index"],
                "stimulus_id": trial["stimulus_id"],
                "expected_asset_sha256": trial["asset_sha256"],
                "asset_url": f"/api/assets/{trial['stimulus_id']}",
            }
            for trial in assignment["trials"]
        ],
    }


def _public_session(store: ExperimentStore, participant_id: str) -> dict[str, Any]:
    result = _public_assignment(store.assignment_for(participant_id))
    result["profile"] = store.profile_for(participant_id)
    result["consent"] = store.consent_for(participant_id)
    result["quality_decision"] = store.latest_quality_decision(participant_id)
    return result


def _raise_store_error(error: StoreError) -> None:
    status_code = 404 if error.code == "ASSIGNMENT_NOT_FOUND" else 409
    raise HTTPException(status_code=status_code, detail={"code": error.code, "message": str(error)}) from error
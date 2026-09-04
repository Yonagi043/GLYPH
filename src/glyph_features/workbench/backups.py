"""Coordinated, checksum-verified backups for workbench-owned state."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glyph_features.social_system.backups import restore_backup as restore_social_backup
from glyph_features.social_system.service import SocialNarrativeService

from .catalog import CATALOG_SCHEMA_VERSION, Catalog


COORDINATED_BACKUP_ID = re.compile(
    r"^coordinated_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$"
)
CATALOG_BACKUP_ID = re.compile(
    r"^catalog_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$"
)
SOCIAL_BACKUP_ID = re.compile(r"^backup_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$")


class BackupError(ValueError):
    """Raised when coordinated backup or restore validation fails."""


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _inspect_catalog(path: Path) -> dict[str, Any]:
    uri = f"file:{path}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=10) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            metadata = connection.execute(
                "SELECT schema_version FROM workbench_metadata WHERE singleton = 1"
            ).fetchone()
            if integrity != "ok" or metadata is None:
                raise BackupError("CATALOG_BACKUP_INTEGRITY_FAILED")
            if metadata[0] != CATALOG_SCHEMA_VERSION:
                raise BackupError("CATALOG_BACKUP_SCHEMA_UNSUPPORTED")
            counts = {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "modules",
                    "handoff_imports",
                    "artifacts",
                    "entity_links",
                    "analysis_runs",
                    "release_candidates",
                    "audit_events",
                )
            }
    except sqlite3.Error as error:
        raise BackupError("CATALOG_BACKUP_UNREADABLE") from error
    return {
        "integrity_check": integrity,
        "schema_version": metadata[0],
        "counts": counts,
    }


def create_catalog_backup(database_path: Path, backup_root: Path) -> dict[str, Any]:
    backup_id = f"catalog_{_stamp()}_{uuid.uuid4().hex[:8]}"
    directory = backup_root / backup_id
    directory.mkdir(parents=True, exist_ok=False)
    database_copy = directory / "glyph-workbench.sqlite3"
    temporary = directory / ".glyph-workbench.sqlite3.tmp"
    source = sqlite3.connect(database_path, timeout=30)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    temporary.replace(database_copy)
    inspection = _inspect_catalog(database_copy)
    manifest = {
        "backup_id": backup_id,
        "created_at": _now(),
        "database_file": database_copy.name,
        "byte_size": database_copy.stat().st_size,
        "sha256": _sha256(database_copy),
        **inspection,
    }
    _write_json(directory / "manifest.json", manifest)
    return manifest


def restore_catalog_backup(
    target_database: Path,
    backup_root: Path,
    backup_id: str,
) -> dict[str, Any]:
    if not CATALOG_BACKUP_ID.fullmatch(backup_id):
        raise BackupError("CATALOG_BACKUP_ID_INVALID")
    directory = backup_root / backup_id
    manifest_path = directory / "manifest.json"
    source_database = directory / "glyph-workbench.sqlite3"
    if not manifest_path.is_file() or not source_database.is_file():
        raise BackupError("CATALOG_BACKUP_NOT_FOUND")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("backup_id") != backup_id
        or manifest.get("sha256") != _sha256(source_database)
    ):
        raise BackupError("CATALOG_BACKUP_CHECKSUM_MISMATCH")
    source_inspection = _inspect_catalog(source_database)
    if target_database.exists():
        raise BackupError("RESTORE_TARGET_MUST_NOT_EXIST")
    target_database.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_database.with_name(
        f".{target_database.name}.{uuid.uuid4().hex}.restore"
    )
    source = sqlite3.connect(source_database, timeout=30)
    target = sqlite3.connect(temporary, timeout=30)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    temporary.replace(target_database)
    restored = _inspect_catalog(target_database)
    if restored != source_inspection:
        target_database.unlink(missing_ok=True)
        raise BackupError("CATALOG_RESTORE_VERIFICATION_FAILED")
    return {"restored_backup_id": backup_id, **restored}


def _checksums(directory: Path, relative_paths: list[str]) -> str:
    lines = [f"{_sha256(directory / name)}  {name}" for name in sorted(relative_paths)]
    path = directory / "checksums.sha256"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _sha256(path)


def create_coordinated_backup(
    catalog_database: Path,
    social_database: Path,
    backup_root: Path,
) -> dict[str, Any]:
    if not catalog_database.is_file() or not social_database.is_file():
        raise BackupError("COORDINATED_BACKUP_REQUIRES_BOTH_DATABASES")
    backup_id = f"coordinated_{_stamp()}_{uuid.uuid4().hex[:8]}"
    directory = backup_root / backup_id
    started_at = _now()
    directory.mkdir(parents=True, exist_ok=False)
    try:
        catalog_manifest = create_catalog_backup(catalog_database, directory / "catalog")
        social_manifest = SocialNarrativeService(social_database).create_backup(
            directory / "social",
            reason=f"workbench_coordinated:{backup_id}",
        )
        catalog_prefix = f"catalog/{catalog_manifest['backup_id']}"
        social_prefix = f"social/{social_manifest['backup_id']}"
        component_paths = [
            f"{catalog_prefix}/manifest.json",
            f"{catalog_prefix}/glyph-workbench.sqlite3",
            f"{social_prefix}/manifest.json",
            f"{social_prefix}/glyph-social.sqlite3",
        ]
        checksums_sha256 = _checksums(directory, component_paths)
        manifest = {
            "manifest_version": "1.0.0",
            "backup_id": backup_id,
            "started_at": started_at,
            "completed_at": _now(),
            "consistency_model": "sequential_sqlite_online_backups",
            "checksums_file": "checksums.sha256",
            "checksums_sha256": checksums_sha256,
            "components": {
                "catalog": {
                    "backup_id": catalog_manifest["backup_id"],
                    "schema_version": catalog_manifest["schema_version"],
                    "sha256": catalog_manifest["sha256"],
                    "integrity_check": catalog_manifest["integrity_check"],
                    "counts": catalog_manifest["counts"],
                },
                "social": {
                    "backup_id": social_manifest["backup_id"],
                    "schema_version": social_manifest["schema_version"],
                    "sha256": social_manifest["sha256"],
                    "integrity_check": social_manifest["integrity_check"],
                    "counts": social_manifest["counts"],
                },
            },
        }
        _write_json(directory / "coordinated_manifest.json", manifest)
        return manifest
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _verify_checksums(directory: Path, expected_sha256: str) -> None:
    checksum_path = directory / "checksums.sha256"
    if not checksum_path.is_file() or _sha256(checksum_path) != expected_sha256:
        raise BackupError("COORDINATED_CHECKSUM_FILE_MISMATCH")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise BackupError("COORDINATED_CHECKSUM_FORMAT_INVALID")
        path = directory / relative
        if path.resolve().is_relative_to(directory.resolve()) is False:
            raise BackupError("COORDINATED_CHECKSUM_PATH_INVALID")
        if not path.is_file() or _sha256(path) != digest:
            raise BackupError("COORDINATED_COMPONENT_CHECKSUM_MISMATCH")


def restore_coordinated_backup(
    backup_root: Path,
    backup_id: str,
    *,
    target_catalog_database: Path,
    target_social_database: Path,
) -> dict[str, Any]:
    if not COORDINATED_BACKUP_ID.fullmatch(backup_id):
        raise BackupError("COORDINATED_BACKUP_ID_INVALID")
    directory = backup_root / backup_id
    manifest_path = directory / "coordinated_manifest.json"
    if not manifest_path.is_file():
        raise BackupError("COORDINATED_BACKUP_NOT_FOUND")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("backup_id") != backup_id:
        raise BackupError("COORDINATED_MANIFEST_ID_MISMATCH")
    _verify_checksums(directory, manifest.get("checksums_sha256", ""))
    catalog_component = manifest["components"]["catalog"]
    social_component = manifest["components"]["social"]
    if not SOCIAL_BACKUP_ID.fullmatch(social_component["backup_id"]):
        raise BackupError("SOCIAL_BACKUP_ID_INVALID")
    catalog_result = restore_catalog_backup(
        target_catalog_database,
        directory / "catalog",
        catalog_component["backup_id"],
    )
    try:
        target_social_database.parent.mkdir(parents=True, exist_ok=True)
        social_result = restore_social_backup(
            target_social_database,
            directory / "social",
            social_component["backup_id"],
        )
        restored_catalog = Catalog(target_catalog_database)
        if restored_catalog.integrity_check() != "ok":
            raise BackupError("RESTORED_CATALOG_NOT_HEALTHY")
    except Exception:
        target_catalog_database.unlink(missing_ok=True)
        target_social_database.unlink(missing_ok=True)
        raise
    return {
        "backup_id": backup_id,
        "restore_mode": "temporary_drill",
        "catalog": catalog_result,
        "social": social_result,
    }
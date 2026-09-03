"""Consistent SQLite backup and restore primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import SCHEMA_VERSION


BACKUP_ID = re.compile(r"^backup_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite 完整性检查失败：{integrity}")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        counts = {}
        for table in ("collection_runs", "observations", "review_events", "collector_cursors"):
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        cursors = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT platform, cursor FROM collector_cursors ORDER BY platform"
            ).fetchall()
        }
        return {
            "integrity_check": integrity,
            "schema_version": version,
            "counts": counts,
            "collector_cursors": cursors,
            "bluesky_cursor": cursors.get("bluesky"),
        }
    finally:
        connection.close()


def create_backup(database_path: Path, backup_root: Path, *, reason: str) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"backup_{stamp}_{uuid.uuid4().hex[:8]}"
    directory = backup_root / backup_id
    directory.mkdir(parents=True, exist_ok=False)
    database_copy = directory / "glyph-social.sqlite3"
    temporary = directory / ".glyph-social.sqlite3.tmp"
    source = sqlite3.connect(database_path, timeout=30)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    temporary.replace(database_copy)
    inspection = _inspect(database_copy)
    manifest = {
        "backup_id": backup_id,
        "created_at": _now(),
        "reason": reason,
        "database_file": database_copy.name,
        "byte_size": database_copy.stat().st_size,
        "sha256": _sha256(database_copy),
        **inspection,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def list_backups(backup_root: Path) -> list[dict[str, Any]]:
    if not backup_root.exists():
        return []
    output = []
    for manifest_path in backup_root.glob("backup_*/manifest.json"):
        try:
            output.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(output, key=lambda item: item["created_at"], reverse=True)


def restore_backup(database_path: Path, backup_root: Path, backup_id: str) -> dict[str, Any]:
    if not BACKUP_ID.fullmatch(backup_id):
        raise KeyError(backup_id)
    directory = backup_root / backup_id
    manifest_path = directory / "manifest.json"
    backup_database = directory / "glyph-social.sqlite3"
    if not manifest_path.is_file() or not backup_database.is_file():
        raise KeyError(backup_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("backup_id") != backup_id or _sha256(backup_database) != manifest.get("sha256"):
        raise ValueError("备份清单或 SHA-256 校验失败")
    inspection = _inspect(backup_database)
    if not 1 <= inspection["schema_version"] <= SCHEMA_VERSION:
        raise ValueError(
            f"备份 schema v{inspection['schema_version']} 与当前 v{SCHEMA_VERSION} 不兼容"
        )

    temporary = database_path.with_name(f".{database_path.name}.{uuid.uuid4().hex}.restore")
    source = sqlite3.connect(backup_database)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    _inspect(temporary)
    for suffix in ("-wal", "-shm"):
        database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
    os.replace(temporary, database_path)
    return {"restored_backup_id": backup_id, **inspection}
"""Controlled directory/zip import for trusted upstream handoff pointers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from glyph_features.asset_system.catalog import normalize_repo_path

from .catalog import CatalogError
from .handoffs import UPSTREAM_HANDOFFS, inspect_handoff_manifest


@dataclass(frozen=True)
class HandoffImportLimits:
    max_files: int = 2048
    max_file_size: int = 64 * 1024 * 1024
    max_total_size: int = 256 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise CatalogError("HANDOFF_ZIP_PATH_INVALID")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or (path.parts and ":" in path.parts[0])
    ):
        raise CatalogError("HANDOFF_ZIP_PATH_INVALID")
    return path


def _check_limits(count: int, size: int, total: int, limits: HandoffImportLimits) -> None:
    if count > limits.max_files:
        raise CatalogError("HANDOFF_PACKAGE_FILE_COUNT_EXCEEDED")
    if size > limits.max_file_size:
        raise CatalogError("HANDOFF_PACKAGE_FILE_SIZE_EXCEEDED")
    if total > limits.max_total_size:
        raise CatalogError("HANDOFF_PACKAGE_TOTAL_SIZE_EXCEEDED")


def _copy_directory(source: Path, staging: Path, limits: HandoffImportLimits) -> None:
    if source.is_symlink():
        raise CatalogError("HANDOFF_PACKAGE_SYMLINK_FORBIDDEN")
    count = 0
    total = 0
    pending = [(source, staging)]
    while pending:
        current, target_root = pending.pop()
        target_root.mkdir(parents=True, exist_ok=True)
        with os.scandir(current) as entries:
            for entry in entries:
                source_path = Path(entry.path)
                target = target_root / entry.name
                if entry.is_symlink():
                    raise CatalogError("HANDOFF_PACKAGE_SYMLINK_FORBIDDEN")
                if entry.is_dir(follow_symlinks=False):
                    pending.append((source_path, target))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise CatalogError("HANDOFF_PACKAGE_SPECIAL_FILE_FORBIDDEN")
                size = entry.stat(follow_symlinks=False).st_size
                count += 1
                total += size
                _check_limits(count, size, total, limits)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, target, follow_symlinks=False)


def _extract_zip(source: Path, staging: Path, limits: HandoffImportLimits) -> None:
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise CatalogError("HANDOFF_ZIP_INVALID") from error
    with archive:
        seen: set[str] = set()
        count = 0
        total = 0
        for member in archive.infolist():
            relative = _safe_member(member.filename)
            key = relative.as_posix()
            if key in seen:
                raise CatalogError("HANDOFF_ZIP_DUPLICATE_MEMBER")
            seen.add(key)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                raise CatalogError("HANDOFF_PACKAGE_SYMLINK_FORBIDDEN")
            if member.is_dir():
                continue
            if member.flag_bits & 0x1:
                raise CatalogError("HANDOFF_ZIP_ENCRYPTED_MEMBER_FORBIDDEN")
            count += 1
            total += member.file_size
            _check_limits(count, member.file_size, total, limits)
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(member) as reader, target.open("xb") as writer:
                while chunk := reader.read(1024 * 1024):
                    written += len(chunk)
                    if written > limits.max_file_size or total - member.file_size + written > limits.max_total_size:
                        raise CatalogError("HANDOFF_PACKAGE_TOTAL_SIZE_EXCEEDED")
                    writer.write(chunk)
            if written != member.file_size:
                raise CatalogError("HANDOFF_ZIP_SIZE_MISMATCH")


def _load_primary_manifest(staging: Path) -> tuple[Path, dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in staging.rglob("handoff_manifest.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("task_id") in {
            spec.task_id for spec in UPSTREAM_HANDOFFS
        }:
            candidates.append((path, value))
    if not candidates:
        raise CatalogError("HANDOFF_PACKAGE_MANIFEST_MISSING")
    exact = [
        item
        for item in candidates
        if item[0].relative_to(staging).as_posix()
        == next(
            spec.relative_path
            for spec in UPSTREAM_HANDOFFS
            if spec.task_id == item[1]["task_id"]
        )
    ]
    selected = exact or candidates
    if len(selected) != 1:
        raise CatalogError("HANDOFF_PACKAGE_MANIFEST_AMBIGUOUS")
    return selected[0]


def _package_file(
    staging: Path,
    manifest_path: Path,
    expected_manifest_path: str,
    logical_path: str,
) -> Path:
    try:
        normalized = normalize_repo_path(logical_path)
    except (TypeError, ValueError) as error:
        raise CatalogError("HANDOFF_PACKAGE_ARTIFACT_PATH_INVALID") from error
    direct = staging / normalized
    if direct.is_file():
        return direct
    prefix = Path(expected_manifest_path).parent
    logical = Path(normalized)
    if manifest_path.parent == staging and logical.is_relative_to(prefix):
        bundled = staging / logical.relative_to(prefix)
        if bundled.is_file():
            return bundled
    raise CatalogError(f"HANDOFF_PACKAGE_ARTIFACT_MISSING:{normalized}")


def inspect_handoff_package(
    source: str | Path,
    workspace_root: str | Path,
    *,
    limits: HandoffImportLimits | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate a package without retaining or executing any package payload."""

    root = Path(workspace_root).resolve()
    supplied = Path(source).expanduser()
    effective_limits = limits or HandoffImportLimits()
    if not supplied.exists() and not supplied.is_symlink():
        raise CatalogError("HANDOFF_PACKAGE_NOT_FOUND")
    with tempfile.TemporaryDirectory(prefix="glyph-handoff-import-") as temporary:
        staging = Path(temporary)
        if supplied.is_dir() and not supplied.is_symlink():
            _copy_directory(supplied, staging, effective_limits)
        elif supplied.is_file() and zipfile.is_zipfile(supplied):
            _extract_zip(supplied, staging, effective_limits)
        elif supplied.is_symlink():
            raise CatalogError("HANDOFF_PACKAGE_SYMLINK_FORBIDDEN")
        else:
            raise CatalogError("HANDOFF_PACKAGE_TYPE_UNSUPPORTED")

        manifest_path, manifest = _load_primary_manifest(staging)
        task_id = manifest["task_id"]
        spec = next(spec for spec in UPSTREAM_HANDOFFS if spec.task_id == task_id)
        version = manifest.get("handoff_schema_version")
        if version not in spec.supported_versions:
            raise CatalogError(f"HANDOFF_VERSION_UNSUPPORTED:{version}")
        trusted_manifest = root / spec.relative_path
        if (
            not trusted_manifest.is_file()
            or _sha256(trusted_manifest) != _sha256(manifest_path)
        ):
            raise CatalogError("HANDOFF_PACKAGE_MANIFEST_NOT_TRUSTED")
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise CatalogError("HANDOFF_PACKAGE_OUTPUTS_INVALID")
        pointers = []
        for output in outputs:
            if not isinstance(output, dict) or not {
                "logical_type",
                "path",
                "sha256",
            }.issubset(output):
                raise CatalogError("HANDOFF_PACKAGE_OUTPUT_INVALID")
            package_path = _package_file(
                staging,
                manifest_path,
                spec.relative_path,
                output["path"],
            )
            digest = _sha256(package_path)
            if digest != output["sha256"]:
                raise CatalogError(f"HANDOFF_PACKAGE_HASH_MISMATCH:{output['path']}")
            workspace_path = root / normalize_repo_path(output["path"])
            if not workspace_path.is_file() or _sha256(workspace_path) != digest:
                raise CatalogError(
                    f"HANDOFF_PACKAGE_WORKSPACE_MISMATCH:{output['path']}"
                )
            classification = (
                output.get("privacy_level")
                or output.get("data_classification")
                or output.get("rights_or_privacy_level")
                or output.get("rights_tier")
                or output.get("license_tier")
                or "unspecified_metadata"
            )
            pointers.append(
                {
                    "module_id": spec.module_id,
                    "logical_type": output["logical_type"],
                    "path": output["path"],
                    "sha256": digest,
                    "schema_version": output.get("schema_version"),
                    "data_classification": classification,
                    "rights_tier": output.get("rights_tier")
                    or output.get("license_tier"),
                    "privacy_level": output.get("privacy_level"),
                    "record_count": output.get("record_count"),
                    "validation_schema": output.get("validation_schema"),
                }
            )
        result = inspect_handoff_manifest(trusted_manifest, root)
        if result["errors"]:
            raise CatalogError(
                "HANDOFF_NATIVE_VALIDATION_FAILED:" + " | ".join(result["errors"])
            )
        result["manifest_path"] = spec.relative_path
        return result, pointers
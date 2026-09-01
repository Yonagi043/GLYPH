"""Small, dependency-light helpers shared by the social-narrative tools.

The module deliberately contains no network code.  Collection adapters (for
example PRAW, the YouTube API client, Facepager, or a manually exported
Zeeschuimer file) hand their bounded results to the offline normalizer.  This
keeps the public repository reproducible and keeps platform credentials out of
the analysis path.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "social_observation.schema.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize JSON in the one deterministic form used for record hashes."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_validator(path: Path) -> Draft202012Validator:
    """Build an offline validator for a repository JSON Schema.

    All sibling ``*.schema.json`` files are registered by file URI.  The
    schema files themselves remain portable (they do not contain a host URL),
    while relative references such as ``shared.schema.json`` resolve without
    network access.
    """

    schema_file = path.resolve()
    schema = load_schema(schema_file)
    # The repository schemas intentionally keep their files portable and do
    # not hard-code a host URL.  Give the in-memory copy a file URI so that
    # relative references resolve against the local schema directory.
    schema["$id"] = schema_file.as_uri()
    # Register both documents explicitly.  This avoids the deprecated
    # RefResolver and, importantly, prevents a relative ``shared.schema.json``
    # reference from causing an unexpected network fetch in an offline run.
    registry = Registry().with_resource(schema_file.as_uri(), Resource.from_contents(schema))
    for sibling in sorted(schema_file.parent.glob("*.schema.json")):
        if sibling.resolve() == schema_file:
            continue
        sibling_schema = load_schema(sibling)
        sibling_schema["$id"] = sibling.resolve().as_uri()
        registry = registry.with_resource(sibling.resolve().as_uri(), Resource.from_contents(sibling_schema))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def validator(path: Path = SCHEMA_PATH) -> Draft202012Validator:
    """Return the social-observation validator (backwards-compatible alias)."""

    return schema_validator(path)


def validation_errors(record: dict[str, Any], check: Draft202012Validator | None = None) -> list[str]:
    check = check or validator()
    return [error.message for error in sorted(check.iter_errors(record), key=lambda item: list(item.path))]


def _json_value(value: Any, default: Any = None) -> Any:
    """Decode a JSON-in-CSV cell while accepting already decoded values."""

    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def read_input_rows(path: Path) -> list[dict[str, Any]]:
    """Read JSONL, JSON arrays/objects, or CSV into adapter-neutral dictionaries.

    JSON objects containing a top-level ``data`` array (the shape returned by
    X API and common API exports) are expanded.  A top-level object without
    ``data`` is treated as one row.  No rows are silently discarded.
    """

    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(raw, newline=""))]
    stripped = raw.lstrip()
    if not stripped:
        return []
    # Try a complete JSON document first.  This supports pretty-printed API
    # responses as well as compact arrays/objects; if decoding fails, fall
    # through to line-oriented JSONL parsing below.
    if stripped.startswith(("[", "{")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            if isinstance(payload, list):
                return [dict(row) for row in payload]
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return [dict(row) for row in payload["data"]]
            if isinstance(payload, dict):
                return [payload]
            raise ValueError("JSON input must contain objects")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at line {line_number}: {error.msg}") from error
        if isinstance(value, dict) and isinstance(value.get("data"), list):
            rows.extend(dict(row) for row in value["data"])
        elif isinstance(value, dict):
            rows.append(value)
        else:
            raise ValueError(f"JSONL line {line_number} is not an object")
    return rows


def first_nonempty(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def as_string(value: Any, default: str = "") -> str:
    value = first_nonempty(value, default=default)
    return str(value) if value is not None else default


def as_int(value: Any, *, allow_negative: bool = False) -> int | None:
    """Parse an integer metric; opt in explicitly for Reddit's negative score."""
    value = first_nonempty(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if allow_negative or number >= 0 else None


def split_labels(value: Any) -> list[str]:
    """Normalize a list or a pipe/comma/semicolon-delimited label cell."""

    value = _json_value(value, default=[])
    if value is None:
        return []
    if isinstance(value, str):
        chunks = value.replace(",", "|").replace(";", "|").split("|")
    elif isinstance(value, (list, tuple, set)):
        chunks = [str(item) for item in value]
    else:
        chunks = [str(value)]
    clean = {chunk.strip() for chunk in chunks if chunk and chunk.strip()}
    return sorted(clean, key=lambda item: (item.casefold(), item))


def nested_dict(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = _json_value(row.get(key), default={})
    return value if isinstance(value, dict) else {}


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield canonical JSONL records, with a useful line number on errors."""

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid output JSONL at line {line_number}: {error.msg}") from error
            if not isinstance(value, dict):
                raise ValueError(f"output JSONL line {line_number} is not an object")
            yield value


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(canonical_json(record) + "\n")

"""Export gates for experiment responses."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .schema import validate_record


FORMAL_GATES = {"GATE-ETHICS", "GATE-PARTICIPANTS", "GATE-TRANSLATION"}
FORBIDDEN_KEYS = {
    "name",
    "full_name",
    "email",
    "phone",
    "address",
    "ip",
    "ip_address",
    "contact",
    "compensation",
    "cookie",
    "token",
}


class ExportBlocked(ValueError):
    """A stable, machine-readable export failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def require_export_eligible(
    records: Iterable[Mapping[str, Any]],
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> None:
    """Reject synthetic responses from formal analysis and release."""
    if purpose not in {"engineering_fixture", "formal_analysis", "release"}:
        raise ExportBlocked("EXPORT_PURPOSE_INVALID", purpose)
    origins = {record.get("data_origin") for record in records}
    if purpose in {"formal_analysis", "release"} and "synthetic" in origins:
        raise ExportBlocked(
            "SYNTHETIC_FORMAL_EXPORT_FORBIDDEN",
            "synthetic responses are restricted to engineering fixtures",
        )
    if purpose in {"formal_analysis", "release"}:
        statuses = human_gates or {}
        blocked = sorted(gate for gate in FORMAL_GATES if statuses.get(gate) != "passed")
        if blocked:
            raise ExportBlocked("HUMAN_GATES_NOT_PASSED", ",".join(blocked))


def write_deidentified_export(
    records: Iterable[dict[str, Any]],
    output_path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    rows = list(records)
    require_export_eligible(rows, purpose=purpose, human_gates=human_gates)
    errors = validate_export_records(rows)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_EXPORT_INVALID", "; ".join(errors))
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"export already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in sorted(rows, key=lambda item: item["rating_id"])
    )
    output.write_text(payload, encoding="utf-8", newline="\n")
    return {
        "path": output.as_posix(),
        "record_count": len(rows),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "data_origins": sorted({row["data_origin"] for row in rows}),
        "purpose": purpose,
    }


def validate_export_records(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    rating_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        schema_errors = validate_record(record, "experiment_rating.schema.json")
        errors.extend(f"line {index}: {error}" for error in schema_errors)
        leaked = sorted(_forbidden_keys(record))
        errors.extend(f"line {index}: FORBIDDEN_PII_KEY:{key}" for key in leaked)
        rating_id = record.get("rating_id")
        if rating_id in rating_ids:
            errors.append(f"line {index}: DUPLICATE_RATING_ID:{rating_id}")
        if isinstance(rating_id, str):
            rating_ids.add(rating_id)
    return errors


def read_and_validate_export(
    path: str | Path,
    *,
    purpose: str,
    human_gates: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    errors = validate_export_records(rows)
    if errors:
        raise ExportBlocked("DEIDENTIFIED_EXPORT_INVALID", "; ".join(errors))
    require_export_eligible(rows, purpose=purpose, human_gates=human_gates)
    return rows


def _forbidden_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).lower() for key in value if str(key).lower() in FORBIDDEN_KEYS}
        return found | set().union(*(_forbidden_keys(child) for child in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_forbidden_keys(child) for child in value), set())
    return set()

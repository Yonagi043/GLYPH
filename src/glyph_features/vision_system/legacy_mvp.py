"""Compatibility shim for the historical Li Jie CV MVP batch workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Sequence

import numpy as np
from PIL import Image, UnidentifiedImageError

from .definitions import load_registry
from .extract import VisionSystemError, measure_array


ALLOWED_WEIGHT_KEYS = {
    "balance", "composition", "complexity", "density", "rhythm", "uniformity",
    "proportion", "stroke_gesture",
}


class LegacyMVPError(RuntimeError):
    pass


def validate_legacy_weights(path: str | Path) -> dict[str, float]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    except LegacyMVPError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyMVPError(f"WEIGHT_FILE_INVALID: {exc}") from exc
    weights = payload.get("weights") if isinstance(payload, dict) else None
    if not isinstance(weights, dict) or not weights:
        raise LegacyMVPError("WEIGHT_OBJECT_REQUIRED")
    unknown = sorted(set(weights) - ALLOWED_WEIGHT_KEYS)
    if unknown:
        raise LegacyMVPError(f"WEIGHT_UNKNOWN_KEY: {','.join(unknown)}")
    normalized: dict[str, float] = {}
    for key, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise LegacyMVPError(f"WEIGHT_NONFINITE: {key}")
        if value < 0:
            raise LegacyMVPError(f"WEIGHT_NEGATIVE: {key}")
        normalized[key] = float(value)
    if sum(normalized.values()) == 0:
        raise LegacyMVPError("WEIGHT_ALL_ZERO")
    return normalized


def run_batch(
    *,
    workspace_root: str | Path,
    input_dir: str | Path,
    output_dir: str | Path,
    representation: str,
    weights_path: str | Path | None = None,
) -> dict[str, int]:
    root = Path(workspace_root).resolve()
    source_root = Path(input_dir).resolve()
    output_root = Path(output_dir)
    if output_root.exists():
        raise LegacyMVPError(f"OUTPUT_EXISTS: {output_root}")
    if weights_path is not None:
        validate_legacy_weights(weights_path)
    registry = load_registry(root / "configs/visual_measurements_v2.yaml", root / "schema")
    definitions = {item["feature_code"]: item for item in registry.active_definitions}
    inputs = sorted(
        item for item in source_root.rglob("*")
        if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
    )
    if not inputs:
        raise LegacyMVPError("NO_IMAGES")
    failures: list[dict[str, str]] = []
    successes = 0
    output_root.mkdir(parents=True)
    for image_path in inputs:
        source_ref = image_path.relative_to(source_root).as_posix()
        try:
            content = image_path.read_bytes()
            with Image.open(image_path) as image:
                gray = np.asarray(image.convert("L"), dtype=np.uint8)
            measurements = measure_array(gray, representation, registry)
            input_sha256 = hashlib.sha256(content).hexdigest()
            result_id = f"legacy_{hashlib.sha256((source_ref + '|' + input_sha256).encode('utf-8')).hexdigest()[:24]}"
            payload = {
                "schema_version": "1.0.0",
                "result_id": result_id,
                "source_ref": source_ref,
                "input_sha256": input_sha256,
                "representation": representation,
                "registry_version": registry.version,
                "measurements": {
                    code: {
                        "value": measured.value,
                        "numerator": measured.numerator,
                        "denominator": measured.denominator,
                        "unit": definitions[code]["unit"],
                        "missing_code": measured.missing_code,
                    }
                    for code, measured in sorted(measurements.items())
                    if code in definitions
                },
                "joint_analysis_eligible": False,
                "calibration_status": "not_calibrated",
            }
            _atomic_write_json(output_root / result_id / "result.json", payload)
            successes += 1
        except (UnidentifiedImageError, OSError) as exc:
            if isinstance(exc, OSError) and not isinstance(exc, UnidentifiedImageError) and "cannot identify image file" not in str(exc):
                raise
            failures.append({
                "failure_code": "IMAGE_DECODE_FAILED",
                "message": f"cannot decode {source_ref}",
                "source_ref": source_ref,
            })
        except VisionSystemError as exc:
            failures.append({
                "failure_code": exc.code,
                "message": str(exc),
                "source_ref": source_ref,
            })
    if failures:
        _atomic_write_lines(output_root / "failures.jsonl", failures)
    _atomic_write_json(output_root / "summary.json", {
        "failed_count": len(failures),
        "joint_analysis_eligible": False,
        "processed_count": len(inputs),
        "succeeded_count": successes,
    })
    return {"processed_count": len(inputs), "succeeded_count": successes, "failed_count": len(failures)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the deprecated CV MVP through visual measurements v2.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--representation", choices=("A_layout", "B_shape", "C_ink"), required=True)
    parser.add_argument("--weights", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_batch(
            workspace_root=args.workspace_root,
            input_dir=args.input_dir,
            output_dir=args.output,
            representation=args.representation,
            weights_path=args.weights,
        )
    except LegacyMVPError as exc:
        print(str(exc))
        return 2
    return 1 if summary["failed_count"] else 0


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _atomic_write_lines(path: Path, rows: list[dict[str, str]]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for row in rows)
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _reject_nonfinite(value: str) -> None:
    raise LegacyMVPError(f"WEIGHT_NONFINITE: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
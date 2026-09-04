"""Extract raw, long-form visual measurements from a validated TASK-01 handoff."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.morphology import skeletonize

from glyph_features.asset_system.export import validate_handoff

from .definitions import FeatureRegistry, canonical_sha256, load_registry


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class VisionSystemError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Metric:
    value: float | int | None
    numerator: float | int | None = None
    denominator: float | int | None = None
    missing_code: str | None = None


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_handoff(
    *,
    workspace_root: str | Path,
    handoff_path: str | Path,
    registry_path: str | Path,
    schema_root: str | Path,
    output_dir: str | Path,
    extraction_run_id: str,
    computed_at: str,
    allow_fixture: bool = False,
) -> dict[str, Any]:
    """Validate TASK-01 provenance and atomically publish one immutable run."""
    if not RUN_ID_PATTERN.fullmatch(extraction_run_id):
        raise VisionSystemError("RUN_ID_INVALID", extraction_run_id)
    root = Path(workspace_root).resolve()
    handoff_file = Path(handoff_path).resolve()
    registry_file = Path(registry_path).resolve()
    schema_directory = Path(schema_root).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"run output already exists: {output}")

    registry = load_registry(registry_file, schema_directory)
    handoff, candidates, stimuli = _load_task01_inputs(
        root,
        handoff_file,
        allow_fixture,
        registry.payload["accepted_task01_commit"],
    )
    source_handoff_sha256 = sha256_file(handoff_file)
    software = _software_environment()
    software_environment_sha256 = canonical_sha256(software)
    validator = _measurement_validator(schema_directory)
    candidate_by_id = {record["asset_id"]: record for record in candidates}
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = []

    for stimulus in stimuli:
        for representation in ("A_layout", "B_shape", "C_ink"):
            reference = stimulus["representations"].get(representation)
            if reference is None:
                failures.append(_failure(stimulus["stimulus_id"], representation, "REPRESENTATION_MISSING", "representation reference is null"))
                continue
            try:
                candidate = candidate_by_id[reference["asset_id"]]
                image_path = _validated_asset_path(root, reference, candidate)
                array = _load_grayscale(image_path)
                metrics = measure_array(array, representation, registry)
                feature_record_id = _stable_id(
                    "feature",
                    stimulus["stimulus_id"],
                    reference["asset_id"],
                    extraction_run_id,
                    representation,
                )
                for definition in registry.active_definitions:
                    code = definition["feature_code"]
                    metric = metrics[code]
                    record = _measurement_record(
                        definition=definition,
                        metric=metric,
                        stimulus_id=stimulus["stimulus_id"],
                        asset_id=reference["asset_id"],
                        extraction_run_id=extraction_run_id,
                        representation=representation,
                        feature_record_id=feature_record_id,
                        input_sha256=reference["asset_ref"]["sha256"],
                        computed_at=computed_at,
                        algorithm_config_sha256=registry.payload["algorithm_config_sha256"],
                        software_environment_sha256=software_environment_sha256,
                        source_contract_sha256=source_handoff_sha256,
                        fixture_only=stimulus["release_status"] == "fixture_only",
                    )
                    errors = sorted(validator.iter_errors(record), key=lambda error: [str(item) for item in error.path])
                    if errors:
                        detail = "; ".join(f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors)
                        raise VisionSystemError("MEASUREMENT_SCHEMA_INVALID", detail)
                    records.append(record)
                input_records.append(
                    {
                        "stimulus_id": stimulus["stimulus_id"],
                        "asset_id": reference["asset_id"],
                        "representation": representation,
                        "path": reference["asset_ref"]["path"],
                        "sha256": reference["asset_ref"]["sha256"],
                    }
                )
            except Exception as error:
                failures.append(
                    _failure(
                        stimulus["stimulus_id"],
                        representation,
                        getattr(error, "code", "EXTRACTION_FAILED"),
                        str(error),
                    )
                )

    records.sort(key=lambda item: (item["stimulus_id"], item["asset_id"], item["representation"], item["feature_code"]))
    input_records.sort(key=lambda item: (item["stimulus_id"], item["representation"]))
    run_manifest = {
        "schema_version": "1.0.0",
        "extraction_run_id": extraction_run_id,
        "protocol_version": registry.payload["protocol_version"],
        "created_at": computed_at,
        "task01_handoff_path": handoff_file.relative_to(root).as_posix(),
        "task01_handoff_sha256": source_handoff_sha256,
        "task01_handoff_schema_version": handoff["handoff_schema_version"],
        "accepted_task01_commit": registry.payload["accepted_task01_commit"],
        "registry_path": registry_file.relative_to(root).as_posix(),
        "registry_sha256": sha256_file(registry_file),
        "algorithm_config_sha256": registry.payload["algorithm_config_sha256"],
        "implementation_sha256": sha256_file(__file__),
        "software_environment": software,
        "software_environment_sha256": software_environment_sha256,
        "fixture_only": all(stimulus["release_status"] == "fixture_only" for stimulus in stimuli),
        "input_representations": input_records,
        "measurement_count": len(records),
        "failure_count": len(failures),
        "canonical_output": "measurements.jsonl",
    }
    summary = {
        "extraction_run_id": extraction_run_id,
        "stimulus_count": len(stimuli),
        "representation_count": len(input_records),
        "measurement_count": len(records),
        "failure_count": len(failures),
        "fixture_only": run_manifest["fixture_only"],
    }
    _publish_run(output, records, failures, run_manifest, registry.payload)
    return summary


def measure_array(
    array: np.ndarray,
    representation: str,
    registry: FeatureRegistry,
    *,
    binary_threshold: int | None = None,
) -> dict[str, Metric]:
    """Measure one frozen representation without centering or component removal."""
    if representation not in {"A_layout", "B_shape", "C_ink"}:
        raise VisionSystemError("REPRESENTATION_UNKNOWN", representation)
    image = np.asarray(array, dtype=np.uint8)
    if image.ndim != 2 or image.size == 0:
        raise VisionSystemError("IMAGE_SHAPE_INVALID", str(image.shape))
    threshold = int(binary_threshold or registry.payload["algorithm_defaults"]["binary_threshold"])
    foreground = image < threshold
    computed = _binary_metrics(foreground)
    if representation == "C_ink":
        computed.update(_tonal_metrics(image))
    result: dict[str, Metric] = {}
    for definition in registry.definitions:
        code = definition["feature_code"]
        if representation not in definition["input_representations"]:
            result[code] = Metric(None, missing_code="REPRESENTATION_NOT_APPLICABLE")
        else:
            result[code] = computed.get(code, Metric(None, missing_code="MEASUREMENT_NOT_IMPLEMENTED"))
    return result


def _binary_metrics(foreground: np.ndarray) -> dict[str, Metric]:
    height, width = foreground.shape
    canvas_pixels = int(foreground.size)
    ys, xs = np.nonzero(foreground)
    if xs.size == 0:
        return {}
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    bbox_width = x1 - x0
    bbox_height = y1 - y0
    area = int(foreground.sum())
    local = foreground[y0:y1, x0:x1]
    labels, component_count = ndimage.label(local, structure=np.ones((3, 3), dtype=np.uint8))
    component_areas = [float(value) for value in ndimage.sum(local, labels, range(1, component_count + 1))]
    component_centers = [
        (float(center[1] + x0), float(center[0] + y0))
        for center in ndimage.center_of_mass(local, labels, range(1, component_count + 1))
    ]
    inner_labels, inner_count = ndimage.label(
        ~local,
        structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8),
    )
    edge_labels = set(
        np.concatenate((inner_labels[0], inner_labels[-1], inner_labels[:, 0], inner_labels[:, -1])).tolist()
    )
    closure_count = sum(label not in edge_labels for label in range(1, inner_count + 1))
    margins = np.asarray([y0 / height, (height - y1) / height, x0 / width, (width - x1) / width], dtype=float)
    metrics: dict[str, Metric] = {
        "ink_coverage_ratio": Metric(area / canvas_pixels, area, canvas_pixels),
        "bbox_fill_ratio": Metric(area / (bbox_width * bbox_height), area, bbox_width * bbox_height),
        "bbox_aspect_ratio": Metric(bbox_width / bbox_height, bbox_width, bbox_height),
        "symmetry_horizontal": Metric(1.0 - np.count_nonzero(foreground != np.fliplr(foreground)) / canvas_pixels, canvas_pixels - np.count_nonzero(foreground != np.fliplr(foreground)), canvas_pixels),
        "symmetry_vertical": Metric(1.0 - np.count_nonzero(foreground != np.flipud(foreground)) / canvas_pixels, canvas_pixels - np.count_nonzero(foreground != np.flipud(foreground)), canvas_pixels),
        "centroid_x_norm": Metric(float(xs.mean() / width), float(xs.mean()), width),
        "centroid_y_norm": Metric(float(ys.mean() / height), float(ys.mean()), height),
        "margin_imbalance": Metric(float(np.std(margins, ddof=0))),
        "connected_component_count": Metric(component_count),
        "closure_count": Metric(closure_count),
    }
    metrics["component_area_cv"] = _coefficient_of_variation(component_areas, minimum_count=2)
    if len(component_centers) < 3:
        metrics["component_spacing_cv"] = Metric(None, missing_code="SEQUENCE_TOO_SHORT")
    else:
        ordered = sorted(component_centers)
        spacings = [math.dist(first, second) for first, second in zip(ordered, ordered[1:])]
        metrics["component_spacing_cv"] = _coefficient_of_variation(spacings, minimum_count=2)

    skeleton = skeletonize(local)
    skeleton_points = np.argwhere(skeleton)
    if skeleton_points.size == 0:
        for code in ("stroke_width_mean_norm", "stroke_width_cv", "direction_coherence", "skeleton_endpoint_count"):
            metrics[code] = Metric(None, missing_code="SKELETON_UNSTABLE")
        return metrics
    distance = ndimage.distance_transform_edt(local)
    widths = 2.0 * distance[skeleton]
    metrics["stroke_width_mean_norm"] = Metric(float(widths.mean() / bbox_height), float(widths.mean()), bbox_height)
    metrics["stroke_width_cv"] = _coefficient_of_variation(widths.tolist(), minimum_count=2)
    neighbor_count = ndimage.convolve(skeleton.astype(np.uint8), np.ones((3, 3), dtype=np.uint8), mode="constant") - skeleton
    metrics["skeleton_endpoint_count"] = Metric(int(np.count_nonzero(skeleton & (neighbor_count == 1))))
    orientations: list[float] = []
    for y, x in skeleton_points.tolist():
        neighbors = [
            (neighbor_y, neighbor_x)
            for neighbor_y in range(max(0, y - 1), min(skeleton.shape[0], y + 2))
            for neighbor_x in range(max(0, x - 1), min(skeleton.shape[1], x + 2))
            if (neighbor_y, neighbor_x) != (y, x) and skeleton[neighbor_y, neighbor_x]
        ]
        if len(neighbors) != 2:
            continue
        first, second = neighbors
        orientations.append(math.atan2(second[0] - first[0], second[1] - first[1]))
    if orientations:
        resultant = abs(np.mean(np.exp(2j * np.asarray(orientations))))
        metrics["direction_coherence"] = Metric(float(resultant))
    else:
        metrics["direction_coherence"] = Metric(None, missing_code="SKELETON_UNSTABLE")
    return metrics


def _tonal_metrics(image: np.ndarray) -> dict[str, Metric]:
    foreground = image < 254
    values = image[foreground]
    if values.size == 0:
        return {
            code: Metric(None, missing_code="EMPTY_FOREGROUND")
            for code in ("gray_mean_ink", "gray_entropy_ink", "local_contrast_ink", "edge_spread_ink")
        }
    quantized = np.floor(values.astype(float) * 32.0 / 256.0).astype(int)
    if np.unique(quantized).size < 3:
        return {
            code: Metric(None, missing_code="INSUFFICIENT_TONAL_RANGE")
            for code in ("gray_mean_ink", "gray_entropy_ink", "local_contrast_ink", "edge_spread_ink")
        }
    darkness = 1.0 - values.astype(float) / 255.0
    counts = np.bincount(quantized, minlength=32).astype(float)
    probability = counts[counts > 0] / counts.sum()
    normalized = image.astype(float) / 255.0
    gradient_x = ndimage.sobel(normalized, axis=1, mode="nearest")
    gradient_y = ndimage.sobel(normalized, axis=0, mode="nearest")
    boundary = ndimage.binary_dilation(foreground) ^ ndimage.binary_erosion(foreground)
    gradient = np.hypot(gradient_x, gradient_y)
    edge_value = float(gradient[boundary].mean()) if np.any(boundary) else 0.0
    return {
        "gray_mean_ink": Metric(float(darkness.mean()), float(darkness.sum()), int(values.size)),
        "gray_entropy_ink": Metric(float(-(probability * np.log2(probability)).sum())),
        "local_contrast_ink": Metric(float(np.std(values.astype(float) / 255.0, ddof=0))),
        "edge_spread_ink": Metric(edge_value, edge_value * 255.0, 255.0),
    }


def _coefficient_of_variation(values: list[float], minimum_count: int) -> Metric:
    if len(values) < minimum_count:
        return Metric(None, missing_code="SEQUENCE_TOO_SHORT")
    mean = float(np.mean(values))
    if mean == 0:
        return Metric(None, missing_code="ZERO_DENOMINATOR")
    deviation = float(np.std(values, ddof=0))
    return Metric(deviation / mean, deviation, mean)


def _measurement_record(
    *,
    definition: dict[str, Any],
    metric: Metric,
    stimulus_id: str,
    asset_id: str,
    extraction_run_id: str,
    representation: str,
    feature_record_id: str,
    input_sha256: str,
    computed_at: str,
    algorithm_config_sha256: str,
    software_environment_sha256: str,
    source_contract_sha256: str,
    fixture_only: bool,
) -> dict[str, Any]:
    value = _finite_number(metric.value)
    numerator = _finite_number(metric.numerator)
    denominator = _finite_number(metric.denominator)
    missing_code = metric.missing_code if value is None else None
    applicability = definition["cross_script_comparability"] if value is not None else "not_applicable"
    dimensions = sorted({definition["dimensions"]["primary"], *definition["dimensions"]["secondary"]})
    constructs = sorted({mapping["construct_code"] for mapping in definition["construct_mappings"]})
    return {
        "schema_version": "1.0.0",
        "measurement_id": _stable_id("measurement", feature_record_id, definition["feature_code"]),
        "feature_record_id": feature_record_id,
        "stimulus_id": stimulus_id,
        "asset_id": asset_id,
        "extraction_run_id": extraction_run_id,
        "representation": representation,
        "normalization_profile": "task01_frozen",
        "feature_code": definition["feature_code"],
        "feature_definition_version": definition["definition_version"],
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unit": definition["unit"],
        "applicability": applicability,
        "measurement_status": "valid" if value is not None else "missing",
        "missing_code": (missing_code or "MEASUREMENT_UNAVAILABLE") if value is None else None,
        "algorithm_config_sha256": algorithm_config_sha256,
        "input_sha256": input_sha256,
        "computed_at": computed_at,
        "software_environment_sha256": software_environment_sha256,
        "source_contract_sha256": source_contract_sha256,
        "dimensions": dimensions,
        "constructs": constructs,
        "fixture_only": fixture_only,
        "legacy_v1_context": None,
    }


def _load_task01_inputs(
    root: Path,
    handoff_file: Path,
    allow_fixture: bool,
    accepted_commit: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    errors = _validate_task01_at_checkpoint(handoff_file, root, accepted_commit)
    if errors:
        raise VisionSystemError("TASK01_HANDOFF_INVALID", "; ".join(errors[:20]))
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    if handoff.get("task_id") != "TASK-01" or handoff.get("handoff_schema_version") != "2.0.0":
        raise VisionSystemError("TASK01_HANDOFF_INCOMPATIBLE", "TASK-01 handoff 2.0.0 is required")
    if not handoff.get("readiness", {}).get("engineering_ready"):
        raise VisionSystemError("TASK01_ENGINEERING_NOT_READY", "upstream engineering_ready is false")
    entrypoint = next((item for item in handoff.get("next_task_entrypoints", []) if item.get("task_id") == "TASK-02"), None)
    if not entrypoint:
        raise VisionSystemError("TASK01_ENTRYPOINT_MISSING", "TASK-02 entrypoint is absent")
    if entrypoint.get("status") == "fixture_only" and not allow_fixture:
        raise VisionSystemError("FIXTURE_OPT_IN_REQUIRED", "pass allow_fixture=True for the accepted synthetic input")
    if entrypoint.get("status") not in {"fixture_only", "passed"}:
        raise VisionSystemError("TASK01_ENTRYPOINT_BLOCKED", str(entrypoint.get("status")))
    candidates_path = _safe_repo_file(root, entrypoint["path"])
    stimulus_artifact = next((item for item in handoff["outputs"] if item.get("logical_type") == "fixture_stimuli"), None)
    if not stimulus_artifact:
        raise VisionSystemError("TASK01_STIMULUS_MISSING", "fixture_stimuli output is absent")
    stimuli_path = _safe_repo_file(root, stimulus_artifact["path"])
    candidates = _read_jsonl(candidates_path)
    stimuli = _read_jsonl(stimuli_path)
    if not stimuli:
        raise VisionSystemError("TASK01_STIMULUS_EMPTY", str(stimuli_path.relative_to(root)))
    for stimulus in stimuli:
        if stimulus.get("qc", {}).get("status") != "passed":
            raise VisionSystemError("TASK01_STIMULUS_QC_NOT_PASSED", stimulus.get("stimulus_id", "unknown"))
        if stimulus.get("rights_tier") != "open":
            raise VisionSystemError("TASK01_RIGHTS_NOT_OPEN", stimulus.get("stimulus_id", "unknown"))
        if stimulus.get("release_status") == "fixture_only" and not allow_fixture:
            raise VisionSystemError("FIXTURE_OPT_IN_REQUIRED", stimulus.get("stimulus_id", "unknown"))
    return handoff, candidates, stimuli


def _validate_task01_at_checkpoint(handoff_file: Path, root: Path, accepted_commit: str) -> list[str]:
    """Retain strict artifact checks while proving producer files at the accepted checkpoint."""
    errors = validate_handoff(handoff_file, root)
    handoff = json.loads(handoff_file.read_text(encoding="utf-8"))
    declared = {
        item["path"]: item["sha256"]
        for item in handoff.get("producer_provenance", {}).get("files", [])
        if isinstance(item, dict) and {"path", "sha256"} <= item.keys()
    }
    relative_handoff = handoff_file.relative_to(root).as_posix()
    checkpoint_handoff = _git_blob(root, accepted_commit, relative_handoff)
    if checkpoint_handoff is None or hashlib.sha256(checkpoint_handoff).hexdigest() != sha256_file(handoff_file):
        errors.append(f"accepted checkpoint handoff mismatch: {relative_handoff}")
    retained: list[str] = []
    for error in errors:
        prefix = "producer hash mismatch: "
        if not error.startswith(prefix):
            retained.append(error)
            continue
        path = error[len(prefix):]
        blob = _git_blob(root, accepted_commit, path)
        if blob is None or hashlib.sha256(blob).hexdigest() != declared.get(path):
            retained.append(f"accepted checkpoint producer hash mismatch: {path}")
    return retained


def _git_blob(root: Path, commit: str, path: str) -> bytes | None:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        return None
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout if result.returncode == 0 else None


def _validated_asset_path(root: Path, reference: dict[str, Any], candidate: dict[str, Any]) -> Path:
    if candidate.get("asset_role") != reference.get("asset_role"):
        raise VisionSystemError("ASSET_ROLE_MISMATCH", reference["asset_id"])
    if candidate.get("asset_ref") != reference.get("asset_ref"):
        raise VisionSystemError("ASSET_REFERENCE_MISMATCH", reference["asset_id"])
    if candidate.get("automated_qc", {}).get("status") != "passed" or candidate.get("curation_status") != "passed":
        raise VisionSystemError("ASSET_QC_NOT_PASSED", reference["asset_id"])
    path = _safe_repo_file(root, reference["asset_ref"]["path"])
    if path.stat().st_size != reference["asset_ref"]["byte_size"]:
        raise VisionSystemError("ASSET_BYTE_SIZE_MISMATCH", reference["asset_id"])
    if sha256_file(path) != reference["asset_ref"]["sha256"]:
        raise VisionSystemError("ASSET_HASH_MISMATCH", reference["asset_id"])
    return path


def _safe_repo_file(root: Path, value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise VisionSystemError("UNSAFE_PATH", value)
    path = (root / Path(*pure.parts)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise VisionSystemError("UNSAFE_PATH", value)
    return path


def _load_grayscale(path: Path) -> np.ndarray:
    try:
        with Image.open(path) as image:
            image.load()
            return np.asarray(image.convert("L"), dtype=np.uint8)
    except Exception as error:
        raise VisionSystemError("IMAGE_DECODE_FAILED", path.name) from error


def _measurement_validator(schema_root: Path) -> Draft202012Validator:
    schema = json.loads((schema_root / "visual_measurement.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _software_environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "architecture": platform.machine(),
        "numpy": np.__version__,
        "pillow": version("Pillow"),
        "scipy": version("scipy"),
        "scikit_image": version("scikit-image"),
    }


def _finite_number(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        raise VisionSystemError("NONFINITE_MEASUREMENT", str(value))
    return int(value) if isinstance(value, (int, np.integer)) else float(value)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _failure(stimulus_id: str, representation: str, code: str, message: str) -> dict[str, str]:
    return {
        "stimulus_id": stimulus_id,
        "representation": representation,
        "failure_code": code,
        "message": message,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n" for record in records)
    path.write_text(payload, encoding="utf-8")


def _publish_run(output: Path, records: list[dict[str, Any]], failures: list[dict[str, Any]], manifest: dict[str, Any], registry: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        _write_jsonl(staging / "measurements.jsonl", records)
        _write_jsonl(staging / "failures.jsonl", failures)
        _write_json(staging / "run_manifest.json", manifest)
        _write_json(staging / "feature_registry.json", registry)
        for path in staging.iterdir():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        staging.rename(output)
    except Exception:
        for path in staging.glob("*"):
            path.unlink(missing_ok=True)
        staging.rmdir()
        raise
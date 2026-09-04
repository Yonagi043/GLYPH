"""Deterministic A/B/C representations with immutable parent provenance."""
from __future__ import annotations

import copy
import io
import math
import warnings
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from . import PROTOCOL_VERSION
from .catalog import canonical_json, normalize_repo_path, sha256_file, stable_id
from .qc import inspect_image, target_geometry_bbox


class RepresentationNotApplicable(ValueError):
    pass


def config_sha256(config: dict[str, Any]) -> str:
    import hashlib

    identity_config = copy.deepcopy(config)
    if identity_config.get("protocol_version") == "1.0.0":
        # Non-visual contract upgrades must not change visual v1 representation IDs.
        identity_config["schema_versions"].update(
            {
                "ecological_stimulus": "1.0.0",
                "rights_evidence": "1.0.0",
                "handoff_manifest": "1.0.0",
            }
        )
    return hashlib.sha256(canonical_json(identity_config)).hexdigest()


def transform_candidate(
    record: dict[str, Any],
    input_path: str | Path,
    output_dir: str | Path,
    representation: str,
    config: dict[str, Any],
    *,
    logical_output_root: str,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    if representation not in {"A_layout", "B_shape", "C_ink"}:
        raise ValueError(f"unsupported representation: {representation}")
    source_path = Path(input_path)
    source_sha256 = sha256_file(source_path)
    if source_sha256 != (record.get("asset_ref") or {}).get("sha256"):
        raise ValueError("QC_HASH_MISMATCH")

    geometry = _target_geometry(record) if representation == "B_shape" else None
    inspection = inspect_image(
        source_path,
        max_pixels=int(config["qc"]["max_pixels"]),
        target_geometry=geometry,
        assume_srgb_without_profile=bool(config["qc"]["assume_srgb_without_profile"]),
    )
    failures = inspection["automated_qc"]["failure_codes"]
    if failures:
        raise ValueError(",".join(failures))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(source_path) as opened:
            opened.load()
            input_size = opened.size
            image = ImageOps.exif_transpose(opened)
    parameters: dict[str, Any]
    outputs: list[tuple[str, Image.Image, dict[str, Any]]]
    if representation == "A_layout":
        rendered = _layout_image(image)
        parameters = {
            "exif_orientation": True,
            "preserve_canvas": True,
            "input_size": list(input_size),
            "output_size": list(rendered.size),
        }
        outputs = [("A_layout", rendered, parameters)]
    elif representation == "B_shape":
        shape, mask, parameters = _shape_images(image, geometry, config["representations"]["B_shape"])
        outputs = [("B_shape", shape, parameters), ("mask", mask, parameters)]
    else:
        rendered, parameters = _ink_image(image, config["representations"]["C_ink"])
        outputs = [("C_ink", rendered, parameters)]

    config_hash = config_sha256(config)
    encoded = [(role, _png_bytes(output), role_parameters) for role, output, role_parameters in outputs]
    result: list[dict[str, Any]] = []
    destinations: list[tuple[Path, bytes]] = []
    for role, payload, role_parameters in encoded:
        import hashlib

        output_sha256 = hashlib.sha256(payload).hexdigest()
        asset_id = stable_id(
            "asset",
            {
                "parent_asset_id": record["asset_id"],
                "asset_role": role,
                "config_sha256": config_hash,
                "parameters": role_parameters,
                "output_sha256": output_sha256,
            },
        )
        filename = f"{asset_id}.{role}.png"
        logical_path = normalize_repo_path(str(PurePosixPath(logical_output_root) / filename))
        destination = Path(output_dir) / filename
        destinations.append((destination, payload))
        result.append(
            _derived_record(
                record,
                asset_id=asset_id,
                role=role,
                logical_path=logical_path,
                payload=payload,
                output_size=outputs[len(result)][1].size,
                output_mode=outputs[len(result)][1].mode,
                config_hash=config_hash,
                parent_sha256=source_sha256,
                parameters=role_parameters,
            )
        )

    existing = [str(path) for path, _ in destinations if path.exists()]
    if existing:
        raise FileExistsError("derived output exists: " + ", ".join(existing))
    if not dry_run:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        for destination, payload in destinations:
            destination.write_bytes(payload)
    return result


def _target_geometry(record: dict[str, Any]) -> dict[str, Any]:
    geometry = record.get("target_geometry")
    if not geometry or not geometry.get("confirmed_by"):
        raise ValueError("QC_HUMAN_BOUNDARY_REQUIRED")
    try:
        target_geometry_bbox(geometry)
    except ValueError as error:
        raise ValueError("QC_HUMAN_BOUNDARY_REQUIRED") from error
    return geometry


def _target_bbox(record: dict[str, Any]) -> list[float]:
    try:
        return target_geometry_bbox(_target_geometry(record))
    except ValueError as error:
        raise ValueError("QC_HUMAN_BOUNDARY_REQUIRED")


def _layout_image(image: Image.Image) -> Image.Image:
    if image.mode in {"1", "L", "LA", "RGB", "RGBA"}:
        return image.copy()
    if image.mode == "P" and "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


def _flatten_grayscale(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    return ImageOps.grayscale(white.convert("RGB"))


def _shape_images(
    image: Image.Image,
    geometry: dict[str, Any],
    shape_config: dict[str, Any],
) -> tuple[Image.Image, Image.Image, dict[str, Any]]:
    bbox = target_geometry_bbox(geometry, width=image.width, height=image.height)
    left, top, right, bottom = bbox
    integer_bbox = (math.floor(left), math.floor(top), math.ceil(right), math.ceil(bottom))
    grayscale = _flatten_grayscale(image)
    if geometry["geometry_type"] == "polygon":
        coordinates = [float(value) for value in geometry["coordinates"]]
        points = [(coordinates[index], coordinates[index + 1]) for index in range(0, len(coordinates), 2)]
        polygon_mask = Image.new("L", grayscale.size, 0)
        ImageDraw.Draw(polygon_mask).polygon(points, fill=255)
        grayscale = Image.composite(grayscale, Image.new("L", grayscale.size, 255), polygon_mask)
    cropped = grayscale.crop(integer_bbox)
    canvas_width, canvas_height = [int(value) for value in shape_config["canvas_px"]]
    content_width, content_height = [int(value) for value in shape_config["content_px"]]
    scale = min(content_width / cropped.width, content_height / cropped.height)
    output_width = max(1, round(cropped.width * scale))
    output_height = max(1, round(cropped.height * scale))
    resized = cropped.resize((output_width, output_height), Image.Resampling.LANCZOS)
    offset_x = (canvas_width - output_width) // 2
    offset_y = (canvas_height - output_height) // 2
    shape = Image.new("L", (canvas_width, canvas_height), int(shape_config["background"]))
    shape.paste(resized, (offset_x, offset_y))
    threshold = int(shape_config["threshold"])
    mask = shape.point(lambda value: 0 if value < threshold else 255, mode="L")
    parameters = {
        "bbox": list(integer_bbox),
        "scale": scale,
        "offset": [offset_x, offset_y],
        "canvas_px": [canvas_width, canvas_height],
        "content_px": [content_width, content_height],
        "threshold": threshold,
        "matrix": [scale, 0.0, offset_x - scale * integer_bbox[0], 0.0, scale, offset_y - scale * integer_bbox[1], 0.0, 0.0, 1.0],
    }
    if geometry["geometry_type"] == "polygon":
        parameters["geometry_type"] = "polygon"
        parameters["polygon"] = [float(value) for value in geometry["coordinates"]]
    return shape, mask, parameters


def _ink_image(image: Image.Image, ink_config: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    grayscale = _flatten_grayscale(image)
    values = np.asarray(grayscale, dtype=np.uint8)
    if len(np.unique(values)) < int(ink_config["minimum_gray_levels"]):
        raise RepresentationNotApplicable("C_INK_NOT_APPLICABLE")
    width, height = grayscale.size
    fraction = float(ink_config["corner_fraction"])
    patch_width = max(1, round(width * fraction))
    patch_height = max(1, round(height * fraction))
    corners = np.concatenate(
        [
            values[:patch_height, :patch_width].ravel(),
            values[:patch_height, -patch_width:].ravel(),
            values[-patch_height:, :patch_width].ravel(),
            values[-patch_height:, -patch_width:].ravel(),
        ]
    )
    background = float(np.median(corners))
    target = int(ink_config["target_background"])
    corrected = np.clip(values.astype(np.float32) + target - background, 0, 255).astype(np.uint8)
    parameters = {
        "background_correction": ink_config["background_correction"],
        "corner_fraction": fraction,
        "estimated_background": background,
        "target_background": target,
        "input_gray_levels": int(len(np.unique(values))),
    }
    return Image.fromarray(corrected), parameters


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=9, optimize=False)
    return buffer.getvalue()


def _derived_record(
    parent: dict[str, Any],
    *,
    asset_id: str,
    role: str,
    logical_path: str,
    payload: bytes,
    output_size: tuple[int, int],
    output_mode: str,
    config_hash: str,
    parent_sha256: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    import hashlib

    width, height = output_size
    record = {
        "schema_version": parent["schema_version"],
        "asset_id": asset_id,
        "record_origin": parent["record_origin"],
        "source_id": parent["source_id"],
        "parent_asset_id": parent["asset_id"],
        "work_id": parent.get("work_id"),
        "asset_role": role,
        "candidate_kind": parent["candidate_kind"],
        "asset_ref": {
            "path": logical_path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mime_type": "image/png",
            "byte_size": len(payload),
        },
        "pixel_metadata": {
            "width_px": width,
            "height_px": height,
            "mode": output_mode,
            "color_space": "grayscale" if output_mode in {"1", "L", "LA"} else "sRGB",
            "has_alpha": "A" in output_mode,
            "dpi_x": None,
            "dpi_y": None,
        },
        "rights_tier": parent["rights_tier"],
        "transform": {
            "tool": "glyph-assets",
            "tool_version": PROTOCOL_VERSION,
            "config_sha256": config_hash,
            "parent_sha256": parent_sha256,
            "parameters": copy.deepcopy(parameters),
        },
        "automated_qc": {
            "status": "passed",
            "decodable": True,
            "pixel_limit_status": "passed",
            "hash_duplicate_status": "unique",
            "perceptual_duplicate_status": "not_checked",
            "boundary_status": "passed" if role in {"B_shape", "mask"} else "not_applicable",
            "format_status": "passed",
            "failure_codes": [],
        },
        "classification": copy.deepcopy(parent["classification"]),
        "target_geometry": copy.deepcopy(parent.get("target_geometry")),
        "curation_status": parent["curation_status"],
        "exclusion_codes": list(parent["exclusion_codes"]),
        "review": copy.deepcopy(parent["review"]),
        "award_context": copy.deepcopy(parent.get("award_context")),
        "font_metadata": copy.deepcopy(parent.get("font_metadata")),
    }
    return record

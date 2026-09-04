"""Bounded image/font inspection and deterministic duplicate diagnostics."""
from __future__ import annotations

import warnings
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps
from fontTools.ttLib import TTFont

from .catalog import sha256_file, stable_id


SUPPORTED_FORMATS = {"BMP", "GIF", "JPEG", "PNG", "PPM", "TIFF", "WEBP"}


def _color_space(mode: str, *, assume_srgb_without_profile: bool) -> str:
    if mode in {"1", "L", "LA", "I", "F"}:
        return "grayscale"
    if mode == "P":
        return "indexed"
    if mode == "CMYK":
        return "CMYK"
    return "sRGB" if assume_srgb_without_profile else "unknown"


def _dpi(info: dict[str, Any]) -> tuple[float | None, float | None]:
    value = info.get("dpi")
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    if isinstance(value, (int, float)):
        return float(value), float(value)
    return None, None


def _dhash(image: Image.Image) -> str:
    sample = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(sample.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{value:016x}"


def inspect_image(
    path: str | Path,
    *,
    max_pixels: int,
    target_bbox: list[float] | None = None,
    target_geometry: dict[str, Any] | None = None,
    assume_srgb_without_profile: bool = False,
) -> dict[str, Any]:
    if target_bbox is not None and target_geometry is not None:
        raise ValueError("provide target_bbox or target_geometry, not both")
    if target_bbox is not None:
        target_geometry = {"geometry_type": "bbox", "coordinates": target_bbox}
    image_path = Path(path)
    result: dict[str, Any] = {
        "sha256": sha256_file(image_path),
        "byte_size": image_path.stat().st_size,
        "pixel_metadata": None,
        "perceptual_hash": None,
        "format": None,
        "mime_type": "application/octet-stream",
        "automated_qc": {
            "status": "failed",
            "decodable": False,
            "pixel_limit_status": "not_applicable",
            "hash_duplicate_status": "unique",
            "perceptual_duplicate_status": "not_checked",
            "boundary_status": "not_applicable",
            "format_status": "failed",
            "failure_codes": [],
        },
    }
    qc = result["automated_qc"]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(image_path) as image:
                width, height = image.size
                result["format"] = image.format
                result["mime_type"] = Image.MIME.get(image.format or "", "application/octet-stream")
                dpi_x, dpi_y = _dpi(image.info)
                result["pixel_metadata"] = {
                    "width_px": width,
                    "height_px": height,
                    "mode": image.mode,
                    "color_space": _color_space(
                        image.mode,
                        assume_srgb_without_profile=assume_srgb_without_profile,
                    ),
                    "has_alpha": "A" in image.getbands() or "transparency" in image.info,
                    "dpi_x": dpi_x,
                    "dpi_y": dpi_y,
                }
                qc["decodable"] = True
                qc["format_status"] = "passed" if image.format in SUPPORTED_FORMATS else "failed"
                if qc["format_status"] == "failed":
                    qc["failure_codes"].append("QC_FORMAT_UNSUPPORTED")
                if width * height > max_pixels:
                    qc["pixel_limit_status"] = "failed"
                    qc["failure_codes"].append("QC_PIXEL_LIMIT_EXCEEDED")
                else:
                    qc["pixel_limit_status"] = "passed"
                    image.load()
                    result["perceptual_hash"] = _dhash(ImageOps.exif_transpose(image))
                if target_geometry is None:
                    qc["boundary_status"] = "needs_review"
                else:
                    try:
                        target_geometry_bbox(target_geometry, width=width, height=height)
                        qc["boundary_status"] = "passed"
                    except ValueError:
                        qc["boundary_status"] = "failed"
                        qc["failure_codes"].append("QC_BOUNDARY_AMBIGUOUS")
    except (OSError, ValueError, SyntaxError):
        qc["failure_codes"].append("QC_DECODE_FAILED")

    if qc["decodable"] and qc["format_status"] == "passed" and qc["pixel_limit_status"] == "passed":
        qc["status"] = "passed" if qc["boundary_status"] in {"passed", "not_applicable"} else "needs_review"
    qc["failure_codes"] = sorted(set(qc["failure_codes"]))
    return result


def _bbox_is_valid(bbox: list[float], width: int, height: int) -> bool:
    if len(bbox) != 4:
        return False
    left, top, right, bottom = bbox
    return 0 <= left < right <= width and 0 <= top < bottom <= height


def target_geometry_bbox(
    geometry: dict[str, Any],
    *,
    width: int | None = None,
    height: int | None = None,
) -> list[float]:
    geometry_type = geometry.get("geometry_type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in coordinates
    ):
        raise ValueError("target geometry coordinates must be finite numbers")
    if geometry_type == "bbox":
        if len(coordinates) != 4:
            raise ValueError("target bbox must contain four coordinates")
        bbox = [float(value) for value in coordinates]
    elif geometry_type == "polygon":
        if len(coordinates) < 6 or len(coordinates) % 2:
            raise ValueError("target polygon must contain at least three x/y points")
        points = [(float(coordinates[index]), float(coordinates[index + 1])) for index in range(0, len(coordinates), 2)]
        if len(set(points)) < 3:
            raise ValueError("target polygon must contain three distinct points")
        area = abs(
            sum(
                x_value * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * y_value
                for index, (x_value, y_value) in enumerate(points)
            )
        ) / 2
        if area == 0:
            raise ValueError("target polygon must have non-zero area")
        bbox = [
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        ]
    else:
        raise ValueError("target geometry type must be bbox or polygon")
    left, top, right, bottom = bbox
    if left < 0 or top < 0 or left >= right or top >= bottom:
        raise ValueError("target geometry bounds are invalid")
    if width is not None and right > width:
        raise ValueError("target geometry exceeds image width")
    if height is not None and bottom > height:
        raise ValueError("target geometry exceeds image height")
    return bbox


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def duplicate_annotations(records: Iterable[dict[str, Any]], *, near_threshold: int) -> list[dict[str, Any]]:
    items = [dict(record) for record in records]
    exact_groups: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(items):
        exact_groups[str(record["sha256"])].append(index)
    for indexes in exact_groups.values():
        if len(indexes) > 1:
            for index in indexes:
                items[index]["hash_duplicate_status"] = "duplicate_exact"
                items[index]["duplicate_of"] = items[indexes[0]].get("asset_id") if index != indexes[0] else None
        else:
            items[indexes[0]]["hash_duplicate_status"] = "unique"
            items[indexes[0]]["duplicate_of"] = None

    for index, record in enumerate(items):
        record["perceptual_duplicate_status"] = "unique" if record.get("perceptual_hash") else "not_checked"
        record["near_duplicate_of"] = None
        if record["hash_duplicate_status"] == "duplicate_exact" or not record.get("perceptual_hash"):
            continue
        for previous in items[:index]:
            if previous.get("hash_duplicate_status") == "duplicate_exact" or not previous.get("perceptual_hash"):
                continue
            if hamming_distance(record["perceptual_hash"], previous["perceptual_hash"]) <= near_threshold:
                record["perceptual_duplicate_status"] = "duplicate_near"
                record["near_duplicate_of"] = previous.get("asset_id")
                break
    return items


def script_purity_violations(text: str, script_code: str) -> list[str]:
    violations: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character.isspace() or character.isdigit() or _is_common(codepoint):
            continue
        if not _in_script(codepoint, script_code):
            violations.append(f"U+{codepoint:04X}")
    return violations


def _is_common(codepoint: int) -> bool:
    return 0x0020 <= codepoint <= 0x0040 or 0x005B <= codepoint <= 0x0060 or 0x007B <= codepoint <= 0x00BF


def _in_script(codepoint: int, script_code: str) -> bool:
    ranges = {
        "Latn": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F), (0x1E00, 0x1EFF)),
        "Hani": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF)),
        "Kana": ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9D)),
        "Hang": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)),
    }
    if script_code not in ranges:
        raise ValueError(f"unsupported script code: {script_code}")
    return any(start <= codepoint <= end for start, end in ranges[script_code])


def inspect_font(path: str | Path) -> dict[str, Any]:
    font_path = Path(path)
    sha256 = sha256_file(font_path)
    try:
        font = TTFont(font_path, lazy=True)
        family_name = _font_name(font, 1) or font_path.stem
        subfamily_name = _font_name(font, 2)
        postscript_name = _font_name(font, 6)
        version = _font_name(font, 5)
        cmap = font.getBestCmap() or {}
        axes: list[str] = []
        if "fvar" in font:
            for axis in font["fvar"].axes:
                axes.append(f"{axis.axisTag}:{axis.minValue:g}:{axis.defaultValue:g}:{axis.maxValue:g}")
        coverage = [
            f"{script}:{sum(_in_script(codepoint, script) for codepoint in cmap)}"
            for script in ("Latn", "Hani", "Kana", "Hang")
            if any(_in_script(codepoint, script) for codepoint in cmap)
        ]
        sidecars = sorted(
            item.name
            for item in font_path.parent.iterdir()
            if item.is_file() and item != font_path and re_sidecar(item.name)
        )
        regional = "CN" if "SC" in font_path.stem else "JP" if "JP" in font_path.stem else "KR" if "KR" in font_path.stem else None
        result = {
            "sha256": sha256,
            "byte_size": font_path.stat().st_size,
            "mime_type": "font/otf" if font_path.suffix.lower() == ".otf" else "font/ttf",
            "parse_error": None,
            "font_metadata": {
                "font_id": stable_id("font", {"sha256": sha256}),
                "family_id": stable_id("font_family", {"family_name": family_name.casefold()}),
                "family_name": family_name,
                "subfamily_name": subfamily_name,
                "postscript_name": postscript_name,
                "version": version,
                "is_variable": bool(axes),
                "variable_axes": axes,
                "unicode_coverage": coverage,
                "unicode_codepoint_count": len(cmap),
                "regional_glyphs": regional,
                "license_hint": {
                    "internal_text": _font_name(font, 13),
                    "internal_url": _font_name(font, 14),
                    "sidecar_files": sidecars,
                },
            },
        }
        font.close()
        return result
    except Exception as exc:
        return {
            "sha256": sha256,
            "byte_size": font_path.stat().st_size,
            "mime_type": "application/octet-stream",
            "parse_error": f"{type(exc).__name__}: {exc}",
            "font_metadata": None,
        }


def re_sidecar(filename: str) -> bool:
    upper = filename.upper()
    return upper.startswith(("LICENSE", "LICENCE", "NOTICE", "OFL")) or upper.endswith((".LICENSE", ".LICENCE"))


def _font_name(font: TTFont, name_id: int) -> str | None:
    if "name" not in font:
        return None
    preferred = sorted(
        (name for name in font["name"].names if name.nameID == name_id),
        key=lambda item: (item.langID not in {0x0409, 0}, item.platformID != 3),
    )
    for name in preferred:
        try:
            value = name.toUnicode().strip()
        except UnicodeDecodeError:
            continue
        if value:
            return value
    return None

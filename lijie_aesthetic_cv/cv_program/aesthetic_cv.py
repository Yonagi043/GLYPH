#!/usr/bin/env python3
"""Explainable MVP for the 10 aesthetic CV indicators.

The program intentionally returns measurements and a transparent proxy score.
It does not claim that the proxy is a validated universal measure of beauty.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - helpful command-line error
    print("缺少依赖，请先运行: python -m pip install -r requirements.txt", file=sys.stderr)
    raise


EPS = 1e-9
DIMENSIONS = [
    "balance", "symmetry", "proportion", "unity", "rhythm",
    "brushwork", "structure", "spacing", "ink", "qi_proxy",
]
DEFAULT_WEIGHTS = {name: 0.1 for name in DIMENSIONS}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def clip100(value: float) -> float:
    return float(max(0.0, min(100.0, value)))


def exp_score(distance: float, scale: float) -> float:
    """Map a non-negative deviation to 0-100 with 100 at zero deviation."""
    scale = max(float(scale), EPS)
    return clip100(100.0 * math.exp(-((float(distance) / scale) ** 2)))


def robust_cv(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=np.float32).ravel()
    if values.size == 0:
        return 0.0
    mean = float(np.mean(values))
    return float(np.std(values) / (abs(mean) + EPS))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_image(path: Path) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Load BGR image and optional alpha mask."""
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"无法读取图片: {path}")
    alpha = None
    if raw.ndim == 2:
        bgr = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    elif raw.shape[2] == 4:
        bgr = raw[:, :, :3]
        alpha = raw[:, :, 3]
    else:
        bgr = raw[:, :, :3]
    return bgr, alpha


def _background_mask(gray: np.ndarray, alpha: Optional[np.ndarray]) -> np.ndarray:
    """Return a foreground mask using alpha or an adaptive background estimate."""
    if alpha is not None:
        return (alpha > 8).astype(np.uint8) * 255

    # Estimate a light/dark background from the border. Otsu is intentionally
    # kept as a deterministic baseline; QC records the resulting foreground area.
    border = np.concatenate((gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]))
    bg = float(np.median(border))
    if bg >= 127.0:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Remove tiny compression speckles while preserving narrow strokes.
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def preprocess(bgr: np.ndarray, alpha: Optional[np.ndarray]) -> Dict[str, Any]:
    """Create A(layout), B(shape-normalized), C(ink-preserving) channels."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mask = _background_mask(gray, alpha)
    mask = _largest_components(mask, keep_fraction=0.002)
    h, w = gray.shape[:2]
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise ValueError("未检测到前景，请检查背景或图片质量")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    pad = max(2, int(round(0.03 * max(w, h))))
    bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
    bx1, by1 = min(w, x1 + pad), min(h, y1 + pad)
    crop_mask = mask[by0:by1, bx0:bx1]
    crop_gray = gray[by0:by1, bx0:bx1]
    size = 512
    scale = min((size - 2 * pad) / max(crop_mask.shape[1], 1),
                (size - 2 * pad) / max(crop_mask.shape[0], 1))
    nw = max(1, int(round(crop_mask.shape[1] * scale)))
    nh = max(1, int(round(crop_mask.shape[0] * scale)))
    b_mask = cv2.resize(crop_mask, (nw, nh), interpolation=cv2.INTER_NEAREST)
    b_gray = cv2.resize(crop_gray, (nw, nh), interpolation=cv2.INTER_AREA)
    shape_mask = np.zeros((size, size), np.uint8)
    shape_gray = np.full((size, size), 255, np.uint8)
    ox, oy = (size - nw) // 2, (size - nh) // 2
    shape_mask[oy:oy + nh, ox:ox + nw] = b_mask
    shape_gray[oy:oy + nh, ox:ox + nw] = b_gray

    # C keeps gray values only inside the detected foreground.
    ink_gray = gray.copy()
    ink_gray[mask == 0] = 255
    return {
        "gray": gray,
        "mask": mask,
        "layout_gray": gray,
        "layout_mask": mask,
        "shape_gray": shape_gray,
        "shape_mask": shape_mask,
        "ink_gray": ink_gray,
        "bbox": [x0, y0, x1 - x0, y1 - y0],
        "canvas": [w, h],
        "shape_offset": [ox, oy],
        "shape_scale": float(scale),
    }


def _largest_components(mask: np.ndarray, keep_fraction: float = 0.002) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return mask
    total = float(mask.shape[0] * mask.shape[1])
    min_area = max(4.0, total * keep_fraction)
    result = np.zeros_like(mask)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= min_area:
            result[labels == label] = 255
    return result if np.any(result) else mask


def common_features(data: Dict[str, Any]) -> Dict[str, Any]:
    bmask = data["shape_mask"]
    binary = (bmask > 0).astype(np.uint8)
    # The default opencv-python wheel does not ship ximgproc. Use the
    # deterministic morphological fallback unless the contrib module exists.
    skeleton = cv2.ximgproc.thinning(bmask) if hasattr(cv2, "ximgproc") else _morph_skeleton(bmask)
    distance = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    contours, hierarchy = cv2.findContours(bmask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    components = _component_records(data["layout_mask"])
    return {
        "shape_binary": binary,
        "skeleton": skeleton,
        "distance": distance,
        "contours": contours,
        "hierarchy": hierarchy,
        "layout_components": components,
    }


def _morph_skeleton(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning fallback, implemented with NumPy/OpenCV only."""
    img = (mask > 0).astype(np.uint8)
    if not np.any(img):
        return img

    # Neighbours are named in clockwise order P2...P9 around a pixel P1.
    def neighbours(a: np.ndarray):
        p = np.pad(a, 1, mode="constant")
        return (
            p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:],
            p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2],
        )

    changed = True
    while changed:
        changed = False
        for phase in (0, 1):
            n = neighbours(img)
            b = sum(n)
            seq = n + (n[0],)
            a = sum((seq[k] == 0) & (seq[k + 1] == 1) for k in range(8))
            if phase == 0:
                m1 = (n[0] * n[2] * n[4]) == 0
                m2 = (n[2] * n[4] * n[6]) == 0
            else:
                m1 = (n[0] * n[2] * n[6]) == 0
                m2 = (n[0] * n[4] * n[6]) == 0
            remove = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & m1 & m2
            if np.any(remove):
                img[remove] = 0
                changed = True
    return img * 255


def _component_records(mask: np.ndarray) -> List[Dict[str, float]]:
    count, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    result = []
    for i in range(1, count):
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area <= 0:
            continue
        result.append({
            "area": area,
            "x": float(cents[i][0]),
            "y": float(cents[i][1]),
            "w": float(stats[i, cv2.CC_STAT_WIDTH]),
            "h": float(stats[i, cv2.CC_STAT_HEIGHT]),
        })
    return result


def _foreground_centroid(mask: np.ndarray) -> Tuple[float, float, float]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return 0.5, 0.5, 0.0
    h, w = mask.shape[:2]
    mass = float(len(xs))
    return float(np.mean(xs) / w), float(np.mean(ys) / h), mass / (w * h)


def score_balance(data: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    mask = data["layout_mask"]
    cx, cy, density = _foreground_centroid(mask)
    dx, dy = cx - 0.5, cy - 0.5
    h, w = mask.shape[:2]
    q = [
        np.mean(mask[:h // 2, :w // 2] > 0), np.mean(mask[:h // 2, w // 2:] > 0),
        np.mean(mask[h // 2:, :w // 2] > 0), np.mean(mask[h // 2:, w // 2:] > 0),
    ]
    quadrant_gap = float(max(q) - min(q))
    distance = math.sqrt(dx * dx + dy * dy)
    score = exp_score(distance, 0.20) * 0.7 + exp_score(quadrant_gap, 0.25) * 0.3
    return ({"centroid_x": cx, "centroid_y": cy, "offset_x": dx, "offset_y": dy,
             "foreground_density": density, "quadrant_density": q,
             "quadrant_gap": quadrant_gap}, clip100(score))


def score_symmetry(data: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    b = (data["shape_mask"] > 0).astype(np.uint8)
    denom = float(np.sum(b)) + EPS
    hflip = cv2.flip(b, 1)
    vflip = cv2.flip(b, 0)
    sh = 1.0 - float(np.sum(np.abs(b.astype(np.int16) - hflip.astype(np.int16)))) / denom
    sv = 1.0 - float(np.sum(np.abs(b.astype(np.int16) - vflip.astype(np.int16)))) / denom
    r180 = 1.0 - float(np.sum(np.abs(b.astype(np.int16) - cv2.rotate(b, cv2.ROTATE_180).astype(np.int16)))) / denom
    score = 100.0 * (0.4 * max(0.0, sh) + 0.4 * max(0.0, sv) + 0.2 * max(0.0, r180))
    return ({"horizontal": clip100(100 * sh), "vertical": clip100(100 * sv),
             "rotation_180": clip100(100 * r180)}, clip100(score))


def score_proportion(data: Dict[str, Any], common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    x, y, w, h = data["bbox"]
    canvas_w, canvas_h = data["canvas"]
    aspect = float(w / max(h, 1))
    occupancy = float(w * h / max(canvas_w * canvas_h, 1))
    mask = data["shape_mask"]
    area = float(np.sum(mask > 0))
    holes = _hole_area(mask)
    widths = common["distance"][common["skeleton"] > 0] * 2.0
    width_median = float(np.median(widths)) if widths.size else 0.0
    shape_scale = max(mask.shape)
    # Broad, intentionally non-prescriptive reference ranges for the MVP.
    s_aspect = exp_score(math.log(max(aspect, EPS) / 1.0), 0.65)
    s_occupancy = exp_score(math.log(max(occupancy, EPS) / 0.35), 1.1)
    s_void = exp_score((holes / max(area, 1.0) - 0.15), 0.20)
    score = 100.0 * (0.4 * s_aspect / 100 + 0.35 * s_occupancy / 100 + 0.25 * s_void / 100)
    return ({"bbox_width": w, "bbox_height": h, "aspect_ratio": aspect,
             "bbox_occupancy": occupancy, "hole_area_ratio": holes / max(area, 1.0),
             "stroke_width_median": width_median, "stroke_width_relative": width_median / shape_scale},
            clip100(score))


def _stroke_records(common: Dict[str, Any]) -> List[Dict[str, float]]:
    skel = (common["skeleton"] > 0).astype(np.uint8)
    dist = common["distance"]
    ys, xs = np.where(skel > 0)
    if len(xs) == 0:
        return []
    # Local width/orientation values are used as comparable units. A full
    # stroke-order recognizer is intentionally outside this image-only MVP.
    records = []
    for yy, xx in zip(ys[::max(1, len(ys) // 2000)], xs[::max(1, len(xs) // 2000)]):
        y0, y1, x0, x1 = max(0, yy - 1), min(skel.shape[0], yy + 2), max(0, xx - 1), min(skel.shape[1], xx + 2)
        local = skel[y0:y1, x0:x1]
        coords = np.argwhere(local > 0)
        if len(coords) >= 2:
            cov = np.cov(coords.T)
            vals, vecs = np.linalg.eigh(cov)
            vec = vecs[:, int(np.argmax(vals))]
            angle = float(math.atan2(vec[0], vec[1]))
        else:
            angle = 0.0
        records.append({"width": float(2 * dist[yy, xx]), "angle": angle})
    return records


def score_unity(data: Dict[str, Any], common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    records = _stroke_records(common)
    if len(records) < 2:
        return ({"style_units": len(records), "pairwise_distance": None}, 50.0)
    widths = np.array([r["width"] for r in records], dtype=np.float32)
    angles = np.array([r["angle"] for r in records], dtype=np.float32)
    width_cv = robust_cv(widths)
    # Circular orientation dispersion; 0 means same orientation, 1 means dispersed.
    orient_disp = float(1.0 - abs(np.mean(np.exp(1j * angles))))
    pairwise = float(min(1.0, 0.7 * width_cv + 0.3 * orient_disp))
    score = exp_score(pairwise, 0.45)
    return ({"style_units": len(records), "width_cv": width_cv,
             "orientation_dispersion": orient_disp, "pairwise_distance": pairwise}, score)


def _ordered_sequence(common: Dict[str, Any]) -> np.ndarray:
    components = common["layout_components"]
    if len(components) < 2:
        return np.array([], dtype=np.float32)
    # Sort component centers along their first principal axis.
    points = np.array([[c["x"], c["y"]] for c in components], dtype=np.float32)
    points -= points.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(points, full_matrices=False)
    order = np.argsort(points @ vt[0])
    ordered = [components[int(i)] for i in order]
    vals = []
    for a, b in zip(ordered, ordered[1:]):
        vals.append(math.hypot(a["x"] - b["x"], a["y"] - b["y"]))
    return np.asarray(vals, dtype=np.float32)


def score_rhythm(common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    seq = _ordered_sequence(common)
    if seq.size < 2:
        return ({"sequence_length": int(seq.size), "autocorrelation": None,
                 "spectral_peak_ratio": None}, 50.0)
    centered = seq - float(np.mean(seq))
    ac = np.correlate(centered, centered, mode="full")[seq.size - 1:]
    autocorr = float(ac[1] / (ac[0] + EPS)) if seq.size > 1 else 0.0
    fft = np.abs(np.fft.rfft(centered))[1:]
    spectral = float(np.max(fft) / (np.sum(fft) + EPS)) if fft.size else 0.0
    # Reward a visible but not perfectly rigid sequence; this is only a proxy.
    variation = robust_cv(seq)
    score = 100.0 * (0.45 * max(0.0, min(1.0, (autocorr + 1) / 2)) +
                     0.35 * max(0.0, min(1.0, spectral * 2)) +
                     0.20 * exp_score(abs(variation - 0.25), 0.25) / 100)
    return ({"sequence_length": int(seq.size), "spacing_sequence": seq.tolist(),
             "autocorrelation": autocorr, "spectral_peak_ratio": spectral,
             "spacing_cv": variation}, clip100(score))


def score_brushwork(common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    skel = common["skeleton"] > 0
    widths = common["distance"][skel] * 2.0
    if widths.size == 0:
        return ({"stroke_width_median": None, "stroke_width_cv": None}, 50.0)
    width_cv = robust_cv(widths)
    # Count skeleton endpoints and disconnected pieces.
    neighbours = cv2.filter2D(skel.astype(np.uint8), -1, np.ones((3, 3), np.uint8)) - skel
    endpoints = int(np.sum(skel & (neighbours == 1)))
    components = int(cv2.connectedComponents(skel.astype(np.uint8), 8)[0] - 1)
    roughness = float(np.std(widths) / (np.mean(widths) + EPS))
    break_rate = min(1.0, max(0.0, (components - 1) / max(1.0, endpoints + 1)))
    score = 0.55 * exp_score(width_cv, 0.65) + 0.30 * exp_score(roughness, 0.65) + 0.15 * (100 * (1 - break_rate))
    return ({"stroke_width_median": float(np.median(widths)), "stroke_width_mean": float(np.mean(widths)),
             "stroke_width_cv": width_cv, "skeleton_endpoints": endpoints,
             "skeleton_components": components, "break_rate": break_rate}, clip100(score))


def _grid_vector(mask: np.ndarray) -> List[float]:
    h, w = mask.shape[:2]
    # Eight triangular sectors around center, approximated by the 3x3 grid
    # with the center cell split out and normalized to eight directional bins.
    yy, xx = np.indices((h, w), dtype=np.float32)
    cx, cy = w / 2.0, h / 2.0
    dx, dy = xx - cx, yy - cy
    angle = (np.arctan2(-dy, dx) + 2 * np.pi) % (2 * np.pi)
    sector = np.floor((angle + np.pi / 8) / (np.pi / 4)).astype(np.int32) % 8
    result = []
    fg = mask > 0
    for i in range(8):
        denom = max(1, int(np.sum(sector == i)))
        result.append(float(np.sum(fg & (sector == i)) / denom))
    total = sum(result) + EPS
    return [float(v / total) for v in result]


def _hole_area(mask: np.ndarray) -> int:
    inv = cv2.bitwise_not(mask)
    flood = inv.copy()
    h, w = mask.shape[:2]
    ff = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, ff, (0, 0), 128)
    holes = (flood == 255).astype(np.uint8)
    return int(np.sum(holes))


def score_structure(data: Dict[str, Any], common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    q = _grid_vector(data["shape_mask"])
    uniform = 1.0 - float(np.std(np.asarray(q)) / (np.mean(q) + EPS))
    uniform = max(0.0, min(1.0, uniform))
    skel = common["skeleton"] > 0
    neighbors = cv2.filter2D(skel.astype(np.uint8), -1, np.ones((3, 3), np.uint8)) - skel
    endpoints = int(np.sum(skel & (neighbors == 1)))
    branches = int(np.sum(skel & (neighbors >= 3)))
    score = clip100(100.0 * (0.75 * uniform + 0.25 * exp_score(branches / max(endpoints + 1, 1), 0.5) / 100))
    return ({"grid_q1_to_q8": q, "grid_dispersion": 1 - uniform,
             "skeleton_endpoints": endpoints, "skeleton_branch_pixels": branches}, score)


def score_spacing(data: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    mask = data["layout_mask"]
    h, w = mask.shape[:2]
    fg = mask > 0
    rows = np.mean(fg, axis=1)
    cols = np.mean(fg, axis=0)
    ys, xs = np.where(fg)
    if len(xs) == 0:
        return ({}, 50.0)
    margins = [float(ys.min() / h), float((h - 1 - ys.max()) / h),
               float(xs.min() / w), float((w - 1 - xs.max()) / w)]
    holes = _hole_area(mask)
    density = float(np.mean(fg))
    margin_imbalance = float(np.std(margins))
    projection_variation = float(np.std(rows) + np.std(cols))
    score = 0.55 * exp_score(margin_imbalance, 0.18) + 0.25 * exp_score(density - 0.25, 0.25) + 0.20 * exp_score(projection_variation, 0.35)
    return ({"margin_top": margins[0], "margin_bottom": margins[1], "margin_left": margins[2],
             "margin_right": margins[3], "margin_imbalance": margin_imbalance,
             "ink_density": density, "hole_area_ratio": holes / max(int(np.sum(fg)), 1),
             "projection_variation": projection_variation}, clip100(score))


def score_ink(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[float]]:
    mask = data["layout_mask"] > 0
    gray = data["ink_gray"]
    values = gray[mask]
    # Anti-aliased black text can contain many intermediate pixels while still
    # having no meaningful ink wash. Quantize first and detect near-binary data.
    quantized = (values.astype(np.uint16) // 32).astype(np.uint8)
    hist_q = np.bincount(quantized, minlength=8)
    dominant_ratio = float(np.max(hist_q) / max(values.size, 1))
    p05, p95 = np.percentile(values, [5, 95])
    if (values.size < 10 or np.unique(quantized).size <= 2 or
            (dominant_ratio >= 0.90 and float(p95 - p05) <= 48.0)):
        return ({"applicable": False, "reason": "前景灰度层次不足（黑白/数字图形）"}, None)
    vals = values.astype(np.float32) / 255.0
    hist, _ = np.histogram(vals, bins=32, range=(0.0, 1.0), density=False)
    prob = hist.astype(np.float64) / max(hist.sum(), 1)
    entropy = float(-np.sum(prob * np.log(prob + EPS)))
    concentration = float(1.0 - np.mean(vals))
    local_contrast = float(np.std(vals))
    # Edge spread: average gradient magnitude on gray image, normalized.
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edge_spread = float(np.mean(np.sqrt(gx[mask] ** 2 + gy[mask] ** 2)) / 255.0)
    score = 100.0 * (0.25 * exp_score(abs(concentration - 0.75), 0.30) / 100 +
                     0.35 * exp_score(abs(entropy - 2.0), 1.4) / 100 +
                     0.25 * exp_score(abs(local_contrast - 0.20), 0.20) / 100 +
                     0.15 * exp_score(abs(edge_spread - 0.20), 0.25) / 100)
    return ({"applicable": True, "gray_mean": float(np.mean(vals)), "ink_concentration": concentration,
             "gray_entropy": entropy, "local_contrast": local_contrast,
             "edge_spread": edge_spread}, clip100(score))


def score_qi(common: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    records = _stroke_records(common)
    skel = common["skeleton"] > 0
    if not records:
        return ({"direction_coherence": None, "continuity_proxy": None}, 50.0)
    angles = np.asarray([r["angle"] for r in records], dtype=np.float32)
    direction_coherence = float(abs(np.mean(np.exp(1j * angles))))
    # Adjacent local samples are a geometry-only continuity proxy.
    if len(angles) > 1:
        diffs = np.abs(np.angle(np.exp(1j * np.diff(angles))))
        continuity = float(np.exp(-np.mean(diffs ** 2) / (0.8 ** 2)))
    else:
        continuity = 0.5
    widths = np.asarray([r["width"] for r in records], dtype=np.float32)
    width_rhythm = float(np.exp(-abs(robust_cv(widths) - 0.25) / 0.35))
    components = cv2.connectedComponents(skel.astype(np.uint8), 8)[0] - 1
    connectivity = float(1.0 / (1.0 + max(0, components - 1)))
    score = 100.0 * (0.30 * direction_coherence + 0.30 * continuity + 0.20 * width_rhythm + 0.20 * connectivity)
    return ({"direction_coherence": direction_coherence, "continuity_proxy": continuity,
             "width_rhythm_proxy": width_rhythm, "connectivity_proxy": connectivity,
             "sampled_skeleton_points": len(records)}, clip100(score))


def make_debug_image(data: Dict[str, Any], common: Dict[str, Any]) -> np.ndarray:
    base = cv2.cvtColor(data["shape_gray"], cv2.COLOR_GRAY2BGR)
    base[data["shape_mask"] > 0] = (80, 80, 80)
    base[common["skeleton"] > 0] = (0, 0, 255)
    h, w = base.shape[:2]
    cv2.line(base, (w // 2, 0), (w // 2, h - 1), (0, 180, 0), 1)
    cv2.line(base, (0, h // 2), (w - 1, h // 2), (0, 180, 0), 1)
    return base


def analyse(path: Path, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    bgr, alpha = load_image(path)
    data = preprocess(bgr, alpha)
    common = common_features(data)
    details: Dict[str, Any] = {}
    scores: Dict[str, Optional[float]] = {}
    details["balance"], scores["balance"] = score_balance(data)
    details["symmetry"], scores["symmetry"] = score_symmetry(data)
    details["proportion"], scores["proportion"] = score_proportion(data, common)
    details["unity"], scores["unity"] = score_unity(data, common)
    details["rhythm"], scores["rhythm"] = score_rhythm(common)
    details["brushwork"], scores["brushwork"] = score_brushwork(common)
    details["structure"], scores["structure"] = score_structure(data, common)
    details["spacing"], scores["spacing"] = score_spacing(data)
    details["ink"], scores["ink"] = score_ink(data)
    details["qi_proxy"], scores["qi_proxy"] = score_qi(common)
    use_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    applicable = {k: v is not None for k, v in scores.items()}
    denominator = sum(use_weights[k] for k in DIMENSIONS if applicable[k])
    total = sum(use_weights[k] * float(scores[k]) for k in DIMENSIONS if applicable[k]) / max(denominator, EPS)
    return {
        "sample_id": path.stem,
        "source_path": str(path.resolve()),
        "source_sha256": sha256_file(path),
        "image_width": int(bgr.shape[1]),
        "image_height": int(bgr.shape[0]),
        "score_mode": "rule_proxy_v1",
        "dimension_scores": scores,
        "dimension_details": details,
        "weights": use_weights,
        "applicable_dimensions": applicable,
        "total_score": clip100(total),
        "note": "无人工盲评校准；总分是可解释的规则代理分，不是普适的高级感真值。",
        "_data": data,
        "_common": common,
    }


def write_result(result: Dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    serializable = {k: v for k, v in result.items() if not k.startswith("_")}
    (out_dir / "result.json").write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    row = {"sample_id": result["sample_id"], "total_score": result["total_score"], "score_mode": result["score_mode"]}
    for name, value in result["dimension_scores"].items():
        row[name] = "" if value is None else value
    with (out_dir / "result.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)
    debug = make_debug_image(result["_data"], result["_common"])
    cv2.imwrite(str(out_dir / "debug.png"), debug)


def read_weights(path: Optional[Path]) -> Optional[Dict[str, float]]:
    if path is None:
        return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    weights = obj.get("weights", obj)
    return {str(k): float(v) for k, v in weights.items() if str(k) in DIMENSIONS}


def image_paths(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="10项审美指标可解释CV程序")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="单张图片")
    group.add_argument("--input-dir", type=Path, help="图片目录（递归）")
    parser.add_argument("--output", type=Path, required=True, help="输出目录")
    parser.add_argument("--weights", type=Path, help="可选JSON权重文件")
    args = parser.parse_args()
    weights = read_weights(args.weights)
    if args.input is not None:
        result = analyse(args.input, weights)
        write_result(result, args.output)
        print(json.dumps({"sample_id": result["sample_id"], "total_score": result["total_score"],
                          "dimension_scores": result["dimension_scores"]}, ensure_ascii=False, indent=2))
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    paths = list(image_paths(args.input_dir))
    if not paths:
        print("目录中没有支持的图片文件", file=sys.stderr)
        return 2
    for path in paths:
        try:
            result = analyse(path, weights)
            subdir = args.output / path.stem
            write_result(result, subdir)
            row = {"sample_id": result["sample_id"], "source_path": str(path), "total_score": result["total_score"]}
            row.update({k: ("" if v is None else v) for k, v in result["dimension_scores"].items()})
            rows.append(row)
            print(f"完成 {path} -> {result['total_score']:.2f}")
        except Exception as exc:
            rows.append({"sample_id": path.stem, "source_path": str(path), "error": str(exc)})
            print(f"失败 {path}: {exc}", file=sys.stderr)
    fields = sorted({k for row in rows for k in row.keys()})
    with (args.output / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

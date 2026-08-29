"""Quality gates and sensitivity reports for an immutable render run."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .measure import _stats
from .render import load_config, render_manifest, sha256


def _write_checksums(run: Path) -> None:
    files = sorted(p for p in run.rglob("*") if p.is_file() and p.name != "checksums.sha256")
    with (run / "checksums.sha256").open("w", encoding="utf-8") as handle:
        for path in files:
            handle.write(f"{sha256(path)}  {path.relative_to(run).as_posix()}\n")


def _sensitivity(run: Path, payload: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for item in cfg.get("sensitivity_runs", []):
        width, height, threshold = int(item["width_px"]), int(item["height_px"]), int(item["threshold"])
        if width == payload["canvas"]["width_px"] and height == payload["canvas"]["height_px"] and threshold == payload["threshold"]:
            continue
        descriptor = f"{payload['run_id']}_{width}x{height}_t{threshold}"
        out = run.parent / descriptor
        if out.exists():
            existing_manifest = out / "run_manifest.json"
            if existing_manifest.exists():
                existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
                existing_results = existing.get("results", [])
                runs.append({"run_id": existing.get("run_id", descriptor), "width_px": width, "height_px": height, "threshold": threshold, "output_dir": str(out), "failed": sum(r.get("status") != "passed" for r in existing_results)})
            continue
        sid, results, out = render_manifest(payload["config_path"], payload["manifest_path"], out, canvas_override=(width, height), threshold_override=threshold)
        runs.append({"run_id": sid, "width_px": width, "height_px": height, "threshold": threshold, "output_dir": str(out), "failed": sum(r.get("status") != "passed" for r in results)})
        for result in results:
            if result.get("status") != "passed":
                continue
            base = next((r for r in payload["results"] if r["stimulus_id"] == result["stimulus_id"] and r.get("status") == "passed"), None)
            if not base:
                continue
            current = _stats(result["mask_path"], threshold)
            reference = _stats(base["mask_path"], 128)
            if current is None or reference is None:
                continue
            for key in ("ink_coverage_ratio", "bbox_fill_ratio", "bbox_aspect_ratio", "symmetry_horizontal", "symmetry_vertical"):
                delta = abs(float(current[key]) - float(reference[key]))
                relative = delta / abs(float(reference[key])) if reference[key] else 0.0
                if delta > 0.02 or relative > 0.05:
                    warnings.append({"stimulus_id": result["stimulus_id"], "run_id": sid, "feature": key, "absolute_delta": delta, "relative_delta": relative})
    return runs, warnings


def qc_run(run_dir: str | Path) -> bool:
    run = Path(run_dir)
    payload = json.loads((run / "render_results.json").read_text(encoding="utf-8"))
    cfg = load_config(payload["config_path"])
    issues: list[dict[str, str]] = []
    passed = 0
    for row in payload["results"]:
        if row.get("status") != "passed":
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": row.get("failure_code", "UNKNOWN"), "stage": "render", "message": row.get("message", "")})
            continue
        if int(row.get("width_px", 0)) != int(payload["canvas"]["width_px"]) or int(row.get("height_px", 0)) != int(payload["canvas"]["height_px"]):
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": "RENDER_OUT_OF_BOUNDS", "stage": "qc", "message": "wrong canvas"})
            continue
        if sha256(row["gray_path"]) != row.get("gray_sha256") or sha256(row["mask_path"]) != row.get("mask_sha256"):
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": "QC_HASH_MISMATCH", "stage": "qc", "message": "render hash mismatch"})
            continue
        stats = _stats(row["mask_path"], int(payload["threshold"]))
        if stats is None:
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": "ASSET_MISSING_GLYPH", "stage": "qc", "message": "empty mask"})
            continue
        if row["render_profile"] == "bbox_height_matched" and abs((row["ink_bbox"][3] - row["ink_bbox"][1]) - int(cfg["profiles"]["bbox_height_matched"]["target_height_px"])) > 1:
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": "NORMALIZATION_FAILED", "stage": "qc", "message": "bbox height outside tolerance"})
            continue
        if row["render_profile"] == "ink_area_matched" and abs(stats["ink_coverage_ratio"] - float(cfg["profiles"]["ink_area_matched"]["target_ratio"])) > 0.001:
            issues.append({"stimulus_id": row["stimulus_id"], "failure_code": "NORMALIZATION_FAILED", "stage": "qc", "message": "ink ratio outside tolerance"})
            continue
        passed += 1
    sensitivity_runs, warnings = _sensitivity(run, payload, cfg)
    with (run / "missing_records.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["stimulus_id", "failure_code", "stage", "message"])
        writer.writeheader()
        writer.writerows(issues)
    report = [
        "# Quality report", "", f"- Run: `{payload['run_id']}`", f"- Protocol: `{payload['protocol_version']}`",
        "- Condition grid: 160", f"- Unique stimuli: {len({row['stimulus_id'] for row in payload['results']})}",
        f"- Rendered passed: {passed}", f"- Missing/failed: {len(issues)}",
        f"- Sensitivity runs: {len(sensitivity_runs)}", f"- Sensitivity warnings: {len(warnings)}",
        "- Policy: failures are retained; no fallback or silent replacement.",
        "- Feature values are visual measurements, not aesthetic truth or human ratings.",
        "- Release requires zero failed records, public redistributable assets, and two independent human fixture reviews.", "",
        "## Sensitivity", "", "```json", json.dumps({"runs": sensitivity_runs, "warnings": warnings}, ensure_ascii=False, indent=2), "```", "",
    ]
    (run / "quality_report.md").write_text("\n".join(report), encoding="utf-8")
    _write_checksums(run)
    return not issues and not warnings

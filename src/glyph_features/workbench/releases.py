"""Demo audit-package writer; formal release remains gate-controlled."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class ExportError(ValueError):
    """Raised when an audit export would violate no-overwrite or safety rules."""


DEMO_LABEL = "SYNTHETIC / DEMO"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            {"distribution_label": DEMO_LABEL, "payload": payload},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _csv_safe(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    projected = [{"distribution_label": DEMO_LABEL, **row} for row in rows]
    fields = list(projected[0]) if projected else ["distribution_label"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in projected:
            writer.writerow({key: _csv_safe(value) for key, value in row.items()})


def _effect_figure(path: Path, estimate: dict[str, Any]) -> None:
    image = Image.new("RGB", (960, 420), "#f6f4ee")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 62), fill="#17324d")
    draw.text((28, 22), DEMO_LABEL + " - native match log-odds", fill="white")
    low, high = estimate["confidence_interval_95"]
    center = estimate["estimate_log_odds"]
    domain_low = min(-0.5, low - 0.25)
    domain_high = max(0.5, high + 0.25)

    def x(value: float) -> int:
        return int(90 + (value - domain_low) / (domain_high - domain_low) * 780)

    zero_x = x(0.0)
    draw.line((zero_x, 100, zero_x, 330), fill="#7b8790", width=2)
    draw.line((x(low), 215, x(high), 215), fill="#b8472f", width=8)
    draw.ellipse((x(center) - 11, 204, x(center) + 11, 226), fill="#17324d")
    draw.text((90, 355), f"95% CI [{low:.3f}, {high:.3f}]", fill="#24333e")
    draw.text((610, 355), "Engineering recovery only", fill="#b8472f")
    image.save(path, format="PNG")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_checksums(directory: Path) -> Path:
    entries = []
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if path.name == "checksums.sha256":
            continue
        entries.append(f"{_sha256(path)}  {path.relative_to(directory).as_posix()}")
    output = directory / "checksums.sha256"
    output.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return output


def export_demo_audit_package(
    output_root: str | Path,
    *,
    analysis_run: dict[str, Any],
    plan: dict[str, Any],
    release_candidate: dict[str, Any],
) -> dict[str, Any]:
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = analysis_run["analysis_run_id"]
    package_name = f"{run_id}_demo"
    directory = root / package_name
    archive = root / f"{package_name}.zip"
    if directory.exists() or archive.exists():
        raise ExportError("DEMO_EXPORT_NO_OVERWRITE")
    directory.mkdir()
    figures = directory / "figures"
    figures.mkdir()
    result = analysis_run["result"]
    snapshot = analysis_run["snapshot"]
    try:
        _write_json(directory / "analysis_plan.json", plan)
        _write_json(directory / "analysis_run_manifest.json", snapshot)
        _write_json(directory / "input_artifacts.json", snapshot["input_artifacts"])
        _write_json(directory / "join_audit.json", result["join_audit"])
        _write_json(
            directory / "inclusion_exclusion_flow.json",
            result["inclusion_exclusion_flow"],
        )
        _write_json(directory / "model_specification.json", result["model_specification"])
        _write_json(directory / "model_diagnostics.json", result["model_diagnostics"])
        _write_json(directory / "effect_estimates.json", result["effect_estimates"])
        _write_csv(directory / "effect_estimates.csv", result["effect_estimates"])
        _write_json(directory / "sensitivity_results.json", result["sensitivity_results"])
        _write_csv(directory / "sensitivity_results.csv", result["sensitivity_results"])
        _write_json(directory / "gate_report.json", release_candidate)
        _write_json(directory / "software_environment.json", snapshot["software_environment"])
        _effect_figure(figures / "native_match_effect.png", result["effect_estimates"][0])
        (directory / "limitations_zh.md").write_text(
            f"# {DEMO_LABEL}：局限\n\n"
            + "\n".join(f"- {item}" for item in result["limitations"])
            + "\n",
            encoding="utf-8",
        )
        (directory / "README_zh.md").write_text(
            f"# {DEMO_LABEL}：GLYPH 联合分析审计包\n\n"
            "本包仅用于许可 fixture 的工程验收，不是正式研究发布物。\n\n"
            f"- analysis run：`{run_id}`\n"
            f"- snapshot SHA-256：`{snapshot['snapshot_sha256']}`\n"
            f"- formal release：`blocked`\n"
            f"- blocker count：`{len(release_candidate['formal_blockers'])}`\n",
            encoding="utf-8",
        )
        checksum_path = _write_checksums(directory)
        shutil.make_archive(str(archive.with_suffix("")), "zip", directory)
        return {
            "distribution_label": DEMO_LABEL,
            "package_name": package_name,
            "archive_name": archive.name,
            "archive_sha256": _sha256(archive),
            "checksums_sha256": _sha256(checksum_path),
            "formal_release_eligible": False,
        }
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise
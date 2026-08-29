"""Command-line entry points for the frozen visual-features v1 pipeline."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

from .measure import measure_run
from .qc import qc_run
from .render import load_config, render_manifest, sha256
from .validate import validate_visual_csv


def _required_config(config: dict) -> list[str]:
    return ["protocol_version", "schema_versions", "canvas", "profiles", "foreground", "background", "shaping", "thresholds", "contour_params", "skeleton_params", "sensitivity_runs", "release_policy"]


def _find_run(run_id: str, root: Path) -> Path:
    candidates = [root / "runs" / run_id, root / run_id]
    for candidate in candidates:
        if (candidate / "render_results.json").exists():
            return candidate
    raise FileNotFoundError(f"render run not found: {run_id}")


def _human_review_status(root: Path, run_dir: Path) -> tuple[bool, str]:
    """Require two independent, complete fixture reviews without inventing reviewers."""
    review_path = root / "human_review" / "fixture_review_records.csv"
    if not review_path.exists():
        return False, f"human fixture review file missing: {review_path}"
    rows = list(csv.DictReader(review_path.open(encoding="utf-8", newline="")))
    manifest_rows = list(csv.DictReader((run_dir / "manifest.csv").open(encoding="utf-8", newline="")))
    expected: set[str] = set()
    for row in manifest_rows:
        is_unit = row["content_set_id"].endswith("_u01") or row["content_set_id"].endswith("_u02")
        is_baseline = row["style_family"] == "sans"
        is_han_example = row["script_code_iso15924"] == "Hani" and row["unit_count"] == "1"
        if is_unit and (is_baseline or is_han_example):
            expected.add(row["stimulus_id"])
    if not rows:
        return False, f"human fixture review is empty; {len(expected)} fixture stimuli require two independent reviews"
    reviewers = {row.get("reviewer_id", "").strip() for row in rows if row.get("reviewer_id", "").strip()}
    if len(reviewers) < 2:
        return False, f"human fixture review requires at least two reviewers, found {len(reviewers)}"
    for reviewer in reviewers:
        subset = [row for row in rows if row.get("reviewer_id", "").strip() == reviewer]
        seen = {row.get("fixture_id", "").strip() for row in subset}
        missing = expected - seen
        if missing:
            return False, f"reviewer {reviewer} missing {len(missing)} fixture records"
        if any(row.get(field, "").strip().lower() != "true" for row in subset for field in ("visual_grid_pass", "character_boundary_pass", "style_classification_pass")):
            return False, f"reviewer {reviewer} has non-passing fixture review"
    return True, "two complete independent fixture reviews"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glyph-features")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config")
    validate.add_argument("--config", required=True)
    validate_features = sub.add_parser("validate-features")
    validate_features.add_argument("--csv", required=True)
    render = sub.add_parser("render")
    render.add_argument("--config", required=True)
    render.add_argument("--manifest", required=True)
    render.add_argument("--output-dir")
    render.add_argument("--width", type=int)
    render.add_argument("--height", type=int)
    render.add_argument("--threshold", type=int)
    measure = sub.add_parser("measure")
    measure.add_argument("--run-id", required=True)
    measure.add_argument("--run-dir")
    qc = sub.add_parser("qc")
    qc.add_argument("--run-id", required=True)
    qc.add_argument("--run-dir")
    release = sub.add_parser("release")
    release.add_argument("--run-id", required=True)
    release.add_argument("--run-dir")
    release.add_argument("--output-dir")
    args = parser.parse_args(argv)
    root = Path("data/processed/visual_features_v1")
    try:
        if args.command == "validate-config":
            config = load_config(args.config)
            missing = [key for key in _required_config(config) if key not in config]
            if missing:
                print("invalid config, missing: " + ",".join(missing), file=sys.stderr)
                return 2
            print(f"valid config {config['protocol_version']}")
            return 0
        if args.command == "validate-features":
            errors = validate_visual_csv(args.csv)
            if errors:
                print("invalid visual feature CSV:", file=sys.stderr)
                print("\n".join(errors[:20]), file=sys.stderr)
                return 2
            print(f"valid visual feature CSV {args.csv}")
            return 0
        if args.command == "render":
            override = (args.width, args.height) if args.width or args.height else None
            if override and (not args.width or not args.height):
                raise ValueError("--width and --height must be supplied together")
            run_id, results, output = render_manifest(args.config, args.manifest, args.output_dir, canvas_override=override, threshold_override=args.threshold)
            print(f"run_id={run_id}\noutput_dir={output}\nrecords={len(results)}\nexit_code=0")
            return 0
        run_dir = Path(args.run_dir) if args.run_dir else _find_run(args.run_id, root)
        if args.command == "measure":
            records = measure_run(run_dir)
            print(f"run_id={args.run_id}\noutput_dir={run_dir}\nrecords={len(records)}\nexit_code=0")
            return 0
        if args.command == "qc":
            passed = qc_run(run_dir)
            print(f"run_id={args.run_id}\noutput_dir={run_dir}\nstatus={'passed' if passed else 'needs_review'}\nexit_code={0 if passed else 2}")
            return 0 if passed else 2
        if args.command == "release":
            report = run_dir / "quality_report.md"
            missing = run_dir / "missing_records.csv"
            if not report.exists() or not missing.exists():
                print("release blocked: QC outputs are missing", file=sys.stderr)
                return 2
            with missing.open(encoding="utf-8", newline="") as handle:
                failures = list(csv.DictReader(handle))
            inventory = root / "asset_inventory.csv"
            assets = list(csv.DictReader(inventory.open(encoding="utf-8", newline=""))) if inventory.exists() else []
            if failures:
                print(f"release blocked: {len(failures)} missing or failed records", file=sys.stderr)
                return 2
            if any(row.get("distribution_tier") != "public" or row.get("redistributable", "").lower() != "true" for row in assets):
                print("release blocked: source assets are not all public and redistributable", file=sys.stderr)
                return 2
            review_ok, review_message = _human_review_status(root, run_dir)
            if not review_ok:
                print(f"release blocked: {review_message}", file=sys.stderr)
                return 2
            destination = Path(args.output_dir) if args.output_dir else Path("data/releases/visual_features_v1")
            if destination.exists() and any(destination.iterdir()):
                raise FileExistsError(f"release directory is non-empty: {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.csv", "visual_features.csv", "stimulus_records.jsonl", "missing_records.csv", "run_manifest.json", "quality_report.md", "checksums.sha256", "feature_dictionary_zh.md", "rendering_protocol_zh.md", "README.md", "asset_inventory.csv", "asset_licences.csv"):
                source = run_dir / name if (run_dir / name).exists() else root / name
                if source.exists():
                    shutil.copy2(source, destination / name)
            if (run_dir / "rendered").exists():
                shutil.copytree(run_dir / "rendered", destination / "rendered")
            shutil.copy2(root / "human_review" / "fixture_review_records.csv", destination / "fixture_review_records.csv")
            print(f"release ready: {destination}\nexit_code=0")
            return 0
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

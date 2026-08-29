# Visual Features v1 Results

This directory is the public, reproducible result layer for the frozen first
visual-feature protocol. `manifest.csv` is the canonical 140-stimulus input
matrix. `asset_inventory.csv` records the exact OFL-1.1 font assets used to
build it. Immutable executions live under `runs/`; a run never overwrites a
previous run.

## Reference execution

`runs/render_551362ca0ff22f33/` is the current reference execution on 2026-08-29
under protocol `visual_features_v1.2.0`. It has 140 passed render records and
zero failed records. v1.2.0 changes only the feasible normalization targets
(320 px bbox height and 0.050 ink-area ratio); the complete feasibility audit
is retained under `audits/`.

The reference run includes grayscale PNGs, thresholded masks, a two-
representation feature table, complete `stimulus_records.jsonl`, checksums, a
machine-readable failure table, and the 1024 x 512, threshold-96, and
threshold-160 sensitivity runs. Sensitivity targets and anchors scale with the
resolution; the quality report records zero warnings. Release remains gated
only on two independent human fixture reviews.

The local `history/` directory is ignored by Git. It retains the pre-open-font
Apple fixture and incomplete or pre-guard executions for audit continuity, but
is neither an input to the current run nor a candidate release.

To validate the shared stimulus projection and regenerate the deterministic
fixture list:

```bash
python tools/validate_stimulus_manifest.py \
  --manifest data/processed/visual_features_v1/manifest.csv \
  --run-dir data/processed/visual_features_v1/runs/render_551362ca0ff22f33 \
  --output data/processed/visual_features_v1/runs/render_551362ca0ff22f33/stimulus_records.jsonl
python tools/build_fixture_stimuli.py \
  --output data/processed/visual_features_v1/human_review/fixture_stimuli.csv
```

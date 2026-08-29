# GLYPH Visual Features v1.2.0

**Technical report**  
Date: 2026-08-30  
Repository: <https://github.com/Yonagi043/GLYPH>

## 1. Objective

GLYPH v1 establishes a reproducible visual-measurement layer for research on
writing systems, type styles, and glyph form. It measures rendered form under
fixed conditions; it does not estimate aesthetic truth, replace human ratings,
or produce a composite aesthetic score.

## 2. Frozen design

| Item | Frozen specification |
| --- | --- |
| Protocol | `visual_features_v1.2.0` |
| Schema | stimulus `1.1.0`; visual features `1.1.0` |
| Writing systems | Latin (`Latn`), Han (`Hani`), Kana (`Kana`), Hangul (`Hang`) |
| Canvas | 2048 x 1024 px, sRGB, black on white, 96 DPI |
| Shaping and rasterization | Unicode NFC + HarfBuzz cluster validation; Pillow/FreeType BASIC rendering; `-liga`, `-kern`; no fallback or silent substitution |
| Anchors | Single glyph ink-bbox center `(1024, 512)`; multi-unit text center `x=1024`, baseline `y=640` |
| Normalization profiles | `bbox_height_matched`: ink bbox height 320 px; `ink_area_matched`: ink ratio 0.050 |
| Binary and sensitivity thresholds | Main binary threshold 128; sensitivity thresholds 96 and 160 |

The canonical manifest contains 160 condition cells and 140 unique stimuli.
Each stimulus is identified by a stable `stimulus_id`; all source, font,
language, layout, normalization, and provenance fields remain in the manifest.

## 3. Font assets

The matrix uses seven locally stored, redistributable OFL-1.1 assets:

- Noto Sans (Latin baseline)
- Noto Sans CJK SC (Han baseline)
- Noto Sans CJK JP (Kana baseline)
- Noto Sans KR (Hangul baseline)
- Noto Serif SC (Han serif comparison)
- Bpmf Iansui (Han display comparison)
- LXGW Marker Gothic (Han display comparison)

Exact source URLs, access dates, license hash, coverage status, and SHA-256
values are recorded in
[`data/processed/visual_features_v1/asset_inventory.csv`](../data/processed/visual_features_v1/asset_inventory.csv).

## 4. Processing pipeline

```text
asset registration and license check
    -> manifest/schema validation
    -> NFC and HarfBuzz cluster validation
    -> deterministic rasterization
    -> profile-specific normalization
    -> grayscale and binary feature extraction
    -> QC, checksums, and sensitivity comparison
    -> independent human fixture review
```

The implementation is in [`src/glyph_features/`](../src/glyph_features/).
Runs are immutable and never overwrite an existing run directory. Missing or
failed records are retained with explicit failure codes; inputs are never
silently replaced.

## 5. Feature extraction

For each passed stimulus, the extractor writes two records:
`raster_binary` and `raster_grayscale`. The v1 implementation exposes 17
interpretable measurements:

- **Density and proportion:** `ink_coverage_ratio`, `whitespace_ratio`,
  `bbox_fill_ratio`, `bbox_aspect_ratio`
- **Topology and geometry:** `connected_component_count`, `closure_count`,
  `symmetry_horizontal`, `symmetry_vertical`
- **Stroke gesture and visual center:** `straight_curve_ratio`,
  `centroid_x_norm`, `centroid_y_norm`
- **Sequence layout and rhythm:** `inter_glyph_spacing_mean_norm`,
  `inter_glyph_spacing_sd_norm`, `rhythm_periodicity`
- **Unit uniformity:** `unit_area_cv`, `unit_width_cv`, `unit_height_cv`

Sequence-only measures are explicitly marked not applicable for single-unit
stimuli. Short sequences receive `MEASURE_SEQUENCE_TOO_SHORT`; no missing value
is imputed.

Definitions and applicability rules are in
[`data/processed/visual_features_v1/feature_dictionary_zh.md`](../data/processed/visual_features_v1/feature_dictionary_zh.md).

## 6. Reference results

Reference run:
[`render_551362ca0ff22f33`](../data/processed/visual_features_v1/runs/render_551362ca0ff22f33/)

| Metric | Result |
| --- | ---: |
| Unique stimuli | 140 |
| Condition cells | 160 |
| Feature records | 280 |
| Passed renders | 140 / 140 |
| Failed or missing records | 0 |
| Sensitivity runs | 3 |
| Sensitivity warnings | 0 |

The run contains grayscale PNGs, binary masks, `visual_features.csv`, complete
stimulus records, manifests, run metadata, logs, QC results, and SHA-256
checksums. The quality report is
[`quality_report.md`](../data/processed/visual_features_v1/runs/render_551362ca0ff22f33/quality_report.md).

## 7. Validation and release gate

Automated validation currently passes:

```text
uv run --locked --extra dev pytest -q
4 passed
```

The repository also retains normalization-feasibility audits and three
sensitivity executions. Public release is gated by two independent human
fixture reviews of the 28-item review set. The review templates and
instructions are in
[`data/processed/visual_features_v1/human_review/`](../data/processed/visual_features_v1/human_review/).
No human review record has been fabricated.

After both reviews are complete, run:

```bash
uv run --locked --extra dev python -m glyph_features.cli release \
  --run-id render_551362ca0ff22f33
```

## 8. Reproduction

```bash
conda activate glyph
uv sync --locked --extra dev

python -m glyph_features.cli validate-config \
  --config configs/visual_features_v1.yaml
python -m glyph_features.cli render \
  --config configs/visual_features_v1.yaml \
  --manifest data/processed/visual_features_v1/manifest.csv
python -m glyph_features.cli measure \
  --run-id render_<manifest-hash>
python -m glyph_features.cli qc \
  --run-id render_<manifest-hash>
```

The frozen rendering and normalization rules are documented in
[`rendering_protocol_zh.md`](../data/processed/visual_features_v1/rendering_protocol_zh.md).

## 9. Scope limits and next-round handoff

This release measures image-derived form only. It does not claim cross-cultural
equivalence, readability equivalence, historical causality, or aesthetic
ranking. The stable handoff for the next research round is the combination of
`stimulus_id`, versioned schemas, immutable run IDs, manifests, license
inventory, locked dependencies, fixture tests, and the human-review records.

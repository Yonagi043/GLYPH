# Synthetic social-narrative demo

This directory is a complete, **synthetic** end-to-end example. It contains no
real platform response, real user, real brand, or real traffic measurement.
Every URL uses `example.org`, and every text string is written for testing.

The demo shows the intended public-repository hand-off:

```text
input.json → normalize → observations.jsonl
                     ↘ sources.csv
observations.jsonl → validate → matrices/
                     ↘ project → narratives.jsonl (optional)
```

The checked-in `observations.jsonl` and `matrices/` are deterministic outputs
from the input. To reproduce them from the repository root:

```bash
python tools/normalize_social_records.py \
  --input demo/social_narrative/input.json \
  --output demo/social_narrative/observations.jsonl \
  --sources-output demo/social_narrative/sources.csv \
  --platform public_web --source-kind imported_export \
  --collection-run-id social_run_demo_20260901 \
  --query-id q_example_typography_en \
  --normalized-at 2026-09-01T00:00:00Z \
  --force

python tools/validate_social_observations.py \
  --input demo/social_narrative/observations.jsonl \
  --queries data/templates/social_queries.csv \
  --codebook data/templates/social_codebook.csv \
  --objects data/templates/social_object_map.csv \
  --sources demo/social_narrative/sources.csv \
  --run-manifest demo/social_narrative/run_manifest.json \
  --report demo/social_narrative/validation.json \
  --force

python tools/summarize_narratives.py \
  --input demo/social_narrative/observations.jsonl \
  --output-dir demo/social_narrative/matrices --force

python tools/project_social_to_narratives.py \
  --input demo/social_narrative/observations.jsonl \
  --output demo/social_narrative/narratives.jsonl \
  --default-confidence 0.9 --force
```

The demo intentionally includes one `creator` role. Projection to the frozen
cultural-narrative schema records that role as `unknown`; the original social
observation remains unchanged. One image-only row is retained in the canonical
file but is not part of the default `human_verified` matrices.

The failure CSV is kept even when empty so that real runs have a stable place to
record parse, permission, deletion, and duplicate failures.

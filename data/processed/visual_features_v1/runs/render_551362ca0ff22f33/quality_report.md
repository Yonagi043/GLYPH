# Quality report

- Run: `render_551362ca0ff22f33`
- Protocol: `visual_features_v1.2.0`
- Condition grid: 160
- Unique stimuli: 140
- Rendered passed: 140
- Missing/failed: 0
- Sensitivity runs: 3
- Sensitivity warnings: 0
- Policy: failures are retained; no fallback or silent replacement.
- Feature values are visual measurements, not aesthetic truth or human ratings.
- Release requires zero failed records, public redistributable assets, and two independent human fixture reviews.

## Sensitivity

```json
{
  "runs": [
    {
      "run_id": "render_a684e5065ef23359",
      "width_px": 1024,
      "height_px": 512,
      "threshold": 128,
      "output_dir": "data/processed/visual_features_v1/runs/render_551362ca0ff22f33_1024x512_t128",
      "failed": 0
    },
    {
      "run_id": "render_ed6b4f9e38d94545",
      "width_px": 2048,
      "height_px": 1024,
      "threshold": 96,
      "output_dir": "data/processed/visual_features_v1/runs/render_551362ca0ff22f33_2048x1024_t96",
      "failed": 0
    },
    {
      "run_id": "render_0795bceb332e6f9c",
      "width_px": 2048,
      "height_px": 1024,
      "threshold": 160,
      "output_dir": "data/processed/visual_features_v1/runs/render_551362ca0ff22f33_2048x1024_t160",
      "failed": 0
    }
  ],
  "warnings": []
}
```

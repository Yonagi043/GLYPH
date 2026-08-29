# Normalization Feasibility Audit

This diagnostic evaluates the frozen protocol without changing any stimulus or target.

- Conditions audited: **140**
- Geometrically infeasible: **0**
- bbox-height failures: **0** (0 width-bound)
- ink-area failures: **0** (0 width-bound, 0 height-bound)

For a single uniformly scaled raster, a target can fit only when both target width and target height are within the canvas. The CSV records the exact dimensions and limiting axis for every condition; no crop, non-uniform stretch, fallback font, or target adjustment is applied.

All audited conditions fit the canvas under the active protocol targets.

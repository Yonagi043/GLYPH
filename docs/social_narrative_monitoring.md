# GLYPH social-narrative monitoring

This document is the public implementation guide for the cultural--historical
research line. The system measures **which descriptions co-occur in a declared
sample**; it does not measure total traffic, impressions, public opinion, or
causal influence.

## What we keep from earlier work

| Prior attempt | Proven useful idea | GLYPH adaptation |
| --- | --- | --- |
| [4CAT](https://github.com/digitalmethodsinitiative/4cat) (MPL-2.0) | Separate capture, processing, datasets, and run records; keep intermediate data | The same separation, implemented as a small offline core so the repository does not depend on a changing plugin stack |
| [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer) (MPL-2.0) | A normal browsing session can provide a bounded observation when an API is unavailable | Treat browser capture as a labelled, fixed-quota sample; never call it a platform-wide sample or bypass access controls |
| [Facepager](https://github.com/strohne/Facepager) (MIT) | Pagination, throttling, SQLite storage, and request logs matter | Accept its export as an input; retain the request/run manifest and normalize to one GLYPH schema |
| [PRAW](https://github.com/praw-dev/praw) (BSD-2-Clause) | OAuth and rate-limit-aware Reddit collection | Use it as an optional upstream collector; credentials and network code stay outside this repository |
| [YouTube Data Tools](https://github.com/bernorieder/YouTube-Data-Tools-v2) (GPL-3.0-or-later) | Batch requests, quota accounting, pseudonymization, offline fixtures, and run reports | Borrow the controls, not the GPL application; submit an export to the GLYPH normalizer |
| [X API v2/XDK](https://docs.x.com/x-api/getting-started/about-x-api.md) | A documented query and API response are auditable; public metrics are distinct from impressions | Enable only after approval and budget checks; request the minimum fields and publish IDs/aggregates only when permitted |
| [Taguette](https://gitlab.com/remram44/taguette) (BSD-3-Clause) | Human highlighting and coding makes text evidence inspectable | Candidate labels are queues; a source excerpt, annotator, and timestamp are required for final coding |

The methodological guardrails come from digital-trace research: an API,
browser observation, and data donation are different observation processes
(Tufekci, 2014; Ohme et al., 2023). We therefore compare only cells
with the same platform, language, time window, query set, and counting rule.

## Repository contract

```text
data/templates/social_queries.csv             # registered query strings
data/templates/social_codebook.csv            # allowed labels and inclusion rules
data/templates/social_object_map.csv          # canonical object labels and aliases
data/templates/social_run_manifest.json       # one example run manifest
data/templates/sources.csv                    # source-registry CSV projection
configs/social_narrative_v0.yaml              # frozen pilot protocol
schema/social_run_manifest.schema.json        # how a run is described
schema/social_observation.schema.json         # one normalized item
data/raw/social/<platform>/<run_id>/          # local raw exports; ignored by git
data/processed/social_narrative_v0/           # local normalized results; ignored by git
tools/social_io.py                            # shared readers, hashes, schema checks
tools/normalize_social_records.py             # JSON/JSONL/CSV -> canonical JSONL
tools/validate_social_observations.py         # offline release gate
tools/summarize_narratives.py                 # two conditional matrices + Lift
tools/project_social_to_narratives.py         # reviewed rows -> shared narrative schema
tools/x_discourse_monitor.py                  # optional legacy X snapshot demo
```

The raw tree is intentionally ignored. Do not add API keys, cookies, usernames,
full restricted posts, downloaded videos, or screenshots to a commit. A public
release may contain only rights-cleared metadata, permitted short excerpts,
IDs/URLs allowed by the platform, hashes, and derived tables.

## One run, from export to result

1. Register the exact query in `social_queries.csv`; choose a language, region,
   category, inclusive UTC window, result cap, and deduplication rule.
2. Create a copy of `social_run_manifest.json` under the local raw run
   directory. Fill in the collector, endpoint/API version, raw-file SHA-256,
   terms date, retention decision, and completion time.
3. Save the approved API or manual export under
   `data/raw/social/<platform>/<collection_run_id>/`. Collection is performed
   by the platform's official API or a normal, user-driven browser session;
   this repository has no crawler.
4. Normalize offline. The normalizer derives an observation identity from the
   platform, collection run, and platform item ID; it sorts output by that ID,
   strips direct author identifiers unless a private salt is explicitly
   supplied, removes only known tracking parameters/fragments (no redirects or
   network calls), validates every row, and writes a failure CSV instead of
   dropping a row. The failure CSV is a repair queue: fix the upstream export
   and rerun; unresolved failures cannot enter a release.

   The required `content_status` field distinguishes text-bearing items from
   image/video-only, deleted, private, and unreachable items; an empty `text`
   field is therefore not silently treated as an irrelevant item.

   ```bash
   python tools/normalize_social_records.py \
     --input data/raw/social/reddit/social_run_20260901_reddit/export.json \
     --output data/processed/social_narrative_v0/observations.jsonl \
     --platform reddit --source-kind official_api \
     --collection-run-id social_run_20260901_reddit \
     --query-id q_typography_en \
     --normalized-at 2026-09-01T12:00:00Z
   ```

5. Run the offline gate. A release must have no errors; warnings are retained
   in the report and are resolved by a reviewer.

   ```bash
   python tools/validate_social_observations.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --queries data/templates/social_queries.csv \
     --codebook data/templates/social_codebook.csv \
     --objects data/templates/social_object_map.csv \
     --sources data/processed/social_narrative_v0/sources.csv \
     --run-manifest data/raw/social/reddit/social_run_20260901_reddit/run_manifest.json \
     --report data/processed/social_narrative_v0/validation.json
   ```

6. Two reviewers code the object, aesthetic term, stance, mechanism, and exact
   evidence span. `candidate` is a work queue; only `human_verified` enters
   the primary summary. At least 20% of every platform--language cell is
   double-coded before a comparison is reported.
7. Build the two directions of association. The default unit is one record;
   visible interactions are a separate descriptive sensitivity view.

   ```bash
   python tools/summarize_narratives.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --output-dir data/processed/social_narrative_v0/matrices/summary_20260901
   ```

   If a reviewed row is also needed by the frozen cultural-narrative line,
   project it explicitly (one output row per verified object--term pair):

   ```bash
   python tools/project_social_to_narratives.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --output data/processed/social_narrative_v0/narratives.jsonl
   ```

The collection schema has a `creator` role that is absent from the frozen
cultural-narrative schema. During projection it is explicitly recorded as
`unknown` (never as designer or ordinary user); the original role remains in
the social observation. The X snapshot script is retained only as a small,
optional adapter/demo; it is not required by the offline pipeline and its
output must not be published without a separate rights review.

## Measures

For object \(S\), term \(A\), and the declared analysis set:

\[
P(A\mid S)=\frac{n(S,A)}{n(S)},\qquad
P(S\mid A)=\frac{n(S,A)}{n(A)},\qquad
\operatorname{Lift}(S,A)=\frac{P(A\mid S)}{P(A)}.
\]

`n` counts records in the default output. A row carrying two terms contributes
to both term cells; this is multi-label presence, not a claim that terms are
mutually exclusive. `--weight engagement` produces a separate descriptive
table using visible likes, comments, shares, quotes, and platform score; views
are reported separately and are never silently treated as interactions.
The role, reference, evidence, and time-series companion tables remain
record-count indexes even when a weighted sensitivity table is requested; this
is stated in `summary.json` and prevents unlike units from being merged.
Each matrix row also carries an `exploratory` flag. If either denominator is
below 20, the cell is exploratory and must not be ranked or used for a
between-group claim.

Lift greater than one means only “more co-occurrence than this sample's
baseline under these filters.” It is not evidence that a script is inherently
premium, that an algorithm caused exposure, or that the sample represents a
population.

## Platform decisions

The first pass uses Reddit (PRAW), YouTube (official Data API), and public
design/award/brand pages. X is opt-in after API approval and a spending cap.
Instagram, TikTok, Douyin, and Xiaohongshu are manual/browser-capture inputs
only until a lawful, stable access path is documented. Pushshift, snscrape,
CrowdTangle, and archived TCAT are historical references, not current
collection dependencies. Never use browser automation to evade a platform's
API or anti-bot controls.

## What the result can support

The output can identify recurring, source-backed descriptions and generate
specific hypotheses for GLYPH's controlled human-rating study. It cannot
establish a narrative's true historical origin, total reach, algorithmic
recommendation, causal effect, or human aesthetic preference. Those claims
require archival/source criticism or the real-participant experiment in the
other GLYPH research lines.

## References

The complete numbered bibliography, including tool names and license checks, is
in [`status/social_narrative_methods_review_zh.md`](../status/social_narrative_methods_review_zh.md).

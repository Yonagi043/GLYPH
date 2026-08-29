# GLYPH X discourse monitor

This is a meeting-safe prototype for the cultural-narrative line. It turns a bounded X recent-search sample into a standalone HTML snapshot with sampled posts, visible engagement, explicit reply/repost/quote relations, likely sampled origins, and hashtag destinations.

## Run without credentials

```bash
python3 x_discourse_monitor.py --demo --out ../demo/x_discourse_demo.html
```

## Run with an X API v2 bearer token

```bash
export X_BEARER_TOKEN='...'
python3 x_discourse_monitor.py --query '(logo OR wordmark) (typography OR branding)' --limit 100 --out ../demo/x_discourse_live.html
```

## Scientific boundary

The tool observes only what the supplied X API sample exposes. It does not observe impressions, private sharing, the entire discussion, or the true origin/causal spread of an idea. “Potential origins” means original posts inside the sample, ranked by visible engagement. Store tweet IDs, query, collection time, and API response before making any research claim.

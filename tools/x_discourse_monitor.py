#!/usr/bin/env python3
"""GLYPH X discourse monitor.

Fetches a small X API v2 recent-search sample (when a bearer token is provided)
and renders a self-contained HTML report.  With --demo it is fully runnable
without network access or credentials.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEMO = {
    "data": [
        {"id": "101", "author_id": "u1", "created_at": "2026-08-16T08:05:00Z", "text": "Why do Latin wordmarks often read as premium? Is it form or cultural association? #Typography #Branding", "public_metrics": {"like_count": 48, "repost_count": 11, "reply_count": 7, "quote_count": 2}, "entities": {"hashtags": [{"tag": "Typography"}, {"tag": "Branding"}]}},
        {"id": "102", "author_id": "u2", "created_at": "2026-08-16T08:24:00Z", "text": "Seal script can look exceptionally premium in tea and fragrance identities, but legibility matters.", "public_metrics": {"like_count": 35, "repost_count": 8, "reply_count": 4, "quote_count": 1}, "referenced_tweets": [{"type": "replied_to", "id": "101"}], "entities": {"hashtags": [{"tag": "ChineseTypography"}]}},
        {"id": "103", "author_id": "u3", "created_at": "2026-08-16T09:00:00Z", "text": "Useful framing: visual density, readability, and cultural narrative are distinct variables.", "public_metrics": {"like_count": 27, "repost_count": 5, "reply_count": 2, "quote_count": 3}, "referenced_tweets": [{"type": "quoted", "id": "101"}], "entities": {"hashtags": [{"tag": "DesignResearch"}]}},
        {"id": "104", "author_id": "u4", "created_at": "2026-08-16T09:35:00Z", "text": "A beautiful Japanese wordmark may be read as minimalist because of learned branding narratives, not just glyph geometry.", "public_metrics": {"like_count": 19, "repost_count": 4, "reply_count": 3, "quote_count": 0}, "referenced_tweets": [{"type": "reposted", "id": "101"}], "entities": {"hashtags": [{"tag": "JapaneseDesign"}, {"tag": "Branding"}]}},
        {"id": "105", "author_id": "u5", "created_at": "2026-08-16T10:10:00Z", "text": "Collect award-winning identity systems, then run controlled experiments rather than treating awards as proof of beauty.", "public_metrics": {"like_count": 61, "repost_count": 17, "reply_count": 9, "quote_count": 5}, "entities": {"hashtags": [{"tag": "DesignResearch"}, {"tag": "LogoDesign"}]}},
        {"id": "106", "author_id": "u2", "created_at": "2026-08-16T10:52:00Z", "text": "Exactly. Chinese internal style variation may exceed average cross-script variation.", "public_metrics": {"like_count": 22, "repost_count": 3, "reply_count": 1, "quote_count": 0}, "referenced_tweets": [{"type": "replied_to", "id": "105"}], "entities": {"hashtags": [{"tag": "ChineseTypography"}]}},
    ],
    "includes": {"users": [
        {"id": "u1", "name": "Type Lab", "username": "typelab"}, {"id": "u2", "name": "Han Form", "username": "hanform"},
        {"id": "u3", "name": "Visual Methods", "username": "visualmethods"}, {"id": "u4", "name": "Brand Culture", "username": "brandculture"},
        {"id": "u5", "name": "Design Evidence", "username": "designevidence"},
    ]},
}


def fetch(query: str, token: str, limit: int) -> dict:
    params = {
        "query": query, "max_results": str(max(10, min(limit, 100))),
        "tweet.fields": "created_at,public_metrics,conversation_id,referenced_tweets,entities,lang,author_id",
        "expansions": "author_id,referenced_tweets.id",
        "user.fields": "name,username,verified,public_metrics",
    }
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "GLYPH-research-monitor/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def analyse(payload: dict) -> dict:
    tweets = payload.get("data", [])
    users = {u["id"]: u for u in payload.get("includes", {}).get("users", [])}
    by_id = {t["id"]: t for t in tweets}
    name = lambda uid: "@" + users.get(uid, {}).get("username", uid)
    edges, hashtags, domains, origins, timeline = [], Counter(), Counter(), Counter(), Counter()
    rows = []
    for t in tweets:
        metrics = t.get("public_metrics", {})
        engagement = sum(metrics.get(k, 0) for k in ("like_count", "repost_count", "reply_count", "quote_count"))
        refs = t.get("referenced_tweets", [])
        if not refs:
            origins[name(t.get("author_id", "unknown"))] += engagement
        for ref in refs:
            target = by_id.get(ref.get("id"), {})
            if target:
                edges.append({"source": name(t.get("author_id", "unknown")), "target": name(target.get("author_id", "unknown")), "type": ref.get("type", "reference"), "weight": engagement})
        for tag in t.get("entities", {}).get("hashtags", []): hashtags["#" + tag.get("tag", "").lower()] += 1
        for url in t.get("entities", {}).get("urls", []):
            expanded = url.get("expanded_url", "")
            if expanded: domains[urllib.parse.urlparse(expanded).netloc] += 1
        stamp = t.get("created_at", "")[:13] + ":00Z"
        timeline[stamp] += engagement
        rows.append({"id": t.get("id"), "author": name(t.get("author_id", "unknown")), "time": t.get("created_at", ""), "text": t.get("text", ""), "engagement": engagement, "refs": ", ".join(r.get("type", "") for r in refs) or "origin"})
    return {"tweets": len(tweets), "origins": origins, "edges": edges, "hashtags": hashtags, "domains": domains, "timeline": timeline, "rows": sorted(rows, key=lambda x: x["engagement"], reverse=True)}


def render(report: dict, query: str, mode: str) -> str:
    esc = html.escape
    top_origins = report["origins"].most_common(8)
    top_tags = report["hashtags"].most_common(10)
    edge_rows = "".join(f"<tr><td>{esc(e['source'])}</td><td>→</td><td>{esc(e['target'])}</td><td>{esc(e['type'])}</td><td>{e['weight']}</td></tr>" for e in sorted(report["edges"], key=lambda x: x["weight"], reverse=True)) or "<tr><td colspan='5'>No observable reply/repost/quote links in this sample.</td></tr>"
    posts = "".join(f"<article><b>{esc(r['author'])}</b> <span>{esc(r['time'])}</span><em>{r['engagement']} engagement · {esc(r['refs'])}</em><p>{esc(r['text'])}</p></article>" for r in report["rows"])
    bars = "".join(f"<div class='bar'><label>{esc(k)}</label><i style='width:{min(100, v * 3)}%'></i><b>{v}</b></div>" for k,v in top_origins) or "<p>None</p>"
    tags = " ".join(f"<mark>{esc(k)} · {v}</mark>" for k,v in top_tags) or "<p>None</p>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>GLYPH X discourse monitor</title><style>
body{{font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1120px;margin:32px auto;padding:0 20px;background:#f7f7f4;color:#171717}}h1{{font-size:34px;margin-bottom:0}}.note{{color:#625f58;max-width:850px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}}.card,section{{background:#fff;border:1px solid #ddd8cf;border-radius:12px;padding:18px}}.n{{font-size:32px;font-weight:750}}h2{{margin-top:0;font-size:20px}}.bar{{display:grid;grid-template-columns:155px 1fr 32px;gap:8px;align-items:center;margin:7px 0}}.bar i{{height:12px;background:#287a71;border-radius:8px}}mark{{display:inline-block;background:#ece7dc;margin:4px;padding:4px 7px;border-radius:6px}}table{{border-collapse:collapse;width:100%}}td,th{{padding:7px;border-bottom:1px solid #e6e1d8;text-align:left}}article{{border-top:1px solid #e6e1d8;padding:12px 0}}article span,article em{{color:#726d64;font-style:normal;margin-left:8px;font-size:12px}}article em{{float:right}}p{{margin-bottom:0}}footer{{color:#625f58;font-size:12px;margin:20px 0}}</style></head><body>
<h1>GLYPH · X discourse monitor</h1><p class='note'>Query: <b>{esc(query)}</b> · mode: {esc(mode)}. This report maps only observable sampled posts and explicit reply/repost/quote references. It does <b>not</b> measure total X traffic, impressions, or causal influence.</p>
<div class='grid'><div class='card'><div class='n'>{report['tweets']}</div>sampled posts</div><div class='card'><div class='n'>{len(report['edges'])}</div>observable interaction links</div><div class='card'><div class='n'>{len(report['hashtags'])}</div>hashtags</div></div>
<section><h2>Potential origins</h2><p class='note'>Original sampled posts, ranked by visible engagement. “Origin” here is operational, not a claim about the idea's true origin.</p>{bars}</section>
<section><h2>Conversation flow</h2><table><thead><tr><th>source account</th><th></th><th>target account</th><th>relation</th><th>visible engagement</th></tr></thead><tbody>{edge_rows}</tbody></table></section>
<section><h2>Hashtag destinations</h2>{tags}</section><section><h2>Sampled posts</h2>{posts}</section>
<footer>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · GLYPH Pilot tool · preserve source URLs/IDs and obey X terms before collecting or redistributing data.</footer></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an auditable X discourse-monitor snapshot.")
    parser.add_argument("--query", default='("logo" OR "wordmark") (typography OR branding)', help="X API v2 recent-search query")
    parser.add_argument("--out", default="x_discourse_report.html", help="HTML report path")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--token", default=os.getenv("X_BEARER_TOKEN"), help="X API bearer token; defaults to X_BEARER_TOKEN")
    parser.add_argument("--demo", action="store_true", help="Use included demo data; no API request")
    args = parser.parse_args()
    try:
        payload, mode = (DEMO, "offline demo data") if args.demo else (fetch(args.query, args.token, args.limit), "X API v2 recent-search sample")
        if not args.demo and not args.token: raise ValueError("Missing token. Set X_BEARER_TOKEN or run with --demo.")
    except Exception as error:
        print(f"Could not fetch X data: {error}", file=sys.stderr); print("Tip: run with --demo for the meeting-safe report.", file=sys.stderr); raise SystemExit(2)
    Path(args.out).write_text(render(analyse(payload), args.query, mode), encoding="utf-8")
    print(f"Wrote {args.out} ({mode})")

if __name__ == "__main__": main()

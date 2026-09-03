# -*- coding: utf-8 -*-
"""
DFA (Design for Asia Awards) 专用抓取器
======================================
DFA winners 站为 AJAX/JSON 驱动, 通用 scrape_award.py(Chrome+正则)无法消费,
故本脚本直接请求其 POST JSON API, 输出格式与 scrape_award.py 完全一致:
  图包/<scope>/DFA/<year>/*.jpg  +  图包/<scope>/DFA/sources.csv
每个获奖项目取封面图(第一张)以避免同项目多张产品/mockup 照片。
用法:
  python fetch_dfa.py --config configs/dfa.json --out 图包/中文奖项
"""
import os, csv, json, time, argparse, hashlib, urllib.parse, urllib.request
from datetime import datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def post_api(api, year, design_category):
    body = urllib.parse.urlencode({"keyword": "", "year": year, "design_category": design_category}).encode()
    req = urllib.request.Request(api, data=body, headers={
        "User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def download(url, out_path, min_bytes):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < min_bytes:
            return False, f"too small {len(data)}B"
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)
        return True, len(data)
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    award = cfg["award"]
    api = cfg["api"]
    exclude = [e.lower() for e in cfg.get("exclude", [])]
    max_per_year = cfg.get("max_per_year", 16)
    min_bytes = cfg.get("min_bytes", 8000)

    award_dir = os.path.join(args.out, award)
    os.makedirs(award_dir, exist_ok=True)
    src_rows = []

    for page in cfg["pages"]:
        year = page["year"]
        dc = page.get("design_category", cfg.get("design_category", "3"))
        print(f"[{award} {year}] API year={year} design_category={dc}")
        try:
            d = post_api(api, year, dc)
        except Exception as e:
            print(f"    [api err] {e}"); continue
        if d.get("status") != 1:
            print(f"    (status={d.get('status')} msg={d.get('message')}, 跳过)"); continue

        # 保序展开: Grand > Gold > Silver > Bronze > Merit, 每项目取封面图
        data = d.get("data", {})
        picks = []  # (project, url)
        for tier in ["Grand Award", "Gold Award", "Silver Award", "Bronze Award", "Merit Award"]:
            for it in data.get(tier, []):
                imgs = it.get("images", [])
                if not imgs:
                    continue
                url = imgs[0].get("image", "")
                low = url.lower()
                if not url or any(x in low for x in exclude):
                    continue
                picks.append((it.get("project_name_en", ""), it.get("company_name_en", ""), tier, url))

        ydir = os.path.join(award_dir, year)
        n = 0
        seen = set()
        for proj, comp, tier, u in picks:
            if n >= max_per_year:
                break
            if u in seen:
                continue
            seen.add(u)
            base = os.path.basename(urllib.parse.urlparse(u).path)
            h = hashlib.sha1(u.encode()).hexdigest()[:8]
            fn = f"{award}_{year}_{n+1:02d}_{h}_{base}"[:120]
            outp = os.path.join(ydir, fn)
            ok, info = download(u, outp, min_bytes)
            if ok:
                n += 1
                src_rows.append({"award": award, "year": year, "file": fn,
                                 "url": u, "bytes": info, "tier": tier,
                                 "project": proj, "company": comp,
                                 "page": f"{api}?year={year}&design_category={dc}",
                                 "fetched": datetime.now().isoformat(timespec="seconds")})
            else:
                print(f"    skip {info}")
            time.sleep(0.2)
        print(f"    下载 {n} 张 -> {ydir}")

    if src_rows:
        sp = os.path.join(award_dir, "sources.csv")
        write_header = not os.path.exists(sp)
        with open(sp, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(src_rows[0].keys()))
            if write_header:
                w.writeheader()
            w.writerows(src_rows)
        print(f"来源记录 -> {sp} (+{len(src_rows)})")


if __name__ == "__main__":
    main()

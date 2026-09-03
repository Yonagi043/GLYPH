# -*- coding: utf-8 -*-
"""
Indigo Design Award 专用抓取器 (fetch_indigo.py)
================================================
Indigo 官网为 Next.js SSR：每个年份页 /winners/competition/<YEAR> 的 __NEXT_DATA__
里内嵌该届全部获奖数据(含 competition.name=年份、Branding 等分类、每件作品 cover 原图)。
本脚本读取 configs/indigo.json，逐年解析该 JSON，抓取 Branding(品牌识别)分类下获奖作品
封面图，输出与其它抓取器一致：<out>/Indigo/<year>/  +  <out>/Indigo/sources.csv

用法：
  python fetch_indigo.py --config configs/indigo.json --out 图包/国际奖项
"""
import os, re, csv, json, time, argparse, hashlib, urllib.parse, urllib.request
from datetime import datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def fetch_year(year):
    url = f"https://www.indigoaward.com/winners/competition/{year}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("no __NEXT_DATA__")
    d = json.loads(m.group(1))
    return url, d["props"]["pageProps"]["data"]


def download(url, out_path, min_bytes):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=90) as r:
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
    ap.add_argument("--chrome", required=False)
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    award = cfg["award"]
    categories = cfg.get("categories", ["Branding"])
    # 兼容不同年份的分类层级：某些年份 Branding/Logos 是 Graphic Design 下的子类
    sub_titles = set(t.lower() for t in cfg.get("sub_titles", ["Branding", "Logos"]))
    max_per_year = cfg.get("max_per_year", 18)
    min_bytes = cfg.get("min_bytes", 8000)

    award_dir = os.path.join(args.out, award)
    os.makedirs(award_dir, exist_ok=True)
    src_rows = []

    for page in cfg["pages"]:
        year = str(page["year"])
        print(f"[{award} {year}] /winners/competition/{year}")
        try:
            page_url, data = fetch_year(year)
        except Exception as e:
            print(f"    [err] {e}"); continue
        comp_name = (data.get("competition") or {}).get("name")
        if str(comp_name) != year:
            print(f"    [warn] 页面返回届次={comp_name} 与请求 {year} 不符")
        groups = data.get("allWinners", [])
        # 收集目标分类下所有作品(保序)
        picks = []
        for g in groups:
            gname = g.get("main_category_name")
            for s in g.get("subCategories", []):
                stitle = s.get("title", "")
                # 命中条件：① 顶层分类在 categories 中（取该分类全部子类）
                #          ② 或 子类标题在 sub_titles 中（兼容 Graphic Design > Branding/Logos）
                if gname in categories or stitle.lower() in sub_titles:
                    for it in s.get("winnersItem", []):
                        cov = it.get("cover")
                        if cov:
                            picks.append((gname, stitle, it, cov))
        print(f"    候选作品 {len(picks)} (分类 {categories} / 子类 {sorted(sub_titles)})")

        ydir = os.path.join(award_dir, year)
        n = 0; seen = set()
        for cat, sub, it, cov in picks:
            if n >= max_per_year:
                break
            if cov in seen:
                continue
            seen.add(cov)
            base = os.path.basename(urllib.parse.urlparse(cov).path)
            h = hashlib.sha1(cov.encode()).hexdigest()[:8]
            fn = f"{award}_{year}_{n+1:02d}_{h}_{base}"[:120]
            outp = os.path.join(ydir, fn)
            ok, info = download(cov, outp, min_bytes)
            if ok:
                n += 1
                src_rows.append({"award": award, "year": year, "file": fn,
                                 "url": cov, "bytes": info,
                                 "category": cat, "sub_category": sub,
                                 "title": (it.get("title") or "")[:120],
                                 "creator": it.get("creator", ""),
                                 "page": page_url,
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

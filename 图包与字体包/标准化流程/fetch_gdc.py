# -*- coding: utf-8 -*-
"""GDC Award 专用抓取器。GDC 为双年展，bo 参数=届次：
   bo9=2025, bo8=2023, bo7=2021, bo6=2019, bo5=2017。
   列表页每页6个作品(before_works/detail?id=)，详情页含作品图(腾讯COS)。
   每个作品取前若干张图(默认取封面1张)，按年份归档，写 sources.csv。
用法: python fetch_gdc.py --out 图包/中文奖项 --chrome <chrome> [--per-edition 15] [--imgs-per-work 1]
"""
import os, re, sys, csv, time, html, argparse, subprocess, hashlib, urllib.request
from datetime import datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
EDITIONS = {"9": "2025", "8": "2023", "7": "2021", "6": "2019", "5": "2017"}
CDN = re.compile(r'https://gdc-\d+\.cos[^"\']+?\.(?:jpg|jpeg|png|webp)', re.I)


def render(chrome, url, budget=12000):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--dump-dom",
           f"--virtual-time-budget={budget}", "--hide-scrollbars",
           "--window-size=1400,3000", url]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=budget/1000+30).stdout.decode("utf-8", "ignore")
    except Exception as e:
        print("   render err", e); return ""


def dl(url, out, min_bytes=8000):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=60).read()
        if len(data) < min_bytes:
            return False, f"small {len(data)}"
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(data)
        return True, len(data)
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--chrome", required=True)
    ap.add_argument("--per-edition", type=int, default=15)
    ap.add_argument("--imgs-per-work", type=int, default=1)
    args = ap.parse_args()

    adir = os.path.join(args.out, "GDC")
    os.makedirs(adir, exist_ok=True)
    rows = []

    for bo, year in EDITIONS.items():
        print(f"[GDC {year}] bo={bo}")
        ids = []
        for page in range(1, 6):
            url = f"https://www.gdcaward.com/gdc-works?bo={bo}&pagenum={page}&lang=cn"
            h = render(args.chrome, url)
            pids = re.findall(r'before_works/detail\?id=(\d+)', h)
            new = [i for i in dict.fromkeys(pids) if i not in ids]
            ids += new
            if not new:
                break
            if len(ids) >= args.per_edition + 3:
                break
        print(f"   收集作品 {len(ids)} 个")
        n = 0
        for wid in ids:
            if n >= args.per_edition:
                break
            durl = f"https://www.gdcaward.com/op/before_works/detail?id={wid}&bo={bo}&lang=cn"
            dh = render(args.chrome, durl, 10000)
            imgs = list(dict.fromkeys(CDN.findall(dh)))
            imgs = [u for u in imgs if not re.search(r'(logo_02|icon|banner|wechat|avatar)', u, re.I)]
            got = 0
            for u in imgs[:args.imgs_per_work]:
                base = os.path.basename(u.split("?")[0])
                fn = f"GDC_{year}_{n+1:02d}_{wid}_{base}"[:120]
                ok, info = dl(u, os.path.join(adir, year, fn))
                if ok:
                    got += 1
                    rows.append({"award": "GDC", "year": year, "bo": bo, "work_id": wid,
                                 "file": fn, "url": u, "bytes": info, "page": durl,
                                 "fetched": datetime.now().isoformat(timespec="seconds")})
                time.sleep(0.2)
            if got:
                n += 1
        print(f"   下载 {n} 个作品图 -> {adir}/{year}")

    if rows:
        sp = os.path.join(adir, "sources.csv")
        wh = not os.path.exists(sp)
        with open(sp, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            if wh:
                w.writeheader()
            w.writerows(rows)
        print(f"来源 -> {sp} (+{len(rows)})")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
GLYPH 获奖图包抓取器 (scrape_award.py)
=====================================
通用流程：用无头 Chrome 渲染列表/画廊页 -> 抽取图片URL -> 选原图/大图 -> 下载并按年份归档。
不做站点专属魔法，只提供确定性、可复现、可审计的抓取骨架；每个奖项用一个 config(JSON)描述。

config 示例(见 configs/*.json)：
{
  "award": "WOLDA",
  "scope": "国际奖项",
  "pages": [ {"year":"2024","url":"https://...","edition":"17th"}, ... ],
  "img_regex": "wp-content/uploads/.*\\.(jpg|jpeg|png)",
  "prefer_largest": true,          # 同名多尺寸时取最大
  "exclude": ["logo","icon","banner","avatar","-80x","-36x","-120x","150x150"],
  "max_per_year": 20,
  "min_bytes": 6000
}

用法：
  python scrape_award.py --config configs/wolda.json --out 图包/国际奖项 --chrome "<chrome.exe>"
每张图会写 <year>/ 下，并生成 sources.csv 记录来源URL与抓取时间(便于版权/复现)。
"""
import os, re, sys, csv, json, time, argparse, subprocess, hashlib, urllib.parse
from datetime import datetime
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def render_dom(chrome, url, budget_ms=12000):
    """无头 Chrome 渲染并 dump DOM。"""
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--dump-dom", f"--virtual-time-budget={budget_ms}",
           "--hide-scrollbars", "--window-size=1400,3000", url]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=budget_ms/1000 + 30)
        return out.stdout.decode("utf-8", "ignore")
    except Exception as e:
        print(f"    [render err] {e}")
        return ""


def extract_imgs(html, base_url, img_regex):
    """从 DOM 抽取图片URL，含 src / data-src / srcset / background。"""
    urls = set()
    for m in re.finditer(r'(?:src|data-src|data-lazy-src|data-original)="([^"]+)"', html):
        urls.add(m.group(1))
    for m in re.finditer(r'srcset="([^"]+)"', html):
        for part in m.group(1).split(","):
            u = part.strip().split(" ")[0]
            if u:
                urls.add(u)
    for m in re.finditer(r'url\((["\']?)([^)"\']+)\1\)', html):
        urls.add(m.group(2))
    # 归一化为绝对URL + 过滤
    out = set()
    rx = re.compile(img_regex, re.I)
    for u in urls:
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = urllib.parse.urljoin(base_url, u)
        if rx.search(u):
            out.add(u)
    return out


def largest_variant(url):
    """把 WordPress 缩略图尺寸后缀(-1030x748)去掉，尽量取原图。"""
    return re.sub(r'-\d{2,4}x\d{2,4}(?=\.(jpg|jpeg|png|webp)$)', '', url, flags=re.I)


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
    ap.add_argument("--chrome", required=True)
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    award = cfg["award"]
    exclude = [e.lower() for e in cfg.get("exclude", [])]
    prefer_largest = cfg.get("prefer_largest", True)
    max_per_year = cfg.get("max_per_year", 20)
    min_bytes = cfg.get("min_bytes", 6000)
    img_regex = cfg["img_regex"]

    award_dir = os.path.join(args.out, award)
    os.makedirs(award_dir, exist_ok=True)
    src_rows = []

    for page in cfg["pages"]:
        year = page["year"]; url = page["url"]
        print(f"[{award} {year}] {url}")
        html = render_dom(args.chrome, url, page.get("budget_ms", 12000))
        if not html:
            print("    (空DOM, 跳过)"); continue
        imgs = extract_imgs(html, url, img_regex)
        # 排除干扰图
        kept = []
        for u in sorted(imgs):
            low = u.lower()
            if any(x in low for x in exclude):
                continue
            kept.append(largest_variant(u) if prefer_largest else u)
        kept = sorted(set(kept))
        print(f"    候选图 {len(imgs)} -> 过滤后 {len(kept)}")

        ydir = os.path.join(award_dir, year)
        n = 0
        seen = set()
        for u in kept:
            if n >= max_per_year:
                break
            base = os.path.basename(urllib.parse.urlparse(u).path)
            h = hashlib.sha1(u.encode()).hexdigest()[:8]
            fn = f"{award}_{year}_{n+1:02d}_{h}_{base}"[:120]
            outp = os.path.join(ydir, fn)
            ok, info = download(u, outp, min_bytes)
            if ok:
                n += 1
                src_rows.append({"award": award, "year": year, "file": fn,
                                 "url": u, "bytes": info,
                                 "page": url, "fetched": datetime.now().isoformat(timespec="seconds")})
            time.sleep(0.2)
        print(f"    下载 {n} 张 -> {ydir}")

    # sources.csv
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

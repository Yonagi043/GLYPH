# -*- coding: utf-8 -*-
"""
Golden Pin 專用抓取器 (scrape_goldenpin.py)
==========================================
金點設計獎官網為 SPA，獲獎列表經由帶 CSRF Token + Cookie 的 POST API
  /goldenpin/api/v1/get_total_works
載入，沒有「按年份/類別」的靜態 URL，因此通用 scrape_award.py(渲染URL的DOM)無法驅動。
本腳本讀取同格式的 configs/goldenpin.json，直接呼叫該 API，按 (year, main_category,
sub_category) 取得「傳達設計 > 企業/品牌識別」獲獎作品的原圖，輸出與 scrape_award.py
完全一致：<out>/<award>/<year>/  +  <out>/<award>/sources.csv

用法：
  python scrape_goldenpin.py --config configs/goldenpin.json --out 图包/中文奖项
"""
import os, re, csv, json, time, argparse, hashlib, http.cookiejar, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def build_opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    return op


def get_csrf(opener, index_url):
    with opener.open(index_url, timeout=60) as r:
        html = r.read().decode("utf-8", "ignore")
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    if not m:
        m = re.search(r'content="([^"]+)"\s+name="csrf-token"', html)
    return m.group(1) if m else None


def api_call(opener, api_url, token, referer, year, prize, main_cat, sub_cat, index):
    fields = [("year", str(year)), ("prize", str(prize)), ("index", str(index)),
              ("is_main_category", "true"), ("main_category", str(main_cat)),
              ("search", ""), ("lang", "zh-TW")]
    if sub_cat is not None:
        fields.append(("sub_category[]", str(sub_cat)))
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(api_url, data=data, headers={
        "X-CSRF-Token": token, "X-Requested-With": "XMLHttpRequest",
        "Referer": referer, "Origin": "https://goldenpin.org.tw",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with opener.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def download(opener, url, out_path, min_bytes):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with opener.open(req, timeout=90) as r:
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
    ap.add_argument("--chrome", required=False)  # 接受但不使用，保持與 scrape_award.py 命令一致
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    award = cfg["award"]
    api_url = cfg["api"]
    index_url = cfg["index_page"]
    prize = cfg.get("prize", "1")
    exclude = [e.lower() for e in cfg.get("exclude", [])]
    max_per_year = cfg.get("max_per_year", 18)
    min_bytes = cfg.get("min_bytes", 8000)
    img_rx = re.compile(cfg["img_regex"], re.I)

    award_dir = os.path.join(args.out, award)
    os.makedirs(award_dir, exist_ok=True)

    opener = build_opener()
    token = get_csrf(opener, index_url)
    print(f"[csrf] {'ok' if token else 'FAILED'}")
    if not token:
        print("無法取得 CSRF token，中止。"); return

    from datetime import datetime
    src_rows = []
    for page in cfg["pages"]:
        year = str(page["year"]); mc = page["main_category"]; sc = page.get("sub_category")
        print(f"[{award} {year}] main_category={mc} sub_category={sc}")
        # 分頁收集作品(每頁30)，直到湊夠或無更多
        works = []
        seen_ids = set()
        idx = 0
        while len(works) < max_per_year * 2 and idx < 300:
            try:
                d = api_call(opener, api_url, token, index_url, year, prize, mc, sc, idx)
            except Exception as e:
                print(f"    [api err] {e}"); break
            batch = d.get("award_works", []) if d.get("stage") == "ok" else []
            if not batch:
                break
            new = 0
            for w in batch:
                if w.get("id") in seen_ids:
                    continue
                seen_ids.add(w.get("id")); works.append(w); new += 1
            count = d.get("count", 0)
            idx += len(batch)
            if new == 0 or idx >= count:
                break
            time.sleep(0.3)
        print(f"    取得作品 {len(works)} 件 (類別總數 count={d.get('count') if 'd' in dir() else '?'})")

        ydir = os.path.join(award_dir, year)
        n = 0
        for w in works:
            if n >= max_per_year:
                break
            li = w.get("list_image") or {}
            url = li.get("url")  # 原圖(非 thumb)
            if not url:
                continue
            low = url.lower()
            if not img_rx.search(url) or any(x in low for x in exclude):
                continue
            base = os.path.basename(urllib.parse.urlparse(url).path)
            h = hashlib.sha1(url.encode()).hexdigest()[:8]
            fn = f"{award.replace(' ','')}_{year}_{n+1:02d}_{h}_{base}"[:120]
            outp = os.path.join(ydir, fn)
            ok, info = download(opener, url, outp, min_bytes)
            if ok:
                n += 1
                src_rows.append({"award": award, "year": year, "file": fn,
                                 "url": url, "bytes": info,
                                 "work_id": w.get("id"),
                                 "title": (w.get("title_en") or w.get("title_zh") or "")[:120],
                                 "page": f"{index_url}#{year}/comm/brand-identity",
                                 "fetched": datetime.now().isoformat(timespec="seconds")})
            time.sleep(0.2)
        print(f"    下載 {n} 張 -> {ydir}")

    if src_rows:
        sp = os.path.join(award_dir, "sources.csv")
        write_header = not os.path.exists(sp)
        with open(sp, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(src_rows[0].keys()))
            if write_header:
                w.writeheader()
            w.writerows(src_rows)
        print(f"來源記錄 -> {sp} (+{len(src_rows)})")


if __name__ == "__main__":
    main()

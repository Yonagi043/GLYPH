# -*- coding: utf-8 -*-
"""
GLYPH 视觉刺激标准化流程 (standardize.py)
===========================================
目的：把所有 logo 图包 与 字体渲染样张 "剔除命题无关特征、统一到同一起点"，
     使跨文字系统的视觉比较只保留字形/结构本身，去除颜色、尺寸、留白、背景等混杂变量。

统一到同一起点 = 一张图片依次经过下列确定性步骤，任何输入都落到同一基准：
  1. 载入 → 转 RGBA（统一色彩模型）
  2. 去背景：将接近纯���/纯透明的边缘视为背景，自动裁到内容外接框（trim）
  3. 去色 / 灰度：RGB→单通道亮度（命题无关的颜色被剔除）
  4. 可选二值化（本项目默认关闭，用灰度）
  5. 等比缩放：按最长边缩放到 CONTENT 尺寸，绝不拉伸变形（保留曲直比例）
  6. 居中贴到统一正方形画布 CANVAS，四周留白固定 → 留白比例统一
  7. 归一化背景为纯白(255)，前景为灰度 → 统一起点
  8. 输出 PNG（无损）+ 记录每张图的处理参数到 manifest

设计原则：确定性、可复现、参数集中在 CONFIG，一处修改全局一致。
用法：
  python standardize.py --in <输入目录> --out <输出目录> --kind logo|font
  python standardize.py --self-test        # 生成一张合成图跑通全流程
"""
import os, sys, csv, json, argparse, hashlib
from datetime import datetime
from PIL import Image, ImageOps, ImageChops

# ---------------- CONFIG：统一起点的全部参数 ----------------
CANVAS   = 512          # 统一画布边长(px)，正方形
CONTENT  = 448          # 内容最长边缩放到的尺寸；(CANVAS-CONTENT)/2 = 32px 四周留白
BG        = 255         # 统一背景灰度(纯白)
GRAYSCALE = True        # 去色→灰度
BINARIZE  = False       # 是否二值化(纯黑白)。本项目默认 False，用灰度
BIN_THRESHOLD = 200     # 二值化阈值(仅 BINARIZE=True 时)
TRIM_BORDER_TOL = 12    # 判定"背景边"的容差：与角落像素差<该值视为背景
TRIM_ALPHA_TOL  = 8     # 透明度<该值视为透明背景
# -----------------------------------------------------------

VALID_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _flatten_to_white(im):
    """任何模式 → RGB，透明区域填白。"""
    im = im.convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def _autocrop(im_rgb, im_rgba):
    """去背景/裁到内容外接框。优先用 alpha，其次用与角落同色的白边。"""
    # 1) 依据 alpha 通道
    alpha = im_rgba.split()[-1]
    bbox = None
    if alpha.getextrema()[0] < 255:  # 存在透明
        mask = alpha.point(lambda a: 255 if a > TRIM_ALPHA_TOL else 0)
        bbox = mask.getbbox()
    # 2) 依据边缘背景色（取四角均值作为背景基准）
    if bbox is None:
        w, h = im_rgb.size
        corners = [im_rgb.getpixel(p) for p in
                   [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]]
        bg_color = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
        bgimg = Image.new("RGB", im_rgb.size, bg_color)
        diff = ImageChops.difference(im_rgb, bgimg).convert("L")
        mask = diff.point(lambda d: 255 if d > TRIM_BORDER_TOL else 0)
        bbox = mask.getbbox()
    if bbox:
        return im_rgb.crop(bbox)
    return im_rgb  # 全空则原样返回


def standardize_image(path, out_path):
    """对单张图片执行完整标准化，返回处理元数据 dict。"""
    with Image.open(path) as raw:
        raw.load()
        orig_size = raw.size
        rgba = raw.convert("RGBA")
        rgb  = _flatten_to_white(raw)

    # 去背景 → 内容外接框
    content = _autocrop(rgb, rgba)
    cw, ch = content.size
    if cw == 0 or ch == 0:
        content = rgb
        cw, ch = content.size

    # 去色 / 灰度
    if GRAYSCALE:
        content = ImageOps.grayscale(content)   # L 模式
    if BINARIZE:
        content = content.point(lambda p: 255 if p >= BIN_THRESHOLD else 0, mode="L")

    # 等比缩放到 CONTENT 最长边（不拉伸）
    scale = CONTENT / max(cw, ch)
    new_w, new_h = max(1, round(cw * scale)), max(1, round(ch * scale))
    content = content.resize((new_w, new_h), Image.LANCZOS)

    # 居中贴到统一画布
    mode = "L"
    canvas = Image.new(mode, (CANVAS, CANVAS), BG)
    off = ((CANVAS - new_w) // 2, (CANVAS - new_h) // 2)
    canvas.paste(content, off)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    canvas.save(out_path, "PNG", optimize=True)

    with open(path, "rb") as f:
        sha = hashlib.sha1(f.read()).hexdigest()[:12]

    return {
        "src": path, "out": out_path, "src_sha1": sha,
        "orig_w": orig_size[0], "orig_h": orig_size[1],
        "content_w": cw, "content_h": ch,
        "scale": round(scale, 4),
        "canvas": CANVAS, "content_max": CONTENT,
        "grayscale": GRAYSCALE, "binarize": BINARIZE, "bg": BG,
    }


def run_dir(in_dir, out_dir, kind, log_rows):
    n_ok, n_err = 0, 0
    for root, _, files in os.walk(in_dir):
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in VALID_EXT:
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, in_dir)
            out = os.path.join(out_dir, os.path.splitext(rel)[0] + ".png")
            try:
                meta = standardize_image(src, out)
                meta["kind"] = kind
                log_rows.append(meta)
                n_ok += 1
            except Exception as e:
                print(f"  [ERR] {rel}: {e}")
                n_err += 1
    print(f"  {kind}: 成功 {n_ok}，失败 {n_err}")
    return n_ok, n_err


def self_test():
    """生成一张彩色带白边合成图，跑通全流程并校验输出。"""
    from PIL import ImageDraw
    tdir = os.path.join(os.path.dirname(__file__), "_selftest")
    os.makedirs(tdir, exist_ok=True)
    im = Image.new("RGB", (800, 400), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([250, 120, 420, 290], fill=(200, 30, 30))
    d.rectangle([440, 150, 560, 260], fill=(20, 60, 180))
    src = os.path.join(tdir, "sample.png"); im.save(src)
    out = os.path.join(tdir, "sample_std.png")
    meta = standardize_image(src, out)
    with Image.open(out) as o:
        assert o.size == (CANVAS, CANVAS), o.size
        assert o.mode == "L"
    print("[self-test] OK ->", out)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir")
    ap.add_argument("--out", dest="out_dir")
    ap.add_argument("--kind", default="logo", choices=["logo", "font"])
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test(); return
    if not args.in_dir or not args.out_dir:
        ap.error("需要 --in 和 --out")

    log_rows = []
    run_dir(args.in_dir, args.out_dir, args.kind, log_rows)

    # 写 manifest（CSV + JSON）
    if log_rows:
        stamp = datetime.now().strftime("%Y%m%d")
        base = os.path.join(args.out_dir, f"_manifest_{args.kind}_{stamp}")
        with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()))
            w.writeheader(); w.writerows(log_rows)
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump({"config": {"CANVAS": CANVAS, "CONTENT": CONTENT, "BG": BG,
                                   "GRAYSCALE": GRAYSCALE, "BINARIZE": BINARIZE},
                       "items": log_rows}, f, ensure_ascii=False, indent=2)
        print(f"  manifest -> {base}.csv / .json")


if __name__ == "__main__":
    main()

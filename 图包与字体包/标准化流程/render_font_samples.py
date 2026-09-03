# -*- coding: utf-8 -*-
"""
GLYPH 字体样张渲染 (render_font_samples.py)
==========================================
把每个字体文件渲染成"标准字符样张"图片，再交给 standardize.py 统一到同一起点。
每个字体渲染同一组受控字符串（按文字系统选择代表字符），黑字白底、字面居中，
使字体之间只在字形上有差异，其它命题无关变量(颜色/背景/字号名义值)一致。

用法：
  python render_font_samples.py --fonts <字体包目录> --out <输出目录>
"""
import os, sys, argparse
from PIL import Image, ImageDraw, ImageFont

# 每种文字系统的受控样张字符（尽量覆盖字形结构；不含品牌名，避免命题相关语义）
SAMPLES = {
    "拉丁文字": "Aa Bb Gg Rр  Handgloves  1234",
    "汉字":     "永 東 國 龍 鳳  字体审美  0123",
    "韩文":     "가 나 다 라 한글  로고  0123",
    "片假名":   "ア イ ウ エ オ  カタカナ  0123",
}
RENDER_PX = 900   # 渲染画布宽（高自适应），后续会被 standardize 统一
FONT_SIZE = 120


def render_one(font_path, text, out_path):
    try:
        font = ImageFont.truetype(font_path, FONT_SIZE)
    except Exception as e:
        # 可变字体在旧 PIL 上可能需 layout；直接报错跳过
        raise RuntimeError(f"load font failed: {e}")
    # 量测文本尺寸
    tmp = Image.new("L", (10, 10), 255)
    d = ImageDraw.Draw(tmp)
    bbox = d.multiline_textbbox((0, 0), text, font=font, spacing=20)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 40
    W, H = tw + pad * 2, th + pad * 2
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    d.multiline_text((pad - bbox[0], pad - bbox[1]), text, fill=0,
                     font=font, spacing=20)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    im.save(out_path, "PNG")
    return (W, H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, help="字体包根目录(含 拉丁文字/汉字/...)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    n_ok = n_err = 0
    for script, text in SAMPLES.items():
        sdir = os.path.join(args.fonts, script)
        if not os.path.isdir(sdir):
            print(f"  [skip] 无目录 {script}"); continue
        for fn in sorted(os.listdir(sdir)):
            if not fn.lower().endswith((".ttf", ".otf")):
                continue
            fpath = os.path.join(sdir, fn)
            stem = os.path.splitext(fn)[0]
            out = os.path.join(args.out, script, stem + ".png")
            try:
                sz = render_one(fpath, text, out)
                print(f"  [ok] {script}/{fn} {sz}")
                n_ok += 1
            except Exception as e:
                print(f"  [ERR] {script}/{fn}: {e}")
                n_err += 1
    print(f"渲染完成：成功 {n_ok}，失败 {n_err}")


if __name__ == "__main__":
    main()

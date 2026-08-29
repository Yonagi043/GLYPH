"""Build a screen-share friendly PDF briefing with embedded CJK font."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/processed/visual_features_v1/runs/render_551362ca0ff22f33"
OUT = ROOT / "docs/GLYPH_v1.2.0_group_meeting_brief.pdf"
ASSET_DIR = ROOT / "docs/meeting_brief_assets"
REPO_URL = "https://github.com/Yonagi043/GLYPH"
PAGE = landscape(letter)

# Use the repository's CJK-complete serif font for the briefing text.  The
# Iansui display font is intentionally retained for rendered stimulus assets,
# but it does not cover every Chinese character used in this document.
pdfmetrics.registerFont(TTFont("NotoSerifSC", str(ROOT / "data/assets/fonts/NotoSerifSC-Regular.ttf")))
pdfmetrics.registerFont(TTFont("NotoSansKR", str(ROOT / "data/assets/fonts/NotoSansKR-static.ttf")))
FONT = "NotoSerifSC"

NAVY = colors.HexColor("#0B2545")
BLUE = colors.HexColor("#2E74B5")
PALE = colors.HexColor("#E8EEF5")
LIGHT = colors.HexColor("#F2F4F7")
INK = colors.HexColor("#1E1E1E")
MUTED = colors.HexColor("#5A6470")


def styles():
    return {
        "title": ParagraphStyle("title", fontName=FONT, fontSize=30, leading=34, textColor=NAVY, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT, fontSize=17, leading=22, textColor=INK, spaceAfter=6),
        "meta": ParagraphStyle("meta", fontName=FONT, fontSize=9.5, leading=13, textColor=MUTED),
        "h1": ParagraphStyle("h1", fontName=FONT, fontSize=19, leading=23, textColor=BLUE, spaceBefore=2, spaceAfter=8),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=11.5, leading=17, textColor=INK, spaceAfter=7),
        "small": ParagraphStyle("small", fontName=FONT, fontSize=9.3, leading=13, textColor=INK),
        "small_center": ParagraphStyle("small_center", fontName=FONT, fontSize=9.4, leading=13, alignment=TA_CENTER, textColor=INK),
        "small_kr": ParagraphStyle("small_kr", fontName="NotoSansKR", fontSize=9.3, leading=13, textColor=INK),
        "white_metric": ParagraphStyle("white_metric", fontName=FONT, fontSize=24, leading=28, alignment=TA_CENTER, textColor=colors.white),
        "metric_label": ParagraphStyle("metric_label", fontName=FONT, fontSize=9.5, leading=12, alignment=TA_CENTER, textColor=NAVY),
    }


def footer(canvas: Canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(PAGE[0] / 2, 0.34 * inch, "GLYPH  |  内部组会简报  |  2026-08-30")
    canvas.restoreState()


def contact_sheet() -> Path:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSET_DIR / "han_yong_font_comparison.png"
    items = [("Noto Sans CJK SC", "stim_046feb329e243591.gray.png"), ("Noto Serif SC", "stim_43e4de4c0226c52b.gray.png"), ("Bpmf Iansui", "stim_7b6b8cc8ec5488f4.gray.png"), ("LXGW Marker Gothic", "stim_32f7caf9902568e8.gray.png")]
    sheet = Image.new("RGB", (1200, 760), (248, 249, 250)); draw = ImageDraw.Draw(sheet)
    for i, (label, file) in enumerate(items):
        x, y = (i % 2) * 600, (i // 2) * 380
        img = Image.open(RUN / "rendered" / file).convert("L").resize((560, 280))
        sheet.paste(Image.merge("RGB", (img, img, img)), (x + 20, y + 48)); draw.text((x + 24, y + 16), label, fill=(11, 37, 69))
    sheet.save(path); return path


def P(text, style): return Paragraph(text, style)


def build_story():
    s = styles(); story = []
    story += [Spacer(1, 0.35 * inch), P("GLYPH", s["title"]), P("第一版视觉特征数据基础", s["subtitle"]), P("组会简报 · protocol visual_features_v1.2.0", s["meta"]), Spacer(1, 0.18 * inch)]
    meta = [[P("仓库", s["small"]), P(REPO_URL, s["small"])], [P("参考运行", s["small"]), P("render_551362ca0ff22f33", s["small"])], [P("数据规模", s["small"]), P("140 个刺激 · 280 条视觉特征记录", s["small"])], [P("当前状态", s["small"]), P("技术链完成；等待两名组员独立完成 fixture 审查", s["small"])]]
    t = Table(meta, colWidths=[1.25 * inch, 8.75 * inch]); t.setStyle(TableStyle([("BACKGROUND", (0,0),(0,-1), PALE), ("TEXTCOLOR", (0,0),(0,-1), NAVY), ("VALIGN", (0,0),(-1,-1), "MIDDLE"), ("BOX", (0,0),(-1,-1), 0.5, colors.HexColor("#D5DDE7")), ("INNERGRID", (0,0),(-1,-1), 0.25, colors.white), ("LEFTPADDING", (0,0),(-1,-1), 10), ("RIGHTPADDING", (0,0),(-1,-1), 10), ("TOPPADDING", (0,0),(-1,-1), 7), ("BOTTOMPADDING", (0,0),(-1,-1), 7)])); story += [t, Spacer(1, 0.2 * inch)]
    story += [P("一句话结论：我们已经把“字体审美”第一步收紧成一套可复现、可审查、可继续扩展的视觉测量基础；它不是审美真值，也没有替代真人实验。", s["body"]), Spacer(1, 0.08 * inch), P("1. 我们现在拿到了什么", s["h1"])]
    metrics = [[P("140", s["white_metric"]), P("280", s["white_metric"]), P("7", s["white_metric"]), P("0", s["white_metric"])], [P("唯一刺激", s["metric_label"]), P("特征记录", s["metric_label"]), P("开放字体资产", s["metric_label"]), P("主运行失败", s["metric_label"])]]
    mt = Table(metrics, colWidths=[2.5*inch]*4, rowHeights=[0.52*inch,0.35*inch]); mt.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0), NAVY), ("BACKGROUND", (0,1),(-1,1), LIGHT), ("VALIGN", (0,0),(-1,-1), "MIDDLE"), ("BOX", (0,0),(-1,-1), 0.5, colors.white), ("INNERGRID", (0,0),(-1,-1), 0.5, colors.white), ("TOPPADDING", (0,0),(-1,-1), 5), ("BOTTOMPADDING", (0,0),(-1,-1), 5)])); story += [mt, Spacer(1, 0.18*inch), P("所有数据和运行产物都带有 manifest、字体哈希、许可证状态、PNG/mask 哈希、QC 报告和 checksums。", s["body"]), PageBreak()]
    story += [P("2. 研究矩阵与标准化", s["h1"])]
    matrix_data = [[P(x, s["small"]) for x in ["文字系统", "内容", "基线字体", "WP4 汉字范例"]]]
    for row in [("Latn", "A E H M O R S T + 2 序列", "Noto Sans", "—"), ("Hani", "永 山 水 中 文 門 木 人 + 2 序列", "Noto Sans CJK SC", "Serif / Iansui / Marker Gothic"), ("Kana", "あ い す ね の ま る よ + 2 序列", "Noto Sans CJK JP", "—")]:
        matrix_data.append([P(x, s["small"]) for x in row])
    hang = ("Hang", "가 나 다 라 마 바 사 아 + 2 序列", "Noto Sans KR", "—")
    matrix_data.append([P(hang[0], s["small"]), P(hang[1], s["small_kr"]), P(hang[2], s["small"]), P(hang[3], s["small"])])
    tab = Table(matrix_data, colWidths=[1.4*inch, 3.15*inch, 2.55*inch, 2.9*inch]); tab.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0), PALE), ("TEXTCOLOR", (0,0),(-1,0), NAVY), ("GRID", (0,0),(-1,-1), 0.35, colors.HexColor("#C9D2DD")), ("VALIGN", (0,0),(-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0),(-1,-1), 8), ("RIGHTPADDING", (0,0),(-1,-1), 8), ("TOPPADDING", (0,0),(-1,-1), 7), ("BOTTOMPADDING", (0,0),(-1,-1), 7)])); story += [tab, Spacer(1, 0.15*inch), P("两个 profile：bbox_height_matched = 320 px；ink_area_matched = 0.050。所有字体、字符、地区语言标签、画布和整形参数均固定。", s["body"]), P("管线：资产登记 → NFC + HarfBuzz cluster 校验 → Pillow/FreeType BASIC 渲染 → 等比例归一化 → 灰度/二值特征 → QC → 人工 fixture 审查 → release。", s["body"]), PageBreak()]
    story += [P("3. 真实样本：同一汉字的四种字体", s["h1"]), RLImage(str(contact_sheet()), width=9.6*inch, height=6.08*inch), Spacer(1, 0.08*inch), P("图：字符“永”在四个汉字字体范例中的规范化输出。测量记录包括 ink coverage、bbox aspect ratio、对称性、闭合空间、骨架直/曲比例等。", s["meta"]), PageBreak()]
    story += [P("4. 组员审查与下一步", s["h1"]), P("审查不是给字体打审美分，而是确认样本和协议没有明显的输入错误。请两名组员独立检查同一份 28 条 fixture 清单，不先互相讨论后合并。", s["body"])]
    review = [[P(x, s["small"]) for x in ["检查项", "要看什么", "填写字段"]], [P("刺激网格", s["small"]), P("28 条 fixture 是否齐全、内容和 profile 是否对应", s["small"]), P("visual_grid_pass", s["small"])], [P("字符边界", s["small"]), P("字符顺序、边界和地区字形是否异常", s["small"]), P("character_boundary_pass", s["small"])], [P("书体归类", s["small"]), P("字体角色/风格标签是否与图像一致", s["small"]), P("style_classification_pass", s["small"])]]
    rt = Table(review, colWidths=[1.65*inch, 5.3*inch, 3.05*inch]); rt.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0), PALE), ("GRID", (0,0),(-1,-1), 0.35, colors.HexColor("#C9D2DD")), ("VALIGN", (0,0),(-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0),(-1,-1), 8), ("RIGHTPADDING", (0,0),(-1,-1), 8), ("TOPPADDING", (0,0),(-1,-1), 7), ("BOTTOMPADDING", (0,0),(-1,-1), 7)])); story += [rt, Spacer(1, 0.16*inch), P("审查表：data/processed/visual_features_v1/human_review/fixture_review_records.csv", s["body"]), P("审查完成后运行：uv run --locked --extra dev python -m glyph_features.cli release --run-id render_551362ca0ff22f33", s["small"]), Spacer(1, 0.16*inch), P("边界：当前成果是视觉测量，不是综合审美分数；下一轮继续沿用 stimulus_id、schema、许可证分层和 run 哈希。", s["body"]), P(REPO_URL, s["subtitle"])]
    return story


def main():
    doc = SimpleDocTemplate(str(OUT), pagesize=PAGE, leftMargin=0.72*inch, rightMargin=0.72*inch, topMargin=0.55*inch, bottomMargin=0.55*inch)
    doc.build(build_story(), onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__": main()

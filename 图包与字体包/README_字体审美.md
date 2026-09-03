# 字体审美 · 素材与标准化流程 README

本目录为 GLYPH 研究（跨文字系统字标视觉审美）的素材与预处理工作区。
包含：① 四文字系统标准字体包（每种 3 款字族）② 五大奖项获奖 logo 图包（近5年，按年份归档）
③ 一套确定性"标准化流程"，把所有字体样张与 logo 图"剔除命题无关特征、统一到同一起点"。

## 数据总览（截至 2026-09-03，全部已抓取 + 已标准化）

| 范畴 | 奖项 | 年份覆盖 | 原图数 | 标准化数 | 备注 |
|---|---|---|---|---|---|
| 国际 | **WOLDA** | 2020–2024 (12th–16th) | 87 | 87 | 作品展板，含标题/奖牌 |
| 国际 | **Indigo** | 2020–2024 | 90 | 90 | Branding 类孤立封面图，最干净 |
| 中文 | **DFA** (Design for Asia) | 2020–2024 | 80 | 80 | Communication 类项目封面 |
| 中文 | **Golden Pin** 金點設計獎 | 2022–2025 | 72 | 72 | 傳達設計>品牌識別；官网仅 4 连续年 |
| 中文 | **GDC** (AIGA China) | 2021/2023/2025 | 46 | 46 | 双年展，3 届≈近5年窗口 |
| — | **合计** | — | **375** | **375** | 每张均有 sources.csv 溯源 |

> **原定 6 个奖项，最终收官为 5 个。** 国际第 3 个奖位在实测中放弃：A' Design、iF、German
> Design Award、DIA、DNA Paris、MUSE 等顶级奖官网均为 JS 无限滚动、或忽略年份/类别参数
> 返回同一页，无法在合理成本内"按年份 + 品牌类"分档抓取。经确认，以现有 5 个可靠奖项收官
> （近5年、每年约 16–18 张，样本量对研究第 3 条线视觉量化已充分）。字体样张见 `标准化输出/字体样张/`。

## 目录结构

```
字体审美/
├── 字体包/                      # 标准字体（每种文字3款字族）
│   ├── 拉丁文字/  Roboto, Open Sans, Lato
│   ├── 汉字/      Noto Sans SC, Noto Serif SC, Ma Shan Zheng
│   ├── 韩文/      Noto Sans KR, Noto Serif KR, Nanum Gothic
│   └── 片假名/    Noto Sans JP, Noto Serif JP, M PLUS 1p
│
├── 图包/                        # 获奖 logo 原图（按 奖项/年份 归档，含 sources.csv 来源审计）
│   ├── 中文奖项/  DFA, Golden Pin, GDC / <年份>/*
│   └── 国际奖项/  WOLDA, Indigo / <年份>/*
│
├── 标准化流程/                  # 处理脚本（确定性、可复现）
│   ├── standardize.py           # 核心：图片统一到同一起点（灰度+去背景+统一画布）
│   ├── render_font_samples.py   # 把字体渲染成受控字符样张
│   ├── scrape_award.py          # 通用获奖图抓取器（无头Chrome + 正则抽图）
│   ├── configs/*.json           # 每个奖项一个抓取配置
│   └── SCRAPER_RECIPE.md        # 抓取子任务操作说明
│
└── 标准化输出/                  # 处理后的标准刺激（512×512 灰度 PNG + manifest）
    ├── 字体样张/  <文字系统>/*.png
    └── logo/     <奖项>/<年份>/*.png
```

## 标准化定义（standardize.py）

对任意输入图片，依次执行确定性步骤，剔除与研究命题无关的变量：

| 步骤 | 剔除的"命题无关特征" | 做法 |
|---|---|---|
| 1 色彩模型统一 | 不同编码/透明度 | 一律转 RGBA→RGB，透明区填白 |
| 2 去背景/裁切 | 原图不同的留白量、背景色 | 按角落背景色/alpha 自动裁到内容外接框 |
| 3 去色/灰度 | **颜色**（品牌色是强命题无关干扰） | RGB→单通道亮度 L |
| 4 (可选)二值化 | 材质/灰阶 | 默认关闭；开启则纯黑白轮廓 |
| 5 等比缩放 | **绝对尺寸** | 按最长边缩到 448px，绝不拉伸（保曲直比例） |
| 6 居中统一画布 | 位置、留白比例 | 贴到 512×512 白底正方形，四周留白固定 32px |
| 7 背景归一 | 底色 | 统一纯白 255 底、灰度前景 |
| 8 记录 manifest | — | 每张图记录原始尺寸/缩放比/SHA/参数，可复现可审计 |

全部参数集中在 `standardize.py` 顶部 CONFIG，一处修改全局一致：
`CANVAS=512, CONTENT=448, BG=255, GRAYSCALE=True, BINARIZE=False`。

## 复现命令

```bash
PY="E:/Anaconda/python.exe"
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"

# 自检
"$PY" 标准化流程/standardize.py --self-test

# 字体 → 样张 → 标准化
"$PY" 标准化流程/render_font_samples.py --fonts 字体包 --out 标准化输出/字体样张/_raw
"$PY" 标准化流程/standardize.py --in 标准化输出/字体样张/_raw --out 标准化输出/字体样张 --kind font

# 抓某奖项 → 标准化
"$PY" 标准化流程/scrape_award.py --config 标准化流程/configs/<award>.json --out 图包/<scope> --chrome "$CHROME"
"$PY" 标准化流程/standardize.py --in 图包/<scope>/<award> --out 标准化输出/logo/<award> --kind logo
```

## 重要说明与边界
- **版权**：图包为学术研究小样本，每张图在 `sources.csv` 记录原始 URL、抓取时间、奖项年份、类别、项目/作者。请勿再分发；正式使用前复核各奖项版权与 robots 政策。
- **奖项年份**：部分奖项按"届次"而非自然年（WOLDA 12th–16th≈2020–2024；GDC 为双年展，取 2021/2023/2025 三届覆盖近5年窗口）。年份文件夹按对应举办年份命名。
- **各奖样本纯度（重要，影响研究第 3 条线的可比性）**：
  - **Indigo**：Branding 类孤立封面图，背景干净、最接近"纯字标"，推荐作主分析集。
  - **DFA / Golden Pin / GDC**：项目封面图，多数为品牌识别应用图，部分含 mockup/场景；已"每项目取封面第一张"降噪。
  - **WOLDA**：发布的是"作品展板"（含标题/说明/奖牌），非孤立 logo；标准化会连同版面文字一起处理。若研究需要纯字标，需人工再裁剪或仅使用 Indigo。
- **国际第 3 奖为何缺位**：A' Design、iF、German Design Award、DIA、DNA Paris、MUSE 官网均为 JS 无限滚动或忽略年份/类别参数，无法低成本按"年份+品牌类"分档。经用户确认以 5 个可靠奖项收官。可复现的抓取判定见 `SCRAPER_RECIPE.md`。
- **字体样张**：使用受控字符串（不含品牌名），避免引入语义/命题相关变量；每种文字 3 款字族（拉丁另含 Lato Regular+Bold 两字重共 4 样张）。

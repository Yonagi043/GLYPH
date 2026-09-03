# 抓取子任务通用说明 (SCRAPER_RECIPE)

环境（已验证可用）：
- Python: `E:/Anaconda/python.exe`（含 PIL, numpy, fontTools, pip）
- Chrome 无头: `/c/Program Files/Google/Chrome/Application/chrome.exe`
- 工作根目录: `C:\Users\16249\Desktop\字体审美`
- 通用抓取器: `标准化流程/scrape_award.py`（用法见其文件头）
- 标准化器: `标准化流程/standardize.py`

## 抓取器工作方式
1. 用无头 Chrome 渲染每个"获奖列表/画廊页"→ dump DOM
2. 正则抽取图片 URL（src/data-src/srcset/background）→ 绝对化 → 按 img_regex 过滤 → 去缩略图后缀取原图 → 排除干扰词
3. 每年下载至 `图包/<scope>/<award>/<year>/`，并追加 `sources.csv`（url+抓取时间，供版权与复现审计）

## 你的产出要求
- 目标：该奖项 **最近5年**（2020–2024，按需可含2025）每年 **10–18 张** 获奖 **logo/品牌字标/视觉识别** 样本
- 学术研究用途，小样本即可；务必保留 `sources.csv`
- 优先纯 logo / 品牌字标类别；避免海报、包装照片、人像、banner、icon
- 若该奖项最近5年无 logo/品牌类别或无法抓取 → 明确报告失败原因，不要硬凑

## 写 config 的步骤
1. 先渲染该奖项的 winners 主页，找出"按年份/届次"的列表页或画廊页 URL：
   `"$CHROME" --headless=new --disable-gpu --dump-dom --virtual-time-budget=12000 "<url>" > _probe.html`
2. 找出图片 CDN 的 URL 规律（`grep -oiE 'https?://[^" ]+\.(jpg|jpeg|png|webp)' _probe.html`）
3. 写 `标准化流程/configs/<award>.json`（照 wolda.json 的字段）
4. 运行：`"$PY" 标准化流程/scrape_award.py --config <cfg> --out 图包/<scope> --chrome "$CHROME"`
   注意：Chrome 渲染慢，多页时请后台运行；单页渲染预算 budget_ms 可加大到 18000–22000
5. 核对每年张数与图片内容（抽查 file 类型/尺寸），报告结果

## 已完成
- 国际奖项 / WOLDA：2020–2024 各 ~18 张 ✓

# GLYPH 视觉特征 v1.2.0

**技术报告**  
日期：2026-08-30  
仓库：<https://github.com/Yonagi043/GLYPH>

## 1. 目标

GLYPH v1 为文字系统、书体与字形形式研究建立一套可复现的视觉测量层。
系统在固定条件下测量渲染后的字形形式；不估计审美真值，不替代真人评分，
也不生成综合审美分数。

## 2. 冻结设计

| 项目 | 冻结规范 |
| --- | --- |
| 协议 | `visual_features_v1.2.0` |
| Schema | stimulus `1.1.0`；visual features `1.1.0` |
| 文字系统 | 拉丁文（`Latn`）、汉字（`Hani`）、假名（`Kana`）、谚文/韩文（`Hang`） |
| 画布 | 2048 x 1024 px，sRGB，黑字白底，96 DPI |
| 整形与栅格化 | Unicode NFC + HarfBuzz cluster 校验；Pillow/FreeType BASIC 渲染；`-liga`、`-kern`；不使用 fallback 或静默替换 |
| 锚点 | 单字 ink-bbox 中心 `(1024, 512)`；多单位文本中心 `x=1024`，基线 `y=640` |
| 归一化 profile | `bbox_height_matched`：ink bbox 高度 320 px；`ink_area_matched`：ink 比例 0.050 |
| 二值化与敏感性阈值 | 主二值阈值 128；敏感性阈值 96 和 160 |

规范 manifest 包含 160 个条件单元和 140 个唯一刺激。每个刺激使用稳定的
`stimulus_id` 标识；来源、字体、语言、版式、归一化和溯源字段均保留在
manifest 中。

## 3. 字体资产

矩阵使用七个本地存储、可再分发的 OFL-1.1 字体资产：

- Noto Sans（拉丁文基线）
- Noto Sans CJK SC（汉字基线）
- Noto Sans CJK JP（假名基线）
- Noto Sans KR（韩文基线）
- Noto Serif SC（汉字衬线对照）
- Bpmf Iansui（汉字展示体对照）
- LXGW Marker Gothic（汉字展示体对照）

准确的来源 URL、访问日期、许可证哈希、覆盖状态和 SHA-256 值记录在
[`data/processed/visual_features_v1/asset_inventory.csv`](../data/processed/visual_features_v1/asset_inventory.csv)。

## 4. 处理管线

```text
资产登记与许可证检查
    -> manifest/schema 校验
    -> NFC 与 HarfBuzz cluster 校验
    -> 确定性栅格化
    -> 按 profile 归一化
    -> 灰度与二值视觉特征提取
    -> QC、checksums 与敏感性比较
    -> 独立人工 fixture 审查
```

实现位于 [`src/glyph_features/`](../src/glyph_features/)。运行目录不可变，
不会覆盖既有 run。缺失或失败记录会以明确失败码保留；输入不会被静默替换。

## 5. 特征提取

对于每个通过渲染的刺激，提取器写入两条记录：`raster_binary` 和
`raster_grayscale`。v1 实现提供 17 项可解释测量：

- **密度与比例：** `ink_coverage_ratio`、`whitespace_ratio`、
  `bbox_fill_ratio`、`bbox_aspect_ratio`
- **拓扑与几何：** `connected_component_count`、`closure_count`、
  `symmetry_horizontal`、`symmetry_vertical`
- **笔画动作与视觉中心：** `straight_curve_ratio`、`centroid_x_norm`、
  `centroid_y_norm`
- **序列版式与节奏：** `inter_glyph_spacing_mean_norm`、
  `inter_glyph_spacing_sd_norm`、`rhythm_periodicity`
- **单位一致性：** `unit_area_cv`、`unit_width_cv`、`unit_height_cv`

仅适用于序列的测量在单单位刺激上明确标记为不适用。过短序列使用
`MEASURE_SEQUENCE_TOO_SHORT`；不对缺失值进行插补。

定义和适用性规则见
[`data/processed/visual_features_v1/feature_dictionary_zh.md`](../data/processed/visual_features_v1/feature_dictionary_zh.md)。

## 6. 参考结果

参考运行：
[`render_551362ca0ff22f33`](../data/processed/visual_features_v1/runs/render_551362ca0ff22f33/)

| 指标 | 结果 |
| --- | ---: |
| 唯一刺激 | 140 |
| 条件单元 | 160 |
| 特征记录 | 280 |
| 通过渲染 | 140 / 140 |
| 失败或缺失记录 | 0 |
| 敏感性运行 | 3 |
| 敏感性警告 | 0 |

该运行包含灰度 PNG、二值 mask、`visual_features.csv`、完整刺激记录、
manifest、运行元数据、日志、QC 结果和 SHA-256 checksums。质量报告见
[`quality_report.md`](../data/processed/visual_features_v1/runs/render_551362ca0ff22f33/quality_report.md)。

## 7. 验证与 release gate

当前自动化验证通过：

```text
uv run --locked --extra dev pytest -q
4 passed
```

仓库同时保留归一化可行性审计和三次敏感性运行。公开 release 由两名审查者
对 28 条 fixture 清单进行独立人工审查后才能通过。审查模板和说明见
[`data/processed/visual_features_v1/human_review/`](../data/processed/visual_features_v1/human_review/)。
当前没有伪造任何人工审查记录。

两次审查完成后运行：

```bash
uv run --locked --extra dev python -m glyph_features.cli release \
  --run-id render_551362ca0ff22f33
```

## 8. 复现

```bash
conda activate glyph
uv sync --locked --extra dev

python -m glyph_features.cli validate-config \
  --config configs/visual_features_v1.yaml
python -m glyph_features.cli render \
  --config configs/visual_features_v1.yaml \
  --manifest data/processed/visual_features_v1/manifest.csv
python -m glyph_features.cli measure \
  --run-id render_<manifest-hash>
python -m glyph_features.cli qc \
  --run-id render_<manifest-hash>
```

冻结的渲染与归一化规则记录在
[`rendering_protocol_zh.md`](../data/processed/visual_features_v1/rendering_protocol_zh.md)。

## 9. 范围限制与下一轮交接

本版本仅测量由图像计算得到的字形形式。不宣称跨文化等价、可读性等价、
历史因果关系或审美排序。下一轮研究的稳定交接接口是：`stimulus_id`、
版本化 schema、不可变 run ID、manifest、许可证清单、锁定依赖、fixture
测试和人工审查记录。

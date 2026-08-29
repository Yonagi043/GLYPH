# GLYPH Shared Schema

版本：`1.1.0`（冻结，2026-08-29）

这套 schema 是四条研究线的共同数据契约。它把“刺激是什么”“视觉上测到了什么”“谁如何评价”“公共话语如何描述它”“依据来自哪里”分开记录，再用稳定 ID 联结。

## 文件

| 文件 | 一行代表什么 | 关键联结 |
|---|---|---|
| `stimulus.schema.json` | 一个受控字形/字标刺激及其渲染条件 | 主键 `stimulus_id` |
| `visual_features.schema.json` | 一次特征提取运行的结果 | `stimulus_id` + `extraction_run_id` |
| `human_rating.schema.json` | 一个受试者对一个刺激的一次反应 | `stimulus_id` + `study_id` |
| `cultural_narrative.schema.json` | 一条可人工复核的叙事证据标注 | `source_id`，可选 `stimulus_id` |
| `source.schema.json` | 原始来源、许可和本地存档信息 | 主键 `source_id` |
| `shared.schema.json` | 公共 ID、枚举和复用对象定义 | 被其他 schema 引用 |

## 设计规则

1. `stimulus_id` 一经发布不可复用或改写。条件改变（文字、字体、画布、颜色、版式、归一化策略）就创建新刺激。
2. 原始资产和处理后资产都保留，并用 SHA-256 校验；任何渲染或归一化参数写入 `provenance.generation_parameters`。
3. JSON 是规范格式；`data/templates/*.csv` 只用于批量录入，空值使用空字符串，不使用 `NA`、`null` 或自造枚举。
4. 一对多数据不放进刺激宽表：视觉特征可以有多个表示/运行，评分可以有多个受试者，叙事可以有多个来源。
5. AI 生成或抽取的候选必须在 `collection_method`、`generator` 或备注中明确标记；不能把模拟受试者当成人类评分。
6. 任何文化叙事结论都必须能通过 `source_id` 找回 URL、访问日期和 `evidence_span` 原文片段。

## 核心字段对照

用户要求的共享字段在规范中的位置如下：

| 研究字段 | schema 路径 |
|---|---|
| stimulus_id | `stimulus_id` |
| 文字系统 | `writing_system`, `script_code_iso15924`, `script_name` |
| 书体 | `style_family`, `style_name` |
| 字体 | `font` |
| 字符内容 | `text` |
| 画布 | `canvas` |
| 颜色 | `foreground_rgba`, `canvas.background_rgba`, `canvas.color_space` |
| 字面面积 | `ink_area_target_ratio`；实际值见 `visual_features.features.ink_coverage_ratio` |
| 版式 | `layout` |
| 可读性和熟悉度条件 | `readability` |
| 来源、许可证、生成参数 | `provenance`、`source.schema.json` |
| 视觉特征 | `visual_features.schema.json` |
| 人类评分 | `human_rating.schema.json` |
| 文化叙事证据 | `cultural_narrative.schema.json` |

## 最小联结示意

```text
source_id ──┬── stimulus.provenance
            └── cultural_narrative
stimulus_id ─┬── visual_features (many)
             ├── human_rating (many)
             └── cultural_narrative (optional, many)
```

## CSV 映射与校验

JSON 是规范记录格式；视觉特征 CSV 为可排序的宽表导出。`*_json` 列分别映射到
`feature_numerators`、`feature_denominators`、`feature_units`、
`feature_applicability` 和 `missing_reasons`，其余特征列映射到 `features`。
仓库中的校验命令会逐行展开并用 `jsonschema` 验证，不能只检查列名。

## 版本策略

当前采用语义版本号。增加可选字段不改变主版本；改变必填字段、枚举含义或测量定义时提升主版本。每个数据文件必须写明所使用的 schema 版本，分析脚本不得静默混用版本。

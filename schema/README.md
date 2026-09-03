# GLYPH Shared Schema

基础共享 schema 版本：`1.1.0`（冻结，2026-08-29）。社会叙事采集层另有独立的
`social_observation`/`social_run_manifest` `0.2.0` 版本；历史 `0.1.0` 记录继续原样校验，
Mastodon 记录必须使用 `0.2.0`。该最小扩展不会改写视觉特征、刺激、评分或既有文化叙事契约。

这套 schema 是四条研究线的共同数据契约。它把“刺激是什么”“视觉上测到了什么”“谁如何评价”“公共话语如何描述它”“依据来自哪里”分开记录，再用稳定 ID 联结。

## 文件

| 文件 | 一行代表什么 | 关键联结 |
|---|---|---|
| `stimulus.schema.json` | 一个受控字形/字标刺激及其渲染条件 | 主键 `stimulus_id` |
| `visual_features.schema.json` | 一次特征提取运行的结果 | `stimulus_id` + `extraction_run_id` |
| `human_rating.schema.json` | 一个受试者对一个刺激的一次反应 | `stimulus_id` + `study_id` |
| `cultural_narrative.schema.json` | 一条可人工复核的叙事证据标注 | `source_id`，可选 `stimulus_id` |
| `social_observation.schema.json` | 一条从公开平台/API/人工采集中规范化的内容观察 | `observation_id` + `collection_run_id`，可选 `stimulus_id`/`font_id` |
| `social_run_manifest.schema.json` | 一次有边界的采集运行的查询、时间窗、抽样和治理记录 | `collection_run_id` |
| `source.schema.json` | 原始来源、许可和本地存档信息 | 主键 `source_id` |
| `shared.schema.json` | 公共 ID、枚举和复用对象定义 | 被其他 schema 引用 |

## 设计规则

1. `stimulus_id` 一经发布不可复用或改写。条件改变（文字、字体、画布、颜色、版式、归一化策略）就创建新刺激。
2. 原始资产和处理后资产都保留，并用 SHA-256 校验；任何渲染或归一化参数写入 `provenance.generation_parameters`。
3. JSON 是规范格式；`data/templates/*.csv` 只用于批量录入，空值使用空字符串，不使用 `NA`、`null` 或自造枚举。
4. 一对多数据不放进刺激宽表：视觉特征可以有多个表示/运行，评分可以有多个受试者，叙事可以有多个来源。
5. AI 生成或抽取的候选必须在 `collection_method`、`generator` 或备注中明确标记；不能把模拟受试者当成人类评分。
6. 任何文化叙事结论都必须能通过 `source_id` 找回 URL、访问日期和 `evidence_span` 原文片段。
7. `social_observation.schema.json` 是采集层契约：它保留平台项目 ID、查询、内容可得状态、可见互动数、引用关系、治理状态和规范化哈希；`observation_id` 同时绑定平台、采集运行和平台条目，因此重复运行不会覆盖历史观察。它不等同于全网流量。人工确认后，记录可以投影到 `cultural_narrative.schema.json`。
8. 每次社会叙事采集都应同时保存 `social_run_manifest.schema.json`；观察记录中的 `collection_run_id` 必须能回到该运行的查询、时间窗和抽样规则。
9. `social_run_manifest.sampling.method=realtime_stream` 用于 Jetstream 等有增量游标的实时官方流；游标、包含式重放和幂等策略必须进入本地运行审计，不得把流式样本描述为平台总体。
10. Mastodon 使用 `sampling.method=api_pagination`。选定实例、访问方式、分页上限和逐请求间隔冻结在 query；实例级分页状态、高水位和 sighting 保存在本地审计层。跨实例观察不等于 Mastodon 全网样本，原始账号与 payload 不进入发布导出。

模板中的全零 SHA-256 只是占位符；发布闸门默认拒绝它。只有检查模板结构时才显式使用 `--allow-zero-hash`，真实运行必须写入实际输入和记录哈希。

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
| 社交/公开内容观察 | `social_observation.schema.json` |
| 社交采集运行说明 | `social_run_manifest.schema.json` |

## 最小联结示意

```text
source_id ──┬── stimulus.provenance
            ├── cultural_narrative
            └── social_observation
stimulus_id ─┬── visual_features (many)
             ├── human_rating (many)
             ├── cultural_narrative (optional, many)
             └── social_observation (optional, many)
```

## CSV 映射与校验

JSON 是规范记录格式；视觉特征 CSV 为可排序的宽表导出。`source.schema.json` 的
CSV 投影使用 `local_archive` 列（JSON 对象字符串或空值），不能再使用旧的
`local_archive_json` 列。`*_json` 列分别映射到
`feature_numerators`、`feature_denominators`、`feature_units`、
`feature_applicability` 和 `missing_reasons`，其余特征列映射到 `features`。
仓库中的校验命令会逐行展开并用 `jsonschema` 验证，不能只检查列名。

## 版本策略

当前采用语义版本号。增加可选字段不改变主版本；改变必填字段、枚举含义或测量定义时提升主版本。每个数据文件必须写明所使用的 schema 版本，分析脚本不得静默混用版本。

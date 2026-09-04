# GLYPH Data Layout

数据目录按“规范、模板、原始、处理中间结果、发布结果”分层。当前仓库只提交规范和空模板；受版权、隐私或平台条款限制的资产不应直接提交。

```text
data/
├── templates/       # 可复制的 CSV 表头与一行示例
├── raw/              # 原始来源或受控下载（默认不提交）
│   └── social/       # 平台/API 导出；包含凭据或受限正文时永不提交
├── processed/        # 清洗后的记录与渲染资产
└── releases/         # 经过许可、去标识和质量审查的公开版本
```

CSV 模板对应 `schema/` 中的 JSON Schema。复杂对象字段使用 JSON 字符串存储，例如 `canvas_json`、`ratings_json`；正式分析前应解析并校验，而不是按逗号拆分。

`data/templates/sources.csv` 和规范化器的 `--sources-output` 是
`source.schema.json` 的 CSV 投影：`local_archive` 若非空必须是 JSON 对象，布尔值
使用 `true`/`false`，空单元格表示 `null`。规范 JSON 仍以 schema 为准。

模板中的全零哈希仅用于示例结构检查；对模板运行发布校验时需要显式加
`--allow-zero-hash`，真实数据不能使用该选项。

## 资产系统 fixture 参考交接

`data/fixtures/asset_system/reference_handoff_v1/` 是 TASK-01 的可提交工程参考运行。目录只包含项目生成且以 `CC0-1.0` 提供的 fixture 派生图；五奖项图片和字体不会被复制到该目录，只交接 metadata、完整 SHA-256、QC、人工审核队列和 `blocked_unknown` 权利状态。

参考包的 `handoff_manifest.json` 使用 handoff 2.0，声明 `engineering_ready=true`、`pilot_ready=false`、`research_validated=false`，并以逐文件及聚合 SHA-256 固化 dirty producer source snapshot。它可用于下游契约和算法测试，不能移入 `data/releases/`，也不能当作正式研究刺激。操作协议见 `docs/asset_curation_protocol_zh.md`。

社会叙事线的登记顺序是：先填写 `data/templates/social_queries.csv` 和
`data/templates/social_run_manifest.json`，再保存原始导出，最后生成
`social_observations.jsonl`。`social_codebook.csv` 固定对象、评价词和品类的写法，
`social_object_map.csv` 记录别名到规范标签的映射；这些表只接受增量版本，不在脚本里
临时改词。

## 社会叙事监测

社会平台的规范记录使用 JSONL，每行符合
[`schema/social_observation.schema.json`](../schema/social_observation.schema.json)。
建议把一次采集放在
`data/raw/social/<platform>/<collection_run_id>/`，再用
`tools/normalize_social_records.py` 生成
`data/processed/social_narrative_v0/observations.jsonl` 和失败记录。矩阵及
`Lift` 汇总放在该目录下的 `matrices/<run_label>/`。原始响应、用户名、访问令牌和
不具备再分发许可的正文不进入公开 release；只发布经人工审查的元数据或派生统计。

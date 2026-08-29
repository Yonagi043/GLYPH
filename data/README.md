# GLYPH Data Layout

数据目录按“规范、模板、原始、处理中间结果、发布结果”分层。当前仓库只提交规范和空模板；受版权、隐私或平台条款限制的资产不应直接提交。

```text
data/
├── templates/       # 可复制的 CSV 表头与一行示例
├── raw/              # 原始来源或受控下载（默认不提交）
├── processed/        # 清洗后的记录与渲染资产
└── releases/         # 经过许可、去标识和质量审查的公开版本
```

CSV 模板对应 `schema/` 中的 JSON Schema。复杂对象字段使用 JSON 字符串存储，例如 `canvas_json`、`ratings_json`；正式分析前应解析并校验，而不是按逗号拆分。

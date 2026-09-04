# TASK-03 schema-valid templates

这些文件由以下命令从冻结协议和许可 TASK-01 fixture 生成：

```bash
uv run --frozen glyph-experiment build-reference --seed task03-template-v1 --output-dir data/templates/experiment_system_v1
```

所有记录都是 `data_origin=synthetic` 的完整填写示例，不是空白真人表单。`reference_manifest.json` 记录每个文件对应的 schema、记录数和 SHA-256。复制或改写 wording、item、scale 或版本时必须生成新 questionnaire/protocol 版本；不得直接把模板 participant ID 或 synthetic 响应投入正式分析。
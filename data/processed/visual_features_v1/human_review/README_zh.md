# Fixture 人工审查

发布前必须由两名具备字体或视觉经验的审查者独立检查 fixture。审查者不得共用结论；每名审查者都要对每个 `fixture_id` 填写一行，三个 pass 字段只能填 `true` 或 `false`。

本目录中的 `fixture_stimuli.csv` 是需要检查的 28 条 fixture 刺激清单；`fixture_review_records.csv` 只提供空模板，不包含伪造的 reviewer 或审查结果。审查内容包括：刺激网格是否完整、字符边界/顺序是否正确、书体归类是否符合登记。任何不一致或争议样本都应填 `false` 并在 `notes` 说明，随后进入 `needs_review`，不能通过代码强行裁决。

填写完成后运行：

```bash
python -m glyph_features.cli release --run-id <RUN_ID>
```

release 命令会验证至少两名不同审查者，并要求每名审查者对全部 fixture 给出独立通过。

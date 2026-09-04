# TASK-03 synthetic reference

该目录只消费 TASK-01 strict handoff `2.0.0` 中的 open fixture，不含奖项图、字体包、真人响应或 Persona 输出。

- `dry_run_1000_seed_a.json`：1000 assignments / 8000 unique presentations / 0 lost / 0 duplicate / exposure spread 0 / position spread 1。
- `dry_run_1000_seed_b.json`：不同 seed，仍满足同一约束且 summary hash 不同。
- `blocks/`：4 个 synthetic participant 的可读 assignment/catalog/audit 小样。
- `records/`：九类 schema-valid reference artifact；rating 为 7 条逐题 JSONL。
- `power_scenarios.json`：假设 effect/ICC 的 planning approximation，不是批准样本量。

任何 `formal_analysis` 或 `release` 导出都必须机械拒绝这些记录。
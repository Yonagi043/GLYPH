# TASK-02 visual measurement fixtures

- `cross_script_component_cases.json`：CC0 合成矩形组件定义，覆盖拉丁变音符/serif、汉字分离点画、韩文 jamo、假名浊点、书法断续边缘和复合 logo。
- `reference_run_v1/`：visual measurements v2.0.0 / handoff 1.0 的历史参考运行。
- `reference_run_v2/`：从 TASK-01 accepted CC0 fixture 生成的当前 v2.0.1 不可覆盖参考运行，包含完整算法配置与跨工件来源链。

参考运行只用于工程回归。`quality_report.json` 中的 `pilot_ready` 与 `research_validated` 均为 `false`，不得用它支持审美、跨文化或书法专家结论。

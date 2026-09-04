# TASK-04 汉字书体知识与专家在环子系统报告

版本：`1.1.0`
起始 checkpoint：`af3820836a6ffa92c63016b0e308f624f9b42db0`
implementation commit：`dc269966775a4730ebef1865c4c932eb99794b2d`

## 完成范围

- 八类目标书体本体：8 条；字符映射：10 条。
- 字形实例：1 条；知识断言：2 条。
- synthetic review：2 条；real expert review：0 条。
- fixture-only 候选：2 条；TASK-01/02/03/WP2 adapter：14 条。

## Readiness 与推断边界

- `engineering_ready=true`：schema、CLI、证据外键、离线审核、签名、候选与 handoff 可机械验证。
- `pilot_ready=false`：真实专家审核、正式权利和 TASK-01 `stimulus_id` 均未通过。
- `research_validated=false`：没有真人专家、参与者数据或研究结论。
- `instance_level_only`：2 条；类别级候选：0 条。
- 类别推断门槛为每类至少 3 个独立合格实例，当前没有任何类别达标。

## 门禁

- `GATE-EXPERT=blocked`：未联系专家，synthetic review 不构成专家结论。
- `GATE-RIGHTS=blocked`：仅 CC0 抽象 fixture 可用于工程链；没有正式历史字形或字体获批。
- `GATE-TERMS=blocked`：未下载、登录、付费、接受条款或发起受限请求。

## integration_requests

- 共享热点 `pyproject.toml`：仅新增 `glyph-han` console script；依赖和锁文件未改。
- TASK-01：消费候选冻结请求并独占正式 `stimulus_id` 分配。
- TASK-02：adapter 仅依据 checkpoint 书面契约；C1-C5 保持 `within_script_only` / `protocol_dependent`。
- TASK-03：等待正式 `stimulus_id`、真实专家审核和权利通过；盲评与 contextual 条件必须分离。
- WP2：当前 registry 仅匹配 `seal` 与 `sans`；其余书体需扩展 object map，原词形不得覆盖规范 `style_id`。

## Handoff

- manifest：`data/fixtures/han_style_system/reference_handoff_v1/handoff_manifest.json`
- checksums：`data/fixtures/han_style_system/reference_handoff_v1/checksums.sha256`
- 所有 producer 与 implementation-bound 工件必须与上述 implementation commit 的 Git blob 完全一致。

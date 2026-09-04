# TASK-02 理论构念、可解释视觉测量与 CV 子系统报告

版本：`visual_measurements_v2.0.1`
生成时间：2026-09-04T11:00:00Z
可信整改起点：`6c1d998ac55f360c5c0edee71255bf76be694532`
整改实现提交：`e3fc34883a0a2ec6ff30fbd56dd950d7c7fd2306`
参考运行提交：`1c748b96f5a2a1c2b0376521458a1373da9f739a`
上游 TASK-01 accepted checkpoint：`af3820836a6ffa92c63016b0e308f624f9b42db0`

## 1. 实际完成范围

本任务只完成 TASK-02：把 visual features v1 与李婕 5+5 理论/CV 原型协调为“表示 -> 原始测量 -> 理论构念映射 -> 真人校准模型”四层架构。前三层已形成版本化、可执行、可验证的工程契约；第四层只定义边界，未在没有 TASK-03 真人评分时估计方向、非线性、权重或审美分。

已实现：

- 严格消费 TASK-01 handoff 2.0、accepted checkpoint、开放许可、QC 和 A/B/C 资产哈希；
- 将六个公开算法配置字段接入实际运行时分派，完整配置与成熟库实现/版本写入 run manifest；
- 冻结 TASK-01 handoff、asset candidates、stimuli、A/B/C 与 `B_shape_mask`，并由 validator 从实际文件重建逐 measurement 来源链；
- 8 个 visual v1 组织维度与 10 个设计/书法构念的多对多 registry；
- 20 个 active 原始/诊断特征及 8 个 visual v1-only deprecated 兼容定义；
- A_layout、B_shape、C_ink 表示边界，长表提取、显式缺失、部分失败、no-overwrite；
- 确定性重复计算、阈值敏感性、表示比较、schema、配置和输出 checksum QC；
- visual v1.1 宽表与长表的确定性语义往返；
- 李婕旧 CV MVP 的根环境兼容 shim，不再发布或迁移 `total_score`；
- TASK-02 handoff 1.0、producer commit provenance 和 blocked `GATE-EXPERT` 包。

未处理真实奖项资产，未执行真人实验、专家判定、模型训练、联合分析或公开 release。

## 2. 关键文件与公开接口

- `configs/visual_measurements_v2.yaml`：feature registry `2.0.1`，8 维、10 构念、28 个定义。
- `schema/visual_feature_definition.schema.json`：registry 契约 `1.0.0`。
- `schema/visual_measurement.schema.json`：canonical 长表记录契约 `1.0.0`。
- `schema/visual_measurement_handoff.schema.json`：TASK-02 handoff 契约 `1.1.0`，强制 TASK-01 三类来源快照。
- `schema/visual_expert_gate.schema.json`：专家审核包契约 `1.0.0`。
- `src/glyph_features/vision_system/`：definitions、extract、QC、compat、legacy shim、handoff 与 CLI。
- `docs/visual_measurement_protocol_zh.md`：四层协议、表示边界、QC 与复现命令。
- `docs/visual_measurement_migration_zh.md`：visual v1 和李婕 MVP 迁移/拒绝边界。
- `glyph-vision`：`validate-definitions`、`extract`、`qc`、`compare-representations`、`export`、`export-handoff`、`validate-handoff`。
- `glyph-vision-legacy`：旧批处理兼容入口，只输出 active 原始/诊断测量。

共享热点只有根 `pyproject.toml` 的两个命令入口。根 README、CONTRIBUTING 和 `docs/agent_tasks/` 未修改。

## 3. Schema、配置与迁移

Canonical v2 是长表。每条记录绑定 `stimulus_id`、`asset_id`、表示、归一化、feature definition 版本、值/分子/分母/单位、适用性、缺失码、输入/配置/环境/上游契约哈希。`valid` 必须有有限数值且无缺失码；`missing` 必须为 `null` 且有机器可读原因。JSON 禁止 `NaN` 和 `Infinity`。long schema 仍为 `1.0.0`。

Registry/producer 从 `2.0.0` 升至 `2.0.1`。默认算法数值不变；`binary_threshold`、组件/孔洞 connectivity、骨架实现、对称对齐和 tonal bins 现在均为真实执行参数。未知 connectivity、骨架或对齐枚举以稳定 `ALGORITHM_CONFIG_UNSUPPORTED` 失败。Handoff 从 `1.0.0` 升至不向后兼容的 `1.1.0`；旧 v1 bundle 作为历史证据保留，不能冒充新 strict contract。

visual v1.1 历史 schema 和 140 个唯一刺激参考运行未改写。冻结的 280 行、17 特征宽表可迁移为 4,760 条长记录并恢复原表语义；空值不转成 0，未知列不猜测。普通 A/B/C v2 记录不能反向伪造 v1 的 glyph-box 与序列上下文。

李婕理论、公式、字段字典、文献和检索日志保留。旧程序成为历史原型；兼容 shim 修复同 stem 覆盖、部分失败零退出、异常权重、绝对路径和未检查写入。未知/负数/全零/NaN/Infinity 权重均拒绝，且权重不参与原始量计算。

`total_score`、未校准十项规则分、未绑定 `analysis_run_id` 的手工权重和把 qi 当直接观测的字段，均列入联合分析机械排除清单。

## 4. 输入、输出、记录数与哈希

当前参考运行 `reference_run_v2` 只使用 TASK-01 项目生成的 CC0 fixture：1 个 stimulus、3 个 A/B/C 测量表示、1 个 `B_shape_mask` 支撑表示、20 个 active feature，共 60 条测量。

| 指标 | 数量 |
|---|---:|
| Registry definitions | 28 |
| Active v2 features | 20 |
| Deprecated v1-only definitions | 8 |
| 有效测量 | 19 |
| 显式缺失 | 41 |
| 提取失败 | 0 |
| 阈值敏感性 warning | 14 |
| 重复计算差异 | 0 |

关键快照：

| 产物 | 记录数 | SHA-256 |
|---|---:|---|
| TASK-01 handoff | 1 | `acc193134495401b9a026aab0e7a866d7f15202b9b865db0d73d6f689bd1bdab` |
| TASK-01 candidates | 5 | `e132abc1bc2658315ac89a7d9c7772ac0bf3e510500eb8a8adda2d9c695c01ad` |
| TASK-01 stimuli | 1 | `a7c49d069effc90ba1d696e38681ff91326edfcfe874c0bf270dac4e368c6f4a` |
| v2.0.1 registry config | 1 | `af093ac82a3042b63d80e96aaf080c9a8e60af08079b063dc6e43f6aa8edb4eb` |
| resolved algorithm config | 1 | `1db1e859767d04b11afa94b156f8f3c5cf97cd93912325b20c05a46b4b663188` |
| registry snapshot | 1 | `c5341ea8b55d96d870cfa5aa19de1f82f5231706226f7c82707befeda1bf0dbd` |
| `run_manifest.json` | 1 | `cbc800ddade4e21843711e78f654d6ab0e88188def4c672a207a4a30c22815d0` |
| `measurements.jsonl` | 60 | `1e50e12da8d3c41b9391e779d50d7e0a4f1766d884617291a50dcc7b8368483a` |
| `quality_report.json` | 1 | `2fcfac83c1eae10df52e2d74a3f885c8d6c5bcc2e76b7d78f347d4737da72b3b` |
| `sensitivity_report.json` | 1 | `4e98b4d87cfba653b8f52e9189dd9f923ab77eb3bfa366c109f082e9abb60e19` |
| reference checksums | 8 | `c499e4d085358016da96ba5a65427b6f0ebf18cd98787782367b518541cfd761` |
| `GATE-EXPERT.json` | 1 | `9b7a142d92456d6736b0b40dd3ca25b07bb6635d2f64f5b8cd769ac5bb223cd4` |
| `handoff_manifest.json` | 1 | `d039330f7aceb12d3a3620c99bdb2749dfaf51421b97df606ee0c87a10446ba8` |
| handoff checksums | 2 | `b9714a8735ebaee06d917d714f72e8cde16afc3ff71afd5b6584598cd35a21dd` |

Producer provenance 固化 15 个入口、锁、配置、schema 与源码文件；聚合 SHA-256 为 `da50876efbfd620f217c0c9f45d8a960dab8c383693ba93e5ca01290f8dd0202`，并验证全部内容与整改实现提交 `e3fc348...` 一致。

## 5. 测试与验收

- `uv run --frozen pytest tests/test_vision_system.py tests/test_vision_legacy_mvp.py -q`：`33 passed`。
- `uv run --frozen pytest -q`：`268 passed`。
- `uv lock --check`：48 个包解析一致。
- 两个安装入口 `--help` 均实际加载；registry 输出 `feature_count=20`、`valid=true`。
- reference `extract`：60 条测量、0 failure；`qc`：0 error、`engineering_ready=true`。
- `glyph-vision validate-handoff data/fixtures/visual_measurements/reference_handoff_v2/handoff_manifest.json`：`failure_count=0`、`valid=true`。
- `git diff --check`：通过；reference 绝对路径/非有限值/评分字段扫描未命中。
- 编辑器静态诊断：TASK-02 Python 与测试无错误。

新增解析 fixture 分别验证 threshold、4/8 组件 connectivity、4/8 孔洞 connectivity、骨架端点、canvas symmetry 与 4/32 tonal bins 的实际结果；四类未知算法枚举验证稳定拒绝码。重哈希攻击同时修改 TASK-01 snapshot、run `asset_id` 与 measurement `input_sha256`，并重算普通 run/handoff checksums 与 artifact SHA；strict validator 仍定位 accepted checkpoint、`run_manifest.input_representations[0].asset_id`、`measurements[*].source_contract_sha256` 和 `measurements[0].input_sha256`，CLI 返回 1。

其余专项继续覆盖解析矩形、A 平移、B/C 亮度变形关系、六类跨文字小组件、空/全白/全黑、A/B/C 适用性、路径逃逸、部分失败、no-overwrite、v1 往返/未知列、旧 MVP 权重/同名/写入失败，以及 handoff producer provenance。

## 6. 产品行为与界面验收

本任务没有新增图形界面。CLI 是任务书规定的最低产品面：公开路径均为相对 POSIX 路径；记录级部分失败保留成功结果并返回 1；操作/契约失败返回 2；覆盖冲突返回 3。Canonical export 只允许长表，拒绝把普通 v2 记录伪投影为 v1 宽表。

## 7. 研究有效性边界

- `engineering_ready=true`：registry、schema、提取、QC、迁移、fixture、checksums 和 handoff 可执行。
- `pilot_ready=false`：只有一个工程 fixture，且 14 条阈值敏感性 warning 待审。
- `research_validated=false`：没有专家表面效度结论、TASK-03 真人评分、构念关联、跨文化差异估计或留出预测验证。

Feature 与构念的映射是有来源和证据等级的代理关系，不是已验证效度。对称、居中、均匀等不预设“越大越美”；`C5_qi_movement_proxy` 只映射方向、连续、粗细和连通等低层视觉量。

## 8. 未完成、降级与外部阻塞

- `GATE-EXPERT` 未通过：需至少两名独立领域审核者检查 fixture 表面效度、A/B/C 边界、跨文字失效和构念措辞。
- 14 条阈值敏感性 warning 被保留为 `needs_review`，未调参掩盖。
- 未实现或运行真人校准层；权重、方向和非线性仍未知。
- 没有正式 TASK-01 刺激 release；当前链仅为 `fixture_only`。
- 未把连通域数量冒充字符/cluster 边界，序列类 v1 量只保留为历史定义。
- 没有公开发布、专家结论、真人数据或 TASK-05 联合模型。

## 9. Handoff 与下游入口

规范交接清单：`data/fixtures/visual_measurements/reference_handoff_v2/handoff_manifest.json`。`reference_handoff_v1` 仅保留为 handoff 1.0 历史工件。

- TASK-03：读取冻结 registry 供问卷分层/平衡和预注册引用；不得向参与者泄露代理值，当前仅 `fixture_only`。
- TASK-04：读取 within-script 适用性及低层 stroke/ink API；不得替专家通过书法构念，当前 `metadata_only`。
- TASK-05：可用长表做契约和产品 dry-run；必须执行 `joint_analysis_exclusions`，当前 `fixture_only`。

Handoff 的 `git_commit` 固定为整改实现提交 `e3fc348...`，不是参考运行或后续 handoff 提交。Validator 会复验 producer commit、当前 producer 哈希、TASK-01 accepted checkpoint、三类 upstream snapshot、逐表示 QC/rights/transform、逐 measurement 来源、artifact schema/记录数/SHA-256、reference checksums、绝对路径和禁止评分字段。

## 10. 等待人工批准的门禁

`GATE-EXPERT` 包位于 `data/fixtures/visual_measurements/reference_handoff_v2/GATE-EXPERT.json`。最低要求为两名独立审核者：至少一名具字体/视觉设计/字形分析经验，至少一名具中国书法或跨文字系统经验。审核前禁止声称表面/构念效度、发布书法专业结论或把 `research_validated` 解锁。

TASK-03 的真人校准还受全局伦理与参与者门禁约束，本任务没有代替用户批准、招募或采集数据。

## 11. TASK-02 完成定义逐条核对

| 条目 | 结果 | 证据 |
|---|---|---|
| 八维与 5+5 版本化多对多映射 | 满足 | registry + schema |
| 每个发布特征定义/公式/单位/适用性/缺失/哈希完整 | 满足 | 20 active definitions |
| visual v1 参考运行与 schema 保持可读 | 满足 | 280 行往返测试 |
| 旧 MVP 五类工程缺陷有回归 | 满足 | 8 项 legacy tests |
| TASK-01 fixture -> long/QC/checksum/handoff | 满足（fixture only） | reference run + handoff |
| A/B/C 用途边界被测试强制 | 满足 | analytic + metamorphic tests |
| 四文字系统及书法/复合图小组件不静默删除 | 满足（synthetic） | 6 类 CC0 fixture |
| Canonical 无综合审美分，qi 只作代理 | 满足 | schema/registry/export tests |
| 根锁定环境与全仓测试通过 | 满足 | 259 passed + lock check |
| 稳定性与三类效度分开报告 | 满足；效度仍 blocked | quality report + GATE-EXPERT |

## 12. 停止声明

TASK-02 在工程就绪、fixture-only、专家和真人效度未就绪的真实状态下停止，等待独立验收与 `GATE-EXPERT` 人工决定。不会自动启动 TASK-03、TASK-04、TASK-05，不会替专家或真实参与者给出结论，也不会发布未经真人校准的审美分。
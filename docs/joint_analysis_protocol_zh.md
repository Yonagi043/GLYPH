# GLYPH 四线联合分析协议

版本：`1.0.0`

## 1. 证据与所有权

联合层只消费 TASK-01 至 TASK-04 的验证 handoff 和 social v17 validated export。目录/zip handoff 先在隔离 staging 中完成路径、限额、可信 manifest、payload hash、workspace binding 和原生 validator 检查，再用单个事务登记。Social export 的版本化 package manifest 在全部 payload 完成后生成，覆盖 manifest、governance、quality、observations、queries、sources、narratives 和矩阵；adapter 重算哈希、记录数、稳定 ID 和 narrative 投影。领域模块继续拥有业务数据与写操作，catalog 只保存 pointer、版本、SHA-256、稳定 ID 关系和联合运行状态。

Synthetic fixture 用于工程恢复测试，不是参与者证据、专家判断、版权批准或研究结论。三个就绪度独立报告：

| 维度 | 当前值 | 证据边界 |
|---|---|---|
| `engineering_ready` | `true` | 合同、fixture、E2E、备份和浏览器验收通过 |
| `pilot_ready` | `false` | 伦理、权利、翻译、参与者、专家与真实运行门禁未通过 |
| `research_validated` | `false` | 无真人评分、真实专家审核或可发布正式叙事证据 |

## 2. 稳定 ID 与分析单位

规范连接只使用 `source_id`、`asset_id`、`stimulus_id`、`style_id`、`participant_id`、`rating_id`、`feature_record_id`、`evidence_id`、`collection_run_id` 和 `analysis_run_id`。文件 stem、显示名称、URL、行号或字体自由文本不参与联结。

主要分析单位固定为：

```text
participant_x_stimulus_x_item
```

每个 join step 记录输入行数、唯一键、未匹配、倍数和 inflation factor。右表在声明键上重复时以 `UNEXPECTED_MANY_TO_MANY` 失败。作品、source stimulus 和 social source/thread cluster 保留，不把同一 source stimulus 的 16 个实验条件伪装成 16 个视觉独立样本。

## 3. 不可变计划和快照

冻结计划为 `configs/joint_analysis_plan_v1.json`。每个 `analysis_run_id` 绑定：

- plan revision 与 SHA-256；
- 四份 handoff、所有输入 artifact、schema/registry/ontology 版本和哈希；
- 纳入、排除、缺失和表示规则；
- Git commit、Python/依赖、平台和随机种子；
- Git commit 必须是实际 commit object、等于 clean HEAD；所有选定输入字节必须与该 commit 的 blob 一致，上游 producer commit 必须可追溯；
- synthetic/real 来源和冻结时的人工 gate 状态。

Snapshot v1.1 还记录输入分类、repository scope、Git object type 和 clean 状态；synthetic/fixture 输入不能以 `data_origin=real` 冻结。同一输入按 canonical JSON 得到同一 run ID；结果完成后不可覆盖。已存在的 v1.0 snapshot 只有在显式提供其祖先 commit、ID/hash 与请求参数完全一致时原样重取，不会被迁移或重写。计划同版本内容改变时返回 `ANALYSIS_PLAN_IMMUTABLE_CONFLICT`。真实结果出现后的修改必须新建 amendment/version。

## 4. 模型方法决定

Likert 量表走 ordinal route；continuous 量表走 continuous route；混用时以 `RATING_SCALE_ROUTE_AMBIGUOUS` 失败。工程 fixture 使用 Statsmodels `OrderedModel` 的 logit link 验证注入方向，依赖锁定为 Statsmodels 0.14.5、Pandas 2.3.3、NumPy 2.0.2 和 SciPy 1.14.1。

Statsmodels 与 Pandas 为 BSD 系许可证，NumPy/SciPy 为 BSD 系许可证。当前使用不需要网络、模型权重或遥测。完整依赖哈希在 `uv.lock`；正式升级需重新验证 OrderedModel 公共 API、参数恢复、收敛和锁文件。

Fixture approximation 不冒充预注册研究模型：真实研究仍要求参与者与刺激的交叉层级 ordinal 模型。模型、join 或持久化失败必须形成 failed run、稳定错误码、失败阶段和 audit event，不能静默降级后沿用 confirmatory 标签，也不能永久停在 `snapshot_frozen`。

## 5. 工作包

### WP1：跨文化感知

Synthetic generator 产生 24 个参与者、16 个实验刺激、共 384 个 `participant × stimulus × item` 单位。注入 native-script match 的正向 ordinal 关联；工程验收要求估计和 95% 区间方向为正、概率行和为 1、优化收敛。

双重分组 holdout 同时排除测试参与者和测试刺激。真实研究仍需预注册的随机效应、缺失机制、样本量和多重比较门禁。

### WP2：文化叙事

Social fixture 在全新显式 v17 临时库中经公共 `SocialNarrativeService` 创建 confirmatory scope、完成 run、include 筛选、双编码、human-verified 投影、质量评估和 canonical export。联合层只登记 `social-export://` pointer、哈希和 `context_evidence_for_object` 关系。

当前没有实验随机呈现的叙事材料、参与者熟悉度操作化或满足时间/样本框架的地区聚合变量。因此：

```text
participant_exposure_attached = false
analysis_boundary = context_only_not_participant_exposure
```

WP2 可生成假设和描述语境，不能进入个体评分模型或支持“传播导致偏好”的因果结论。

### WP3：视觉形式增量解释

Canonical features 只使用冻结的 feature code、representation 和 normalization profile；deprecated 综合分禁止进入模型，缩放只在 training fold 拟合。

当前 16 个实验 stimulus 全部映射到一个 TASK-01 source stimulus，因此视觉独立变化不足：

```text
status = blocked
visual_increment_eligible = false
```

不得报告 M0 到 M_visual 的增量解释。

### WP4：汉字书体实例与类别

书体概念、作品/字体实例和字符层级分别建模。当前没有任一类别达到 3 个独立合格 exemplar，且 GATE-EXPERT 未通过：

```text
status = instance_level_only
category_effect_allowed = false
```

Synthetic review 只验证工作流，不能视为专家真值。

## 6. 最低诊断

每次运行输出：收敛与优化器信息、概率合法性、效应和 95% 区间、设计矩阵尺度、共线性、按参与者/刺激的 double-group holdout、纳入排除流量、缺失、cluster 数、表示/profile sensitivity 和工作包资格。

Fixture 当前明确限制：

- 评分和叙事均为 `SYNTHETIC / DEMO`；
- OrderedModel fixture fit 没有交叉随机效应；
- WP3 无足够 source-stimulus variation；
- WP4 无独立真实实例和专家批准；
- WP2 不是参与者暴露。

## 7. 发布门禁

Formal release 逐项检查 handoff/schema/hash、权利、视觉/刺激/专家 QC、伦理/同意/隐私、social validated export、计划、诊断、去标识、人工 gate、no-overwrite、manifest 和 checksums。

只要 synthetic、`pilot_ready=false`、`research_validated=false`、模型层级不足、WP3/WP4 阻断或任何人工 gate 未决，候选状态为 `blocked`。UI 只能运行检查，不能改为 released。

Demo export 可以生成，但始终：

- 使用独立 `_demo` 目录；
- 所有可读文件和图标记 `SYNTHETIC / DEMO`；
- 不含绝对路径、PII、secret、平台 raw payload 或受限原文；
- 生成 package checksums，并禁止覆盖已有目录/zip。

## 8. 复现命令

```bash
uv run --frozen pytest -q tests/test_workbench.py
uv run --frozen glyph-workbench run-system-fixture \
  --catalog-database "${TMPDIR:-/tmp}/glyph-task05/catalog.sqlite3" \
  --social-database "${TMPDIR:-/tmp}/glyph-task05/social.sqlite3" \
  --export-root "${TMPDIR:-/tmp}/glyph-task05/exports" \
  --backup-root "${TMPDIR:-/tmp}/glyph-task05/backups"
```

真实数据入口是条件阶段：只有用户明确批准，且相应权利、伦理、参与者、专家、条款和 release gate 有范围化人类决定时，才登记真实 export；登记前展示分类、数量、哈希、许可/伦理范围和预期分析，不自动运行 confirmatory 模型。
# TASK-05：四线联合分析、统一工作台与系统总装

版本：`0.1.0-draft`
日期：2026-09-04
建议执行顺序：最后一项；必须消费 TASK-01 至 TASK-04 的合格交接包
系统角色：把模块组装为可运行的 GLYPH 成品，并守住跨线解释和发布边界

## 1. 给执行 Agent 的任务指令

你负责 GLYPH 的最终总装。任务不是做一个展示首页，也不是把四条研究线的数据做一次数据库 join，而是交付一个本机可启动、统一导航、模块可独立维护、跨线可审计分析、失败可下钻、结果可导出、发布有机械门禁的中文研究工作台。

你必须把“工程完成、pilot 就绪、真实研究验证”分开显示。没有真人评分、专家审核或真实叙事证据时，系统仍可用许可 fixture 完成工程验收，但不得显示为研究结论已经成立。

必须先阅读：

- `docs/agent_tasks/00_system_blueprint_zh.md`
- `docs/agent_tasks/01_asset_stimulus_system_task_zh.md`
- `docs/agent_tasks/02_visual_measurement_system_task_zh.md`
- `docs/agent_tasks/03_cross_cultural_experiment_task_zh.md`
- `docs/agent_tasks/04_han_style_knowledge_task_zh.md`
- `status/four_research_lines_zh.md`
- `schema/README.md` 和全部当前 schema
- `README.md`
- `src/glyph_features/cli.py`
- `src/glyph_features/social_system/` 的 CLI、Web、service、storage、exports 和测试
- `docs/social_narrative_local_ops_zh.md`
- 各任务实际生成的 `handoff_manifest.json`、版本说明和质量报告

如果任一上游任务尚未交付，不要伪造输出。可以先用该任务定义的规范 fixture 建立 adapter，但最终验收必须明确哪些模块是 fixture-only。

## 2. 最终产品定义

最终命令建议为：

```bash
uv run glyph-workbench serve \
  --catalog-database "${TMPDIR:-/tmp}/glyph-workbench.sqlite3" \
  --social-database "${TMPDIR:-/tmp}/glyph-social-v17.sqlite3"
```

默认绑定 `127.0.0.1`，提供一个中文工作台入口。它至少支持：

1. 查看四线模块、协议、数据和人工门禁状态；
2. 导入并验证各任务的交接包；
3. 从来源下钻到资产、刺激、特征、评分、叙事证据和分析；
4. 运行许可 fixture 的端到端流程；
5. 选择已冻结分析计划，创建不可变分析快照并运行；
6. 查看模型诊断、不确定性、缺失和研究边界；
7. 生成审计包、去标识导出和发布候选；
8. 在任何门禁未通过时明确阻断发布；
9. 备份、恢复、健康检查和运行日志；
10. 保留各领域模块的独立 CLI 和测试入口。

不要把静态报告导航、CLI 菜单或 fixture 截图称为最终工作台。

## 3. 组合架构，不建巨型单体

### 3.1 模块所有权

每个模块继续拥有自己的领域状态和写操作：

- 资产模块拥有来源、候选资产、权利和刺激策展；
- 视觉模块拥有特征定义、提取运行和视觉 QC；
- 实验模块拥有 study、问卷、分配、响应和实验质量；
- 社会叙事模块拥有 scope、query、采集、审核、叙事分析和其 SQLite；
- 汉字书体模块拥有本体、知识断言、字形和专家审核；
- 工作台拥有交接包登记、模块状态、人工门禁决定记录、分析快照、联合分析运行和发布候选；门禁决定权属于总蓝图指定的人类批准者，不属于工作台或 Agent。

工作台不得直接修改模块私有数据库表。写操作通过明确 service/router/CLI API；读操作通过版本化导出、只读 service 或快照。不得让中央目录成为第二份事实源。

### 3.2 中央目录只存指针和审计

建议中央 catalog SQLite 只包含：

- `modules`：模块版本、能力、健康和公开入口；
- `handoff_imports`：交接包路径、哈希、生产者 commit 和验证状态；
- `artifacts`：规范对象类型、路径/URI、哈希、schema、权利/隐私层级；
- `entity_links`：跨模块稳定 ID 关系及来源；
- `gate_decisions`：人工门禁、决定者引用、时间、范围和证据包；
- `analysis_plans`：冻结 estimand、公式、主要结果和版本；
- `analysis_runs`：输入快照、环境、种子、状态、诊断和输出；
- `release_candidates`：发布内容、阻断项、审计和最终决定；
- `audit_events`：追加式系统事件。

不复制第三方原图、平台 raw payload、参与者 PII 或完整模块业务表。

### 3.3 模块描述契约

每个模块应提供机器可读 descriptor：

```json
{
  "module_id": "vision",
  "module_version": "...",
  "contract_versions": {},
  "capabilities": [],
  "health": "ready|degraded|blocked|absent",
  "read_endpoints": [],
  "command_endpoints": [],
  "handoff_schema_version": "1.0.0",
  "data_classifications": [],
  "human_gates": []
}
```

工作台启动时验证兼容矩阵；不兼容模块显示阻断，不通过猜字段继续运行。

## 4. 保护现有社会叙事系统

社会叙事模块已有 FastAPI、调度器、SQLite v17、运行审计、人工审核、导出和备份。总装必须：

1. 保留 `glyph-social` 独立 CLI 和现有测试；
2. 通过 adapter、共享 service 或安全挂载路由接入，不复制业务逻辑；
3. 避免启动两个调度器或重复恢复同一数据库；
4. 保持生产主库与显式测试库隔离；不得因工作台启动自动迁移现有生产数据库；
5. 继续从环境读取平台凭据，工作台不得显示、存储或记录 secret；
6. 保持 Reddit/TikTok/X 的真实请求和费用门禁；
7. 保持只有 `human_verified` 进入本机主分析，正式 release 继续检查双编码、query 和 registry 门禁；
8. 复用其 validated export 作为联合分析输入，不直接从内部表拼凑“方便版”数据；
9. 若需要新增只读状态 API，附契约测试并保持旧客户端可用。

总装前必须用临时数据库验证；生产库迁移需要用户单独批准。

## 5. 跨线联结规则

### 5.1 稳定 ID 是唯一主连接

连接优先级：

```text
source_id
asset_id
stimulus_id
style_id / font_id / content_set_id
study_id / participant_id / rating_id
feature_record_id / extraction_run_id
evidence_id / observation_id / collection_run_id
analysis_run_id
```

禁止按文件 stem、显示名称、字体家族自由文本、URL 字符串或行号模糊联结。别名只能经版本化 registry 解析，并保留原词和解析证据。

### 5.2 防止笛卡尔膨胀

视觉特征、评分和叙事都是一对多。分析数据构建器必须先声明分析单位，再聚合或选择表示：

- rating 模型通常一行是 `participant × stimulus × item/presentation`；
- feature 表需按冻结规则选择 extraction run、表示和 profile，或保留长表；
- narrative 证据不能直接逐条复制到每个参与者评分；
- 同一刺激横跨多个 research line 时不得重复计权；
- 同一作品多图、同一字体多字符和同一社交线程需要 cluster ID。

每次构建输出 join audit：各表输入行数、唯一键数、未匹配数、一对多倍数、过滤原因和最终分析单位。发现意外多对多时必须失败。

### 5.3 叙事与评分不能随意合并

WP2 产生的是有界公共话语证据，不是每个参与者实际接触到的曝光。只有满足以下之一，叙事变量才可进入个体评分模型：

1. TASK-03 实验随机呈现了冻结文化标签/叙事材料；
2. 问卷明确测量了参与者熟悉度/接触，并有预注册操作化；
3. 使用地区/时期聚合变量且时间顺序、样本框架和生态推断边界明确。

否则 WP2 只用于生成假设、描述语境或单独分析，不得把平台词频附给每条 rating 后声称影响了个体偏好。

## 6. 分析快照与计划

### 6.1 不可变输入快照

每个 `analysis_run_id` 必须绑定：

- analysis plan 版本与哈希；
- 所有 handoff 和 artifact 哈希；
- schema/registry/feature/questionnaire/style ontology 版本；
- 纳入/排除和缺失规则；
- 软件锁、Git commit、平台和随机种子；
- 真实/synthetic 数据状态；
- 创建时间和人工门禁状态。

上游数据变化不会静默改变旧分析。重跑旧快照应得到相同分析表和在声明容差内相同输出；更换输入生成新 run。

### 6.2 分析计划对象

最低字段：

- `plan_id`、版本、状态（draft/preregistered/amended/exploratory）；
- 研究问题、estimand、主要/次要结果；
- 分析单位、纳入/排除、分层和对比；
- 模型公式、link、先验/优化器（适用时）；
- 随机效应/层级、cluster 和重复测量；
- 特征选择与变换；
- 缺失、多重比较、敏感性和停止规则；
- confirmatory/exploratory 输出边界；
- 批准/修订历史。

看到真实结果后的修改必须生成 amendment，不覆盖原计划。

## 7. 最低联合分析族

### 7.1 WP1：跨文化感知

核心形式：

$$
y_{pij}=\alpha+\beta_1\,\text{StimulusScript}_i+\beta_2\,\text{NativeScript}_p+
\beta_3(\text{StimulusScript}_i\times\text{NativeScript}_p)+
\gamma^T X_{pi}+u_p+v_i+\epsilon_{pij}
$$

其中 $u_p$ 是参与者层效应，$v_i$ 是刺激层效应。实际模型随 ordinal/continuous 量表决定，不得把 Likert 当连续而不说明敏感性。

### 7.2 WP3：视觉形式增量解释

按预注册顺序比较：

```text
M0       : y ~ script/style + participant controls + (participant/stimulus hierarchy)
M_visual : y ~ selected visual features + script/style + controls + hierarchy
```

报告加入视觉特征后的增量解释、系数/后验区间、交叉验证和校准。特征选择必须在训练 fold 内完成；TASK-02 的 deprecated 综合分不得进入 canonical 模型。

### 7.3 WP4：汉字书体实例与类别

模型至少区分书体概念、字体/作品实例和字符：

```text
y ~ style_concept + visual_features + familiarity + context
    + participant effects + exemplar/work effects + character effects
```

如果某类没有足够独立实例，只报告实例级结果，不生成“书体总体效应”。专家审核是纳入门禁，不是结果变量的真值。

### 7.4 WP2：叙事证据

沿用现有 Matrix A/B、Lift、周趋势和有界采样定义。联合层只消费通过现有质量门禁的输出，并可产生跨线**假设链接**：

- 某对象与某评价词的叙事证据；
- 对应可检验 stimulus/style 条件；
- 对应问卷 item 和 analysis plan；
- 结果支持、不支持或无法检验。

不得因人类评分与平台叙事方向相同就声称传播造成了偏好。

### 7.5 模型与诊断

使用维护良好、许可清晰的统计库，不自行实现优化器或混合模型。选择库前写 method decision，锁定版本并以模拟恢复测试验证。

最低诊断：

- 收敛、奇异拟合/发散和有效样本；
- 残差/后验预测检查；
- 多重共线性和特征尺度；
- cluster、随机效应和重复测量；
- 缺失与排除的组间差异；
- 分组交叉验证，按参与者/刺激/作品防泄漏；
- sensitivity：表示/profile、排除规则、量表处理和模型规格；
- 多重比较或层级收缩；
- 效应量与不确定性，而不只报 p 值或单一准确率。

模型失败必须产生 `failed` run 和诊断，不得退回更简单模型后仍沿用原计划标签。

## 8. 合成数据与真实数据隔离

工作台必须能用一套小型、许可明确、完全合成的纵向 fixture 演示：

```text
source -> asset -> stimulus -> visual feature
       -> synthetic assignment/rating
       -> synthetic narrative evidence
       -> style knowledge/review fixture
       -> analysis -> audit -> release blocked
```

最后一步必须被阻断，因为 synthetic rating 不是研究证据。可以另生成 `demo_export`，但所有页面、图、文件和 API 都需带 `SYNTHETIC / DEMO` 标记，且不能写入正式 release 路径。

测试不得复制真实平台正文、参与者数据或受限图片。

## 9. 统一工作台信息架构

### 9.1 全局导航

- **总览**：模块健康、研究阶段、最近运行、失败和待人工门禁；
- **来源与资产**：权利、候选、派生链、策展和刺激；
- **视觉测量**：特征、运行、敏感性、QC 和构念映射；
- **跨文化实验**：study、问卷版本、分配、配额、质量和真实收集锁；
- **文化叙事**：复用现有 scope、采集、审核、矩阵、证据和导出；
- **汉字书体**：本体、字形、知识断言、专家审核和候选刺激；
- **联合分析**：计划、快照、运行、诊断、对比和证据边界；
- **审计与发布**：schema、哈希、许可、隐私、人工门禁、备份和 release。

### 9.2 页面原则

- 这是研究操作工具，不做营销式 landing page；
- 信息密集但层级清楚，优先表格、过滤、状态、证据下钻和批量操作；
- 不用卡片套卡片，不用装饰性渐变或巨大标题占用工作区；
- 状态不能只靠颜色，使用文字、图标和可访问标签；
- 危险操作显示具体影响、目标数据库/运行和确认短语；
- synthetic、真实、受限、未审核和 release-ready 在所有相关页面一致标识；
- 手机端允许查看状态和审核摘要，复杂表格可水平滚动或切换字段，不重排到不可比较；
- 所有失败都能下钻到原因、输入、版本和建议下一步；
- 不在前端暴露绝对路径、PII、secret 或受限原文。

### 9.3 运行编排

工作台只允许调用模块声明的命令，不拼接任意 shell。参数经类型验证，命令记录输入摘要、操作者、本机时间、退出码和日志位置。长任务支持状态、停止和恢复；停止不把部分输出标为成功。

## 10. 人工门禁与状态机

就绪度是独立维度，必须使用总蓝图的精确枚举，并显示未达到的下一档及阻断原因：

```text
engineering_ready
pilot_ready
research_validated
```

不得用 `fixture_validated` 冒充 `pilot_ready`，也不得用 `analysis_completed` 冒充 `research_validated`。流程状态至少包括：

```text
absent
contract_ready
fixture_validated
awaiting_rights
awaiting_expert_review
awaiting_ethics_or_participants
real_data_available
analysis_ready
analysis_completed
release_blocked
release_candidate
released
```

流程状态由机器检查和人工决定记录共同产生，不能由用户界面随意选择最终状态。每条待办和决定必须保留总蓝图中的精确 gate ID：`GATE-RIGHTS`、`GATE-HISTORY`、`GATE-ETHICS`、`GATE-PARTICIPANTS`、`GATE-EXPERT`、`GATE-TERMS`、`GATE-RELEASE`；不得只存 `awaiting_human` 或把多个 gate 压成一条不可审计状态。

发布前机械检查：

- 输入 handoff/schema/hash 全部匹配；
- 资产可按目标用途使用和再分发；
- 刺激、视觉和专家 QC 通过；
- 真实评分有伦理/同意/隐私状态且非 synthetic；
- 叙事数据满足 query、registry、人工审核和 release 质量门槛；
- 分析计划、amendment 和模型诊断完整；
- 去标识和重识别风险检查通过；
- 所有必要人工 gate 有明确范围和证据；
- release 目录为空且 no-overwrite；
- checksums 和 manifest 完整。

任何一项失败都输出机器可读阻断码和人类说明。UI 不提供“仍然发布”快捷绕过。

## 11. 审计包与发布物

一次分析/发布候选至少包含：

```text
analysis_plan.json
analysis_run_manifest.json
input_artifacts.json
join_audit.json
inclusion_exclusion_flow.json
model_specification.json
model_diagnostics.json
effect_estimates.csv/json
sensitivity_results.csv/json
figures/
limitations_zh.md
gate_report.json
checksums.sha256
software_environment.json
README_zh.md
```

发布包另含 schema、数据字典、许可、隐私和人工审核摘要。图表必须显示有效样本、不确定性和组定义；不得只展示排序榜单或综合“高级感分”。

## 12. 备份、恢复与运维

- 中央 catalog 使用 SQLite 一致性备份和校验；
- 模块数据库保持各自备份机制，工作台生成协调备份 manifest，而非直接复制打开中的 WAL 文件；
- 备份 manifest 记录每个模块备份 ID、schema 版本、哈希和一致时间点；
- 恢复先演练到临时路径，验证后才允许覆盖目标；
- 恢复社会叙事生产库沿用其现有确认和停服规则；
- 大型资产只记录位置和哈希，不在每次 catalog 备份重复复制；
- 健康页显示磁盘空间、数据库 integrity、schema 兼容、最近备份、失败任务和凭据布尔状态；
- 凭据只显示 configured/not configured，不显示值；
- 日志轮转、路径和数据分类写入本机运维文档。

## 13. 安全与本机边界

- 默认只监听 `127.0.0.1`；对外绑定必须显式警告并另行批准；
- 防止路径遍历、任意文件读取、任意命令、CSV formula injection 和恶意 zip 导入；
- handoff/zip 先在隔离 staging 验证，再原子登记；
- Web 写操作使用防重放/CSRF 等适合本机应用的保护；
- 导入大小、解压大小、文件数和图像像素有上限；
- secret、PII、平台正文和受限资产不得写入前端日志或分析包；
- 错误页面不显示堆栈和环境变量；
- 第三方依赖固定版本并记录许可证与安全审查。

## 14. 建议模块边界

```text
src/glyph_features/workbench/
  cli.py
  app.py
  catalog.py
  modules.py
  handoffs.py
  gates.py
  snapshots.py
  joins.py
  analysis/
  releases.py
  backups.py
  static/
schema/
  handoff_manifest.schema.json
  analysis_plan.schema.json
  analysis_run.schema.json
  gate_decision.schema.json
data/fixtures/system_e2e/
docs/
  workbench_local_ops_zh.md
  joint_analysis_protocol_zh.md
```

可以按现有工程风格调整，但领域边界和公开接口必须保留。尽量复用 FastAPI、SQLite 和现有静态应用方式；引入新框架前证明必要性，不重写已工作的社会叙事 UI。

## 15. 实施阶段

### 阶段 A：契约兼容与适配器

- 验证 TASK-01 至 TASK-04 handoff；
- 建立 module descriptor、中央 catalog 和兼容矩阵；
- 为社会叙事现有 validated export 建立 adapter；
- 不兼容或缺失模块明确显示 blocked/fixture-only。

### 阶段 B：不可变快照与联合构建

- 实现 artifact registry、hash、analysis plan 和 snapshot；
- 实现分析单位、join audit 和多对多失败；
- 用 synthetic fixture 验证所有 ID 关系。

### 阶段 C：分析引擎

- 选择并锁定成熟统计依赖；
- 用模拟数据验证参数恢复、分层结构、缺失和错误模型诊断；
- 实现 WP1/WP3/WP4 和 WP2 假设链接，不虚构真实结论。

### 阶段 D：统一工作台

- 组合模块状态、入口、运行和证据下钻；
- 保留原模块独立入口；
- 实现审计、gate 和 release 页面；
- 桌面/移动和可访问性验收。

### 阶段 E：端到端与运维

- 完整 synthetic/许可 fixture 演示；
- 备份/恢复、停止/重启和故障注入；
- release 必须因 synthetic 和人工门禁而阻断；
- 生成本机操作手册和最终完成矩阵。

### 阶段 F：真实数据入口（条件执行）

只有用户明确批准并且上游真实门禁通过后，才导入真实评分/专家审核/正式叙事输出。导入前展示数据分类、数量、哈希、许可/伦理范围和预期分析，不自动运行 confirmatory 模型。

## 16. 自动测试

至少覆盖：

### 契约与导入

- handoff schema、哈希、commit、版本和兼容矩阵；
- zip slip、重复文件、超限、篡改和不受支持 schema；
- 原子导入与失败回滚；
- 同一 handoff 重复导入幂等，不覆盖不同哈希版本。

### 联结与分析

- 全部稳定 ID 外键和未匹配报告；
- 意外多对多/笛卡尔膨胀必须失败；
- 同一 stimulus 跨 research line 不重复计权；
- 同作品/字体/线程 cluster 保留；
- null/不适用不转 0；
- synthetic/real 严格分区；
- 特征选择和标准化无 fold 泄漏；
- 模拟数据参数恢复和错误模型失败路径；
- ordinal/continuous 量表路由正确；
- narrative 变量无合法暴露操作化时不能进入个体模型；
- 实例不足时阻断书体类别结论；
- 重跑快照确定性和旧 run 不变。

### 产品与安全

- 模块缺失、降级、数据库锁、磁盘满、任务取消和恢复；
- 社会调度器只启动一次，独立 `glyph-social` 仍可运行；
- 默认不迁移生产数据库；
- secret/PII 不出现在 API、HTML、日志和导出；
- 路径遍历、任意命令和 CSV 注入防护；
- release gate 对许可、隐私、QC、专家、伦理、synthetic 和模型失败逐项阻断；
- 备份 consistency、协调 manifest 和临时恢复演练；
- 浏览器桌面/移动主要流程、文本不重叠、键盘操作和错误下钻；
- 根测试集及资产、视觉、实验、社会叙事、汉字书体、工作台六个模块的契约测试全部通过。

## 17. 最低端到端验收场景

使用许可明确、无 PII 的 fixture，必须完成：

1. 导入一个 source 和 asset；
2. 生成/登记一个稳定 stimulus 及 A/B/C 或适用表示；
3. 导入至少一组可解释 visual measurements；
4. 导入一个 synthetic participant 的 assignment、presentation 和 ratings；
5. 导入一个带来源的 synthetic narrative evidence；
6. 关联一个 Han style knowledge/review fixture；
7. 创建 analysis plan 和不可变 snapshot；
8. 构建分析表并生成 join audit；
9. 运行模型并显示诊断与局限；
10. 在统一入口逐级下钻所有证据；
11. 导出 demo audit package；
12. 正式 release 因 synthetic/人工门禁被机械阻断；
13. 重启服务后状态、运行和审计仍一致；
14. 协调备份并恢复到临时路径后复验；
15. 独立模块 CLI 和既有社会叙事/视觉测试仍通过。

## 18. 全局完成定义

本任务只有同时满足以下条件才算完成：

1. 一条 `stimulus_id` 能贯通来源、资产、视觉、问卷、评分、书体知识和分析；
2. WP2 没有具体 stimulus 时，也能以规范 object/hypothesis link 连接而不伪造个体暴露；
3. 一个入口可查看并操作模块，但每个模块仍可独立测试和运行；
4. 中央 catalog 不复制 raw 数据或成为冲突事实源；
5. 分析运行具有不可变输入、计划、环境、诊断、审计和可复现输出；
6. 系统能识别多对多、泄漏、伪重复、实例不足和无效叙事联结；
7. synthetic E2E 全通过且正式发布被正确阻断；
8. 所有真实、高风险和人工决定继续锁在明确 gate 后；
9. 本机运维、备份恢复、失败处理和数据分类文档完整；
10. 桌面和移动工作台经自动截图和交互验证，无空白、重叠或虚假状态；
11. 现有 `glyph-social`、visual v1 和历史数据保持兼容；
12. 最终报告逐项区分 `engineering_ready`、`pilot_ready` 和 `research_validated`。

## 19. 最终交接

TASK-05 也必须生成符合总蓝图的 `handoff_manifest.json`，不得因其是最后一项任务而省略。除通用字段外，至少包含：

- 五个任务和现有 WP2 adapter 的实际版本、输入 handoff 哈希与兼容结论；
- module descriptor、中央 catalog schema 和只读/写入入口；
- analysis plan、snapshot、run、join audit 和 release 契约版本；
- synthetic E2E 运行、浏览器验收、备份恢复与故障注入结果；
- 每个模块分别对应的 `engineering_ready`、`pilot_ready`、`research_validated` 状态与证据；
- 全部未决 gate 的精确 ID、范围、阻断对象和门禁包路径；
- 受限、PII、synthetic、不可发布和不可进入正式分析的机器可读原因；
- 启动命令、健康检查、审计导出、备份和恢复入口；
- 最终系统已知限制和后续维护责任。

## 20. 强制停止条件

出现以下任一情况必须停止相关切片并提交决策包：

- 任一上游 handoff 哈希/schema 不匹配，但只能靠猜字段继续；
- 需要迁移或修改社会叙事生产数据库；
- 需要把真实 PII、受限资产或平台 raw 数据复制到中央 catalog；
- 需要把平台叙事频率直接赋给个体评分才能跑联合模型；
- 需要把一个字体实例报告为书体类别结论；
- 需要用未经校准的 CV 总分作为审美真值；
- 需要接受条款、付费、对外部署或导入真实研究数据；
- 需要绕过许可、伦理、专家、隐私或 release gate；
- 用户本地未提交修改无法安全保留。

停止时提交总蓝图规定的最终报告、决策/门禁包和完整系统 handoff，不自行进入真实研究或公开发布。

# TASK-02：理论构念、可解释视觉测量与 CV 子系统

版本：`0.1.0-draft`
日期：2026-09-04
建议执行顺序：第二项；可先修复 fixture 路径，正式运行等待 TASK-01 刺激接口冻结
系统角色：把冻结刺激转换为可复现视觉事实，不替人类判断审美

## 1. 给执行 Agent 的任务指令

你负责把现有两套视觉工作整合为一个正式子系统：

1. 仓库已冻结并实现的 visual features v1：八个上层视觉维度和一组底层可解释代理量；
2. `lijie_aesthetic_cv/`：5 个设计理论指标、5 个书法理论指标、公式和 CV MVP。

你的任务不是二选一，也不是继续输出一个未经验证的总分。你必须建立“**图像表示 → 原始测量 → 理论构念映射 → 真人校准模型**”四层架构，把理论、算法和效度边界分开。

必须先阅读：

- `docs/agent_tasks/00_system_blueprint_zh.md`
- `docs/agent_tasks/01_asset_stimulus_system_task_zh.md`
- `status/four_research_lines_zh.md`
- `status/visual_analysis_framework_zh.md`
- `status/visual_feature_v1_proposal_zh.md`
- `configs/visual_features_v1.yaml`
- `schema/visual_features.schema.json`
- `schema/stimulus.schema.json`
- `src/glyph_features/render.py`
- `src/glyph_features/measure.py`
- `src/glyph_features/qc.py`
- `tests/test_measurements.py`
- `lijie_aesthetic_cv/` 下全部文档、代码、测试和依赖

开始时核对实际仓库状态和现有测试，不要把本文中的测试数或当前文件位置当成永久事实。

## 2. 系统定位

本子系统只回答：

- 某个冻结刺激在某个明确表示、归一化协议和算法版本下，测到了什么；
- 测量是否稳定、适用于哪些对象、缺失或失败在哪里；
- 哪些原始测量可以作为某个设计/书法理论构念的代理；
- 这些代理与真实人类评价的关系能否在后续模型中被验证。

本子系统不回答：

- 哪种文字、字体或书体天然更美或更高级；
- 获奖图是否比未获奖图更美；
- 一个手工权重总分是否代表审美真值；
- “气韵”是否被 CV 直接测量；
- 模型输出是否可以替代真实受试者或专家。

## 3. 当前基线与必须解决的问题

### 3.1 可复用基础

- `src/glyph_features` 已有锁定环境、渲染、测量、QC、no-overwrite 和稳定运行目录；
- visual features v1 已定义八维、表示、适用性、分子/分母、缺失语义和两个 normalization profile；
- 已有 140 个唯一受控刺激的参考运行，可作为回归 fixture，不是公共 release；
- `lijie_aesthetic_cv` 已有 5+5 理论构念、文献、公式、字段字典和可运行 MVP；
- 当前 MVP 可以处理现有 375 张标准化图，但这只证明执行兼容，不证明测量有效。

### 3.2 必须修复的工程与研究问题

- 两套框架尚未明确映射，容易产生“八维”和“十项”互相竞争；
- CV MVP 使用独立、未锁定的 `requirements.txt`，未接入根项目运行时和测试发现；
- 递归批处理按 `path.stem` 输出，同名输入会静默覆盖；
- 坏图可以被记录为失败，但总进程仍返回 0；
- 权重允许零、负数、NaN 和 Infinity，并可生成表面合法的 0 或 100；
- `cv2.imwrite` 返回值未检查；输出含绝对路径，缺少完整运行环境和变换元数据；
- 当前规则分把理论假设提前固化为“越大越好”，与文档提出的非线性和人评校准相冲突；
- 单一灰度居中图会抹去平衡、章法、墨色等构念所需信息；
- 自动去小连通域、背景估计和骨架算法可能系统性伤害附点、细笔画和特定文字系统；
- `qi_proxy` 只能拆成低层代理，不得作为被直接观测的实体。

## 4. 四层视觉知识模型

### 层 1：表示（Representation）

输入必须来自冻结资产/刺激并明确是：

- `A_layout`
- `B_shape`
- `C_ink`
- 受控字体的 `bbox_height_matched` / `ink_area_matched`
- `raster_grayscale` / `raster_binary` / `contour` / `skeleton`

不得从文件夹名称猜测表示。每个输入必须带 `stimulus_id`、`asset_id`、输入哈希、表示协议和 QC 状态。

### 层 2：原始测量（Measurement）

原始量包括面积、距离、比例、质心、对称差异、轮廓、骨架、灰度统计和序列统计。它们必须具有公式、单位、输入表示、适用范围、分子/分母、缺失语义和算法配置哈希。

### 层 3：理论构念（Construct）

“平衡、统一、笔法、气韵”等是解释层，不等于一个像素统计。一个构念可由多个原始特征支持，一个原始特征也可服务多个构念；映射必须显式、多对多、有证据等级。

### 层 4：校准模型（Calibration）

只有接入 TASK-03 的真实人类评分后，才可以估计特征方向、非线性、权重和跨文化差异。校准结果属于 `analysis_run_id`，不得回写或篡改原始测量。

## 5. 八维与 5+5 构念的统一映射

八维保留为 visual features v1 的视觉组织语言；十项保留为理论构念和人评解释语言。最低映射如下，Agent 必须补成版本化 registry，而不是硬编码在散落函数中。

| 5+5 构念 | 主要八维来源 | 首选表示 | 解释边界 |
|---|---|---|---|
| D1 平衡 | 视觉重心、排版、稠密度 | A | 偏心不自动等于差；方向由人评校准 |
| D2 对称 | 几何度 | B | 对称是描述量，允许非线性效应 |
| D3 比例与尺度 | 比例、稠密度 | A/B | 同类参考分布，不默认黄金比例 |
| D4 统一/一致性 | 统一度、几何度、笔势 | B | 层级差异不等于不统一 |
| D5 节奏/序列 | 阅读节奏、排版、统一度 | A/B | 形式序列不等于心理阅读速度 |
| C1 笔法与线质 | 笔势、几何度 | B/C | 图像只能测笔迹结果，不能还原书写动作 |
| C2 结体/字内结构 | 几何度、比例、稠密度 | B | 默认仅同字符/同书体 cohort 可比 |
| C3 布白/章法 | 排版、稠密度、视觉重心 | A/B | 字内与整体版面分层报告 |
| C4 墨法/墨色 | 新增灰度/纹理测量 | C | 黑白数字字形可明确不适用 |
| C5 气韵/行气/力势代理 | 笔势、节奏、统一度 | B/C | 只发布方向、连续、粗细、连通等低层代理 |

不得给十项各强行制造一个 0–100 分。允许提供可视化或标准化统计，但必须命名为对应原始量或校准后预测，不能命名为客观审美分。

## 6. 可扩展特征契约

现有 `visual_features.schema.json` 的固定宽表适合 v1 核心量，但无法无限承载新增墨色、骨架和理论映射。先完成 schema gap 分析，然后在不破坏 v1.1 历史记录的前提下增加两个规范对象。

### 6.1 Feature Definition Registry

建议新增 `visual_feature_definition` schema/registry，每个定义至少包含：

- `feature_code` 和定义版本；
- 中英文名称与严格公式；
- 输入表示、对象层级（单字/多字/生态图/书法）；
- 单位、值域、分子、分母和零点含义；
- 适用性与机器可读缺失码；
- 算法、参数 schema、默认配置哈希；
- 主要/次要八维归属；
- 5+5 构念映射及证据等级；
- 跨脚本可比性：`direct` / `protocol_dependent` / `within_script_only` / `not_applicable`；
- 状态：`core` / `diagnostic` / `experimental` / `deprecated`；
- 文献来源和已知偏差。

### 6.2 Long-form Measurement Record

建议新增长表测量记录或严格等价接口，最低字段：

```text
measurement_id
feature_record_id
stimulus_id
asset_id
extraction_run_id
representation
normalization_profile
feature_code
feature_definition_version
value
numerator
denominator
unit
applicability
measurement_status
missing_code
algorithm_config_sha256
input_sha256
computed_at
software_environment_sha256
```

现有 v1.1 宽表继续可读，并提供确定性 `wide <-> long` 适配器。适配器不得猜测未知列，也不得把 `null` 转成 0。若选择直接升级现有 schema，必须保留历史 schema 文件、迁移说明、兼容测试和旧参考运行读取能力。

## 7. 算法实现要求

### 7.1 输入与运行

- 只消费 TASK-01 通过 schema、哈希和 QC 的表示；
- 每次运行冻结 feature registry、配置、依赖、操作系统/架构和输入 manifest 哈希；
- 输出目录使用 `extraction_run_id`，同一 run 不覆盖；
- 单个样本用 `stimulus_id + asset_id + representation` 定位，不使用文件 stem；
- 批处理中任一意外失败必须非零退出，同时保留已完成记录和失败清单；
- 预期的不适用和缺失不是异常，但必须写机器可读原因。

### 7.2 图像处理

- A 通道不得在测平衡/章法前自动居中；
- B 通道只能使用经人工确认的主体 mask；
- C 通道保留灰度/色彩层次并记录背景校正；
- 不得用“保留最大连通域”默认删除点、变音符、细线或分离部件；
- 任何形态学操作、阈值、平滑、重采样和骨架算法必须配置化并记录；
- 采用标准库/成熟实现时记录包和版本；自实现算法必须用解析 fixture 和参考实现交叉验证；
- `cv2.imwrite`、文件 fsync/关闭和输出哈希必须检查；
- 所有公开路径为仓库/运行目录相对 POSIX 路径，不泄露用户绝对路径。

### 7.3 十项构念输出

每个构念页面或报告显示：

1. 理论定义和来源；
2. 本次刺激可用的原始代理量；
3. 不适用/缺失原因；
4. 表示和归一化敏感性；
5. 可视化诊断；
6. 是否有真人校准；
7. 可支持和不可支持的解释。

没有真人校准时只能标记 `uncalibrated_proxy`，不能出现“审美 83 分”式结论。

## 8. 现有 CV MVP 的处置

不得简单删除 `lijie_aesthetic_cv`，也不得让它继续成为第二套生产管线。完成以下迁移：

1. 保留理论文档和检索日志，补充证据等级与引用核验状态；
2. 把可复用算法迁入或包装进 `src/glyph_features` 的视觉模块；
3. 根 `pyproject.toml` 和锁文件固定实际直接依赖，测试进入根 `pytest`；
4. 修复同名覆盖、错误退出码、异常权重、绝对路径、未检查写入和环境漂移；
5. canonical 输出移除未经校准的 `total_score`；如保留演示，必须显著标为 deprecated/uncalibrated，并拒绝进入联合分析；
6. 权重文件只属于后续分析模型，不属于原始特征提取；若仍支持读取，拒绝未知键、负数、全零、NaN 和 Infinity；
7. 提供旧 MVP 输出到新测量契约的迁移说明，不伪造缺失元数据。

## 9. 建议模块边界与 CLI

建议结构：

```text
src/glyph_features/vision_system/
  definitions.py
  representations.py
  geometry.py
  layout.py
  stroke.py
  ink.py
  sequence.py
  extract.py
  qc.py
  export.py
configs/
  visual_measurements_v2.yaml
data/fixtures/visual_measurements/
```

最低 CLI：

```text
glyph-vision validate-definitions
glyph-vision extract --stimulus-manifest ... --asset-handoff ...
glyph-vision qc --run-id ...
glyph-vision compare-representations --run-id ...
glyph-vision export --run-id ... --format long|v1-wide
glyph-vision validate-handoff ...
```

准确命名可遵循现有 CLI 组织方式，但不能复制两套入口和两套 run 语义。

## 10. 科学验证策略

### 10.1 解析与合成 fixture

为简单矩形、圆、镜像图、偏心图、等距序列、已知孔洞、已知灰度梯度建立可计算期望值。测试允许数值容差，不允许只断言“在 0 到 100 之间”。

### 10.2 变形关系测试（metamorphic tests）

- 平移 A 表示应改变质心/边距，B 重新对齐后形状量应稳定；
- 等比缩放应保持无量纲比例，像素量按声明变化；
- 镜像应按预期改变/保持对应对称量；
- 亮度变化不应改变二值形状量，但应改变 C 通道墨色量；
- 分辨率和阈值敏感性必须落入冻结容差或产生 warning；
- 增加噪声、压缩和模糊时，系统应报告 QC/敏感性，而非无声改变结论。

### 10.3 跨文字偏差 fixture

至少包含：

- 拉丁字母的点、变音符和细 serif；
- 汉字分离点画、封闭空间和复杂结构；
- 韩文组合块和多个 jamo；
- 假名曲线、浊点/半浊点；
- 书法灰度、飞白、断续边缘；
- 多组件 logo 和复合展板的拒绝/需审路径。

验证小组件不会被默认删除，cluster/字符边界不由连通域数冒充。

### 10.4 人工与真人效度

- 两名视觉/字体领域审核者检查 fixture 表面效度，属于 `GATE-EXPERT`；
- TASK-03 人评用于构念关联和权重估计，不用于事后修改冻结特征定义；
- 若特征在某文字系统失效，标记适用性或升协议版本，不隐藏该组。

## 11. 自动测试与质量门禁

至少覆盖：

- feature registry 唯一性、公式/单位/适用性完整性；
- v1.1 历史数据继续验证和读取；
- long/wide 适配器 round-trip；
- NaN/Infinity 禁止进入 JSON、CSV 和分析；
- 分母为零、单元素序列、空前景、全白/全黑、损坏输入；
- 输入哈希、配置哈希和输出篡改检测；
- 同名不同目录样本不会覆盖；
- `cv2.imwrite`/磁盘失败传播；
- 部分失败非零退出且失败记录完整；
- no-overwrite 和新 run ID；
- 确定性重复运行；
- A/B/C 适用性强制；
- 十项构念不能在缺少底层代理时生成默认分；
- canonical export 不包含未校准综合审美分。

## 12. 最低可执行验收

1. 八维与 5+5 的版本化多对多映射可被程序读取和验证；
2. 每个发布特征都有定义、公式、单位、输入表示、适用性、缺失码和配置哈希；
3. visual features v1 参考运行和历史 schema 仍可读取，不被新系统改写；
4. 旧 CV MVP 的同名覆盖、错误退出、写入检查和非有限权重问题都有回归测试；
5. 许可明确 fixture 可从 TASK-01 handoff 完整运行到 long-form measurements、QC、checksums 和 handoff；
6. A/B/C 的用途边界由测试强制，A 不被自动居中，C 不被无声二值化；
7. 至少一组四文字系统 fixture 通过组件保留和敏感性检查；
8. canonical 输出没有综合审美分，`qi` 只以低层代理和构念映射出现；
9. 根锁定环境一条命令可运行新增测试，全仓既有测试继续通过；
10. 质量报告区分计算稳定性、表面效度、构念效度和预测效度，未完成项如实标记。

## 13. 对下游的交接

### 给 TASK-03 跨文化实验

- 5+5 构念的人类可理解定义，但不强迫问卷每次询问全部十项；
- 可用作问卷分层/平衡的刺激特征和 QC，不把预测结果泄漏给参与者；
- 冻结特征字典和版本，供预注册分析引用。

### 给 TASK-04 汉字书体

- 单字/多字、轮廓/骨架/灰度的测量 API；
- `within_script_only` 和专家审核接口；
- 字形结构、笔势、墨法与气韵代理的严格边界。

### 给 TASK-05 联合分析

- feature registry、long-form measurements、v1 兼容适配器；
- 运行 manifest、失败记录、敏感性和 QC；
- 明确哪些是原始量、实验性量和未经校准代理；
- 禁止联合分析消费的 deprecated `total_score` 字段清单。

## 14. 强制停止条件

出现以下任一情况必须停止相关切片：

- TASK-01 尚未冻结正式输入，却准备把临时文件当正式刺激发布；
- 需要为了得到“更合理的审美结果”在看过真人评分后改特征公式；
- 需要把十项手工加权成总分才能完成展示；
- 新 schema 会破坏历史 visual v1 且无迁移路径；
- 某文字系统持续失败但只能通过删除其细小结构才能通过；
- 需要专家判断书法结构或气韵，却没有通过 `GATE-EXPERT`；
- 用户未提交代码与本任务修改发生不可安全解决的冲突。

停止时提交总蓝图规定的报告与 `handoff_manifest.json`，不自动进入真实人评或 TASK-05。

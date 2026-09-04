# TASK-04：汉字书体、字形演化知识与专家在环子系统

版本：`0.1.0-draft`
日期：2026-09-04
建议执行顺序：第四项；本体和 fixture 可并行，正式刺激通过 TASK-01 与专家门禁
系统角色：把汉字书体的历史知识、字形结构、文化联想和受控实验连接起来

## 1. 给执行 Agent 的任务指令

你负责实现 GLYPH 第四条研究线的基础子系统。任务不是收集一批名字带“篆、隶、楷、行、草”的字体文件，也不是让模型自动判断哪种书体更美，而是建立：

> 可追溯的书体知识记录 + 字符级字形实例 + 同内容受控刺激 + 专家独立审核 + 与视觉、问卷和文化叙事模块兼容的接口。

必须先阅读：

- `docs/agent_tasks/00_system_blueprint_zh.md`
- `docs/agent_tasks/01_asset_stimulus_system_task_zh.md`
- `docs/agent_tasks/02_visual_measurement_system_task_zh.md`
- `docs/agent_tasks/03_cross_cultural_experiment_task_zh.md`
- `status/four_research_lines_zh.md`
- `status/visual_feature_v1_proposal_zh.md`
- `schema/source.schema.json`
- `schema/stimulus.schema.json`
- `schema/cultural_narrative.schema.json`
- `schema/shared.schema.json`
- `configs/visual_features_v1.yaml`
- `data/fixtures/content_sets.csv`
- `lijie_aesthetic_cv/` 中书法理论、公式和文献部分
- 社会叙事系统的 object map、codebook 与人工审核边界

开始时核对实际实现和数据。现有 visual v1 中的四个汉字字体实例只是测量 fixture，不能被当成完整 WP4 或四类书体总体代表。

## 2. 系统定位

本子系统服务四种连接：

- **历史知识 → 字形实例**：某个书体/字形归属由什么来源和证据支持；
- **字形实例 → 视觉测量**：轮廓、笔画、比例、重心、曲直和空间结构如何被测量；
- **书体条件 → 真人实验**：在相同文字内容和呈现条件下，不同书体实例如何被评价；
- **文化叙事 → 可检验假设**：如“小篆＝古典/权威”等说法在哪些来源出现，是否影响带标签与盲评差异。

本子系统不负责：

- 把字体文件名当成书体归属证据；
- 把一个数字字体实例推广为整个历史书体；
- 用现代 Unicode 字体自动重建古代字形；
- 让 LLM 代替书法史、篆刻或字体设计专家；
- 把文化联想写成书体固有属性；
- 把专家意见当作普通受试者审美评分。

## 3. 研究对象必须分层

“书体”“字体”“字形”和“文化标签”不是同一个对象。至少区分：

1. **书体概念 `style_concept`**：如小篆、隶书、楷书、行书、草书、宋体、黑体、瘦金体；
2. **历史/功能子类 `style_variant`**：具体时期、地域、媒介、碑帖/印章/印刷等变体；
3. **字体实例 `font_instance`**：一个可哈希的数字字体文件或静态 variable font instance；
4. **字形实例 `glyph_instance`**：一个具体字符在特定来源、字体或作品中的具体形态；
5. **作品/载体 `work`**：碑帖、手稿、印章、印刷样本、现代字库等；
6. **结构描述 `glyph_structure`**：构件、轮廓、笔画/线段、比例、重心和变体关系；
7. **历史断言 `historical_claim`**：时期、归属、演变或影响关系，必须带来源；
8. **文化联想断言 `association_claim`**：如古典、权威、文人、锋利、现代，必须视为可核验话语；
9. **专家审核 `expert_review`**：对归属、结构和刺激适用性的独立意见；
10. **实验刺激 `stimulus`**：冻结内容、资产、画布和条件后的展示对象。

禁止在一个 `style_name` 字符串中压平以上层级。

## 4. 首版范围与边界

### 4.1 目标书体集合

首版知识本体应能表达四线文档列出的：

- 小篆；
- 隶书；
- 楷书；
- 行书；
- 草书；
- 宋体；
- 黑体；
- 瘦金体。

这不意味着首版必须为八类都发布完整实验刺激。只有来源、权利、字符覆盖、结构和专家审核通过的类别才能进入 pilot。缺失是合法结果，不得用风格相似字体顶替。

本体必须明确历史书体、书家风格、印刷字体类别和现代数字字体不是同一分类层。例如“瘦金体”不能仅因某款现代字体使用该名称就被视为历史原作等价物。

### 4.2 字符内容

以 visual v1 冻结的汉字内容集作为兼容起点，而不是自动作为最终 WP4 清单。对每个候选字符核验：

- 在目标历史阶段/书体中是否有可追溯形态；
- 简繁、异体、古今字和 Unicode 映射；
- 是否因字义、构形或缺字造成系统性选择偏差；
- 不同书体是否比较的是同一语言单位，还是只能比较相关字形；
- 数字字体是否 fallback、替换或现代化重构。

任何字符替换或扩展进入版本化 content set；不得因某字体缺字而静默换字。

### 4.3 推断单位

只有一个字体实例的类别只能报告“该实例差异”，不能报告“书体效应”。若目标是类别层推断，协议原则上应为每个书体纳入多个具有独立来源的实例，并在模型中把实例作为层级/随机效应。

建议把“每类至少 3 个合格实例”作为进入类别推断的目标门槛；达不到时保留实例级 pilot，并明确禁止泛化。历史手写书体的“实例”应来自不同作品/书家/时期的设计化抽样，不能把同一碑帖的多个字当成独立书体复本。

## 5. 知识契约设计

### 5.1 不要求图数据库

首版使用版本化 JSON/JSONL schema 和规范关系表即可；本机 SQLite 可做索引和审核队列。除非有可执行证据证明需要，不引入 Neo4j 或云图数据库。图谱的核心是可追溯关系，不是技术品牌。

### 5.2 建议新增规范对象

#### `han_style_concept`

- `style_id`
- 中英文规范名、历史名称和受控别名
- 上位/下位概念
- 分类层级：历史书体/书家风格/印刷类别/现代数字类别
- 时期和地域（允许不确定区间）
- 典型媒介和使用场景
- 定义来源列表
- 记录状态和人工审核状态

#### `han_glyph_instance`

- `glyph_instance_id`
- Unicode/字符身份、异体和内容集 ID
- `style_id`、`work_id`、`font_id`/`asset_id`
- 来源、定位（页、拓片、字帖位置等）和资产哈希
- 原始/描摹/数字字体/生成等获取类型
- 轮廓、mask、父资产和变换
- 权利层级与发布层级
- 结构 QC、归属状态和专家审核状态

#### `han_knowledge_claim`

- `claim_id`
- 主语、关系、宾语/文字值
- claim 类型：定义、时期、归属、演变、形式描述、使用场景、文化联想
- `source_id`、精确页码/定位和 `evidence_span`
- 原文语言、翻译和翻译审核状态
- 证据等级、置信度和不确定性
- AI 抽取候选与人工确认状态
- 支持、反对或限定关系

#### `expert_review`

- `review_id`、review package/version、pseudonymous reviewer ID
- 审核对象和独立轮次
- 归属、结构、笔画逻辑、历史适切性、来源忠实度、实验适用性
- 决定：`pass` / `fail` / `needs_revision` / `outside_expertise`
- 冻结理由码和可选说明
- 时间、冲突/裁决关系；原始审核不可覆盖

所有对象都要有 schema、版本、模板、fixture、验证器和外键检查。复用现有 `source_id`、`asset_id`、`font_id`、`stimulus_id`，不得创建同义 ID。

## 6. 证据与叙事分层

必须把以下内容物理和语义分开：

| 层 | 示例 | 能支持什么 |
|---|---|---|
| 来源事实 | 某字形出现于某碑帖/字库 | 来源和对象存在 |
| 学术断言 | 某研究将某形态归于某书体/时期 | 可追溯的学术观点 |
| 形式测量 | 该实例纵横比、对称、曲直等 | 视觉描述 |
| 公共叙事 | 媒体称小篆“古典、权威” | 叙事观察 |
| 专家审核 | 专家认为刺激结构/归属可用 | 研究 QC |
| 受试者评分 | 参与者认为其高级/现代 | 感知结果 |

不得把公共叙事提升为历史事实，也不得把专家判断提升为公众偏好。

每条知识断言必须能回到 `source_id` 和证据片段。仅有书名而没有页码/章节定位的核心归属断言不能进入已验证层。AI 可辅助候选抽取和翻译，但必须保留原文并由人复核。

## 7. 字形资产与权利

- 所有字体、扫描、拓片、矢量描摹和截图先进入 TASK-01 资产系统；
- 古籍/碑帖公版不自动意味着数字扫描可自由再分发，分别记录作品权利和数字化版本权利；
- 现代字库名称和可下载不等于开放许可；
- 描摹/重绘必须保留父来源、操作者、方法和差异，不标为历史原件；
- 生成式模型输出只可作为实验候选，不能伪装成传统字形；
- 受限图像只能在本机审核包显示，公开 release 使用元数据、哈希或获准的低风险派生物；
- 任何新下载、登录、条款或付费遵守 `GATE-TERMS` 和 `GATE-RIGHTS`。

## 8. 受控刺激设计

### 8.1 实验矩阵

最低维度：

```text
style_concept
  x exemplar/font/work
  x character/content_set
  x render/representation profile
  x label condition (blind / contextual, if separately approved)
```

不得把同一作品的多个字符当成多个独立书体样本。矩阵必须同时报告类别、实例、字符和刺激的数量。

### 8.2 控制变量

- 同一比较 block 尽量使用相同字符内容；
- 字符语义和可读性单独记录；
- 画布、颜色、显示尺寸、anchor 和渲染环境冻结；
- 等比例变换，不把纵长篆书强行拉成方形；
- 保留 natural/bbox profile 与必要敏感性 profile；
- 现代字体默认 kerning/feature、地区字形和 variable axes 必须显式；
- 历史图像的纸张、损伤、拓印和拍摄差异不能被当成书体特征；
- 需要重绘以统一噪声时，同时保留原件和重绘，并把“重绘者效应”作为限制。

### 8.3 刺激层级

至少区分：

- `historical_source_specimen`：保留历史载体，用于来源/生态研究；
- `expert_traced_shape`：专家或受训人员依据来源描摹的形状；
- `digital_font_specimen`：由合法字体渲染；
- `controlled_comparison_stimulus`：通过协议和专家审核，可进入问卷；
- `generated_candidate`：AI/规则生成，默认不能进入真实研究。

不同层级不在主分析中无说明地合并。

## 9. 专家在环流程

### 9.1 专家角色

审核包应分别覆盖：

- 书法史/文字学或相关研究者：历史归属、术语和来源；
- 书法/篆刻实践专家：笔画逻辑、结体和书写合理性；
- 字体/视觉设计专家：数字化、字库实例和实验呈现。

同一人不必覆盖全部角色；允许 `outside_expertise`。Agent 不得自行把某人的一般设计经验推断为所有领域资格。

### 9.2 独立审核

正式 pilot 候选至少需要两份独立审核。审核包必须随机/盲化可盲化信息，先独立导出，再导入系统；第二位审核者不能先看到第一位答案。分歧进入裁决，但裁决不删除原始意见。

审核维度至少包括：

- 字符身份和异体映射；
- 书体/字体实例归属；
- 缺笔、错笔、fallback 或现代化误写；
- 结构、比例和书写逻辑；
- 历史来源忠实度；
- 是否适合作为该层级的实验刺激；
- 应限制为实例级还是可进入类别级比较。

专家只决定有效性和边界，不为模型直接填写“美感真值”。

### 9.3 轻量工作台

首版不建设专家账号系统。实现：

- 版本化、去敏、可离线的 review package；
- 只读来源/候选并排查看、缩放和差异叠加；
- 结构化审核表和明确不适用；
- 独立导出/导入、签名哈希和冲突报告；
- 统一工作台显示汇总状态，但不暴露受限来源给无权访问者。

联系专家、发送材料或收集真实审核属于 `GATE-EXPERT`，需要用户批准。

## 10. 与其他研究线的接口

### 10.1 与 TASK-01

- 所有资产和许可证由资产系统拥有；
- 本任务提交字符覆盖、书体分类和专家审核决定；
- 通过后由 TASK-01/公开服务冻结 `stimulus_id`，不在本任务私建刺激编号。

### 10.2 与 TASK-02

- 视觉测量消费通过审核的轮廓/mask/灰度表示；
- C1–C5 默认 `within_script_only` 或 `protocol_dependent`；
- 原始特征不可因专家期望而修改；专家只标记构念和适用性；
- “气韵”只通过低层代理进入探索模型。

### 10.3 与 TASK-03

- 提供同内容跨实例的冻结候选和 label condition；
- 普通参与者看不到专家归属答案或历史说明，除非处于单独 contextual 条件；
- 专家术语量表不直接复制给普通参与者；
- 问卷分配按作品/字体实例分组，避免伪重复。

### 10.4 与 WP2 社会叙事

- `style_id` 及审核别名投影到 object map，原词形与规范对象分开；
- “小篆＝权威”等只进入 `cultural_narrative`/association claim；
- 叙事系统不得根据 style 词命中自动确认具体图片书体；
- 历史知识与公共话语可互相链接，但保留不同证据类型。

## 11. 建议模块与 CLI

建议结构：

```text
schema/
  han_style_concept.schema.json
  han_glyph_instance.schema.json
  han_knowledge_claim.schema.json
  expert_review.schema.json
src/glyph_features/han_style_system/
  ontology.py
  sources.py
  glyphs.py
  review.py
  stimuli.py
  export.py
configs/
  han_style_protocol_v1.yaml
data/fixtures/han_style_system/
```

最低 CLI：

```text
glyph-han validate-ontology
glyph-han import-claims
glyph-han validate-glyphs
glyph-han build-review-package
glyph-han import-reviews
glyph-han build-stimulus-candidates
glyph-han export-handoff
```

所有命令 no-overwrite、输入/配置哈希、失败记录和明确退出码。自由文本术语不能绕过 registry 直接进入已验证对象。

## 12. 实施阶段

### 阶段 A：本体与证据规范

- 固定对象层级、关系、别名和不确定性；
- 迁移现有 style family 时保留语义差异；
- 用少量公开领域知识 fixture 验证关系和来源链。

### 阶段 B：资产与字符映射

- 登记候选字体/作品/字形，不擅自扩充受限资产；
- 建立 Unicode、异体和来源定位；
- 输出缺字、fallback、许可和历史映射问题。

### 阶段 C：候选刺激

- 建立同内容矩阵和实例分层；
- 生成 `historical_source_specimen`、`digital_font_specimen` 或 `controlled_comparison_stimulus` 候选及差异视图；
- 将最终图像表示交给 TASK-01 按 `A_layout` / `B_shape` / `C_ink` 登记，并另行记录 `bbox_height_matched` / `ink_area_matched` 等 render profile；不得另创 `natural` / `controlled` 表示枚举；
- 不通过专家审核前保持 `candidate`。

### 阶段 D：专家审核准备

- 生成独立 review package、说明、rubric 和导入器；
- 用 synthetic reviews 测试冲突和裁决流程；
- 到达真实专家步骤时触发 `GATE-EXPERT`。

### 阶段 E：交接

- 仅审核通过的对象可进入 pilot-ready 清单；
- 实例不足的类别明确限制推断；
- 生成知识、刺激、审核、权利、QC 和 handoff 摘要。

## 13. 自动测试与验收

### 13.1 自动测试

至少覆盖：

- style、font、glyph、work 和 claim ID 唯一性与外键；
- 循环分类、非法关系、未知别名和歧义别名；
- 一条核心断言缺来源/定位/证据片段时不能验证；
- 简繁/异体/Unicode 映射和未映射状态；
- fallback、缺字、variable axis 和静态实例哈希；
- 原件、描摹、数字字体和生成候选不可混类；
- 同一作品多个字符的 cluster/group ID；
- 两位专家审核独立性、导入签名、冲突和裁决保留；
- 未审核/分歧/权利阻断不能进入正式刺激；
- 文化联想不能写入形式事实字段；
- object map 投影保留规范 ID 和原始词；
- no-overwrite、篡改检测、部分失败退出码。

### 13.2 最低可执行验收

1. 八类目标书体均可在本体中无歧义表达，即使部分没有可发布字形；
2. 书体、字体、字形、作品、历史断言、文化联想和专家审核为不同对象；
3. 每条已验证知识断言可追溯到来源和精确证据定位；
4. 一个许可明确的小型 fixture 可走完资产登记、字形映射、候选刺激、双审核模拟、视觉测量接口和 handoff；
5. 类别实例不足时，系统机械标记 `instance_level_only`，报告不得生成书体总体结论；
6. 真实 expert review 默认未执行，状态如实显示并触发门禁；
7. WP2 object map、TASK-02 特征和 TASK-03 问卷都能引用同一 `style_id`/`stimulus_id`；
8. 专家分歧和失败样本保留，不因追求完整矩阵被静默替换；
9. 所有真实/派生资产有权利层级和 SHA-256，未知许可不进入 release；
10. 全仓测试通过，文档明确当前能支持实例级还是类别级推断。

## 14. 对 TASK-05 的交接

`handoff_manifest.json` 至少包含：

- style ontology 和 alias registry 版本；
- glyph/work/font/stimulus 的稳定关系；
- 已验证与候选知识断言及证据等级；
- 专家审核原始记录、汇总状态和门禁；
- 可进入问卷/视觉分析的刺激清单；
- `instance_level_only` 与类别可推断状态；
- 权利、缺失、争议和不适用原因；
- 给社会叙事 object map 的规范投影；
- API/导出路径、哈希和记录数。

## 15. 强制停止条件

出现以下任一情况必须停止相关切片：

- 需要联系专家、发送受限材料或代替专家作通过决定；
- 需要下载/公开权利不清的字体、拓片或扫描；
- 需要用现代字体名替代历史归属证据；
- 无法确认字符身份、异体或来源却准备进入正式刺激；
- 每类只有一个实例却准备报告书体类别效应；
- 需要把公共文化联想写成历史事实；
- 需要改变冻结视觉测量来迎合书体预期；
- 用户未提交修改无法安全保留。

停止时提交总蓝图规定的最终报告、专家/权利门禁包和 `handoff_manifest.json`，不自动进入真实问卷或最终结论。

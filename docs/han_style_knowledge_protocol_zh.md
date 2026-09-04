# TASK-04 汉字书体知识与专家在环协议

版本：`1.0.0`

## 1. 范围

本协议管理八类书体概念、字符身份映射、字形实例、证据断言、离线专家审核包、受控候选和跨系统 adapter。它不根据字体文件名证明历史归属，不让 synthetic review 代替专家，不把文化联想写成历史事实，也不在 TASK-04 分配正式 `stimulus_id`。

对象必须保持分层：

- `style_concept`：历史书体、书家风格、印刷类别或现代数字类别的受控概念；
- `font_instance`、`work`、`glyph_instance`：数字字体、作品和字符级实例；
- `han_knowledge_claim`：可回到 `source_id`、精确定位和证据片段的断言；
- `association_claim`：公共话语中的文化联想，不等于形式或历史事实；
- `expert_review`：不可覆盖的独立审核记录；
- `han_stimulus_candidate`：等待 TASK-01 冻结的候选，不是正式刺激。

## 2. 固定契约

- `schema/han_style_concept.schema.json`：八类书体及受控别名。
- `schema/han_character_mapping.schema.json`：content set、Unicode、异体和替换状态。
- `schema/han_glyph_instance.schema.json`：来源、作品/字体、A/B/C 表示、结构、权利和归属状态。
- `schema/han_knowledge_claim.schema.json`：历史、形式、协议边界和文化联想证据。
- `schema/han_review_package.schema.json`、`han_review_item.schema.json`、`expert_review.schema.json`：盲化包、条目和签名审核。
- `schema/han_stimulus_candidate.schema.json`：render profile、审核、权利、推断范围和 TASK-01 冻结状态。
- `schema/han_adapter_record.schema.json`：TASK-01/02/03 与 WP2 的显式适配层。
- `schema/han_handoff_manifest.schema.json`：implementation commit、工件、三档 readiness 和门禁交接。

配置入口是 `configs/han_style_protocol_v1.yaml`。文件使用 JSON 语法以便标准库解析，不引入新依赖。

## 3. CLI

```text
glyph-han validate-ontology
glyph-han import-claims
glyph-han validate-glyphs
glyph-han build-review-package
glyph-han import-reviews
glyph-han build-stimulus-candidates
glyph-han export-handoff
glyph-han validate-handoff
```

所有写命令使用排他创建或 staging-directory rename，不覆盖已有输出。`--dry-run` 不写文件；记录级失败可写入 `--failure-output` JSONL。退出码固定为：

- `0`：命令和全部记录成功；
- `1`：记录级部分失败，合法记录可保留；
- `2`：参数外的命令级、输入或验证操作失败；
- `3`：目标或 failure output 已存在，拒绝覆盖。

claims 模板为 `data/templates/han_knowledge_claims.csv`；审核模板为 `data/templates/han_expert_reviews.csv`。自由文本术语不能绕过 ontology、source registry 或字符映射进入已验证对象。

## 4. 字符和证据

字符映射必须与版本化 content set 的冻结文字逐项一致，并显式保存 Unicode code point、简繁/异体关系、历史映射状态和替换理由。缺字、fallback、现代化重构或身份不确定均阻断正式候选，不得静默替换。

每条已验证 claim 必须有 `source_id`、`source_locator` 和 `evidence_span`。翻译与原文分列；AI 抽取只能处于候选或待复核状态。`association_claim` 的 relation 受限于话语观察，不得改写为 `historically_is` 等历史事实关系。

## 5. Review package

`build-review-package` 仅接收权利允许的本地资产。包使用 staging 目录生成，包含：

- 去敏、随机排序的 `items.jsonl`；
- 浏览器可显示的 PNG/JPEG/GIF/WebP 预览，其他可解码格式转为 PNG；
- 本地 `index.html` 并排、缩放和叠加工作台；
- 带 package ID 和 content SHA-256 的 CSV 模板；
- package manifest 与文件 checksums。

导入时重新验证全文件 checksum 集合，以及 item manifest、工作台、模板和每个预览资产的规范相对路径、包目录包含关系、字节数和 SHA-256。独立审核不得看到先前答案；synthetic reviewer 必须使用 `reviewer_fixture_*`，且永远不能满足 `GATE-EXPERT`。裁决必须引用同包、同对象、已存在且决定冲突的至少两条独立审核；原始记录不会被删除或覆盖。

## 6. 候选与推断

候选固定输出 `bbox_height_matched` 与 `ink_area_matched` profile，引用 TASK-01 的 `A_layout`、`B_shape`、`B_shape_mask`、`C_ink`，不发明新的表示枚举。正式冻结要求同时满足字符身份、书体归属、结构 QC、映射、真实专家双审和正式权利。

每类少于三个独立合格 exemplar cluster 时，系统机械输出 `instance_level_only` 和 `INSUFFICIENT_INDEPENDENT_EXEMPLARS`。同一作品多个字符不能增加类别级独立实例数。当前 reference run 只有一个 CC0 抽象 fixture，因此只能验证工程行为，不能支持字符、书体或审美结论。

## 7. Adapter 边界

- TASK-01：接收候选、表示和 render profile；正式 `stimulus_id` 只能由 TASK-01 冻结。
- TASK-02：只消费通过授权的表示；C1-C5 保持 `within_script_only` 或 `protocol_dependent`，不得按专家期待修改原始测量。
- TASK-03：等待正式 `stimulus_id`、权利和真实专家门禁；blind/contextual 条件分离，并按 work/font/exemplar cluster 防止伪重复。
- WP2：投影规范 `style_id` 与审核别名，同时保留观察到的原词形；词命中不能确认图片书体，文化联想仍属于 narrative evidence。

adapter 中 `TARGET_IMPLEMENTATION_NOT_AVAILABLE_AT_CHECKPOINT` 表示只对任务书中的书面契约编程，未读取并行 worktree。所有未证明字段留在 `blocking_reasons` 和 handoff 的 `integration_requests`。

## 8. Handoff 与门禁

`export-handoff` 只能在 clean worktree 上运行，且要求完整 40 位 implementation commit。它使用 Git blob 复验 producer 及所有 implementation-bound 输入/输出，生成 manifest、checksums、TASK-04 报告和以下 blocked packet：

- `GATE-EXPERT`：联系专家、发送材料和收集真实审核前审批；
- `GATE-RIGHTS`：历史作品、数字化版本、描摹和现代字体的用途/再分发审批；
- `GATE-TERMS`：登录、付费、接受条款或首次受限下载前审批。

严格 validator 复验 schema、规范相对路径、文件包含关系、SHA-256、记录数、implementation commit blob、checksums 集合、审核签名、门禁状态、TASK-01 ID 所有权和 `instance_level_only`。reference handoff 必须如实保持：

```text
engineering_ready=true
pilot_ready=false
research_validated=false
```

任何真实专家、受限资产、外部条款或正式研究步骤都在相应 gate 停止，不由 Agent 自动改为 passed。
# TASK-04 汉字书体知识与专家在环协议

版本：`1.1.0`

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
- `schema/han_style_trust_root.schema.json`：fixture reviewer、本地审核授权、真实专家 approval、accepted batch 和 claim 人工决定的固定 registry。

配置入口是 `configs/han_style_protocol_v1.yaml`。文件使用 JSON 语法以便标准库解析，不引入新依赖。
固定 trust root 是 `configs/han_style_trust_root_v1.json`，读取器同时固定其仓库路径和完整 SHA-256；CLI 参数、review row、claim 或 handoff manifest 均不能替换它。当前 registry 只登记 synthetic fixture reviewer 和本地 fixture 授权，`expert_gate_approvals`、`accepted_review_batches` 与 `claim_human_decisions` 均为空。

`1.1.0` 对 `1.0.0` 非向后兼容：review package/item、expert review、claim、candidate、adapter 和 handoff 增加必填的 trust、lineage、decision 或 compatibility 字段。读取器必须按 `schema_version` 分派，不能用默认值把旧记录静默提升为 1.1。

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

每条已验证 claim 必须有 `source_id`、`source_locator` 和 `evidence_span`。`subject_type/subject_id` 与 `object_type/object_id` 必须能回到 style、glyph、work、font 或 candidate registry；有文本对象时显式使用 `object_value`。翻译与原文分列；AI 抽取只能处于候选或待复核状态。`association_claim` 的 relation 受限于话语观察，不得改写为 `historically_is` 等历史事实关系。

`verification_status=human_verified` 同时要求 `human_reviewer_id` 和 `human_decision_id`，decision 必须存在于固定 trust root，并逐项绑定 `claim_id`、reviewer 与 source locator/evidence span 的 SHA-256。调用者传入的 decision 字典没有信任效力，即使字段完全匹配也返回 `HAN_CLAIM_HUMAN_DECISION_SOURCE_UNTRUSTED`。当前没有任何受信 claim 人工决定。

## 5. Review package

`build-review-package` 仅接收权利允许的本地资产。`open_fixture` 可以复制到 fixture package；`research_local_only` 必须由固定 registry 授权 source 和 rights tier，目录/文件权限分别收紧为 `0700/0600`，且 `redistribution_status=prohibited`。包使用 staging 目录生成，包含：

- 去敏、随机排序的 `items.jsonl`；
- 浏览器可显示的 PNG/JPEG/GIF/WebP 预览，其他可解码格式转为 PNG；
- 本地 `index.html` 并排、缩放和叠加工作台；
- 带 package ID 和 content SHA-256 的 CSV 模板；
- package manifest 与文件 checksums。

导入时重新验证全文件 checksum 集合，以及 item manifest、工作台、模板和每个预览资产的规范相对路径、包目录包含关系、字节数和 SHA-256。每条 review 绑定 `package_id`、package content SHA-256 和 `review_item_id`。独立审核不得看到先前答案；通过至少要求两名 reviewer、配置指定的实质维度覆盖，以及历史/文字学与书法/设计两个角色组覆盖。全 `not_applicable`、同角色双审或未满足维度覆盖均不能通过。

synthetic reviewer 必须在固定 trust root 登记，且永远不能满足 `GATE-EXPERT`。真实 review 除受信 approval 和 reviewer scope 外，还必须命中固定 registry 中绑定 package、content SHA-256 与整批 review 文件 SHA-256 的 accepted batch。裁决必须由已授权第三人引用同包、同对象、同 origin、已存在且决定冲突的完整独立审核集合；原始记录不会被删除或覆盖。

## 6. 候选与推断

候选固定输出 `bbox_height_matched` 与 `ink_area_matched` profile，引用 TASK-01 的 `A_layout`、`B_shape`、`B_shape_mask`、`C_ink`，不发明新的表示枚举。正式冻结要求同时满足字符身份、书体归属、结构 QC、映射、真实专家双审和正式权利。权利状态只从严格验证的 TASK-01 handoff 中解析：handoff snapshot、声明 output path/SHA-256、Git blob 和 rights record schema 必须一致；单独传入 rights JSONL 只能得到 `standalone_untrusted`。

类别独立性不信任调用者填写的 `exemplar_cluster_id`。系统以 parent glyph、work、source、font、static-instance hash 和 primary asset 的并集关系推导 `lineage_unit_id`；任何共享锚点都会合并为同一 lineage unit。每类少于三个通过全部 formal 条件的独立 lineage unit 时，机械输出 `instance_level_only` 和 `INSUFFICIENT_INDEPENDENT_EXEMPLARS`。

candidate Python API 在使用前验证 mapping、glyph、review 与 rights schema。只有 ontology、source、asset、claim 和 content-set 完整输入图也通过外键与资产关系验证时，才允许形成 formal-ready candidate；缺少完整图只可运行 fixture 流程，并增加 `INPUT_GRAPH_UNVERIFIED`。当前 reference run 只有一个 CC0 抽象 fixture，因此只能验证工程行为，不能支持字符、书体或审美结论。

## 7. Adapter 边界

- TASK-01：接收候选、表示和 render profile；正式 `stimulus_id` 只能由 TASK-01 冻结。
- TASK-02：只消费通过授权的表示；C1-C5 保持 `within_script_only` 或 `protocol_dependent`，不得按专家期待修改原始测量。
- TASK-03：等待正式 `stimulus_id`、权利和真实专家门禁；blind/contextual 条件分离，并按 work/font/exemplar cluster 防止伪重复。
- WP2：投影规范 `style_id` 与审核别名，同时保留观察到的原词形；词命中不能确认图片书体，文化联想仍属于 narrative evidence。

adapter API 在投影前验证 ontology/candidate schema、candidate ID 唯一性和 style 外键。TASK-01 `ready` 还要求 source record、formal review passed、formal rights passed、evidence-supported mapping、`eligible_for_task01_freeze`、空 blocker 与未分配 `stimulus_id` 同时成立；单独自述 `ready_for_request` 会降级为 blocked。

adapter 中 `TARGET_IMPLEMENTATION_NOT_AVAILABLE_AT_CHECKPOINT` 表示只对任务书中的书面契约编程，未读取并行 worktree。所有未证明字段留在 `blocking_reasons` 和 handoff 的 `integration_requests`。

## 8. Handoff 与门禁

`export-handoff` 只能在 clean worktree 上运行，且要求完整 40 位 implementation commit。它使用 Git blob 复验 producer 及所有 implementation-bound 输入/输出，生成 manifest、checksums、TASK-04 报告和以下 blocked packet：

- `GATE-EXPERT`：联系专家、发送材料和收集真实审核前审批；
- `GATE-RIGHTS`：历史作品、数字化版本、描摹和现代字体的用途/再分发审批；
- `GATE-TERMS`：登录、付费、接受条款或首次受限下载前审批。

严格 validator 不把“每个文件的 SHA-256 都正确”视为业务一致。除 schema、规范相对路径、文件包含关系、记录数、implementation commit blob、checksums 集合和审核签名外，它还要求：

- protected output 均为 implementation-bound，固定 trust-root input 指向规范路径；
- next-task entrypoint 和 quality-gate evidence 指向 manifest 声明的 output；
- 从 content set、source、asset、ontology、mapping、glyph、claim、review package/reviews 与 TASK-01 rights snapshot 重验完整外键图；
- 从受信输入重建 candidates、lineage scope、adapters 和 integration requests；
- 重算 review/inference summary、七个 quality gate 与三档 readiness，并与 manifest 逐项比较。

因此，即使攻击者同步篡改 candidate、adapter、request、manifest、artifact SHA 和 checksums，仍不能把自述 formal review/rights/freeze 变成受信状态。reference handoff 必须如实保持：

```text
engineering_ready=true
pilot_ready=false
research_validated=false
```

reference 仅允许 `synthetic_double_review=fixture_only`；`formal_expert_review`、`formal_asset_rights`、`task01_stimulus_freeze`、`category_level_inference`、`GATE-EXPERT`、`GATE-RIGHTS` 和 `GATE-TERMS` 均保持 blocked。TASK-04 不联系专家、不获取新资产、不接受外部条款，也不分配正式 `stimulus_id`。

任何真实专家、受限资产、外部条款或正式研究步骤都在相应 gate 停止，不由 Agent 自动改为 passed。
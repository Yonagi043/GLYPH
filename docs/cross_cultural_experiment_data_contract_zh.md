# TASK-03 数据契约、兼容与隐私说明

文档版本：`1.1.0`。冻结 study protocol 与 questionnaire 版本仍为 `1.0.0`。

## `human_rating` gap 与兼容策略

旧 `schema/human_rating.schema.json` 保持原样，历史 fixture 继续按旧语义验证。它不能作为 TASK-03 主记录，原因包括：Likert 声明与 0–100 宽范围并存；只有单值 `native_script`；七维评分混在一个对象；没有 questionnaire/assignment/block/presentation 版本外键；没有逐题缺失原因；没有展示资产 hash；没有 `data_origin`，因而不能机械隔离 synthetic/Persona。

TASK-03 新增 `schema/experiment_rating.schema.json` `2.0.0`，一行只表示一个 questionnaire item。Likert 1–7、Likert 1–5 与 continuous 0–100 分别使用条件范围；`null` 必须带机器可读 `missing_reason`，不得转为 0。`native_scripts` 支持多值，rating 绑定 questionnaire、assignment、block、presentation、stimulus 和实际展示 SHA-256。`data_origin` 只允许 `synthetic|real`，Persona 不在合同枚举中。

这是并列主版本，不是静默迁移。TASK-05 应按 schema/logical type 分派：旧数据继续读取 `human_rating`；新实验只读取 `experiment_rating` 2.0。两者不能无损互转，除非另建有版本、有 provenance 的迁移产物。

## 规范对象

| 对象 | Schema | 关键语义 |
|---|---|---|
| 研究协议 | `study_protocol.schema.json` 1.0 | 假设、estimand、排除、模型、功效情景、人工门禁 |
| 问卷 | `questionnaire_definition.schema.json` 1.0 | 四语 item、锚点、审核状态与 wording 版本 |
| 参与者背景 | `participant_profile.schema.json` 1.0 | 去标识、多母语/多文字、粗粒度背景 |
| 同意回执 | `consent_receipt.schema.json` 1.1 | 协议/问卷/信息页版本、呈现语言、状态与年龄资格；无签名与姓名 |
| 刺激目录 | `experiment_stimulus_catalog.schema.json` 1.0 | TASK-01 handoff、open fixture、盲化与 synthetic 边界 |
| 分配 | `experiment_assignment.schema.json` 1.0 | seed、quota snapshot、block、trial 顺序与恢复 |
| 呈现事实 | `presentation_event.schema.json` 1.0 | 预期/实际 hash、timing、viewport 与原始 attention response |
| 逐题评分 | `experiment_rating.schema.json` 2.0 | 量表范围、缺失语义、item/construct/version 外键 |
| 质量决定 | `quality_decision.schema.json` 1.0 | 版本化、保留历史、只按预注册规则决定 |

`glyph-experiment build-reference` 会从冻结 config 与许可 fixture 生成一套逐 schema 验证的 synthetic bundle。`data/templates/experiment_system_v1/` 是填写示例；`data/fixtures/experiment_system/reference_v1/records/` 是测试和下游 fixture。两者都不得冒充真人记录。固定 reference 与运行时导出均包含 profile、consent、assignment、presentation、rating 和 quality decision 六类记录及内容寻址 manifest。

当前浏览器会收集并持久化 schema-valid 的完整 synthetic `participant_profile` 与 `consent_receipt`，和 assignment 在同一个 session allocation 事务中建立；刷新或进程重启后恢复 profile、consent、下一个 trial 与最新 quality decision。该数据链验证的是工程契约，不是可审计的真人同意：runtime 没有参与者认证、撤回身份核验、联系/补偿分区或授权会话。系统不得据此声称已完成真人 consent flow。

## 外键与事务边界

Store 在事务前验证 event/rating schema，并核对 study、questionnaire、assignment、block、participant、presentation、stimulus、trial index、data origin 与展示 hash。每个 accepted presentation 必须精确包含冻结问卷的 7 个必答 Likert item：`item_aesthetic`、`item_premium`、`item_modern`、`item_trustworthy`、`item_visual_clarity`、`item_recognition`、`item_unfamiliarity`。缺项、额外注入当前未呈现的可选 `item_brand_fit`、重复 item、未知 item、construct/scale 不符、未分配 presentation、伪造 hash、冲突重试或任何 real payload 都稳定失败。

session allocation 与全局 quota snapshot 在 SQLite `BEGIN IMMEDIATE` 中完成。持久 `session_nonce` 对完全相同请求幂等，对冲突请求拒绝；participant 只能有一个 assignment。assignment 构造从历史记录恢复配额状态，因此并发、刷新与进程重启不会重新从内存零点分配。

SQLite 的 `system_metadata.synthetic_only` 固定为 `true`。初始化遇到其他值返回 `STORE_MODE_CONFLICT`；assignment、event 或 rating 的 data origin 非 synthetic 返回 `REAL_COLLECTION_LOCKED`。这不是人工 gate 的替代品，而是当前版本没有真实收集路径的机械事实。

## 隐私分区

```text
PII / 联系 / 补偿（本任务未实现，禁止进入 Git）
        |
        | 经批准的单向映射
        v
participant_id -> profile -> assignment -> presentation -> item rating
```

规范对象采用 `additionalProperties=false`，姓名、email、电话、地址、账号、IP、精确生日和原始设备指纹不能写入。联系、补偿、签名与映射密钥必须位于独立受限系统。真人原始响应未来只能进入 Git ignored 的 `data/raw/participants/` 或受控数据库；本任务不创建真人 fixture。

去标识 export 读取上述六类规范记录，不暴露 SQLite 私有表、联系信息、补偿信息或 session nonce。导出前逐对象扫描常见 PII key、复验 schema/外键/冻结 questionnaire 和每个 presentation 的 7 项精确集合，并校验 participant 只能对应一个 assignment。manifest 固定六类 artifact 的路径、schema、版本、记录数与 SHA-256；写入端和读取端执行相同 formal、quality 与内容绑定门禁。缺失值保持 `not_applicable`、`skipped`、`refused`、`technical_failure`，绝不零填充。

## 质量与正式用途门禁

服务端是质量决定的唯一权威。客户端提交的 `quality` 与 `attention_check` 会被丢弃；服务端只从 schema-valid profile、consent、presentation event、原始 `attention_response` 和 ratings 按冻结 rule `1.0.0` 计算结果，再将 canonical 摘要写回每条 rating。每次 accepted submission 追加一个不可变 decision，通过 `previous_decision_id` 保留全历史。bundle validator 会逐节点重算 decision、校验 source presentations、rating 摘要、链根、链接、分叉与 manifest 内容；原因不能由客户端声明，也不能由评分高低任意决定。组间排除率差异单独审计并报告，不自动掩盖某一语言或设备组。

`engineering_fixture` 允许 synthetic 去标识导出。`formal_analysis` 与 `release` 先检查 data origin；只要有 synthetic 记录即返回 `SYNTHETIC_FORMAL_EXPORT_FORBIDDEN`，即使人工 gates 被伪造为 passed 也不能绕过。当前正式刺激、真实收集、pilot-ready 和 research-validated 均为 false。

## Synthetic runtime 已知限制

浏览器产生的 `response_ms`、viewport、focus/zoom 和 `attention_response` 是客户端原始事实声明；服务端能决定如何解释并防止客户端伪造最终 quality，但当前没有 challenge/receipt、可信时钟或独立 runtime 证明这些原始遥测来自真实呈现。synthetic session 也没有认证或提交授权，知道本机 session 数据的一方可构造请求。这两项不影响离线工程 fixture 的契约验收，但都是任何真人 pilot 的明确 blocker；不得用“服务端权威”表述掩盖原始输入真实性边界。
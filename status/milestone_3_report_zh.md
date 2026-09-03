# GLYPH 里程碑 3：YouTube 真实接入阶段报告

版本：1.2.0<br>
日期：2026-09-02<br>
状态：M3 进行中；v0.2.0 真实 calibration discovery 已完成；等待 105 条人工盲筛；不进入 M4

## 收口状态修订

本报告不再将一次零纳入 smoke/pilot 等同于 M3 最终完成。按照
`status/social_narrative_goal_prompt_v2_zh.md`，“工程链路能运行”不等于“研究链路有效”；当前
pilot 证明真实 API 与排除审计闭环，但没有证明 query 具有足够研究产出，也没有产生可进入真实
评论、双编和裁决链路的纳入视频。因此 M3 保持进行中。

离线收口新增以下机械约束：

- 晋级不再把 confirmatory query 写回 calibration scope；系统原子创建独立 scope，要求新的
	非重叠窗口和显式视频/评论/回复配额，并归档来源 scope。
- 部分通过时只携带通过 query；同一 source run/report/query 不能通过换窗口重复晋级；来源报告
	evidence revision 变化后，确认运行继续被阻断。
- calibration scope 只能手动运行一次，不能 schedule、scheduled trigger 或 retry。
- YouTube Web 启动必须先确认 run 级 search/shared 双桶预算；快照参与真实消费闸门。
- 评论阶段等待全部视频筛选明确后才开始，并按剩余视频公平分配总额度；启用评论时总额度不得
	低于全部 query 的视频候选容量。

新的冻结校准方案为
`status/milestone_3_youtube_query_calibration_proposal_zh.md` v0.2.0。用户已明确批准文件版本、
12 条 query、top-20、search=24/shared=48 和全部停止条件。唯一 run
`social_run_youtube_20260902134215_18f86349` 已完成真实 discovery：12 次 search、12 次 videos、
12 次 channels，0 评论/回复请求、0 run error；形成 105 个去重视频和 145 个带连续 query-local
rank 的 match。含 Key 服务已关闭，当前无 Key 盲筛队列为 105 条。

当前不能把这些候选自动写成“人工”决定：现有提交接口固定记录
`annotator_local01/manual_review=true`，由 AI 自动提交会伪造审核身份。故本报告保持进行中，等待
研究者本人在不显示 query identity 的 8767 工作台逐条决定。人工筛选完成前不冻结 query-yield
报告、不晋级 query、不创建或执行 confirmatory scope。

## Query-Yield 校准系统补充

在真实 pilot 的零纳入诊断后，M3 没有止于书面限制。系统新增 schema v13 query-yield 校准能力：`calibration` phase、不可变且可配置的评价政策、query 内视频候选排名、只以视频 discovery 候选为分母的逐 query 指标、Wilson 区间、`passed/failed/inconclusive` 三态、稳定盲筛队列、追加式报告、证据 revision 过期检测、API/UI 和三份导出证据。

达标 query 的晋级不是原地改 phase，也不与 calibration query 留在同一 scope。系统原子创建独立 confirmatory scope 和新的 query，保存 source calibration run、source query、report ID 和 policy version，并归档来源 scope。部分 query 失败不阻止同 run 中通过 query 晋级；失败或证据不足的 query 不能晋级，同一来源证据不能换窗口重复晋级。若源筛选随后修订，系统保留历史链但机械阻止基于过期证据的 confirmatory run 启动。

YouTube 配额同时执行当前全局日预算和不可放宽的 run 快照预算；启动接口可独立冻结本 run 的 search/shared 上限，修复了此前消费检查读取可变全局 settings、未真正执行 run 快照上限的问题。

原真实 pilot 没有可靠 query 内 rank，且每 query 只有 2 条，因此只能生成 retrospective `inconclusive` 诊断，不得回写成正式 precision@20。新的 12-query、top-20 冻结校准见 `status/milestone_3_youtube_query_calibration_proposal_zh.md` v0.2.0；现已获批并完成 discovery，当前等待 105 条人工盲筛。

主库已在一致性备份后前向迁移至 schema v13。原 pilot 的追加式 query-yield 报告为 `retrospective / inconclusive`：两条 query 均为 retrieved=2、ranked=0、include=0，原因均为 `retrieved_below_evaluation_k` 与 `rank_metadata_incomplete`，`calibration_passed_query_ids=[]`。主库仍为 3 个 run、16 条 observation；旧政策 204 units 未改写，`integrity_check=ok`。

迁移前备份为 `backup_20260902T092605Z_b97a66bc`，schema v12，SHA-256 `272ef20e4cd8ac4d1d75d6f60a780f36497f435967668976b046b8e91b82f572`。最终备份为 `backup_20260902T092624Z_66135d6c`，schema v13，SHA-256 `c8c913640cde27477c2f90c155725f16fc2cfb13b7dd703737bdcf69b6c27cca`；两者完整性均为 `ok`。

## 结论

经用户明确批准，GLYPH 严格按 `milestone_3_youtube_pilot_proposal_zh.md` v0.1.0，通过 `http://127.0.0.1:7897` 执行了一次 YouTube Data API v3 confirmatory pilot。运行完成了真实 API 接入、两阶段采集、人工视频筛选、质量检查、显式发布决定、导出和前后备份。

本次两个 query 共返回 4 个视频候选。4 个候选均不满足预登记的 Latin typography 对象—评价纳入规则，人工筛选全部排除。因此没有请求评论或回复，没有可合法形成的 gold、独立双编或裁决记录。最新质量报告为 `failed`，`release_allowed=false`。这是合法的零纳入结果，不得改写成通过的研究结果。

M3 证明的是有界真实接入和证据治理闭环可运行，不证明 YouTube 上的总体偏好、曝光量、流行度、因果关系，亦不证明 Latin typography 固有地具有 premium 或 modern 属性。

## 零纳入原因诊断

零纳入本身暴露了研究设计限制。当前证据不支持把主要原因归结为筛选规则过严：4 条候选都是明确误命中，没有一条处于对象指代或审美评价的边界状态。放宽规则会把 sigil 工具、AI 招聘、汽车词源或拉丁文阅读错误转成 Latin typography 叙事，重新引入“搜索命中即对象事实”的已修复问题。

主要限制来自检索和抽样设计：

- 时间窗只有 7 天，每条 query 只取 relevance 前 2 个结果，总候选数仅 4；这个规模适合验证工程状态机，不足以估计检索产出率或形成可发布样本。
- `search.list` 是关键词相关性检索，不是对研究构念的严格匹配器。即使 collector 确实发送了两条冻结 exact query，实际前排结果仍出现 `Latin` 词源、`modern` 泛义和完全无关内容。
- 两条 query 只覆盖 `Latin typography` 与两个审美词，没有分开测试 `Latin letterforms`、`Roman type`、`alphabet typography` 等对象表达，也没有先做独立的 query-yield 校准。
- 每 query 的 top-2 relevance 截断使排序波动主导样本；本次没有足够深度判断相关结果是否存在于后续页。

因此，本次 pilot 只能认定真实接入和治理闭环通过，不能认定 M3 已形成高质量可用研究成果。下一步必须按 v0.2.0 预登记检索校准：扩大候选深度和时间窗、将对象同义表达拆成独立不可变 query、报告每条 query 的 precision@k，并继续在全部视频筛选冻结后才请求评论。该工作需要新的真实请求批准，不能用本次授权自动执行。

## 批准与边界

- 用户授权：明确批准 v0.1.0 冻结提案，经 7897 执行一次 pilot；不扩大范围，不进入 M4。
- 平台：YouTube Data API v3 公共数据；未使用 OAuth 或用户数据权限。
- 凭据：Key 由本机 macOS 钥匙串直接注入单次进程；日志、仓库、URL、manifest、raw evidence 和导出均未显示 Key。
- 代理：运行进程的 `outbound_proxy_configured=true`，目标为本机 `127.0.0.1:7897`。
- 调度：运行前后 YouTube schedule enabled=0；仅创建一次手动 run，未自动重试。
- 真实服务：仅在执行期间监听 `127.0.0.1:8765`；完成后已关闭并确认端口释放。无 Key 的 fixture UI `8766` 不构成真实研究证据。

## 冻结设计

| 项目 | 实际冻结值 |
|---|---|
| Scope | `scope_youtube_3599c19252277528` |
| Run | `social_run_youtube_20260902085203_382c800b` |
| 对象 | `writing_system / latin` |
| 语言 | `en`；平台语言提示不解释为作者身份或国籍 |
| UTC 窗口 | `2026-08-26T00:00:00Z` 至 `2026-09-02T00:00:00Z` |
| Query 1 | `q_youtube_3599c19252277528`；`"Latin typography" premium` |
| Query 2 | `q_youtube_680b3fe88fba7b50`；`"Latin typography" modern` |
| Query family / phase | `object_aesthetic / confirmatory` |
| 视频上限 | 每 query 2；最多 4 个 query-video 命中 |
| 评论线程 / 回复 | 每纳入视频最多 5 线程；每线程最多 2 回复 |
| 评论/回复运行上限 | 20 条，不是 per-query 上限 |
| Search 桶 | 2 calls/day |
| Shared 桶 | 25 units/day |
| 排序 | YouTube relevance；随不可变 query 快照保存 |

Query 1 的配置 SHA-256 为 `b377d27707300b58ac95c1cdfbe8bb1607ecce814572abb059dea95d4eaef697`；Query 2 为 `dec8a44d6da22720de60b0f46e895a40104d86368254d6949c0ba07ffc646569`。两条 query 共用 object map v0.1.0 和 codebook v0.1.0：

- object map SHA-256：`fef8182bc3e5922eaa64a59418ea4777a6b47532aef592cf350c80bbf1595c33`
- codebook SHA-256：`df8637e03607876b2c8399c0d58a641bd762ab6f836dde2096aec604962e1584`

## 运行证据

### 请求与配额

发现阶段完成后，run 自动停在 `awaiting_screening`。逐请求 quota event 为：

| Operation | 次数 | 桶 | 结果 |
|---|---:|---|---|
| `search.list` | 2 | `search_calls` | 2 次 success，达到 2/2 上限 |
| `videos.list` | 2 | `shared_units` | 2 次 success |
| `channels.list` | 2 | `shared_units` | 2 次 success |
| `commentThreads.list` | 0 | `shared_units` | 未调用 |
| `comments.list` | 0 | `shared_units` | 未调用 |

最终 shared 使用量为 4/25 units，search 使用量为 2/2 calls。运行没有认证、权限、quota、4xx、5xx 或响应结构错误，`failure_count=0`。

### 分层分母

| 分母 | 数量 |
|---|---:|
| Search results | 4 |
| Video details | 4 |
| Video candidates / observations | 4 |
| Query matches | 4 |
| Screening include | 0 |
| Screening exclude | 4 |
| Comment threads seen | 0 |
| Top comments inserted | 0 |
| Replies seen / inserted | 0 / 0 |

两个 query 没有命中同一视频，因此本次真实样本没有触发重叠视频去重分支；该分支仍由离线 fixture 测试覆盖，不能把 fixture 覆盖冒充真实重叠样本证据。

### 人工筛选

| 视频 | 命中 query | 决定 | 理由摘要 |
|---|---|---|---|
| `VIA7SQhyF4E` | premium | exclude | 讨论 modern sigil/icon 生成工具；modern 修饰图标与赛博审美，未明确评价 Latin typography。 |
| `Yv8nKwQJQec` | premium | exclude | AI 工程招聘与职业访谈；未讨论 Latin typography。 |
| `QDSNBfZBS2g` | modern | exclude | 汽车活动；Latin 是词源，modern 修饰其他语境。 |
| `4p0-j2Dc4vU` | modern | exclude | 拉丁文修辞阅读；没有 typography 的 premium/modern 审美评价。 |

导出保存 8 条 screening events：4 条机器 `uncertain` 建议和 4 条人工 `exclude` 决定。人工决定均使用 `social_screening_v0.1.0` 并保存理由。零 include 后继续同一 run，状态机未请求评论，直接完成运行。

### 双编、裁决与质量

因为 `eligible_count=0`，不存在可合法双编的 observation：

- independent annotations：0
- adjudications：0
- object label alpha：不可定义，unit count=0
- stance alpha：不可定义，unit count=0
- latest quality status：`failed`
- blockers：`no_screening_includes`、`agreement_below_0.80`

系统先保存首份 failed 报告。后续 provenance 修复改变 evidence revision，首份报告自动成为 stale；复评保存第二份 failed 报告，最新报告与当前 evidence revision 一致。

显式治理决定为 `release_allowed=false`：零纳入、无可双编记录，维持阻断，不发布、不作总体推断。质量失败没有被导出成功或工程测试覆盖。

## Pilot 发现的 Provenance 缺陷

首次导出核验发现：不可变 query 快照、run manifest 和 `observation_query_matches` 的 query ID 均正确，但 4 条 observation 的 `query_text` 被规范化器写成 scope 关键词的 OR 拼接，而不是各自的 exact query。这触发了冻结方案的 query 一致性停止条件。该缺陷不是 4 条记录各自的数据错误，而是共享 `ResearchScope` 缺少 exact-query 传递造成的系统性规范化缺陷；当 `exact_query` 与关键词拼接不同时，YouTube 视频、评论、回复和 Bluesky 帖文都可能受影响。

发现后没有发起任何新 YouTube 请求，也没有重跑 pilot。处理分为两部分：

1. 根因修复：`ResearchScope` 现在携带 `exact_query`，Bluesky/YouTube 规范化器优先写入该值；服务和 collector 从冻结 run 快照传递该字段。两个生产入库路径新增运行时不变量，query ID 或 `query_text` 与 run-bound exact query 不一致时直接拒绝写入。
2. 真实数据修复：仅从既有不可变 query 快照和 query-match 离线回填 4 条 observation，重算 `record_sha256`，执行 schema 校验，并保存 4 条前后 review history 与 4 条 `observation_query_provenance_repaired` 审计事件。

修复后对真实主库全部 16 条 observation 执行审计，16/16 满足 `query_text == immutable exact_query`。其中只有本次 4 条因触发条件成立而需要改值；历史 12 条的 exact query 原本就等于旧回退文本，因此不应为制造修复记录而改写。备份作为不可变审计点不做原地修改。新增回归覆盖旧 run 快照、两条不同 exact query 的多 query observation、重叠 query-match、Bluesky 规范化，以及错误 query provenance 的入库拒绝。没有修改平台原始响应、query ID、筛选决定或请求计数。

## 导出与备份

最终导出目录：`data/processed/social_narrative_v0/exports/social_run_youtube_20260902085203_382c800b/`<br>
最终 ZIP：`data/processed/social_narrative_v0/exports/social_run_youtube_20260902085203_382c800b.zip`<br>
当前 ZIP SHA-256：`0b5552e26b05cd1c8aae2ee6ee3a0de3fd21217baa5abc036393ffb42f732253`

ZIP 完整性检查无错误，`validation.json.valid=true`。当前包包括 2 条 query、4 条 observation、4 条 source、4 条 query-match、8 条 screening、4 条 provenance repair review、2 条质量报告、1 条 retrospective query-yield 报告、冻结 query-yield policy、当前 calibration 快照、0 条独立编码和 0 条裁决。四条 `candidate_not_final` warning 与零纳入一致；`mixed_input_hashes` 表示有意合并两个预登记 query 的输入证据，不是 schema error。v13 前的 ZIP SHA-256 `f03b6a63f5ba257a2c44143d443ab7b83641437c63f1cf325f5e4bd94b9ffdcf` 保留为历史交付锚点。

| 备份 | 阶段 | SHA-256 | 完整性 |
|---|---|---|---|
| `backup_20260902T085019Z_0ab7ecf2` | pre-run schema v12 | `a754be41f869a5e67cce7a96d5313bbc2b77589c01f3dc4ab34c06bad26acd1c` | `ok` |
| `backup_20260902T085433Z_52481053` | post-run、provenance 修复前审计点 | `90f9848f1b67a4b8a89f82656d80024d89c362dd952935be22f4c3016371594c` | `ok` |
| `backup_20260902T085753Z_1025241e` | 最终 post-repair | `2679401b7eabdc3545ad225fd27e112f0d1d096d3e0940d2e8b64e1a5e8341f8` | `ok` |
| `backup_20260902T092605Z_b97a66bc` | pre-schema-v13 query-yield | `272ef20e4cd8ac4d1d75d6f60a780f36497f435967668976b046b8e91b82f572` | `ok` |
| `backup_20260902T092624Z_66135d6c` | post-schema-v13 query-yield | `c8c913640cde27477c2f90c155725f16fc2cfb13b7dd703737bdcf69b6c27cca` | `ok` |

最终备份为 schema v13，包含 3 个 run、16 条 observation 和 1 条 retrospective query-yield 报告。两个历史 YouTube run 仍为 `engineering_only / analysis=false / release=false`；历史 12 条 observation、6 条旧 quota event 和 204 legacy units 未改写。

## 验收结论与限制

已验证：

- 官方 API、钥匙串凭据、统一代理和双桶配额在真实请求上可工作；
- 多 query 顺序、run-bound 快照、registry 哈希和 query-match 可导出审计；
- 视频筛选前没有评论请求，零纳入时评论阶段保持零请求；
- 离线 fake-client 回归验证全部视频筛选未冻结时评论请求为零，冻结后总额度跨纳入视频公平分配，且不合法的评论容量设计在 run 启动前阻断；
- 真实人工筛选、质量 blocker、stale evidence 防护和显式 release=false 可落盘；
- 导出 ZIP、pre/post 备份和历史 engineering-only 隔离均通过检查；
- 真实 pilot 暴露的 exact-query provenance 缺陷已在无重请求条件下修复并形成回归测试。

本轮最终离线验证为全仓 95 passed，`node --check`、YAML 解析、184 天留出窗口等长断言、
`git diff --check` 和触及文件编辑器诊断全部通过。真实主库只读复核为 schema=13、
`integrity_check=ok`、3 runs、16 observations、12 quota events、1 query-yield report；旧政策仍为
6 events / 204 units。无 Key、无代理的最新代码服务运行在 `http://127.0.0.1:8767`，active run=0、
enabled schedule=0；桌面与移动质量页无控制台/页面错误和全局横向溢出。预算对话框读取后取消，
run 数仍为 3。该验收没有发起新增 YouTube 请求。

未被本次真实样本验证：重叠视频的真实去重、评论/回复真实采集、真实双编一致性与第三人裁决。这些分支有离线 fixture 覆盖，但因本次零纳入不得声称已完成真实研究验收。不得为了覆盖这些分支扩大 query 或重发请求。

M3 当前停在真实 calibration 的人工盲筛门禁：discovery 与证据备份已完成，但尚未达到最终完成定义。当前没有可发布研究结果，也不自动进入 M4；人工筛选后才可冻结 query-yield 报告，后续 confirmatory 真实运行及任何 M4 工作仍分别需要与冻结设计绑定的新批准。
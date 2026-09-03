# GLYPH 里程碑 3：YouTube 小规模真实 pilot 冻结提案

版本：0.1.0<br>
日期：2026-09-02<br>
状态：已获用户明确批准并执行；零纳入，研究发布阻断<br>
适用范围：M3 YouTube 真实接入；不进入 M4

> 历史状态说明（2026-09-02）：本文件保存已执行 pilot 的原始冻结设计和授权边界，
> 不再是待执行提案，也不授权任何新请求。当前 M3 门禁见
> `status/milestone_3_youtube_query_calibration_proposal_zh.md` v0.2.0。

## 批准边界

本文件只冻结待执行方案，不表示已经批准，也不触发任何网络请求。只有用户明确批准本文件的版本和参数后，才允许通过 `http://127.0.0.1:7897` 发起请求。批准不得通过测试通过、已配置密钥、按钮可用或历史 run 推定。

批准后仍不得在聊天、仓库、日志、URL、manifest、raw evidence 或导出包中显示 API key。密钥只由研究者在本机环境或本机 secret manager 配置，系统界面只显示布尔状态。

## 冻结研究范围

| 项目 | 冻结值 |
|---|---|
| 平台 | YouTube Data API v3 |
| 数据用途 | confirmatory pilot；仅验证真实接入和研究工作流，不做总体推断 |
| 对象 | `writing_system / latin` |
| 语言层 | `en`；平台语言提示不是作者身份或国籍 |
| UTC 窗口 | `2026-08-26T00:00:00Z` 至 `2026-09-02T00:00:00Z` |
| 排序 | YouTube search 默认 relevance；随 query 快照保存 |
| Query 1 | family=`object_aesthetic`；`"Latin typography" premium` |
| Query 2 | family=`object_aesthetic`；`"Latin typography" modern` |
| 视频上限 | 每 query 2 个；最多 4 个 query-video 命中，重叠视频去重 |
| 评论线程 | 每个纳入视频最多 5 个 |
| 回复 | 每线程最多 2 个 |
| 评论/回复运行上限 | 20 条；不是 per-query 上限 |
| Search 调用预算 | 当日最多 2 次；重试也计入事件 |
| 共享单位预算 | 当日最多 25 units |
| 调度 | 禁用；只允许一次手动 run |
| 发布默认值 | `release_allowed=false` |

这两个 query 用相同对象、不同预登记审美词测试多 query 采集和去重，不用于声称 Latin typography 固有地 premium 或 modern。返回结果是有界 relevance 样本，不是随机样本、曝光量或公众偏好。

## 执行顺序

1. 先确认真实数据库已有当日一致性备份、`integrity_check=ok`、YouTube schedule enabled=0、无活动 run。
2. 在本机安全配置 key 和 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`；任何输出只记录“已配置/未配置”。
3. 登记上述一个 scope 和两条不可变 query，核对 query family、phase、exact query、UTC 窗口、registry hash 和配额快照后再启动一次手动 run。
4. 第一阶段只执行 search/video/channel 请求并暂停；不在视频 screening 前请求评论。
5. 逐视频人工记录 include/exclude/uncertain 及理由。只有 include 视频继续评论阶段；若仍有 uncertain，run 保持暂停。
6. 继续同一个 run，采集评论和回复；核对重叠视频只请求一次评论，同时每条派生 observation 保留全部 query-match。
7. 对 screening include 记录完成人工 gold、两位编码员独立编码和必要的第三人裁决。不得将普通 review history 当作第二份编码。
8. 运行质量检查。failed 报告停止发布；passed 也保持 release=false，直到研究者另行填写治理理由并显式授权或决定继续阻断。
9. 导出并验证 run 包，创建 post-run 一致性备份；核对数据库、ZIP 和备份的记录数与证据边界。

## 立即停止条件

任一条件出现即停止，不扩大范围、不增加 query、不自动重跑：

- proxy、key 布尔状态或 API 请求目标不符合冻结方案；
- 请求将超过 2 次 search 调用或 25 个共享单位；
- 出现 `quotaExceeded`、认证/权限错误、不可解释的 4xx、连续 5xx 或响应结构不符合官方 v3 形状；
- query、时间窗、语言、排序、页 token 或 query-match 与 manifest 不一致；
- 评论在视频人工 include 前发出，或重叠视频重复下载评论；
- secret、直接作者标识或未经许可正文进入不应出现的位置；
- frozen schema、registry hash、不可变 query、审计 trigger、备份完整性或 export validation 失败；
- 历史两个 engineering-only run、12 条 observation、6 条旧配额事件或 204 units 被改写；
- 用户撤销批准。

## 必须形成的验收证据

- 一份 pre-run 和一份 post-run 备份清单，均含 SHA-256 与 `integrity_check=ok`；
- run manifest、两条 query 快照、registry 快照、quota policy 和逐请求 quota event；
- search 结果数、video detail 数、候选/纳入/排除视频数、线程数、回复数及截断说明；
- observation、source、本机 raw evidence、screening history 和 `observation_query_matches.jsonl`；
- 两份独立编码、必要裁决、字段级 alpha、质量 blockers 和显式 release 决定；
- `validation.json.valid=true` 的导出 ZIP；
- 对样本偏差、不可见缺失、relevance 排序和不可作因果/总体推断的书面限制。

真实 run 只证明官方 API 接入、证据链和工作流在这个有界样本上可用。它不因测试、alpha 或导出成功而自动成为可发布研究结果。

## 所需明确批准

可接受的授权必须明确引用本文件及版本，例如：

> 批准执行 `status/milestone_3_youtube_pilot_proposal_zh.md` v0.1.0，严格按冻结参数通过 7897 发起一次 YouTube pilot；不扩大范围，不进入 M4。

## 执行记录

- 用户于 2026-09-02 明确批准本文件 v0.1.0，要求严格按冻结参数经 7897 执行一次 pilot，不扩大范围、不进入 M4。
- 已执行 run：`social_run_youtube_20260902085203_382c800b`。
- 实际请求：`search.list=2`、`videos.list=2`、`channels.list=2`；shared 4/25 units，search 2/2 calls；评论和回复请求均为 0。
- 4 个视频候选经人工筛选全部排除，独立双编和裁决均为 0；最新质量报告 `failed`，显式 `release_allowed=false`。
- 首次导出发现 observation 的 `query_text` 未使用 exact query；已停止外部请求，从不可变 query 快照离线修复 4 条记录、重算哈希、保存前后审计，并增加回归测试。最终 4/4 observation 与 exact query 一致。
- pilot 证据、限制和备份见 `status/milestone_3_report_zh.md`。M3 未因零纳入 pilot 最终完成；当前停在 v0.2.0 query-yield calibration 的明确批准门禁，不进入 M4。
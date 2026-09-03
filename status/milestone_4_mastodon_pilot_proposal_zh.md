# GLYPH 里程碑 4 Mastodon 真实 pilot 冻结提案

版本：0.1.0
日期：2026-09-02
状态：待用户单独批准；本文件不是网络请求授权
适用范围：M4 Mastodon 最小真实平台验收

## 研究与覆盖边界

- 目标：验证已离线通过的 Mastodon 多实例采集链在真实公开 API 响应上的兼容性、分页记账、实例故障隔离、规范化、证据下钻与导出，不估计总体流量、曝光或公众意见。
- 对象目标：`object_type=writing_system`，`object_label=latin`。这些值只冻结在 query 目标中，不自动写成 observation 的研究事实。
- 查询：`#typography`。
- 语言提示：`en`。
- UTC 窗口：`2026-08-27T00:00:00Z` 至 `2026-09-03T00:00:00Z`，包含边界。
- 覆盖表述只能是“在选定实例的公开 hashtag timeline 中观察到”，不得表述为 Mastodon 全网样本。
- 不执行人工筛选、query 晋级、跨平台比较或 M5 工作。

## 冻结请求配置

| 项目 | 冻结值 |
| --- | --- |
| 实例 | `mastodon.social`、`hachyderm.io` |
| 访问方式 | `hashtag_timeline` |
| endpoint | 每实例 `GET /api/v1/timelines/tag/typography` |
| 认证 | 无认证；不设置 `GLYPH_MASTODON_ACCESS_TOKENS_JSON` |
| proxy | `http://127.0.0.1:7897` |
| 每页数量 | 20 |
| 每实例页数 | 1 |
| 总 observation 上限 | 40 |
| 逐请求间隔 | 2.0 秒 |
| 单请求 timeout | 30 秒 |
| retry | 仅 429/5xx/连接错误，最多 3 次重试；退避 1、2、4 秒 |
| HTTP 尝试总上限 | 8（2 个实例 × 每实例最多 4 次） |
| trigger | 仅手动 1 次 |
| schedule | 不创建或保持 `enabled=false` |
| token/账号 | 不收集、不输入、不导出 |

两实例的当前可达性、API 版本差异和匿名访问状态尚未通过真实请求验证。获批后的首次 timeline 请求同时承担最小可达性检查并计入上述 8 次上限；不得额外发送 `/api/v2/instance`、搜索、账号或其他预检请求。

## 停止与禁止变更

- 任一实例返回 401/403：记录 `mastodon_instance_authentication`，停止该实例；不得临时加入 token。
- 任一实例在有限重试后仍为 429/5xx/连接失败：记录实例失败，保留另一实例结果；不得放宽间隔、页数或重试上限。
- 出现 private/direct 可见性、schema 验证错误、非 JSON、非 status list、未知字段导致规范化失败或 token/凭据疑似进入日志：立即停止整个 pilot。
- 达到 40 条统一 observation、每实例 1 页、8 次 HTTP 尝试或 30 分钟本机运行上限中的任一条件即停止。
- 不得现场替换实例、查询、时间窗、endpoint、认证方式、proxy、分页或上限；任何变更必须形成新版本并重新批准。
- 不得因零命中追加 hashtag、扩大窗口或切换 `search_statuses`。

## 执行前门禁

1. 用户明确批准本提案的版本、两实例与请求预算。
2. 确认 7897 proxy 正在监听，但不以平台请求测试代理。
3. 确认主库 `PRAGMA integrity_check=ok`，schema v14，活动任务为 0，启用 schedule 为 0。
4. 创建并校验新的 pilot 前一致快照；记录 backup ID、SHA-256、schema 和 M3 冻结计数。
5. 确认环境中未设置 `GLYPH_MASTODON_ACCESS_TOKENS_JSON`，且没有真实 token 写入仓库、命令、聊天、fixture 或 Web。
6. 以本文件冻结值创建一个 Mastodon scope；创建后复核 query snapshot SHA、manifest v0.2.0 与“非全网”说明，再手动启动一次。

## 验收与报告

- 技术完整性：run manifest 和全部 observation 通过 frozen schema/hash/query/source 校验；实例状态、错误、sighting、query-match 和 raw evidence 可下钻。
- 去重：同一 canonical status 经两个实例观察时只形成一条统一 observation，并保留两条实例 sighting。
- 隐私：本地 evidence 可保留 raw status；导出 `mastodon_sightings.jsonl` 不含 raw payload、账号或 token。
- 故障隔离：实例结果分别报告。只有两个实例均完成才记为“跨实例技术通过”；一个完成一个失败记为“部分通过/不足以验收”，不得包装为全面成功。
- 零命中是有效但不充分的 pilot 结果，不追加请求。
- pilot 后再次核对 M3 冻结 run 仍为 105 条 observation、145 个 query-match、0 条 `human_verified`，并记录主库完整性、Mastodon 表计数、HTTP 尝试数和导出 validation。
- 未完成人工编码，不产出文化叙事结论；不进入 M5。

## 所需批准文本

只有用户在本提案完成后另行明确表示批准执行，例如：

> 批准执行 `status/milestone_4_mastodon_pilot_proposal_zh.md` v0.1.0，按其中冻结的两个实例、`#typography`、无认证方式和最多 8 次 HTTP 尝试执行一次真实 pilot。

在收到等价的明确批准前，不得发送任何 Mastodon 请求。

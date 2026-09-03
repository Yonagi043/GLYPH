# GLYPH 里程碑 5：受限平台离线待接入能力报告

版本：`1.0.0`<br>
日期：2026-09-02<br>
状态：M5 离线能力完成；Reddit、TikTok Research API、X 真实接入均未授权、未执行<br>
适用范围：M5，严格按 Reddit → TikTok Research API → X 执行

## 结论

M5 已在现有社会叙事统一系统内完成 Reddit Data API、TikTok Research API 和 X API v2
recent search 的本地适配器、去敏官方结构 fixture、collector、恢复状态、错误分类、预算/费用守卫、
Web、监控、导出、备份恢复和离线契约测试。三者继续使用既有不可变 query、registry snapshot、
raw evidence、candidate、query-match provenance、人工审核和 release gate，不建立平台专属研究结论路径。

本报告中的“完成”仅指离线待接入能力完成，不指平台批准或真实接入。M5 没有登录平台、没有执行
OAuth 同意、没有提交正式申请、没有接受新条款、没有配置真实凭据、没有购买 credits、没有启用
付费、没有发真实平台请求，也没有产生 Reddit、TikTok 或 X 实证样本。真实请求、真实凭据和平台
费用均为 0。

M5 没有继续 M3 的 105 条人工盲筛，没有重跑 YouTube discovery，没有执行 Mastodon pilot，也没有
进入 M6。完成本报告与最终验证后停止。

## 统一实现

- 源码 SQLite schema 为 v17。v15 新增通用受限 API 分区状态；v16 新增 TikTok UTC 日预算和逐尝试
  请求账本；v17 新增 X 日期化价格快照、billing-cycle 守卫、run 费用绑定和逐请求资源/微美元账本。
- Reddit、TikTok 与 X 均在 `create_run` 前执行平台 readiness 检查。缺凭据、固定代理或费用门禁时
  返回 422，不创建 run，不启动 collector，也不留下预算事件。
- 三个平台均使用 `http://127.0.0.1:7897` 固定代理边界。凭据只允许来自本机进程环境；Web 没有
  secret 输入框，health/monitoring 不回显 secret。
- 分页状态复用通用 `api_collection_states`，按 run/query/partition 保存 token、计数和终态。
  completed 分区幂等重入不会再次发请求；中断只恢复未完成分区。
- 所有 observation 继续保留冻结 query ID/text、registry hash、raw event 和 query-match provenance。
  规范化器不得从 scope 复制对象、评价词、角色或立场作为研究事实。
- Web 已提供六平台 selector、受限平台配置、readiness 和预算/费用监控；导出与备份恢复覆盖新增状态。
  主分析仍只读取 `human_verified` observation。

## Reddit

Reddit 实现覆盖 OAuth token provider/refresh 边界、显式且不可伪装的 User-Agent、Bearer 请求、
Listing `data.children`/`data.after`、运行时 `X-Ratelimit-*`、429/5xx 有界重试和 401 单次刷新。
collector 按冻结 subreddit/query 分区，保存字符串续页 token 与跨 run `created_utc` 高水位；单分区
403/404、连接或 malformed child 不抹掉其他分区结果。

去敏规范化区分可读、removed、deleted 和 unavailable 内容；removed 内容只保留审计哈希，不保留
伪正文。raw evidence、query match 和覆盖边界均进入统一导出。专项离线测试为 15 项；Reddit 完成时
全仓为 135 passed。没有 Reddit 登录、OAuth 同意、refresh token、真实响应或请求。

当前 Terms 与 archived API/OAuth/JSON 结构参考的核验日期为 2026-09-02。归档材料只支持 fixture
兼容契约，不构成当前配额保证；真实 pilot 前必须人工复核现行 Data API Terms、用途批准、删除义务、
User-Agent 和运行时限额。

## TikTok Research API

TikTok 实现覆盖 research client-credentials token、非嵌套条件 AST、最长 30 个 UTC 整日窗口、
视频 query、顶层评论与回复分层分页、视频 `search_id`/cursor 恢复、评论 cursor、401/429/5xx 分类和
平台 error envelope。短页只记录 `possible_unavailable_items`，不推断不可见条目的身份或内容。

本机守卫按 UTC 日期原子预留每次请求尝试，范围为 1..1000 requests/day；成功与失败尝试都进入
不可回滚账本。预算在客户端调用前耗尽时保持零网络调用，UTC 次日可从原 cursor 恢复。Web 与导出
保留冻结 AST、整日窗口、分层页数、请求事件和日预算快照。

专项离线测试为 26 项；TikTok 完成时全仓为 161 passed。没有 developer account 登录、Research
Tools 申请或批准、client secret、真实响应或请求。1000 requests/day、100 records/request 和 token
有效期等均为 2026-09-02 查得的动态文档快照，真实 pilot 必须以当日官方文档和运行时错误为准。

## X

X 实现覆盖 GET `/2/tweets/search/recent`、bearer 认证、最近七天 UTC 时间窗、query/token/字段校验、
`meta.next_token` → `pagination_token` 恢复、rate-limit headers、平台 error envelope、401 非重试和
429/5xx 有界重试。去敏 raw evidence 和 observation 不保留 `author_id`。

X 金额统一为整数微美元。当前 active snapshot 只记录 2026-09-02 查得的
`post_read=5000 microusd/resource`；它是带生效日的本机证据，不是未来价格保证。每个 run 在创建时
原子绑定价格快照、run cap、本机 billing-cycle cap、Console hard limit 确认和 cycle 时间窗；事务
故障不会留下未绑定的半成品 run。

每次请求发出前按 `max_results × frozen unit price` 原子预留最坏成本，同时检查 run 和 cycle 两级
预算。成功按实际 `result_count` 结算；明确无 resource 的失败结算为 0；请求发出后取消按最坏资源数
标记 `indeterminate`，不把不确定费用当成 0。run cap 只停止当前 run；cycle cap 打开全局 breaker；
active price snapshot 改变会阻断旧价 run，新 run 必须绑定新 snapshot。

Developer Console hard spending limit 是真实启用的外部前提，本机确认不能证明 Console 事实。
因此 Web 只显示价格、cap、已计费用、剩余额度和 breaker，不提供“确认 Console 上限”按钮。导出
包含 `x_request_events.json`、`x_run_billing_snapshot.json` 与 `x_billing_status.json`，不包含 bearer。

X 专项离线测试为 27 项。已验证 token 恢复、completed 幂等、401/429/503、逐尝试记账、run/cycle
cap、价格变化、取消最坏成本、run/billing 原子回滚、v17 迁移、备份恢复、Web 422 零 run 门禁、
monitoring 和导出。没有 Developer Console 登录、hard limit 设置、credits、bearer、真实响应或请求。

## 验证结果

| 检查 | 最终结果 |
|---|---|
| Python | 3.11.15；项目 `.venv` / `uv run` |
| Reddit 专项 | 15 项离线测试通过 |
| TikTok 专项 | 26 项离线测试通过 |
| X 专项 | 27 项离线测试通过 |
| 全仓测试 | 188 passed |
| 前端语法 | `node --check src/glyph_features/social_system/static/app.js` 通过 |
| 浏览器验收 | 1440×900 与 390×844；六平台切换、X 字段/readiness/费用、无 secret 输入、无横向溢出通过 |
| 零副作用门禁 | 缺 bearer、固定代理或 billing guard 均为 422，run 数保持 0 |
| 迁移 | v14/v15/v16→v17 与历史 schema fixture 在临时库通过 |
| 备份/恢复 | X 四张 v17 表、请求账本与费用状态在临时库通过 |
| 外部平台活动 | 请求 0；登录/申请 0；真实凭据 0；平台费用 0 |

全部自动化平台测试使用临时 SQLite、去敏 fixture、fake client/opener 和本机 ASGI/浏览器页面。
它们没有调用 Reddit、TikTok、X、YouTube 或 Mastodon，也不能替代真实平台响应验收。

## 主库不可变复核

生产主库 `data/raw/social/glyph-social.sqlite3` 没有用 v17 `ResearchStore` 打开。最终复核使用绝对
SQLite URI `mode=ro&immutable=1`，结果如下：

- `PRAGMA integrity_check=ok`，`PRAGMA user_version=14`；
- `collection_runs=4`，`observations=121`，`human_verified=0`；
- M3 冻结 run `social_run_youtube_20260902134215_18f86349` 保持 `observations=105`、
  `observation_query_matches=145`、`review_events=0`；
- `mastodon_instance_states=0`、`mastodon_scope_state=0`、`mastodon_sightings=0`；
- active run=0，enabled schedule=0；8765、8766、8767 均无监听；
- 查询前后主库 SHA-256 均为
  `0f25d887db798152d1379b2119c3f864292dd2a42cc6620de1b201a6aa49aaa3`，字节数与 mtime 未变。

因此 M5 没有迁移或回写主库，没有改变 M3 候选、人工审核、YouTube 配额、M4 表或调度状态。
源码支持 v17 与主库保持 v14 是有意的安全边界；未经单独批准和一致性备份，不得用当前服务打开
主库触发前向迁移。

## 限制

- fixture 只能证明已知响应结构、状态机和故障契约，不能证明平台资格、真实权限、当日价格、真实
  限额、响应分布或样本质量。
- 受限平台的价格、配额、资格、许可和删除义务均会变化，本文日期快照不得被写成永久承诺。
- 当前没有三个平台的真实 observation，不能报告命中率、覆盖率、叙事频率、互动比较或总体结论。
- X 本机账本是保守控制与审计工具，不能替代 Developer Console 账单；auto-recharge 不能替代 hard
  spending limit。
- 任何导出仍受权利、隐私、双人复核和 release gate 约束；candidate 不进入主分析。

## 后续批准门槛

M5 到此停止。任一真实平台 pilot 都必须另行提交冻结方案并获得用户明确批准，至少固定资格/用途、
条款核验日、query、UTC 时间窗、分页与请求上限、代理、凭据注入、停止条件、保留、删除和发布边界。

X 还必须由用户本人在 Developer Console 设置 hard spending limit，重新核验当日价格，保证本机
billing-cycle cap 不高于 Console cap，并分别批准 credits/付费、主库 v14→v17 迁移和一次手动 run。
不得自动购买 credits、启用付费、提高 cap、确认 Console 状态、重置 breaker 或启用 schedule。

这些未来事项不属于本次 M5 授权。本报告提交后不继续 M3、M4、M6 或任何真实平台操作。
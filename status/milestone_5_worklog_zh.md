# 里程碑 5 受限平台离线待接入工作记录

版本：`0.6.0`<br>
日期：2026-09-02<br>
状态：M5 离线待接入能力完成；真实平台接入均未授权、未执行<br>
适用里程碑：M5（Reddit → TikTok Research API → X）<br>
是否替代/被替代：不替代 M3/M4 记录；后续由本文件增量更新

## 事实证据

- 当前分支：`main`；HEAD：`143ed92`。
- 工作区已有大量未提交的 M1–M4 代码、测试、schema、配置和文档资产；M5 在这些资产上增量实现，不回退、不整理、不提交无关修改。
- VS Code/Pylance 与项目锁定环境均使用 `.venv/bin/python`，Python `3.11.15`。
- M5 启动基线命令：`uv run pytest -q`；结果：`120 passed in 5.05s`。
- 主库：`data/raw/social/glyph-social.sqlite3`；最终用绝对 URI `mode=ro&immutable=1` 只读核验：`PRAGMA integrity_check=ok`，`PRAGMA user_version=14`。查询前后 SHA-256 均为 `0f25d887db798152d1379b2119c3f864292dd2a42cc6620de1b201a6aa49aaa3`，文件字节数与 mtime 未变。
- M3 冻结 run `social_run_youtube_20260902134215_18f86349`：`observations=105`、`observation_query_matches=145`、`review_events=0`、`human_verified=0`。
- YouTube 全库：`collection_runs=4`、`observations=121`。
- M4 Mastodon 状态：`mastodon_instance_states=0`、`mastodon_scope_state=0`、`mastodon_sightings=0`。
- 运行状态：`collection_runs` 中 active run 为 `0`，启用 schedule 为 `0`；端口 8765/8766/8767 无监听。
- 恢复期发现旧摘要所列 `social_observations`/`social_runs` 并非实际表名；实际表为 `observations`/`collection_runs`。所有基线计数已按实际 schema 重跑并通过，不改写历史事实。
- frozen `social_observation` 与 `social_run_manifest` schema 已允许 `reddit`、`tiktok`、`x`，当前没有协议扩展必要。
- 2026-09-02 Reddit 离线闭环完成后，全量测试为 `135 passed in 4.41s`；前端 `node --check src/glyph_features/social_system/static/app.js` 通过。
- 2026-09-02 TikTok Research API 离线闭环完成后，专项测试为 `26 passed in 0.66s`，全量测试为 `161 passed in 4.71s`；Pylance/VS Code 涉及文件诊断为 0，前端 `node --check` 通过。
- 2026-09-02 X 离线闭环完成后，专项测试为 `27 passed`，全量测试为 `188 passed`；前端 `node --check` 通过。Playwright 在 1440×900 与 390×844 验证六平台切换、X 表单/readiness/费用监控、无 bearer 输入、无横向溢出，以及未满足门禁时提交采集返回 422 且 run 数保持 0。
- 当前代码的 SQLite schema 为 v17：v15 为通用受限 API 状态表，v16 为 TikTok UTC 日预算与请求事件账本，v17 为 X 日期化价格快照、费用守卫、run 绑定和逐请求资源/微美元账本。所有 v14/v15/v16→v17、历史 schema 和备份恢复测试均只使用临时库；主库未被迁移，保持 v14。
- 最终本机状态：8765/8766/8767 均无监听，active run=0，enabled schedule=0。M5 没有配置真实凭据、没有创建真实受限平台 run、没有发平台请求，平台费用为 0。

## 决定与理由

1. 当前唯一实施范围是 M5 的本地适配器、官方结构去敏 fixture、统一系统接入、契约测试、界面待授权状态和手动开通清单。
2. 严禁 Reddit、TikTok、X、Mastodon 真实请求；严禁登录/OAuth 同意、正式申请、接受新条款、购买 credits、启用付费或外部部署。
3. 不修改 M3 的 105 条候选，不新增人工决定，不晋级 query，不重跑 YouTube discovery；不执行冻结的 Mastodon pilot；不进入 M6。
4. 沿用不可变 query、registry 哈希、raw evidence、candidate 状态、人工审核和 release 闸门；规范化不得从 scope 制造对象、评价词、角色或立场事实。
5. 按 Reddit → TikTok Research API → X 顺序逐个平台完成最窄离线闭环并运行聚焦测试；三者完成前不并行跨平台开发。
6. 旧 `tools/x_discourse_monitor.py` 与 `demo/x_discourse_demo.html` 仅作历史参考，不视为统一系统的官方 X 适配器或研究真源。

## 验证结果

| 检查 | 结果 |
|---|---|
| Git/解释器基线 | 已核验；Python 3.11.15 |
| 全量自动化测试 | M5 完成后 188 passed |
| 主库完整性/schema/不可变性 | ok / v14 / 查询前后 SHA-256、字节数、mtime 一致 |
| M3 冻结计数 | 105 / 145 / 0 review |
| M4 三张状态表 | 全部 0 |
| 活动运行/启用调度 | 0 / 0 |
| 本机服务 | 8765/8766/8767 均未监听 |
| 外部平台请求/真实凭据/平台费用 | 0 / 0 / 0 |
| Reddit 专项 | 15 项离线测试通过；无真实请求 |
| TikTok 专项 | 26 项离线测试通过；无真实请求 |
| X 专项 | 27 项离线测试通过；无真实请求 |
| 前端语法 | `node --check` 通过 |
| 浏览器验收 | 1440×900、390×844；六平台/X 门禁/无溢出通过 |
| v14→v15 迁移 | 临时库通过；历史 scope/query/run/observation/raw evidence/query-match 均保持 |
| v15→v16 迁移 | 临时库通过；历史记录与通用 API 分区状态均保持；请求账本可备份恢复 |
| v16→v17 迁移 | 临时库通过；X 价格/守卫/run 绑定/request events 可备份恢复；原子故障回滚通过 |

## 官方资料快照

核验日期均为 2026-09-02。所有页面仅通过显式代理 `http://127.0.0.1:7897` 只读访问；未调用平台 API，未登录、未提交申请、未接受条款、未使用凭证或购买 credits。

### Reddit

- 当前治理依据：[Reddit Data API Terms](https://redditinc.com/policies/data-api-terms)，最后修订 2026-07-20。Terms 要求使用平台提供的 OAuth 身份，不得伪装 User-Agent/OAuth identity；Reddit 可动态设定限额；收到 User Content removal 请求时须进入治理流程；超出获批用途或终止访问时存在删除义务。
- 当前帮助中心/API 参考入口在本次自动化只读访问中返回 HTTP 403。结构依据补充自 Reddit 官方组织的 archived Wiki：[API](https://github.com/reddit-archive/reddit/wiki/API)、[OAuth2](https://github.com/reddit-archive/reddit/wiki/OAuth2)、[JSON](https://github.com/reddit-archive/reddit/wiki/JSON)。这些归档页只用于 fixture 结构与兼容契约，不作为当前费用或额度承诺。
- 结构事实：bearer 请求使用 `oauth.reddit.com`；永久用户授权才返回 `refresh_token`，access token 约一小时；listing 的下一页由 `data.after` 给出，条目位于 `data.children`；运行时应读取 `X-Ratelimit-*` 响应头并处理 429。
- 工程影响：实现显式且不可伪装的 User-Agent、注入式 token provider/refresh 边界、`after` 游标、429/5xx 重试、删除/不可用条目的审计状态；不得把归档页的 60 requests/min 写成当前硬保证。
- 离线实现结果：
	- `reddit.py` 已实现去敏 `t3` 规范化、removed/deleted/unavailable 分类、subreddit 校验、OAuth refresh/app-only grant、refresh-token rotation、Bearer 请求、显式 User-Agent、强制本机代理、Listing/`after`/`X-Ratelimit-*` 解析和无 secret 错误信息。
	- `RedditCollector` 已实现冻结 subreddit/query 逐分区采集、字符串续页状态、跨 run `created_utc` 高水位、429/5xx 退避、401 单次刷新、403/404 分类、畸形 child 隔离、分区失败隔离、query-match provenance、raw evidence 和 removed 内容哈希审计。
	- SQLite v15 的两张通用受限 API 状态表可被 TikTok/X 复用；已验证中断续跑、幂等重入、前向迁移、备份恢复和状态导出。
	- FastAPI/中文界面已支持 Reddit scope、调度选路、未授权零副作用拒绝，以及 health/monitoring 中仅布尔化的“已配置/待授权”；不会展示凭证值。
	- evidence/monitoring/export 已保留 Reddit raw event、查询列、分区状态和“不代表 Reddit 全网样本”的覆盖边界。

### TikTok Research API

- [Getting Started](https://developers.tiktok.com/docs/en/research-api-get-started)、[Query Videos](https://developers.tiktok.com/docs/en/research-api-specs-query-videos)、[Query Video Comments](https://developers.tiktok.com/docs/en/research-api-specs-query-video-comments)、[Client Access Token Management](https://developers.tiktok.com/docs/en/client-access-token-management)、[FAQ](https://developers.tiktok.com/docs/en/research-api-faq)；页面标注最后更新 2026-09-01。
- 资格边界：developer account 本身不授予 Research Tools；必须满足地区/研究资格、提交研究项目并获批。Research Tools 面向符合条件的独立或学术非营利研究者，本次不代用户判断资格或提交申请。
- 认证/配额：获批 research client 的 `client_key`/`client_secret` 以 `client_credentials` 换取 client access token；token 有效期 7200 秒。FAQ 当前说明 Video/Comments API 共用 1000 requests/day、每请求最多 100 records、每日 00:00 UTC 重置；该动态事实须版本化并以运行时错误为准。
- 视频契约：POST `/v2/research/video/query/`，`research.data.basic` scope；`start_date`/`end_date` 最长 30 天；分页响应含 `cursor`、`has_more`、`search_id`，续页必须保留同一查询与 `search_id`。
- 评论契约：POST `/v2/research/video/comment/list/`；顶层评论按 `video_id`，回复按 `comment_id`，二者不能同时请求；响应含 `cursor`/`has_more`，删除可能导致返回数少于 `max_count`，`parent_comment_id` 保留层级。
- 工程影响：只实现 client-token 接口、条件 AST 校验、`search_id`/cursor 恢复、视频/评论/回复分层上限、删除/不可用审计和每日应用内守卫；不得绕过审批、伦理或地区限制。
- 离线实现结果：
	- `tiktok.py` 已实现去身份视频/评论/回复规范化、非嵌套条件 AST、最长 30 个 UTC 整日窗口、client-credentials token、401 单次刷新、视频与评论分页、平台 error envelope 和强制本机代理。
	- `TikTokCollector` 已实现同一 `search_id`/cursor 恢复、视频/评论/回复独立分区、429/5xx 退避、401 非重试分类、分区失败隔离、幂等重入，以及每个请求尝试前的原子预算预留；短页只审计 `possible_unavailable_items`，不推断不可见条目身份。
	- SQLite v16 按 UTC 日期守卫本机 `1..1000` requests/day，并保留 succeeded/failed 尝试；配额耗尽在客户端调用前停止，UTC 次日可从原游标恢复。
	- FastAPI/中文界面支持 TikTok AST、整日窗口、分层页数、待授权 readiness、调度选路与启动前零副作用 422；导出保留冻结查询列、分区状态、请求事件和 UTC 配额快照。

### X API

- [Search Posts](https://docs.x.com/x-api/posts/search/introduction)、[Recent Search API](https://docs.x.com/x-api/posts/search-recent-posts)、[Pagination](https://docs.x.com/x-api/fundamentals/pagination)、[Rate Limits](https://docs.x.com/x-api/fundamentals/rate-limits)、[Pricing](https://docs.x.com/x-api/getting-started/pricing)、[Bearer Token](https://docs.x.com/fundamentals/authentication/oauth-2-0/bearer-tokens)。Rate Limits 页面修改于 2026-07-25，Pricing 页面修改于 2026-08-13。
- 契约：recent search 为 GET `/2/tweets/search/recent`，bearer token 认证；响应 `meta.next_token` 作为下一请求 `pagination_token`；`start_time` 必须位于最近 7 天。当前 per-app 限额快照为 450/15min，运行时以 `x-rate-limit-limit/remaining/reset` 与 429 为准。
- 费用快照：pay-per-usage，读取按返回 resource 计费；2026-09-02 页面列出 Post read 为 `$0.005/resource`，并明确价格可能变化、应以 Developer Console 为准。可在 Console 设置 billing-cycle spending limit，到限后请求被阻断；auto-recharge 不能替代硬上限。
- 工程影响：实现版本化单价快照、预估与实际 resource 数事件、应用内预算守卫/熔断、429 处理和 `next_token` 恢复；真实启用前要求用户在 Developer Console 设置硬 spending limit，并另行批准 credits/付费，默认不得启用 auto-recharge。
- 离线实现结果：
	- `x.py` 已实现 X API v2 recent-search adapter/client：最近七天 UTC 时间窗、query/token/字段校验、固定 `http://127.0.0.1:7897` 代理、bearer 认证、`next_token` 分页、平台 error envelope、rate-limit headers 和无 secret 错误信息。
	- 去敏规范化只保留研究所需 post 内容和公开指标，不保留 `author_id`；不得从 scope 制造对象、评价词、角色或立场事实。
	- `XCollector` 已实现逐 query 分区状态、token 恢复、completed 幂等、401 非重试、429/5xx 有界重试、每次尝试独立费用事件和取消请求的最坏成本结算。
	- SQLite v17 将金额统一为整数 `microusd`；日期化 active price snapshot、Console hard limit 人工确认、本机 cycle cap、run cap、全局 breaker 和每次请求最坏成本预留共同组成费用真源。run 与 billing binding 在同一事务提交，故障不会留下未绑定半成品 run。
	- 每次请求成功后按实际 `result_count` 结算；run cap 只停止当前 run，cycle cap 会打开全局 breaker；active snapshot 改变会阻断旧价 run，新 run 绑定新快照。请求发出后取消标记为 `indeterminate`，不会按 0 成本处理。
	- FastAPI 在创建 run 前执行 bearer、固定代理与完整 billing guard 双门禁；health/monitoring 只返回布尔配置状态和费用汇总，不回显 bearer。导出包含 X 查询列、分区状态、request events、run billing snapshot 和 billing status。
	- 中文界面已接入 X scope 参数、待授权卡片、readiness 与费用监控；不提供 bearer 输入或“一键确认 Console hard limit”按钮。
	- v14/v15/v16→v17、未来 schema 拒绝、备份恢复和事务故障注入全部在临时库通过；没有打开主库进行迁移。

## 平台进度

| 平台 | 官方资料核验 | fixture/适配器 | 统一系统/界面 | 聚焦测试 | 真实权限 |
|---|---|---|---|---|---|
| Reddit | 已完成；当前 Terms + archived 结构参考 | 已完成；去敏 fixture + adapter/collector | 已完成；待授权状态 | 已完成；15 项 + 全量 135 passed | 待授权；真实请求 0 |
| TikTok Research API | 已完成；2026-09-01 文档 | 已完成；去敏 fixture + adapter/collector | 已完成；待授权状态 | 已完成；26 项 + 全量 161 passed | 待授权；真实请求 0 |
| X API | 已完成；动态价格/限额快照 | 已完成；去敏 fixture + adapter/collector/billing | 已完成；待授权与费用门禁 | 已完成；27 项 + 全量 188 passed | 待授权/待费用确认；真实请求 0 |

## 限制与未完成项

- Reddit 仅完成离线待接入闭环；没有登录、OAuth 同意、正式申请、凭证、真实 API 响应、平台费用或实证样本，不能表述为真实平台接入。
- TikTok Research API 仅完成离线待接入闭环；没有 developer account 登录、Research Tools 申请/批准、凭证、真实 API 响应、平台费用或实证样本，不能表述为真实平台接入。
- X 仅完成离线待接入闭环；没有 Developer Console 登录、项目/权限确认、hard spending limit 设置、credits 购买、bearer 配置、真实 API 响应、平台费用或实证样本，不能表述为真实平台接入。
- 当前代码支持 schema v17，但生产主库有意保持 v14。未经单独批准和一致性备份，不得用当前服务打开主库触发前向迁移。
- Reddit 当前帮助中心/API 参考对自动化读取返回 403；归档结构参考不能替代真实启用前的人工条款/API 复核。
- 三个平台的配额、价格、资格和许可均为带日期快照，真实 pilot 前必须重新核验。
- fixture 验证只能证明离线契约，不能表述为真实平台接入或实证研究结果。
- 当前不需要用户提供 secret；后续也不得在聊天、代码、日志、fixture、导出或 Git 中记录 secret。

## 下一步及批准门槛

1. M5 到此停止，不进入 M6，不执行 M3 人工筛选、YouTube 重跑或 Mastodon pilot，不再增加平台功能。
2. 任一平台未来真实 pilot 必须提交独立冻结方案，并重新核验资格、条款、时间窗、query、请求上限、停止条件、保留和发布边界；不得沿用本次离线批准。
3. X 还必须由用户本人先在 Developer Console 设置 hard spending limit，重新核验日期化单价，保证 local cycle cap 不高于 Console cap，再单独批准 credits/付费、主库 v14→v17 迁移和一次手动 run。
4. 任何真实请求、登录/OAuth、正式申请、条款接受、凭证使用、费用启用、预算调整、breaker 重置或 frozen schema 实质变化，均须用户另行明确批准。

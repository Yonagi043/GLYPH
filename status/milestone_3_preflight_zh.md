# GLYPH 社会叙事里程碑 3：真实请求前核验报告

日期：2026-09-02<br>
范围：仅 YouTube Data API v3；未接入 Mastodon 或其他平台<br>
状态：**工程候选已完成；里程碑 3 尚未最终验收**

> 历史状态说明（2026-09-02）：本文是首次真实请求之前的 schema v7 预检快照。
> 首次 pilot 此后已获批并执行；其中“没有真实请求”和 `search.list=100` 单桶口径不再描述
> 当前系统。现行 M3 状态见 `status/milestone_3_report_zh.md`，现行双桶政策见
> `docs/social_narrative_local_ops_zh.md`。

## 未完成门禁

截至本报告生成时，没有取得“首次真实 YouTube API 请求”的明确授权，本机验收服务也没有
配置 `GLYPH_YOUTUBE_API_KEY`。因此系统没有发出任何真实 YouTube 请求，下述 fixture、fake
client 和本机浏览器结果不得表述为真实平台验收。

里程碑 3 的唯一剩余路径是：研究者在本机安全设置 key，明确授权首次请求，然后经
`http://127.0.0.1:7897` 执行一个小规模真实范围，并核验原始证据、规范化、审核、分析、导出、
配额记账和备份恢复。未完成这些步骤前，不进入里程碑 4。

## 已实现能力

1. 统一研究协议
   - scope、query、run manifest、observation、source、审核和主分析继续共用现有协议。
   - frozen `social_observation` 与 `social_run_manifest` schema 未为平台私有字段解冻。
   - 视频、顶层评论和回复映射到同一 observation；parent/reply 使用 `references`。
   - 频道和直接作者元数据只保留在本机 raw evidence，规范化 observation 不发布直接作者标识。

2. YouTube 官方 API 采集路径
   - `search.list` 检索有界视频，`videos.list` 补充互动统计，`channels.list` 保存本机来源证据。
   - `commentThreads.list` 采集顶层评论和内嵌回复；回复不完整时使用 `comments.list` 分页补齐。
   - API key 通过 `X-Goog-Api-Key` 请求头发送，不进入 URL、manifest、raw、导出、UI 或错误消息。
   - HTTP 与 HTTPS 均使用 `GLYPH_OUTBOUND_PROXY`；429/5xx 有限指数退避，403 配额错误不重试，
     `commentsDisabled` 留下错误记录后跳过该视频评论。

3. 配额、分页与幂等
   - SQLite schema v7 增加本地日预算、逐请求 quota event、run page-token state 和 scope 高水位。
   - 官方成本基线：`search.list=100`；`videos.list`、`channels.list`、
     `commentThreads.list`、`comments.list` 各 1 单位。
   - 每次网络尝试前在 `BEGIN IMMEDIATE` 事务中检查并记账；预算不足时零网络调用。
   - 配额日按 `America/Los_Angeles` 计算；默认本地预算为 1000 单位，可经 UI/API 修改。
   - 达到 `max_items` 而未穷尽分页时不推进 scope 高水位，下一 run 允许安全重放。
   - 同一 run 的平台 item 重放幂等；不同 run 保留独立 observation 和互动快照。

4. 本机系统闭环
   - Web manager 按 scope 平台选择 Bluesky 或 YouTube collector；APScheduler 调度定义继续存于 SQLite。
   - 范围视图支持 Bluesky/YouTube 选择，列表与运行记录显示平台。
   - 系统视图显示 key 是否已配置、配额日、预算、已用、剩余和按 operation 用量；不提供 key 输入框。
   - YouTube run 导出继续执行现有 schema/query/source/manifest/project/summarize 验证，并额外写入
     不含凭据的 `youtube_quota_usage.json`。
   - SQLite 一致性备份和恢复覆盖配额设置、用量事件与 checkpoint；备份清单列出各平台 cursor。

## 可核验证据

### 自动测试

- YouTube 专项：`13 passed in 0.27s`
- YouTube + Bluesky 社会系统专项：`30 passed in 0.47s`
- 全仓：`69 passed in 2.33s`
- 锁定环境：`uv sync --locked --extra dev`，47 个包解析、45 个包检查通过
- `git diff --check`：通过
- VS Code 工作区诊断：0
- Pylance 核心文件语法检查：0

YouTube 专项覆盖：fixture schema、视频/评论/回复规范化、page token、完整回复分页、配额预算与
重启、跨 run 快照、103/104 单位闭环、503 重试、403 `quotaExceeded` 不重试、预算零网络阻断、
`commentsDisabled`、导出、备份恢复、Web collector 选择、无 key 阻断。

### 浏览器

- 视口：1440×900、390×844
- 五个视图均可打开：分析、范围、人审、运行、系统
- 两个视口的页面横向溢出：0
- 390px 视口越界表单/按钮：0
- 浏览器 console/page error：0
- 移动顶栏品牌与状态：无重叠
- A/B/Lift 分段标签：完整可见

### 最终候选服务

- URL：`http://127.0.0.1:8766`
- 应用版本：`0.3.0`
- `database=ok`
- `platforms=[bluesky,youtube]`
- `scheduler_running=true`
- `active_runs=0`
- `outbound_proxy_configured=true`
- `youtube_api_key_configured=false`
- YouTube 本地配额：`used_units=0`、`daily_budget=1000`

### 凭据核验

- 严格 `AIza[0-9A-Za-z_-]{30,}` 工作区扫描：0 命中
- `.env.example` 只包含空的 `GLYPH_YOUTUBE_API_KEY=`
- 未在聊天、仓库、fixture、数据库导出或日志中请求、写入或回显真实 key

## 真实验收清单

取得明确授权后，仍需逐项记录：

1. 本机 key 已配置，但任何输出均只显示布尔状态。
2. 通过 7897 发出首个 `search.list`，本地预算建议先限制在 150 单位。
3. 保存真实 search/video/channel/comment 原始响应，并验证规范化记录通过 frozen schema。
4. 核对 API 请求顺序、分页、时间窗、语言、`max_items` 和实际配额事件。
5. 由研究者完成人工审核，确认主分析只纳入 `human_verified`。
6. 从矩阵下钻到 observation、query、source、manifest 和本机 raw evidence。
7. 导出 ZIP 并确认 `validation.json.valid=true` 与 `youtube_quota_usage.json`。
8. 创建备份，修改本机状态后恢复，核对审核、配额和 checkpoint。
9. 更新为最终 `status/milestone_3_report_zh.md`，停止开发并等待是否进入里程碑 4。
# GLYPH 社会叙事本机运维

本文档适用于当前 Bluesky Jetstream、YouTube Data API v3、Mastodon 选定实例，以及 M5 的
Reddit Data API、TikTok Research API 与 X API v2 recent search 本机系统。
`social_observation`、`social_run_manifest` 对 Mastodon 使用 `0.2.0`，历史平台记录保持 `0.1.0`；
文化叙事投影协议不变。M5 受限平台当前只批准本地实现和离线验证，本文的运行方式不构成
登录、申请、条款接受、付费启用或真实平台请求授权。

## 路径与边界

| 内容 | 默认路径 | 是否可直接发布 |
| --- | --- | --- |
| SQLite、WAL、原始事件 | `data/raw/social/glyph-social.sqlite3*` | 否 |
| 一致性备份 | `data/raw/social/backups/` | 否 |
| 按运行导出 | `data/processed/social_narrative_v0/exports/` | 仍需权利审查 |

导出 ZIP 包含 observation、query/source registry、run manifest、审核历史、运行审计、
文化叙事投影、Matrix A/B、Lift、周趋势和验证报告。原始 Jetstream payload 不进入 ZIP。
YouTube run 另含不带凭据的 `youtube_quota_usage.json`；原始 API 响应仍只留在本机数据库。
Mastodon run 另含 `mastodon_instance_states.json`、不带 raw payload 的
`mastodon_sightings.jsonl`，query CSV 包含选定实例、访问方式、分页与间隔快照；原始 status/account
仍只留在本机 evidence。
Reddit/TikTok/X run 使用通用 `api_collection_states.json` 保存可恢复分页状态。TikTok 另含
请求事件与 UTC 日预算快照；X 另含逐请求资源/微美元事件、不可变 run 价格绑定和导出时的
billing-cycle 状态。凭据从不进入导出。
主分析和投影始终只使用 `human_verified` 记录。

## 安装与前台运行

要求 macOS、CPython 3.11 和 `uv`。所有外网连接继续通过本机 7897 代理。
当前源码会在启动时把目标数据库前向迁移到 v17；主库仍冻结在 v14。未取得迁移批准时，只能按
下例显式使用临时数据库，不得省略 `--database` 指向默认主库：

```bash
cd /Users/wuyida/Research/GLYPH
uv sync --locked --extra dev
GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897 \
  uv run glyph-social serve --host 127.0.0.1 --port 8765 \
  --database "${TMPDIR:-/tmp}/glyph-social-m5-offline.sqlite3"
```

Bluesky 不需要密钥。YouTube scope 只有在本机进程存在 `GLYPH_YOUTUBE_API_KEY` 时才能启动；
不要把真实 key 写入仓库、`.env.example`、plist、日志、fixture、run manifest 或聊天。首次真实
YouTube 请求还必须经过项目里程碑的明确确认。确认后只在本机 shell 或秘密管理器中设置：

```bash
export GLYPH_YOUTUBE_API_KEY="$(security find-generic-password -a "$USER" -s GLYPH_YOUTUBE_API_KEY -w)"
GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897 uv run glyph-social serve
```

如需先写入 macOS 钥匙串，可运行 `security add-generic-password -a "$USER" -s GLYPH_YOUTUBE_API_KEY -w`，
并在终端提示中直接输入；不要把秘密作为命令参数或聊天消息传递。

Mastodon public endpoint 可不带 token，但实例可能要求认证。获批的真实 pilot 只能从本机环境读取
实例到 token 的 JSON 对象；不要通过 Web 表单输入 token，也不要把 token 写入 query、manifest 或导出：

```bash
export GLYPH_MASTODON_ACCESS_TOKENS_JSON="$(security find-generic-password -a "$USER" -s GLYPH_MASTODON_ACCESS_TOKENS_JSON -w)"
GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897 uv run glyph-social serve
```

在未单独批准真实 pilot 时，不设置该变量，也不点击 Mastodon scope 的采集/立即调度入口。

Reddit、TikTok 与 X 的真实凭据也只允许由本机 shell 或秘密管理器注入：

```bash
export GLYPH_REDDIT_CLIENT_ID="$(security find-generic-password -a "$USER" -s GLYPH_REDDIT_CLIENT_ID -w)"
export GLYPH_REDDIT_CLIENT_SECRET="$(security find-generic-password -a "$USER" -s GLYPH_REDDIT_CLIENT_SECRET -w)"
export GLYPH_REDDIT_REFRESH_TOKEN="$(security find-generic-password -a "$USER" -s GLYPH_REDDIT_REFRESH_TOKEN -w)"
export GLYPH_REDDIT_USER_AGENT="GLYPH-social-research/<approved-contact>"
export GLYPH_TIKTOK_CLIENT_KEY="$(security find-generic-password -a "$USER" -s GLYPH_TIKTOK_CLIENT_KEY -w)"
export GLYPH_TIKTOK_CLIENT_SECRET="$(security find-generic-password -a "$USER" -s GLYPH_TIKTOK_CLIENT_SECRET -w)"
export GLYPH_X_BEARER_TOKEN="$(security find-generic-password -a "$USER" -s GLYPH_X_BEARER_TOKEN -w)"
```

这些命令只是未来批准后的本机注入形式，不是当前执行步骤。TikTok 必须先取得 Research Tools
批准；Reddit 必须使用获批用途和诚实 User-Agent；X 必须先完成下文的价格与费用门禁。不得把
secret 放入命令历史参数、Web 表单、query、manifest、fixture、日志、导出或聊天。

打开 <http://127.0.0.1:8765>。前台停止使用 `Ctrl-C`。停止时活动 collector 会取消，
已保存游标保留；下次启动会把异常遗留的 `running` run 标记为可重试失败，并重新装载
SQLite 中已启用的 schedule。

## 使用 launchd 持续运行

以下模板使用默认主库，只能在主库迁移和真实持续运行分别获批后启用。M5 离线验收期间不得加载。

先创建本机日志目录：

```bash
mkdir -p /Users/wuyida/Research/GLYPH/data/raw/social/logs
```

在 `~/Library/LaunchAgents/org.glyph.social.plist` 配置当前用户服务：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.glyph.social</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/wuyida/Research/GLYPH/.venv/bin/glyph-social</string>
    <string>serve</string><string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8765</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/wuyida/Research/GLYPH</string>
  <key>EnvironmentVariables</key>
  <dict><key>GLYPH_OUTBOUND_PROXY</key><string>http://127.0.0.1:7897</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/wuyida/Research/GLYPH/data/raw/social/logs/service.log</string>
  <key>StandardErrorPath</key><string>/Users/wuyida/Research/GLYPH/data/raw/social/logs/service.error.log</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.glyph.social.plist
launchctl print gui/$(id -u)/org.glyph.social
launchctl bootout gui/$(id -u)/org.glyph.social
```

修改 plist 后先 `bootout`，再 `bootstrap`。不要同时启动前台服务和 launchd 服务。

## 调度与运行恢复

每个研究范围最多有一个 interval schedule，间隔为 1 分钟到 7 天。调度器使用
APScheduler，SQLite 是调度定义的事实来源。进程启动时重新装载启用项；错过多个周期时
只合并触发一次，同一 schedule 最多运行一个实例。范围归档或时间窗结束会停用其 schedule。
每次实时采集还有 30 分钟本机运行上限，避免零命中连接无限占用；`max_items` 仍是样本上限。

`calibration` scope 是一次性校准单元：只能手动创建一个 run，不能启用 schedule、scheduled
trigger 或 retry。只有当前预登记 query-yield 报告中的通过 query 可以晋级；晋级会原子创建
独立的 confirmatory scope、冻结新的非重叠窗口和视频/评论/回复配额，并归档来源 calibration
scope。已经从同一 source run/report/query 晋级的 query 不能换窗口重复晋级。

停止、手动运行、scheduled run 和 retry run 都保留独立 run 与触发血缘。Bluesky 沿用整数
游标；YouTube 按 run 保存 page token，并在完整穷尽分页后推进 scope 的发布时间高水位。
达到 `max_items` 时不推进 scope 高水位，下一次运行允许重放并由幂等层去重，避免漏掉同页记录。

Mastodon 在 query 中冻结规范化实例列表、`hashtag_timeline`/`search_statuses` 访问方式、每页数量、
每实例页数和逐请求间隔。每个 run/query/instance 独立保存下一页 token、页数、status 数、sighting 数
与终态；单实例 401/403、429/5xx 或连接失败不抹掉其他实例结果。429/5xx 使用有限指数退避。
同一 run 的进程内恢复直接使用保存的分页 token；新 retry run 对未完整实例允许安全重放并由幂等层
去重。只有实例完整结束才提交 scope/query/instance 高水位，后续 run 首请求使用 `since_id`。
公开 timeline 只规范化 `public`/`unlisted`，不采集 private status。

Reddit 按 run/query/subreddit 保存 `after` token，并仅在完整结束后推进 `created_utc` 高水位。
TikTok 分别保存视频 `search_id`/cursor、评论和回复 cursor；同一视频查询的 `search_id` 变化会
停止该分区。X 按 run/query 保存 recent-search `next_token`，恢复时只将其映射为下一次请求的
`pagination_token`。三者的 completed 分区重入均不再发请求。

## YouTube 配额

新 run 使用 2026-06-01 版本化政策：`search.list` 进入独立的每日调用桶，每次请求记 1 call；
`videos.list`、`channels.list`、`commentThreads.list` 和 `comments.list` 进入共享单位桶，每次
请求记 1 unit。翻取下一页和重试都会再次记账，无效请求也会消耗对应桶。旧 run 中按早期政策
保存的 `search.list=100 units` 事件标记为 `legacy_pre_2026-06-01`，不得回写。

系统同时执行两层闸门：当前全局日预算，以及 run 启动时冻结且不可放宽的 search/shared 快照。
提高全局预算不会扩大已经启动的 run。Web 对 YouTube 手动采集会先显示“冻结本次运行预算”
对话框；只有明确填写 search calls 和 shared units 上限后才创建 run。请求发出前原子记账，任一
桶不足时保持零网络调用并将 run 标为失败。配额日按 `America/Los_Angeles` 午夜重置；本机预算
不会修改 Google Cloud 项目额度，系统也不会从 API key 推断云端真实余额。

评论采集必须等待该 run 的全部视频候选完成明确 `include/exclude` 筛选。启用评论时，
`max_items` 不得低于全部 query 的视频候选容量；运行时按剩余总额度和剩余纳入视频公平分配，
避免前排视频提前耗尽整个评论样本。

## X 价格与费用门禁

X 金额真源统一为整数微美元。当前离线快照仅记录 2026-09-02 查得的
`post_read=$0.005/resource`，不是未来价格承诺；真实 pilot 前必须重新核对官方 pricing 页面和
Developer Console。每个 X run 在创建时原子绑定价格快照、run cap、本机 billing-cycle cap、
Console hard spending limit 与 cycle 时间窗，绑定失败时不得留下半成品 run。

每次 GET 发出前按 `max_results × frozen unit price` 原子预留最坏成本，同时检查 run 与 cycle
两级上限。成功后按响应 `result_count` 结算；明确失败且无 resource 返回时结算为 0；请求发出后
结果不确定的取消按最坏资源数记为 `indeterminate`。run cap 只停止该 run，cycle cap、价格快照
变化或 Console 未确认会打开全局熔断器。应用内确认只是本机审计记录，不能证明 Console 已配置。

当前 Web 只读显示 readiness、价格生效日、cap、已计费用、剩余额度与熔断原因，不提供“确认
Console 上限”按钮。未来真实启用必须逐项完成：

1. 取得用户对冻结 pilot 和可能费用的单独明确批准；重新核对 X 条款、价格和限额日期。
2. 由用户本人在 Developer Console 设置 hard spending limit，关闭或限制 auto-recharge，并保留本机外部确认记录。
3. 先做一致性备份并明确批准主库从 v14 前向迁移到当前 v17；不得用日常启动隐式代替批准。
4. 在受控本机操作中调用 `SocialNarrativeService.configure_x_billing_guard()`；local cycle cap 必须不高于 Console cap，cycle 必须为当前 UTC 时间窗。
5. 只从钥匙串注入 bearer，固定代理必须精确为 `http://127.0.0.1:7897`；health 中 `x_collection_ready` 必须为 `true`。
6. 首次只允许手动单 run，不启用 schedule；冻结 query、七天内 UTC 窗口、page size、页数、run cap 和停止条件。
7. 任一价格、权限、429、费用或响应结构异常都停止，不自动提高 cap、购买 credits 或重置熔断器。

M5 没有执行上述真实启用步骤；主库仍为 schema v14，X 熔断器只在临时 v17 fixture 库中验证。

## 导出

Web 的运行页可对已结束 run 执行“导出”。无 Web 时使用：

```bash
uv run glyph-social export-run social_run_<platform>_<id>
```

成功返回前，系统会实际运行现有 observation schema/哈希/query/source/manifest 验证、
文化叙事投影和矩阵汇总。检查包内 `validation.json` 的 `valid` 必须为 `true`。candidate
警告不会被隐藏，但 candidate 不进入主矩阵或叙事投影。

Mastodon 导出中的 sighting 只包含 observation/run/query、观察实例、本地 status ID、canonical
status identity、公开 URL 与 visibility 等审计元数据，不包含本地 raw payload 或联邦账号字段。
X 导出的 `x_request_events.json` 按尝试保存预留/实际 resource 和成本，
`x_run_billing_snapshot.json` 保存 run 启动时不可变费用边界，`x_billing_status.json` 保存导出时
cycle 状态；三者均不包含 bearer token。

## 备份与恢复

Web 系统页可创建热备份。CLI 等价命令：

```bash
uv run glyph-social backup
```

备份使用 `sqlite3.Connection.backup()` 获得 WAL 一致快照，随后执行 SQLite
`integrity_check`，并写入 schema 版本、表计数、游标、字节数和 SHA-256。

恢复前必须停止 Web/launchd 服务，确认没有 collector 写入：

```bash
launchctl bootout gui/$(id -u)/org.glyph.social
uv run glyph-social restore backup_YYYYMMDDTHHMMSSZ_xxxxxxxx \
  --confirm backup_YYYYMMDDTHHMMSSZ_xxxxxxxx
```

恢复会先自动创建 `pre_restore` 安全备份，再校验目标备份的 ID、SHA-256、完整性和 schema
版本，最后原子替换数据库。Web 恢复入口同样要求活动任务数为零，并会暂停调度器。

恢复后验证：

```bash
uv run glyph-social serve --host 127.0.0.1 --port 8765
curl -s http://127.0.0.1:8765/api/health | python -m json.tool
curl -s http://127.0.0.1:8765/api/monitoring | python -m json.tool
```

重点核对数据库状态、各平台游标/checkpoint、YouTube/TikTok 配额用量、Mastodon 实例
completed/failed 计数与 sightings、X run 价格绑定/request events/breaker、审核计数、schedule
和最近 `database_restored` 审计。任何平台凭据都只显示布尔 readiness 或实例数，不显示内容。

## 升级

1. 停止前台或 launchd 服务。
2. 执行 `uv run glyph-social backup`，确认 `integrity_check` 为 `ok`。当前代码 schema 为 v17；主库仍为 v14，首次用当前代码打开会前向迁移，必须先取得明确升级批准并保留 v14 备份。
3. 更新工作区代码后执行 `uv sync --locked --extra dev`。
4. 运行 `.venv/bin/python -m pytest -q`。
5. 启动服务并检查 `/api/health` 与 `/api/monitoring`。

SQLite 迁移只前向执行。新程序拒绝打开高于自身支持版本的数据库；不要用旧代码回写已升级数据库。

## 故障处理

- `startup_interrupted`：上次进程未正常结束。检查错误详情后使用 run 的“重跑”，它从保存游标继续。
- `connection_error`：确认 7897 代理正在监听，再检查 Jetstream 可达性；退避重连由 collector 处理。
- `youtube_api_429` 或 `youtube_api_5xx`：请求会有限指数退避；每次重试都会重新消耗官方配额。
- `youtube_api_403`：检查错误 reason。`commentsDisabled` 仅跳过该视频评论；配额/权限错误会结束 run。
- `youtube_quota_budget`：本机日预算不足，collector 未发出该请求；核对研究计划后再决定是否调整预算。
- `GLYPH_YOUTUBE_API_KEY 未配置`：只在本机进程环境或秘密管理器设置，不要通过 Web 或聊天传递。
- `mastodon_instance_authentication`：该实例返回 401/403；核对 pilot 是否批准、实例是否要求 token，以及本机 token map 的实例键。
- `mastodon_instance_rate_limited`：该实例在有限 429 重试后仍失败；保持其他实例结果，不立即放宽冻结间隔或页数。
- `mastodon_instance_http_5xx` / `mastodon_instance_connection`：检查单实例状态、7897 代理和错误时间；不要把一个实例失败解释成全网不可用。
- `GLYPH_MASTODON_ACCESS_TOKENS_JSON` 解析失败：值必须是实例 hostname 到 token 的 JSON 对象；秘密只在本机 shell/钥匙串处理，不要通过聊天排障。
- `reddit_authentication`：停止该 subreddit 分区；核对获批用途、OAuth grant、User-Agent 与固定代理，不在日志中打印 secret。
- `tiktok_authentication` / `tiktok_api_*`：核对 Research Tools 批准、client 权限与 query AST；不得用普通 developer account 绕过资格门槛。
- `quota_exhausted`：TikTok 本机 UTC 日请求预算已到；保持 cursor，等待下一个 UTC 日或另行批准修改预算。
- `x_authentication` / `x_rate_limited`：保持 `next_token` 和 request event；核对 Console 权限、运行时 rate-limit headers 与冻结重试上限。
- `budget_exhausted`：X 请求在发出前被 run/cycle cap 拒绝；不得自动提高预算。cycle 拒绝还会保持全局熔断。
- `active_price_snapshot_changed`：旧价 run 不再允许请求；重新核价、登记新快照并重新确认费用边界后创建新 run，不改写旧绑定。
- 任务无法停止：先在运行页停止；若进程退出，重启恢复会把遗留 run 记为失败而非伪装完成。
- 导出 422：读取 run 的错误/审核状态；修复源记录后重新导出，不手工改验证报告。
- 恢复 409：仍有活动 collector，先停止全部运行。
- 恢复 422：备份哈希、完整性或 schema 不兼容；保留现场，不覆盖数据库。
- 磁盘空间不足：在系统页检查 SQLite、WAL 和可用空间；先做经校验的备份，再移动旧备份/导出。

Bluesky 公共未认证 Jetstream 与 Mastodon 实例 API 当前不产生平台 API 账单；YouTube 配额单位也不是美元价格。
X 费用只按日期化快照与实际 resource 在本机记账，不能替代 Console 账单。系统显示的 `$0` 不包括本机计算、存储、代理或网络成本。fixture 与 fake client 只证明离线
契约，不等于真实平台验收；任何平台样本都不代表总体。
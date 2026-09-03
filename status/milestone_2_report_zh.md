# GLYPH 社会叙事里程碑 2 验收报告

报告日期：2026-09-02<br>
范围：本机可持续运行与完整系统能力<br>
结论：通过自动化与浏览器验收；未进入里程碑 3

## 1. 范围约束

- 唯一在线采集入口仍为 Bluesky 官方公开 Jetstream v2。
- 所有外网仍通过 `http://127.0.0.1:7897`；代理地址不进入 health、manifest 或导出包。
- 未增加 YouTube、Mastodon 或其他平台 collector、凭证、schema 分支或 UI 入口。
- 未修改冻结的 observation/文化叙事分析原则；主分析仍只使用 `human_verified`。
- 原始事件只保存在本机 SQLite，按 run 导出不包含 raw payload，发布仍需权利审查。

## 2. 已交付能力

### 持续运行与任务生命周期

- SQLite schema v6 持久化研究范围、interval schedule、run trigger 血缘和操作审计。
- APScheduler 3.11.0 作为成熟计时引擎；SQLite 是调度定义的事实来源。
- 启动时恢复启用的 schedule；`coalesce=True`、`max_instances=1` 防止补跑风暴和重叠。
- 范围支持编辑、归档；归档或窗口过期会停用 schedule。
- 支持手动启动、scheduled trigger、停止、取消和 retry；retry 创建新 run 并链接父 run。
- collector 继续使用持久化 Bluesky 游标；每次运行同时受 `max_items` 和 30 分钟上限约束。
- 启动时遗留 `running` run 会记录 `startup_interrupted` 并转为可重试失败。

### 人审与分析

- 人审状态变更保留前后完整 record，可按 observation 查询审核历史。
- UI 可查看 Matrix A、Matrix B、Lift、周趋势、平台记录汇总和原始证据链。
- 所有矩阵、趋势和平台汇总只读取 `human_verified` observation。

### 可验证导出

- 已结束 run 可从 Web 或 CLI 导出 ZIP。
- 包含 `observations.jsonl`、`run_manifest.json`、`queries.csv`、`sources.csv`、
  `review_history.jsonl`、`audit.json`、`narratives.jsonl`、`validation.json` 和 `matrices/`。
- 正式目录使用临时目录构建；验证、投影和汇总全部成功后才原子替换。
- 导出实际调用既有 observation schema/哈希/query/source/manifest validator、
  文化叙事投影和 Matrix A/B/Lift/上下文表汇总，不以“文件已写出”代替验证通过。

### 备份恢复与监控

- 使用 `sqlite3.Connection.backup()` 创建 WAL 一致快照。
- 每份备份记录 schema 版本、表计数、Bluesky 游标、字节数、SHA-256 和
  `PRAGMA integrity_check` 结果。
- 恢复校验 backup ID、SHA-256、完整性和 schema 版本；恢复前自动生成 `pre_restore` 备份。
- Web 恢复要求无活动 collector，并在替换数据库期间暂停 APScheduler。
- 系统页展示数据库/WAL/磁盘占用、run/review/error/schedule 状态、备份和操作审计。
- 成本口径明确为公共未认证 Jetstream 平台 API 账单 `$0`，不包含本机、代理和网络成本；
  平台未提供账户配额不被描述为无限或总体样本。

### macOS 运维

- CLI 提供 `serve`、`backup`、`restore` 和 `export-run`。
- 恢复 CLI 要求 `--confirm` 与 backup ID 完全一致。
- 已提供前台与 launchd 启停、升级、调度恢复、导出、备份恢复和故障处理手册：
  `docs/social_narrative_local_ops_zh.md`。

## 3. 自动化证据

锁定环境同步与全仓测试：

```text
HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 \
  uv sync --locked --extra dev
.venv/bin/python -m pytest -q
56 passed in 2.12s
```

社会系统专项共 17 项，包含：

- schedule 重启持久化、APScheduler 恢复、禁用和 scheduled trigger 血缘；
- scope 归档联动、retry 父 run、操作审计和完整审核历史；
- 按 run 导出通过既有 validator/project/summarize；
- populated SQLite 备份后修改审核状态和游标，再恢复并比对；
- 恢复后的 `human_verified` 状态、原游标和 `database_restored` 审计；
- 篡改备份 SHA-256 后拒绝恢复；
- Matrix B、周趋势、平台汇总和本机监控口径；
- CLI 备份在无 Web 情况下通过完整性检查。

编辑器诊断：全工作区 0 errors。<br>
补丁检查：`git diff --check` 通过。<br>
依赖锁：`uv lock` 新增 APScheduler 3.11.0、tzlocal 5.4.4、tzdata 2026.3。

## 4. 浏览器证据

本机验收地址：`http://127.0.0.1:8766`。

- 桌面端：分析和系统页截图通过，面板无重叠，所有关键数据来自真实 API。
- 移动端：分析、范围、人审、运行、系统五视图逐一检查，页面级横向溢出均为 0。
- A/B/Lift 分段控件分别显示正确条件概率和 Lift 列语义。
- 范围编辑器显示 11 个真实控件，包含运行频率与 schedule 启用开关。
- `/api/scopes`、`/api/schedules`、`/api/runs`、`/api/review-history`、`/api/analysis`、
  `/api/monitoring`、`/api/backups`、`/api/audit` 均返回 HTTP 200。
- 浏览器控制台与 page error：0。
- 通过系统页实际创建并校验本机备份
  `backup_20260902T040450Z_41b3c2f4`，显示 schema v6、完整性 `ok`。

## 5. 恢复比对证据

自动化恢复使用含一条人工确认 observation 的临时数据库：

1. 采集并审核为 `human_verified`，记录当前 Bluesky 游标。
2. 使用 SQLite backup API 创建并校验备份。
3. 将同一 observation 改回 `candidate`，并把当前数据库游标增加 100。
4. 恢复目标备份；恢复前自动创建第二份安全备份。
5. 比对恢复后游标等于原备份游标，observation 恢复为 `human_verified`。
6. 确认 `database_restored` 审计存在，备份目录包含目标与 `pre_restore` 两份备份。

该流程不是 mock，也不是只复制文件；测试实际打开、修改、替换并重新读取 SQLite 数据库。

## 6. 保留边界

- 当前是单研究者、本机回环地址部署，不提供多用户身份、远程访问或权限系统。
- schedule 只支持分钟级 interval，不支持 cron/calendar；这是本机持续采集的有意边界。
- Jetstream 是实时公开流的约束样本，不回填完整历史，也不代表 Bluesky 总体。
- 少于 20 的对象或术语分母继续标记为探索性，不支持排名或总体推断。
- 真实发布仍受许可、隐私、双人复核和 release gate 约束。

## 7. 停止点

里程碑 2 开发到此停止。里程碑 3 的新平台接入、跨平台比较或任何范围扩张均未开始，
等待用户明确确认后再继续。
# GLYPH 统一研究工作台本机运维

版本：`0.1.0`

## 1. 运行边界

工作台是本机、单研究者的编排层。中央 catalog 只保存模块 descriptor、交接包和工件指针、稳定 ID 关系、冻结分析快照、门禁结果与追加式审计。资产原图、平台 raw payload、参与者 PII 和领域业务表继续由各模块拥有。

以下边界不可由工作台覆盖：

- 默认且只允许监听 `127.0.0.1`、`localhost` 或 `::1`；外部绑定返回 `EXTERNAL_BIND_REQUIRES_SEPARATE_APPROVAL`。
- catalog 与 social 数据库必须是两个显式且互异的路径。
- `data/raw/social/glyph-social.sqlite3` 被代码机械拒绝；生产 social 迁移或恢复需要独立批准和停服流程。
- 工作台不挂载 social Web app，不创建第二个 scheduler。
- fixture、页面、API 和 demo 包统一标为 `SYNTHETIC / DEMO`。
- 工作台没有“仍然发布”或忽略 blocker 的入口。

## 2. 锁定环境

```bash
uv sync --frozen --extra dev
uv lock --check
```

Python 固定为 3.11。直接依赖版本记录在 `pyproject.toml` 和 `runtime.lock.json`，完整解析和下载哈希以 `uv.lock` 为准。工作台运行 fixture 不访问外网。

## 3. 启动

使用两个全新的本机测试数据库：

```bash
export GLYPH_RUN_ROOT="${TMPDIR:-/tmp}/glyph-workbench-local"
uv run glyph-workbench serve \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3" \
  --export-root "$GLYPH_RUN_ROOT/exports" \
  --backup-root "$GLYPH_RUN_ROOT/backups" \
  --restore-root "$GLYPH_RUN_ROOT/restores" \
  --host 127.0.0.1 \
  --port 8025
```

入口为 `http://127.0.0.1:8025`。启动只初始化工作台 catalog；不会创建、迁移或恢复 social 数据库。页面写操作要求同源 `Origin` 和有界 TTL 的一次性 CSRF token；每个 unsafe 请求消费一个新 token，重放或过期均返回 `CSRF_TOKEN_INVALID`。完整 fixture、备份、恢复及 operation 停止/恢复还要求服务器验证动作专属确认短语。导出/备份/恢复路径由启动参数固定，浏览器不能提交文件路径或命令。

## 4. CLI 操作

```bash
# 验证四份 handoff 并登记 pointer-only reference graph
uv run glyph-workbench initialize \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3"

# 在隔离 staging 中验证并导入 TASK-01 至 TASK-04 的目录或 zip handoff
uv run glyph-workbench import-handoff HANDOFF_PACKAGE \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3"

# 完整 synthetic E2E：social validated export、分析、demo、formal block、备份
uv run glyph-workbench run-system-fixture \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3" \
  --export-root "$GLYPH_RUN_ROOT/exports" \
  --backup-root "$GLYPH_RUN_ROOT/backups"

# 只读状态
uv run glyph-workbench status \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3"
```

`import-handoff` 只接受已知 TASK/schema，拒绝绝对路径、zip slip、重复成员、符号链接、超限和篡改，并在原生 validator 通过后用单个 catalog 事务登记 pointer。包内文件不会被执行或成为中央事实副本。

`run-system-fixture` 要求 social 路径不存在，或该库已经有当前 catalog 登记的 validated export。若 social export 已完成但 catalog attach 前进程退出，重启会从唯一 synthetic public package manifest 验证并幂等 attach；它不会复用未知 v17 库制造 fixture。

## 5. 健康与凭据

`GET /api/health` 返回：

- catalog integrity 和 schema 版本；
- social schema/integrity，以及 `migration_performed=false`；
- 可用磁盘空间；
- 最近协调备份和失败分析数；
- 平台凭据的 `configured/not configured` 布尔状态；
- `scheduler_started=false`。

响应不返回数据库路径、环境变量名、凭据值、平台正文、PII 或受限资产。平台凭据继续由 social 模块从环境读取；工作台不发起真实请求。

分析和完整 system fixture 也可通过固定 operation API 提交。`GET /api/operations` 和 `GET /api/operations/{operation_id}` 返回持久化的 kind、status、当前阶段、attempt、checkpoint、净化错误码和结果；cancel 只在声明阶段边界生效，resume 沿用同一 operation 的已完成阶段。队列只有一个 worker，不能提交任意 command 或路径。`canceled` 的 result 永远为空，不会被显示为成功。进程重启会把遗留 `queued/running/cancel_requested` attempt 标为 `failed` 和 `OPERATION_INTERRUPTED_BY_RESTART`，保留最后业务 checkpoint，等待显式 resume。

## 6. Demo 审计包

```bash
uv run glyph-workbench export-demo ANALYSIS_RUN_ID \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3" \
  --export-root "$GLYPH_RUN_ROOT/exports"
```

输出使用 `<analysis_run_id>_demo/` 和同名 zip。目录或 zip 已存在时返回 `DEMO_EXPORT_NO_OVERWRITE`。CSV 字段以 `= + - @` 开头时会加单引号，防止表格公式执行。`checksums.sha256` 覆盖包内所有其他文件。Formal release 与 demo export 是不同目的的不可变 release candidate；synthetic 输入始终阻断 formal release。

## 7. 协调备份与恢复演练

```bash
uv run glyph-workbench backup \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3" \
  --backup-root "$GLYPH_RUN_ROOT/backups"

uv run glyph-workbench restore-drill COORDINATED_BACKUP_ID \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/social-v17.sqlite3" \
  --backup-root "$GLYPH_RUN_ROOT/backups" \
  --restore-root "$GLYPH_RUN_ROOT/restores"
```

Catalog 使用 SQLite online backup；social 先以只读连接核对角色、integrity 和精确 v17 schema，再复用不会迁移源库的 backup/restore primitive。非 v17 social 源在创建协调包之前以 `SOCIAL_BACKUP_SOURCE_SCHEMA_UNSUPPORTED` 失败，源库版本、表集和字节不变。协调 manifest 记录两个 backup ID、schema、SHA-256、包含持久 operations 的记录数和顺序一致性窗口。恢复只允许两个互异、尚不存在、非当前源库且非生产库的目标。组件或 checksum 被修改时，在创建目标库前失败；任一恢复阶段失败会删除本次临时目标。

生产恢复不通过 `glyph-workbench restore-drill` 执行。应停止独立 `glyph-social`，按社会叙事运维手册的确认和 pre-restore safety backup 流程操作。

## 8. 常见阻断码

| 代码 | 含义 | 处理 |
|---|---|---|
| `PRODUCTION_SOCIAL_DATABASE_FORBIDDEN` | 指向受保护生产路径 | 换用全新显式临时库；生产变更另行批准 |
| `SOCIAL_SCHEMA_MIGRATION_REQUIRES_SEPARATE_APPROVAL` | social 不是 v17 | 不自动迁移；转交 social 独立流程 |
| `SOCIAL_BACKUP_SOURCE_SCHEMA_UNSUPPORTED` | 协调备份输入不是精确 v17 | 停止备份；按 social 独立流程审查或迁移 |
| `CSRF_TOKEN_INVALID` | token 缺失、过期或已消费 | 重新读取 `/api/session`，每个 unsafe 请求只使用一次 |
| `CONFIRMATION_PHRASE_INVALID` | 危险操作确认缺失或不精确 | 核对 UI 展示的目标、影响和动作专属短语 |
| `SYSTEM_FIXTURE_REQUIRES_NEW_OR_ATTACHED_SOCIAL_DATABASE` | 未知 social 库没有已登记 export | 使用新库或先验证并登记正式 export |
| `UNEXPECTED_MANY_TO_MANY` | 联结可能笛卡尔膨胀 | 修复稳定 ID/表示选择，不降低守卫 |
| `NARRATIVE_EXPOSURE_NOT_OPERATIONALIZED` | 把 WP2 语境误作个体暴露 | 保持 context-only 或提供预注册暴露设计 |
| `DEMO_EXPORT_NO_OVERWRITE` | 目标已存在 | 保留旧包；新输入应形成新 analysis run |
| `COORDINATED_COMPONENT_CHECKSUM_MISMATCH` | 备份组件被修改 | 隔离该备份并重新生成 |
| `FORMAL_RELEASE_BLOCKED` | 至少一个发布门禁未通过 | 查看 gate report，不存在 UI 绕过 |

## 9. 日志与清理

Uvicorn 只记录本机方法、路由和状态码；API 错误不显示堆栈或环境变量。SQLite、导出和备份位于操作者显式指定的本机目录；建议由本机日志系统轮转标准输出，并按数据分类设置目录权限和保留期。

测试目录可在服务停止后删除。不得删除仍被 handoff、analysis snapshot、release candidate 或协调备份 manifest 引用的正式研究工件。

## 10. 验证

```bash
node --check src/glyph_features/workbench/static/app.js
uv run --frozen pytest -q tests/test_workbench.py
uv run --frozen python tools/validate_task05_handoff.py
git diff --check
```

独立模块 CLI 仍为 `glyph-assets`、`glyph-vision`、`glyph-experiment`、`glyph-social` 和 `glyph-han`；工作台不替代其写入、审核或恢复职责。
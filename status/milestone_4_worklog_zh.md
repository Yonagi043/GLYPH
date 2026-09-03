# GLYPH 社会叙事里程碑 4 工作记录

版本：0.2.0
日期：2026-09-02
状态：M4 Mastodon 本地实现与离线验证进行中；尚未批准或执行真实 Mastodon 请求
适用里程碑：M4 Mastodon 真实接入
是否替代/被替代：不替代 M3 报告或工作记录；后续由 `status/milestone_4_report_zh.md` 汇总已验证结果

## 事实证据

- 当前唯一实施范围是 M4 Mastodon。本轮不回到 M1/M2，不继续 M3 人工盲筛、query 晋级或 confirmatory scope，也不接入 M5 平台。
- Git 基线：`main`，HEAD `143ed92c92b0a1e80165bd48fd0ea86406082ba1`。工作区已有 M1-M3 大量未提交修改；M4 不整理、回退或覆盖这些修改。
- Python 基线：Pylance 选择 `/Users/wuyida/Research/GLYPH/.venv/bin/python`；项目要求 CPython 3.11；`uv 0.11.23`。
- 自动化基线：`uv run pytest -q` 为 `96 passed in 3.62s`。
- 服务基线：`127.0.0.1:8765` 与 `127.0.0.1:8766` 均无监听，未发现 `glyph-social`、social system 或对应 uvicorn 采集进程。
- 主库基线：`data/raw/social/glyph-social.sqlite3` 存在，schema v13，`PRAGMA integrity_check=ok`；共有 4 个 YouTube run、121 条 YouTube observation、0 条 `human_verified`。
- M3 冻结校准 run `social_run_youtube_20260902134215_18f86349` 保持 105 条 observation、145 个 query-match、0 条人工 screening、0 份 query-yield 报告、0 条晋级 query。
- 唯一 schedule 属于 YouTube 且 `enabled=0`。M4 实现不得启用、继续或重试该 schedule。
- `status/milestone_3_preflight_zh.md` 顶部已经明确标记其“未发真实请求”和旧配额口径为历史预检事实；现行 M3 边界以 goal prompt v2.1.0、M3 报告和工作记录为准。
- M3 报告与工作记录中“不进入 M4”是转段前门禁；goal prompt v2.1.0 的用户转段决定仅批准 M4 本地设计、fixture、实现和离线验证，不批准任何真实 Mastodon 请求。

## 决定与理由

- 用户于 2026-09-02 明确批准社会采集 schema v0.2.0 最小扩展：在 `social_observation` 与 `social_run_manifest` 平台枚举中加入 `mastodon`，保留历史 v0.1.0 校验兼容，并同步 normalizer、协议配置、schema 文档、fixture 和契约测试。
- 本批准不授权新增研究字段、修改 object map/codebook、迁移或回写 M3 数据，也不授权任何真实 Mastodon 请求。
- 除已批准新增 `mastodon` 平台枚举并提升两份社会采集 schema 至 v0.2.0 外，不增加或改变其他 frozen 字段，也不修改 `cultural_narrative`。Mastodon 的状态 ID、原帖 URL、联邦账号、公开可见性和观察实例使用现有 observation 字段、run/query 配置、raw evidence 和内部 SQLite 状态表达。
- Mastodon 使用独立适配模块，但继续进入现有 scope、query、run、observation、screening、review、analysis、export、backup 和 monitoring 真源，不建立平台专属分析路径。
- scope 目标对象只保留在不可变 query 快照中；Mastodon 规范化不得把目标对象、评价词、立场、角色或语言提示写成 gold 事实。
- 公开实例与 hashtag 只定义有界观察范围。任何看板、导出和报告都必须表述为“选定实例中观察到”，不得表述为 Mastodon 全网样本。
- 真实请求前必须另行冻结实例、hashtag、访问方式、UTC 时间窗、分页与分层上限、逐实例限速、认证状态、代理、请求预算、停止条件和公开边界，并取得用户针对该方案的明确批准。

## 当前局部假设与最窄检查

- 可证伪假设：现有统一 observation 协议能够在不制造研究事实的前提下表达一个公开 Mastodon status，包括 HTML 清理后的正文、联邦账号的去标识来源、状态 ID、canonical 原帖 URL、公开可见性、回复关系和“在哪个实例观察到”的覆盖说明。
- 最窄检查：用去敏 Mastodon API fixture 调用独立规范化函数，并用 frozen `social_observation` validator 验证；同时断言输出没有从 scope 复制 `object_type/object_label`，语言仅保留 API 可见提示，raw payload 仍在本地证据层。
- 若该检查失败且无法通过现有字段或内部派生状态表达，停止 schema 改动并提交具体反例，等待用户确认实质协议变化。

## 验证结果

- 恢复基线已完成；未启动服务、未修改主库、未发任何外网请求。
- frozen `social_observation` 与 `social_run_manifest` v0.1.0 的 `platform` enum 均不含 `mastodon`；通用 normalizer 的 `PLATFORMS` 也不含该值。
- 使用 Pylance 所选 `.venv` 对完全有效的内存 observation 和 manifest 执行 validator，两者均只产生一项错误：`'mastodon' is not one of [...]`。
- 使用 `other` 不能满足 M4：`source_row()`、平台汇总、平台过滤、证据索引和导出均以 observation 的 `platform` 为真源，因而会把已知 Mastodon 记录持久标成 `other`。内部表、raw evidence 或派生 artifact 只能补充实例覆盖，不能修复统一记录的平台语义。
- 最小必要协议扩展是仅在两个 frozen schema 的平台枚举中加入 `mastodon`，并同步通用 normalizer、schema 文档、fixture 和契约测试；当前证据不要求增加新的研究字段或修改 object map/codebook。
- `social_observation` 与 `social_run_manifest` 已按批准实现 v0.2.0：历史 v0.1.0 继续通过，Mastodon 强制使用 v0.2.0；schema 契约测试 `1 passed`。
- 通用 normalizer 已按平台路由版本：Mastodon 输出 v0.2.0，既有 X 记录仍输出 v0.1.0；聚焦测试 `2 passed`。
- 去敏双实例 fixture 与 Mastodon adapter 已实现并通过 HTML 清理、跨实例稳定 status identity、公开/非公开可见性和禁止制造研究 gold 字段的 `3 passed`。
- Mastodon scope 已将规范化实例、访问方式、每页上限、每实例页数和请求间隔写入不可变 query 快照；新 run 生成 v0.2.0 manifest，并明确“选定实例、不代表 Mastodon 全网”；聚焦测试 `1 passed`。
- 内部 SQLite schema v14 新增逐 run/query/instance 分页状态、逐 scope/query/instance 增量高水位和实例 sighting raw evidence；不修改或回写 observation 协议和历史记录。
- 多实例 collector fixture 已验证两页采集、跨实例同一联邦状态去重、三条实例 sighting 留证和单实例认证失败隔离：统一写入 2 条 observation、3 条 sighting、1 条独立 error，run 仍完成；聚焦测试 `1 passed`。
- 429→503→成功的注入客户端验证 1 秒、2 秒有界退避；成功重试不写入 collection error。取消后的同 run 恢复直接使用实例保存的下一页 token，并累计页数、status 与 sighting，不重放第一页。
- 完整实例采集结束才提交 scope/query/instance 高水位；同一 scope 的新 run 首请求使用保存的 `since_id`。中断中的待提交最大 status ID 保存在实例状态，不提前推进增量边界。
- 临时 v13 数据库迁移到 v14 前后，既有 scope、query、run、observation 与 raw event 计数逐项不变；三个 Mastodon 内部表新建为空。该测试未打开或迁移主库。
- Mastodon HTTP client 已用 fake opener 验证实例规范化、Bearer header、代理 handler 与 Link `rel=next` 的 `max_id` 提取，不跟随远端绝对分页 URL。
- `uv run pytest -q tests/test_mastodon_system.py tests/test_social_monitoring.py tests/test_query_yield.py` 为 `54 passed`；相关 Python 文件 Pylance diagnostics 为零。上述检查均使用临时数据库和注入 fake client/opener，未打开主库为可写、未发外网请求。
- FastAPI `ScopeInput`、显式三平台 collector 路由和静态范围表单已接入 Mastodon；Web 与 schedule fixture 均确认调用 `MastodonCollector`，不再由“非 YouTube”默认落入 Bluesky。实例、访问方式、页数和间隔在创建、编辑、归档与列表展示中保留。
- 本地 evidence 已展示 observation 的全部实例 sightings；monitoring 汇总实例 completed/failed、sighting 与本机 token 配置实例数，不返回 token。统一 screening→human review→analysis fixture 通过，平台汇总正确标为 Mastodon。
- Mastodon 导出已包含 query 平台配置列、`mastodon_instance_states.json` 与去 raw payload 的 `mastodon_sightings.jsonl`；原始 status/account 只留本地 evidence。导出 validator 通过。
- SQLite 一致备份/恢复已验证包含 Mastodon 实例状态、scope 高水位和 sightings。v14 服务现可恢复 v13 快照后执行前向迁移，并分别报告源版本和最终版本；未来版本仍拒绝。
- `configs/social_narrative_v0.yaml`、schema README、仓库 README、中文监测阶段说明、本机运维手册和 summary CLI 已同步 Mastodon v0.2.0；真实请求门禁仍保持关闭。
- 最终 `uv run pytest -q` 为 `120 passed in 4.00s`，`node --check` 通过。Playwright 在 1440×900 与 390×844 验证 Mastodon 三平台切换、实例/访问/分页/间隔字段、系统监控和无横向溢出；移动端实例字段改为单列全宽，静态资源使用 v0.4.0-m4 cache key。
- 新增并通过 6 个残余反例：`max_items` 页内截断不推进实例高水位、status search 治理说明明确实例依赖、3 类非单一 hashtag 查询被拒绝、单条畸形 status 记录 `mastodon_status_invalid` 后继续同页处理。Mastodon 文件共 `22 passed`。
- 主库迁移前只读复核为 schema v13、`integrity_check=ok`、4 个 YouTube run、121 条 YouTube observation、0 条 `human_verified`、M3 冻结 run 105 条 observation/145 个 query-match、0 个启用 schedule。M3 的 105 条 `screening_events` 均为 `GLYPH candidate router` 自动写入的 machine `uncertain` 候选占位，人工 `review_events=0`；未执行 M3 人工筛选。
- 迁移前一致快照为 `backup_20260902T150127Z_5c6568ac`，schema v13，SHA-256 `b6ce0dc75a3345b7bb1a56bb114b6bbd625f38c92ecbf99c77fefa65ba1bf269`，`integrity_check=ok`。
- 主库已前向迁移到 schema v14；迁移后上述全部计数逐项不变、`integrity_check=ok`，`mastodon_instance_states`、`mastodon_scope_state`、`mastodon_sightings` 均为 0。未创建 Mastodon scope/run，未发外网请求。
- `status/milestone_4_mastodon_pilot_proposal_zh.md` v0.1.0 已冻结两个实例、`#typography`、UTC 窗口、匿名访问、proxy、单页限额、2 秒间隔、最多 8 次 HTTP 尝试、停止条件与公开边界；状态为待用户单独批准，未执行。

## 限制与未完成项

- 尚未执行真实 Mastodon pilot，因此不能声称 M4 完成或真实平台接入通过。
- 尚未获得或执行真实 Mastodon pilot 批准；实例可达性、真实响应差异与真实限速仍未验收。
- frozen schema 缺少 `mastodon` 平台值的协议阻塞已获用户明确批准并完成最小实现；尚待相关 social schema 全量回归与文档同步。
- M3 的 105 条冻结候选仍等待研究者本人盲筛；该事项不属于 M4 实施范围。

## 下一步及批准门槛

1. 实施并验证两个 frozen schema 的 v0.2.0 最小扩展；不接受把已知平台降格为 `other` 的失真方案。
2. 实现 Mastodon 单 status 规范化与 frozen schema 契约测试。
3. 沿现有 collector/service/storage 路径实现多实例 hashtag timeline、分页、实例级游标、限速、重试和故障隔离的离线 fixture 测试。
4. 将 Mastodon 接入现有 Web 范围配置、调度、筛选、人审、分析、导出、备份和监控，并执行桌面与窄屏验收。
5. 在全量回归和 M3 冻结数据复核通过后，提交单独的冻结真实 pilot 方案。
6. 未取得该方案的明确批准前，不发任何 Mastodon 请求；M4 未完成前不进入 M5。

# GLYPH 社会叙事里程碑 3 工作记录

版本：0.2.0<br>
日期：2026-09-02<br>
状态：M3 进行中；真实 pilot 已完成，离线收口已完成，真实校准待明确批准<br>
适用里程碑：M3 YouTube 真实接入<br>
是否替代/被替代：不替代方法记录；后续由 `status/milestone_3_report_zh.md` 汇总已验证结果

## 事实证据

- Git：`main`，HEAD `143ed92c92b0a1e80165bd48fd0ea86406082ba1`；工作区包含 M1/M2/M3 既有未提交改动，本轮不回退或整理这些改动。
- Python：仓库 `.venv`，Python 3.11.15；`tests/test_youtube_system.py` 基线为 13 passed。
- 服务与调度：未发现 GLYPH 服务或采集进程；本机数据库中的 YouTube schedule 数为 1、enabled 数为 0。
- 数据库：`data/raw/social/glyph-social.sqlite3` 为 schema v7。
- 真实运行：`social_run_youtube_20260902065620_815d2d6f` 于 2026-09-02 完成，received=12、normalized=12、failures=0；另有一次同日失败 run，未产生 observation。
- 当前 12 条真实记录为 11 candidate、1 excluded。查询 `logo design` 偏离文化—历史叙事的对象—评价核心，只能作为 `engineering-only` 审计样本；不得进入主分析或 release。
- 当前数据库尚未机械保存 `engineering-only` 标记，run manifest 的 `release_decision` 仍为 `pending_review`，这是必须修复的治理缺口。
- 旧真实配额事件原样记录为 search.list=100、videos.list=1、channels.list=1、commentThreads.list=2，共 204 单位；不得按新政策回写。
- 当前进程的 `GLYPH_YOUTUBE_API_KEY` 环境状态为 false，本地 `.env` 凭据状态为 false。该布尔状态不否定历史真实请求，但会阻止后续 pilot。
- `status/milestone_3_preflight_zh.md` 中“未发真实请求”和旧配额口径已失效，只保留为历史预检记录。

## 决定与理由

- 当前唯一工作范围仍为 M3，不重做 M1/M2，不进入 M4，不发起新的真实请求。
- 先修复不可变 query 与旧 run 快照。当前 `queries` 会被原地更新，`export_data()` 又按 scope 联接 query；因此旧 run 可能读到后来修改的查询，破坏证据链。
- 本切片不修改 frozen schema。query 版本、run 快照和治理状态先由内部 SQLite 表、manifest 既有字段及派生审计表达。
- 局部可证伪假设：创建 run 后修改 scope 查询，旧 run 导出的 query 文本会错误变为新文本。
- 最窄检查：离线创建 scope/run，修改关键词并再建 run，分别断言旧 run 与新 run 的 query ID 和 query 文本。

## 验证结果

- `.venv/bin/python -m pytest tests/test_youtube_system.py -q`：13 passed，未发网络请求。
- 本机 SQLite 审计确认上述真实 run、12 条记录、204 个旧口径单位和禁用调度。
- query 快照切片：内部 SQLite schema 升至 v8，query 行由 trigger 阻止更新/删除；scope 查询变化只追加新 query；run 导出按 manifest `query_ids` 精确读取。
- `.venv/bin/python -m pytest tests/test_youtube_system.py::test_query_update_preserves_old_run_snapshot -q`：1 passed。
- `.venv/bin/python -m pytest tests/test_youtube_system.py tests/test_bluesky_system.py -q`：33 passed；相关编辑器诊断为 0。
- 真实库迁移前备份：`data/raw/social/backups/pre-m3-governance-v7-20260902.sqlite3`，schema 7，`integrity_check=ok`，SHA-256 `512f9c261e8e1a562b92f4153fb1bab816bef38bf63c374c0f03228284fd504f`。
- engineering-only 隔离：增加内部 `run_governance`，终局分类由 SQLite trigger 防止升回研究用途；审核、主分析、导出叙事和证据下钻均执行治理位。
- `.venv/bin/python -m pytest tests/test_youtube_system.py::test_engineering_only_run_is_auditable_but_cannot_enter_analysis -q`：1 passed；双平台回归 34 passed，相关诊断为 0。
- 真实库已前向迁移至 schema 8，`integrity_check=ok`。`social_run_youtube_20260902065319_a906d1df` 与 `social_run_youtube_20260902065620_815d2d6f` 均为 `engineering_only`、`analysis_allowed=false`、`release_allowed=false`；后者保留 12 条原始 observation，未改写历史配额或 evidence。
- 规范化事实边界：Bluesky 与 YouTube 候选 observation 不再从 scope 写入 `object_type/object_label`；目标对象只保留在 query 快照，人工审核后才可写入 gold。
- 两个平台窄测试 2 passed；YouTube + Bluesky 回归 34 passed，相关诊断为 0。
- registry 强制：object map 增加显式 0.1.0 版本；运行时从协议配置加载 object map/codebook，校验活动对象与统一版本并计算原始文件 SHA-256。不可变 query 保存 registry 快照，schema v9 的 `run_registry_snapshots` 将新 run 标为 `bound`、历史 run 标为 `legacy_unbound`。
- Web 范围对象和审核对象/审美术语已改为 registry 选择控件；审核使用 observation 所属 run 的锁定快照，后端拒绝未登记对象与术语。engineering-only/legacy-unbound 候选不进入 gold 审核队列。
- registry 契约测试 1 passed；registry、治理和 Web 闭环组合 3 passed；双平台回归 35 passed；相关诊断为 0。
- 独立筛选：schema v9 增加只追加 `screening_events`；采集仅产生机器 `uncertain` 建议，人工 `include/exclude/uncertain` 保存规则版本、信号、工具版本、决定者、时间和理由。只有最新筛选为 include 的 bound/research-candidate observation 进入编码队列。
- Web 人审工作台区分“待筛选/待编码”，三种筛选操作连接真实后端；筛选历史随证据和 run 导出。screening 窄测试 1 passed、Web 组合 2 passed、双平台回归 36 passed，相关诊断为 0。
- 查询与分层抽样：不可变 query 保存 `query_family`、`phase`、精确平台 query、配置哈希和视频/线程/回复三层配额；Web 使用冻结查询族代码。YouTube 首阶段只取视频并进入 `awaiting_screening`，筛选前不请求评论；同一 run 续跑时仅对人工 include 视频请求评论。搜索命中、视频详情、候选/纳入/排除视频、线程和回复分母随 run state 保存，因配额截断时不推进增量游标。
- YouTube 配额政策：schema v10 为 run 和 event 保存政策版本；新 run 使用 `youtube_data_api_2026-06-01`，分别守卫每日 `search.list` 调用桶和其他端点共享单位桶。v9 迁移测试确认旧 100-unit search 事件数值不变并标记 `legacy_pre_2026-06-01`。运行包导出 policy、bucket 及扩展 query 字段；Web 分别设置和监控两个桶。
- 分层抽样与配额迁移后双平台回归 39 passed；相关编辑器诊断为 0，均为离线 fixture，未发网络请求。
- schema v10 真实库迁移前一致性备份：`data/raw/social/backups/backup_20260902T082248Z_88ec054a/`，源 schema v8，`integrity_check=ok`，SHA-256 `1919b9c77008be61346c64e6d50387d6abc2bbe6a54cdcfa841809952c3cbbd0`。
- 真实库已前向迁移至 schema v10，`integrity_check=ok`，observation 仍为 12 条。两个旧 YouTube run 均保持 `engineering_only`、`analysis_allowed=false`、`release_allowed=false`、`legacy_unbound` 和 `legacy_pre_2026-06-01`；6 条旧配额事件保持原 units/结果，12 条筛选为 `legacy_migration_v9 + uncertain + machine`。YouTube schedule 仍为 1 条、enabled=0。
- 质量闸门：schema v11 增加不可变独立编码、不可变第三人裁决、agreement report 和 run quality report。对象、立场和逐项审美术语使用 `krippendorff==0.8.2` 计算名义尺度 alpha；不足 30 条的纳入样本要求全量双编，阈值为 0.80。原始双编与裁决同时保留，裁决产生 gold 投影但不覆盖原编码。
- 发布治理：通过的质量报告不会自动设置 `release_allowed`。显式授权要求最新报告为 passed、报告的 screening/review/annotation/adjudication 证据 revision 与当前数据库一致，并保存理由；failed 或过期报告均被机械拒绝，授权可以显式撤销。
- 多 query 与 provenance：schema v12 增加不可变 `observation_query_matches`。同一 scope 可登记多条活动的不可变 YouTube query；run manifest 按顺序冻结全部 query ID，collector 逐 query、逐语言执行。重叠 query 命中同一视频时只保留一条 observation，评论端点只调用一次，但视频、顶层评论和回复均保存全部 query-match；导出包增加 `observation_query_matches.jsonl`。
- Web 产品面：普通审核新增受控来源角色；新增质量与发布工作区，可选择 run/observation、提交独立编码、第三人裁决、运行质量检查和带理由的显式授权/撤销；范围页展示 Q1/Q2 等活动 query，并可为既有 YouTube scope 登记附加 query。
- 语义筛选 fixture：新增明确对象—评价正例、创作者推广、技术问答、泛称赞、明确否定、顶层评论、父语境回复和中英混合 uncertain 案例；fixture 只锁定预登记人工 screening 决策，不宣称机器完成语义判断。
- 自动验证：全仓 `.venv/bin/python -m pytest -q` 为 85 passed；`node --check` 通过；相关 VS Code 诊断为 0。测试均使用 fixture/fake client，没有发出新的真实 YouTube 请求。
- 本机 UI 验收：临时数据库包含 2 条 confirmatory query、2 条纳入记录、4 条独立编码和 passed 质量报告。质量页正确显示 alpha=1、双编 2/2、初始 release 未授权；浏览器操作完成重新评估、填写治理理由、明确授权。范围编辑忠实回读 query family/phase/exact query/分层配额，普通审核显示 8 个受控来源角色；桌面与移动检查无横向溢出。该 fixture 验收不构成真实平台或研究验收。
- schema v11 真实库迁移前备份：`backup_20260902T083133Z_8b861c87`，源 schema v10，`integrity_check=ok`，SHA-256 `f72f14a11b3639b69199ad2e6126af3eab66a9199141cc578789c26ee15e4203`。
- schema v12 真实库迁移前备份：`backup_20260902T084231Z_5c641a51`，源 schema v11，`integrity_check=ok`，SHA-256 `59431b2577d063b1f8334342fa7b4532d453717a4c38b0b03c547fa10264de72`。
- 真实库已前向迁移至 schema v12，`integrity_check=ok`。12 条历史 observation 回填为 12 条一对一 query-match；两个旧 run 仍为 `engineering_only / analysis=false / release=false / legacy_unbound / legacy_pre_2026-06-01`；6 条旧配额事件和 204 units 不变；YouTube schedule 仍为 1 条、enabled=0；四张质量证据表仍为空。
- 用户明确批准冻结提案 v0.1.0 后，创建 scope `scope_youtube_3599c19252277528` 和 run `social_run_youtube_20260902085203_382c800b`。两条 confirmatory query 分别为 `"Latin typography" premium` 与 `"Latin typography" modern`，UTC 窗口、registry 哈希和每 query 2 视频/每视频 5 线程/每线程 2 回复/运行总上限 20 均在请求前锁定。
- 真实发现阶段经 7897 成功调用 `search.list=2`、`videos.list=2`、`channels.list=2`；search 桶 2/2，shared 桶 4/25，failure=0。状态机在 `awaiting_screening` 暂停，确认评论端点尚未调用。
- 4 个视频候选均不满足预登记的 Latin typography 对象—评价关系，人工按 `social_screening_v0.1.0` 全部 exclude。零 include 后继续同一 run，未调用 `commentThreads.list` 或 `comments.list`，run 正常 completed；独立双编和裁决均为 0。
- 质量报告 `failed`：`eligible_count=0`，blockers 为 `no_screening_includes` 与 `agreement_below_0.80`。显式决定 `release_allowed=false`，没有用导出成功或 fixture 覆盖替代研究通过。
- 首次真实导出发现 observation `query_text` 使用 scope 关键词 OR 拼接，而非不可变 exact query。该缺陷来自共享 `ResearchScope`，在 exact query 与关键词拼接不同时可影响 YouTube 视频/评论/回复和 Bluesky。外部请求随即保持停止；全局修复两个平台规范化器、service 和 collector 的 exact-query 传递，并在两个生产入库路径增加不一致即拒绝的运行时闸门。
- 4 条 pilot observation 从既有不可变 query 快照离线修复，重算 `record_sha256`，schema 验证通过，并保存 4 条前后 review history 与 4 条 `observation_query_provenance_repaired` audit。主库全量审计为 16/16 exact query 一致；历史 12 条原值已正确，未改写。回归覆盖旧 run 快照、多 query 各自 exact query、重叠 query-match、Bluesky 和错误 provenance 入库拒绝。
- 零纳入原因复核：4 条均为明确误命中，不支持“筛选规则过严”；主要限制是 7 天窗口、每 query 仅 relevance top-2、对象表达单一且未做独立 query-yield 校准。真实接入工程验收通过，但 M3 研究产出验收未通过，当前检索设计尚未证明足以形成可发布样本。
- 质疑复核后的最终验证：全仓 86 passed，相关编辑器诊断为 0，主库 `integrity_check=ok` 且 16/16 exact query 一致；含 Key 的 `8765` 端口保持关闭，没有新增 YouTube 请求。
- 最终导出 `validation.json.valid=true`，ZIP SHA-256 `f03b6a63f5ba257a2c44143d443ab7b83641437c63f1cf325f5e4bd94b9ffdcf`。pre-run 备份 `backup_20260902T085019Z_0ab7ecf2`、修复前审计备份 `backup_20260902T085433Z_52481053`、最终备份 `backup_20260902T085753Z_1025241e` 均为 `integrity_check=ok`。
- 最终备份再次确认两个旧 engineering-only run、历史 12 条 observation、6 条 quota event 和 204 legacy units 未改写。含 Key 的 `8765` 服务已关闭并确认端口释放；fixture `8766` 继续运行但不构成真实验收。
- 用户要求检索与抽样设计不能止于“合法零结果”后，新增 schema v13 query-yield 校准核心：`calibration` phase、可配置且随不可变 query 哈希保存的 policy、query 内视频候选 rank、视频-only 分母、resolved precision、Wilson 区间和 passed/failed/inconclusive 三态。
- 历史 run 自动标记为 retrospective；只有全 calibration phase 且运行前冻结政策的 run 是 preregistered。系统拒绝 phase 混跑、`max_videos < evaluation_k` 和 calibration 阶段评论/回复配额非零。
- 预登记校准 screening API 后端移除 query ID/text，并按 run+observation 固定哈希盲化顺序；同一重叠视频只作一次相关性决定。报告保存 evidence revision，后续筛选变更会使冻结报告过期。
- query-yield API、质量工作台和导出已接通；导出新增 `query_yield_policy.json`、`query_yield_reports.jsonl` 与 `yield_calibration.json`。逐 query 通过列表支持只晋级达标子集。
- 晋级生成新 confirmatory query 而非改写原 query，保存 source run/query/report/policy 引用并 supersede 来源；源报告过期后，confirmatory run 启动被机械阻断。
- 修复 YouTube 新政策 run quota 快照未实际参与消费检查的问题。当前同时执行全局当日总用量与 run 内用量双闸门；启动可独立冻结 run search/shared 上限，提高全局预算不能放宽已启动 run。
- 新增冻结但未批准的 12-query、top-20 calibration 提案 `status/milestone_3_youtube_query_calibration_proposal_zh.md` v0.1.0；不采评论，不执行晋级 query，不进入 M4。当前未发任何新增外部请求。
- query-yield 完整回归后全仓为 94 passed，前端 `node --check` 通过，相关编辑器诊断为 0，`git diff --check` 通过。
- 真实主库迁移前备份 `backup_20260902T092605Z_b97a66bc` 为 schema v12、16 条 observation、`integrity_check=ok`、SHA-256 `272ef20e4cd8ac4d1d75d6f60a780f36497f435967668976b046b8e91b82f572`。
- 主库已前向迁移至 schema v13；3 个历史 run 均自动获得 retrospective policy。原 pilot 保存第 1 份 query-yield 报告：两条 query 各 retrieved=2/ranked=0/include=0，均为 inconclusive，原因是候选低于 k 且无可靠 rank；通过列表为空。16 条 observation 和旧政策 204 units 不变，完整性为 ok。
- 原 pilot 导出已离线重建，新增三份 query-yield 证据，`validation.json.valid=true`，当前 ZIP SHA-256 `0b5552e26b05cd1c8aae2ee6ee3a0de3fd21217baa5abc036393ffb42f732253`。
- 最终 schema v13 备份 `backup_20260902T092624Z_66135d6c` 为 `integrity_check=ok`，SHA-256 `c8c913640cde27477c2f90c155725f16fc2cfb13b7dd703737bdcf69b6c27cca`。全过程未启动含 Key 服务，未发新增 YouTube 请求。
- 真实主库 UI 在无 Key、无代理的 `127.0.0.1:8767` 验收：质量页显示 retrospective/current frozen/inconclusive，两条原 pilot query 均显示 2/2、precision@k 不可计算及候选不足/排名缺失原因，晋级按钮禁用。桌面与移动重载均无 console/page error；移动页面无全局横向溢出，宽指标表只在自身容器滚动，校准标题和操作在窄屏改为上下布局。
- 最终复核再次为 94 passed、`node --check` 与 `git diff --check` 通过；主库 schema=13、integrity=ok、observations=16、quota_events=12、query_yield_reports=1，含 Key 的 8765 端口关闭。
- 晋级语义收口：通过 query 不再混入来源 calibration scope；系统原子创建独立 confirmatory scope，要求非重叠窗口、显式三层配额和总上限，随后归档来源 scope。部分通过只复制 passed query，同一 source run/report/query 不可通过换窗口重复晋级，stale source report 继续阻断确认运行。
- calibration 执行收口：scope 只能手动运行一次，不允许 schedule、scheduled trigger 或 retry；API 将确认 scope 名称、窗口和三层配额设为必填。
- Web 收口：query promotion 表单暴露独立确认设计和逐 query 选择；YouTube run 启动前必须冻结 search/shared 双桶预算。原 retrospective pilot 无 passed query，控件保持禁用。
- 评论抽样收口：collector 必须先确认全部视频候选均有明确 screening 决定，任一 unresolved 时保持零评论请求；全部 resolved 后按剩余总额度和剩余纳入视频公平分配，避免首视频耗尽样本。启用评论时，启动闸门要求 `max_items` 至少覆盖全部 query 的视频候选容量。
- 新增最小回归先复现“只筛入第一条即插入 2 条评论”的缺陷；根修后公平性与容量闸门 2 passed，YouTube/query-yield 组合 34 passed。全过程仅使用 fake client，未发外部请求。
- 冻结校准提案已从未执行的 v0.1.0 升至 v0.2.0，补充独立 confirmatory scope 模板、`2025-08-29T00:00:00Z` 至 `2026-03-01T00:00:00Z` 的 184 天等长留出窗口和二次真实运行批准边界。该更新不构成 v0.2.0 执行批准。
- 最终离线复核：全仓 95 passed；`node --check`、YAML 解析、184 天等长窗口断言、`git diff --check` 和触及文件编辑器诊断均通过。
- 最终主库只读复核：schema=13、`integrity_check=ok`、3 runs、16 observations、12 quota events、1 query-yield report；旧政策 6 events / 204 units 和新政策 6 events / 6 units 分离保存；YouTube schedule 1 条、enabled=0。唯一 error 是历史 `youtube_api_400`，不可重试。
- 最新代码已在 `127.0.0.1:8767` 以无 Key、无代理方式重启：active run=0、observations=16、run count=3。桌面与移动质量页无 console/page error 和全局横向溢出，retrospective pilot 显示不可晋级且 promotion 控件禁用；run 预算对话框默认 search=4/shared=32，取消后 run 数不变。含 Key 的 8765 端口保持关闭。
- 用户明确批准 query-yield calibration 提案 v0.2.0。请求前将全局本机阈值最小调整为 search=26/shared=52，使扣除既有 2/4 后的余量恰为本 run 24/48；pre-run 备份 `backup_20260902T133921Z_e3593eef` 为 schema v13、integrity ok，SHA-256 `71e1fd735bb34e17e3503a07c88341bd96f3929bcf04f3cf0a012a8f8afde1c1`。
- 登记 12 条 query 后，请求前强审计发现同秒新增 query 会按哈希 ID 重排。含 Key 服务在零新增请求时关闭；`list_scope_queries()` 改为按追加表 rowid 保持登记顺序并移除二次哈希排序，增加同秒顺序回归。聚焦回归 36 passed、Q01-Q12 强断言通过后才启动真实 run。
- calibration scope 为 `scope_youtube_99295095c85ad5ba`；唯一 run 为 `social_run_youtube_20260902134215_18f86349`。实际经 7897 调用 search/videos/channels 各 12 次，评论/回复 0，run error=0；105 个去重视频形成 145 个 query-match，12/12 query 的 rank 均为连续唯一 1…n 且 n≤20。
- discovery 完成后立即关闭含 Key 的 8765。checkpoint 备份 `backup_20260902T134427Z_3d5e00e9` 为 schema v13、integrity ok，SHA-256 `7eeac45cd3ca45c1d210b5f5854e46183cdbec289be1910475a869b56dcd673b`。全仓回归 96 passed，前端语法、diff 和无凭据服务门禁通过。
- 无 Key、无代理 8767 的本 run 盲筛队列为 105 条；顺序稳定且不含 query ID/text。当前 screening 人工决定为 0。系统固定把提交记为 `annotator_local01/manual_review=true`，因此 AI 不代填，等待研究者本人逐条筛选；尚未冻结报告、晋级或执行 confirmatory scope。

## 限制与未完成项

- 本次真实 pilot 为零纳入，因此没有真实评论/回复、独立双编或第三人裁决记录；这些分支的 fixture 覆盖不能冒充真实研究验收。
- 当前没有可发布研究结果。最新质量报告为 failed，release 显式阻断。
- Web 质量工作区是本机单研究者协调面，不是认证、多租户或盲法标注平台；两位编码员仍必须按协议独立作业，系统只保存受控 ID 和不可变结果。
- `max_items` 当前控制评论/回复阶段的运行总上限；视频层明确按 query 使用 `max_videos`。报告中不得把评论/回复上限表述成 per-query 配额。

## 收口及下一批准门槛

1. M3 阶段证据与限制见 `status/milestone_3_report_zh.md`；不得把零纳入改写为通过的研究结果或 M3 最终完成。
2. 不扩大 query、不重发旧 pilot、不自动进入 M4。
3. v0.2.0 的真实 discovery 已按批准完成；下一步是研究者本人完成 105 条稳定盲序候选的逐条筛选。不得由 AI 调用现有接口冒充人工决定。
4. 人工筛选完成后才冻结 query-yield 报告、只晋级 passed query、导出并创建 post-run 备份；不得执行 confirmatory 网络请求或进入 M4。
# GLYPH 统一研究工作台本机运维

版本：研究接入 `0.4`；下方原工程流程 `0.1.0` 保留。

## 0. 当前研究入口

本机现有交付位置为 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，无需合并工作树。使用已有 Python 3.11 环境，不为启动重新安装依赖：

```bash
cd /Users/wuyida/Research/GLYPH-worktrees/task-05
.venv/bin/python -m glyph_features.workbench.cli serve --local-config configs/workbench_local_v04.json
```

实际入口：**http://127.0.0.1:8025/#research**。同配置重启恢复原库，不重新调用模型。若端口被其他服务使用，先在本地启动配置中选择空闲端口，不停止别人的服务；配置值优先于命令默认参数。

[本地配置](../configs/workbench_local_v04.json) 的 `material_root=../../GLYPH` 指向主目录；源材料只读。运行库为 `data/processed/workbench_v04/catalog.sqlite3`；问卷输入别名与提示在同目录 `research/`，导出在 `exports/research/`。`unused-social.sqlite3` 只是显式保留的独立路径，研究流程不创建、不读取生产社会库、不迁移或启动采集。

### 浏览器流程

当前修订 `research-usability-2` 已接入研究判断与后续比较：

- 运行详情先显示保存的结论，再显示作品等权/同内容字体配对、顺序与重复变化。统计由系统计算，解释为研究者或agent判断，原始模型理由另列；不要将有序评分均差作为人类总体效应。
- “记录新的研究判断”将支持/不支持/无法区分、具体证据、材料ID、混杂和下一问题绑定当时结果SHA，保存完整依据。结果已经变化时拒绝旧依据提交，应刷新并重新审视；不修改原判断。
- “据此继续研究”继承下一问题、比较依据和父判断，进入可编辑配置。它不自动执行问卷，也不保证继承的旧条件已经适合新问题；先调整材料、预期和停止规则再保存。
- “同内容字体对照”使用目录中的现有字体，按逐行文本生成固定画布黑白样张；选择字体、名义字重、字号及画布尺寸。可变字体明确设置wght，其他轴保持默认；静态字重不匹配、缺字或画布溢出会拒绝，不自动缩放或替字。源文件、许可依据、轴值、Pillow/FreeType版本和渲染实现哈希保留；名义同字重不等视觉重量。输出位于独立库同级 `research/font_samples/`，重启后仍在材料目录中，原字体与旧样张不变。
- 每项输入可选原色/灰度和最长边，预览、草稿、冻结输入使用相同变换。灰度化在缩放后进行；空最长边保留原尺寸，大图可能超模型通道限制。每份问卷图片数控制分组，反序在每个内容组内进行；覆盖分母按实际任务图片数，不按整批总数。

1. 在“来源与资产”检索整套现有目录，按商业图像、字体样张或字体文件筛选。材料详情显示原图/标准化图、来源、用途、同图/同作品关联和原始记录。字体文件只能盘点，图像问卷选择其样张。
2. 勾选材料后进入“配置研究”。填写问题、候选解释、每项选材原因、未用范围和停止理由；美观固定为主要结果。可选原图/已有标准化、身份、顺序、语言、措辞和重复。需要局部构图时填写左/上/右/下四个像素值，坐标基于所选原图或标准化图，右/下为不包含边界；四项全空代表不裁剪。“预览输入 / 掩码”显示本次实际输入，确认深/浅文字前景后另显示阈值128掩码及叠加。选择确认前景必须有裁剪和具体观察依据；未能确认时保持“未确认：构图”，矩形裁剪本身不等于字形。保存产生持久运行，源哈希/尺寸与派生SHA保留，不覆盖旧版本。
3. 打开已保存运行，执行测量或生成问卷任务。后者先调用现有 v2 测量，再检查模型输入用途与缺字。旧标准化图不是正式 A/B/C 发布物；现成字标及观察确认文字区域用探索性 B_shape，商业未确认构图按 A_layout。浅色字仅在测量提取时反转，问卷实际输入保持原色/极性。掩码阈值128和源输入SHA保留；不是通用分割、历史书体或专家审核。
4. 将运行 ID 交给具有 `runSubagent` 和看图工具的 VS Code agent，按下述固定接口执行。网页自身没有模型 API，也不会因“生成任务”按钮自动调用模型。
5. 回填后刷新运行详情，顶部直接显示问题、登记作品/未登记分组输入、实际输入、评分分母、条件覆盖、逐作品身份/顺序/重复差值和测量/NA。“表示比较的参考运行”可在创建时选已保存版本；仅同父图且输入SHA不同、身份/顺序/重复/语言/措辞/模型显示标签一致的唯一评分形成描述配对，未匹配项保留，不是纯裁剪因果效应。具体来源由主材料根 `configs/research_evidence_v1.json` 按material_id选择并冻结，显示来源事实、支持/不支持及局限；六条旧文献仅背景。当前字体cmap不等于历史书体专家证据。
6. “导出内部审计包”生成可下载 ZIP。包含 `result.json`（配置、快照、原始回答、调用证据、测量、比较和局限）、`ratings.csv`、`manifest.json`，不含图像，不是正式发布或再分发授权。CSV 使用已有公式转义，原始值仍在 JSON。包名随结果摘要改变，不覆盖已有包。
7. “复用配置”恢复选材与条件；手改后再去选材、增删并返回时，未移除项的表示/裁剪/极性/理由与主条件保留，新项采用默认。“新建空白研究”明确清空上一草稿，保存的新版本不覆盖已完成、部分成功、协议偏离或暂停版本；未保存草稿只在当前页面生命周期内保持，刷新浏览器应从已保存运行复用。

### 固定宿主接口

在上述目录中，将 `RUN_ID` 替换为界面显示的运行 ID：

```bash
.venv/bin/python -m glyph_features.workbench.cli persona-next RUN_ID --local-config configs/workbench_local_v04.json
.venv/bin/python -m glyph_features.workbench.cli persona-pending RUN_ID --local-config configs/workbench_local_v04.json
.venv/bin/python -m glyph_features.workbench.cli persona-import RUN_ID --local-config configs/workbench_local_v04.json --session HOST_SESSION_JSONL
```

- `persona-next` 仅领取 queued 任务，返回固定 `task_id`、`prompt_path`、哈希、`agent_name` 和 `invocation_prompt`；无可领取任务返回 `null`。执行 agent 原样将返回的 `invocation_prompt` 与 `agent_name` 传给 `runSubagent`，不手写问卷、不拼回填评分、不提供其他回答。当前新配置默认 Explore；默认 agent 曾发生任务外研究上下文读取，旧版本已暂停。
- 实际宿主 JSONL 应使用本会话的 `workspaceStorage/.../chatSessions/<session-id>.jsonl`，不是任意历史研究文件或空的调试主日志。执行 agent 从当前宿主上下文核对位置，调用 `persona-import` 提取真实父/子工具事件与原始返回。当前这轮使用会话 `296ffc95-9173-420f-899e-8588b280299b`，换会话不能沿用旧路径冒充新记录。
- `persona-pending` 只读列出已领取任务的固定调用信息，不增加次数。**列表出现任务不能证明未调用**：中断恢复先导入并核对原会话日志；只在确认没有发出调用时执行该领取任务。已发出但证据未落盘不能重调。
- 原始返回已落盘而图像轨迹未齐时记 `awaiting_evidence`，保存原文与可见用量但不纳入比较。日志完整后再次导入，按父调用 ID 幂等更新。不得按等待时长推断没看图。
- 人工核对完整轨迹后确认仍缺视觉输入时，可在 `persona-import` 追加 `--finalize-evidence`，保存失败而不是伪造评分；后续完整证据仍可纠正该判定。仅 `failed` 任务可在详情“重新排队”，旧 attempt 不删除。协议偏离不能借重试掩盖，应保留并创建修订后的新版本。
- 暂停只停止未领取任务，不声称取消已经发出的模型请求；“恢复队列”只恢复 suspended 任务，不重领完成任务。服务本身不常驻研究、不在会话结束后续跑。

所有回答统一为 `synthetic_persona`，没有真人写入。记录的 `Auto` 是宿主显示标签，不是确定模型版本；底层模型、effort、温度、seed、tokens 未暴露就记 unknown。可见 credits 保留原值与未知单位，不换算货币或 tokens。

### 当前真实运行与用途范围

`research-usability-2` 当前：424目录项=原412+12受控样张；16持久运行含4份不执行问卷的交互回归。0.4累计83实际问卷，74合格、8失败、1偏离，242纳入，0重试/待证据；不是人类样本。下方41次/10运行是保留的上一修订记录，不作当前总数。

| 新运行 | 证据与下一决定 |
|---|---|
| C01原色 `study_4f9e5fee9963b67f59bdb4f3` / 灰度 `study_e42f7f249f78e673d6258921` | 各5调用、3合格、2失败，各11余任务暂停。原返回缺失及33345 patches超过30000上限保留；不恢复原分辨率队列 |
| C02原色 `study_b3e0f9665b6808b23f8c4fb1` / 灰度 `study_2934f6bdc036d5250a3ff64e` | 同八作品最长边1280、灰度精确转换；共16调用、60纳入，灰度1格式失败。28配对中7负/19零/2正，作品等权灰度减原色-0.1458，未支持一致颜色增美。判断 `assessment_7bbb12f65ad31fb81a7d7f59` 接T01 |
| T01 `study_e565a5e26d3584bc1dc982de` | 三现有字体、四新控制文本、字重400/96px/1280x320；16调用48纳入。Serif减Sans均+0.4375，但正序+0.875、反序0；MaShan的“文字工坊”减Sans四次+1。判断 `assessment_3c7732c655e8176c1ee0a063` 保留顺序反例，停止原条件重复 |
| U5 `study_406aa6ff338752320297e2cb` | 浏览器从T01判断继续并复用两个既有受控样张，保存/reload；父判断及两输入SHA保持。无任务/调用，不计研究发现 |

当前内部固定包（JSON/CSV/manifest，无图片）已通过HTTP下载、CSV行数及包内/结果SHA核验：

- [C02配对证据](http://127.0.0.1:8025/api/research-exports/study_2934f6bdc036d5250a3ff64e-deb74fb7baf0befa)，151278字节，SHA `eb54ee4b436b5e3c5c35f4ccda6fd2e8aea62c3cee1e8b55ffee23e591a6ad8a`；CSV28，JSON另含原色32评分及8原始调用。
- [T01字体证据](http://127.0.0.1:8025/api/research-exports/study_e565a5e26d3584bc1dc982de-b682921df6505a3b)，194947字节，SHA `b6e4fa5905e4b54e252509352f241b9b7f539f3106e338261120cbbca126da3d`；CSV48，12项内容内字体比较和已保存判断。

后续路线/实现变化可能改变实时结果摘要，不覆盖这些固定包。桌面/手机结果页及桌面判断续轮保存已实际验证；手机宿主最终另存下载仍是历史未验证项，不用HTTP核验冒充该项通过。两轮未新增真人或外部文献，字体与形态/联想未分离，不称因果证明。完整解释和恢复位置以主根AUTORESEARCH第8/12节 `research-usability-2` 为准。

以下为上一修订 `acceptance-followup-1` 的历史记录：

2026-09-07 实施更新：主材料根 `configs/research_material_uses_v1.json` 已将A11限定研究用途接入MaterialCatalog，按既有来源清单SHA及真实图像字节验证375件商业材料。不把用户声明伪装成第三方许可证，不放开未来输入、再分发或正式发布。完整结果与恢复提示在主根AUTORESEARCH第8、12节 `acceptance-followup-1`，不重做已完成修复或问卷。F5/U6仍有手机宿主最终下载保存未验证，不签整体通过。

| 运行 ID | 已有材料及条件 | 当前结果 |
|---|---|---|
| `study_75f85a264e619952c8130e3e` | 现成 NotoSansSC / NotoSerifSC，默认 agent | 首调用看图但任务外读取，protocol_deviation；余七任务暂停，不纳入比较 |
| `study_4de4e9699bb856b5a52f7b2e` | 相同样张，Explore，baseline/zh，正反序，两次重复 | 八次实际调用完成，十六条逐图评分，可回查 |
| `study_6afd1464ce3dec54a48a38f7` | 现成 Lato Bold/Regular 原样张，Explore，baseline/en，正反序 | 四次实际调用完成，八条逐图评分，界面换材料及暂停/恢复已实际执行 |
| `study_ac60e55a654a5271fe0d87cb` | A10 的四件既有商业作品 | 历史blocked快照保留8个用途blocker、无测量/任务/调用，不原地改写 |
| `study_0906e3bfccd0a34486668913` | 四商业作品原构图（Paris仅左侧1140x740，去除联系方式）及两片假名样张；baseline/en/ja、正反序、两次重复 | 12实际调用，9合格/54条纳入，3次反序漏末图失败/15条原始评分排除；0重试，questionnaire_partial如实保留。六输入/测量/匹配比较、原始轨迹可回查 |
| `study_dc254b7d121ad4a7571de807` | 汉仪赤云隶与Kontrapunkt Type既有作品完整图，baseline/zh、正反序、重复2 | 8调用/16评分，均完整看图，无缺失或重试；中位数分别6、5 |
| `study_dfbb8c0bf244a35dd49b9d6a` | 同作品观察确认文字区域，原色dark/light；参考上一完整图运行，同提示条件 | 8调用/16评分，均完整；中位数仍6、5，每作品8配对，区域减完整图分别-1至0、-1至1，与重复波动同量级，因果不可辨识 |

另三配置为明确不生成问卷的交互回归：F1 `study_4e8155c5e338e3a901f0f8b7`、手机 `study_baab96fa1ac672dc184448ae`、桌面 `study_cf98982f1e5680d4ae9bff76`。总10运行并非10研究批次；0.4总41问卷、127原始回答，130规范化行包含3个null缺图占位，110条纳入；另1次非问卷Explore误委派单列在主路线，不加入问卷或研究成果。

375 对商业图、原字体包13文件、13对样张及 `data/assets/fonts` 的11个额外字体文件均可盘点，共412条材料记录。额外字体的7条旧库存和许可哈希复用，4文件无该库存记录，仅盘点不伪造许可。11个无缺字样张有内嵌OFL 1.1依据；MaShanZheng旧样张缺四个繁体字，不作无缺字对照；Nanum的内嵌信息不足以确认许可。**U2已贯通实际商业构图研究**，不是通过所有历史权利门禁或完成真人实证。三次失败是结果的一部分，不影响继续选材保存新版本，也不应为了满额展示而自动重抽。

旧商业批次Serif减Thin Sans在9个有效任务中为+1至+2，但字重/渲染混杂，不能归因为衬线；商业身份变化与重复波动均在一分内，文化机制未识别。深色书籍A_layout暗像素覆盖接近1，描述背景而非字形。新两作品仅确认区域可测探索性形状量；来源支持作品出处/语境动机，不是审美真值。旧工程按钮仍在“工程档案 / Fixture”，不混入实际评分。当前桌面/手机可见普通点击、输入/掩码预览、保存重开及截图已执行；隐藏页旧限制仍保留历史，不改CSP。

已验证[商业内部审计包](http://127.0.0.1:8025/api/research-exports/study_0906e3bfccd0a34486668913-d2c4f194c932c7cc)，SHA-256 `fe10ead400478323c2a2d8e6c5d6299cdb6cbe5fdad1c5aa4ffb11290c35a10c`，三文件/54条纳入评分/全部12次调用与失败证据，无图片；包内SHA及结果摘要均核验。同配置重启后五运行与结果恢复，未重复调用。后续路线全文哈希或实现变化会生成新摘要，旧包仍可下载，不覆盖。

新[完整图包](http://127.0.0.1:8025/api/research-exports/study_dc254b7d121ad4a7571de807-284fd2825f864ad0)为24595字节，SHA `5077244aa0267ce7885d5c5c01af53dff655a5bcea705cdaccb68b96fdb17ba6`；[区域及配对包](http://127.0.0.1:8025/api/research-exports/study_dfbb8c0bf244a35dd49b9d6a-78e6f97aa56a368a)为34072字节，SHA `e628c04bd3210cf41b725bc4807d013835bf1748f5e5547a456b7bf050a54efa`。各CSV16条，配对包JSON另含参考全部调用；三文件及16配对独立核验，旧商业数据逐字段不变。桌面配对包实际落入Downloads；手机完整图点击收到服务GET200，但未定位最终保存文件，Playwright下载事件也未透传。用户可检查集成浏览器另存为/下载提示后按上述SHA核验；不因此重复模型调用或绕过浏览器权限。

## 1. 运行边界

工作台是本机、单研究者的编排层。原中央 catalog 保存模块 descriptor、交接包和工件指针、稳定 ID 关系、冻结分析快照、门禁结果与追加式审计。研究接入额外在同一独立 catalog 保存 research_studies、persona_tasks、persona_attempts，与旧 fixture 分析和真人表隔离。资产原图、平台 raw payload、参与者 PII 和领域业务表继续由各模块拥有。

以下边界不可由工作台覆盖：

- 默认且只允许监听 `127.0.0.1`、`localhost` 或 `::1`；外部绑定返回 `EXTERNAL_BIND_REQUIRES_SEPARATE_APPROVAL`。
- catalog 与 social 数据库必须是两个显式且互异的路径。
- `data/raw/social/glyph-social.sqlite3` 被代码机械拒绝；生产 social 迁移或恢复需要独立批准和停服流程。
- 工作台不挂载 social Web app，不创建第二个 scheduler。
- 旧工程 fixture、对应页面/API 和 demo 包统一标为 `SYNTHETIC / DEMO`；实际问卷与内部导出另标 `synthetic_persona`，不混用。
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

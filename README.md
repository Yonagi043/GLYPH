# GLYPH

GLYPH 是围绕文字审美的本机研究系统，研究问题是：**在招牌、Logo、包装等商业场景中，哪种文字、字体或书体更好看，为什么？** 跨文化感知、文化历史叙事、跨文字视觉形式和汉字内部书体四条研究线共同区分候选解释，不预设某种文字或字体更美。

系统复用 [图包与字体包/README_字体审美.md](图包与字体包/README_字体审美.md) 中的商业材料、字体及标准化成果，支持从材料选择、条件配置、测量和实际模型问卷，到结果比较、证据回查、保存判断及继续下一轮研究。美观是主要结果；清晰度、文化联想和视觉指标分别保留，不能替代它。

## 当前能力

截至 2026-09-07，路线版本为 **0.4 / research-usability-2**。以下数量是已有本机研究环境的快照，不代表 Git 克隆自动附带这些材料或运行数据。

- **材料与表示：** 424 条目录记录，包括原有 412 项和 12 张新增控制样张；375 件商业图像支持限定用途的本机分析及现有 Copilot 看图问卷。原图、标准化图、裁剪、颜色和尺度条件分别保留。
- **受控字体比较：** 使用已有字体生成同内容、固定字号及画布的黑白样张，明确可变字重轴，检查缺字与画布溢出，记录源文件、许可依据和输入哈希；不自动缩放来掩盖不匹配。
- **实际问卷：** 配置角色、图片分组、顺序和重复，经现有 VS Code 会话实际看图执行，再通过固定接口导入原始回答、缺失和可见用量；模型结果统一标记 `synthetic_persona`。
- **比较与研究积累：** 展示作品等权、同内容字体配对及顺序和重复变化；保存结论、反例、混杂、下一问题与当时结果依据，点击“据此继续研究”复用父判断和配置。
- **回查与导出：** 重开冻结输入、测量及不适用项、原始回答和来源，导出带哈希的内部 JSON/CSV 证据包；旧结果和失败不覆盖。

0.4 累计 83 次实际问卷调用：74 次合格、8 次失败、1 次协议偏离，242 条评分纳入，0 次重试、无待处理调用。16 个保存版本中有 4 个无问卷的交互回归，不能当作研究批次；0.3 的历史结果另列，不混入这些数量。

## 最近研究结果

C02 商业色彩比较与 T01 受控字体比较共执行 32 次实际看图调用，108 条评分纳入分析；一份格式失败保留且不补抽。以下均为给定模型、提示和材料下的描述性结果，不是真人人群效应。

| 比较 | 观察结果 | 当前解释边界 |
|---|---|---|
| C02：八件商业作品，原色与同尺度灰度 | 28 个匹配差值中 7 负、19 零、2 正；灰度减原色的作品等权均差为 -0.1458 分 | 作品间方向不同，差异未超过一分的重复波动，不支持颜色一致增美；整图去色也改变产品、图形和背景 |
| T01：Noto Sans SC、Noto Serif SC、Ma Shan Zheng，四组文字 | 同字号、画布和名义字重 400 下，Serif 减 Sans 平均 +0.4375 分；正序 +0.875，反序 0 | 统一 Serif 优势对顺序不稳定；名义同字重仍不等于同墨量、比例或笔画对比 |
| T01 的“文字工坊”实例 | Ma Shan Zheng 减 Sans 四次均为 +1 分 | 是该内容及条件下的局部稳定偏好，不代表字体家族或历史书体总体排名 |

字体元数据核验发现旧 Sans 样张默认字重为 100、Serif 为 400；T01 明确设置新输入字重，旧比较保留且不再用来单独解释衬线效应。T01 的下一问题是区分呈现位置、第三字体比较语境与调用波动，已保存判断并停止原条件重复，尚未执行该后续比较。

完整设计、逐对差值、研究判断和失败记录见 [AUTORESEARCH.md](AUTORESEARCH.md#8-当前执行位置与待办)。已有本机运行库中可直接打开：

- C02 原色：`study_b3e0f9665b6808b23f8c4fb1`；灰度：`study_2934f6bdc036d5250a3ff64e`。
- T01：`study_e565a5e26d3584bc1dc982de`。

## 本机研究入口

**服务启动后打开：[GLYPH 研究工作台](http://127.0.0.1:8025/#research)。** 这是本机回环地址，不是公开网站。运行需要 Python 3.11；问卷实际执行还需要具有看图和 subagent 工具的 VS Code 会话。

### 新克隆环境

在仓库根目录安装锁定依赖，并将 `GLYPH_MATERIAL_ROOT` 指向已有的、获准使用的 GLYPH 材料根目录。该目录须包含来源 handoff、原图/标准化映射及字体，不是任意图片文件夹；A11 配置只适用于其哈希绑定的既有材料，不自动授权新增素材。

```bash
uv sync --frozen --extra dev
export GLYPH_MATERIAL_ROOT="/absolute/path/to/approved-material-root"
export GLYPH_RUN_ROOT="$PWD/data/processed/workbench_local"
uv run --frozen glyph-workbench serve \
  --material-root "$GLYPH_MATERIAL_ROOT" \
  --catalog-database "$GLYPH_RUN_ROOT/catalog.sqlite3" \
  --social-database "$GLYPH_RUN_ROOT/unused-social.sqlite3" \
  --export-root "$GLYPH_RUN_ROOT/exports" \
  --backup-root "$GLYPH_RUN_ROOT/backups" \
  --restore-root "$GLYPH_RUN_ROOT/restores" \
  --host 127.0.0.1 --port 8025
```

这里的绝对材料路径需要替换为实际位置；新库不会自动包含本文报告的本机问卷运行。若端口已占用，选择其他空闲端口，不停止别人的服务。外网依赖安装使用命令级代理，不改全局网络设置。

### 已有本机安装

当前已验证的安装仍使用 TASK-05 工作树中的已有环境、独立研究库和主目录材料。下列路径针对现有机器，不是新克隆的通用安装命令；同配置重启可恢复已有运行。

```bash
cd /Users/wuyida/Research/GLYPH-worktrees/task-05
.venv/bin/python -m glyph_features.workbench.cli serve --local-config configs/workbench_local_v04.json
```

配置只读接入主目录资产，持久运行库和派生输入留在 TASK-05，不连接生产社会叙事库。本次更新不新增上传本机数据库、原始问卷返回、内部导出包及未获再分发许可的图片和字体；已有文件被 Git 跟踪也不意味着获得了新的再分发许可。

研究页可查看 C02/T01 的结论和证据，或从已保存判断点击“据此继续研究”，调整材料、条件、预期与停止规则后保存新版本。**网页本身不直接调用 VS Code subagent，也不在会话外自动研究。** 当前 agent 使用 `persona-next`、`persona-pending`、`persona-import` 固定接口完成真实任务执行和回填，不要求用户手拼评分。

研究相关局部测试、桌面和手机结果页、判断续轮、样张复用与保存重开已验证；C02/T01 内部证据包已核对下载内容、CSV 行数和哈希。手机集成浏览器的最终下载保存仍有历史未验证项，不把 HTTP 下载成功写成该项通过。

执行与恢复时读取 [AGENTS.md](AGENTS.md) 和 [AUTORESEARCH.md](AUTORESEARCH.md)，以后者第 7、8、12 节的最新授权、进度和恢复点为准；旧暂停和旧验收记录不覆盖当前状态。

共同数据规范位于 [`schema/`](schema/)，批量录入模板位于 [`data/templates/`](data/templates/)。研究说明和原型工具仍保留在 [`status/`](status/) 与 [`tools/`](tools/)；它们必须通过 `stimulus_id` 使用这套数据契约，不能各自发明字段。

团队成员向本仓库提交代码或材料前，请先阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)。默认使用个人
功能分支和 Pull Request，不直接向 `main` 推送。

## 研究边界

视觉特征是可解释测量，不是“好看”的真值；文化叙事是带来源的公共话语观察，不是历史起源或因果传播证明。对现实人群的审美主张需要相应人类证据。本轮身份 subagent 实际看图问卷可形成标记为 `synthetic_persona` 的模型研究结果，但不写入 `human_rating`、不代表真实母语人群，也不把历史真人门禁改为通过。真人采集不作为本轮闭环系统交付的前置条件。

## 目录

```text
schema/       JSON Schema 与字段规则
data/
  templates/  空模板与最小示例
  raw/        原始材料（默认不提交）
  processed/  清洗、渲染与特征中间结果
  releases/   经过许可与去标识的发布数据
status/       研究备忘录与范围说明
tools/        可复现的小工具与其文档
demo/         不含敏感数据的演示产物
```

## Visual features v1

The frozen implementation lives in `src/glyph_features` and follows
`status/visual_feature_v1_proposal_zh.md`. It uses a JSON-compatible YAML
configuration, fixed Python dependencies, explicit failure records, and a
no-overwrite policy. The v1 matrix contains 160 condition cells and 140 unique
stimuli, using seven OFL-1.1-cleared Noto, Bpmf Iansui, and LXGW Marker Gothic font assets. Exact source
URLs, access dates, license text hash, font hashes, and coverage checks are in
`data/processed/visual_features_v1/asset_inventory.csv`.

```bash
conda activate glyph
uv sync --locked --extra dev
python -m glyph_features.cli validate-config --config configs/visual_features_v1.yaml
python -m glyph_features.cli render --config configs/visual_features_v1.yaml --manifest data/processed/visual_features_v1/manifest.csv
python -m glyph_features.cli measure --run-id render_<manifest-hash>
python -m glyph_features.cli qc --run-id render_<manifest-hash>
```

Before a batch run, the frozen targets can be checked for geometric
feasibility without changing any inputs:

```bash
python tools/audit_normalization_feasibility.py \
  --output data/processed/visual_features_v1/audits/normalization_feasibility.csv
```

The current reference run is `render_551362ca0ff22f33`; it produces 140 passed
stimuli with zero failed normalizations under protocol `visual_features_v1.2.0`.
The area-profile integer calibration removes rounding-only errors without
changing the frozen target. The
auditable feasibility report is in
`data/processed/visual_features_v1/audits/`. The run is therefore a
measurement fixture, not a public release. A release remains blocked until
the protocol owner explicitly resolves the incompatible canvas/normalization
constraints and the complete matrix is rerun under a new protocol version.
The pipeline produces grayscale and binary records, keeps missing samples, and
never produces a composite aesthetic score.

数据许可和受试者隐私协议尚未冻结；在发布真实资产或评分前必须补充相应许可与伦理文件。

## Social-narrative monitoring (offline core)

The cultural-narrative line has a small, offline core that accepts an export
from an approved API, public-web capture, Facepager, or Zeeschuimer session.
It never logs in or crawls a platform itself.  Normalize an export into the
independent `schema/social_observation.schema.json` contract, then build the
two conditional-probability matrices and `Lift` summary:

```bash
RUN_ID=example
python tools/normalize_social_records.py \
  --input data/raw/social/public_web/social_run_example_20260901/export.json \
  --output data/processed/social_narrative_v0/observations.jsonl \
  --sources-output data/processed/social_narrative_v0/sources.csv \
  --platform public_web --source-kind imported_export \
  --collection-run-id social_run_example_20260901 \
  --query-id q_example_typography_en \
  --normalized-at 2026-09-01T00:00:00Z
python tools/validate_social_observations.py \
  --input data/processed/social_narrative_v0/observations.jsonl \
  --queries data/templates/social_queries.csv \
  --codebook data/templates/social_codebook.csv \
  --objects data/templates/social_object_map.csv \
  --sources data/processed/social_narrative_v0/sources.csv \
  --run-manifest data/templates/social_run_manifest.json
python tools/summarize_narratives.py \
  --input data/processed/social_narrative_v0/observations.jsonl \
  --output-dir data/processed/social_narrative_v0/matrices/summary_$RUN_ID
```

The complete sampling, rights, privacy, annotation, and interpretation rules
are in the bilingual guides [`docs/social_narrative_monitoring_zh.md`](docs/social_narrative_monitoring_zh.md) and [`docs/social_narrative_monitoring.md`](docs/social_narrative_monitoring.md).
A deterministic, entirely synthetic end-to-end example is checked in at
[`demo/social_narrative/`](demo/social_narrative/); it contains no platform or
user data.

## 本机社会叙事系统（六平台统一运行层）

本机运行层通过 Bluesky 官方公开 Jetstream v2 接收实时帖文，也可通过 YouTube Data API v3
采集有界视频、频道元数据、公开评论与回复，或从冻结的 Mastodon 实例列表采集有界 hashtag
timeline/status search。M5 另提供 Reddit Data API、TikTok Research API 与 X API v2 recent search
的离线待接入适配器；三者只有在资格、凭据、固定代理和平台专属预算门禁全部满足后才可创建 run。
原始证据、Bluesky `seq` 游标、YouTube 分页状态和配额用量、Mastodon
逐实例分页/高水位/sighting、规范化 observation、query、source、run manifest、失败与人工审核历史
保存在同一 SQLite 数据库中。主分析仍只读取 `human_verified` observation，并继续使用离线核心的
Matrix A/B、Lift 与周趋势定义。持久化 schedule、停止/重跑、按 run 验证导出、SQLite
一致性备份恢复及操作监控均在本机完成。

```bash
uv sync --locked --extra dev
GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897 uv run glyph-social serve \
  --database "${TMPDIR:-/tmp}/glyph-social-m5-offline.sqlite3"
```

当前源码目标 schema 为 v17，而生产主库仍有意保持 v14；在迁移另行获批前必须显式使用临时
数据库，不能省略上述 `--database`。也可以使用 `--proxy http://127.0.0.1:7897` 传入代理。代理只用于
平台外网连接；Web 界面仍默认绑定 `127.0.0.1`。带凭证的代理地址只能放在 shell 环境
或被 Git 忽略的本地 `.env` 中，不能提交到仓库、日志、fixture 或运行 manifest。

浏览器打开 <http://127.0.0.1:8765>。系统默认只监听本机回环地址；生产数据库位于
`data/raw/social/glyph-social.sqlite3`，该目录已被 Git 忽略。Bluesky 公开实时流不需要
账号或密钥；YouTube 仅从本机 `GLYPH_YOUTUBE_API_KEY` 环境变量读取 key，并受可配置日预算
守卫约束；Mastodon token map 仅从本机 `GLYPH_MASTODON_ACCESS_TOKENS_JSON` 读取。Reddit、
TikTok 和 X 凭据同样只允许来自本机进程环境；X 还要求日期化价格快照、run/billing-cycle cap、
已人工核验的 Developer Console hard spending limit 和关闭状态的费用熔断器。不要把真实
key/token 写入仓库、日志、fixture、manifest 或聊天。停止服务使用 `Ctrl-C`；
采集任务停止时，已处理游标/checkpoint、配额用量和运行审计会保留。

完整的 macOS 前台/launchd 启停、升级、调度恢复、导出、备份恢复和故障处理步骤见
[`docs/social_narrative_local_ops_zh.md`](docs/social_narrative_local_ops_zh.md)。默认备份保存在
`data/raw/social/backups/`，验证导出保存在
`data/processed/social_narrative_v0/exports/`；两者都默认被 Git 忽略。

当前链路只覆盖已登记关键词、语言和 UTC 时间窗内的有界样本，不代表任一平台全网或总体舆论。
M5 的 Reddit、TikTok 与 X 仅完成本地实现和去敏 fixture 验证；未登录、未申请、未接受条款、
未配置真实凭据、未购买 credits、未启用付费，也未发真实平台请求。原始 payload 仅供本机证据核验，任何发布仍须遵守现有
权利、隐私、双人复核和发布闸门。

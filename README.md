# GLYPH

GLYPH 研究文字系统、书体与品牌字标审美的四条研究线：跨文化感知、文化—历史叙事、跨文字视觉形式，以及汉字内部书体演化。

当前阶段先冻结共同数据基础。规范位于 [`schema/`](schema/)，批量录入模板位于 [`data/templates/`](data/templates/)。研究说明和原型工具仍保留在 [`status/`](status/) 与 [`tools/`](tools/)；它们必须通过 `stimulus_id` 使用这套数据契约，不能各自发明字段。

## 研究边界

视觉特征是可解释测量，不是“好看”的真值；文化叙事是带来源的公共话语观察，不是历史起源或因果传播证明；审美结论必须基于真实受试者数据。模拟受试者和通用视觉模型只能用于预测试或辅助分析。

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

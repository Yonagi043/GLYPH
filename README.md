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

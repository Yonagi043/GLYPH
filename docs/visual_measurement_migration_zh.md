# Visual v1 与李婕 CV MVP 迁移说明

## 1. 兼容矩阵

| 来源 | 读取 | 写回 | Canonical 状态 |
|---|---|---|---|
| visual features v1.1 宽表 | 支持严格读取 | 支持确定性语义往返 | 历史兼容，不改写原运行 |
| visual measurements v2.0.1 长表 | 支持 | 支持 long export | 当前 canonical 原始测量 |
| 李婕 CV MVP 原始图片 | 通过根项目 shim 重跑 | 输出原始/诊断量 | 仅 diagnostic，禁止联合分析 |
| 李婕 MVP `total_score`/十项规则分 | 可作为历史文件保留 | 不迁移为测量值 | deprecated、uncalibrated |

## 2. visual v1 宽表

`glyph_features.vision_system.compat.v1_wide_to_long` 要求冻结的 33 列表头，未知列直接失败。空字符串迁移为 `null`，不会变成 0；分子、分母、单位、适用性和缺失原因逐项保留。输入 render 由 v1 run manifest 的 SHA-256 绑定，迁移资产 ID 从内容哈希确定性派生。

`glyph_features.vision_system.compat.long_to_v1_wide` 只接受带完整 `legacy_v1_context` 的迁移记录。普通 A/B/C v2 长表不能投影成 v1 宽表，因为 v1 的 glyph box、序列和 normalization 语义无法从 v2 像素记录补造。

参考运行 `data/processed/visual_features_v1/runs/render_551362ca0ff22f33/` 的 280 行可往返为 4,760 条记录并恢复原表语义。原目录保持只读。

### 2.1 v2.0.0 到 v2.0.1

v2.0.1 不改变 20 个 active 特征、8 个 deprecated v1 定义、canonical long measurement schema `1.0.0` 或默认算法参数。它修复 v2.0.0 对非 threshold 配置只哈希而未执行的实现缺陷。使用默认配置的旧测量可读取，但自定义 `component_connectivity`、`hole_connectivity`、`skeleton_algorithm`、`symmetry_alignment` 或 `tonal_bins` 的 v2.0.0 run 不能声明配置已被执行，必须在 v2.0.1 下重新提取。

TASK-02 handoff 从 `1.0.0` 升级为不向后兼容的 `1.1.0`：新包必须包含 TASK-01 handoff、asset candidates、stimuli 和 measured/supporting representations 的快照，并通过 accepted checkpoint 与逐 measurement 来源复验。旧 `1.0.0` handoff 不能通过降低 schema 继续发布，应从保留 TASK-01 来源的 v2.0.1 run 重新生成。

仓库中的 `reference_run_v1/` 与 `reference_handoff_v1/` 作为 v2.0.0/1.0.0 历史证据保留；当前可验证工件使用 `reference_run_v2/` 与 `reference_handoff_v2/`。

## 3. 李婕 CV MVP

原目录的理论、公式、字段字典、文献与检索日志全部保留。`lijie_aesthetic_cv/cv_program/` 作为历史原型保留，不再是第二套生产管线。新入口为：

```bash
uv run --frozen glyph-vision-legacy \
  --workspace-root . --input-dir <images> --output <new-output> \
  --representation A_layout
```

shim 使用根锁定环境和 v2 registry，不按文件 stem 命名，不覆盖已有输出，部分失败返回 1，输出路径为输入根相对 POSIX 路径，写入采用 fsync 后原子替换。它只输出 active 原始/诊断测量，并固定：

```text
joint_analysis_eligible=false
calibration_status=not_calibrated
```

若提供旧权重文件，只做严格兼容校验，不参与原始量计算；未知键、负数、全零、`NaN` 和 `Infinity` 均拒绝。权重只允许在未来有真人评分并绑定 `analysis_run_id` 的校准层中使用。

## 4. 不可迁移字段

旧 MVP 输出缺少 `stimulus_id`、TASK-01 `asset_id`、冻结表示、输入/配置哈希或完整变换链时，不得伪造这些字段。应从有来源链的原始图片重新进入 TASK-01；无法追溯的旧结果只能保留为历史 diagnostic artifact。

以下字段不得进入 v2 canonical 或 TASK-05 联合分析：

- `total_score`；
- 未经真人校准的十项 0–100 规则分；
- 把 `qi_proxy` 命名为直接观测“气韵”的字段；
- 未绑定 `analysis_run_id` 的手工权重结果。

## 5. 证据状态

`lijie_aesthetic_cv/04_参考文献与检索日志.md` 保留 A/B/C/D 证据等级和引用核验状态。Registry 的 `citation_ids` 与该日志对齐；映射表示理论支持强度，不表示代理已经通过真人构念效度或预测效度验证。

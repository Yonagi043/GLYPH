# GLYPH 可解释视觉测量协议 v2

版本：`visual_measurements_v2.0.0`

## 1. 系统边界

本协议只发布冻结表示下的可复现视觉事实，不发布审美真值或未经真人校准的综合分。知识结构固定为四层：

1. **表示**：TASK-01 冻结的 `A_layout`、`B_shape`、`C_ink` 及其资产 ID、SHA-256、变换和 QC；
2. **原始测量**：面积、比例、质心、对称、连通、骨架和灰度统计；
3. **理论构念映射**：八个视觉维度与 5+5 设计/书法构念的版本化多对多解释；
4. **真人校准模型**：未来仅在 TASK-03 真实评分下估计方向、非线性、权重与跨文化差异，并绑定独立 `analysis_run_id`。

前三层由本任务实现。第四层目前为 blocked，不得从工程 fixture 推断或补写。

## 2. Registry 与记录

`configs/visual_measurements_v2.yaml` 是定义源，使用 `schema/visual_feature_definition.schema.json` 验证。它包含：

- 8 个 visual v1 组织维度；
- 10 个理论构念；
- 20 个 active v2 原始或诊断特征；
- 8 个仅为 visual v1 历史往返保留的 `deprecated` 定义；
- 每项公式、单位、值域、输入表示、对象层级、分子/分母语义、缺失码、算法版本、配置哈希、构念映射、证据等级、跨文字可比性和已知偏差。

Canonical 长表由 `schema/visual_measurement.schema.json` 验证。`valid` 必须有有限数值且 `missing_code=null`；`missing` 必须有 `value=null` 和机器可读缺失码。JSON 写入禁止 `NaN` 与 `Infinity`。

`C5_qi_movement_proxy` 只接收方向、连续、粗细和连通等低层代理。它不是被直接观测的“气韵”，也没有独立分数。

## 3. 表示边界

| 表示 | 保留信息 | 允许解释 | 禁止替代 |
|---|---|---|---|
| `A_layout` | 原始相对位置、边距、画布占用 | 平衡、章法、整体比例代理 | 提取前自动居中 |
| `B_shape` | TASK-01 人工确认边界所对应的主体形状 | 对称、结构、轮廓、骨架代理 | 自动保留最大连通域 |
| `C_ink` | 灰度层次与边缘过渡 | 墨色、纹理、局部对比代理 | 无声二值化后声称测得墨法 |

连通域只描述像素组件，不推断字符或 cluster。点、变音符、细 serif、分离点画、jamo、浊点、飞白和复合 logo 小组件均不得默认删除。

## 4. 可复现运行

验证 registry：

```bash
uv run --frozen glyph-vision validate-definitions \
  --workspace-root . --schema-root schema \
  --registry configs/visual_measurements_v2.yaml
```

从已接受的 TASK-01 许可 fixture 提取：

```bash
uv run --frozen glyph-vision extract \
  --workspace-root . --schema-root schema \
  --registry configs/visual_measurements_v2.yaml \
  --asset-handoff data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json \
  --output-dir <new-run-directory> --run-id <new-run-id> \
  --computed-at <RFC-3339-time> --allow-fixture
```

随后运行：

```bash
uv run --frozen glyph-vision qc \
  --workspace-root . --schema-root schema --run-dir <new-run-directory>
```

输出目录不可覆盖。任一意外样本失败返回 1，同时保留已完成记录与 `failures.jsonl`；契约/操作错误返回 2；覆盖请求返回 3。

## 5. QC 与效度

QC 分开报告：

- **输入与配置完整性**：TASK-01 handoff、资产、registry、算法配置和输出 SHA-256；
- **计算稳定性**：相同输入和配置重复计算是否一致；
- **表示/阈值敏感性**：变化超过冻结阈值时标记 `needs_review`，不改写原值；
- **表面效度**：等待两名独立视觉或字体领域审核者，`GATE-EXPERT` blocked；
- **构念效度**：等待专家审阅及 TASK-03 真人关联；
- **预测效度**：等待真人评分、冻结分析计划和留出验证。

因此 `engineering_ready=true` 不推出 `pilot_ready=true` 或 `research_validated=true`。

## 6. 参考运行

`data/fixtures/visual_measurements/reference_run_v1/` 是 CC0 工程 fixture：1 个 stimulus、3 个表示、60 条 active 测量、0 提取失败。它用于 schema、确定性、敏感性、checksum 和下游接线回归，不是公共 release、真人 pilot 或审美结论。

当前参考运行有 19 条有效值、41 条显式缺失和 14 条阈值敏感性 warning。表面、构念和预测效度均保持 blocked。

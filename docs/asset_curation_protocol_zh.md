# GLYPH 资产策展与刺激冻结协议 v1

版本：`1.0.0`
状态：工程参考实现；正式资产权利和人工策展未通过
配置：`configs/asset_curation_v1.yaml`

## 1. 范围与边界

本协议只治理 DFA、Indigo、WOLDA、Golden Pin、GDC 五个奖项图包，以及现有字体包。奖项图片是生态候选，不是审美正例，也不等于干净 logo。目录名、奖项标签、自动分类和字体内部元数据都不能替代人工内容判断或许可判断。

正式资产当前只允许本机盘点、哈希、QC 和人工审核准备。公开参考链只处理 `data/fixtures/asset_system/open_fixture.pgm`；该文件由项目生成并以 `CC0-1.0` 提供，但其刺激始终保持 `fixture_only`。

## 2. 对象链

```text
legacy source table
  -> source record + migration event
  -> original asset candidate
  -> automated QC + classification suggestion
  -> human curation decision + confirmed target geometry
  -> A_layout / B_shape / C_ink (+ mask)
  -> ecological stimulus
  -> handoff manifest + checksums + gate packets
```

稳定标识均由规范 JSON 条件的 SHA-256 派生。原始资产、派生资产和刺激使用不同 ID；条件变化产生新 ID。任何派生文件都不得覆盖父文件或同名旧输出。

## 3. 契约与兼容性

| 对象 | Schema | 版本 | 与既有契约关系 |
|---|---|---:|---|
| 来源 | `schema/source.schema.json` | `1.1.0-compatible` | 沿用冻结来源字段；许可依据另存 rights evidence |
| 候选资产 | `schema/asset_candidate.schema.json` | `1.0.0` | 新增对象，不把候选伪装成刺激 |
| 权利证据 | `schema/rights_evidence.schema.json` | `2.0.0` | 必填 `permitted_uses`；ID 绑定完整证据内容；不作法律判断 |
| 受控字体刺激 | `schema/stimulus.schema.json` | `1.1.0` | 字段与含义不变 |
| 生态/fixture 刺激 | `schema/ecological_stimulus.schema.json` | `2.0.0` | 必填权利证据 ID 与用途；与字体刺激并列读取 |
| 交接清单 | `schema/handoff_manifest.schema.json` | `2.0.0` | 必填、可验证的 producer source snapshot；不向后兼容 1.0.0 |

旧 manifest 的 12 位 SHA-1、平台路径和工作目录语义不会被静默接受。`audit-sources` 读取旧表、保留旧表 SHA-256，并输出规范记录和逐条修复事件；旧文件本身不改写。

## 4. 来源与权利

每条来源记录至少有稳定 `source_id`、URL、访问日期、许可状态和可选本地存档 SHA-256。抓取时间只表示访问，不表示授权。

权利层级含义：

- `open`：有可核验开放许可；仍受用途和 fixture/release 状态约束。
- `research_local_only`：仅允许经批准的本地研究处理，不允许公开再分发。
- `metadata_only`：只交接描述、哈希和引用，不交接二进制。
- `blocked_unknown`：许可或用途未核验，默认阻断冻结与发布。

`rights_evidence` 将许可 URL、文本/标识、页面快照、核验人、决定状态和 `permitted_uses` 分开保存。`rights_evidence_id` 由除自身外的完整证据内容派生；任一字段改变而 ID 未改变时，冻结返回 `RIGHTS_EVIDENCE_ID_MISMATCH`。冻结还要求 `source_id`、`rights_tier`、`decision_status=passed` 和实际用途一致。字体 name table 中的许可字符串仅作线索，不能单独把字体升级为 `open`。正式判断停在 `GATE-RIGHTS`；登录、付费、接受条款或首次受限请求停在 `GATE-TERMS`。

## 5. QC 与内容分类

自动 QC 检查完整 SHA-256、安全解码、像素上限、格式、精确重复、感知近重复和目标边界状态。超像素限制的图片不计算感知哈希，避免解码资源失控。感知近重复只产生人工复核建议，不自动合并作品。

自动主类仅能写入 `classification.automated_suggestion`。真人决定写入 `human_decision`；fixture 协议断言写入独立的 `fixture_decision`，二者不可互相替代。人工通过必须同时具备：

1. 合格内容类；
2. 审核人和时间；
3. 确认的 bbox/polygon；
4. 权利层级满足用途；
5. 自动 QC 无阻断失败。

`review_queue.csv` 中的建议列只用于分流。审核者填写 `human_decision`、`curation_status`、`target_bbox_json` 或 `target_polygon_json`、`reviewer_id`、UTC `reviewed_at`、排除码和备注。`import-curation` 生成新 JSONL，不改写输入；随后从工作区实体文件重新核验路径、大小、SHA-256、解码、格式、像素上限和确认几何。只有 post-curation QC 真实为 `passed` 才保留人工 `passed`；人工字段不能覆盖自动失败。

## 6. A/B/C 表示

### A_layout

保留原画布、边距和相对位置，仅执行安全解码、EXIF 方向修正和无损 PNG 输出。不得裁主体、强制居中或拉伸。

### B_shape

使用人工确认边界裁取目标，等比放入配置化画布，并同时输出 shape 与 mask。bbox 使用 `[left, top, right, bottom]`；polygon 使用扁平 `[x1, y1, x2, y2, ...]`，至少三个非共线点。polygon 先生成确定性像素掩膜，其外部置白，再按外接整数 bbox 裁切。记录 geometry type、polygon（如适用）、整数 bbox、缩放、偏移、画布、阈值和 3x3 变换矩阵。未确认或越界几何机械失败。

v1 的 `asset_role=mask` 仅指 B_shape 的阈值形状掩膜，不是源图 alpha 通道，也不声称支持 alpha mask。alpha mask 已从 v1 能力声明中排除；若后续需要，必须在协议 2.0 中新增独立 `alpha_mask` role、合成规则、schema 版本与像素测试，不能复用 v1 `mask` 偷换语义。

### C_ink

保留灰度层次，通过角区中位数估计背景并记录校正参数。输入灰阶不足时返回 `C_INK_NOT_APPLICABLE`，不得制造纹理层次。

A/B/C 描述保留的信息；`bbox_height_matched` 和 `ink_area_matched` 描述受控字体渲染条件。两套枚举并存，不互相改名或覆盖。

## 7. 冻结与发布阻断

正式 `stimulus_id` 只在来源、权利、人工分类、目标边界、QC 和所需表示全部通过后生成。`freeze-stimuli` 在构造刺激前逐条 schema 校验 original/derived，并用统一解析器核验规范相对 POSIX 路径、解析后工作区边界、普通文件、实际字节数和完整 SHA-256；最终 stimulus schema 不能替代这些真实性检查。fixture 可用 `fixture_protocol` 走完整工程链，但也必须消费允许 `engineering_fixture` 的 passed evidence，并输出 `release_status=fixture_only`。

以下情况机械阻断：

- `blocked_unknown` 权利；
- 人工策展未通过；
- 缺少目标边界或父哈希不匹配；
- A/B/mask 不完整；
- fixture 缺 C_ink；
- 企图将 fixture 作为正式发布；
- 目标输出已存在。

正式发布还须单独通过 `GATE-RELEASE`。本协议不提供绕过参数。

## 8. CLI

所有命令通过锁定环境运行：

```bash
uv run --frozen glyph-assets audit-sources --output-dir <new-dir>
uv run --frozen glyph-assets inventory --output-dir <new-dir>
uv run --frozen glyph-assets qc --output-dir <new-dir>
uv run --frozen glyph-assets build-review-queue --output <new.csv>
uv run --frozen glyph-assets import-curation --candidates <jsonl> \
  --decisions <curation_decisions.csv> --output <new.jsonl>
uv run --frozen glyph-assets transform --candidates <jsonl> \
  --representation A_layout --output-dir <new-dir>
uv run --frozen glyph-assets freeze-stimuli --originals <jsonl> \
  --derived <jsonl> --rights-evidence <jsonl> \
  --created-at <UTC> --output <new.jsonl>
uv run --frozen glyph-assets validate-handoff <handoff_manifest.json> \
  --workspace-root . --schema-root .
uv run --frozen glyph-assets export-handoff --output-dir <new-dir> \
  --git-commit <40-hex> --created-at <UTC>
```

各写命令支持 `--dry-run` 和 `--failure-output <jsonl>`。输出文件使用排他创建，输出目录必须不存在或为空。退出码：

| 退出码 | 含义 |
|---:|---|
| `0` | 全部成功 |
| `1` | 批处理中至少一条记录失败，成功输出可保留并有失败 JSONL |
| `2` | 命令级配置、解析或运行错误 |
| `3` | no-overwrite 冲突 |

## 9. 参考交接包

`data/fixtures/asset_system/reference_handoff_v1/` 是工程参考运行。它包含：

- 五奖项与字体的 metadata-only 来源、候选、QC、权利待审记录和审核队列；
- CC0 fixture 的 original、A_layout、B_shape、mask、C_ink 和生态刺激；
- 运行环境、输入快照、质量报告、checksums 和四个人工门禁包；
- handoff 2.0 producer provenance：base commit、全工作树 clean/dirty 状态、producer 是否匹配基线、实现/schema/config/入口逐文件哈希与聚合哈希；
- `engineering_ready=true`、`pilot_ready=false`、`research_validated=false`。

下游只能把 fixture 用于契约/算法测试。TASK-03 不得把它当正式可呈现样本；TASK-04 只能读取字体 metadata，不能据此再分发字体；TASK-05 必须保留 blocked 状态。正式资产需在权利和人工策展通过后生成新的不可变 handoff。

handoff 1.0 只记录 40 位 commit，不能证明 dirty producer，因而不与 2.0 向后兼容。2.0 validator 会重建 producer 文件集合、核验逐文件和聚合 SHA-256、检查 base commit 真实存在及 snapshot/base 匹配声明，并扫描 reference handoff 全目录中的本机绝对路径。运行环境只记录 Python 版本、实现、平台和依赖版本，不记录解释器绝对路径。

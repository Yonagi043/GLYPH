# TASK-01：资产治理、五奖项图包与统一刺激子系统

版本：`0.1.0-draft`
日期：2026-09-04
建议执行顺序：第一项
系统角色：所有研究线的来源、资产和刺激入口

## 1. 给执行 Agent 的任务指令

你负责把现有“图包与字体包”完善为 GLYPH 可长期使用的**资产治理与刺激策展子系统**。你的交付不是再下载更多图片，也不是把 375 张图批量转灰度，而是建立从来源、许可、原始候选、人工策展、派生表示、稳定刺激 ID 到下游交接的完整可审计链路。

必须先阅读：

- `docs/agent_tasks/00_system_blueprint_zh.md`
- `status/four_research_lines_zh.md`
- `schema/README.md`
- `schema/source.schema.json`
- `schema/stimulus.schema.json`
- `schema/shared.schema.json`
- `status/visual_analysis_framework_zh.md`
- `status/visual_feature_v1_proposal_zh.md`
- `data/README.md`
- `图包与字体包/README_字体审美.md` 及该目录全部脚本、来源表和 manifest

开始前先核对 Git 状态、远端 HEAD、用户未提交修改和实际文件统计。本文记录的数量是 2026-09-04 的审查基线，不可替代重新核验。

## 2. 系统定位

本子系统是四条研究线共用的“入口闸门”：

- 为 WP1 提供可盲评、可随机化、权利状态明确的冻结刺激；
- 为 WP2 提供来源和对象身份，不把获奖状态写成审美事实；
- 为 WP3 提供用途明确的 A/B/C 表示和可复现变换；
- 为 WP4 提供字体/字形来源、字符覆盖和专家策展接口；
- 为总装提供稳定 `source_id`、`asset_id`、`stimulus_id` 和交接清单。

本任务不定义审美指标、不训练审美模型、不设计正式问卷、不招募受试者，也不替版权持有人作许可判断。

## 3. 当前基线与必须解决的问题

以实际仓库核验为准，已知基线包括：

- 字体包覆盖拉丁、汉字、韩文、片假名四组；设计目标是每组 3 个字族，实际有 13 个字体文件，因为 Lato 含两个字重；
- 图包接受 5 个奖项：DFA、GDC、Golden Pin、Indigo、WOLDA，不再寻找第 6 个；
- 当前有 375 个原始图片文件和 375 个单通道灰度输出；
- GDC 来源表存在列错位，Golden Pin 存在重复记录，WOLDA 存在悬空 preloader/manifest 记录；
- WOLDA、DFA 等目录包含展板、场景照、类别页眉和说明文字，不全是孤立 logo；
- 存在完全重复图片、超大像素图片和来源表行数与文件数不一致；
- 当前 manifest 使用平台相关路径、12 位 SHA-1、绝对/工作目录语义和日期命名，不能作为正式可移植契约；
- 当前脚本在部分失败后仍可能返回成功，不记录锁定环境，也没有 no-overwrite 保证；
- 图片和字体已直接进入 Git，新增历史体积约 604 MiB，且没有 Git LFS；
- 图片来源记录不等于再分发许可；根 MIT 许可证不覆盖第三方图片和字体。

不得通过删除几行 CSV 或把错误样本排除在统计之外掩盖这些问题。

## 4. 不可改变的设计决定

1. **只维护现有 5 个奖项**。缺少第 6 个不是失败；数据质量和权利优先于凑数。
2. **奖项图片是生态候选，不是审美正例**。禁止使用 `award=true` 作为美丑标签。
3. **目录名不是内容证明**。每张图必须经过内容分类，才能成为问卷或视觉刺激。
4. **原始资产不可覆盖**。所有裁切、缩放、灰度化和掩膜都是有父子关系的新资产。
5. **受限资产不进入公开 release**。未知许可默认为阻断，不按“学术用途”推定可再分发。
6. **不改写 Git 历史**，除非用户通过 `GATE-HISTORY` 明确批准。
7. **不把现有 visual features v1 推倒重做**。受控字体刺激与奖项生态刺激是不同数据层。

## 5. 规范对象与接口

### 5.1 来源记录

所有来源必须投影到现有 `source.schema.json`，至少记录：

- `source_id`
- 来源类型、标题、URL、发布者/创作者、访问日期
- `license_status`
- `license_text_or_id`
- `redistribution_allowed`
- 本地存档 SHA-256（允许本地受限、公开为空）
- 许可判断所依据的 URL、页面快照哈希和核验日期

同一图片文件可有作品页和文件 URL 两级来源，但必须明确主来源及关系。抓取时间不能伪装成授权日期。

### 5.2 候选资产契约

现有 schema 不足以表达“尚未成为刺激的文件候选”。实现时新增一个最小、版本化的候选资产 schema（建议 `schema/asset_candidate.schema.json`），不得把候选硬塞成已通过的 `stimulus`。

最低字段：

| 字段 | 要求 |
|---|---|
| `asset_id` | 稳定、不透明、全局唯一 |
| `source_id` | 必须能回到规范来源 |
| `parent_asset_id` | 派生资产必填；原始资产为空 |
| `asset_role` | `original` / `A_layout` / `B_shape` / `C_ink` / `mask` / `thumbnail` |
| `candidate_kind` | `font_file` / `ecological_award_image` / `isolated_wordmark` / `controlled_font_specimen` / `han_style_specimen` |
| `asset_ref` | 相对 POSIX 路径、完整 SHA-256、MIME、字节数 |
| `pixel_metadata` | 宽、高、模式、色彩空间、alpha、DPI（未知可空） |
| `rights_tier` | `open` / `research_local_only` / `metadata_only` / `blocked_unknown` |
| `transform` | 工具版本、配置哈希、父哈希、裁切框/矩阵、参数；原始资产为空 |
| `automated_qc` | 可解码、像素上限、哈希重复、感知重复、边界和格式结果 |
| `curation_status` | `pending` / `passed` / `excluded` / `needs_review` |
| `exclusion_codes` | 冻结枚举，不只写自由文本 |
| `review` | 审核人、时间、决定和原始建议分开保存 |

新增 schema 时必须同步模板、验证器、fixture、版本说明和契约测试。历史核心 schema 字段含义不得改变。

### 5.3 内容分类

每张奖项候选至少归入一个主类：

- `isolated_wordmark_clean`
- `logo_lockup_with_symbol`
- `project_board_or_poster`
- `mockup_or_scene`
- `award_header_or_navigation_asset`
- `call_for_entries_or_non_winner`
- `duplicate_exact`
- `duplicate_near`
- `unreadable_or_corrupt`
- `rights_blocked`
- `uncertain`

自动模型只能建议分类，不能直接写入人工 gold。若同一作品有多张图，必须有 `work_id`/组关系，避免把同一设计当成独立样本。

### 5.4 刺激契约

只有满足以下条件的候选才可生成 `stimulus_id`：

1. 来源和资产 SHA-256 完整；
2. 用途所需的许可/本地研究状态明确；
3. 内容分类和目标主体经人工确认；
4. 对应表示生成成功且变换可复现；
5. 刺激条件、研究线、语义状态和 QC 写入 manifest；
6. 不与已有刺激条件冲突或覆盖。

现有 `stimulus.schema.json` 主要面向字体渲染，不能自然表达所有生态图片。先写一份 schema gap 说明；若需要扩展，采用次版本或独立生态刺激 schema，并提供迁移/联合读取策略。不得删除字体刺激所需的 `shaping`、`font`、`anchors` 等语义来迁就图片。

## 6. 三通道表示协议

### 6.1 A：`A_layout`

目的：保留生态构图、真实边距、主体相对位置和版面关系。

允许：安全解码、EXIF 方向修正、明确记录的色彩空间转换、生成无损副本/缩略图。
禁止：自动裁主体、居中、强制正方形、非等比缩放、去除说明文字后仍声称保留原版面。

### 6.2 B：`B_shape`

目的：比较经人工确认的目标字标/字形轮廓。

要求：

- 使用人工确认的 bbox、polygon 或 alpha mask；
- 自动分割只能产生待审候选；
- 等比缩放，不拉伸；
- padding、anchor、画布和阈值进入协议配置；
- 目标主体不明确时标记 `needs_review`，不强行裁切；
- 保留父资产、裁切框、变换矩阵和 mask 哈希。

### 6.3 C：`C_ink`

目的：保留灰度/色彩层次、墨色、材质和边缘扩散信息。

要求：保留原始色彩副本和背景校正参数；纸张、曝光、压缩与抗锯齿作为质量协变量。纯数字黑白图允许明确标记 `not_applicable`，不能制造墨色层次。

### 6.4 与现有字体 v1 的关系

现有 `bbox_height_matched` 和 `ink_area_matched` 是受控字体刺激的两个 render profile，不应被 A/B/C 名称覆盖。建立明确映射表：

- render profile 描述“如何控制字体渲染条件”；
- A/B/C 描述“为哪种分析保留什么信息”；
- 同一资产可能只适用其中部分表示；
- 下游每条特征记录必须指明实际表示和 normalization profile。

## 7. 字体包治理

1. 明确 12 个主字族与额外字重/变体的关系，不把 13 个文件误报成 13 个独立字体家族；
2. 每个字体登记家族名、PostScript 名、版本、变量轴、静态实例、Unicode 覆盖、地区字形、SHA-256、许可证及可再分发状态；
3. 字体目录随附许可证/NOTICE 或受限获取说明，不能只依赖字体内部 name table；
4. 修复拉丁样本文本中混入 Cyrillic `р` 的问题，并增加 Unicode 脚本断言；
5. 字体样张使用冻结 content set、显式语言/脚本、HarfBuzz shaping 和固定环境；
6. 不把字体包中的 12 个字族自动替换现有 visual v1 已冻结字体矩阵；若要建立扩展实验，另起协议版本。

## 8. 五奖项治理

接受以下现实年份结构并准确表述：

- DFA：2020–2024；
- Indigo：2020–2024；
- WOLDA：2020–2024，但内容纯度风险高；
- Golden Pin：现有连续年度范围按实际来源记录，不伪造缺失年份；
- GDC：双年展届次覆盖近五年窗口，不表述为五个自然年度。

必须完成：

1. 修复并统一五份来源表字段；
2. 一文件一规范资产记录，额外页面/作品关系单独表达；
3. 清除来源表重复行但保留修复日志和旧文件哈希；
4. 对悬空文件、重复图片、跨年复用、非作品资产和超大像素图生成明确 QC 记录；
5. 生成按奖项、年份、内容类别、权利层级和唯一作品数的质量报告；
6. 不因清洗后样本减少而回填低质量图片；
7. 报告“文件数、唯一二进制数、唯一作品数、通过策展数”，不得只报一个总数。

## 9. Git 与大文件治理

先产出 `asset_history_remediation_plan_zh.md`，至少比较：

- 保留现状；
- 只从当前 tip 删除（不能缩小历史）；
- 迁移到本机受限目录/可复现下载；
- 使用 DVC、外部研究存储或 Git LFS；
- 使用 `git filter-repo` 重写历史后的团队影响、备份、通知、重新 clone/rebase 和回滚。

你可以在临时 clone 演练并记录前后 pack 大小，但未经 `GATE-HISTORY` 不得对主仓库 force push，不得擅自删除远端资产。未经 `GATE-RIGHTS` 也不得上传到新的第三方存储。

## 10. 建议实现边界

建议新增或整理为：

```text
schema/
  asset_candidate.schema.json
configs/
  asset_curation_v1.yaml
src/glyph_features/asset_system/
  catalog.py
  rights.py
  qc.py
  transform.py
  curation.py
  export.py
data/templates/
  asset_candidates.csv
  curation_decisions.csv
data/fixtures/asset_system/
docs/
  asset_curation_protocol_zh.md
```

实际命名可按仓库惯例微调，但公开接口和职责不得消失。不要把逻辑继续堆进一次性脚本。所有可调阈值进入 JSON-compatible YAML 配置并参与 SHA-256。

最低 CLI：

```text
glyph-assets audit-sources
glyph-assets inventory
glyph-assets qc
glyph-assets build-review-queue
glyph-assets transform --representation A_layout|B_shape|C_ink
glyph-assets freeze-stimuli
glyph-assets validate-handoff
```

命令必须支持 dry-run、no-overwrite、明确退出码和失败 CSV/JSONL。部分失败不能返回 0。

## 11. 实施阶段

### 阶段 A：只读盘点

- 固定当前 Git 树、文件数、字节数、哈希和来源表快照；
- 输出 known-issues，不修改原始资产；
- 用小型合成 fixture 先验证 schema 和 CLI。

### 阶段 B：来源与许可

- 将来源表迁移到规范记录；
- 核验字体许可证与五奖项使用/再分发条款；
- 未能核验的标为 `unknown`/`blocked_unknown`；
- 到达权利人工判断时触发 `GATE-RIGHTS`。

### 阶段 C：QC 与策展队列

- 解码、像素、哈希/感知重复、URL、记录一一对应检查；
- 内容分类建议和人工审核 UI/表单；
- 不自动把建议升级为通过。

### 阶段 D：派生表示

- 先在许可明确的 fixture 上实现 A/B/C；
- 做重复运行、跨平台路径、no-overwrite 和变换可逆审计；
- 正式资产只生成本机研究表示，不默认进入 release。

### 阶段 E：冻结刺激与交接

- 只为人工通过资产分配刺激；
- 生成 schema 验证、checksums、quality report 和 handoff；
- 分别标记 `engineering_ready`、`pilot_ready` 和被人工门禁阻塞的状态。

## 12. 测试与验收

### 12.1 自动测试

至少覆盖：

- 来源 CSV 列错位、重复行、缺列、额外列和非法 URL；
- Windows/Unix 路径归一化；
- SHA-256、完整文件读取和篡改检测；
- 完全重复、感知近重复和同作品分组；
- 灰度、RGB、RGBA、调色板图、EXIF 旋转、损坏图和超大像素防护；
- 透明/白/黑/复杂背景的 A/B/C 行为；
- 变换父子链和参数哈希；
- Unicode 样本文本脚本纯度；
- no-overwrite、幂等、空输入、部分失败非零退出码；
- 许可未知阻断刺激 release；
- 候选不能绕过人工策展直接变成正式刺激。

### 12.2 最低可执行验收

1. 所有现有字体文件进入资产清单，12 个主字族与额外字重关系清楚；
2. 375 个原图逐文件有 `asset_id`、SHA-256、规范来源或明确缺失状态；
3. 来源表解析后不存在静默列错位，重复/悬空记录有迁移日志；
4. 文件数、唯一哈希数、唯一作品数和策展通过数分别报告；
5. 至少一组完全开放 fixture 端到端产生 A/B/C、刺激记录、checksums 和 handoff；
6. 任一许可未知、内容未审或 QC 失败样本无法进入 release；
7. 重跑得到相同派生哈希；条件改变生成新 ID 且不覆盖旧文件；
8. 全仓既有测试继续通过，新增测试接入根 `pytest`；
9. Git 历史问题有可执行方案，但主历史未在无批准情况下改写；
10. 文档明确五奖项边界，不把现有图包宣称为 375 个干净 logo。

## 13. 对下游的交接

`handoff_manifest.json` 必须分别提供：

### 给 TASK-02 视觉测量

- 可用于测试的 A/B/C fixture；
- 表示定义、变换配置、mask、QC 和算法配置哈希；
- 正式候选中哪些表示可测、哪些需人工处理。

### 给 TASK-03 跨文化实验

- 可呈现刺激清单；
- 盲化展示资产、固定尺寸建议、权利/隐私用途；
- 奖项和来源标签的独立元数据，默认不随盲评呈现。

### 给 TASK-04 汉字书体

- 字体资产、许可证、字符覆盖、地区字形和静态实例接口；
- WP4 候选资产角色和专家审核入口。

### 给 TASK-05 总装

- 来源/资产/刺激 API 或导出契约；
- 队列、QC、权利门禁和运行状态读取接口；
- 不能公开或不能进入分析的机器可读原因。

## 14. 强制停止条件

出现以下任一情况必须停止相关切片并报告：

- 需要代表用户接受网站条款、登录、付费或申请访问；
- 需要认定版权例外或公开受限图片；
- 需要 force push、历史重写或迁移远端大文件；
- 自动分割无法可靠确定目标字标；
- 需要改变冻结 stimulus/visual v1 字段含义；
- 正式实验刺激仍含无法盲化的奖项、作者或品牌线索；
- 用户本地未提交修改与任务修改无法安全合并。

停止时提交门禁包和本文总蓝图要求的最终报告，不自动进入 TASK-02。

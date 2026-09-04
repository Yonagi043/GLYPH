# TASK-01 资产治理与统一刺激子系统报告

版本：`1.1.0`（首次独立验收定向整改版）
生成时间：2026-09-04T04:07:50Z
Git 基线：`f89daec0e5e1f2df216a8e18c551d81f9954032f`

## 1. 实际完成范围

本任务只完成 TASK-01：DFA、Indigo、WOLDA、Golden Pin、GDC 五奖项图包、现有字体包、候选资产、权利证据、QC、人工策展入口、A/B/C 表示、生态刺激和跨任务交接。未下载新资产，未登录、付费或接受条款，未修改原始图片/字体/旧来源表，未改写 Git 历史，未进入 TASK-02。

工程链已闭合：

```text
旧来源表 -> 规范来源/迁移事件 -> 候选资产 -> QC/自动建议
-> 人工审核队列 -> import-curation/物理 post-QC
-> A/B/C fixture -> 权利证据绑定 -> 稳定刺激 -> checksums/handoff 2.0
```

正式资产停在权利与人工策展门禁；只有项目生成的 CC0 fixture 走完派生与冻结链。

## 2. 关键文件与公开接口

- `schema/asset_candidate.schema.json`：候选与派生资产契约 `1.0.0`。
- `schema/ecological_stimulus.schema.json`：生态图像/fixture 刺激及权利用途绑定契约 `2.0.0`。
- `schema/rights_evidence.schema.json`：许可依据、完整内容 ID 与允许用途契约 `2.0.0`。
- `schema/handoff_manifest.schema.json`：输入/输出、哈希、门禁、readiness 和 producer source snapshot 契约 `2.0.0`。
- `configs/asset_curation_v1.yaml`：五奖项根、QC 阈值、A/B/C 参数、fixture 与发布策略。
- `src/glyph_features/asset_system/`：catalog、QC、rights、curation、transform、export、CLI。
- `glyph-assets`：`audit-sources`、`inventory`、`qc`、`build-review-queue`、`import-curation`、`transform`、`freeze-stimuli`、`validate-handoff`、`export-handoff`。
- `data/templates/asset_candidates.csv`、`curation_decisions.csv`：批量登记与人工审核入口。
- `data/fixtures/asset_system/open_fixture.pgm`：16x12、`CC0-1.0` 开放 fixture。
- `docs/asset_curation_protocol_zh.md`：操作、兼容、退出码与下游边界。
- `docs/asset_history_remediation_plan_zh.md`：`GATE-HISTORY` 方案与演练/回滚要求。

九个子命令已从安装入口实际加载。写命令支持 dry-run、排他创建和失败 JSONL。退出码 `0/1/2/3` 分别表示全部成功、记录级部分失败、命令级失败和 no-overwrite 冲突；每个命令级失败只向 stderr 或指定 failure output 发射一次 JSON failure。

## 3. Schema、配置与迁移

冻结的 `shared`、`source`、受控字体 `stimulus` 和 visual v1 参数含义未改变。`asset_candidate` 保持 `1.0.0`；`rights_evidence`、`ecological_stimulus`、`handoff_manifest` 升级到 `2.0.0`。生态刺激仍采用并列 schema，不删除 `shaping`、`font`、`anchors` 等字体语义。handoff 2.0 因新增必填 producer snapshot 明确不向后兼容 1.0；下游必须按 `logical_type` 和 schema 版本分派读取。

schema-valid 不再被当作实体真实性。transform 和 freeze 共用 `resolve_workspace_asset`，在解码或冻结前机械验证规范相对 POSIX 路径、strict resolve 后工作区包含关系、普通文件、实际字节数与完整 SHA-256。rights evidence 2.0 的 ID 绑定除自身外的完整内容，freeze 还要求唯一 source、`decision_status=passed`、tier 与实际 `intended_use` 一致。

旧 manifest 的 12 位 SHA-1、平台路径和工作目录语义不被静默兼容。迁移器读取五份旧表并保留各自完整 SHA-256；规范输出统一使用相对 POSIX 路径和完整 SHA-256。实际迁移事件：

| 事件 | 数量 |
|---|---:|
| `GDC_SHIFTED_COLUMNS` | 15 |
| `SOURCE_DUPLICATE_FILE_ROW` | 18 |
| `SOURCE_FILENAME_EXTENSION_REPAIRED` | 25 |
| `SOURCE_WITHOUT_FILE` | 10 |

旧表共 403 行，规范迁移输出 385 行；重复和悬空记录保留在 68 条问题日志中，而不是从证据中静默消失。

## 4. 输入、输出、记录数与哈希

真实只读库存：

| 指标 | 数量 |
|---|---:|
| 奖项原图文件 | 375 |
| 图像唯一 SHA-256 | 372 |
| 唯一作品 | 358 |
| 字体文件 / 主家族 | 13 / 12 |
| 候选资产 | 388 |
| 超像素上限图像 | 4 |
| 精确重复文件 | 6 |
| 感知近重复建议 | 17 |
| 正式策展通过 | 0 |

奖项拆分：DFA `80/80/80/0`、Indigo `90/90/90/0`、WOLDA `87/84/85/0`、Golden Pin `72/72/72/0`、GDC `46/46/31/0`；四个数字依次为文件、唯一二进制、唯一作品、策展通过。Golden Pin 按实际 2022-2025 四年记录，GDC 按 2021/2023/2025 三届记录，不伪造五个自然年度。

交接包关键输出：

| 输出 | 记录数 | SHA-256 |
|---|---:|---|
| `sources.jsonl` | 395 | `f180122abae5a829490ab2fb5ffe9495f27e6ac0247f72b2913bce54ca1def94` |
| `repository_asset_candidates.jsonl` | 388 | `7e1e4f1b9a01b050f2ce7bf0b831c9085ee5cb0223724d8d7b2c0dde2d792391` |
| `rights_evidence.jsonl` | 395 | `e9ab54f00970d8be674b77f4e1990b2396f18b4d92f05da32f97b6615f761273` |
| `source_migration.csv` | 385 | `2e9d432d3c56fe40b299c64f30e0365dae70a3aad8b363930d9b778b7a03e936` |
| `source_issues.csv` | 68 | `61286e2773390f99f1056cf536bd933af59e26aa78877d1304261820f2856d6f` |
| `review_queue.csv` | 388 | `bc8f9df09bb71150b623600b343375c5a090c2e94ab6f69f8fe390f1d1cdcc58` |
| fixture 候选 original+A+B+mask+C | 5 | `e132abc1bc2658315ac89a7d9c7772ac0bf3e510500eb8a8adda2d9c695c01ad` |
| fixture 刺激 | 1 | `a7c49d069effc90ba1d696e38681ff91326edfcfe874c0bf270dac4e368c6f4a` |
| `run_manifest.json` | 1 | `46c5c945fe38d3ae7c533ffacc118808a3f343cf6e72a51c6acdbd0f86d61a87` |
| `checksums.sha256` | 19 | `94fdcbb51c30f4a15ccb5b7ce790d368186143e293659105edc05ba34c90a7a4` |
| `handoff_manifest.json` | 1 | `acc193134495401b9a026aab0e7a866d7f15202b9b865db0d73d6f689bd1bdab` |

395 个来源由 381 个奖项页、13 个字体文件和 1 个生成 fixture 构成。权利证据中 394 条为 `pending_human_review`；仅 CC0 fixture 的 1 条为 `passed`。fixture 刺激 `stim_eco_ed82ad5985adf0287b9a` 绑定 `rights_3c47d3d61a9ed8ccecf2d519` 与 `engineering_fixture` 用途。

五个 visual v1 fixture `asset_id`（original、A、B、mask、C）与整改前逐项一致，视觉配置哈希保持 `b6373dd53dc648cecc51a229eae788ac43e855113fa75989b4675e1b5ba069c9`。rights evidence/stimulus 因 2.0 内容与用途绑定发生预期变化。

## 5. 测试与验收

- `uv run --frozen pytest tests/test_asset_system.py -q`：退出 `0`，`45 passed in 16.95s`。
- `uv run --frozen pytest -q`：退出 `0`，`233 passed in 24.66s`。
- `uv run --frozen glyph-assets export-handoff --workspace-root . --config configs/asset_curation_v1.yaml --output-dir data/fixtures/asset_system/reference_handoff_v1 --git-commit f89daec0e5e1f2df216a8e18c551d81f9954032f --created-at 2026-09-04T04:07:50Z`：退出 `0`，真实计数与 readiness 保持。
- `uv run --frozen glyph-assets validate-handoff data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json --workspace-root . --schema-root . --input-root .`：退出 `0`，`valid=true`、失败数 `0`。
- 全 reference 的 PCRE2 Unix/Windows 绝对路径独立扫描：未命中；包装命令退出 `0`。
- `uv lock --check`：退出 `0`，48 个包解析一致。
- `git diff --check`：退出 `0`，无空白错误。

专项覆盖来源列错位/重复/缺列/多列/非法 URL、歧义 basename、路径逃逸、SHA-256/字节数篡改、重复图、作品分组、图像模式、EXIF、透明/纯色背景、损坏/超像素、字体关系、Unicode 脚本、bbox/polygon A/B/C、父子 provenance、幂等/no-overwrite、空输入、部分失败、权利用途与人工策展阻断。

### 5.1 七项独立验收 finding 关闭证据

| Finding | 根因整改 | 直接回归 |
|---|---|---|
| Freeze 信任边界 | `catalog.resolve_workspace_asset` 与 `cli._freeze_records` 对全部 original/derived 做路径、实体、size、SHA-256 真值校验；rights 2.0 做完整内容 ID、唯一 source、passed、tier、用途校验 | `test_freeze_cli_rejects_missing_or_forged_derived_file`、`test_freeze_cli_rejects_derived_workspace_escape`、`test_freeze_cli_rejects_forged_rights_evidence_content`、`test_freeze_cli_requires_unambiguous_passed_rights_evidence` |
| Transform 越界 | `cli._transform_records` 在 Pillow 解码前调用同一 resolver；绝对路径、`..`、symlink 逃逸与实体篡改均稳定失败 | `test_transform_cli_rejects_workspace_escape_before_decode` |
| Basename 错配 | `catalog._resolve_source_file`/`_select_source_candidate` 保留同名全集，优先精确相对路径，再只接受 year-aware 唯一候选；歧义写 `SOURCE_FILE_AMBIGUOUS`，不再后写覆盖 | `test_source_migration_disambiguates_by_year_and_rejects_duplicate_basename` |
| 策展闭环 | 新增 `import-curation`；`apply_curation_decisions` 验证 reviewer、UTC、分类、状态、排除码与 bbox/polygon，随后从实体重跑 post-QC；人工 `passed` 不能覆盖自动失败 | `test_curation_decision_validates_human_fields`、`test_import_curation_cli_reruns_qc_before_transform`、`test_import_curation_cli_cannot_promote_corrupt_image`、真实库存 rights-only blocker 回归 |
| Polygon | `qc.target_geometry_bbox` 校验点数、偶数坐标、非退化面积和图像边界；`transform` 以确定性像素 polygon mask 置白外部区域并记录 geometry/matrix | `test_polygon_candidate_transforms_through_cli_with_masked_pixels` |
| Producer provenance | handoff 2.0 固化入口、锁、配置、六个 schema 和 asset-system 源码共 17 文件的 role/path/SHA-256 与聚合哈希；validator 重建集合并核验 base commit 与 match flag | `test_handoff_bundle_is_valid_immutable_and_detects_tampering` |
| 绝对路径泄漏 | run manifest 移除解释器路径；validator 扫描 handoff 目录全部文件，而非只扫 manifest outputs，覆盖 Unix/Windows 路径 | 同一 handoff 对抗测试中的未声明 `portability_probe.txt`，以及重建后全目录独立扫描 |

严格 handoff 验证会复验配置、fixture、五份旧来源表、全部声明输出和 producer snapshot 的路径安全、记录数、schema 与 SHA-256，并扫描 handoff 目录中未声明文件的绝对路径。

## 6. 产品行为与界面验收

TASK-01 没有新增图形界面；任务书最低产品面是 CLI、CSV 人工队列和机器可读 gate packet。CLI 安装入口和九个子命令已实际加载。部分失败保留成功记录但返回非零，并按 `asset_id` 输出失败 JSONL；已有输出和已有失败日志均不覆盖。

## 7. 研究有效性边界

- `engineering_ready=true`：契约、迁移、只读库存、QC、人工入口、fixture A/B/C、稳定 ID、checksums、handoff 与机械门禁可执行。
- `pilot_ready=false`：375 张图片和 13 个字体文件均为 `blocked_unknown`，正式策展通过数为 0。
- `research_validated=false`：未执行真人 pilot、专家审核、效度分析或研究结论验证。

奖项标签未写成审美标签；自动内容类未写入人工 gold；fixture 协议断言与 `human_decision` 分列保存。参考链只能证明工程可运行，不能证明刺激有效或研究结论成立。

v1 的 `asset_role=mask` 仅表示 B_shape 的阈值形状掩膜，不表示源图 alpha。alpha mask 未实现、未宣称可用；后续若需要，必须通过协议 2.0 新增独立 role、合成规则、schema 与像素回归，不能静默复用 v1 语义。

## 8. 未完成、降级与外部阻塞

- 未人工核验五奖项和字体的许可页、再分发范围及用途，正式资产全部阻断。
- 未人工判定 375 张图片的内容主类或目标 bbox，0 条可生成正式刺激。
- 4 张超像素上限图像未做感知哈希；17 条近重复仅是复核建议。
- 未执行 Git 历史重写。只读审计显示资产目录约 606 MiB、Git pack 547.82 MiB，另有 48.91 MiB 临时 pack 垃圾警告。
- 未访问受限站点、接受条款、付费、上传第三方存储或公开发布。

## 9. Handoff 与下游入口

规范交接清单：`data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json`。

该路径名为历史稳定入口，内部合同已是 handoff `2.0.0`。producer provenance 如实记录：base commit `f89daec0e5e1f2df216a8e18c551d81f9954032f`、`working_tree_state=dirty`、`producer_snapshot_matches_base=false`、17 个文件、聚合 SHA-256 `a633f59b59f477344ed2f3f509663d38a063c98db969353b93d7c025aa4daac9`。因此 base commit 不再被误当作当前未提交 producer 的证明。

- TASK-02：只可消费 `fixture/asset_candidates.jsonl` 的 A/B/C、mask 和变换配置哈希。
- TASK-03：正式可呈现刺激为 blocked；`fixture/stimuli.jsonl` 仅供呈现链测试。
- TASK-04：可读取 repository candidates 中的字体 metadata；权利与专家步骤仍阻断。
- TASK-05：可读取 catalog、QC、rights 和运行状态，但必须保留 readiness 与 gate 原值。

## 10. 等待人工批准的门禁

- `GATE-RIGHTS`：394 个真实来源的许可与用途证据待核验。
- `GATE-HISTORY`：需用户选择保留、本机受限、LFS、DVC/外部存储或历史重写方案。
- `GATE-TERMS`：任何登录、付费、接受条款或首次受限请求前需单独审核。
- `GATE-RELEASE`：权利、人工策展、QC 和下游协议未全部通过，禁止公开发布。

机器可读包位于 handoff 的 `gates/`；历史选项、团队影响和回滚步骤见 `docs/asset_history_remediation_plan_zh.md`。

## 11. TASK-01 完成定义逐条核对

| 条目 | 结果 | 证据 |
|---|---|---|
| 13 字体文件、12 主家族 | 满足 | inventory + font family report |
| 375 原图逐文件 ID/SHA/source 状态 | 满足 | repository candidates |
| 来源列错位/重复/悬空不静默 | 满足 | migration + 68 issues |
| 文件/二进制/作品/策展数分报 | 满足 | inventory summary + quality report |
| 开放 fixture A/B/C/checksums/handoff | 满足（fixture only） | fixture + manifest |
| 未知权利/未审/QC 失败阻断 release | 满足 | rights/freezing tests + gates |
| 重跑稳定、条件变化新 ID、不覆盖 | 满足 | deterministic/no-overwrite tests |
| 根 pytest 通过 | 满足 | 233 passed |
| 历史问题有方案且未擅改 | 满足（待人工门禁） | history plan + GATE-HISTORY |
| 五奖项边界与非干净 logo 声明 | 满足 | protocol + quality report |

## 12. 停止声明

TASK-01 在工程就绪、正式 pilot 与研究验证未就绪的真实状态下停止，等待独立复验。不会自动启动 TASK-02，不会替用户通过任何人工门禁。

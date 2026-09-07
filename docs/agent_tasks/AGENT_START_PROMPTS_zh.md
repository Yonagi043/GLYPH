# GLYPH 新 Agent 首条提示词与执行环境

## 现行 Autoresearch 入口（2026-09-07）

当前执行目标是充分利用已有资产并交付好用的研究系统。执行会话读取根目录 [AGENTS.md](../../AGENTS.md) 和 [AUTORESEARCH.md](../../AUTORESEARCH.md) 0.4，使用路线第12节 `research-usability-2` 恢复提示。C02/T01研究及判断续轮已完成，旧暂停与F1至F5记录仅为历史；A15另授权本轮成果提交、合并并推送main，不扩大原始数据或素材发布权限。当前授权、结果与恢复位置只在路线第7、8、12节维护；不重发已完成问卷，原则正文不改。

**下文为 2026-09-04 的 TASK 派发和首轮整改历史，不再是现行 autoresearch 启动指令。** 其中“当前只派发第 13 节”、旧 trusted HEAD、独立任务提交权限和当时的整改门禁均按历史语境阅读，不据此重派任务、回退工作树、重跑整改或取得 Git 权限。TASK-05 后续验收范围见 [docs/GLYPH_project_intro_zh.md](../GLYPH_project_intro_zh.md)，现存实现位置与本轮延续方式见新路线第 2 节；仍须保留历史事实和数据/权限边界。

以下原版本、状态、表格和提示保留作历史记录。

版本：`0.9.0-task05-remediation`
日期：2026-09-04
用途：记录 TASK-02、TASK-03、TASK-04 最终独立验收与集中合并结论、TASK-05 首轮独立验收结论；提供已实例化的 TASK-05 首次整改 prompt

## 0. 当前状态（TASK-05 首轮独立验收未通过）

TASK-01 已验收并提交。TASK-02、TASK-03 已通过第二轮独立验收，TASK-04 已通过第三轮独立验收；三项已集中合并并通过集成测试与四个上游 handoff validator。TASK-05 已形成实现提交和交接提交，但首轮独立验收复现了输入信任、数据库迁移、数据来源、失败审计、handoff 语义验证和浏览器键盘边界缺陷，结论为不通过。第 4 至 7 节首条 prompt、第 9 至 11 节首次整改 prompt 和第 12 节第二次整改 prompt 均只保留作审计记录；当前只向原 TASK-05 Agent 派发第 13 节。

本 `0.9.0-task05-remediation` 文件由协调工作区维护。TASK-02/03/04 worktree 固定在下表的 accepted HEAD；TASK-05 worktree 固定在首轮交接 HEAD。不要为了同步这份派发手册而修改任何实施 worktree 的 HEAD、分支或工作树。

| 任务 | worktree | 分支 | trusted HEAD | 结论 | 当前动作 |
|---|---|---|---|---|---|
| TASK-02 | `/Users/wuyida/Research/GLYPH-worktrees/task-02` | `feature/task-02-visual-measurement` | `c3c3d46ba00dbf88935a3821680454ebe56d6996` | **PASS / accepted** | 已集中合并；不再派发 |
| TASK-03 | `/Users/wuyida/Research/GLYPH-worktrees/task-03` | `feature/task-03-cross-cultural-experiment` | `87f914bdae036d83d8e3c44a1ab57219cabb1576` | **PASS / accepted** | 已集中合并；不再派发 |
| TASK-04 | `/Users/wuyida/Research/GLYPH-worktrees/task-04` | `feature/task-04-han-style-knowledge` | `48fbad87e84de5f323f9515c7f583c62b2cb7209` | **PASS / accepted** | 已集中合并；不再派发 |
| TASK-05 | `/Users/wuyida/Research/GLYPH-worktrees/task-05` | `feature/task-05-joint-workbench` | `79d254339fb6804fbfbc4140c9c305cda663ba60` | **FAIL / remediation required** | 向原 Agent 发送第 13 节 |

当前操作边界：

1. 不再向 TASK-02、TASK-03 或 TASK-04 Agent 发送 prompt，也不要改动三个 accepted worktree。
2. TASK-02/03/04 已集中合并到 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`；不要重复 merge、重建分支或改写集成历史。
3. TASK-05 不得合并或重新派发首条 prompt；只允许原 Agent 从 clean HEAD `79d254339fb6804fbfbc4140c9c305cda663ba60` 执行第 13 节定向整改。

## 1. 当前环境基线

以下是 2026-09-04 当前已经验证的本机事实。Agent 仍须在开始时重新检查，不能因本文记录而跳过基线检查。

| 项目 | 已验证状态 |
|---|---|
| 操作系统 | macOS，Apple Silicon `arm64`，交互 shell 为 zsh |
| 协调工作区根目录 | `/Users/wuyida/Research/GLYPH` |
| Git 当前状态 | 协调分支 `integration/task-01-accepted` 位于集成 commit `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9` |
| 受保护的本地修改 | 协调工作区的 `README.md` 和本文件含未提交修改；实施 Agent 不得覆盖或提交 |
| 现有 worktree | 协调工作区与 TASK-02/03/04/05 四个独立 worktree；四个实施 worktree 均位于第 0 节所列 HEAD，并已验证 clean |
| 磁盘余量 | 创建三个 worktree 前约 652 GiB；任务运行大体积操作前仍须复核 |
| Python 约束 | `pyproject.toml` 要求 `>=3.11,<3.12` |
| 可用项目 Python | `.venv/bin/python` 与 `uv run --frozen python` 均为 CPython 3.11.15 |
| 禁止误用的 Python | 系统 `python3` 为 3.9.6，不满足项目约束 |
| 环境管理 | `uv 0.11.23`；存在 Conda `glyph` 环境，但规范命令统一使用项目 `.venv`/`uv run` |
| 锁文件 | `pyproject.toml`、`uv.lock`、`runtime.lock.json` 均由 Git 跟踪 |
| 独立验收结论 | TASK-02 专项 `35 passed`/全仓 `268 passed`，PASS；TASK-03 对抗 `15 passed`、专项 `55 passed`/全仓 `288 passed`、桌面与移动 Playwright，PASS；TASK-04 第三轮聚焦 `10 passed`、专项 `43 passed`/全仓 `276 passed`，独立 adjudication、candidate 与重哈希 handoff 攻击通过，PASS |
| 集成验收 | 全仓 `366 passed`；TASK-01/02/03/04 strict handoff 均为 `failure_count=0`、`valid=true`；`uv lock --check` 和编辑器诊断通过 |
| TASK-05 首轮独立验收 | 两提交拓扑、TASK-05 `27 passed`、全仓 `393 passed`、五个 handoff validator、lock、前端语法和桌面/移动正向流程均通过；七类公开反例仍可复现，结论为 FAIL |
| TASK-01 handoff | `data/fixtures/asset_system/reference_handoff_v1/handoff_manifest.json` 已在集成 commit 上严格验证为 `valid=true` |
| 网络代理 | 外网及 Git HTTPS 使用 `http://127.0.0.1:7897`，只按命令设置，不修改全局配置 |
| 社会叙事数据库 | 源码目标 schema v17；生产主库有意保持 v14，未经批准只能使用显式临时数据库 |

`f89daec...` 只是 TASK-01 实施前的远端基线。TASK-02/03/04 的原始实施起点仍是 `af3820836a6ffa92c63016b0e308f624f9b42db0`，第 4、5、6 节仅保留首轮派发记录。TASK-02/03/04 现已全部 accepted 并集中合并，不再派发整改 prompt。TASK-05 从集成 commit `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9` 启动，首轮实现/交接提交分别为 `3947de40ebeb24799999bbd0ff866ce07c50355f` 和 `79d254339fb6804fbfbc4140c9c305cda663ba60`；后者是第 13 节唯一可信整改起点。

## 2. 并行派发与提交总协议

### 2.1 角色与并行边界

1. 协调者独占 `/Users/wuyida/Research/GLYPH`，负责 TASK-01 checkpoint、worktree/分支创建、验收、合并、冲突处理和任何远端操作；实施 Agent 不得在协调工作区写入。
2. TASK-02、TASK-03、TASK-04 各使用一个预先创建的独立 worktree 和专属分支，可以同时运行；一个 worktree 同一时间只允许一个写入型 Agent。
3. TASK-05 不与前三项并行。TASK-02/03/04 已验收并合并，协调者已从集成 commit 创建 TASK-05 worktree；不要再次创建或切换该分支。
4. Agent 不得读取、复制或修改其他任务的未完成 worktree。跨任务依赖只通过起始 checkpoint、任务书、已冻结 schema 和已验收 handoff 传递。
5. TASK-04 并行阶段只依赖 TASK-01 和书面冻结接口；对 TASK-02/03 的未完成实现使用 adapter 边界、fixture 和明确假设，不得窥读其 worktree。最终接口校准由集成阶段完成。
6. `README.md`、`CONTRIBUTING.md`、`docs/agent_tasks/` 由协调者拥有。并行 Agent 不得编辑这些文件；需要修订时写入各自任务报告的 `integration_requests`，由协调者统一处理。
7. `pyproject.toml`、`uv.lock`、`runtime.lock.json`、`schema/README.md`、`data/README.md` 和包级注册文件是共享热点。Agent 仅在本任务确实需要时作最小修改，并在 handoff 中逐项列出；不得预注册其他任务或批量格式化。

### 2.2 协调者初始准备与当前 accepted 基线

TASK-01 已通过全仓测试和严格 handoff 验证，并以普通本地提交 `af3820836a6ffa92c63016b0e308f624f9b42db0` 固化。TASK-02/03/04 的分支和 worktree 最初从该提交创建，现已分别前进到第 0 节的 accepted HEAD，并已集中合并到 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`。TASK-05 分支和 worktree 已从该集成 commit 创建。不要再次运行 `git switch -c` 或 `git worktree add -b`，也不要 reset 到旧 checkpoint。

协调者需要复核当前派发状态时只运行以下只读命令：

```bash
cd /Users/wuyida/Research/GLYPH
git branch --show-current
git rev-parse HEAD
git status --short --branch
git worktree list
git -C /Users/wuyida/Research/GLYPH-worktrees/task-02 status --short --branch
git -C /Users/wuyida/Research/GLYPH-worktrees/task-03 status --short --branch
git -C /Users/wuyida/Research/GLYPH-worktrees/task-04 status --short --branch
git -C /Users/wuyida/Research/GLYPH-worktrees/task-05 status --short --branch
```

预期协调分支为 `integration/task-01-accepted`，HEAD 为 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`。TASK-02/03/04 分支及 accepted HEAD 见第 0 节；TASK-05 分支必须为 `feature/task-05-joint-workbench`，HEAD 必须为同一集成 commit。四个实施 worktree 均应为空状态。协调工作区允许保留已知的 `README.md` 和本文件修改。实施 worktree 不共享主工作区 `.venv`，但可复用 uv 全局下载缓存。

### 2.3 每个并行 Agent 的本地提交协议

协调者预建分支后，TASK-02/03/04 Agent 获得以下有限 Git 权限：只能在自己的 worktree 和专属分支执行只读 Git 命令、按路径 `git add` 和普通 `git commit`。不得执行 `git switch`、`git checkout`、`git worktree`、`git stash`、`git reset`、`git clean`、`git merge`、`git rebase`、`git pull`、`git push`、`git commit --amend`、tag 或远端配置修改。

每个任务采用两阶段本地提交：

1. **实现提交**：包含本任务源码、schema、配置、测试、fixture、协议文档和必要的最小共享文件修改，但不包含最终生成的 handoff 包和最终报告。完成专项与全仓测试后，按明确路径暂存，检查 `git diff --cached --name-status` 和 `git diff --cached --check`，再创建普通 commit。
2. **交接提交**：以最新实现 commit 的 40 位哈希生成 handoff；`git_commit`/producer commit 必须指向该实现 commit，而不是起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0` 或尚不存在的交接 commit。严格验证 handoff 后，只暂存 handoff、最终报告和门禁包，创建第二个普通 commit。
3. 最终分支必须 clean。Agent 报告起始 checkpoint、实现 commit、交接 commit、相对起点的变更清单、测试命令/结果、handoff 路径和所有 blocked gate。
4. 若实现提交后发现缺陷，不 amend、不 rebase；创建新的普通修复 commit，把新的分支 tip 作为实现 commit，重新生成 handoff，再创建新的交接 commit。
5. 不使用 `git add .` 或仓库根级 `git add -A`。删除本任务拥有的文件时可使用限定路径的 `git add -A -- <task-owned-path>`。不得提交 `.venv`、缓存、数据库、日志、真实参与者数据、凭据、未知许可资产或其他 worktree 内容。
6. Agent 的“提交”只表示本地 branch commit 和 handoff，不表示 push、PR 或合并。远端备份、PR 和进入集成分支均由协调者在独立验收后决定。

### 2.4 协调者验收与集中合并（已完成）

协调者已按 TASK-02、TASK-03、TASK-04 顺序执行本地 `--no-ff` 合并。唯一共享冲突为 `pyproject.toml` 的 console scripts 注册区，最终保留 `glyph-vision`、`glyph-vision-legacy`、`glyph-experiment`、`glyph-han` 以及 social/experiment static package-data。集成时还修复了四个历史 handoff validator 对当前共享文件漂移的误拒绝，仍由各自声明的 producer commit 或受 Git 固定的历史快照验证文件集与哈希。

最终集成 commit 为 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`。全仓测试为 `366 passed`；TASK-01、TASK-02、TASK-03、TASK-04 strict handoff 均为 `failure_count=0`、`valid=true`；三个 accepted HEAD 均为该 commit 的祖先。TASK-05 worktree 已从该 commit 创建并验证 clean。以下命令只用于只读复核，不得重复 merge 或创建 worktree：

```bash
cd /Users/wuyida/Research/GLYPH
test "$(git rev-parse HEAD)" = "41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9"
git merge-base --is-ancestor c3c3d46ba00dbf88935a3821680454ebe56d6996 HEAD
git merge-base --is-ancestor 87f914bdae036d83d8e3c44a1ab57219cabb1576 HEAD
git merge-base --is-ancestor 48fbad87e84de5f323f9515c7f583c62b2cb7209 HEAD
git -C /Users/wuyida/Research/GLYPH-worktrees/task-05 status --short --branch
```

TASK-01 已验收通过，第 3 和 3.1 节保留作审计记录。第 4、5、6、7 节是已执行的首轮提示词；第 9、10、11、12 节是已执行的上游整改提示词，均不再派发。TASK-02/03/04 都没有下一条 prompt；第 13 节是当前唯一可派发 prompt。

## 3. TASK-01 首条 prompt

```text
你是 GLYPH 的 TASK-01 执行 Agent，只负责资产治理、五奖项图包、字体包与统一刺激子系统。

项目环境是 macOS arm64/zsh，唯一工作区根目录为 /Users/wuyida/Research/GLYPH。所有命令从该目录运行。项目要求 Python >=3.11,<3.12；现有 .venv 和 `uv run --frozen python` 是 Python 3.11.15，而系统 `python3` 是不兼容的 3.9.6，禁止使用裸 `python3` 跑项目。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；测试默认用 `uv run --frozen pytest ...`。只有确需同步依赖时才运行 `uv sync --locked --extra dev`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd`、`git status --short --branch`、`git rev-parse HEAD`、`uv --version`、`uv run --frozen python -V`。已知派发基线是 main 与 origin/main 同在 f89daec0e5e1f2df216a8e18c551d81f9954032f；README.md 的本地修改、未跟踪 CONTRIBUTING.md 和 docs/agent_tasks/ 全部是用户资产。不得编辑、暂存、删除、stash 或回退这些文件，除非本任务明确需要新增自己的交付且用户批准。不要 pull、switch、reset、clean、commit、merge、rebase 或 push；发现状态变化先报告，不得自行恢复到本文 commit。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/01_asset_stimulus_system_task_zh.md、CONTRIBUTING.md，以及任务书列出的现有实现和数据。先核对实际文件，不要假设任务书中的计数仍然正确。五个奖项范围固定为 DFA、Indigo、WOLDA、Golden Pin 和 GDC，不寻找第六个。

先提出一个可证伪的局部实现假设和一个最便宜的检查，随后直接实施，不要停在计划。正式资产操作前先用许可明确 fixture；不得登录、接受条款、付费、下载未知许可材料、公开受限资产或改写 Git 历史。遇到 GATE-RIGHTS、GATE-HISTORY、GATE-TERMS 或 GATE-RELEASE 时停止相应切片并提交门禁包，不替用户决定。

每次首次实质编辑后立即运行最窄可执行验证；完成后运行相关专项测试、`uv run --frozen pytest -q` 和 `git diff --check`。不要修复无关失败。最终生成符合总蓝图的 handoff_manifest.json 和任务报告，明确 engineering_ready、pilot_ready、research_validated，且不自动进入 TASK-02。不要调用其他 Agent。
```

## 3.1 TASK-01 第二条 prompt（首次验收整改）

使用方式：将下面代码块原样发送到完成 TASK-01 首轮实现的同一 Agent 会话。不要重新发送首条 prompt，也不要另开 Agent。

```text
继续执行 GLYPH TASK-01。本轮是首次独立验收后的定向整改，不是新任务，也不得进入 TASK-02、扩展到其他模块或重写无关代码。

仍在 /Users/wuyida/Research/GLYPH 的当前 dirty worktree 中工作。先重新运行并报告 `pwd`、`git status --short --branch`、`git rev-parse HEAD`、`uv --version`、`uv run --frozen python -V`，再阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/01_asset_stimulus_system_task_zh.md、docs/asset_curation_protocol_zh.md、status/task_01_report_zh.md 和现有 TASK-01 实现。README.md、CONTRIBUTING.md、docs/agent_tasks/ 及其他既有修改仍是用户资产；不要 stash、reset、clean、switch、commit、merge、rebase、pull、push，不要覆盖或回退任何非本轮修改。不要调用其他 Agent。

独立验收结论为“不通过”。现有专项 20 项、全仓 208 项、handoff validator、`uv lock --check` 和 `git diff --check` 虽然通过，但没有覆盖以下真实行为。先对每项提出一个可证伪的局部原因和最便宜复现，再按最小改动逐项修复；首次实质编辑后立刻运行能推翻当前假设的最窄测试。

必须关闭以下七项问题：

1. 修复 `freeze-stimuli` 的输入信任边界。original 与 derived JSONL 必须在使用前通过 candidate schema；所有资产路径必须是工作区内规范相对 POSIX 路径，并核验文件存在、普通文件、实际字节数和完整 SHA-256。不得只信任记录中的 `asset_ref`、父哈希、QC、策展或权利字段。正式冻结必须消费并核对可追溯的 rights evidence 或等价的已通过权利门禁记录，绑定 source_id、rights tier、decision status 和用途；缺失、待审、冲突或伪造证据必须机械失败。最终 stimulus schema 验证不能替代输入真实性验证。

2. 修复 `transform` 的工作区路径越界。candidate schema 通过后仍要使用统一安全解析器拒绝绝对路径、`..`、Windows 盘符以及解析后或符号链接后逃出 workspace root 的路径；任何图像解码前完成此检查。工作区外绝对 PGM 的 `transform --dry-run` 必须非零退出且给出稳定 failure code。

3. 修复来源迁移的同 basename 静默错配。不得再用 basename 到单个 Path 的覆盖字典。使用保留全部候选的映射和可解释的相对路径规则；只有唯一匹配才能自动关联。跨年份或子目录同名时必须精确消歧，无法消歧则输出稳定 ambiguity issue 并阻止该行进入规范映射，不能让后一个文件覆盖前一个。为 `2023/a.png` 与 `2024/a.png` 补最小回归测试。

4. 补齐真实人工策展闭环。提供受支持的 CLI 入口导入 `curation_decisions.csv`，验证审核者、UTC 时间、分类、排除码和目标几何，生成新记录且不原地伪造历史。人工确认几何后必须重新运行与该几何相关的 QC；只有全部自动检查真实通过时才把 `automated_qc.status` 派生为 passed，不能直接赋值绕过损坏、像素或格式失败。至少用一个初始 `automated_qc.status=needs_review` 的真实库存候选证明“导入决定 -> post-curation QC -> transform -> freeze”可达；权利仍未通过时应只被权利门禁阻断。

5. 统一目标几何契约与运行时。当前 schema 接受 polygon，而 B_shape 只接受 bbox。至少让 schema 已公开的 bbox 与 polygon 都能确定性执行、记录参数并生成正确 mask；任务书提到的 alpha mask 要么在本协议版本中完整实现和测试，要么明确从 v1 schema、协议和能力声明中移除，并给出版本化后续入口。合法 schema 记录不得到运行时才以 `QC_HUMAN_BOUNDARY_REQUIRED` 拒绝其已确认 polygon。

6. 修复 handoff 的生产者溯源。不得把不含 TASK-01 实现和 schema 的 `f89daec0...` 描述为足以复现生产者的 commit。在不违反“Agent 不得 commit”的前提下，明确区分 base commit、dirty working-tree 状态和 producer source snapshot，记录并验证实现、schema、配置及必要入口的哈希；或者在无法证明生产者状态时机械拒绝 `engineering_ready=true`。validator 必须能发现“声明 commit 不含生产实现且没有受验证源码快照”的情况，而不只是验证 40 位格式。若修改 handoff schema，正确升级版本并说明兼容策略。

7. 清除可移植 handoff 中的本机绝对路径。run manifest 不得写入 `/Users/.../.venv/bin/python3` 或其他用户目录；改为可移植、足以诊断但不泄露本机路径的解释器与环境标识。对整个 reference handoff 增加绝对路径扫描测试。

补充回归测试时必须直接覆盖此前漏掉的入口，而不只测内部 helper：

- 不存在或哈希伪造的 derived 文件不能冻结；
- 没有匹配 passed rights evidence 的记录不能生成正式 ecological stimulus；
- 绝对路径、遍历路径和符号链接逃逸不能进入 transform/freeze；
- 同 basename 不得静默关联；
- 真实 needs_review 候选经人工决定与重跑 QC 后状态正确；
- polygon 的 schema 与 transform 行为一致；
- 错误 producer provenance 使 handoff 校验失败；
- reference handoff 不含用户绝对路径。

保持现有五奖项计数、12 字族关系、fixture A/B/C、no-overwrite、稳定 ID 和既有 visual v1 兼容性；不要为了让测试通过而降低 schema、删除门禁、硬编码当前机器路径或把 formal 记录改标成 fixture。所有新失败使用稳定、可测试的错误码；批处理继续遵守退出码 0/1/2/3 契约。

完成后重新生成 reference handoff 和 TASK-01 报告，逐项列出七项 finding 的修复位置与回归测试。依次运行最窄测试、TASK-01 全部专项测试、`uv run --frozen pytest -q`、严格 handoff 校验、`uv lock --check`、绝对路径扫描和 `git diff --check`。报告实际命令、退出码和测试数，区分 engineering_ready、pilot_ready、research_validated；不要自行宣告进入 TASK-02，完成后等待独立复验。
```

## 4. TASK-02 首条 prompt（已实例化，可直接复制）

```text
你是 GLYPH 的 TASK-02 执行 Agent，只负责理论构念、可解释视觉测量与 CV 子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-02`，唯一允许停留的分支是 `feature/task-02-visual-measurement`，起始 commit 必须是 `af3820836a6ffa92c63016b0e308f624f9b42db0`。如果这段消息中的起始 commit 不是这个完整的 40 位小写值，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-02 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-03、task-04 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-02`，分支正好是 `feature/task-02-visual-measurement`，HEAD 正好是 `af3820836a6ffa92c63016b0e308f624f9b42db0`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-02 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/02_visual_measurement_system_task_zh.md、CONTRIBUTING.md，以及现有 src/glyph_features、configs/visual_features_v1.yaml、visual v1 参考运行和 lijie_aesthetic_cv。现有 visual v1 是冻结兼容基线；李婕目录是待工程化原型，不是第二套可直接发布的生产管线。

先验证 commit `af3820836a6ffa92c63016b0e308f624f9b42db0` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。只消费该 checkpoint 内已验收的许可 fixture 和冻结契约；不得读取其他并行 worktree 的实现。保持 v1 历史 schema/参考运行可读，canonical 输出不得含未经真人校准的综合审美分，也不得根据预期结论修改特征。需要本机服务时只绑定 127.0.0.1，优先使用端口 8022；端口被占用时选择空闲端口并记录。

每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-02 专项、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。涉及专家判断时停在 GATE-EXPERT。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-02 的路径执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有其他任务、真实数据、凭据、缓存或绝对路径后，提交 `git commit -m "Add TASK-02 visual measurement system"`。将此时 `git rev-parse HEAD` 记录为 TASK-02 implementation commit。

第二阶段以该 implementation commit 生成最终 handoff_manifest.json、checksums、门禁包和 TASK-02 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0` 或未来的交接 commit。严格验证 handoff，明确计算稳定性、表面效度、构念效度、预测效度及三档 readiness。然后只暂存生成的 handoff、门禁包和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-02 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-02 专项、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改和 blocked gate。不要 push、创建 PR、合并其他分支、运行真实人评或进入 TASK-05；完成后等待独立验收。
```

## 5. TASK-03 首条 prompt（已实例化，可直接复制）

```text
你是 GLYPH 的 TASK-03 执行 Agent，只负责跨文化感知实验与简中、英文、日文、韩文问卷子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-03`，唯一允许停留的分支是 `feature/task-03-cross-cultural-experiment`，起始 commit 必须是 `af3820836a6ffa92c63016b0e308f624f9b42db0`。如果这段消息中的起始 commit 不是这个完整的 40 位小写值，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-03 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-04 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-03`，分支正好是 `feature/task-03-cross-cultural-experiment`，HEAD 正好是 `af3820836a6ffa92c63016b0e308f624f9b42db0`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-03 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/03_cross_cultural_experiment_task_zh.md、CONTRIBUTING.md 和现有 schema。真实参与者数据进入受限、被 Git 忽略的存储；联系/补偿 PII 与研究响应物理分离。任何本机 Web 服务默认只绑定 127.0.0.1。

先验证 commit `af3820836a6ffa92c63016b0e308f624f9b42db0` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。只用该 checkpoint 内的许可 fixture 和 synthetic participants 完成协议、schema、平衡不完全区组分配、四语界面、质量规则、去标识导出和浏览器验证；不得读取其他并行 worktree 的实现。synthetic 数据必须机械拒绝进入正式分析和 release。Web 服务只绑定 127.0.0.1，优先使用端口 8023；端口被占用时选择空闲端口并记录。

不得提交伦理申请、联系/招募真人、收集真实响应、接受第三方条款或把机器翻译标成已审核。任何真实参与者响应、联系信息、补偿记录、cookie、浏览器配置、数据库、WAL、日志或截图中的个人信息都不得暂存或提交。每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-03 专项、桌面/移动浏览器验收、相关 `node --check`、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-03 的源码、schema、配置、测试、synthetic fixture、空模板和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，机械扫描 staged 内容不存在 PII、凭据、真实响应和绝对路径后，提交 `git commit -m "Add TASK-03 cross-cultural experiment system"`。将此时 `git rev-parse HEAD` 记录为 TASK-03 implementation commit。

第二阶段以该 implementation commit 生成 GATE-ETHICS、GATE-PARTICIPANTS 等门禁包、handoff_manifest.json、checksums 和 TASK-03 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0` 或未来的交接 commit。严格验证 handoff，保持真实收集锁定，并如实标记翻译、伦理、招募和真人 pilot 的 readiness。然后只暂存 handoff、checksums、门禁包、无个人信息的验收证据和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-03 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-03 专项、浏览器验收、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改、数据来源扫描和 blocked gate。不要 push、创建 PR、合并其他分支、接触真人或进入 TASK-05；完成后等待独立验收。
```

## 6. TASK-04 首条 prompt（已实例化，可直接复制）

```text
你是 GLYPH 的 TASK-04 执行 Agent，只负责汉字书体、字形演化知识、受控候选与专家在环子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，唯一允许停留的分支是 `feature/task-04-han-style-knowledge`，起始 commit 必须是 `af3820836a6ffa92c63016b0e308f624f9b42db0`。如果这段消息中的起始 commit 不是这个完整的 40 位小写值，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-04 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-03 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，分支正好是 `feature/task-04-han-style-knowledge`，HEAD 正好是 `af3820836a6ffa92c63016b0e308f624f9b42db0`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-04 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/04_han_style_knowledge_task_zh.md、CONTRIBUTING.md、TASK-01 已验收 handoff，以及 checkpoint 中 TASK-02/03 的书面接口要求。必须区分书体概念、字体实例、字形实例、作品、历史断言、文化联想和专家审核；所有真实字形资产先经过 TASK-01 权利与资产接口，正式 stimulus_id 由 TASK-01 冻结。

先验证 commit `af3820836a6ffa92c63016b0e308f624f9b42db0` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。先做本体、证据链、字符映射、review package、导入器和许可 fixture；不得读取 TASK-02/03 并行 worktree。与视觉测量或问卷的连接必须封装为 adapter，对当前书面契约和 synthetic fixture 编程；未能在本分支证明的字段放入机器可读 blocked 状态和最终报告 `integration_requests`，不得猜测其他 Agent 将如何实现。需要本机服务时只绑定 127.0.0.1，优先使用端口 8024。

不得联系专家、发送真实材料、伪造专家结论、下载未知许可字形或以现代字体名证明历史归属。每类实例不足时机械限制为 instance_level_only。真实专家、权利、受限下载和条款步骤分别停在 GATE-EXPERT、GATE-RIGHTS、GATE-TERMS；门禁包可以提交，门禁结果不能由 Agent 自行改成 passed。

每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-04 专项、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-04 的源码、schema、配置、测试、许可 fixture、空模板和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有其他任务、专家个人信息、未知许可资产、凭据、缓存或绝对路径后，提交 `git commit -m "Add TASK-04 Han style knowledge system"`。将此时 `git rev-parse HEAD` 记录为 TASK-04 implementation commit。

第二阶段以该 implementation commit 生成 handoff_manifest.json、checksums、GATE-EXPERT/GATE-RIGHTS/GATE-TERMS 门禁包和 TASK-04 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0` 或未来的交接 commit。严格验证 handoff，明确实例级与类别级推断、`instance_level_only` 降级、adapter 假设及三档 readiness。然后只暂存 handoff、checksums、门禁包和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-04 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-04 专项、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 checkpoint `af3820836a6ffa92c63016b0e308f624f9b42db0`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改、`integration_requests` 和 blocked gate。不要 push、创建 PR、合并其他分支、接触专家或进入 TASK-05；完成后等待独立验收。
```

## 7. TASK-05 首条 prompt（已完成但未通过首轮独立验收，仅保留审计）

状态：已执行。Implementation commit 为 `3947de40ebeb24799999bbd0ff866ce07c50355f`，handoff HEAD 为 `79d254339fb6804fbfbc4140c9c305cda663ba60`；首轮独立验收未通过。不要再次发送下面的代码块，改发第 13 节。

```text
你是 GLYPH 的 TASK-05 执行 Agent，只负责四线联合分析、统一工作台和系统总装；只有 TASK-01 至 TASK-04 已提供可验证 handoff 后才执行正式总装。

你在三路上游完成独立验收并集中合并后预建的 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，唯一允许停留的分支是 `feature/task-05-joint-workbench`，起始 commit 必须是 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`。如果实际 HEAD 与这个完整的 40 位小写 commit 不一致，立即停止并要求协调者重新派发，不要自行猜测或拉取上游分支。

Agent 会话的初始终端可能位于协调工作区 `/Users/wuyida/Research/GLYPH` 或其他目录；初始目录不等于 TASK-05 worktree 本身不是失败。任何仓库检查、文件读取或编辑之前，第一条终端命令必须且只允许执行 `cd /Users/wuyida/Research/GLYPH-worktrees/task-05`。这是唯一一次跨目录 bootstrap 例外；不要在初始目录运行 Git 守卫、读取任务文件或修改任何内容。若 `cd` 失败，或进入后 `pwd -P` 仍不等于该绝对路径，立即停止并报告。

项目环境是 macOS arm64/zsh。完成 bootstrap 后，所有命令都从 TASK-05 worktree 根目录运行，不得再 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-03、task-04 或其他 worktree，也不得从那些目录复制文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由集成 commit 中的 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有远程（即非本地） Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

完成上述 `cd` 后再运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git log --oneline --decorate -8`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，分支正好是 `feature/task-05-joint-workbench`，HEAD 正好是 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`，工作树为空。任一不符就停止并报告；除了首次 bootstrap `cd`，不得通过 switch、reset、stash、clean、merge、rebase、pull 或复制文件来自行“修复”环境。

本任务只允许在当前分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。上游分支已经由协调者合并；若发现缺失、不兼容或冲突，不得自行 merge task-02/03/04，而应机械标记 blocked 并停止相关切片。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/；共享注册文件只作 TASK-05 总装所需最小修改。即使 VS Code 窗口仍把协调工作区显示为 workspace root，也不要因此停止；所有非终端文件工具必须使用 `/Users/wuyida/Research/GLYPH-worktrees/task-05/` 下的绝对路径，下文所有相对路径也都以该 worktree 为基准。若某个工具不能明确指向 TASK-05 worktree，停止使用该工具并报告，不得退回协调工作区读写。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/05_joint_analysis_workbench_task_zh.md、CONTRIBUTING.md、所有上游 handoff，以及现有 src/glyph_features/social_system。社会叙事源码目标数据库 schema v17，但生产主库有意保持 v14；未经用户明确批准，所有启动、迁移、备份恢复和 E2E 都必须通过 `--catalog-database` 与 `--social-database` 指向两个不同的显式临时路径，不得把 `data/raw/social/glyph-social.sqlite3` 传给任一参数或在启动时迁移它。若为兼容保留 `--database`，它只能是 `--catalog-database` 的已弃用别名，不得按文件内容猜测数据库角色。

开始实现前逐一运行 TASK-01、TASK-02、TASK-03、TASK-04 的 handoff validator，核对 manifest 声明的 producer commit 可由当前集成历史追溯，并记录各自 readiness、schema 版本和 blocked gate。任一 handoff 缺失、被篡改或不兼容时，只阻断对应入口并报告；不得从其他 worktree、聊天附件或临时文件补齐。

随后提出一个可证伪的局部实现假设和最便宜检查并直接实施。总装采用 adapter、规范导出和中央目录，不直接修改模块私有表、不启动重复 scheduler、不重写成熟社会叙事核心。缺少或不兼容 handoff 时显示 blocked/fixture-only，不猜字段或伪造输出。联合模型必须防止多对多膨胀、伪重复、数据泄漏和无依据的 WP2 个体暴露联结。Web 服务只绑定 127.0.0.1，优先使用端口 8025。

先用许可 fixture、synthetic ratings 和显式临时数据库完成 E2E；正式 release 必须因 synthetic 或未决人工门禁被机械阻断。每次首次实质编辑后立即运行最窄验证；完成实现后运行模块契约测试、`uv run --frozen pytest -q`、必要的 `node --check`、浏览器桌面/移动验收、备份恢复演练、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-05 的源码、adapter、schema、配置、测试、许可 fixture、synthetic 数据和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有生产数据库、真实响应、凭据、缓存、绝对路径或上游任务的无关重写后，提交 `git commit -m "Add TASK-05 joint analysis workbench"`。将此时 `git rev-parse HEAD` 记录为 TASK-05 implementation commit。

第二阶段以该 implementation commit 生成系统 handoff_manifest.json、checksums、门禁包和 TASK-05 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写起始 commit `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9` 或未来的交接 commit。严格验证系统 handoff，逐模块说明 engineering_ready、pilot_ready、research_validated，并保留所有上游 blocked/fixture-only 状态。然后只暂存系统 handoff、checksums、门禁包、无敏感信息的 E2E 证据和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-05 system handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑模块契约测试、全仓测试、四个上游及系统 handoff validator、前端语法检查、浏览器验收、备份恢复、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 commit `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`、implementation commit、handoff commit、全部验证结果、系统 handoff 路径、临时数据库路径/清理结果、共享热点修改和 blocked gate。不要 push、创建 PR、合并分支、触碰生产数据库或替用户通过人工门禁；完成后等待独立验收。
```

## 8. 代理命令速查

所有实施 Agent 先在自己的 worktree 运行以下守卫，不在协调工作区运行：

```bash
# 从第 0 节复制当前任务唯一对应的 40 位可信验收基线；不要复制其他任务的值。
EXPECTED_HEAD=<CURRENT_TASK_TRUSTED_HEAD>
pwd -P
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
git worktree list
uv run --frozen python -V
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
```

只在确需联网安装依赖时设置代理：

```bash
HTTP_PROXY=http://127.0.0.1:7897 \
HTTPS_PROXY=http://127.0.0.1:7897 \
ALL_PROXY=http://127.0.0.1:7897 \
uv sync --locked --extra dev
```

下面的联网 Git 示例**仅供协调者**使用，TASK-02/03/04/05 Agent 禁止 fetch、pull 或 push：

```bash
git -c http.proxy=http://127.0.0.1:7897 \
    -c https.proxy=http://127.0.0.1:7897 \
    fetch origin
```

常规本机验证不需要代理：

```bash
uv run --frozen python -V
uv run --frozen pytest tests/相关测试.py -q
uv run --frozen pytest -q
uv lock --check
git diff --check
```

实施 Agent 每次本地提交前使用限定路径暂存，并检查 staged 内容；下列 `<明确路径...>` 是操作说明，不可原样执行：

```bash
git status --short
git diff
git add -- <明确路径...>
git diff --cached --name-status
git diff --cached --check
git diff --cached
git commit -m "<本任务 prompt 指定的提交信息>"
git status --porcelain=v1 --untracked-files=all
```

任何 Agent 都不得用 `git add .`、根级 `git add -A`、`commit --amend`、merge、rebase 或 push。协调者验收时以任务分支 commit 和 handoff 为输入，不从 Agent 的工作目录手工拷贝文件。

## 9. TASK-02 首次独立验收整改 prompt（已完成并通过第二轮验收，仅保留审计）

状态：已执行，accepted HEAD 为 `c3c3d46ba00dbf88935a3821680454ebe56d6996`。不要再次发送下面的代码块。

```text
继续执行 GLYPH TASK-02。本轮是首次独立验收后的定向整改，不是新任务；只修复理论构念、可解释视觉测量与 handoff 契约，不进入 TASK-03/04/05。

唯一允许写入的根目录仍是 `/Users/wuyida/Research/GLYPH-worktrees/task-02`，唯一允许停留的分支仍是 `feature/task-02-visual-measurement`。本轮可信起始 HEAD 必须精确等于 `6c1d998ac55f360c5c0edee71255bf76be694532`，工作树和 index 必须为空。开始时运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git diff --cached --name-status`、`git worktree list`、`uv --version`、`uv run --frozen python -V`。任一守卫不符立即停止并报告；不得用 switch、checkout、reset、stash、clean、merge、rebase、pull、复制其他 worktree 文件或改写历史来“修复”环境。

继续遵守首条 prompt 的全部边界：不得读取或修改协调工作区及 TASK-03/04 worktree；不得编辑 README.md、CONTRIBUTING.md 或 docs/agent_tasks/；只允许本分支上的只读 Git、限定路径 `git add` 和普通 `git commit`；禁止 `git add .`、根级 `git add -A`、amend、push、tag 和远端配置修改。使用本 worktree 的 Python 3.11 与 `uv run --frozen`，不使用系统裸 `python3`，不运行真实人评。

先重读 `docs/agent_tasks/02_visual_measurement_system_task_zh.md`、现有 TASK-02 报告、`configs/visual_measurements_v2.yaml`、`src/glyph_features/vision_system/`、相关 schema、专项测试、reference run 和 reference handoff。独立验收结论为“不通过”：常规专项 `26 passed`、全仓 `259 passed`、strict handoff、`uv lock --check` 和 `git diff --check` 虽然通过，但没有覆盖下面两个已复现的行为缺陷。对每项先写出一个可证伪的局部原因和最便宜公开入口复现；首次实质编辑后立即运行能推翻当前假设的最窄测试。

必须关闭以下问题：

1. 让算法配置成为真实的可执行契约，而不是只参与哈希。当前 `measure_array()` 只消费 `binary_threshold`，但公开配置还声明并哈希 `component_connectivity`、`hole_connectivity`、`skeleton_algorithm`、`symmetry_alignment`、`tonal_bins` 等字段，实际计算却使用硬编码邻域、固定 `skimage.skeletonize` 和固定 32 桶。逐项统一 config/schema/registry/runtime/run manifest：每个公开字段必须实际驱动对应算法并被记录，或者在本协议版本中被明确拒绝/移除并完成版本兼容，不能接受一个不会改变行为却会改变 `algorithm_config_sha256` 的字段。采用成熟库时记录实现与版本；不支持的枚举用稳定错误码失败，不能静默回退。

2. 修复 TASK-01 到 measurement handoff 的跨工件 provenance。validator 必须从实际文件重算并机械比较：TASK-01 handoff 文件 SHA、TASK-02 handoff `input_snapshots` 中对应 SHA、run manifest 的 `task01_handoff_sha256`、每条 measurement 的 `source_contract_sha256`，以及 measurement 所引用的 stimulus/asset/input SHA 是否真实属于该 TASK-01 snapshot。逐文件自洽哈希不等于跨文件同源；替换一个 TASK-01 snapshot、再重算其本地 checksums/record counts 后，strict validator 仍必须失败。正式 B_shape/C_ink 输入也必须保留其 TASK-01 QC、表示与权利链，不能只信任 TASK-02 记录里的自述字段。

新增的回归测试必须通过公开 API/CLI 和 handoff validator 覆盖此前漏掉的路径：

- 分别扰动每个公开算法字段，断言测量按定义改变，或以稳定 unsupported code 拒绝；禁止只断言配置哈希改变。
- 至少保留一个解析 fixture，交叉验证连通性、孔洞、骨架、对称与灰度桶中实际支持的配置。
- 构造语义分叉的 TASK-01 snapshot/run manifest/measurements，并重算攻击包自己的普通哈希；strict handoff 必须定位具体不一致字段并非零退出。
- 正常 reference run 的所有 measurement 必须共享且可追溯到同一 TASK-01 contract，旧 visual v1 兼容读取仍通过。

不要通过硬编码当前 fixture SHA、降低 schema、删除配置字段但不升版本、把所有输入改标 synthetic，或让 validator 只比较 manifest 自己声明的值来过测试。canonical 输出继续禁止未经真人校准的总分，原始 measurements 不因预期结论改变。

修复后先创建普通实现修复 commit，建议消息 `Fix TASK-02 acceptance findings`；不得 amend `6c1d998...`。以新的实现 tip 重新生成 reference run、handoff、checksums、门禁包和报告，确保 producer provenance 指向该新实现 tip，再创建普通 handoff commit，建议消息 `Update TASK-02 handoff after remediation`。只按明确路径暂存并审阅 staged diff；若 handoff 后又改源码，另建普通修复 commit 并再次生成 handoff。

结束前依次运行新增最窄反例、TASK-02 全部专项、`uv run --frozen pytest -q`、strict handoff validator、`uv lock --check`、`git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告可信起始 HEAD、新实现 commit、新 handoff commit、实际测试数/退出码、两项 finding 的修复位置、攻击回归、更新后的 handoff 路径、共享热点和 blocked gate。不要合并、push、创建 PR 或进入 TASK-05；完成后等待协调者重新验收。
```

## 10. TASK-03 首次独立验收整改 prompt（已完成并通过第二轮验收，仅保留审计）

状态：已执行，accepted HEAD 为 `87f914bdae036d83d8e3c44a1ab57219cabb1576`。不要再次发送下面的代码块。

```text
继续执行 GLYPH TASK-03。本轮是首次独立验收后的定向整改，不是新任务；只修复跨文化实验运行、持久状态、质量决定与 handoff，不接触真人，也不进入 TASK-04/05。

唯一允许写入的根目录仍是 `/Users/wuyida/Research/GLYPH-worktrees/task-03`，唯一允许停留的分支仍是 `feature/task-03-cross-cultural-experiment`。本轮可信起始 HEAD 必须精确等于 `b2a4f39112851add4e2d136fa6485924e49e6a63`，工作树和 index 必须为空。开始时运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git diff --cached --name-status`、`git worktree list`、`uv --version`、`uv run --frozen python -V`。任一守卫不符立即停止并报告；不得用 switch、checkout、reset、stash、clean、merge、rebase、pull、复制其他 worktree 文件或改写历史来“修复”环境。

继续遵守首条 prompt 的全部隐私与 Git 边界：不得读取或修改协调工作区及 TASK-02/04 worktree；不得编辑 README.md、CONTRIBUTING.md 或 docs/agent_tasks/；不得提交真实响应、PII、数据库、WAL、日志、cookie 或浏览器配置；只使用 synthetic participant 和临时数据库；只允许限定路径暂存和普通提交，禁止 amend、push、tag。Web 服务仍只绑定 127.0.0.1。

先重读 `docs/agent_tasks/03_cross_cultural_experiment_task_zh.md`、现有 TASK-03 报告、study/questionnaire 配置、`src/glyph_features/experiment_system/`、相关 schema、专项测试、reference fixture 与 release handoff。独立验收结论为“不通过”：常规专项 `35 passed`、全仓 `268 passed`、strict handoff、锁检查和现有浏览器证据虽然通过，移动 DOM 复测也未发现横向溢出，但实际 Web 控制路径仍有下面四项缺陷。对每项先从公开 API/UI 写最小失败测试，再作最小实现修复；首次实质编辑后立即运行最窄测试。

必须关闭以下问题：

1. 把分配配额改为数据库持久、事务化的全局状态。当前 `/api/session` 每次只调用 `build_assignments([participant])`，导致 exposure、position 和 group sequence 每次从零开始，已有 SQLite assignments 与服务重启均不参与下一次分配。实际 Web 入口必须在同一事务中读取并更新累计 stimulus/group/position/anchor 配额，处理并发创建、幂等 session nonce、刷新恢复和进程重启；批量 1000 人 dry-run 与在线单人创建必须共享同一冻结分配策略或得到等价约束证明。

2. 实现真实 Web 流程所需的 participant profile 与 consent receipt 数据链，但仍只运行 synthetic。UI/API/SQLite/schema/export 必须保存版本化同意状态和时间、问卷/协议版本，以及任务书要求的多母语/主导语言、多原生文字、各目标文字读写/接触熟练度、设计/字体/书法训练和经协议允许的粗粒度背景；不采集姓名、精确地址、IP 或不必要指纹。不能只保留 `language`、`native_scripts` 和三个前端 checkbox，也不能仅在 reference fixture 中伪装这些对象已存在。外键、缺失语义、恢复和去标识导出必须可验证。

3. 让服务端成为质量决定的唯一权威。前端只提交原始 presentation/rating/viewport/focus/timing/attention 信号，不得自行提交可被信任的 `quality=passed`。后端按冻结 `quality_rule_version` 调用完整规则，持久化不可覆盖的 `quality_decision`/原因历史，并让去标识导出、handoff 计数和正式分析锁读取该服务端决定。恶意客户端把 quality 写成 passed、遗漏 profile、过快、未完成、直线作答或 viewport 不可用时，均不能绕过排除；原始记录仍保留。

4. 补齐 handoff 下游入口与交付物的语义绑定。`next_task_entrypoints[].path` 必须存在、位于 workspace、属于受 `outputs` SHA/record count 保护的工件，并与 reference manifest、schema 版本、外键、记录数和 synthetic-only 状态一致。TASK-05 入口不能指向一个顶层 handoff 未声明或未验证的内部 manifest。strict validator 必须重算 profile/consent/assignment/presentation/rating/quality 之间的关键外键与汇总，并拒绝修改入口、遗漏质量决定或重新哈希后的语义分叉包。

回归测试至少包括：

- 通过 TestClient/公开 API 连续创建多批单人 session，断言累计配额满足容差；关闭并重开数据库后继续分配仍不归零。
- 并发相同 nonce 只生成一个 session/assignment；不同 nonce 的事务不会丢失配额更新。
- 四语 UI 完成同意、背景、练习、试次和完成流程，规范表中实际出现 profile、consent 与服务端 quality decision；桌面和移动检查无截断、重叠或流程死路。
- 客户端伪造 passed quality、过快/未完成/缺背景等攻击通过公开提交入口后，被服务端按稳定原因码处理。
- 篡改 entrypoint、从 outputs 删除 reference manifest、改变内部计数或外键并重算普通文件哈希后，strict handoff 仍失败。

保持 real collection 默认锁死，GATE-ETHICS、GATE-PARTICIPANTS、翻译和招募状态不得被整改测试自动改成 passed。不得为方便持久配额而保存 PII，不得让 synthetic 进入正式分析/release，也不得用前端隐藏字段代替后端约束。

修复后先创建普通实现修复 commit，建议消息 `Fix TASK-03 acceptance findings`；不得 amend `b2a4f391...`。以新的实现 tip 重新生成 synthetic reference、浏览器证据、release handoff、checksums、门禁包和报告，producer provenance 必须指向新实现 tip；再创建普通 handoff commit，建议消息 `Update TASK-03 handoff after remediation`。若 handoff 后又改源码，另建普通修复 commit 并重新生成 handoff。

结束前依次运行新增 API/持久化/质量最窄测试、TASK-03 全部专项、相关 `node --check`、桌面/移动 Playwright 流程与布局检查、`uv run --frozen pytest -q`、strict handoff validator、`uv lock --check`、PII/绝对路径扫描和 `git diff --check`，并要求最终工作树为空。最终报告可信起始 HEAD、新实现 commit、新 handoff commit、实际测试数/退出码、四项 finding 的修复位置、数据库重启与攻击回归、浏览器证据、handoff 路径及所有 blocked gate。不要接触真人、合并、push、创建 PR 或进入 TASK-05；完成后等待协调者重新验收。
```

## 11. TASK-04 首次独立验收整改 prompt（已完成但未通过第二轮验收，仅保留审计）

状态：已执行并生成 HEAD `cdf327492994e899d34a8728b035360e8e85aa1a`，第二轮验收发现一个组合缺陷；该缺陷已由第 12 节整改关闭。不要再次发送下面的代码块。

```text
继续执行 GLYPH TASK-04。本轮是首次独立验收后的定向整改，不是新任务；只修复汉字书体知识、专家在环、类别推断和 handoff 信任边界，不联系专家、不获取新资产，也不进入 TASK-05。

唯一允许写入的根目录仍是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，唯一允许停留的分支仍是 `feature/task-04-han-style-knowledge`。本轮可信起始 HEAD 必须精确等于 `5d0c6bd259f6e162f122a1c48bb214eba7db67a4`，工作树和 index 必须为空。开始时运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git diff --cached --name-status`、`git worktree list`、`uv --version`、`uv run --frozen python -V`。任一守卫不符立即停止并报告；不得用 switch、checkout、reset、stash、clean、merge、rebase、pull、复制其他 worktree 文件或改写历史来“修复”环境。

继续遵守首条 prompt 的全部边界：不得读取或修改协调工作区及 TASK-02/03 worktree；不得编辑 README.md、CONTRIBUTING.md 或 docs/agent_tasks/；不得联系专家、发送材料、伪造人工结论、下载未知许可字形、接受条款或把现代字体名当历史证据；只允许限定路径暂存和普通提交，禁止 amend、push、tag。真实门禁在没有外部人工批准时必须保持 blocked。

先重读 `docs/agent_tasks/04_han_style_knowledge_task_zh.md`、现有 TASK-04 报告、TASK-01 已验收 handoff、`configs/han_style_protocol_v1.yaml`、`src/glyph_features/han_style_system/`、相关 schema、专项测试、reference run 和 reference handoff。独立验收结论为“不通过”：常规专项 `19 passed`、全仓 `252 passed`、strict handoff、`uv lock --check`、`git diff --check` 和编辑器诊断虽然通过，但公开 CLI/API 可复现下面的门禁和语义缺陷。先把每个反例写成失败测试，再修复直接控制状态的代码；首次实质编辑后立即运行最窄测试。

必须关闭以下问题：

1. 建立不可由调用者自述绕过的专家与权利信任链。`build-stimulus-candidates` 在使用前必须验证 ontology、mapping、glyph、review、rights 及其外键；formal review 必须绑定已验证 review package、`package_content_sha256`、受信 gate approval、批准范围/角色和不可变 review 记录，不能只看 `review_origin=real_expert` 与任意非空 `gate_approval_id`。formal rights 必须来自严格验证且由 SHA 固定的 TASK-01 handoff/output，并绑定 source、rights tier、decision status 和 `research_stimulus_local` 用途；任意 standalone JSON 即使 schema-valid 也不能自行成为信任根。选择一个最小、可审计的本地 trust-root 设计，并明确测试 fixture 与真实 approval 的边界；本轮不得制造真实 passed approval。

2. 让独立审核具备实质维度和角色覆盖。两条同角色、八个维度全部 `not_applicable`、仅 `overall_decision=pass` 的记录不得满足 formal pass。至少两位不同 reviewer 之外，还要按协议检查适用于对象的非空实质维度、配置化角色覆盖、independence、round、prior-review visibility 与 package binding；`outside_expertise`/N/A 可以诚实保留，但不能累计成通过票。当前 reference synthetic review 仍只能 fixture-only。

3. 支持合法的 `research_local_only` 本机审核包。当前构建器硬编码 `rights_tier=open` 且 `release_tier=fixture_only`，使真实但获准仅本地研究的资产无法进入专家审核。实现受限本机 package 的 access level、路径/复制策略、checksums 和防公开再分发约束；它可以在临时/受控本地目录供审核，但不得被标成 `open_fixture` 或进入公共 release。blocked/unknown rights 仍必须拒绝。

4. 让 adjudication 真正参与冻结聚合，同时保留原始意见。合法 independent `pass`/`fail` 冲突后，一个正确绑定冲突 review IDs、轮次、可见性与授权裁决者的 adjudication 必须按冻结政策得到可解释终态；当前聚合完全忽略 adjudication、永久返回 conflicted 的行为必须修复。原始审核不可删除或覆盖，decision counts、supersedes/conflict links 和审计历史必须一致；无效或自述裁决不得解锁。

5. 从可验证 lineage 派生或校验 exemplar 独立性，不能只对自由 `exemplar_cluster_id` 字符串去重。三个记录若共享同一 work、source、font/static instance、parent lineage 或 primary asset，仅改三个 cluster ID 不得升级为 `category_candidate`。按历史作品、字体实例和来源类型定义确定性、可解释的独立单元；同一碑帖多个字符不能冒充三个书体复本。实例不足时必须机械保持 `instance_level_only`。

6. 补齐知识图对象与人工确认外键。`han_knowledge_claim` schema 允许的 `style_concept`、`glyph_instance`、`work`、`font_instance`、`stimulus_candidate` 主语都必须按类型验证，`object_id` 必须按 relation 指向允许且存在的对象；`human_verified` 不能只凭任意 reviewer 字符串成立，必须绑定受控人工决定/审核身份与原始证据。一个引用不存在 work、object 和 reviewer 的 schema-valid claim 必须失败，精确 source locator/evidence span 仍不可缺失。必要时增加缺失的轻量 work/font registry，而不是把对象压回字符串。

7. 修复 CLI schema root 与 handoff 语义验证。`glyph-han validate-handoff --workspace-root "$PWD" --schema-root "$PWD/schema" ...` 必须把参数视为直接 schema 目录并成功验证 reference，不能拼成 `schema/schema/...`；省略参数的默认行为继续可用。strict handoff 还必须从受保护 outputs 重算 review summary、candidate release/freeze 状态、inference scope、adapter 状态和 gate truth，确保 entrypoint 属于 outputs。TASK-01 adapter 对 ready-for-request 候选必须表达可消费请求，或提供真实非空 blocker；不得出现 blocked 但无原因的语义。重新哈希一个自相矛盾包不能通过。

公开入口回归测试至少覆盖以下已复现反例：

- 自造 approval + 两条同角色全 N/A 的 schema-valid “real expert” review + schema-valid standalone rights，不能生成 `eligible_for_task01_freeze`/`ready_for_request`。
- 合法 `research_local_only` 字形可生成受限本机 review package，blocked/unknown rights 不可生成。
- independent pass/fail 加合法 adjudication 后按冻结政策得到终态，原始三条记录均保留；错误 conflict IDs 或未授权裁决失败。
- 同一 work/source/asset 伪造三个 cluster ID 后仍是 `instance_level_only`；真正独立 lineage 才达到门槛。
- 不存在 work/object/reviewer 的 `human_verified` claim 被稳定错误码拒绝。
- 直接 schema 目录形式的 `--schema-root` 成功；篡改 review/rights/candidate/adapter/gate 语义并重算普通哈希后 strict handoff 失败。

不要通过把正式路径全部禁用、把 real 输入改标 synthetic、硬编码当前 package ID/SHA、降低 schema、删除 research-local 支持或让 Agent 自动签发真实 approval 来过测试。reference run 应继续如实保持 synthetic、formal expert/rights/TASK-01 freeze blocked、`pilot_ready=false`、`research_validated=false`，不得因测试 trust fixture 自动升级。

修复后先创建普通实现修复 commit，建议消息 `Fix TASK-04 acceptance findings`；不得 amend `5d0c6bd...`。如 schema/contract 变更，正确升级版本并保留明确兼容策略。以新的实现 tip 重新生成 reference review package、candidate/adapters、handoff、checksums、三个 gate packet 和报告，producer provenance 必须指向新实现 tip；再创建普通 handoff commit，建议消息 `Update TASK-04 handoff after remediation`。若 handoff 后又改源码，另建普通修复 commit 并重新生成 handoff。

结束前依次运行所有新增攻击回归、TASK-04 全部专项、`uv run --frozen pytest -q`、默认与显式 `--schema-root` strict handoff validator、`uv lock --check`、绝对路径/受限资产泄漏扫描和 `git diff --check`，并要求最终工作树为空。最终报告可信起始 HEAD、新实现 commit、新 handoff commit、实际测试数/退出码、七项 finding 的修复位置、攻击回归、schema 兼容说明、handoff 路径、共享热点、integration_requests 和所有 blocked gate。不要联系专家、合并、push、创建 PR 或进入 TASK-05；完成后等待协调者重新验收。
```

## 12. TASK-04 第二次整改 prompt（已完成并通过第三轮验收，仅保留审计）

状态：已执行。Implementation commit 为 `cecdf3325f8701b5e4125d35811ed58b6580564d`，accepted handoff HEAD 为 `48fbad87e84de5f323f9515c7f583c62b2cb7209`；第三轮独立验收通过。不要再次发送下面的代码块。

```text
继续执行 GLYPH TASK-04。本轮是第二轮独立验收后的单一缺陷整改，不是新任务；只修复 review aggregation 中 adjudication 绕过既有审核政策的问题，不联系专家、不获取新资产、不读取 TASK-02/03 worktree，也不进入 TASK-05。

唯一允许写入的根目录仍是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，唯一允许停留的分支仍是 `feature/task-04-han-style-knowledge`。可信起始 HEAD 必须精确等于 `cdf327492994e899d34a8728b035360e8e85aa1a`，工作树和 index 必须为空。开始时运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git diff --cached --name-status`、`git worktree list`、`uv --version`、`uv run --frozen python -V`。任一守卫不符立即停止并报告；不得用 switch、checkout、reset、stash、clean、merge、rebase、pull、复制其他 worktree 文件或改写历史来“修复”环境。

继续遵守首条 prompt 的全部边界：不得读取或修改协调工作区及 TASK-02/03 worktree；不得编辑 README.md、CONTRIBUTING.md 或 docs/agent_tasks/；不得联系专家、伪造人工结论、签发真实 approval、改变 rights/trust root 或放宽 schema；只允许限定路径暂存和普通提交，禁止 `git add .`、根级 `git add -A`、amend、push、tag。reference run 的 formal expert、formal rights、TASK-01 freeze、pilot_ready 与 research_validated 必须继续如实 blocked/false。

第二轮独立验收已确认上一轮七项 finding 的其他路径通过：聚焦回归 `16 passed`、TASK-04 专项 `38 passed`、全仓 `271 passed`；默认和显式 `--schema-root` 的公开 `glyph-han validate-handoff` 均为 `failure_count=0`；handoff 24 项和 review package 6 项 checksum、`uv lock --check`、编辑器诊断、泄漏扫描与 clean 状态均通过。自造 trust root、standalone rights、未知 claim 外键、伪 cluster ID、不一致 TASK-01 adapter，以及重算全部 hash/checksum 的 candidate/claim/gate/readiness 篡改也都被正确拒绝。不要重写这些已合格的子系统。

唯一仍未关闭的反例位于 `src/glyph_features/han_style_system/review.py` 的聚合状态机：两个独立 review 使用不同 reviewer ID，但都只有 `type_or_visual_design` 角色，八个 rubric dimension 全部为 `not_applicable`，overall decision 分别为 `pass` 和 `fail`。它们制造冲突后，加入一个由固定 trust root 授权、正确绑定两个 `conflict_review_ids`、round/visibility 合法且 overall decision 为 `pass` 的 adjudication。当前 `aggregate_reviews(..., minimum_independent_reviews=2)` 错误返回 `fixture_status="passed"` 且 `fixture_policy_blockers=[]`；同一 summary 的 formal policy 仍能看见独立审核数、维度与角色不足。这证明 terminal adjudication 分支清空了 policy blockers，并把“冲突终局决定”错误当成了“满足独立审核前置条件”。

先把该组合反例写成使用公开 `build_review_package`、`import_review_rows` 和 `aggregate_reviews` 的失败回归，再作最小实现修复。审核政策前置条件与 decision resolution 必须分开计算：adjudication 可以在授权、引用和唯一 terminal chain 均合法时解决已有 pass/fail conflict，但不得替代或清空 minimum independent reviews、reviewer independence、required role groups、minimum substantive dimensions、required dimension coverage、package binding 等 blockers，也不得把 adjudicator 自身计为独立盲审。只要前置 policy blocker 仍存在，fixture/formal status 就必须保持 `blocked` 并保留稳定 blocker codes；只有底层独立审核集合已满足全部前置条件时，合法 terminal adjudication 才能决定 `passed`、`failed` 或 `needs_revision`。原始 reviews、decision counts、conflict/supersedes links 和审计顺序必须保留。

回归至少同时证明：

- “同角色 + 全 N/A + pass/fail + 授权 pass adjudication”仍为 blocked，且 blockers 明确包含角色覆盖、实质维度和维度覆盖不足；不能只断言 formal_status。
- 缺少独立 reviewer、错误 conflict IDs、未授权 adjudicator、多 terminal 或循环 supersedes 均不能借 adjudication 解锁。
- 两个角色覆盖正确、维度实质且完整、package binding 合法的 independent pass/fail，在唯一授权 adjudication 后仍得到既有冻结终态；上一轮合法 adjudication、supersedes chain 和不可覆盖审计测试继续通过。
- 候选生成与 strict handoff 的 semantic gate 使用修复后的 summary；上述攻击不得让 `synthetic_double_review` 从 blocked 升为 fixture_only，也不得生成更高 release/readiness。即使攻击包重算普通 hash/checksum，strict validator 仍按语义拒绝。

不要硬编码当前 reviewer ID、角色、fixture package ID 或 blocker 列表来过测试；使用协议配置传入的 minimum/required policy。若公共 contract 未改变，不做无必要 schema/version 扩张。

首次实质编辑后立即运行新增组合反例这一项最窄测试。通过后创建普通实现修复 commit，建议消息 `Fix TASK-04 adjudication policy bypass`；不得 amend `cdf3274...`。以新实现 commit 重新生成 reference handoff、checksums、门禁包和报告，使 producer provenance 指向该新实现 commit，再创建普通 handoff commit，建议消息 `Update TASK-04 handoff after adjudication fix`。若生成 handoff 后又改源码，另建普通修复 commit 并再次生成 handoff。

结束前依次运行新增组合攻击及既有 adjudication/policy 测试、TASK-04 全部专项、`uv run --frozen pytest -q`、默认与显式 `--schema-root` 的公开 strict handoff CLI、reference 与 review-package checksum、`uv lock --check`、绝对路径/受限资产泄漏扫描、`git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告可信起始 HEAD、新实现 commit、新 handoff commit、实际测试数/退出码、组合反例修复位置、正常 adjudication 正例、handoff 路径和所有 blocked gate。不要合并、push、创建 PR、接触专家或进入 TASK-05；完成后等待协调者第三轮独立复验。
```

## 13. TASK-05 首次独立验收整改 prompt（当前唯一可派发）

使用方式：将下面代码块原样发送到完成 TASK-05 首轮实现的同一 Agent 会话。不要重新发送第 7 节，也不要另开 Agent。

```text
继续执行 GLYPH TASK-05。本轮是首次独立验收后的定向整改，不是新任务；只关闭工作台 handoff/import、social validated export、snapshot/analysis provenance、备份迁移、operation 恢复和浏览器安全/键盘边界，不接触真实数据、不通过人工门禁，也不重写已经通过的联合分析主链。

唯一允许写入的根目录仍是 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，唯一允许停留的分支仍是 `feature/task-05-joint-workbench`。本轮可信起始 HEAD 必须精确等于 `79d254339fb6804fbfbc4140c9c305cda663ba60`，其父提交必须是 implementation commit `3947de40ebeb24799999bbd0ff866ce07c50355f`，祖父提交必须是集成起点 `41e69bd5ca98a85e0ee1f04abba5e81907ba2bc9`，工作树和 index 必须为空。

Agent 会话终端若不在 TASK-05 根目录，第一条命令只执行 `cd /Users/wuyida/Research/GLYPH-worktrees/task-05`；随后运行并报告 `pwd -P`、`git branch --show-current`、`git rev-parse HEAD HEAD^ HEAD^^`、`git status --porcelain=v1 --untracked-files=all`、`git diff --cached --name-status`、`git worktree list`、`uv --version` 和 `uv run --frozen python -V`。任一守卫不符立即停止并报告；不得用 switch、checkout、reset、stash、clean、merge、rebase、pull、复制其他 worktree 文件或改写历史来“修复”环境。即使 VS Code workspace root 仍显示协调工作区，所有非终端文件工具也必须使用 TASK-05 worktree 下的绝对路径。

继续遵守第 7 节的全部 Git、数据库、隐私和人工门禁边界：不得读取或修改协调工作区及 TASK-02/03/04 worktree；不得编辑 README.md、CONTRIBUTING.md 或 docs/agent_tasks/；不得访问或迁移 `data/raw/social/glyph-social.sqlite3`，不得导入真实参与者、专家、受限资产或平台 raw payload；catalog/social 始终使用两个不同的显式临时路径；只允许限定路径暂存和普通本地提交，禁止 amend、push、tag。不得启动第二 scheduler。

首轮独立验收确认以下部分已经通过，不要借整改重写：提交拓扑恰为 `41e69bd... -> 3947de4... -> 79d2543...`；TASK-05 专项 `27 passed`，全仓 `393 passed` 且只有 2 条既存 `RefResolver` 弃用警告；TASK-01 至 TASK-04 原生 handoff validator 与 TASK-05 validator、checksums、`uv lock --check`、前端语法和补丁卫生通过；全新临时数据库的完整 fixture operation 成功，384 个分析单位、WP2 context-only、WP3 blocked、WP4 instance-level、formal release blocked、协调备份、CSP、桌面/移动八视图和全局无横向溢出均正确。保持这些行为和所有上游 blocked/fixture-only 状态。

首轮结论仍为“不通过”。下列反例均已通过公开 API、CLI 或临时数据库独立复现。先把每项写成失败回归，再修复直接控制行为的代码；首次实质编辑后立即运行能推翻当前假设的最窄测试。

必须关闭以下问题：

1. 实现规范要求的受控 handoff 导入，而不只扫描四个硬编码 reference 路径。保留固定 reference bootstrap 可以，但必须新增明确的目录/zip 导入 CLI/service/API，限定 TASK-01 至 TASK-04 的已知 schema 和原生 validator；在隔离 staging 中拒绝 zip slip、绝对路径、符号链接逃逸、重复成员、超限文件数/单文件/解压总量、unsupported schema 和篡改包。校验成功后原子登记 module、handoff、artifact 和 entity link；任一步失败不得留下部分 catalog 状态。同一包重复导入幂等，同 task/path 不同哈希保持不可变冲突。不要执行包内命令，也不要把 payload 复制成中央事实源。

2. 把 social validated export 变成真正绑定当前 payload 的契约。当前 adapter 只信任 `validation.json.valid=true`、最后一条 quality status 和 narrative 自述的 `human_verified=true`；在验证文件不变时替换 `narratives.jsonl` 为未验证内容仍被接受。让 canonical export 在所有输出完成后生成覆盖 manifest/governance/quality/narratives 的版本化 checksum 或等价不可变 package manifest，adapter 必须重算、校验 schema、记录数和 collection/source/evidence 稳定 ID 关系，任何验证后换包即失败。`register_social_export()` 必须从已验证 `data_origin` 派生分类：synthetic 才能登记为 `synthetic_fixture`，real 必须保持 restricted/real/privacy 边界，不能无条件降格为 synthetic。若最小修复需要扩展现有 social public export，保持旧 CLI 和既有 social 测试兼容，不读取私有表。

3. 修复 analysis snapshot 的来源与 Git provenance。当前完整 reference catalog 的 synthetic artifacts 可被 `freeze_analysis_snapshot(..., data_origin="real")` 接受，且不存在的 `0000000000000000000000000000000000000000` 也可记录为 Git commit。冻结前必须核对所有 input artifact classification 与顶层 data origin，禁止 synthetic/mixed 输入冒充 real；验证 commit 对象实际存在、属于当前仓库和允许的历史，并记录/拒绝 dirty producer state，使 snapshot 指向可重建代码。旧 snapshot 保持不可变且确定性重跑不变。

4. 让分析失败和长任务恢复形成持久审计闭环。当前在 snapshot 持久化后注入 `MODEL_DID_NOT_CONVERGE`，数据库中的 run 仍永久停在 `snapshot_frozen`，健康页也看不到失败；模型、join 或诊断异常必须原子写入 `failed` run、稳定 error code、诊断摘要和 audit event，不能伪装成尚未运行。operation 不能只存在进程内存：至少持久化 kind/status/stage/attempt/checkpoint，重启后把中断 attempt 标成可解释状态并允许从已验证 checkpoint 恢复。特别覆盖 social DB/导出已经产生但 catalog 尚未登记的崩溃窗口；重启后不得因“数据库已存在但 export 未 attached”进入只能手工删库的死路，也不得把部分输出标为完成。

5. 阻止协调备份迁移或改写不兼容 social 源库。已复现：一个 `social_status()` 明确返回 `SOCIAL_SCHEMA_MIGRATION_REQUIRES_SEPARATE_APPROVAL` 的真实临时 v14 结构，在调用 `backup` 后被原地升级到 v17 并新增 v15-v17 表。任何备份入口必须先以只读连接核对角色、schema 和 integrity；非 v17 或 blocked 状态在构造会迁移的 `SocialNarrativeService` 之前稳定失败，源库版本、表集和内容哈希保持不变。v17 正常协调备份/临时恢复、component checksum、no-overwrite 和现有测试继续通过；异常路径清理 `.tmp`/`.restore` 文件。不要通过识别某一个硬编码生产路径来代替 schema/角色守卫。

6. 让 TASK-05 strict handoff validator 重建语义，而不只验证自包含 checksum 和 producer 文件。已在本地临时 clone 复现：把 `module_compatibility` 中 social 的 `pilot_ready`、`research_validated` 改为 `true`，重算 `checksums.sha256` 后 validator 仍输出 `TASK-05 handoff valid`。validator 必须从当前受信上游 handoff、module descriptor、数据边界和 gate 规则重建并比较 module compatibility、三档 readiness、blocked gate、关键 interface/validation evidence 及系统汇总；任何模块自述升级、删除 blocker 或互相矛盾的重哈希包必须失败。继续验证 implementation commit 的完整 producer file set 和 Git blobs，不硬编码当前 manifest SHA。

7. 收紧浏览器写操作与键盘浮层。当前进程级 CSRF bearer token 可无限重放；为 unsafe API 增加有界、可轮换且服务端消费/校验的 replay 防护，并保留 local Origin、CSP 和稳定错误响应。备份、恢复、完整 fixture、停止等有副作用操作必须显示目标数据库/operation、影响和确认短语，不能单击即执行。证据 inspector 与移动导航打开时应移动焦点、为背景设置 inert 或等价约束、正确标注 dialog/expanded 状态、处理 Tab/Escape，并在关闭后恢复到触发按钮；已复现当前 inspector 打开后焦点仍在背景 artifact，继续 Tab 也留在背景表格。桌面和移动均补 Playwright 键盘回归。

公开回归至少包括：

- 合法目录和 zip handoff 导入成功；zip slip、重复成员、超限、unsupported schema、重哈希篡改和中途异常均失败且 catalog 前后完全一致。
- 修改 canonical social export 的任一受保护文件后沿用旧 validation/package manifest 必须失败；`synthetic=False` 的已验证输入不得登记为 synthetic。
- synthetic artifact + `data_origin=real`、不存在的 commit、dirty producer state 均不能冻结；合法 clean snapshot 与旧 run 重跑保持确定。
- join/模型异常后 run、health 和 audit 明确为 failed；进程重启能发现并恢复或安全终止中断 operation，social attach 崩溃窗口可幂等收敛。
- 对真实结构的临时 v14 social 库执行 status 后再 backup，必须拒绝且 `user_version`、表集、内容哈希不变；v17 正例与恢复篡改测试继续通过。
- 修改任一模块 readiness/gate/compatibility 并重算普通 checksum，TASK-05 validator 仍按语义拒绝；正常 handoff 继续通过。
- 同一 unsafe 请求重放失败；危险操作确认信息完整；仅键盘可打开/遍历/关闭 inspector 和移动导航并恢复焦点。

不要通过禁用 real API、把所有输入强制改标 synthetic、硬编码当前 fixture ID/SHA、只增加前端检查、信任 zip 文件名、降低 schema、删除失败记录或把 process-local 限制改写成文档说明来过测试。真实数据入口仍保持 gated；本轮只用许可 fixture、synthetic 数据和显式临时数据库验证。

提交继续采用普通、可审计历史，不 amend 既有两个提交。完成代码和回归后，删除本任务拥有的旧 `data/releases/task05_joint_workbench_v1/` 交接包并将该删除与整改源码一起纳入新的 implementation fix commit，建议消息 `Fix TASK-05 acceptance findings`；这样新 implementation HEAD 中不残留过期 handoff。只按明确路径暂存并审阅 staged diff，禁止 `git add .` 和根级 `git add -A`。以该 clean implementation commit 重新生成同一路径的 TASK-05 handoff、checksums 和报告，producer provenance 必须指向新的 implementation commit，再创建普通 handoff commit，建议消息 `Update TASK-05 handoff after remediation`。若生成 handoff 后又改源码，另建普通修复 commit、再次移除过期 handoff并重新生成，不 amend。

结束前依次运行新增最窄攻击回归、TASK-05 全部专项、`uv run --frozen pytest -q`、TASK-01 至 TASK-04 原生 validator、TASK-05 strict validator、handoff checksums、`node --check src/glyph_features/workbench/static/app.js`、桌面/移动 Playwright、v14 不变性与 v17 备份恢复演练、`uv lock --check`、敏感信息/绝对路径扫描和 `git diff --check`，并要求最终工作树和 index 为空。最终报告本轮可信起始 HEAD、新 implementation commit、新 handoff commit、每个反例的修复位置与公开测试、全部命令/退出码/测试数、临时数据库清理、共享热点修改和所有 blocked gate。不要 merge、push、创建 PR、访问生产数据库或替用户通过人工门禁；完成后等待第二轮独立验收。
```

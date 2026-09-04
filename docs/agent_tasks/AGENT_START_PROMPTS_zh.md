# GLYPH 新 Agent 首条提示词与执行环境

版本：`0.3.0-draft`
日期：2026-09-04
用途：由总设计者准备并行 worktree，并复制对应代码块作为每个实施 Agent 的第一条消息

## 1. 当前环境基线

以下是 2026-09-04 派发前已经验证的本机事实。Agent 仍须在开始时重新检查，不能因本文记录而跳过基线检查。

| 项目 | 已验证状态 |
|---|---|
| 操作系统 | macOS，Apple Silicon `arm64`，交互 shell 为 zsh |
| 协调工作区根目录 | `/Users/wuyida/Research/GLYPH` |
| Git 派发前状态 | `main` 与 `origin/main` 同在 `f89daec0e5e1f2df216a8e18c551d81f9954032f`；TASK-01 已验收但尚未提交 |
| 受保护的本地修改 | `README.md` 是 TASK-01 前已有的用户修改，不纳入并行 checkpoint，除非用户另行批准 |
| 现有 worktree | 只有协调工作区；TASK-02/03/04 worktree 尚未创建 |
| 磁盘余量 | 约 652 GiB，可容纳三个完整 worktree；仍须在创建时复核 |
| Python 约束 | `pyproject.toml` 要求 `>=3.11,<3.12` |
| 可用项目 Python | `.venv/bin/python` 与 `uv run --frozen python` 均为 CPython 3.11.15 |
| 禁止误用的 Python | 系统 `python3` 为 3.9.6，不满足项目约束 |
| 环境管理 | `uv 0.11.23`；存在 Conda `glyph` 环境，但规范命令统一使用项目 `.venv`/`uv run` |
| 锁文件 | `pyproject.toml`、`uv.lock`、`runtime.lock.json` 均由 Git 跟踪 |
| 测试 | 锁定环境提供 pytest 8.4.1；根测试入口为 `uv run --frozen pytest` |
| 网络代理 | 外网及 Git HTTPS 使用 `http://127.0.0.1:7897`，只按命令设置，不修改全局配置 |
| 社会叙事数据库 | 源码目标 schema v17；生产主库有意保持 v14，未经批准只能使用显式临时数据库 |

`f89daec...` 只是 TASK-01 实施前的远端基线，不再是剩余任务的派发 commit。TASK-02/03/04 必须从已验收 TASK-01 的本地 checkpoint 启动；该 checkpoint 在创建后以 `<TASK01_CHECKPOINT>` 代称。TASK-05 必须从 TASK-02/03/04 已验收并合并后的 commit 启动，以 `<INTEGRATED_TASK02_03_04_COMMIT>` 代称。复制 prompt 时必须将占位符替换为真实 40 位 commit；Agent 收到未替换占位符时必须停止。

## 2. 并行派发与提交总协议

### 2.1 角色与并行边界

1. 协调者独占 `/Users/wuyida/Research/GLYPH`，负责 TASK-01 checkpoint、worktree/分支创建、验收、合并、冲突处理和任何远端操作；实施 Agent 不得在协调工作区写入。
2. TASK-02、TASK-03、TASK-04 各使用一个预先创建的独立 worktree 和专属分支，可以同时运行；一个 worktree 同一时间只允许一个写入型 Agent。
3. TASK-05 不与前三项并行。只有 TASK-02/03/04 分别验收通过并合并后，协调者才从集成 commit 创建 TASK-05 worktree。
4. Agent 不得读取、复制或修改其他任务的未完成 worktree。跨任务依赖只通过起始 checkpoint、任务书、已冻结 schema 和已验收 handoff 传递。
5. TASK-04 并行阶段只依赖 TASK-01 和书面冻结接口；对 TASK-02/03 的未完成实现使用 adapter 边界、fixture 和明确假设，不得窥读其 worktree。最终接口校准由集成阶段完成。
6. `README.md`、`CONTRIBUTING.md`、`docs/agent_tasks/` 由协调者拥有。并行 Agent 不得编辑这些文件；需要修订时写入各自任务报告的 `integration_requests`，由协调者统一处理。
7. `pyproject.toml`、`uv.lock`、`runtime.lock.json`、`schema/README.md`、`data/README.md` 和包级注册文件是共享热点。Agent 仅在本任务确实需要时作最小修改，并在 handoff 中逐项列出；不得预注册其他任务或批量格式化。

### 2.2 协调者一次性准备

以下命令只由协调者在 `/Users/wuyida/Research/GLYPH` 执行。先逐项检查暂存内容，不使用 `git add .`，不纳入 TASK-01 前已有的 `README.md` 修改：

```bash
cd /Users/wuyida/Research/GLYPH
git switch -c integration/task-01-accepted

git add -- \
    CONTRIBUTING.md \
    docs/agent_tasks \
    pyproject.toml \
    configs/asset_curation_v1.yaml \
    data/README.md \
    data/fixtures/asset_system \
    data/templates/asset_candidates.csv \
    data/templates/curation_decisions.csv \
    docs/asset_curation_protocol_zh.md \
    docs/asset_history_remediation_plan_zh.md \
    schema/README.md \
    schema/asset_candidate.schema.json \
    schema/ecological_stimulus.schema.json \
    schema/handoff_manifest.schema.json \
    schema/rights_evidence.schema.json \
    src/glyph_features/asset_system \
    status/task_01_report_zh.md \
    tests/test_asset_system.py \
    '图包与字体包/标准化流程/render_font_samples.py'

git diff --cached --name-status
git diff --cached --check
uv run --frozen pytest -q
git commit -m "Add accepted TASK-01 asset system"
TASK01_CHECKPOINT=$(git rev-parse HEAD)
printf 'TASK01_CHECKPOINT=%s\n' "$TASK01_CHECKPOINT"
```

提交后，协调工作区允许只剩已知的 `README.md` 用户修改。若还有其他未提交文件，先辨认归属，不创建并行 worktree。确认后创建三条分支：

```bash
mkdir -p /Users/wuyida/Research/GLYPH-worktrees

git worktree add /Users/wuyida/Research/GLYPH-worktrees/task-02 \
    -b feature/task-02-visual-measurement "$TASK01_CHECKPOINT"
git worktree add /Users/wuyida/Research/GLYPH-worktrees/task-03 \
    -b feature/task-03-cross-cultural-experiment "$TASK01_CHECKPOINT"
git worktree add /Users/wuyida/Research/GLYPH-worktrees/task-04 \
    -b feature/task-04-han-style-knowledge "$TASK01_CHECKPOINT"

git worktree list
git -C /Users/wuyida/Research/GLYPH-worktrees/task-02 status --short --branch
git -C /Users/wuyida/Research/GLYPH-worktrees/task-03 status --short --branch
git -C /Users/wuyida/Research/GLYPH-worktrees/task-04 status --short --branch
```

三个新 worktree 必须各自 clean。不要让它们共享主工作区的 `.venv`；每个 worktree 使用自己的 `.venv`，但可复用 uv 的全局下载缓存。复制第 4、5、6 节 prompt 时，只在发给 Agent 的消息中把 `<TASK01_CHECKPOINT>` 替换为上一步真实值，不要为了嵌入 commit 而反复改写本手册。

### 2.3 每个并行 Agent 的本地提交协议

协调者预建分支后，TASK-02/03/04 Agent 获得以下有限 Git 权限：只能在自己的 worktree 和专属分支执行只读 Git 命令、按路径 `git add` 和普通 `git commit`。不得执行 `git switch`、`git checkout`、`git worktree`、`git stash`、`git reset`、`git clean`、`git merge`、`git rebase`、`git pull`、`git push`、`git commit --amend`、tag 或远端配置修改。

每个任务采用两阶段本地提交：

1. **实现提交**：包含本任务源码、schema、配置、测试、fixture、协议文档和必要的最小共享文件修改，但不包含最终生成的 handoff 包和最终报告。完成专项与全仓测试后，按明确路径暂存，检查 `git diff --cached --name-status` 和 `git diff --cached --check`，再创建普通 commit。
2. **交接提交**：以最新实现 commit 的 40 位哈希生成 handoff；`git_commit`/producer commit 必须指向该实现 commit，而不是 `<TASK01_CHECKPOINT>` 或尚不存在的交接 commit。严格验证 handoff 后，只暂存 handoff、最终报告和门禁包，创建第二个普通 commit。
3. 最终分支必须 clean。Agent 报告起始 checkpoint、实现 commit、交接 commit、相对起点的变更清单、测试命令/结果、handoff 路径和所有 blocked gate。
4. 若实现提交后发现缺陷，不 amend、不 rebase；创建新的普通修复 commit，把新的分支 tip 作为实现 commit，重新生成 handoff，再创建新的交接 commit。
5. 不使用 `git add .` 或仓库根级 `git add -A`。删除本任务拥有的文件时可使用限定路径的 `git add -A -- <task-owned-path>`。不得提交 `.venv`、缓存、数据库、日志、真实参与者数据、凭据、未知许可资产或其他 worktree 内容。
6. Agent 的“提交”只表示本地 branch commit 和 handoff，不表示 push、PR 或合并。远端备份、PR 和进入集成分支均由协调者在独立验收后决定。

### 2.4 协调者验收与集中合并

三个 Agent 可以同时实施，但由协调者分别验收。只有分支 clean、专项/全仓测试通过、handoff 严格验证通过且 readiness/人工 gate 如实表达时，才允许合并。协调者按 TASK-02、TASK-03、TASK-04 顺序执行本地 `--no-ff` 合并；并行 Agent 不互相合并。

合并前先确认任务分支没有修改受保护文件，特别是 `README.md`、`CONTRIBUTING.md` 和 `docs/agent_tasks/`。共享热点冲突由协调者按三个任务的真实依赖统一解决，并在每次合并后运行该任务专项测试；三项全部合并后运行全仓测试和全部 handoff validator。

```bash
cd /Users/wuyida/Research/GLYPH
git branch --show-current  # 必须是 integration/task-01-accepted

git merge --no-ff feature/task-02-visual-measurement -m "Merge TASK-02 visual measurement"
git merge --no-ff feature/task-03-cross-cultural-experiment -m "Merge TASK-03 cross-cultural experiment"
git merge --no-ff feature/task-04-han-style-knowledge -m "Merge TASK-04 Han style knowledge"

uv run --frozen pytest -q
INTEGRATED_TASK02_03_04_COMMIT=$(git rev-parse HEAD)
printf 'INTEGRATED_TASK02_03_04_COMMIT=%s\n' "$INTEGRATED_TASK02_03_04_COMMIT"

git worktree add /Users/wuyida/Research/GLYPH-worktrees/task-05 \
    -b feature/task-05-joint-workbench "$INTEGRATED_TASK02_03_04_COMMIT"
git -C /Users/wuyida/Research/GLYPH-worktrees/task-05 status --short --branch
```

若协调工作区仍保留已知 `README.md` 修改，三个任务分支必须都不触碰该文件；否则在 merge 前停止并由用户决定。获得集成 commit 后才能创建 TASK-05 worktree，并在发送第 7 节 prompt 时替换 `<INTEGRATED_TASK02_03_04_COMMIT>`。

TASK-01 已验收通过，第 3 和 3.1 节保留作审计记录，不再派发。首次并行派发时，第 4、5、6 节各发送到一个新 Agent 会话；每个会话只发送对应的完整代码块。

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

## 4. TASK-02 首条 prompt

```text
你是 GLYPH 的 TASK-02 执行 Agent，只负责理论构念、可解释视觉测量与 CV 子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-02`，唯一允许停留的分支是 `feature/task-02-visual-measurement`，起始 commit 必须是 `<TASK01_CHECKPOINT>`。如果这段消息中的 `<TASK01_CHECKPOINT>` 没有被替换成 40 位小写 commit，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-02 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-03、task-04 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-02`，分支正好是 `feature/task-02-visual-measurement`，HEAD 正好是 `<TASK01_CHECKPOINT>`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-02 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/02_visual_measurement_system_task_zh.md、CONTRIBUTING.md，以及现有 src/glyph_features、configs/visual_features_v1.yaml、visual v1 参考运行和 lijie_aesthetic_cv。现有 visual v1 是冻结兼容基线；李婕目录是待工程化原型，不是第二套可直接发布的生产管线。

先验证 `<TASK01_CHECKPOINT>` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。只消费该 checkpoint 内已验收的许可 fixture 和冻结契约；不得读取其他并行 worktree 的实现。保持 v1 历史 schema/参考运行可读，canonical 输出不得含未经真人校准的综合审美分，也不得根据预期结论修改特征。需要本机服务时只绑定 127.0.0.1，优先使用端口 8022；端口被占用时选择空闲端口并记录。

每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-02 专项、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。涉及专家判断时停在 GATE-EXPERT。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-02 的路径执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有其他任务、真实数据、凭据、缓存或绝对路径后，提交 `git commit -m "Add TASK-02 visual measurement system"`。将此时 `git rev-parse HEAD` 记录为 TASK-02 implementation commit。

第二阶段以该 implementation commit 生成最终 handoff_manifest.json、checksums、门禁包和 TASK-02 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写 `<TASK01_CHECKPOINT>` 或未来的交接 commit。严格验证 handoff，明确计算稳定性、表面效度、构念效度、预测效度及三档 readiness。然后只暂存生成的 handoff、门禁包和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-02 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-02 专项、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 `<TASK01_CHECKPOINT>`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改和 blocked gate。不要 push、创建 PR、合并其他分支、运行真实人评或进入 TASK-05；完成后等待独立验收。
```

## 5. TASK-03 首条 prompt

```text
你是 GLYPH 的 TASK-03 执行 Agent，只负责跨文化感知实验与简中、英文、日文、韩文问卷子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-03`，唯一允许停留的分支是 `feature/task-03-cross-cultural-experiment`，起始 commit 必须是 `<TASK01_CHECKPOINT>`。如果这段消息中的 `<TASK01_CHECKPOINT>` 没有被替换成 40 位小写 commit，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-03 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-04 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-03`，分支正好是 `feature/task-03-cross-cultural-experiment`，HEAD 正好是 `<TASK01_CHECKPOINT>`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-03 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/03_cross_cultural_experiment_task_zh.md、CONTRIBUTING.md 和现有 schema。真实参与者数据进入受限、被 Git 忽略的存储；联系/补偿 PII 与研究响应物理分离。任何本机 Web 服务默认只绑定 127.0.0.1。

先验证 `<TASK01_CHECKPOINT>` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。只用该 checkpoint 内的许可 fixture 和 synthetic participants 完成协议、schema、平衡不完全区组分配、四语界面、质量规则、去标识导出和浏览器验证；不得读取其他并行 worktree 的实现。synthetic 数据必须机械拒绝进入正式分析和 release。Web 服务只绑定 127.0.0.1，优先使用端口 8023；端口被占用时选择空闲端口并记录。

不得提交伦理申请、联系/招募真人、收集真实响应、接受第三方条款或把机器翻译标成已审核。任何真实参与者响应、联系信息、补偿记录、cookie、浏览器配置、数据库、WAL、日志或截图中的个人信息都不得暂存或提交。每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-03 专项、桌面/移动浏览器验收、相关 `node --check`、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-03 的源码、schema、配置、测试、synthetic fixture、空模板和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，机械扫描 staged 内容不存在 PII、凭据、真实响应和绝对路径后，提交 `git commit -m "Add TASK-03 cross-cultural experiment system"`。将此时 `git rev-parse HEAD` 记录为 TASK-03 implementation commit。

第二阶段以该 implementation commit 生成 GATE-ETHICS、GATE-PARTICIPANTS 等门禁包、handoff_manifest.json、checksums 和 TASK-03 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写 `<TASK01_CHECKPOINT>` 或未来的交接 commit。严格验证 handoff，保持真实收集锁定，并如实标记翻译、伦理、招募和真人 pilot 的 readiness。然后只暂存 handoff、checksums、门禁包、无个人信息的验收证据和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-03 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-03 专项、浏览器验收、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 `<TASK01_CHECKPOINT>`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改、数据来源扫描和 blocked gate。不要 push、创建 PR、合并其他分支、接触真人或进入 TASK-05；完成后等待独立验收。
```

## 6. TASK-04 首条 prompt

```text
你是 GLYPH 的 TASK-04 执行 Agent，只负责汉字书体、字形演化知识、受控候选与专家在环子系统。

你在预建的独立 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，唯一允许停留的分支是 `feature/task-04-han-style-knowledge`，起始 commit 必须是 `<TASK01_CHECKPOINT>`。如果这段消息中的 `<TASK01_CHECKPOINT>` 没有被替换成 40 位小写 commit，立即停止并要求协调者重新派发，不要自行猜测。

项目环境是 macOS arm64/zsh。所有命令从 TASK-04 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-03 或任何其他 worktree，也不得从那些目录复制未完成文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-04`，分支正好是 `feature/task-04-han-style-knowledge`，HEAD 正好是 `<TASK01_CHECKPOINT>`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge 或复制文件来自行“修复”环境。

并行期间只允许在本分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/。若确需修改 pyproject.toml、uv.lock、runtime.lock.json、schema/README.md、data/README.md 或包级注册文件，只做 TASK-04 所需最小变更，并在最终报告的 `integration_requests` 中逐项说明。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/04_han_style_knowledge_task_zh.md、CONTRIBUTING.md、TASK-01 已验收 handoff，以及 checkpoint 中 TASK-02/03 的书面接口要求。必须区分书体概念、字体实例、字形实例、作品、历史断言、文化联想和专家审核；所有真实字形资产先经过 TASK-01 权利与资产接口，正式 stimulus_id 由 TASK-01 冻结。

先验证 `<TASK01_CHECKPOINT>` 中的 TASK-01 handoff 2.0 严格通过，再提出一个可证伪的局部实现假设和最便宜检查，然后直接实施。先做本体、证据链、字符映射、review package、导入器和许可 fixture；不得读取 TASK-02/03 并行 worktree。与视觉测量或问卷的连接必须封装为 adapter，对当前书面契约和 synthetic fixture 编程；未能在本分支证明的字段放入机器可读 blocked 状态和最终报告 `integration_requests`，不得猜测其他 Agent 将如何实现。需要本机服务时只绑定 127.0.0.1，优先使用端口 8024。

不得联系专家、发送真实材料、伪造专家结论、下载未知许可字形或以现代字体名证明历史归属。每类实例不足时机械限制为 instance_level_only。真实专家、权利、受限下载和条款步骤分别停在 GATE-EXPERT、GATE-RIGHTS、GATE-TERMS；门禁包可以提交，门禁结果不能由 Agent 自行改成 passed。

每次首次实质编辑后立即运行最窄可执行验证；完成实现后运行 TASK-04 专项、`uv run --frozen pytest -q`、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-04 的源码、schema、配置、测试、许可 fixture、空模板和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有其他任务、专家个人信息、未知许可资产、凭据、缓存或绝对路径后，提交 `git commit -m "Add TASK-04 Han style knowledge system"`。将此时 `git rev-parse HEAD` 记录为 TASK-04 implementation commit。

第二阶段以该 implementation commit 生成 handoff_manifest.json、checksums、GATE-EXPERT/GATE-RIGHTS/GATE-TERMS 门禁包和 TASK-04 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写 `<TASK01_CHECKPOINT>` 或未来的交接 commit。严格验证 handoff，明确实例级与类别级推断、`instance_level_only` 降级、adapter 假设及三档 readiness。然后只暂存 handoff、checksums、门禁包和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-04 handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑 TASK-04 专项、全仓测试、handoff validator、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 `<TASK01_CHECKPOINT>`、implementation commit、handoff commit、全部验证结果、handoff 路径、共享热点修改、`integration_requests` 和 blocked gate。不要 push、创建 PR、合并其他分支、接触专家或进入 TASK-05；完成后等待独立验收。
```

## 7. TASK-05 首条 prompt

```text
你是 GLYPH 的 TASK-05 执行 Agent，只负责四线联合分析、统一工作台和系统总装；只有 TASK-01 至 TASK-04 已提供可验证 handoff 后才执行正式总装。

你在三路上游完成独立验收并集中合并后预建的 Git worktree 中工作。唯一允许写入的根目录是 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，唯一允许停留的分支是 `feature/task-05-joint-workbench`，起始 commit 必须是 `<INTEGRATED_TASK02_03_04_COMMIT>`。如果这段消息中的占位符没有被替换成 40 位小写 commit，立即停止并要求协调者重新派发，不要自行猜测或拉取上游分支。

项目环境是 macOS arm64/zsh。所有命令从 TASK-05 worktree 根目录运行，不得 `cd` 到 `/Users/wuyida/Research/GLYPH`、task-02、task-03、task-04 或其他 worktree，也不得从那些目录复制文件。项目要求 Python >=3.11,<3.12；使用本 worktree 自己的 `.venv` 与 `uv run --frozen python`，禁止复用主工作区或其他 worktree 的 `.venv`，禁止使用系统裸 `python3`。依赖由集成 commit 中的 pyproject.toml、uv.lock、runtime.lock.json 锁定；首次需要时可在本 worktree 运行 `uv sync --locked --extra dev`，测试默认用 `uv run --frozen pytest ...`。

所有 Git HTTPS 和其他外网命令走 http://127.0.0.1:7897，但只对当前命令设置代理。Git 使用 `git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 ...`；应用外连使用 `GLYPH_OUTBOUND_PROXY=http://127.0.0.1:7897`。不得修改全局 Git/系统代理，不得在聊天、日志或仓库写入凭据。

开始时先运行并报告：`pwd -P`、`git branch --show-current`、`git rev-parse HEAD`、`git status --porcelain=v1 --untracked-files=all`、`git worktree list`、`git log --oneline --decorate -8`、`git config user.name`、`git config user.email`、`uv --version`、`uv run --frozen python -V`。必须同时满足：物理路径正好是 `/Users/wuyida/Research/GLYPH-worktrees/task-05`，分支正好是 `feature/task-05-joint-workbench`，HEAD 正好是 `<INTEGRATED_TASK02_03_04_COMMIT>`，工作树为空。任一不符就停止并报告，不得通过 switch、reset、stash、clean、merge、rebase、pull 或复制文件来自行“修复”环境。

本任务只允许在当前分支执行只读 Git 命令、限定路径的 `git add` 和普通 `git commit`。禁止 `git switch`、`checkout`、`worktree`、`stash`、`reset`、`clean`、`merge`、`rebase`、`pull`、`push`、`commit --amend`、tag 和远端配置修改。上游分支已经由协调者合并；若发现缺失、不兼容或冲突，不得自行 merge task-02/03/04，而应机械标记 blocked 并停止相关切片。不得编辑或提交 README.md、CONTRIBUTING.md、docs/agent_tasks/；共享注册文件只作 TASK-05 总装所需最小修改。

完整阅读 docs/agent_tasks/00_system_blueprint_zh.md、docs/agent_tasks/05_joint_analysis_workbench_task_zh.md、CONTRIBUTING.md、所有上游 handoff，以及现有 src/glyph_features/social_system。社会叙事源码目标数据库 schema v17，但生产主库有意保持 v14；未经用户明确批准，所有启动、迁移、备份恢复和 E2E 都必须使用显式临时数据库，绝不能省略 `--database` 后误触 data/raw/social/glyph-social.sqlite3。

开始实现前逐一运行 TASK-01、TASK-02、TASK-03、TASK-04 的 handoff validator，核对 manifest 声明的 producer commit 可由当前集成历史追溯，并记录各自 readiness、schema 版本和 blocked gate。任一 handoff 缺失、被篡改或不兼容时，只阻断对应入口并报告；不得从其他 worktree、聊天附件或临时文件补齐。

随后提出一个可证伪的局部实现假设和最便宜检查并直接实施。总装采用 adapter、规范导出和中央目录，不直接修改模块私有表、不启动重复 scheduler、不重写成熟社会叙事核心。缺少或不兼容 handoff 时显示 blocked/fixture-only，不猜字段或伪造输出。联合模型必须防止多对多膨胀、伪重复、数据泄漏和无依据的 WP2 个体暴露联结。Web 服务只绑定 127.0.0.1，优先使用端口 8025。

先用许可 fixture、synthetic ratings 和显式临时数据库完成 E2E；正式 release 必须因 synthetic 或未决人工门禁被机械阻断。每次首次实质编辑后立即运行最窄验证；完成实现后运行模块契约测试、`uv run --frozen pytest -q`、必要的 `node --check`、浏览器桌面/移动验收、备份恢复演练、`uv lock --check` 和 `git diff --check`。不要调用其他 Agent。

验证通过后执行两阶段本地提交。第一阶段用 `git status --short` 列出改动，只对逐项确认属于 TASK-05 的源码、adapter、schema、配置、测试、许可 fixture、synthetic 数据和协议文档执行 `git add -- <明确路径...>`；禁止 `git add .` 和根级 `git add -A`。运行 `git diff --cached --name-status`、`git diff --cached --check` 并审阅 `git diff --cached`，确认没有生产数据库、真实响应、凭据、缓存、绝对路径或上游任务的无关重写后，提交 `git commit -m "Add TASK-05 joint analysis workbench"`。将此时 `git rev-parse HEAD` 记录为 TASK-05 implementation commit。

第二阶段以该 implementation commit 生成系统 handoff_manifest.json、checksums、门禁包和 TASK-05 报告；handoff 的 producer/git commit 必须指向 implementation commit，不得填写 `<INTEGRATED_TASK02_03_04_COMMIT>` 或未来的交接 commit。严格验证系统 handoff，逐模块说明 engineering_ready、pilot_ready、research_validated，并保留所有上游 blocked/fixture-only 状态。然后只暂存系统 handoff、checksums、门禁包、无敏感信息的 E2E 证据和最终报告，复查 staged diff，提交 `git commit -m "Add TASK-05 system handoff"`。若第一阶段后又修了代码，创建普通修复 commit，不 amend；用新的分支 tip 重新生成 handoff，再提交新的交接 commit。

结束前重跑模块契约测试、全仓测试、四个上游及系统 handoff validator、前端语法检查、浏览器验收、备份恢复、`uv lock --check` 和 `git diff --check`，并要求 `git status --porcelain=v1 --untracked-files=all` 为空。最终报告起始 `<INTEGRATED_TASK02_03_04_COMMIT>`、implementation commit、handoff commit、全部验证结果、系统 handoff 路径、临时数据库路径/清理结果、共享热点修改和 blocked gate。不要 push、创建 PR、合并分支、触碰生产数据库或替用户通过人工门禁；完成后等待独立验收。
```

## 8. 代理命令速查

所有实施 Agent 先在自己的 worktree 运行以下守卫，不在协调工作区运行：

```bash
pwd -P
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1 --untracked-files=all
git worktree list
uv run --frozen python -V
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

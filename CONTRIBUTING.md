# GLYPH 团队协作与提交指南

本文供需要将代码、文档或研究材料提交到 GLYPH 仓库的组员使用。

默认协作方式是：**每个人使用自己的 GitHub 账号，在独立分支上提交，通过 Pull Request 合并到 `main`**。
不要共享 GitHub 密码、Personal Access Token、SSH 私钥或平台 API 凭据，也不要直接向 `main` 强制推送。

## 开始前

1. 把自己的 GitHub 用户名发给仓库管理员。
2. 管理员在仓库 `Settings` → `Collaborators` 中发出邀请；若界面提供角色选项，选择 `Write`。个人仓库的协作者通常默认具有写权限。
3. 在 GitHub 通知或邮件中接受邀请。
4. 确认本机 Git 使用的是自己的身份：

```bash
git config --global user.name "你的姓名或 GitHub 用户名"
git config --global user.email "你的 GitHub 邮箱"
```

GitHub 不接受账号密码作为 Git 推送凭据。推荐使用以下任一方式登录：

- GitHub CLI：运行 `gh auth login`，按提示登录自己的账号；
- SSH：把自己的 SSH 公钥添加到 GitHub，然后使用 SSH 仓库地址；
- HTTPS：使用自己账号的 credential manager 或 Personal Access Token。

任何 token、密码或私钥都不要发到群聊，也不要写进仓库文件。

## 第一次克隆仓库

HTTPS：

```bash
git clone https://github.com/Yonagi043/GLYPH.git
cd GLYPH
```

或者使用 SSH：

```bash
git clone git@github.com:Yonagi043/GLYPH.git
cd GLYPH
```

确认远端和当前状态：

```bash
git remote -v
git status
```

不要在已经克隆的 GLYPH 目录里再次运行 `git init`。

## 每项工作新建一个分支

开始修改前，先同步最新 `main`：

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/你的名字-简短任务名
```

分支名使用英文小写、数字和连字符，不要使用空格。例如：

```text
feature/zhang-survey-import
fix/li-schema-validation
docs/wang-method-note
```

建议前缀：

| 前缀 | 用途 |
|---|---|
| `feature/` | 新功能或新的研究处理能力 |
| `fix/` | 缺陷修复 |
| `docs/` | 文档或报告 |
| `test/` | 测试与 fixture |
| `data/` | 经负责人确认可提交的数据模板或发布材料 |

不要直接在 `main` 上开发。如果尚未提交但已经在 `main` 修改了文件，可以立即运行：

```bash
git switch -c feature/你的名字-简短任务名
```

如果已经误提交到本地 `main`，先不要 push，也不要自行强制重置；联系仓库管理员一起处理。

## 已经在其他目录做完一部分怎么办

最安全的方式是克隆一份最新 GLYPH，再把需要的文件复制到新分支：

```bash
git clone https://github.com/Yonagi043/GLYPH.git
cd GLYPH
git switch -c feature/你的名字-简短任务名
```

然后从原工作目录复制实际代码、文档或测试。不要复制以下内容：

- 原项目的 `.git/`；
- `.env`、token、cookie、证书或账号配置；
- `.venv/`、`node_modules/`、缓存、日志和构建目录；
- 本机数据库、备份、原始平台响应或未获许可的数据；
- 与本次工作无关的格式化或批量改名。

不要把现有项目的 `origin` 强行改成 GLYPH 后覆盖推送，也不要使用 `git push --force`。如果两个项目
目录结构差异较大，先在 Pull Request 中说明文件应该放在哪里，必要时请管理员协助拆分。

## 仓库目录约定

```text
src/glyph_features/   Python 源码
tests/                自动化测试
tests/fixtures/       合成或明确去敏的测试 fixture
schema/               共享 JSON Schema
configs/              冻结或版本化配置
data/templates/       可提交的空模板和最小示例
data/raw/             原始数据，默认禁止提交
data/processed/       本地处理结果，默认禁止提交
data/releases/        仅放经过许可与审核的发布数据
docs/                 稳定说明、技术报告与运维文档
status/               阶段记录、提案和工作日志
tools/                可复现的辅助工具
```

修改 `schema/`、`configs/`、`data/templates/`、依赖锁文件或既有里程碑报告前，请在 PR 中明确说明原因和
兼容性影响。不要为了让测试通过而改写历史研究事实、审核记录或已冻结协议。

未经项目负责人单独明确批准，不得执行真实平台 API 请求、登录/OAuth、付费、购买 credits、抓取或
上传真实参与者及平台用户数据。

## 提交前检查

先看清自己改了什么：

```bash
git status
git diff
git diff --check
```

安装项目开发依赖并运行测试：

```bash
uv sync --locked --extra dev
uv run pytest -q
```

如果修改了社会叙事前端 JavaScript，再运行：

```bash
node --check src/glyph_features/social_system/static/app.js
```

如果修改了依赖，应同时提交相应的 `pyproject.toml` 和锁文件，并在 PR 中解释新增依赖的用途。不要
为了消除无关失败而修改其他模块；把与本次工作无关的既有问题写在 PR 说明里。

## 数据和凭据红线

提交前确认没有包含：

- `.env` 或任何真实 API key、bearer token、client secret、refresh token；
- GitHub PAT、SSH 私钥、代理密码或浏览器 cookie；
- `*.sqlite3`、数据库 WAL、备份、运行日志；
- `data/raw/` 中的原始材料；
- 未经许可的全文、图片、视频、字体、问卷回答或个人信息；
- 能直接识别平台用户或研究参与者的字段；
- 大型生成产物、虚拟环境和依赖缓存。

测试数据必须是合成数据或明确去敏的 fixture，示例 secret 应使用 `REDACTED_FIXTURE_*` 形式。

如果真实 secret 曾经进入 Git 历史，**不要只删除文件后继续 push**。立即停止操作，通知仓库管理员，
并撤销或轮换该 secret。

## 暂存与提交

优先明确选择本次要提交的文件，不建议直接使用 `git add .`：

```bash
git add src/glyph_features/相关目录 tests/相关测试 docs/相关文档.md
git diff --cached
git status
```

确认 staged diff 只包含本次任务后提交：

```bash
git commit -m "Add concise description of the change"
```

提交信息应使用动词开头，说明这个提交做了什么。例如：

```text
Add survey response validator
Fix script classification mapping
Document annotation workflow
```

一个提交尽量只处理一个主题。不要把个人编辑器设置、临时文件或无关格式化混入功能提交。

## 推送自己的分支

首次推送：

```bash
git push -u origin feature/你的名字-简短任务名
```

后续同一分支只需：

```bash
git push
```

不要运行：

```text
git push --force origin main
git push origin HEAD:main
```

遇到 `403` 时，先确认已经接受协作者邀请、终端登录的是自己的正确 GitHub 账号，并确认自己有
`Write` 权限。不要借用管理员凭据。

## 创建 Pull Request

推送后打开 GitHub 仓库，点击 `Compare & pull request`：

- base 分支选择 `main`；
- compare 分支选择自己的功能分支；
- 标题简要说明改动；
- 不要自行合并，等待至少一名组员或仓库管理员审查。

PR 说明至少包含：

```markdown
## 做了什么

简述实现或材料。

## 为什么

说明任务背景和研究目的。

## 如何验证

- `uv run pytest -q`
- 其他专项检查及结果

## 数据与权限

- 是否包含真实数据：否/是（若是，注明审批与许可）
- 是否发起真实平台请求：否/是（若是，注明批准记录）
- 是否包含凭据：必须为否

## 已知限制

列出尚未覆盖或需要审查的部分。
```

如果改了界面，请附桌面和移动端截图，并说明浏览器验证范围。不要在截图中暴露账号、token、个人
信息或原始研究数据。

## PR 期间同步 `main`

如果其他人的改动先合并了，可以把最新 `main` 合并到自己的分支：

```bash
git fetch origin
git switch feature/你的名字-简短任务名
git merge origin/main
```

如果发生冲突：

1. 运行 `git status` 查看冲突文件；
2. 与相关文件负责人确认应保留的内容；
3. 编辑并移除冲突标记；
4. 运行测试；
5. `git add` 已解决文件，然后完成 merge commit；
6. 再次 `git push`。

不确定如何解决时，保留现场并在 PR 中求助。不要通过删除他人代码、覆盖整个文件或强推来“解决”
冲突。

## 合并后清理

PR 合并后更新本地 `main`，删除已经完成的本地分支：

```bash
git switch main
git pull --ff-only origin main
git branch -d feature/你的名字-简短任务名
```

GitHub 上的远端功能分支可以在 PR 页面点击 `Delete branch` 删除。

## 最短操作清单

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/你的名字-任务名

# 修改文件并运行测试
uv run pytest -q

git status
git diff --check
git add 需要提交的文件
git diff --cached
git commit -m "Add concise description"
git push -u origin feature/你的名字-任务名

# 最后到 GitHub 创建 Pull Request，不直接推 main
```
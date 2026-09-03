# GLYPH 社会叙事监测系统

> 路线状态（2026-09-02）：M5 已按 Reddit → TikTok Research API → X 完成统一系统的本地实现、
> 去敏 fixture 和离线验证。三者都处于“离线待接入”，不代表平台批准或真实接入；未登录、未提交
> 申请、未接受条款、未配置真实凭据、未购买 credits、未启用付费，也未发真实平台请求。
> 本轮不继续 M3 人工流程、不执行 Mastodon pilot，也不进入 M6。

这是文化—历史叙事线的公开实现说明。系统回答的是：**在一组明确声明的
平台、语言、时间窗和检索式中，哪些文字/书体/字体与哪些描述共同出现**。
它不测量全网流量、曝光量、公众总体意见，也不证明因果传播。

## 借鉴了什么

| 已有尝试 | 已验证的经验 | GLYPH 的取舍 |
| --- | --- | --- |
| [4CAT](https://github.com/digitalmethodsinitiative/4cat)（MPL-2.0） | 采集、处理、数据集和运行记录分开，保留中间结果 | 采用同样的分层原则；只实现轻量离线核心，不依赖易变的插件栈 |
| [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer)（MPL-2.0） | 正常浏览时可以得到没有稳定 API 的平台观察 | 只作为有固定配额的人工观察输入；不绕过登录、验证码或反爬，也不称为平台总体样本 |
| [Facepager](https://github.com/strohne/Facepager)（MIT） | 分页、限速、SQLite、请求日志是可复查性的基础 | 可接收它的导出；运行说明和结果统一进入 GLYPH schema |
| [PRAW](https://github.com/praw-dev/praw)（BSD-2-Clause） | OAuth 与限速响应处理适合 Reddit | 借鉴生命周期；本仓库使用可注入 token provider 和官方 JSON 结构，不嵌入 PRAW |
| [YouTube Data Tools](https://github.com/bernorieder/YouTube-Data-Tools-v2)（GPL-3.0-or-later） | 批量请求、配额记录、作者伪名化、离线 fixture、运行报告 | 借鉴控制措施，不嵌入 GPL 应用；导出后由 GLYPH 规范化 |
| [X API v2/XDK](https://docs.x.com/x-api/getting-started/about-x-api.md) | 固定查询和 API 响应可以审计；公开指标不等于曝光 | 获批并设预算后才启用，只请求必要字段，遵守 ID/数据分发限制 |
| [TikTok Research API](https://developers.tiktok.com/products/research-api/) | 官方研究接口提供视频、评论与回复的有界分页 | 只有资格获批后才启用；冻结 query AST、`search_id`、UTC 日预算和分层上限 |
| [Taguette](https://gitlab.com/remram44/taguette)（BSD-3-Clause） | 人工高亮和编码使文本证据可检查 | 机器/LLM 只生成待办候选；正式编码必须有原文片段、编码员和时间 |

数字痕迹方法还提醒我们：API、浏览器观察和数据捐赠观察到的不是同一个
世界（Tufekci，2014；Ohme 等，2023）。所以只比较相同平台、语言、
时间窗、检索式和计数规则的单元。

## 仓库中的文件

```text
data/templates/social_queries.csv             # 已登记的检索式
data/templates/social_codebook.csv            # 允许的标签及判定规则
data/templates/social_object_map.csv          # 规范对象标签和别名
data/templates/social_run_manifest.json       # 一次运行的示例说明
data/templates/sources.csv                    # 来源登记表（CSV 投影）
configs/social_narrative_v0.yaml              # 冻结的试运行方案
schema/social_run_manifest.schema.json        # 采集运行契约
schema/social_observation.schema.json         # 单条规范化观察
data/raw/social/<平台>/<run_id>/              # 本地原始导出，git 忽略
data/processed/social_narrative_v0/           # 本地处理结果，git 忽略
tools/social_io.py                            # 共用读取、哈希和 schema 校验
tools/normalize_social_records.py             # JSON/JSONL/CSV → JSONL
tools/validate_social_observations.py         # 离线发布闸门
tools/summarize_narratives.py                 # 双向概率矩阵和 Lift
tools/project_social_to_narratives.py         # 人工确认记录 → 共享叙事 schema
tools/x_discourse_monitor.py                  # 可选的旧版 X 快照演示
```

不要把 API 密钥、cookie、用户名、受限全文、下载的视频或截图提交到仓库。
公开 release 只能放许可允许的元数据、短摘录、平台允许的 ID/URL、哈希和派生
统计表。

## 一次运行的做法

1. 在 `social_queries.csv` 登记精确检索式，固定语言、地区、品类、UTC 起止
   时间、数量上限和去重规则。
2. 在本地 raw 运行目录复制 `social_run_manifest.json`，填写采集器、端点/API
   版本、原始文件 SHA-256、条款检查日期、保留决定和完成时间。
3. 将获准 API 或人工导出放入
   `data/raw/social/<platform>/<collection_run_id>/`。统一本机运行层只实现明确登记的官方 API
   适配器；它不抓取网页、不绕过访问控制，也可继续接收研究者正常浏览得到的导出。
   4. 离线规范化。工具按“平台 + 运行 + 平台条目 ID”生成观察身份，按稳定 ID 排序，默认不保留直接作者标识；它只移除已知追踪参数和 fragment，不联网跟随重定向；每一行都校验，
   失败写入 CSV，绝不静默丢弃。失败表是待修复工作队列；修复上游导出后必须重新运行，未清零的失败不能进入 release。

规范记录中的 `content_status` 区分可读正文、只有图片/视频、已删除、私有和无法访问；
空的 `text` 不再被误当作“没有叙事”。

   ```bash
   python tools/normalize_social_records.py \
     --input data/raw/social/reddit/social_run_20260901_reddit/export.json \
     --output data/processed/social_narrative_v0/observations.jsonl \
     --platform reddit --source-kind official_api \
     --collection-run-id social_run_20260901_reddit \
     --query-id q_typography_en \
     --normalized-at 2026-09-01T12:00:00Z
   ```

5. 运行离线发布闸门：有错误就不能用于 release；警告会写入报告，由审查员
   处理。

   ```bash
   python tools/validate_social_observations.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --queries data/templates/social_queries.csv \
     --codebook data/templates/social_codebook.csv \
     --objects data/templates/social_object_map.csv \
     --sources data/processed/social_narrative_v0/sources.csv \
     --run-manifest data/raw/social/reddit/social_run_20260901_reddit/run_manifest.json \
     --report data/processed/social_narrative_v0/validation.json
   ```

6. 两名审查员编码对象、评价词、立场、机制和精确证据片段。`candidate` 只是
   待办队列，主结果只收 `human_verified`。每个平台—语言单元至少 20% 双人
   编码后，才报告比较结果。
7. 生成双向关联矩阵。默认按记录计数；可见互动只是单独的描述性敏感性结果。

   ```bash
   python tools/summarize_narratives.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --output-dir data/processed/social_narrative_v0/matrices/summary_20260901
   ```

如果人工确认的记录还要进入冻结的文化叙事线，必须显式投影（每个已确认的对象—评价词组合输出一行）：

   ```bash
   python tools/project_social_to_narratives.py \
     --input data/processed/social_narrative_v0/observations.jsonl \
     --output data/processed/social_narrative_v0/narratives.jsonl
   ```

如果社会观察中的角色是 `creator`，投影到既有文化叙事 schema 时会明确降为
`unknown`，不会把创作者误标成设计师或普通用户；原始角色仍保留在社会观察记录中。
X 快照脚本只是可选的旧版演示，不是离线核心的依赖；其输出在单独完成人权、许可和隐私审查前不得公开发布。

## 计算方式

对象为 \(S\)，评价词为 \(A\)：

\[
P(A\mid S)=\frac{n(S,A)}{n(S)},\qquad
P(S\mid A)=\frac{n(S,A)}{n(A)},\qquad
\operatorname{Lift}(S,A)=\frac{P(A\mid S)}{P(A)}。
\]

默认的 (n) 是记录数。一条记录若有两个标签，会分别进入两个标签格；这是
“多标签是否出现”，不是说标签互斥。`--weight engagement` 另做一张描述表，
只使用可见点赞、评论、分享、引用和平台 score；播放/浏览量单独报告，不能默默
当作互动。
角色、引用、证据和时间序列表始终按记录数编制，即使另外要求了互动量加权的敏感性表；
`summary.json` 会写明这一点，避免把不同单位混在一起。
矩阵还会写出 `exploratory` 标记；对象或评价词分母小于 20 的单元只能作为探索，
不能排名或支持跨组结论。

Lift 大于 1 只表示在这组过滤条件下共同出现多于样本基线，不能证明某种文字
天然高级、算法造成曝光，或样本代表总体。

## 平台取舍

统一运行层已覆盖 Bluesky、YouTube、Mastodon、Reddit、TikTok Research API 和 X。Reddit、
TikTok、X 当前只有离线待接入能力：必须分别满足 OAuth/用途、Research Tools 资格、X 价格与
双层费用上限门禁后，才可提交独立真实 pilot 批准。Instagram、抖音、小红书在有合法稳定入口前
只作为人工/浏览器捕获输入。Pushshift、snscrape、CrowdTangle、已归档 TCAT 仅作历史方法参考，
不作为当前依赖。绝不通过浏览器自动化绕过平台 API 或反爬。

## 结果边界

输出可以指出“哪些有来源的说法在何处、何时、由谁（若允许记录）共同出现”，并
为 GLYPH 的真人评分实验提出具体假设。它不能证明叙事的真正历史起源、总传播、
推荐算法、因果影响或人的审美偏好；后几类问题交给史料考证和真人实验。

## 参考

完整的编号参考文献、工具链接和许可证核验清单见
[`status/social_narrative_methods_review_zh.md`](../status/social_narrative_methods_review_zh.md)。

# GLYPH 社会叙事：相关工作、开源工具与 M3 改进建议

版本：`0.1.0`<br>
日期：2026-09-02<br>
状态：只读调研记录与 M3 纠偏建议；不是 M3 完成报告，不授权新的平台采集或 M4 工作

## 1. 目的与范围

本记录回答三个问题：

1. 与 GLYPH 文化—历史叙事线最相关、认可度较高的方法工作提供了哪些可迁移设计？
2. 哪些开源工具值得直接采用、借鉴、保留为上游选项或明确延后？
3. 如何在不推倒 frozen schema、不更换现有本机系统的前提下纠正 M3 YouTube 实现？

调研日期为 2026-09-02。可控终端外网核验均显式使用：

```text
http://127.0.0.1:7897
```

书目信息通过 Crossref、OpenAlex 和 DOI 页面交叉核验；工具信息通过官方仓库 README、LICENSE 和提交记录核验；YouTube 行为通过 Google 官方 Data API 文档核验。本轮没有安装外部工具、启动采集服务或产生新的平台请求。

OpenAlex 的 `cited_by_count` 是 2026-09-02 的动态快照，只用于说明传播范围，不作为研究质量的唯一判断标准。领域贴近度、研究设计和正式出版来源优先于引用量。

## 2. 研究边界复核

本系统属于四条研究线中的“文化—历史叙事线”。它研究的是：

- 文字系统、脚本、书体、字体或明确字标对象，与哪些审美或品牌评价共同出现；
- 这些表达出现在哪个平台、语言、时间窗、查询族和品牌场景中；
- 表达由品牌方、设计机构、设计媒体、设计师/创作者还是普通用户提出；
- 表达是肯定、否定、描述、混合、反例还是不明确；
- 这些有界观察能否转化为其他研究线的可检验假设。

本系统不直接估计：

- 全网流量、真实曝光或推荐算法影响；
- 公众总体偏好或跨平台总体占比；
- 某种文字、书体或字体导致某种审美判断的因果效应；
- 社会叙事的历史起源，除非另有档案和来源链证据。

当前 frozen 方法配置已经规定探索/确认分离、查询族、相关性筛选、双人编码和证据边界。主要问题不是协议缺失，而是 Web 实现没有把这些要求落实为运行时约束。

## 3. 高认可度方法工作清单

### 3.1 社交媒体样本、API 与测量

| 工作 | 影响力旁证 | 可迁移设计 | 对 GLYPH 的决定 |
|---|---:|---|---|
| Tufekci (2014), [Big Questions for Social Media Big Data](https://doi.org/10.1609/icwsm.v8i1.14517) | OpenAlex 719 | 区分可获得数据与目标总体；检查代表性、构念效度和缺失 | API 返回只能称为有界查询样本；必须报告检索入口、排序、时间窗和分母 |
| Ruths & Pfeffer (2014), [Social media for large studies of behavior](https://doi.org/10.1126/science.346.6213.1063) | OpenAlex 657 | 平台人群、平台行为、采集机制和分析推断是不同层次 | 不能把活跃发布者、评论者或搜索返回外推为公众总体 |
| Lomborg & Bechmann (2014), [Using APIs for Data Collection on Social Media](https://doi.org/10.1080/01972243.2014.915276) | OpenAlex 258 | API 是平台构造的选择性接口，不是中性窗口 | 查询、接口版本、字段权限、排序和缺失必须进入运行证据 |
| Olteanu et al. (2019), [Social Data: Biases, Methodological Pitfalls, and Ethical Boundaries](https://doi.org/10.3389/fdata.2019.00013) | OpenAlex 748 | 将偏差分为数据来源、采集、处理、分析和解释环节 | 运行报告应逐层登记偏差，不能只给一个笼统限制声明 |
| Lazer et al. (2021), [Meaningful measures of human society in the twenty-first century](https://doi.org/10.1038/s41586-021-03660-7) | OpenAlex 136 | 数字踪迹需要构念效度、交叉测量和理论对应 | “premium 命中”不是“高级感叙事成立”；必须验证对象、说话者、语境和立场 |

### 3.2 机器辅助、定性解释与人工编码

| 工作 | 影响力旁证 | 可迁移设计 | 对 GLYPH 的决定 |
|---|---:|---|---|
| Grimmer & Stewart (2013), [Text as Data](https://doi.org/10.1093/pan/mps028) | OpenAlex 3286 | 自动文本方法没有普遍最佳方案；每个阶段都需要针对研究任务的人工验证 | 机器方法只生成筛选信号和候选，不能直接写入研究标签 |
| Nelson (2017), [Computational Grounded Theory](https://doi.org/10.1177/0049124117729703) | OpenAlex 696 | 将模式发现、语境精读和模式确认串成可复核流程 | 探索运行发现别名和误命中；人工修订后冻结确认运行；不得事后改写旧查询 |
| Hayes & Krippendorff (2007), [Answers to 20 Questions About Interrater Reliability and Interrater Agreement](https://doi.org/10.1177/1094428106296642) | OpenAlex 3577 | 一致性取决于独立判断、测量层级、缺失处理和适当指标 | 两名编码员必须独立提交后再裁决；审核历史不能冒充独立双编 |
| Peeters & Hagen (2022), [The 4CAT Capture and Analysis Toolkit](https://doi.org/10.5117/CCR2022.2.007.HAGE) | OpenAlex 56 | 数据源、处理器、中间产物和运行证据分层 | 保留现有本机核心，但补齐查询快照、筛选事件和质量闸门 |

### 3.3 YouTube 平台特定工作

| 工作 | 影响力旁证 | 可迁移设计 | 对 GLYPH 的决定 |
|---|---:|---|---|
| Rogers (2018), [Researching YouTube](https://doi.org/10.1177/1354856517737222) | OpenAlex 199 | 应按平台原生对象、排序和关系研究 YouTube，而不是将其视为一般文本仓库 | 视频元数据、频道自述、顶层评论和回复是不同观察层 |
| [Social Media Sellout: The Increasing Role of Product Promotion on YouTube](https://doi.org/10.1177/2056305118786720) (2018) | OpenAlex 214 | YouTube 内容中商业推广和创作者自述具有独立分析意义 | 创作者推广可作为“生产者叙事”单独编码，不能混作普通用户采用 |
| [YouTube Data API search.list](https://developers.google.com/youtube/v3/docs/search/list) | 官方文档，2026-06-01 更新 | `q` 支持 `-` 和 `|`；`relevanceLanguage` 只提高相关语言结果权重，仍会返回其他语言 | 每个冻结 query 单独请求；语言必须后验识别并人工确认 |
| [YouTube Data API commentThreads](https://developers.google.com/youtube/v3/docs/commentThreads) | 官方文档，2026-06-01 更新 | `commentThreads` 中嵌入的回复可能不完整；完整回复需 `comments.list` | 必须记录顶层评论、回复、父关系、排序方式和回复完整性 |

### 3.4 字体、文字形式与文化意义

| 工作 | 影响力旁证 | 可迁移设计 | 对 GLYPH 的决定 |
|---|---:|---|---|
| Leeuwen (2006), [Towards a semiotics of typography](https://doi.org/10.1075/idj.14.2.06lee) | OpenAlex 360 | 字体意义由形式资源、文化惯例和使用语境共同构成 | 不能从文字类别直接推出“高级、极简或传统” |
| Henderson, Giese & Cote (2004), [Impression Management using Typeface Design](https://doi.org/10.1509/jmkg.68.4.60.42736) | OpenAlex 353 | 字体形式维度与品牌印象需要分开测量 | 社会叙事只产生待检验假设，最终机制需要受控实验 |
| Childers & Jass (2002), [All Dressed Up With Something to Say](https://doi.org/10.1207/S15327663JCP1202_03) | OpenAlex 235 | 字体语义一致性会影响品牌感知和记忆 | 对象、评价、品牌场景和证据片段必须同时存在，不能只看评价词 |
| Qiu, Watanabe & Omura (2021), [Emotional Responses to Chinese Characters](https://doi.org/10.5057/ijae.ijae-d-20-00018) | OpenAlex 4 | 分开简体、繁体和日文字体，并比较不同文化背景下的情感反应 | 引用量不高但对象最接近；支持对象层级、文字背景和视觉形式分离 |

## 4. 开源工具清单与取舍

维护日期来自各项目官方仓库默认分支的最近提交时间，仅表示维护活跃度，不表示学术有效性。

### 4.1 采集和可追溯基础设施

| 工具 | 许可与维护快照 | 主要能力 | GLYPH 取舍 |
|---|---|---|---|
| [4CAT](https://github.com/digitalmethodsinitiative/4cat) | MPL-2.0；2026-09-01 | 模块化数据源、处理器、中间数据集、Web 研究界面 | 借鉴运行溯源和处理器边界；不引入完整平台 |
| [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer) | MPL-2.0；2026-09-01 | 在研究者正常浏览期间捕获浏览器收到的公开平台数据 | 未来视觉平台的 `manual_capture` 备选；不属于当前 M3 |
| [Facepager](https://github.com/strohne/Facepager) | MIT；2026-05-17 | API/网页请求、分页、限速、字段抽取、SQLite、CSV 导出 | 可作为未来 `imported_export` 上游；不替换现有 YouTube 适配器 |
| [YouTube Data Tools](https://github.com/bernorieder/YouTube-Data-Tools) | GPL；2024-10-07 | 通过 YouTube Data API v3 抽取视频、评论和网络数据 | 可做一次输出交叉检查；维护较慢，且缺少 GLYPH frozen schema 和审计链 |
| [minet](https://github.com/medialab/minet) | GPL；2026-07-01 | 可恢复批处理、网页抽取、URL 规范化和 YouTube 搜索 | 适合未来批量上游任务；M3 不增加第二套采集运行时 |

### 4.2 人工编码和裁决

| 工具 | 许可与维护快照 | 主要能力 | GLYPH 取舍 |
|---|---|---|---|
| [INCEpTION](https://github.com/inception-project/inception) | Apache-2.0；2026-09-02 | 独立标注、证据片段、多层 schema、裁决、IAA、推荐器、REST API | 与需求最匹配；先借鉴工作流，若团队需要外部多人标注再做导入/导出适配 |
| [Label Studio](https://github.com/HumanSignal/label-studio) | Apache-2.0；2026-09-01 | 文本、图像、视频、音频标注，本机部署和 REST API | 多模态备选；当前文字证据裁决不如 INCEpTION 直接，不在 M3 部署 |
| [doccano](https://github.com/doccano/doccano) | MIT；2026-01-17 | 协作式文本分类、序列标注和 API | 易集成，但对裁决、研究代码本和 IAA 的直接支持较弱 |
| [Taguette](https://github.com/remram44/taguette) | BSD-3-Clause；2026-02-05 | 轻量定性文本高亮、标签和项目导出 | 适合探索性精读，不作为 GLYPH 分析真源 |
| [QualCoder](https://github.com/ccbogel/QualCoder) | LGPLv3；2026-09-02 | 文本、图片、音视频定性编码和 coder comparison | 适合独立质性分析；与现有 JSON schema/API 的自动同步成本较高 |

### 4.3 语言、可靠性和探索性分析

| 工具 | 许可与维护快照 | 主要能力 | GLYPH 取舍 |
|---|---|---|---|
| [Fast Krippendorff](https://github.com/pln-fing-udelar/fast-krippendorff) | PyPI `krippendorff`；2026-08-02 | 基于 NumPy 计算 Krippendorff's alpha | 可作为小型可选依赖；多标签术语需逐代码二元化，不能用平均 Jaccard 冒充 alpha |
| [Lingua](https://github.com/pemistahl/lingua-py) | Apache-2.0；2026-03-09 | 本机短文本语言检测，可限制候选语言集合 | 先用中英日韩 fixture 基准；只生成语言候选和置信信号 |
| [spaCy](https://github.com/explosion/spaCy) | MIT；2026-08-24 | 多语种分词、规则匹配、实体和训练管线 | 当前冻结词表匹配不需要这一重量级依赖；以后出现句法需求再评估 |
| [BERTopic](https://github.com/MaartenGr/BERTopic) | MIT；2026-08-27 | embedding、聚类、c-TF-IDF 和动态主题 | 仅适合足量探索样本；不得用于小样本主结论或替代代码本 |

## 5. 现有工程资产评估

### 5.1 可以保留

- 官方 YouTube API 客户端、代理和本地凭据边界；
- 分页、重试、checkpoint、停止和恢复；
- raw evidence、规范记录、稳定 ID 和 SHA-256；
- SQLite WAL、运行审计、失败记录和备份恢复；
- 视频、顶层评论和回复的父关系；
- schema 校验、导出和分析隔离；
- 只有 `human_verified` 进入主分析的原则；
- frozen `social_observation` 和 `social_run_manifest` 的总体契约。

### 5.2 必须纠正

#### 5.2.1 Query 与 scope 被压成一个可变对象

当前 `create_scope()` 只创建一个 query，`aesthetic_terms` 和 `brand_context` 为空；scope 更新会原地覆盖 query。证据页和导出又联查当前 query，而不是运行时的不可变快照。因此旧 run 可能被后来的 scope 修改重新解释。

纠正原则：

- 一个 scope 可以关联多个不可变 query；
- 每个 query 有自己的查询族、阶段、语言、精确平台查询和版本哈希；
- query 修改必须创建新 ID，旧记录永不覆盖；
- run manifest 已支持多个 `query_ids`，无需推倒 frozen manifest schema。

#### 5.2.2 检索假设被写成条目事实

当前 YouTube 规范化器把 scope 的 `object_type/object_label` 无条件复制到视频和评论。这样，“以某对象为目标检索”被错误转换成“该条内容已经确认讨论此对象”。

纠正原则：

- API 返回先规范化为 `unannotated`，对象字段为空；
- scope 目标只保留在 query/run 上；
- 规则或模型输出进入独立筛选事件，不写入研究事实；
- 只有人工确认或裁决后的记录才获得对象标签。

#### 5.2.3 当前总额度会造成首个视频簇支配

当前 `max_items` 同时计算视频、顶层评论和回复。搜索排名第一的视频可能用评论填满整个额度，后续视频无法进入样本。

纠正原则：

- 分别预登记 `max_videos_per_query`；
- 分别预登记 `max_comment_threads_per_video`；
- 分别预登记 `max_replies_per_thread`；
- 视频通过相关性筛选后才请求评论；
- 报告搜索命中、视频详情、合格视频、评论线程、回复、候选、排除和确认记录的逐层分母。

#### 5.2.4 单人审核历史不等于独立双编

当前服务固定使用 `annotator_local01`，审核直接更新 observation。第二位编码员无法在不看第一位结果的情况下提交独立判断，也无法保留两份平行编码。

纠正原则：

- per-coder annotation 与最终 observation 分离；
- 每位编码员保存独立版本、代码本版本和提交时间；
- 编码员提交前看不到他人结果；
- adjudication 单独保存，不覆盖原始编码；
- 只有裁决 gold 投影为 frozen `human_verified` observation。

#### 5.2.5 Web 运行时没有强制 object map 和 codebook

当前 Web 服务主要执行 JSON Schema 校验。对象标签、审美术语和品类并未在审核时强制来自版本化 registry，因此任意词可能进入 `human_verified`，并在导出校验前污染在线分析。

纠正原则：

- 运行时加载并哈希 object map、codebook 和 query registry；
- 审核 UI 使用受控选择，不允许自由字符串直接进入 gold；
- 新术语只能进入下一探索版本；
- 确认运行中途不能修改代码本。

#### 5.2.6 来源角色不能按频道名自动推断

频道标题或简介中的 `official`、`design`、`studio` 等字符串只能作为人工核验提示，不能自动生成 `brand`、`design_media` 或 `ordinary_user`。

可自动记录的只是平台关系事实，例如评论作者是否与视频频道 ID 相同。由于直接作者标识不进入 observation，这一比较结果应以去标识布尔信号或筛选事件保存。最终 `author_role` 仍需有来源证据并人工确认。

#### 5.2.7 分析缺少研究质量闸门

当前在线分析只过滤 `human_verified`，但没有检查：

- 运行是探索还是确认；
- query/codebook/object map 是否冻结；
- 记录是否通过相关性筛选和裁决；
- 双编比例与一致性是否达标；
- 对象—术语分母是否足够；
- 运行是否允许进入 research release。

这些条件必须在分析前机械检查，而不是仅写在报告中。

#### 5.2.8 YouTube 配额模型已发生变化

[YouTube 官方配额页](https://developers.google.com/youtube/v3/determine_quota_cost) 标注 2026-06-01 更新：

- `search.list` 使用独立的每日 100 次调用桶；
- `search.list` 每次调用成本为 1；
- `videos.insert` 有另一个独立调用桶；
- 其他 API 端点默认共享每日 10,000 单位；
- 日界仍为 Pacific Time；
- 失败请求也至少消耗 1。

当前代码仍按旧口径将 `search.list` 记为 100，并与其他方法混入一个本地预算桶。旧真实运行的本地 204/300 记录必须保留原样并标注旧成本模型，不能回写。新运行必须保存 `quota_policy_version`，并分别守卫搜索调用桶与共享单位桶。

## 6. 建议的 M3 改进架构

不修改 frozen observation/manifest schema；只扩展本机 SQLite、服务层和 UI 工作流。

### 6.1 不可变查询层

每个 query 至少保存：

```text
query_id
scope_id
query_family                # object_aesthetic / object_context / aesthetic_context
research_phase              # exploratory / confirmatory
lexicon_version
object_map_sha256
codebook_sha256
language_bcp47
region_hint
exact_platform_query
sort_order
video_window
comment_window
max_videos_per_query
max_comment_threads_per_video
max_replies_per_thread
inclusion_rule
exclusion_rule
query_config_sha256
created_at
supersedes_query_id
```

查询记录只追加，不更新。run 通过冻结 query ID 引用精确配置。

### 6.2 独立筛选层

建议新增内部表 `screening_events`，保存：

```text
observation_id
screening_rule_version
decision                    # include / exclude / uncertain
object_alias_hits
aesthetic_term_hits
brand_context_hits
language_candidate
language_confidence
parent_context_used
tool_name
tool_version
created_at
```

筛选信号不属于最终分析标签，不写入 frozen observation 的 `object_label` 或 `aesthetic_terms`。

### 6.3 独立编码与裁决层

建议新增：

- `annotations`：每位编码员对每条 observation 的独立结果；
- `adjudications`：分歧裁决与 gold 结果；
- `annotation_assignments`：盲审分配和完成状态；
- `agreement_reports`：按平台、语言和字段保存一致性结果；
- `run_quality_reports`：保存一轮是否允许进入分析和 release。

对象、立场和相关性是 nominal 变量；审美术语是多标签变量，应按每个冻结代码转为二元判断并分别报告可靠性。证据片段的一致性需要单独定义重叠或单元化规则，不能与 nominal alpha 混为一个数字。

### 6.4 平台原生抽样层

YouTube 至少区分：

1. 视频标题/描述中的发布者叙事；
2. 顶层评论；
3. 回复；
4. 评论者与视频频道是否相同这一平台关系；
5. 视频可见互动和评论可见互动。

评论可以通过已人工确认的视频对象获得父语境，但编码员必须确认该评论确实指向该对象。仅有“great”“love it”或技术问答，不因父视频属于某 scope 就自动获得对象或评价标签。

### 6.5 发布和分析闸门

一条记录进入主分析前，应同时满足：

```text
run.research_phase == confirmatory
query is immutable and hash-verified
codebook/object map hashes match the run
screening decision == include
adjudication status == gold
observation.annotation_status == human_verified
language is confirmed
run quality gate == passed
release decision permits analysis
```

分析输出按平台、语言、query family、内容层和 author role 分层。视频线程内记录并非独立样本；至少报告每视频记录数和去除最大视频簇后的敏感性结果。

## 7. 分期实施建议

### 阶段 A：先恢复研究契约，不发真实请求

1. 将当前 12 条真实 YouTube 数据标为 `engineering-only` 审计样本；不删除、不重写历史配额、不进入分析或 release。
2. 将 query 改为不可变的一对多 registry，并修复旧 evidence/export 联查当前 query 的问题。
3. 删除 observation 对 scope 对象标签的自动继承。
4. 增加 object map/codebook 的运行时校验和哈希。
5. 为新的筛选、独立编码、裁决和质量报告表编写迁移与单元测试。

### 阶段 B：实现分层抽样和候选筛选

1. 每个 query ID 单独调用 `search.list`，不再把一组关键词直接拼成无结构宽搜。
2. 拆分视频、评论线程和回复配额。
3. 视频未通过筛选前不请求其评论。
4. 将 `relevanceLanguage` 明确标为排序提示，不作为语言过滤结果。
5. 可在 fixture 基准通过后接入 Lingua 作为候选信号。

### 阶段 C：实现双编、裁决和一致性

1. 扩展现有审核 UI，而不是立即部署第二套平台。
2. 两名编码员独立提交对象、术语、品类、立场、机制、来源角色和证据片段。
3. 增加裁决视图；原始两份编码只读保留。
4. 使用经过测试的 Krippendorff alpha 实现，按字段和代码报告。
5. 未达到协议门槛时阻止主分析和 release。

如果团队已经有多名编码员且需要立即并行工作，可以另做 INCEpTION 导出/导入适配；GLYPH SQLite 和 frozen schema 仍是最终研究真源。

### 阶段 D：离线验收后申请真实 pilot

离线 fixture 至少覆盖：

- 明确的“文字对象—评价词—证据”正例；
- 含 `premium` 但只是创作者推广的生产者叙事；
- 泛称赞；
- 技术问答；
- 明确反例或否定；
- 评论借用已确认父视频对象的情况；
- 顶层评论和回复；
- 中英日韩及混合语言；
- 未登记术语、对象和品类；
- scope/query 修订后旧 run 仍返回原始查询；
- 两位编码员分歧、裁决和 IAA 不达标阻断。

离线验收通过并由研究负责人确认 query 后，才单独批准一次小型真实 YouTube pilot。合法的零结果也是研究结果；不得为了闭环制造 `human_verified`。

## 8. M3 修订后的完成定义

M3 只有同时满足以下条件才完成：

1. YouTube API 工程链继续通过离线与真实安全验收；
2. 每个真实 run 引用不可变 query 和版本化 codebook/object map；
3. 搜索命中不会自动获得对象事实；
4. 视频、顶层评论和回复有独立抽样分母；
5. 来源角色和语言不由薄弱启发式直接写成 gold；
6. 至少一轮小型真实 pilot 完成双人独立编码和裁决，或诚实报告零合格记录；
7. 一致性、样本量和 release 闸门机械生效；
8. 当前 12 条工程样本与修订后的研究样本明确隔离；
9. 配额策略与 2026-06-01 官方口径一致并带版本；
10. 提交可复跑的 M3 最终报告后停止，等待 M4 明确批准。

## 9. 最终取舍

建议保留现有采集、raw evidence、哈希、SQLite、恢复、导出和备份能力；在 M3 内重建研究控制层，不更换采集框架，不引入新平台，不用大型主题模型代替代码本。

优先采用的是：

- 4CAT 的透明、可追溯处理边界；
- INCEpTION 的独立编码、裁决和 gold 工作流；
- Krippendorff alpha 的字段级可靠性检查；
- Lingua 经基准验证后的语言候选信号。

暂不采用的是：

- 用 YouTube Data Tools、Facepager 或 minet 替换现有适配器；
- 在 M3 部署完整 4CAT、Label Studio 或 INCEpTION；
- 将 BERTopic、embedding 或 LLM 输出作为最终叙事标签；
- 按频道名称自动推断来源角色；
- 将 `logo_design` 加入对象表来挽救宽泛查询；
- 在 M3 完成前接入 Mastodon 或其他平台。

当前结论：M3 工程接入已证明部分有效，但研究有效性尚未验收。在本记录的离线改造范围获得明确批准之前，不继续实现、审核或采集。
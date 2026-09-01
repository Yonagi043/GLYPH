# GLYPH 社会叙事监测：先例综述与可复现系统设计

版本：`0.1.0`  
日期：2026-09-01  
状态：方法设计依据；本文件不报告新的平台采集结果

## 摘要

本综述回答两个问题：别人已经怎样收集和分析公共网络中的传播与叙事，这些方法哪些适合 GLYPH，哪些必须明确拒绝。检索范围覆盖社会媒体采集与审计、跨平台传播、人工文本编码，以及文字/字体的跨文化感知研究；论文和工具的 DOI、原始页面或代码仓库列在文末，链接核验日期为 2026-09-01（Asia/Shanghai）。

结论很集中：没有一套现成软件能够同时解决平台访问、跨语言文字对象、文化叙事证据和字体实验的要求。可迁移的共同经验是：

1. 把采集、规范化、人工编码、统计汇总和发布拆开，并为每一步保存版本、时间和输入哈希（4CAT、Hoaxy、COVID-19 TweetIDs）。
2. 把 API 或浏览器捕获看作“在明确检索框架内观察到的样本”，而不是随机公众样本、真实曝光量或全网流量（Tufekci；Morstatter 等；Lomborg 与 Bechmann）。
3. 对同一检索式重复采集、比较不同入口、保留失败记录和缺失字段；否则无法知道结果是叙事差异还是采集差异（Cheliotis 等；Pfeffer 等）。
4. 机器方法只负责候选发现和去重，关键对象、评价词、立场和证据片段由人核验，并报告编码一致性（Hoaxy/Anatomy；Hayes 与 Krippendorff）。
5. 字体研究必须控制内容、字号、字高、粗细、版式、可读性和熟悉度；社会媒体中的共现只能产生假设，不能替代真实受试者实验（Qiu 等；Gabriel 与 Ryoke；FontLex；van Rompay 与 Pruyn）。

据此，GLYPH 采用一条小而可审计的链：

```text
固定问题、词表和时间窗
→ 合法 API / 公开网页 / 正常浏览捕获
→ 本地原始导出与运行清单
→ 规范化、去重、失败登记
→ 人工编码和证据复核
→ 双向共现、Lift、来源/时间描述
→ 给跨文化感知、纯视觉和汉字书体实验提供待检验假设
```

第一版监测的是“公共叙事如何出现和被采用的可见线索”，不是购买机器人、估计真实曝光或宣称某种字体天然高级。仓库现有的离线核心从导出文件开始，不在公开代码中保存密钥、Cookie 或绕过反爬的采集器。

## 1. 研究问题、观察单位与推断边界

### 1.1 GLYPH 要回答的问题

社会叙事线（四条研究线中的文化—历史叙事线）只回答以下可观察问题：

- 哪些文字系统、书体、字体或仓库中的 `stimulus_id`，在明确的平台、语言、时间窗和品类中与哪些评价词共同出现？
- 评价由谁提出（品牌方、设计机构、设计媒体、设计师/创作者、普通用户），采用肯定、否定、反例还是描述性语气？
- 同一叙事是否在不同来源或平台重复出现，是否有明确的引用、回复、转发或外链关系？
- 可见互动的分布怎样，是否由少数来源或少数热门内容主导？
- 这些观察能否转化为跨文化问卷、纯视觉特征模型和汉字书体实验中的可检验假设？

“历史起源”“算法造成的曝光”“公众总体偏好”和“字体导致高级感”不是本线的直接估计目标。前两者需要档案/平台机制证据，后两者需要真实受试者和受控实验。

### 1.2 记录和统计的最小单位

- **平台条目（item）**：一个公开帖子、视频、评论、网页项目页或人工观察到的页面条目；同一条目在同一平台只保留一个规范记录。
- **观察记录（observation）**：条目在某次 `collection_run_id` 中被看到的事实。`observation_id` 由平台、运行和平台条目 ID 一起生成；相同条目在不同运行中可以有多个观察，但不得覆盖历史互动数。
- **来源（source）**：发布条目的页面或出版物，使用独立的 `source_id` 记录 URL、发布时间、访问日期和许可状态。
- **对象（object）**：文字系统、脚本、书体、字体、字标或已知的 GLYPH 刺激；不能因为一条内容“看起来像”某种书体就擅自填入 `stimulus_id`。
- **叙事词（term）**：经版本化词表定义的审美/品牌评价，如“高级、极简、国际化、传统、现代、易读、可信、陌生”；同义词、语言和词形必须保留映射。

默认的分析单位是一条通过筛选且人工核验的记录，一条记录一票。互动数只做单独的描述性权重，不与记录数混合。

### 1.3 两个方向的关联量

设 \(S\) 为文字/书体/字体对象，\(A\) 为叙事词，\(n(S,A)\) 为同一条记录同时被标为 \(S\) 和 \(A\) 的数量，\(n(S)\) 和 \(n(A)\) 分别为对象和词的记录数，\(N\) 为总记录数：

\[
P(A\mid S)=\frac{n(S,A)}{n(S)},\qquad
P(S\mid A)=\frac{n(S,A)}{n(A)}
\]

\[
Lift(S,A)=\frac{P(A\mid S)}{P(A)}
       =\frac{n(S,A)N}{n(S)n(A)}
\]

第一项回答“提到某对象时，评价词出现多不多”；第二项回答“谈某评价时，拿什么对象作例子”。`Lift > 1` 只表示在该样本的检索框架中共同出现多于样本基线，不能解释为文字的固有属性。每个比例必须同时报告分母、平台、语言、时间窗、检索版本和记录数。

## 2. 证据选择方法

这不是声称穷尽全部文献的系统综述，而是面向实现的证据扫描。纳入条件为至少满足一项：

- 提供了可复用的采集、版本化、去重、跨平台匹配或人工编码方法；
- 对社交媒体样本的代表性、可靠性、伦理或因果解释提出了可操作的检验；
- 直接测量了字体、文字系统、可读性、文化熟悉度或品牌印象，可帮助 GLYPH 将叙事观察接到受控实验；
- 有可访问的 DOI、正式出版页面、开放论文或公开代码仓库。

文末同时列出“采用的经验”和“拒绝的做法”。外部软件只作为上游采集或人工标注工具候选，不将其代码、账号凭证或受限数据复制进 GLYPH；许可证和平台条款须按使用时的官方版本重新核对。

## 3. 别人已经做过什么

### 3.1 采集、追踪和人工编码工具

| 先例 | 已经解决的问题 | 对 GLYPH 的直接启发 | 我们不照搬的部分 |
|---|---|---|---|
| 4CAT（Peeters & Hagen, 2022；[M1]） | 将采集、处理器和分析模块化，并保留中间结果，强调透明、可追踪和 ethics by design | 每次运行保存查询、时间窗、平台、处理器版本、输入/输出和日志；采集、规范化、标注、汇总分目录 | 不把完整平台插件栈作为 GLYPH 的必需依赖；公开仓库只保留小型离线核心 |
| Zeeschuimer（[T1]） | 记录研究者正常浏览时浏览器收到的公开数据，适合缺少稳定 API 的视觉平台 | 小红书、抖音、Instagram 等采用固定浏览会话和人工观察配额，标记 `manual_capture`，记录会话起止和入口 | 不绕过登录、验证码、反爬或访问限制；不把浏览会话当平台总体样本 |
| Facepager（[T2]） | 用 SQLite 管理 API/网页请求、分页、限速、批量导出和字段抽取 | 可作为 Reddit、YouTube 或公开网页的上游采集器；导出后统一进入 GLYPH schema | 不把 Facepager 数据库格式当长期研究格式；不依赖其预设的隐含版本 |
| Hoaxy（Shao 等, 2018；[M2]）与 Anatomy（Shao 等, 2018；[M3]） | 注册来源、规范化 URL、追踪转发网络，并以人工复核确认关键样本 | 维护来源注册表；去掉跟踪参数、合并同一内容的 URL；明确边和立场；保存证据片段和人工状态 | 不把链接自动解释为赞同；不把固定来源列表描述成全网 |
| Web Centipede（Zannettou 等, 2017；[M4]） | 在 Twitter、Reddit、4chan 之间匹配相同 URL，比较出现时间和平台间滞后 | 对相同规范内容计算首次出现时间、滞后小时数和平台内归一化频率 | 图片、截图和无 URL 文本可能漏检；第一版不把时间先后写成因果起源 |
| COVID-19 TweetIDs（Chen、Lerman & Ferrara, 2020；[M5]） | 按日期/小时发布 Tweet ID，持续扩展查询词并记录采集缺口 | 查询词、采集运行和发布版本都冻结；公开时优先发布允许再水合的 ID/元数据，不发布受限正文 | 不复制其特定疾病词表；英文词表不能直接代表中文、日文或韩文叙事 |
| Taguette / Label Studio（[T3]、[T4]） | 提供多人对文本片段、图片或视频进行人工标注的界面和导出 | 机器只生成候选；人工确认 `object_label`、`aesthetic_terms`、`stance`、`evidence_span`，保留编码人和时间 | 不让通用 LLM 单独决定标签；不把标注平台当数据发布平台 |

这些工具的共同点不是“自动化越多越好”，而是中间结果可见、失败可追溯、人工可以回到原文。GLYPH 的公开代码从已获准的导出文件开始，因此平台价格、登录状态和页面改版不会改变分析契约。

### 3.2 样本偏差、可靠性和伦理先例

| 研究 | 关键发现（限定在原研究样本） | GLYPH 的控制措施 |
|---|---|---|
| Tufekci（2014；[M6]） | 单一平台、按 hashtag 取样、缺少分母、把转发/点赞当影响，都会造成代表性和有效性问题；截图、暗示性提及等也可能漏检 | 不只依赖 hashtag；先宽搜再冻结词表；报告可见互动分母；把支持、反对、嘲讽、讨论分开；声明检索范围 |
| Morstatter 等（2013；[M7]） | 将旧 Twitter Streaming API 与 Firehose 比较时，研究期平均覆盖约 43.5%，且随日期和总体量变化；覆盖差异会改变主题和网络指标 | 不称 API 返回为随机样本；记录 API 版本、返回上限和缺失时段；重复采集并做来源比较。43.5% 仅是该历史研究期的结果，不外推到今天的 X API |
| Pfeffer、Mayer & Morstatter（2018；[M8]） | 实验显示旧 Sample API 的抽样机制可被高频/时间同步内容扭曲，技术架构和机器人会改变样本组成 | 只做被动观察；不创建机器人、不干预平台；检查异常高频账号、重复文本和时间集中，保存异常报告 |
| Cheliotis、Lu & Yi（2015；[M9]） | 用重复运行、多入口匹配、编辑距离、最长公共子序列和信息熵评估采集可靠性；案例中约 20% 的唯一记录只出现在某一采集结果 | 同一查询至少重复一次；报告 ID/URL 重合率、Jaccard、重复率、字段完整率和失败原因；不静默删除缺失记录 |
| Lomborg & Bechmann（2014；[M10]） | API 是平台提供的选择性接口；活跃发帖者被过度代表，行为记录不能直接说明用户意义，需与观察、访谈或问卷结合 | D 线只生成叙事假设；C 线真人问卷检验感知；A 线提供视觉形式变量；三者不相互替代 |
| Chen、Duan & Yang（2022，在线版 2021；[M11]） | 工具、成本、技能和数据完整度要按研究问题选择；趋势内容与完整传播网络需要不同数据；供应商的“代表性”不能未经检查接受 | 先低成本试运行，再决定是否购买 X 的历史数据；索要样本导出检查字段；结果按平台和来源分层，不比较供应商宣传数字 |
| Goodspeed（2013；[M12]） | 数字踪迹存在“内容贫乏”，只能看到公开表达，难以知道动机和未表达的态度 | 叙事证据只说明“出现了什么说法”；心理意义和因果由受控实验、访谈或问卷承担 |
| Fiesler & Proferes（2018；[M13]）与 Zimmer（2010；[M14]） | “公开可见”不自动等于研究者可以任意再传播；用户对研究使用和语境完整性有不同预期 | 记录条款核验日期；不发布用户名、显示名、邮箱或无许可正文/图片；保留删除和撤回处理；发布前做人工隐私与版权审查 |
| Hayes & Krippendorff（2007；[M15]）与 Artstein & Poesio（2008；[M16]） | Krippendorff’s alpha 等一致性指标必须结合测量层级、缺失值和编码设计解释 | 至少 20% 记录双人独立编码；分别报告对象、叙事词、立场的一致性；分歧由第三人裁决并留痕 |

这些研究没有给出一个可以“修正成全网流量”的魔法系数。它们给出的是更有价值的工程要求：知道自己看到了什么、没有看到什么，以及不同采集方式会怎样改变结果。

### 3.3 与文字和字体直接相关的受控研究

| 研究 | 设计和结果中可迁移的部分 | 对 GLYPH 的约束 |
|---|---|---|
| Qiu、Watanabe & Omura（2021；[F1]） | 20 种简体、20 种繁体和 20 种日文字体；使用同一段内容、固定行距和 1–5 量表；大陆与台湾受试者对 Heiti、Songti、Kaiti 的“古典/当代”感受并不总一致 | 文字背景、内容、字号、画布和呈现方式必须分层且固定；跨文化差异不能写成字体的固定属性 |
| Gabriel & Ryoke（2020；[F2]） | 每种语言 10 种字体，以正交设计平衡类别、粗细和字高；18 对 Kansei 形容词、7 点语义差异量表、168 名受试者 | 不把文字系统与字体类别混成一个变量；把可读性和情感印象分开；先检查类别/粗细/字高的平衡 |
| FontLex（Kulahcioglu & de Melo, 2018；[F3]） | 用 200 种字体和 6,721 个词建立字体—情感关联，再用每项 30 名 Mechanical Turk 受试者、反平衡和注意力题验证 25 个词 | 叙事词表先从真实语料提出，再由人验证；不能把英语字体词典直接移植到中文、日文或韩文 |
| van Rompay & Pruyn（2011；[F4]） | 在受控瓶装水实验中操纵产品形状与字体是否协调，测量可信度、美感、价值和价格预期 | 社会媒体中的“高级/可信”只能是待检验机制；必须在控制品牌、版式和文字内容的实验中检验 |
| Henderson、Giese & Cote（2004；[F5]）及 Childers & Jass（2002；[F6]） | 字体的自然性、和谐、繁复程度及语义联想会影响品牌印象和记忆 | 叙事词不能只设“好看”；至少拆分高级、现代、传统、可信、易读、陌生等结果，并保留机制解释 |

字体研究的共同教训是：文字身份、视觉形式、可读性/熟悉度和品牌语境是可分离但相互作用的因素。社会叙事监测只负责发现“哪些意义被说出来”，不能替代对这些因素的实验分解。

### 3.4 观察基础设施和平台变化的补充先例

Willaert 等人的社会媒体 observatory 研究和 Wiedemann 等人的 DIY
observatory 研究说明，持续监测首先是一个可维护的数据基础设施问题；Stieglitz
等人把主题发现、采集和数据准备拆成不同的风险环节；Bruns 对 “APIcalypse” 的
讨论提醒我们平台权限和接口会改变研究可重复性；Ohme 等人则把 API、数据捐赠和
屏幕追踪视为不同的数字踪迹来源。它们共同支持本仓库的选择：把上游采集器与离线
分析契约分开，记录接口版本和缺失，不把供应商或平台的覆盖承诺当作总体流量。

## 4. 从先例整合出的 GLYPH 系统

### 4.1 系统原则

1. **观察范围先于算法**：每次运行先登记平台、来源列表、语言、查询版本、时间窗、排序方式、页数上限和最大条数；没有清单的结果不进入主分析。
2. **离线核心、在线适配器**：PRAW、YouTube API 客户端、X API、Facepager 或 Zeeschuimer 只负责取得获准导出；GLYPH 从导出文件开始规范化和统计。
3. **证据和解释分层**：原始响应/截图留在受控的本地 `data/raw/social/`；公开处理结果只含必要元数据、哈希、允许公开的 ID 或派生统计；叙事标签必须有精确证据片段和人工状态。
4. **缺失是结果的一部分**：权限错误、删除、失效链接、解析错误、没有文本或无法判断对象的行都写入失败/排除记录，不能静默丢弃。
5. **相关不等于因果**：共现、时间先后和可见互动是描述性线索；“谁影响了谁”“谁看到了”“字体导致了什么”必须用更强的设计回答。
6. **与四条线共享 ID，不共享结论**：社会观察可选填 `stimulus_id`/`font_id`，只有来源明确指向该刺激时才填写；视觉特征和受试者评分仍从各自 schema 产生。

### 4.2 数据链和仓库映射

```text
研究问题 + query/codebook 版本
        ↓
获准 API / 公开网页 / 正常浏览捕获
        ↓
data/raw/social/<platform>/<run_id>/  （本地原始导出，不提交）
        ↓
tools/normalize_social_records.py
        ↓
schema/social_observation.schema.json 的规范 JSONL
        ↓
人工编码：对象、叙事词、品类、立场、机制、证据片段
        ↓
tools/summarize_narratives.py
        ↓
双向概率、Lift、来源/时间/互动描述和审计报告
        ↓
给研究线 1、3、4 的假设登记表
```

现有实现的职责边界如下：

| 位置 | 责任 | 不应放入的内容 |
|---|---|---|
| `schema/social_observation.schema.json` | 采集层统一字段、状态、治理和规范化哈希 | 平台密钥、未经许可的原文、临时分析列 |
| `schema/cultural_narrative.schema.json` | 人工确认后的单条叙事证据投影 | 未核验的机器猜测 |
| `tools/social_io.py` | 读取、规范 JSON、哈希和 schema 校验；无网络请求 | 登录、爬虫、平台特定凭证 |
| `tools/normalize_social_records.py` | JSON/JSONL/CSV 导出 → 规范记录；记录失败 | 自动绕过限制、自动补写缺失事实 |
| `tools/summarize_narratives.py` | 记录计数和可见互动的双向矩阵、Lift、摘要 | 因果模型、公众总体估计、隐式曝光估计 |
| `data/raw/social/` | 受控本地原始导出 | Git 提交、公开链接、凭证 |
| `data/processed/social_narrative_v0/` | 可复跑的规范记录、失败表和矩阵 | 未经许可的完整正文/图片 |
| `data/releases/` | 经过许可、去标识和人工审查的派生发布物 | 用户名、Cookie、私盐、版权不明素材 |

### 4.3 来源和采集策略

第一轮采用“来源互补”而不是“平台越多越好”：

| 来源类 | 第一轮用途 | 主要限制 | 记录方式 |
|---|---|---|---|
| Reddit、YouTube 官方 API | 结构化讨论、视频标题/描述/可见互动和评论 | 配额、字段权限、活跃用户偏差；播放量不是曝光量 | `source_kind=official_api`；保存 API 版本、查询、配额/响应时间 |
| X 官方 API（有合法权限时） | 补充公开短文本、回复/引用和近期时间序列 | 付费/权限、返回上限、版本变化；不能自动代表总体 | 单独运行和版本；不把历史价格写死在代码或结论中 |
| 奖项官网、品牌官网、设计媒体和 RSS | 获奖项目说明、设计师叙事和高出处性案例 | 编辑选择偏差、版权和批量访问限制 | 维护固定来源注册表，记录访问日期和许可状态 |
| 小红书、抖音、Instagram 等视觉平台 | 在稳定 API 不可得时做有限人工观察 | 推荐排序、登录状态和页面字段不可见；样本仅是观察会话 | `source_kind=manual_capture`；记录会话、入口、滚动次数和配额 |
| Google Trends/百度指数 | 辅助显示检索关注度的时间变化 | 指数是平台定义的相对量，不是帖子、曝光或审美偏好 | 独立数据类型；不并入帖子分母或 Lift |

首轮不购买“聊天机器人账号矩阵”作为证据。自动账号会改变被观察环境，且看到的推荐流不能代表公共叙事；若以后研究推荐系统，必须另立经过伦理审查的被动、可重复协议。

### 4.4 查询、抽样和版本化

采用探索与确认分离的两阶段：

1. **探索运行**：用较宽的对象别名、语言变体和评价词收集候选；记录每个查询带来的误命中和新词。
2. **确认运行**：人工审核后冻结 `query_lexicon_version`、对象映射、语言和品类词表；只用冻结版本生成主结果。新词进入下一版本，不能事后改写旧结果。

每条运行清单至少包含：

```text
collection_run_id
platform / source_list
query_lexicon_version
query_id / query_text / sort_mode
language_bcp47 / region_hint（仅作为采集分层，不推断个人身份）
window_start / window_end
page_limit / max_items_per_stratum
collector_version / api_version
started_at / ended_at
```

建议首轮的可执行配额：每个平台 × 语言 × 查询族最多 100 条；同一查询在同一时间窗至少重复一次；先做 `zh-CN` 和 `en`，通过质量闸门后再增加 `ja`、`ko` 或视觉平台。不同平台的排序方式、条数和可见互动不直接横比。

### 4.5 规范化、去重和失败处理

- 以平台原始 ID 为首要键；没有稳定 ID 时使用规范 URL，并将原始定位符哈希化保存。
- 规范化器只去除明确的 UTM/常见追踪参数和 URL fragment，并统一主机名及查询参数顺序；离线核心不跟随重定向、不解析短链，也不把不同路径猜成同一内容。需要重定向或内容匹配时，必须由上游适配器记录并人工复核。
- 统一时间为 UTC ISO-8601；保留原始时区在运行清单中。
- 语言识别是候选字段，关键样本由人工确认；`region_hint` 不是个人国籍、民族或所在地。
- 作者默认不采集；若为重复检测必须使用带项目私盐的不可逆 `author_ref`，私盐只在本地保存。
- 每一行失败写入 `observations.jsonl.failures.csv`，至少包含行号、错误码、行哈希和原因；失败不进入分母，但不被删除。
- 原文、截图和媒体只在有权保存且不需要公开时留在受控本地目录；公开 release 仅使用经许可的内容或摘要/哈希。

### 4.6 人工编码和叙事证据

统一代码本至少包含：

- **对象**：拉丁字母/英文、汉字、日文/假名、韩文/韩字，以及 GLYPH 已冻结的汉字书体或字体名；对象层级（文字系统、脚本、书体、字体、刺激）不可混用。
- **评价词**：高级/奢侈、极简、国际化、传统、现代、可信、易读、陌生等；保留原文词、规范词和语言。
- **品牌场景**：茶、酒、香、珠宝、科技、时尚、餐饮/酒店等；一个条目可以多选，但必须有依据。
- **立场**：肯定、否定、混合、描述、反例、不清楚；赞同链接不由链接本身推断。
- **机制主张**：如几何化、线条均匀、印章感、陌生感、历史指涉、易读性、品牌惯例；机制是内容中明确说出的主张，不是编码者的自由联想。
- **证据片段**：能让另一位审查员回到原文核查的最短精确片段；机器摘要不能替代它。

机器分类只生成 `candidate`。主结果默认只使用 `human_verified`。至少 20%（不足 30 条时全量或至少 30 条）由两人独立编码；预先规定：对象、叙事词和立场的 Krippendorff’s alpha 均达到 0.80 才进入主结果；0.67–0.80 仅作探索并返工代码本；低于 0.67 停止汇总并重新培训/编码。分歧由第三人裁决，保留原始两份编码和裁决时间。

### 4.7 汇总指标和传播线索

当前离线脚本已经实现以下描述量（见 `tools/summarize_narratives.py`）：

- 每个平台、语言、时间桶和来源角色的记录数及首末发布时间（`role_timeline.csv`、`time_series.csv`）；
- \(P(A\mid S)\)、\(P(S\mid A)\) 和 Lift，同时列出 \(n(S,A)\) 与分母；
- 可见互动的非空数、总和、最大值、中位数、四分位数和 90/99 分位数（`summary.json`）；播放、点赞、评论、转发、引用、Reddit score 不相加解释为曝光；
- 角色索引、引用边和证据索引（`role_timeline.csv`、`reference_edges.csv`、`evidence_index.csv`）；引用边只记录可见关系，不推断赞同或因果；
- 每个对象—评价词单元的探索性标记：对象或评价词分母小于 20 时 `exploratory=true`，不得据此排名。

来源集中度（前 10% 来源贡献比例或 HHI）、跨平台规范内容匹配、首次出现滞后和
重复采集的 Jaccard 属于运行审计层，第一版核心脚本不自动估计；它们必须由上游
运行报告按平台和查询分别计算，不能从下列矩阵中臆造。

记录数是主结果，互动加权是单独的 `weight_mode=engagement` 描述视图。对象或词的分母小于 20 时只列为探索性观察，不进行排名或跨组结论；任何显著性、置信区间或 Hawkes 等更强模型必须在后续版本预先规定，不能由首轮结果临时选择。

## 5. 第一轮试运行：可以直接照做的协议

下面是把上述经验收紧成一轮可审查的最小系统，不代表已经完成采集。

### 5.1 运行范围

- 运行名：`social_run_<YYYYMMDD>_pilot01`。
- 稳定来源：Reddit、YouTube、公开奖项/品牌/设计媒体页面；X 仅在已有合法 API 权限时加入。
- 语言：先 `zh-CN`、`en`；只有两轮质量检查通过后才扩展 `ja`、`ko`。
- 每个平台 × 语言 × 查询族上限 100 条；查询族至少覆盖“对象 + 评价词”“对象 + 品类”“评价词 + 品类”三类，避免只按对象选择样本。
- 每个查询在同一时间窗重复运行一次；保存返回空页、权限错误、删除和限额错误。
- 视觉平台只做预先登记的人工会话：固定入口、会话起止、滚动/翻页次数、看到的条目数和账号状态；不主动点赞、关注、评论或发布内容。

### 5.2 词表和代码本

将下列内容写入带版本号的 CSV/JSON 清单，不在脚本里散落硬编码：

```text
对象：Latin/English alphabet；Han/Chinese characters/汉字；
      Japanese/Kana/Kanji/日本語；Korean/Hangul/한글；
      以及仓库已登记的书体、字体和 stimulus_id
评价：premium/high-end/luxury；minimal；international/global；
      traditional/classic；modern/contemporary；trustworthy/reliable；
      readable/legible；unfamiliar/foreign；及对应的 zh-CN/en/ja/ko 词形
品类：tea、alcohol、fragrance、jewelry、technology、fashion、
      food/hospitality 及中文、日文、韩文对应词形
机制：geometry、stroke/line、density、spacing、seal/history、
      foreignness/familiarity、readability、symbolism
立场：positive、negative、mixed、descriptive、counterexample、unclear
```

每个规范词保存别名、语言、是否用于探索/确认、加入或停用日期和人工说明。词表不能把“某文字天然等于某评价”写成标签；它只定义要检索和核验的候选表达。

### 5.3 处理顺序

1. 建立运行清单并核对来源条款、时间窗、查询版本和采集上限。
2. 将获准导出放入 `data/raw/social/<platform>/<run_id>/`，计算输入 SHA-256。
3. 用 `tools/normalize_social_records.py` 生成规范 JSONL 和失败 CSV；逐行执行 schema 校验。
4. 先去重、识别语言和筛选相关性，再由两名编码员独立填写对象、叙事词、品类、立场、机制和 `evidence_span`。
5. 将确认记录投影到 `schema/cultural_narrative.schema.json`（如适用），保留与原观察记录的关联，不覆盖采集字段。
6. 用 `tools/summarize_narratives.py` 分别生成记录数和可见互动两个视图；按平台、语言、品类和来源角色分层。
7. 运行重复采集、查询词敏感性、最大来源剔除和双人编码一致性检查；把结果写入审计报告。
8. 只有通过发布清单的记录才进入 `data/releases/`；否则只保留本地处理结果和问题单。

### 5.4 机械验收闸门

一轮试运行只有同时满足以下条件，才可称为“可供组员审查的结果”：

- 规范 JSONL 每行通过 `schema/social_observation.schema.json`；`observation_id` 不重复；失败行全部在失败 CSV，且有错误码和行哈希。
- 同一输入、同一参数和同一 `normalized_at` 连续运行两次，输出字节完全一致；矩阵摘要包含输入 SHA-256、过滤条件和计数单位。
- `platform_item_id`、URL、采集时间等关键字段完整率为 100%；其他允许缺失的字段报告分平台缺失率，不用估计值填补。
- 双人独立编码至少覆盖 20%（或不足 30 条时按协议全量/至少 30 条）；对象、评价词、立场的 alpha 达到预设门槛，未达标则不发布主结论。
- 同一查询的两次运行均报告 ID/URL 重合率、Jaccard、重复率、缺失时段和平台返回上限；不要求动态平台达到预设重合值，但必须解释差异。
- 查询词敏感性、最大来源剔除和语言/平台分层结果均存在；任何对象/词分母小于 20 的单元带有“探索性”标记。
- 进入公开 release 的每条叙事证据都有访问日期、原始定位符、精确证据片段、人工复核状态和许可/隐私决定；无用户名、Cookie、API token 或版权不明全文。

### 5.5 交付物

最小交付包应包含：

```text
运行清单（查询、时间窗、来源、版本、配额）
规范 observations.jsonl
observations.jsonl.failures.csv（可为空，但文件和说明保留）
sources.csv
matrix_a_term_given_object.csv
matrix_b_object_given_term.csv
lift.csv
summary.json
质量/伦理/许可审计报告
可复跑命令和环境版本
待检验假设清单（每条绑定 evidence_id/source_id）
```

假设清单的每一条只写成可证伪句式，例如：“在控制文字内容、字面面积和可读性后，英语语境中被标为 `international` 的拉丁字标是否仍比汉字字标获得更高的国际化评分？”它不能直接写成“拉丁字标更国际化”。

## 6. 与四条研究线的接口

| 研究线 | 社会叙事系统提供 | 下一步由该研究线检验 | 禁止的替代关系 |
|---|---|---|---|
| 1. 跨文化感知 | 各语言/来源/品类中出现的评价词、反例和叙事假设 | 真实母语/非母语受试者对同一刺激的美观、高级、现代、可信、易读、陌生评分；检查文化交互 | 不把帖子数量当受试者比例，不把共现当偏好 |
| 2. 文化—历史叙事 | 带来源、时间、角色和证据片段的叙事证据卡；可能的采用链 | 将当代说法与历史档案、设计史和品牌材料对照，区分起源、再生产和反例 | 不把最早抓到的帖子称为历史起源，不把单一品牌文案称为社会共识 |
| 3. 跨文字视觉形式 | 哪些机制词（密度、几何、留白、笔画、间距等）被公众说出 | 用冻结的 4+4 视觉特征表检查机制词是否对应可测视觉差异，并与人类评分建模 | 不让语言模型或互动量充当视觉特征/审美真值 |
| 4. 汉字内部书体演化 | 小篆、隶书、楷书、行书、草书、宋体、黑体等在品牌和公共讨论中的叙事与反例 | 在相同文字内容、画布、字面面积和可读性条件下比较书体；由书法/字体专家审查历史解释 | 不由一条社交媒体描述推断书体的历史意义或普遍审美 |

统一接口是已有冻结的 `stimulus_id`、`font_id`、`source_id` 和变量字典；四条线的观测结果仍分别进入各自 schema 和分析表。

## 7. 这套系统能回答什么，不能回答什么

| 问题 | 第一版结论能力 | 正确表述 |
|---|---|---|
| 某对象与哪些评价词共同出现？ | 可以 | “在平台 X、语言 Y、时间窗 Z 和词表版本 V 的观察样本中，共现率/Lift 为……” |
| 哪类来源提出或重复某种说法？ | 可以（若角色可核验） | “品牌/设计媒体/普通用户来源中出现的比例和证据片段……” |
| 某条目获得多少互动？ | 只能看可见指标 | “采集时页面显示的点赞/评论/播放等；不是曝光量或独立人数。” |
| 哪个平台最有影响力？ | 不能由原始条数或点赞直接回答 | 只能比较分层、归一化后的观察量，并报告接口覆盖和缺失；“影响力”需另行设计 |
| 谁首先创造了某种刻板印象？ | 不能 | 最早被观察到的记录只是检索框架中的下界；历史起源需档案和来源考证 |
| 推荐算法让多少人看到？ | 不能 | 可做固定会话的推荐暴露观察，但不能换算总体曝光或因果效果 |
| 某种文字导致高级感/信任感吗？ | 不能由社会数据回答 | 由受控、跨文化真人实验在控制视觉特征、可读性和熟悉度后检验 |
| 哪个视觉特征解释评价差异？ | 不能由叙事共现单独回答 | 由纯视觉测量与人类评分的联合模型回答，并报告文化和模型偏差 |

## 8. 公开仓库和持续维护规则

1. **只提交可复现且可公开的层**：schema、代码、模板、合成 fixture、派生统计、运行说明和审计模板可以进入 Git；原始响应、截图、受限正文、密钥和私盐不进入 Git。
2. **版本同时前进**：schema、query lexicon、codebook、normalizer、summary 和运行清单各有版本；修改字段或含义时升版本，不在旧文件上静默改写。
3. **外部工具不 vendoring**：在文档中列出名称、官方 URL、许可证核验日期和用途；使用者在自己的环境按平台条款安装。
4. **删除和撤回可执行**：收到平台删除、作者撤回或版权通知时，在本地登记处置记录，公开派生物按 `source_id`/哈希定位并重建；不依赖公开原文才能复现统计时，说明无法再水合。
5. **审计优先于规模**：每扩大一个平台或语言，先完成一次重复采集、双人复核和权限/许可检查；质量不通过就保留为探索数据，不升级为主结果。

## 9. 正式参考文献与工具清单

以下条目对应正文中的编号。DOI、题名和作者以 DOI/Crossref 元数据为准；工具
链接和许可证是 2026-09-01（Asia/Shanghai）核对的公开信息。许可证只说明
软件本身，不代表任何平台导出数据可以再分发。

### 9.1 研究论文和报告

- **[M1]** Peeters, S., & Hagen, S. (2022). *The 4CAT Capture and Analysis Toolkit: A Modular Tool for Transparent and Traceable Social Media Research*. Computational Communication Research. [DOI: 10.5117/CCR2022.2.007.HAGE](https://doi.org/10.5117/CCR2022.2.007.HAGE)
- **[M2]** Hui, P.-M., Shao, C., Flammini, A., Menczer, F., & Ciampaglia, G. L. (2018). *The Hoaxy Misinformation and Fact-Checking Diffusion Network*. Proceedings of the International AAAI Conference on Web and Social Media, 12(1). [DOI: 10.1609/icwsm.v12i1.14986](https://doi.org/10.1609/icwsm.v12i1.14986)
- **[M3]** Shao, C., Hui, P.-M., Wang, L., Jiang, X., Flammini, A., Menczer, F., & Ciampaglia, G. L. (2018). *Anatomy of an online misinformation network*. PLOS ONE, 13(4), e0196087. [DOI: 10.1371/journal.pone.0196087](https://doi.org/10.1371/journal.pone.0196087)
- **[M4]** Zannettou, S., Caulfield, T., De Cristofaro, E., Kourtelris, N., Leontiadis, I., Sirivianos, M., Stringhini, G., & Blackburn, J. (2017). *The web centipede*. Proceedings of the 2017 Internet Measurement Conference, 405–417. [DOI: 10.1145/3131365.3131390](https://doi.org/10.1145/3131365.3131390)
- **[M5]** Chen, E., Lerman, K., & Ferrara, E. (2020). *Tracking Social Media Discourse About the COVID-19 Pandemic: Development of a Public Coronavirus Twitter Data Set*. JMIR Public Health and Surveillance. [DOI: 10.2196/19273](https://doi.org/10.2196/19273)
- **[M6]** Tufekci, Z. (2014). *Big Questions for Social Media Big Data: Representativeness, Validity and Other Methodological Pitfalls*. Proceedings of the International AAAI Conference on Web and Social Media, 8(1). [DOI: 10.1609/icwsm.v8i1.14517](https://doi.org/10.1609/icwsm.v8i1.14517)
- **[M7]** Morstatter, F., Pfeffer, J., Liu, H., & Carley, K. M. (2013). *Is the Sample Good Enough? Comparing Data from Twitter’s Streaming API with Twitter’s Firehose*. Proceedings of the International AAAI Conference on Web and Social Media, 7(1). [DOI: 10.1609/icwsm.v7i1.14401](https://doi.org/10.1609/icwsm.v7i1.14401)
- **[M8]** Pfeffer, J., Mayer, K., & Morstatter, F. (2018). *Tampering with Twitter’s Sample API*. EPJ Data Science, 7. [DOI: 10.1140/epjds/s13688-018-0178-0](https://doi.org/10.1140/epjds/s13688-018-0178-0)
- **[M9]** Cheliotis, G., Lu, X., & Yi, S. (2015). *Reliability of Data Collection Methods in Social Media Research*. Proceedings of the International AAAI Conference on Web and Social Media, 9(1), 586–589. [DOI: 10.1609/icwsm.v9i1.14669](https://doi.org/10.1609/icwsm.v9i1.14669)
- **[M10]** Lomborg, S., & Bechmann, A. (2014). *Using APIs for Data Collection on Social Media*. The Information Society, 30(4), 256–265. [DOI: 10.1080/01972243.2014.915276](https://doi.org/10.1080/01972243.2014.915276)
- **[M11]** Chen, K., Duan, Z., & Yang, S. (2021). *Twitter as research data*. Politics and the Life Sciences, 41(1), 114–130. [DOI: 10.1017/pls.2021.19](https://doi.org/10.1017/pls.2021.19)
- **[M12]** Goodspeed, R. (2013). *The Limited Usefulness of Social Media and Digital Trace Data for Urban Social Research*. Proceedings of the International AAAI Conference on Web and Social Media, 7(5), 2–4. [DOI: 10.1609/icwsm.v7i5.14485](https://doi.org/10.1609/icwsm.v7i5.14485)
- **[M13]** Fiesler, C., & Proferes, N. (2018). *“Participant” Perceptions of Twitter Research Ethics*. Social Media + Society, 4(1). [DOI: 10.1177/2056305118763366](https://doi.org/10.1177/2056305118763366)
- **[M14]** Zimmer, M. (2010). *“But the data is already public”: on the ethics of research in Facebook*. Ethics and Information Technology, 12(4), 313–325. [DOI: 10.1007/s10676-010-9227-5](https://doi.org/10.1007/s10676-010-9227-5)
- **[M15]** Hayes, A. F., & Krippendorff, K. (2007). *Answering the Call for a Standard Reliability Measure for Coding Data*. Communication Methods and Measures, 1(1), 77–89. [DOI: 10.1080/19312450709336664](https://doi.org/10.1080/19312450709336664)
- **[M16]** Artstein, R., & Poesio, M. (2008). *Inter-Coder Agreement for Computational Linguistics*. Computational Linguistics, 34(4), 555–596. [DOI: 10.1162/coli.07-034-r2](https://doi.org/10.1162/coli.07-034-r2)
- **[M17]** Willaert, T., Van Eecke, P., Beuls, K., & Steels, L. (2020). *Building Social Media Observatories for Monitoring Online Opinion Dynamics*. Social Media + Society. [DOI: 10.1177/2056305119898778](https://doi.org/10.1177/2056305119898778)
- **[M18]** Wiedemann, G., Münch, F. V., Rau, J. P., Kessling, P., & Schmidt, J.-H. (2023). *Concept and challenges of a social media observatory as a DIY research infrastructure*. Publizistik. [DOI: 10.1007/s11616-023-00807-6](https://doi.org/10.1007/s11616-023-00807-6)
- **[M19]** Stieglitz, S., Mirbabaie, M., Ross, B., & Neuberger, C. (2018). *Social media analytics – Challenges in topic discovery, data collection, and data preparation*. International Journal of Information Management. [DOI: 10.1016/j.ijinfomgt.2017.12.002](https://doi.org/10.1016/j.ijinfomgt.2017.12.002)
- **[M20]** Bruns, A. (2019). *After the ‘APIcalypse’: social media platforms and their fight against critical scholarly research*. Information, Communication & Society. [DOI: 10.1080/1369118X.2019.1637447](https://doi.org/10.1080/1369118X.2019.1637447)
- **[M21]** Ohme, J., Araujo, T., Boeschoten, L., Freelon, D., Ram, N., Reeves, B. B., & Robinson, T. N. (2023). *Digital Trace Data Collection for Social Media Effects Research: APIs, Data Donation, and (Screen) Tracking*. Communication Methods and Measures, 18(2), 124–141. [DOI: 10.1080/19312458.2023.2181319](https://doi.org/10.1080/19312458.2023.2181319)
- **[F1]** Qiu, Q., Watanabe, S., & Omura, K. (2021). *Emotional Responses to Chinese Characters: Exploration for Simplified, Traditional Chinese and Japanese Typefaces*. International Journal of Affective Engineering, 20(2), 79–85. [DOI: 10.5057/ijae.ijae-d-20-00018](https://doi.org/10.5057/ijae.ijae-d-20-00018)
- **[F2]** Gabriel, N. V., & Ryoke, M. (2020). *Communication through Typefaces: Affective Selection of English, Myanmar and Japanese Typefaces*. International Symposium on Affective Science and Engineering. [DOI: 10.5057/isase.2020-c000039](https://doi.org/10.5057/isase.2020-c000039)
- **[F3]** Kulahcioglu, T., & de Melo, G. (2018). *FontLex: A Typographical Lexicon based on Affective Associations*. Proceedings of LREC 2018. [DOI: 10.63317/59okd4eav957](https://doi.org/10.63317/59okd4eav957)
- **[F4]** van Rompay, T. J. L., & Pruyn, A. T. H. (2011). *When Visual Product Features Speak the Same Language: Effects of Shape-Typeface Congruence on Brand Perception and Price Expectations*. Journal of Product Innovation Management, 28(4), 599–610. [DOI: 10.1111/j.1540-5885.2011.00828.x](https://doi.org/10.1111/j.1540-5885.2011.00828.x)
- **[F5]** Henderson, P. W., Giese, J. L., & Cote, J. A. (2004). *Impression Management Using Typeface Design*. Journal of Marketing, 68(4), 60–72. [DOI: 10.1509/jmkg.68.4.60.42736](https://doi.org/10.1509/jmkg.68.4.60.42736)
- **[F6]** Childers, T. L., & Jass, J. (2002). *All Dressed Up With Something to Say: Effects of Typeface Semantic Associations on Brand Perceptions and Consumer Memory*. Journal of Consumer Psychology, 12(2). [DOI: 10.1207/S15327663JCP1202_03](https://doi.org/10.1207/S15327663JCP1202_03)

### 9.2 工具、代码和许可证

- **[T1] Zeeschuimer**：Digital Methods Initiative，<https://github.com/digitalmethodsinitiative/zeeschuimer>，MPL-2.0。
- **[T2] Facepager**：<https://github.com/strohne/Facepager>，MIT。
- **[T3] Taguette**：<https://gitlab.com/remram44/taguette>，BSD-3-Clause。
- **[T4] Label Studio**：HumanSignal，<https://github.com/HumanSignal/label-studio>，Apache-2.0。
- **PRAW**：<https://github.com/praw-dev/praw>，BSD-2-Clause；仅作为 Reddit 上游适配器候选。
- **Google API Python Client**：<https://github.com/googleapis/google-api-python-client>，Apache-2.0；仅作为 YouTube 上游适配器候选。
- **YouTube Data Tools**：<https://github.com/bernorieder/YouTube-Data-Tools-v2>，GPL-3.0-or-later；只借鉴公开流程，不在 GLYPH 中嵌入代码。
- **X API 文档**：<https://docs.x.com/x-api/getting-started/about-x-api.md>；平台 API 条款和价格随时间变化，启用前必须重新核对。

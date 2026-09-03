# GLYPH 里程碑 3：YouTube Query 产出校准冻结提案

版本：0.2.0<br>
日期：2026-09-02<br>
状态：已获用户明确批准；真实 discovery 已完成；等待研究者本人完成 105 条盲筛<br>
适用范围：M3 YouTube 检索与抽样设计校准；不进入 M4

版本说明：v0.1.0 未执行，现由 v0.2.0 取代。v0.2.0 冻结独立 confirmatory scope
模板、非重叠留出窗口和显式分层配额，并与当前机械晋级契约一致；真实请求范围不扩大。

## 结论先行

本提案针对 run `social_run_youtube_20260902085203_382c800b` 暴露的零纳入问题，校准 YouTube 视频候选 query 的产出，不放宽对象—评价筛选规则，也不把原 pilot 的 4 条误命中解释成 precision 估计。

校准使用 12 条预登记、不可变 query，每条评价 relevance 排序前 20 个通过视频详情与时间窗检查的候选。候选仅做视频 metadata 相关性盲筛，不采集评论或回复。系统按 query 机械计算 resolved top-20 precision 与 Wilson 95% 区间；只有满足全部预登记最低线的 query 才能生成带校准证据引用的新 confirmatory query。

本文件即使获批，也只授权一次校准 run 及其离线筛选、评价、导出和备份。生成 confirmatory query 不等于授权执行后续确认采集，更不授权 M4。

## 冻结晋级输出（不授权执行）

校准报告冻结后，只允许从当前报告逐条选择 `passed` query。系统为所选 query 原子创建一个新的
confirmatory scope，并归档来源 calibration scope；failed/inconclusive query 留在来源证据中，
不得混入确认运行。每个 source run/report/query 最多晋级一次，不能通过更换窗口或配额重复生成。

确认 scope 模板冻结如下：

| 项目 | 冻结值 |
|---|---|
| 名称 | `M3 YouTube held-out confirmation v0.2.0` |
| UTC 留出窗口 | `2025-08-29T00:00:00Z` 至 `2026-03-01T00:00:00Z` |
| 与校准窗口关系 | 紧邻校准窗口之前、等长且不重叠 |
| 每通过 query 视频候选 | 20 |
| 每纳入视频评论线程 | 20 |
| 每线程回复 | 5 |
| 评论/回复运行总上限 | 480；高于最多 240 个视频候选，保证每个候选至少一个容量位置 |
| 调度 | 默认禁用 |

该模板只建立下一阶段的不可变研究对象，不授权启动 confirmatory run。校准完成后必须根据实际
通过 query 数、全局当日剩余量和上述评论上限另写请求预算与停止条件，并再次取得用户明确批准。

## 为什么不能只扩大原 Query

原 pilot 的 4 条候选分别出现 `Latin` 词源歧义、`modern` 泛义、职业内容和非字体视觉工具误命中。每 query top-2 太浅，无法判断问题来自：

- `Latin typography` 这一对象表达本身产出低；
- `premium` 或 `modern` 的评价词歧义不同；
- 基于已观察误命中的负词过滤是否提高 precision；
- YouTube relevance 前排在更深 k 下是否仍由误命中主导。

因此本次采用对象表达、评价词和过滤策略的因子化比较。过滤变体与未过滤变体并存，避免事后只保留看起来有效的负词规则。

## 冻结研究范围

| 项目 | 冻结值 |
|---|---|
| 平台 | YouTube Data API v3 |
| 目的 | query-yield calibration；不估计平台总体比例或曝光 |
| 对象 registry | `writing_system / latin` |
| 语言提示 | `en`；不解释为作者身份或国籍 |
| UTC 窗口 | `2026-03-01T00:00:00Z` 至 `2026-09-01T00:00:00Z` |
| 排序 | YouTube relevance；不是随机顺序 |
| Query phase | 全部 `calibration`；禁止与 exploratory/confirmatory 混跑 |
| Query family | 全部 `object_aesthetic` |
| 每 query 视频候选 | 20 |
| 最大 query-video 命中 | 240；重叠视频保留各 query-match，observation 去重 |
| 评论线程 / 回复 | 0 / 0 |
| `max_items` | 240；不得截断每 query 的 20 个视频候选 |
| 调度 | 禁用；一次手动 run；不自动重试 |
| 发布默认值 | `release_allowed=false` |

时间窗用于增加候选供给，不表示这 6 个月是时间趋势样本。YouTube 的历史索引、删除、区域可见性和 relevance 排序仍会造成不可见缺失。

## 冻结 Query 集

负词策略固定为 `-music -jobs -automotive -translation`。它来自本次 pilot 的可观察误命中类别，但不预设一定有效；若它也删除相关内容，filtered 变体会通过更低的召回或不足 20 条显现。

| 编号 | 对象表达 | 评价词 | 过滤 | exact query |
|---|---|---|---|---|
| Q01 | Latin typography | premium | 无 | `"Latin typography" premium` |
| Q02 | Latin typography | modern | 无 | `"Latin typography" modern` |
| Q03 | Latin typeface | premium | 无 | `"Latin typeface" premium` |
| Q04 | Latin typeface | modern | 无 | `"Latin typeface" modern` |
| Q05 | Latin letterforms | premium | 无 | `"Latin letterforms" premium` |
| Q06 | Latin letterforms | modern | 无 | `"Latin letterforms" modern` |
| Q07 | Latin typography | premium | 负词 | `"Latin typography" premium -music -jobs -automotive -translation` |
| Q08 | Latin typography | modern | 负词 | `"Latin typography" modern -music -jobs -automotive -translation` |
| Q09 | Latin typeface | premium | 负词 | `"Latin typeface" premium -music -jobs -automotive -translation` |
| Q10 | Latin typeface | modern | 负词 | `"Latin typeface" modern -music -jobs -automotive -translation` |
| Q11 | Latin letterforms | premium | 负词 | `"Latin letterforms" premium -music -jobs -automotive -translation` |
| Q12 | Latin letterforms | modern | 负词 | `"Latin letterforms" modern -music -jobs -automotive -translation` |

引号只是冻结 query 字符的一部分，不被解释为平台保证的严格短语匹配。系统保存 API 实际返回结果与 query 内候选排名，人工筛选仍决定构念相关性。

## 冻结评价政策

政策版本：`query_yield_v0.1.0`。

| 参数 | 冻结值 |
|---|---:|
| `evaluation_k` | 20 |
| `min_included_at_k` | 6 |
| `min_precision_at_k` | 0.30 |
| `min_precision_lower_bound` | 0.12 |
| `confidence_level` | 0.95 |

对每条 query，令 $x$ 为 top-20 中人工 `include` 数，$n=20$，则：

$$
\hat p = \frac{x}{n}
$$

Wilson 区间由冻结代码使用标准正态分位数计算。query 只有同时满足以下条件才为 `passed`：

1. query 内候选排名 1 至 20 完整且无重复；
2. top-20 全部有人工作出的明确 `include` 或 `exclude`，不得残留 `uncertain`；
3. $x\ge 6$；
4. $\hat p\ge 0.30$；
5. Wilson 95% 下界不低于 0.12。

候选不足、排名证据不完整或筛选未决均为 `inconclusive`，不是 `failed`。证据完整但低于最低线才是 `failed`。这些值是本次 M3 的操作性最低线，用于避免把低产 query 带入后续确认采集，不是 YouTube 检索质量的普遍统计定律。

整体报告可以因部分 query 失败而为 `failed`，但逐 query 结果独立。系统只允许晋级 `calibration_passed_query_ids` 中的 query；未达标 query 不会因同一 run 中其他 query 通过而晋级。

## 候选排名与分母

`candidate_rank` 定义为：同一冻结 query 内，按 YouTube relevance 返回顺序，经过 `videos.list` 详情存在性与登记时间窗校验后，实际进入人工筛选队列的视频顺位。不得用数据库插入顺序、observation ID 或后续评论数推断排名。

报告同时保存：

- `unique_candidate_count`：跨 query 去重的视频 observation 数；
- `candidate_query_match_count`：query-video 命中数，最大 240；
- 每 query 的 retrieved、ranked、human screened、resolved、include、exclude、uncertain 和 missing；
- resolved 全体 precision 与 Wilson 区间；
- precision@20 与 Wilson 区间；
- 明确的 inconclusive/failure reasons。

评论和回复的 query-match 保留 provenance，但绝不进入 query-yield 分母。

## 盲筛协议

校准 run 的 screening API 必须移除 `query_id` 与 `query_text`，并按 `SHA-256(run_id + observation_id + blind-version)` 形成稳定、可复算但非 relevance 顺序的队列。研究者一次只筛选本 run。

同一视频被多条 query 命中时只筛选一次，同一决定投影到各 query-match；不得因为某条 query 的预期而对同一视频作不同相关性决定。

仅根据规范化视频标题、描述和其公开页面确认以下关系：

- `include`：文本明确以 Latin typography、Latin typeface 或 Latin letterforms 为对象，并明确使用 premium/modern 评价该对象或其设计结果；
- `exclude`：Latin 仅指语言、词源、地名、人名或其他对象，或 premium/modern 明确修饰汽车、音乐、职业、工具、品牌套餐等非目标对象；
- `uncertain`：对象指代或评价归属无法从可核文本确定。

每个决定必须填写逐条理由。不得为提高 yield 放宽为“出现任一关键词即可”，不得在看到每 query 指标后回改边界案例。若规则本身需要修改，本 run 保持原决定并另建新版本校准。

## 请求和配额上限

本 run 独立冻结：

| 桶 | Run 上限 | 推导 |
|---|---:|---|
| `search_calls` | 24 calls | 每 query 最多 2 页，共 12 条 query |
| `shared_units` | 48 units | 每个搜索页最多 1 次 `videos.list` + 1 次 `channels.list` |

预期通常为 12 次 search 和 24 shared units；上表是机械停止上限，不是调用目标。评论与回复预算为 0，任何 `commentThreads.list` 或 `comments.list` 调用均构成立即停止条件。

运行前还必须确认当前 YouTube 全局日预算与当日剩余量足以容纳本 run。系统同时执行当前全局日预算和不可放宽的 run 快照预算；启动后提高全局预算不得扩大本 run 上限。

## 执行顺序

1. 确认含 Key 的 8765 服务未运行、YouTube schedule enabled=0、无活动 run、主库 `integrity_check=ok`。
2. 创建 pre-run 一致性备份并记录 SHA-256；确认主库为 schema v13、`integrity_check=ok`，并核对历史 run、observation 和 quota event 未改写。
3. 通过本机 Keychain 向单个 8765 进程注入 key；外网代理固定为 `http://127.0.0.1:7897`。
4. 登记一个 scope 和上述 12 条不可变 calibration query；核对 exact query、registry hash、UTC 窗口、layer quotas 和统一 query-yield policy。
5. 以 run search=24、shared=48 启动一次手动 run；不得启用调度或自动重试。
6. discovery 完成后停止外部请求；核对每条 match 的 candidate rank、query ID 和 exact query provenance。
7. 关闭含 Key 服务，再在本机工作台按盲化顺序完成全部视频筛选。
8. 冻结 query-yield 报告；不得在指标可见后改筛选规则或阈值。
9. 按“冻结晋级输出”只为通过 query 创建独立 confirmatory scope；确认来源 calibration scope 已归档，未通过 query 未混入；不执行这些 query。
10. 导出并验证校准包，创建 post-run 备份，更新 M3 报告后停止。

## 立即停止条件

任一条件出现即停止，不扩大 query、不补抽、不自动重跑：

- key、代理、请求目标、scope、query、窗口或 registry hash 与冻结提案不一致；
- calibration 与其他 phase 混跑，或任一 query 的视频上限低于 20；
- search 超过 24 calls，shared 超过 48 units，或发出任何评论/回复请求；
- candidate rank 缺失、重复、跳号，或 query-match 与 API 返回顺序无法核对；
- 视频筛选 API 暴露 query identity，或筛选顺序回到 relevance 顺序；
- 出现认证/权限错误、`quotaExceeded`、不可解释 4xx、连续 5xx 或响应形状异常；
- secret、直接作者标识或未经许可正文进入不应出现的位置；
- schema、不可变 trigger、导出验证、备份完整性或历史数据审计失败；
- 用户撤销批准。

API 结果不足 20 条不是补抽理由：对应 query 记为 `inconclusive`。只有新提案和新批准才能改变窗口、query 或 k。

## 必须形成的证据

- pre/post 备份及 SHA-256、schema version、`integrity_check=ok`；
- run manifest、12 条 query 快照、registry 快照、双桶 run quota policy 和逐请求事件；
- `observation_query_matches.jsonl` 中的 query 内 candidate rank；
- 完整 screening history，含机器候选事件和人工决定理由；
- `query_yield_policy.json`、追加式 `query_yield_reports.jsonl`、当前 `yield_calibration.json`；
- 每 query 三态结果、Wilson 区间、通过 ID 和晋级 query 的 source run/report/query 引用；
- `validation.json.valid=true` 的导出 ZIP；
- 零总体推断、零 M4 扩展、零 confirmatory 网络执行的边界声明。

## 执行记录

- 用户于 2026-09-02 明确批准本文件 v0.2.0，授权边界与下方批准文本一致。
- 全局本机阈值从旧 pilot 的 search=2/shared=25 最小提高到 search=26/shared=52；扣除既有
	2/4 后，本 run 启动前可用量恰为 24/48。run 自身快照仍不可放宽地冻结为 24/48。
- pre-run 备份为 `backup_20260902T133921Z_e3593eef`，schema v13、`integrity_check=ok`，
	SHA-256 `71e1fd735bb34e17e3503a07c88341bd96f3929bcf04f3cf0a012a8f8afde1c1`；
	当时仍为 3 runs、16 observations、12 quota events 和 204 legacy units。
- 登记 scope `scope_youtube_99295095c85ad5ba` 和 12 条不可变 query。请求前审计发现同秒登记
	query 会被哈希 ID 二次排序；含 Key 服务随即关闭，且尚未创建 run、未发 YouTube 请求。
	存储读取改为保持不可变追加表顺序，并增加同秒顺序回归；YouTube/query-yield 36 passed 后，
	Q01-Q12 顺序、唯一配置哈希、registry、政策和零评论配额全部重新通过强断言。
- 唯一真实 run 为 `social_run_youtube_20260902134215_18f86349`。经 7897 实际调用
	`search.list=12`、`videos.list=12`、`channels.list=12`；run error=0，评论/回复调用=0。
	发现 105 个去重视频和 145 个 query-video match，12/12 query 均有连续唯一的 1…n rank，
	每 query 不超过 20；不足 20 的 query 不补抽。
- discovery 完成后含 Key 的 8765 已关闭。checkpoint 备份为
	`backup_20260902T134427Z_3d5e00e9`，schema v13、`integrity_check=ok`，SHA-256
	`7eeac45cd3ca45c1d210b5f5854e46183cdbec289be1910475a869b56dcd673b`。
- 无 Key、无代理的 8767 盲筛队列为 105 条；两次读取顺序一致，响应不含 `query_id` 或
	`query_text`。当前尚未写入任何人工决定，未冻结 query-yield 报告，未创建或执行
	confirmatory scope。自动代填会被系统误记为 `annotator_local01/manual_review=true`，因此必须
	等待研究者本人逐条作出决定，不能用 AI 提交冒充人工筛选。
- discovery 后全仓回归为 96 passed，`node --check`、`git diff --check` 和无凭据服务门禁通过。

## 批准文本（已满足）

可接受授权必须明确引用本文件和版本，例如：

> 批准执行 `status/milestone_3_youtube_query_calibration_proposal_zh.md` v0.2.0，严格按 12 条冻结 query、top-20、盲筛、run search=24/shared=48 和全部停止条件，经 7897 发起一次 YouTube query-yield calibration；不采评论，不执行晋级后的 confirmatory scope，不进入 M4。

上述批准已收到并仅用于本节记录的唯一 calibration run。它不授权自动代替人工盲筛、执行
confirmatory scope 或进入 M4。
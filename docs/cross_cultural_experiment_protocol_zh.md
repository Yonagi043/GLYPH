# TASK-03 跨文化视觉感知实验协议与本机运行

文档版本：`1.1.0`。冻结 study protocol 与 questionnaire 版本仍为 `1.0.0`。

## 当前边界

本子系统当前仅为 synthetic engineering fixture。`configs/cross_cultural_study_v1.json` 中 `synthetic_only=true`，`GATE-ETHICS`、`GATE-PARTICIPANTS`、`GATE-TRANSLATION` 均为 `blocked`；TASK-01 也没有可进入正式问卷的刺激。系统不能招募、联系或收集真人响应，不能把 synthetic 记录用于正式分析或 release。

工程就绪不等于 pilot 就绪，也不等于研究有效。当前浏览器 runtime 用于验证协议、随机化、可访问呈现、SHA-256、持久恢复和数据契约。它没有参与者认证/提交授权；浏览器上报的 timing、viewport、focus/zoom 与 attention response 也没有服务端 challenge 或独立真实性证明。真实 pilot 前必须评估并冻结当前维护且许可兼容的成熟实验库（如 jsPsych）或完成等价的独立时序与授权验证，不能把本次浏览器遥测当作已验证测量工具。

## 研究设计

冻结协议位于 `configs/cross_cultural_study_v1.json`。主要 estimand 是参与者原生文字经验与刺激文字系统在 ordinal latent response scale 上的交互；主要结果为 `aesthetic`、`premium`、`modern`、`trustworthy`。`visual_clarity` 与 `recognition` 分开测量，避免把视觉清晰误写成能否读出。`brand_fit` 只有在另一个版本冻结品类场景后才允许呈现，当前盲评界面不收该项。

正式模型预注册为 ordinal mixed effects，至少包含 participant 与 stimulus random intercept、`native_script × stimulus_script`、预先指定的识别/陌生/训练协变量，并在每个结果族内使用 Holm 校正。confirmatory 与 exploratory 不得在看到真实结果后互换。跨语言比较前必须按 configural、metric、scalar 顺序检查测量等价性。

功效输出是透明假设情景，不是已批准样本量。当前 normal approximation 在假设标准化效应 `0.1/0.2/0.3` 与 crossed-clustering 近似下给出总样本范围 `2812–11744`。真实招募前必须用最终刺激数、流失、配额可得性、multiplicity 和 ordinal mixed model 做模型化模拟，并由 `GATE-PARTICIPANTS` 批准。

## 约束分配

许可 fixture 目录含 4 种文字系统，每种 4 个 synthetic stimulus；每人收到 8 个 trial，每种文字恰好 2 个。算法满足：

- 同一 block 不重复 `stimulus_id` 或 `work_id`；
- 相邻 trial 不连续出现同一文字系统；
- 每个 block 恰好出现 2 个跨版本 anchor；
- 按参与者组分别平衡 stimulus exposure 与 stimulus position；
- 冻结 tolerance 为 `1`，超出时 `audit-assignments` 返回非零；
- assignment、block、presentation 与 seed hash 可重现；
- SQLite 保存 assignment，刷新后恢复到下一个未提交 presentation；
- `request_id` 与 presentation 双重幂等，冲突 payload 稳定拒绝。

冻结的 4×4 fixture 使用按 participant group 独立推进的 16-session 精确周期。每个 session 恰有两个 script anchor；16 个连续 session 对四种文字、16 个 stimulus 与 8 个位置形成完整平衡周期。session allocation 在 SQLite `BEGIN IMMEDIATE` 内从全部历史 assignment 重建 quota state，并和 profile、consent、nonce、assignment 一次提交，因此并发进程和重启不会各自从零分配；相同 nonce 幂等，冲突 nonce payload 拒绝。两个独立 seed 的 1000 人 dry-run 均得到 8000 个 unique presentation、零丢失/重复、group-stimulus exposure spread `0`、stimulus-position spread `1`。

## 四语呈现

问卷定义位于 `configs/questionnaire_v1.json`，稳定 `item_id` 覆盖 10 个模块和简中、英语、日语、韩语。简中为 `source_draft`，其余均为 `translated_draft_unreviewed`，界面持续显示该状态。

浏览器只获得盲化 trial：`presentation_id`、`stimulus_id`、预期 SHA-256 与本机 asset URL。不会返回 writing system、work/source ID、奖项、作者、品牌、年份、文件名、来源 URL 或视觉模型分数。浏览器在显示前以 Web Crypto 计算实际字节 SHA-256；失败时停止 trial，不替换资产。计时从预加载与哈希完成后开始，预加载耗时单独记录。

同意、背景与 rating 控件使用原生 label/input，可键盘操作并有 `:focus-visible`。session API 接收并持久化完整 profile 和 consent receipt 1.1；刷新后恢复原问卷语言、锁定 session 语言、下一个 trial 和最新质量决定。每个 presentation 必须提交 7 个冻结必答 Likert item，当前可选 `brand_fit` 不呈现也不接受。记录 CSS viewport、刺激 CSS 尺寸、device pixel ratio、焦点丢失、zoom anomaly 与原始 attention response，但不记录 IP、user agent、键盘原始输入或设备指纹。

客户端不提交最终 `quality` 或 `attention_check`。服务端丢弃同名注入字段，从持久 profile、consent、累计 events、原始 attention response 与 ratings 按 rule `1.0.0` 计算 canonical decision；每次 accepted submission 追加历史节点，并把同一摘要写回该 presentation 的 7 条 ratings。窗口过小、离开标签页、缩放异常或 attention response 仍是客户端声明的原始遥测：服务端拥有决定权，不等于原始遥测具有独立真实性证明。

## 本机命令

所有命令在项目锁定环境中执行：

```bash
uv run --frozen glyph-experiment validate-study
uv run --frozen glyph-experiment synthetic-dry-run --participants 1000
uv run --frozen glyph-experiment build-blocks --study-id study_cross_cultural_v1 --participants 1000 --output-dir /tmp/task03-blocks
uv run --frozen glyph-experiment audit-assignments --study-id study_cross_cultural_v1 --assignments /tmp/task03-blocks/assignments.jsonl --catalog /tmp/task03-blocks/stimulus_catalog.json
uv run --frozen glyph-experiment build-reference --output-dir /tmp/task03-reference
uv run --frozen glyph-experiment power
uv run --frozen glyph-experiment serve --study-id study_cross_cultural_v1 --synthetic-only --port 8023
uv run --frozen glyph-experiment export --study-id study_cross_cultural_v1 --database data/raw/participants/task03-experiment.sqlite3 --output /tmp/task03-export --purpose engineering_fixture --deidentified
```

服务只绑定 `127.0.0.1`，默认端口 `8023`。省略 `--synthetic-only` 时返回 `REAL_COLLECTION_LOCKED`。export 创建目录，其中包含 profile、consent、assignment、presentation、rating、quality decision 六个 JSONL 及 `export_manifest.json`。写命令排他创建目标；已有输出返回 `NO_OVERWRITE`，不静默覆盖。

## 真实 pilot 前停止条件

以下项目全部完成人工批准前保持停止：伦理与数据管理计划；参与者认证、提交授权与撤回身份核验；招募、补偿、配额和样本量；四语委员会审阅、回译与认知访谈；成熟 runtime、可信时序及客户端原始遥测验证；TASK-01 正式刺激权利与策展；retention、访问控制和备份删除流程；真实设备预测试；跨语言测量等价性计划。任何一个门禁未通过都不能把 `synthetic_only` 改为 false。
# GLYPH 第一版视觉特征任务书与实现协议

版本：0.3（审批稿）  
日期：2026-08-29  
状态：已批准，按本协议进入实现；协议内容冻结，变更须升版本

## 1. 申请审批的事项

本方案申请批准一个有明确边界的第一阶段成果：

> 在受控渲染条件下，建立一批跨文字系统和汉字书体刺激，并把既有的 4+4 个视觉维度转化为可复现的测量表、代码、质量报告和公开文档。

这个阶段的终点是“可信的视觉测量基础设施”，不是审美预测模型，也不是对字体优劣的结论。

本阶段的最小可交付单元不是一张图片，而是一个可追溯记录：`stimulus_id`、输入字体和文字、渲染配置、规范图像、特征记录、质量状态和许可证信息必须能够相互校验。任何缺一项的记录只能留在 `needs_review`，不能进入公开 release。

## 2. 研究对象与八维框架

沿用现有 visual_analysis_framework_zh.md 的八个上层维度，不另起一套理论框架。

| 层级 | 维度 | 第一版的处理 |
|---|---|---|
| 单字/单个字形 | 几何度 | 量化轮廓的角度、直曲和对称等代理量 |
| 单字/单个字形 | 稠密度 | 量化字面覆盖、黑白比例和封闭空间等代理量 |
| 单字/单个字形 | 比例 | 量化外接框、笔画宽高与内部空间比例 |
| 单字/单个字形 | 笔势 | 量化骨架方向变化、曲率和粗细变化等代理量 |
| 多字字标 | 排版 | 量化对齐、字间距、行距、方向和位置关系 |
| 多字字标 | 视觉重心 | 量化轮廓质心、左右/上下平衡和偏移 |
| 多字字标 | 阅读节奏 | 量化字间距序列、面积序列和重复/变化模式 |
| 多字字标 | 统一度 | 量化字形尺寸、面积、笔画和基线的一致性 |

“维度”是理论层的研究语言；表中的角度、覆盖率、质心等是可观测代理量。第一版不把代理量任意加权成“美学分数”。

### 2.1 第一版究竟比较什么

第一版有两个不同的估计对象，不能混成一张总体排名：

1. **同文字系统内的字体/书体差异**：同一字符、同一脚本、同一渲染协议下比较字体条件。这是第一版的主要、可解释结果。
2. **文字系统间的形式分布差异**：在相同处理协议下描述四种文字的代理量分布。这是探索性结果，不把字体设计差异或语言经验解释成“文字系统本质”。

因此，分析表必须包含 script、font/style、content_set 和 normalization_profile；任何跨文字汇总都要同时给出文字系统分层结果，不能只报一个 pooled 均值。

### 2.2 可证伪问题与结论边界

第一版只回答三个可检验问题：

1. 在同一文字、同一内容和同一渲染 profile 内，不同字体实例的代理量是否存在可重复差异；
2. 同一字体实例在两个 profile 下的代理量是否保持方向一致，哪些量对归一化敏感；
3. 多单位序列的间距、面积和重心代理量能否在固定整形协议下稳定重算。

第一版不回答“哪种书体整体更美”“哪种文字系统更高级”或“某个代理量导致审美偏好”。WP4 的四个条件是**字体实例/书体范例**，不是可外推到整个书体类别的因果效应；除非后续加入同类多字体复本，否则报告中不得使用“书体效应”这一表述。

特征定义、阈值和算法参数在看到任何真人评分、品牌标签或结果分布前冻结；v1 不用结果驱动的特征筛选，也不以人工审美判断调参。这样后续 WP1 的评分可以作为外部验证，而不是参与特征构造。

## 3. 第一版范围

### 3.1 文字系统

第一版跨文字样本覆盖：

- 拉丁字母（Latn）
- 汉字（Hani）
- 日文假名（Kana）
- 韩文（Hang）

跨文字样本分为两个分析层，不把“字符”误当作跨脚本一一对应的同一个刺激：

1. **单单位形式层**：每种脚本各选 8 个独立单位。Latn 使用大写字母 A、E、H、M、O、R、S、T；Hani 使用 永、山、水、中、文、門、木、人；Kana 使用 あ、い、す、ね、の、ま、る、よ；Hang 使用 가、나、다、라、마、바、사、아。Kana/Hang 的清单须先通过字体覆盖和 Unicode NFC 检查。它们只用于描述形式分布，不声称跨脚本具有相同语言学功能。
2. **多单位排版层**：每种脚本用同一脚本内的 4 单位组成两条固定序列，并记录单位边界；用于排版、视觉重心、阅读节奏和统一度。第一版序列按单单位清单顺序固定：Latn 为 A-E-H-M 与 O-R-S-T，Hani 为 永-山-水-中 与 文-門-木-人，Kana 为 あ-い-す-ね 与 の-ま-る-よ，Hang 为 가-나-다-라 与 마-바-사-아。序列不使用品牌名称；若单位组成自然语言词语，标记其语义状态，不能把词义当作已控制变量。

单单位层允许跨脚本做分布对照，但不做“同一字符”的配对检验。汉字书体层则严格使用同一批汉字，进行配对比较。

这组清单是第一版的预注册 fixture，不根据第一次测量结果事后替换字符。若存在缺字，只能把该条件标为缺失并记录原因；候补字符必须在下一版协议中公开变更。

`data/fixtures/content_sets.csv` 固定记录 `content_set_id`、`writing_system`、`script_code_iso15924`、`content`、`unit_count`、`semantic_status`、`unicode_codepoints` 和 `selection_rationale`；`expected_clusters.csv` 记录每条序列预期的 cluster 数、单位顺序和语言标签。正式 manifest 只能引用这两个文件中的 ID，不能在命令行临时传入文字。

第一版不纳入真实品牌 Logo 图片、奖项作品截图或带图形符号的复杂 lock-up。这些材料留到后续文化叙事或生态效度研究。

### 3.1.1 选择、排除与替换规则

字符选择在协议批准时冻结，并记录选择理由（笔画、曲直、封闭空间覆盖）及 Unicode 码点。排除条件在采集前固定：缺字或由字体 fallback 代替、组合后 cluster 数与预期不符、彩色/位图字体、可变字体未锁定轴值、轮廓为空或越界、字体文件许可不可核验，均不得进入正式刺激。排除不触发静默替换；只生成缺失记录，候补字符或字体必须在下一协议版本中公开添加。

### 3.2 汉字书体

汉字内部样本使用同一字符清单，先覆盖四个可解释的书体/字体条件：

- 无衬线/黑体基线
- 衬线/宋体基线
- 楷体或规范手写基线
- 篆体或装饰性书体（仅在字形质量和许可证通过人工复核后纳入）

WP3 的跨脚本主比较每个脚本只选一个无衬线基线文件，避免把“脚本差异”和“字体家族差异”混在一起：Latn 采用 Noto Sans，Hani/Kana/Hang 采用相应地区的 Noto Sans CJK 变体，并明确记录地区字形（CN、JP、KR）。WP4 才改变字体/书体条件。Noto Sans CJK 的地区变体不能互换或合并为一个“泛 CJK”字体。

WP4 每个条件先选一个静态字体实例作为范例；若候选是 variable font，必须在 manifest 中写出轴值并导出可哈希的静态实例，不能让默认轴值或渲染器自行决定字形。因此 v1 可以比较“这四个范例”，但不能把结果命名为四类书体的总体规律。

第一版不追求一次覆盖所有历史书体。小篆、隶书、行书、草书等扩展必须在每个字体文件完成来源、许可证、字符覆盖和专家抽查后追加；不能用“风格相似”的随机字体替代书体。

### 3.3 字体来源和许可证

只使用许可证文本可核验、允许研究使用和再分发（或明确标记为不可再分发）的字体文件。优先候选：

- Noto Sans / Noto Sans CJK
- Noto Serif / Noto Serif CJK
- Source Han Sans
- Source Han Serif

候选字体的最终清单在采集时逐文件确认，记录下载 URL、版本、许可证原文或 SPDX 标识、访问日期和 SHA-256。字体文件、许可证和元数据分开记录；许可证不允许再分发时只发布文件哈希和获取说明。第一版不使用来源不明的网盘字体、商业字体试用版或从 Logo 图片反推的字体。

`asset_inventory.csv` 是进入 fixture 前的硬门槛，至少包含：`font_id`、`role`、`family_name`、`file_path`、`font_version`、`variable_axes`、`unicode_coverage_status`、`license_id`、`license_uri`、`redistributable`、`distribution_tier`、`sha256`、`reviewer`、`reviewed_at`。只有 `unicode_coverage_status=complete`、许可证审查通过且（`redistributable=true` 或 `distribution_tier=restricted`）的字体，才能写入正式 manifest；受限字体不得进入公开层。

## 4. 刺激单位和样本规模

一个 stimulus_id 代表一个完整渲染条件，而不是一个抽象字体。文字内容、字体/书体、画布、颜色、版式、缩放或归一化协议任一改变，都生成新的 ID。

建议的首批规模（不含失败记录；profile 复制的是分析条件，不代表新增内容）：

- WP3 单单位：4 脚本 × 8 单位 × 2 profile = 64 个刺激；
- WP3 多单位：4 脚本 × 2 固定序列 × 2 profile = 16 个刺激；
- WP4 单位：8 汉字 × 4 字体/书体 × 2 profile = 64 个刺激；
- WP4 多单位：2 条汉字序列 × 4 字体/书体 × 2 profile = 16 个刺激。

分析单元总数为 160 个“条件格”（content × font/style × profile），但若 WP3 的 Hani 基线与 WP4 的无衬线范例使用同一字体文件、同一地区字形、同一文字、同一布局和同一 profile，则物理上只生成 140 个唯一渲染刺激，并通过 `research_lines` 和 `content_set` 复用同一个 `stimulus_id`。报告必须同时给出条件格数、唯一 stimulus 数和失败数，不能把 160 写成实际文件数。若 WP4 的无衬线字体不是同一文件，则不去重，仍为 160 个唯一刺激。

WP4 的四个条件各只有一个字体实例时，统计单位是“字体实例 × 内容”，不是“书体类别”；8 个汉字不能被当作 8 个独立字体复本。任何类别层面的泛化都列为后续复本研究。

manifest 的生成顺序固定为：文字系统 `Latn, Hani, Kana, Hang`；每个系统内先单单位、后多单位；内容按 `content_sets.csv` 行顺序；字体先 WP3 基线、后 WP4 范例；profile 先 `bbox_height_matched`、后 `ink_area_matched`。CSV 使用 UTF-8、LF 换行和固定列顺序，禁止依赖文件系统遍历顺序。

## 5. 渲染与归一化协议

### 5.1 原始和规范化资产

每个刺激同时保存：

- 字体或矢量原始资产；
- 可审查的 SVG/轮廓中间表示（若输入允许）；
- 规范 PNG；
- 渲染配置和哈希。

视觉特征从规范化的灰度图和二值 mask 提取，原始彩色图只作为来源记录，不进入第一版纯视觉指标。

### 5.2 固定条件

第一版固定：

- 画布：2048 × 1024 px；
- DPI：96；所有输出均使用相同的像素尺寸，DPI 只作为元数据记录，不参与缩放；
- 色彩：sRGB，黑色前景、白色背景；
- 渲染器和版本：锁定依赖版本并写入运行记录；
- 抗锯齿：固定灰度抗锯齿参数，另以 8-bit 灰度阈值 128（小于 128 为前景、大于等于 128 为背景）生成二值 mask；
- 文本整形：固定 HarfBuzz/FreeType 版本、脚本和语言标签；统一 Unicode NFC；关闭可选连字和 kerning，保留脚本必需的整形；记录 OpenType feature 设置；
- 地区字形：Hani/Kana/Hang 的语言/地区标签显式写入 manifest，不把 CN、JP、KR 字形视为同一字形；
- 字体 hinting：关闭或固定 hinting 模式；不能让不同字体的网格拟合差异改变轮廓测量；
- 方向：默认水平排版，单字与多字分别记录；
- 对齐：单单位 ink bounding box 中心固定于 (1024, 512)；多单位文本组水平中心固定于 x=1024、baseline 固定于 y=640，同时保留 baseline anchor 和 ink-bbox anchor，避免把字体 ascender/descender 差异误当成排版差异；
- 缩放：只允许等比例缩放，禁止横向或纵向拉伸；
- 输出：PNG、UTF-8 元数据、SHA-256。

坐标原点在左上角，x 向右、y 向下；前景为不透明黑色，背景为不透明白色。任何 alpha、颜色管理或操作系统默认字体替换都视为 QC 失败。

多单位样本的单位边界来自文本整形器的 cluster 映射，不用连通区域数量猜测“第几个字”。连字、组合字符和跨单位重叠若无法稳定分段，该特征标记为 protocol_dependent 或缺失。

每条 manifest 在写入前按规范化 JSON（固定键排序、UTF-8、无多余空白）计算内容摘要；`stimulus_id` 本身保持不透明，但必须在 `run_manifest` 中记录生成所用的 manifest 摘要和协议版本。这样同一条件的重跑可以验证为同一刺激，任何条件改变都会留下新 ID，而不是覆盖旧文件。

### 5.3 两种归一化

不能用一种归一化同时回答所有问题，因此预先定义两个互相独立的 render profile；它们是不同 stimulus_id，不是同一图像的两个后处理数值：

1. bbox_height_matched（主分析）：等比例缩放，使非空 ink bounding box 高度为 320 px（允许不超过 1 px 的整数取整误差），再以固定 anchor 放入 2048 × 1024 画布；控制显示高度，同时保留宽度、内部比例、密度和笔势差异。320 px 是在保留冻结文字/字体矩阵和画布条件下覆盖最宽多单位样本的可行目标，并留出整数栅格余量。
2. ink_area_matched（敏感性分析）：等比例缩放，使二值 ink 面积占画布比例为 0.050；若按等比例缩放会越界或无法达到目标，则记录 `normalization_failed`，不得非等比例拉伸或事后改目标。0.050 是在同一矩阵下覆盖最低可行面积上限（0.0528565）的保守目标。该 profile 只检验面积控制下的稳定性，不用于报告自然密度差异。

v1.2.0 相对 v1.1.0 仅修订两个归一化目标。修订原因、逐刺激可行性计算和阈值选择记录在 `data/processed/visual_features_v1/audits/normalization_feasibility.*`；文字、字体、画布、整形、特征和目录均不变。旧运行保留在历史目录，不与新版本混用。

任何测量结果都必须带 normalization_profile。不报告归一化 profile 的数字不能进入发布数据。

### 5.4 单个刺激的固定处理顺序

实现必须按以下顺序执行，不能由调用方自由重排：

1. 读取 manifest，验证 schema、字体哈希和许可证状态；
2. 对 `text.content` 做 Unicode NFC，按 manifest 的 script/language/features 调用 HarfBuzz shaping；
3. 验证 glyph 数、cluster 顺序、缺字状态和预期单位数；不通过则写失败记录并停止该刺激；
4. 从 FreeType 获取 glyph outline 和 advance，按选定 profile 计算等比例缩放和 anchor；
5. 以固定参数渲染 8-bit 灰度 PNG，生成阈值 128 的二值 mask；不做模糊、形态学闭运算或非等比例变形；
6. 从 mask 计算核心特征，从 outline/cluster 计算单位边界和诊断特征；
7. 写入规范化 PNG、mask、特征记录、运行元数据和 SHA-256；
8. 执行 QC，只有 `passed` 才能复制到 release 目录。

渲染、测量和 QC 必须是可分别重跑的阶段；后阶段读取前阶段的哈希，不允许隐式重新渲染。

### 5.5 不应被“剥离”的因素

字体的内部比例、笔画关系、真实字间距、曲直和结构是研究对象，不能为了让图像看起来整齐而被非均匀拉伸、形态学平滑或自动重绘。背景、颜色、分辨率、裁切和文件压缩属于渲染噪声，应固定或移除。

### 5.6 混杂因素矩阵

| 可能混杂 | 第一版控制 | 仍然保留的差异 |
|---|---|---|
| 颜色、背景、压缩 | 固定黑字白底、sRGB、无有损压缩 | 不研究颜色效应 |
| 显示大小 | bbox height 匹配 | 字形宽度和内部比例仍保留 |
| 字体 hinting、抗锯齿 | 固定渲染版本和参数 | 极小的栅格化误差以敏感性分析报告 |
| kerning、连字、地区字形 | 显式 feature 和语言标签 | 脚本必需的整形仍保留 |
| 文字语义、品牌熟悉度 | 形式控制集不使用品牌名；语义状态单独记录 | 形式单位不等于语言学等价 |
| 字体设计家族 | WP3 每脚本一个基线；WP4 在同脚本内配对 | 无法声称跨脚本字体家族效应已消除 |

## 6. 八个维度的操作化

第一版输出两层字段：原始代理量 + 其所属的八维标签。每个代理量还带 applicability（direct、protocol_dependent、within_script_only、not_applicable）和缺失原因。

| 维度 | 主要代理量 | 首版可比性 |
|---|---|---|
| 几何度 | 直线/曲线比例、角点密度、轮廓凸凹度、水平/垂直对称 | 跨文字可比，但需报告表示方式 |
| 稠密度 | ink coverage、黑白比例、连通区域数、封闭空间数 | 在同一 mask 协议下可比 |
| 比例 | 外接框宽高比、单字宽度/高度、内部留白比例 | 跨文字可比；不做非均匀缩放 |
| 笔势 | 骨架曲率、方向变化、笔画宽度均值和变异 | 以同一骨架算法比较；对部分字体标为 protocol-dependent |
| 排版 | 对齐、追踪、行距、方向、字间距均值/变异 | 只适用于多单位样本 |
| 视觉重心 | 归一化质心、左右/上下平衡矩、边界偏移 | 单字和多字均可测 |
| 阅读节奏 | 间距序列变异、面积序列变异、重复周期性 | 只作为形式序列指标，不等于心理阅读速度 |
| 统一度 | 字间高度/面积/笔画宽度的变异、基线偏差 | 只适用于多单位样本 |

“阅读节奏”在第一版只表示视觉序列的结构，不声称已经测量真实阅读行为；真实阅读速度属于 WP1 的真人实验。

八维不是八个必须各自产生一个数字的“评分题”。v1 分成两层发布：

- **核心量**：ink coverage、bbox_fill_ratio、bbox aspect ratio、水平/垂直对称、质心、相邻间距均值/变异、单位面积/高度变异。这些量必须有稳定定义并进入主表；
- **诊断量**：角点密度、轮廓凸凹度、闭合空间、骨架曲率、方向变化、周期性等。只有 fixture 和稳定性关通过的诊断量才发布数值，否则保留字段、填 `null` 和缺失原因。

八维标签允许一个原始量归入多个维度，但不得因此复制列或重复计权；特征字典须注明主归属和次归属。

### 6.1 计算口径

所有比例同时保存分子、分母和归一化值；像素值不能脱离画布尺寸解释。首版采用以下口径，并在特征字典中声明二值阈值、连通性（4/8 邻域）、轮廓采样间隔、骨架算法和边界处理：

- ink coverage = 二值 mask 的前景像素数 / 画布像素数；
- whitespace ratio = 1 − ink coverage；在固定画布下同时报告 bbox_fill_ratio = ink 像素数 / bbox 面积，避免把画布留白误当作字形稠密度；
- bbox aspect ratio = ink bounding box 宽 / 高；
- straight/curve ratio = 骨架近似直线长度 / 骨架总长度；
- symmetry = 1 − 归一化图像与其水平/垂直镜像的差异；
- centroid = 前景像素质心的 x、y 除以画布宽、高；
- spacing CV = 多单位相邻 ink-bbox 间距的标准差 / 均值；
- uniformity CV = 多单位面积、宽度、高度或笔画宽度的变异系数。

所有特征记录还必须保存 `numerator`、`denominator`、单位、阈值/算法版本和 `measurement_status`。分母为零、单元素序列无法计算变异系数或骨架不稳定时写 `null` 并给出机器可读的缺失原因，不以 0 代替。

为避免实现者自行选择算法，v1 的默认参数固定为：轮廓按 2 px 等弧长重采样；转角使用前后各 5 个采样点，绝对转角大于 30° 且局部极大、相邻距离至少 8 px 才计为角点；骨架使用 Zhang-Suen 二值细化，局部方向变化以 8 邻域估计，15° 以内计为直段；笔画宽度使用二值 mask 的欧氏距离变换乘 2；周期性只对长度至少 4 的序列计算标准化自相关，取非零 lag 的最大值。参数写入配置文件，不能在代码中隐藏默认值。

多单位相邻 ink-bbox 间距保留有符号值（重叠为负），并统一除以该刺激的 ink-bbox 高度；单单位的间距、节奏和统一度字段固定为 `not_applicable`。对称度统一定义为 `1 - mean(abs(I - flip(I)))`，其中 I 为 [0,1] 的归一化前景图，水平和垂直翻转分别计算。

角点密度、轮廓凸凹度、骨架曲率和周期性必须在特征字典中写出采样间隔、平滑参数和边界处理；若尚未能给出稳定定义，该字段为 null 并标记 not_applicable，不用主观打分填充。

### 6.1.1 特征记录契约

一条 `visual_features` 记录对应一个 `(stimulus_id, extraction_run_id, normalization_profile, representation)` 四元组。每个通过渲染 QC 的刺激至少产生两条记录：`raster_grayscale`（灰度级核心测量）和 `raster_binary`（阈值 mask 核心测量）；`contour`、`skeleton` 只有在相应诊断量成功计算时追加，不能用空记录占位。记录必须包含八维主/次归属、数值单位、算法配置摘要、`measurement_status` 和逐字段 `missing_reason`。同一四元组不得产生两条互相覆盖的结果，重跑必须使用新的 `extraction_run_id`。

核心特征的最小发布集合为：`ink_coverage_ratio`、`bbox_fill_ratio`、`bbox_aspect_ratio`、`symmetry_horizontal`、`symmetry_vertical`、`straight_curve_ratio`（可计算时）、`centroid_x_norm`、`centroid_y_norm`、`inter_glyph_spacing_mean_norm`、`inter_glyph_spacing_sd_norm`、`rhythm_periodicity`（序列长度满足条件时）以及多单位的面积/宽度/高度 CV。字段不存在或不适用时必须显式为 `null`，不能删列。

### 6.2 可比性分层

特征表不允许只用一个“可比/不可比”布尔值，而要标记：

- direct：在本协议下可直接比较；
- protocol_dependent：依赖整形器、骨架或阈值协议，只能在相同运行配置内比较；
- within_script_only：只用于同一脚本/书体内部；
- not_applicable：该刺激层级没有这个概念，例如单字没有阅读节奏。

跨脚本统计默认只汇总 direct 特征；protocol_dependent 和 within_script_only 进入分层表，不进入 pooled 结论。任何汇总必须保留内容清单和有效样本数，禁止把同一 `stimulus_id` 因双重研究线标记而重复计权。

### 6.3 技术实现边界

方案只锁定可审计的处理链，不锁定某一个黑箱模型：

字体解析和文本整形使用 FontTools、HarfBuzz、FreeType；规范栅格化使用 Pillow 或等价的固定 FreeType 封装；轮廓、mask、骨架和区域统计使用 OpenCV/scikit-image。所有直接依赖和版本写入运行清单。第一版不使用通用图像审美模型，也不把模型 embedding 当作八维特征。

### 6.4 有效性声明

v1 只建立三种较低层级的证据：输入和渲染的**构念覆盖**（确实测到了声明的视觉对象）、重复运行的**计算稳定性**、以及字体/视觉专家对刺激和边界的**表面审查**。它不提供与“好看”、品牌适配、可读性或文化意义的收敛效度；这些关系必须在 WP1、WP2 或后续真人实验中单独检验。专家审查的作用是发现渲染和分类错误，不是把专家意见写回特征数值。

## 7. 质量控制和失败处理

每次运行必须自动检查：

- 字体是否覆盖全部目标 Unicode；
- Unicode 规范化和字符数是否一致；
- 图像尺寸、色彩空间、背景和 DPI；
- 字形是否为空、裁切、越界或超出画布；
- 目标字面面积与实际面积；
- 单位顺序、基线、字间距和中心线；
- 原始资产、渲染图和特征记录的哈希；
- 重复渲染是否产生相同输出；
- 不同阈值/分辨率下测量是否出现异常跳变。

另需检查字体是否含 variable axes、COLR/SVG 彩色表或 fallback glyph；必须把字体文件、字体内部版本、OpenType feature、地区/语言标签、操作系统和渲染后端版本写入 `run_manifest`。同一环境重复运行之外，固定再跑一组 1024 × 512 画布和阈值 96、160 的敏感性组合；敏感性结果不覆盖主结果，只写入 `quality_report`。

失败记录保留在数据集中并标记 needs_review，写明原因、失败阶段和是否影响哪些特征；不自动换字体、换字符或修改实验条件。任何人工修正都要留下审计记录。汇总表只使用 `qc.status=passed` 且对应特征 `measurement_status=valid` 的记录，同时发布缺失率分母，避免只看成功样本造成选择性报告。

### 7.1 发布前的三道关卡

1. **渲染 fixture 关**：先用每个脚本 2 个单位、每个汉字书体 2 个字符跑通；确认整形、地区字形、哈希和 mask 可视化没有错误。
2. **测量稳定性关**：同一输入重复运行得到相同渲染哈希；改变输出分辨率或阈值只做敏感性报告，不得出现未解释的数量级跳变。
3. **人工审查关**：至少两名具备字体/视觉经验的审查者独立检查刺激网格、字符边界和书体归类；争议样本进入 needs_review，不在代码中强行裁决。

只有通过三道关卡的记录才进入 releases。质量阈值（例如面积偏差容许范围、重复测量差异阈值）必须在正式批处理前冻结并写入 protocol 版本。fixture 只能发现实现错误和校准整数取整，不能用正式样本的特征分布事后调阈值；若必须改变阈值，升 protocol 版本并重新生成全部记录。

v1.2 的默认验收阈值为：主 profile 的 bbox 高度误差不超过 1 px；面积 profile 的实际 ink ratio 与 0.050 的绝对误差不超过 0.001；参考运行时重复渲染 PNG 和 mask 哈希必须完全一致；1024 × 512 或阈值 96/160 的敏感性运行中，核心比例量相对变化超过 5% 或绝对变化超过 0.02 时标记 `sensitivity_warning`，但不删除主结果。两名审查者必须对每个 fixture 给出独立 pass；不一致即进入 `needs_review`。

### 7.2 分析与不确定性

第一版以描述性输出为主：每个 `script × font/style × content_set × profile` 报告有效数、缺失数、均值、中位数、四分位数和逐内容值。WP4 的字体比较使用同一汉字的配对差值；WP3 跨脚本只做分层分布和效应方向展示，不进行把 8 个字符当作总体复本的显著性检验。若报告 bootstrap 或区间，重采样单位必须写明（默认按内容单位），并同时给出原始值与区间，不能把区间当作心理测量误差。

## 8. 开源仓库交付物

批准并实现后，仓库应新增以下可直接发布的成果：

    data/processed/visual_features_v1/
    ├── manifest.csv
    ├── asset_inventory.csv
    ├── rendered/
    ├── visual_features.csv
    ├── feature_dictionary_zh.md
    ├── rendering_protocol_zh.md
    ├── run_manifest.json
    ├── asset_licences.csv
    ├── quality_report.md
    ├── missing_records.csv
    ├── checksums.sha256
    └── README.md

    src/glyph_features/
    ├── cli.py
    ├── render.py
    ├── measure.py
    └── qc.py

    pyproject.toml
    uv.lock  # 或等价的、可验证摘要的锁定运行时
    configs/
    └── visual_features_v1.yaml
    data/fixtures/
    ├── content_sets.csv
    └── expected_clusters.csv

    tests/
    ├── fixtures/
    └── test_measurements.py

`configs/visual_features_v1.yaml` 必须显式包含 `protocol_version`、`schema_versions`、`canvas`、`profiles`、`foreground/background`、`shaping`、`thresholds`、`contour_params`、`skeleton_params`、`sensitivity_runs` 和 `release_policy`；代码不得依赖未写入配置的隐式常量。

文件命名固定为 `rendered/{stimulus_id}.gray.png`、`rendered/{stimulus_id}.mask.png`、`visual_features.csv` 和 `missing_records.csv`；表格按 `stimulus_id, extraction_run_id, normalization_profile, representation` 排序。任何同名文件已存在时命令必须退出并报错，不能覆盖。

固定命令入口为：

    python -m glyph_features.cli validate-config --config configs/visual_features_v1.yaml
    python -m glyph_features.cli render --config configs/visual_features_v1.yaml --manifest data/processed/visual_features_v1/manifest.csv
    python -m glyph_features.cli measure --run-id RUN_ID
    python -m glyph_features.cli qc --run-id RUN_ID
    python -m glyph_features.cli release --run-id RUN_ID

每条命令必须在日志中输出输入文件哈希、输出目录、运行 ID 和退出码；后一个阶段只接受前一阶段通过哈希校验的输出。`release` 不得在 QC 未通过或许可证状态为 `unknown` 时执行。

代码发布还必须包含 pyproject.toml（固定直接依赖和 Python 版本）、锁文件或容器摘要、可复现运行命令和代码许可证；数据和字体资产的许可证单独列出，不能用代码许可证替代。发布分为三层：公开层（schema、代码、特征表、低风险 PNG、日志和许可证）；受限层（不能再分发的字体及其获取脚本/哈希）；不发布层（原始商业 Logo、个人数据和未获许可图像）。实现前需对现有 schema 做一次有版本记录的增量更新，目标版本为 `stimulus.schema 1.1.0` 和 `visual_features.schema 1.1.0`：

- stimulus schema 增加 content_set、render_profile、整形/锚点配置和实际资产角色；
- visual feature schema 增加八维归属、代理量单位、适用性、缺失原因和运行配置字段；
- human rating、cultural narrative 和 source schema 保持字段含义不变。

已有字段不改含义，旧记录可以通过显式迁移脚本转换，禁止分析代码按列名猜测版本。

## 9. 验收标准

项目完成第一版的条件是：

1. 每个公开刺激都有完整 manifest、来源、许可证状态和资产哈希；
2. 任何人按 README 的单条命令、在项目声明的参考容器或锁定运行时中，均可重新渲染并生成同一版本的特征表；原生环境若使用不同栅格后端，只能在质量报告声明的容差内不同；
3. 每个八维都有明确的代理量、单位、适用范围和测量定义；
4. 同一输入重复运行的渲染哈希和特征结果稳定；
5. 质量报告列出失败样本、缺失字符、不可比指标和归一化敏感性；
6. 仓库文档明确声明：这些是视觉测量，不是审美真值，也没有真人评分结论；
7. 不包含未获许可的 Logo 图像、个人数据或模拟受试者评分。
8. 任何汇总均能追溯到有效 stimulus_id，重复复用的 stimulus 不被重复计权，失败样本和缺失率随 release 一起发布。

## 10. 主要风险与处理

| 风险 | 处理 |
|---|---|
| 不同文字系统的字体设计并非真正同源 | 将“跨文字可比”标为协议结论，不宣称字体家族效应已消除 |
| 骨架算法对不同书写系统偏置 | 同时保存轮廓级代理量，报告算法适用性 |
| 面积匹配抹去真实密度差异 | 保留自然版本和敏感性版本，不只发布一个数字 |
| 字体许可证或奖项图片不可再分发 | 只发布元数据/哈希，受限资产由用户自行获取 |
| 八维概念被误读为心理学量表 | 文档明确区分理论维度、视觉代理量和真人感知变量 |

## 11. 实施顺序和停止条件

批准后按以下顺序实施，每一步都产生可审查中间产物和明确失败码：

1. **资产登记（`ASSET_*`）**：登记 4 个 WP3 基线和 4 个 WP4 范例字体，验证许可证、静态实例、Unicode 覆盖和 SHA-256；任何许可证不清、fallback 或缺字停止，不进入渲染。
2. **配置与 fixture（`FIXTURE_*`）**：提交 `visual_features_v1.yaml`、内容清单和预期 cluster 表；只渲染每脚本 2 个单位和每书体 2 个汉字，验证 shaping、地区字形、320 px 高度、0.050 面积目标、anchor 和视觉网格。
3. **协议冻结（`PROTOCOL_*`）**：由 fixture 发现的实现问题只能通过升版本修复；冻结 manifest、配置和依赖锁文件，生成 160 个条件格，并按字体文件同一性决定 140 或 160 个唯一 stimulus。
4. **批量渲染（`RENDER_*`）**：按固定处理顺序生成 PNG、mask、单位边界和哈希；任何越界、空 glyph、cluster 不符或归一化失败只写 `missing_records.csv`，不自动修复。
5. **特征提取（`MEASURE_*`）**：先生成每个四元组的原始核心/诊断量、单位、适用性和缺失原因，再生成描述性汇总；不生成综合审美分数或结果驱动特征。
6. **QC、发布与复核（`QC_*`/`RELEASE_*`）**：执行重复性、分辨率/阈值敏感性、许可证和人工审查；仅 `passed` 记录进入 release，生成 `quality_report.md`、`checksums.sha256` 和版本化归档。

失败码至少包括：`ASSET_LICENSE_UNKNOWN`、`ASSET_MISSING_GLYPH`、`RENDER_FALLBACK_DETECTED`、`RENDER_CLUSTER_MISMATCH`、`RENDER_OUT_OF_BOUNDS`、`NORMALIZATION_FAILED`、`MEASURE_ZERO_DENOMINATOR`、`MEASURE_SKELETON_UNSTABLE`、`QC_HASH_MISMATCH`、`QC_HUMAN_REVIEW_REQUIRED`。失败码是枚举，不用自由文本替代；新增失败码必须升协议版本。

任一关卡发现无法解释的渲染差异、字体覆盖缺失、许可证问题或单位无法分段，就停止扩展样本，先修订协议并增加版本号。

## 12. 需要批准的具体决定

请审批以下六项。表中的“默认决定”是本方案建议的 v1 基线；任一项改变都要在实现前写入协议版本。

| 决策 | 默认决定 | 不批准/改变后的影响 |
|---|---|---|
| 范围 | 4 个文字系统 + 4 个汉字字体实例范例 | 需要重算刺激矩阵、字符覆盖和比较边界 |
| 字体来源 | 只用许可证可核验、可研究使用的 Noto/Source Han 或同等开放字体 | 受限字体只能进入受限层，不能承诺一键复现 |
| 归一化 | `bbox_height_matched` 主分析，`ink_area_matched` 敏感性分析，目标分别为 320 px 和 0.050（v1.2.0） | 若只留一种 profile，将失去对显示尺寸/自然密度混杂的敏感性检查 |
| 刺激类型 | 只做形式控制集，不纳入真实品牌 Logo 或商业截图 | 结论只能覆盖控制集，不能外推到真实品牌生态 |
| 八维输出 | 保留八维上层框架，发布可解释代理量，不生成综合审美分数 | 若要求综合分数，必须另立心理测量协议和真人验证，不属于 v1 |
| 许可证分层 | 代码、元数据、字体资产分别管理；受限字体发布哈希和获取说明 | 无法满足再分发的资产不进入公开层，发布规模可能减少 |

审批通过后，下一阶段才开始修改 schema、实现渲染/测量代码、制作样本并生成质量报告。

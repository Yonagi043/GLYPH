# 商业字体视觉感知问卷

## 研究说明

研究对象：包装与招牌中的拉丁文字、汉字、韩文、片假名

本问卷关注既定因素：`aesthetic`、`premium`、`modern`、`trustworthy`、`visual_clarity`、`recognition`、`unfamiliarity`。母语、文字熟悉度和设计经验作为背景变量。

你不需要认识、读出或理解图片中的文字。请先根据字形的轮廓、粗细、比例、节奏、排列和与整体画面的关系进行判断。

### 1. 熟练使用的文字系统（可多选）

- 拉丁文字
- 汉字
- 韩文
- 片假名/日文假名
- 其他：______
- 无法判断/不愿回答

### 2. 每种文字系统的经验矩阵

请分别评价你对以下文字系统的经验。每项使用 1–7 分；另有“无法判断/不适用”。

| 文字系统 | 阅读熟练度 | 书写熟练度 | 日常接触频率 | 商业视觉接触频率 | 看到该文字时的熟悉度 |
|---|---:|---:|---:|---:|---:|
| 拉丁文字 | 1–7 | 1–7 | 1–7 | 1–7 | 1–7 |
| 汉字 | 1–7 | 1–7 | 1–7 | 1–7 | 1–7 |
| 韩文 | 1–7 | 1–7 | 1–7 | 1–7 | 1–7 |
| 片假名 | 1–7 | 1–7 | 1–7 | 1–7 | 1–7 |

1 = 完全没有/完全不熟悉；4 = 中等；7 = 非常熟练/非常熟悉。

### 3. 设计与商业视觉经验

- 设计、字体排印或视觉艺术训练：无 / 入门 / 中等 / 专业
- 书法、手写字或 lettering 训练：无 / 入门 / 中等 / 专业
- 每周接触包装、招牌或广告视觉的频率：几乎没有 / 偶尔 / 经常 / 几乎每天

## 正式刺激说明

每张图片只显示一个商业视觉刺激。刺激条件在后台记录，不向参与者显示。

后台字段示例：

```text
presentation_id
stimulus_id
work_id
stimulus_script: latin | han | hangul | katakana
stimulus_condition: semantic_real | low_semantic_control
context: packaging | signage
font_style_family
```

同一参与者不同时看到同一作品的真实版本和控制版本，以减少记忆和直接比较效应。

## 每个刺激的评价题

### A. 七个核心因素评分

请暂时不要考虑文字的意思；如果你认识这些文字，也请先只根据其视觉形式作答。

以下各题使用 1–7 分：1 = 完全不同意，4 = 中立，7 = 非常同意；另有“无法判断”。

1. `aesthetic`：这个视觉形式整体上是美观的。
2. `premium`：这个视觉形式看起来精致、讲究，具有高级感。
3. `modern`：这个视觉形式看起来具有现代感。
4. `trustworthy`：如果用于品牌，这个视觉形式给人可信、可靠的感觉。
5. `visual_clarity`：不考虑是否认识文字，字形轮廓、结构和排列关系在视觉上清楚。
6. `recognition`：你能读出或识别图片中的文字吗？（1 = 完全不能，7 = 完全能）
7. `unfamiliarity`：这种文字形式对你来说陌生吗？（1 = 完全不陌生，7 = 非常陌生）

### B. 商业联想

请把图片想象成一个真实品牌的包装正面或店铺招牌。

8. 这个视觉形式看起来专业。
9. 这个视觉形式让品牌显得可信、可靠。
10. 这个视觉形式让品牌显得有品质。
11. 这个视觉形式让品牌显得具有较高档次。
12. 这个视觉形式适合商业品牌使用。
13. 这个视觉形式容易让人记住品牌。

### C. 识别、熟悉与语义影响

14. 你能读出或识别图片中的文字吗？（1–7；1 = 完全不能，7 = 完全能）
15. 你对这种文字形式熟悉吗？
16. 你理解图片中文字表达的意思吗？
17. 你刚才的评价有多大程度受到“看懂文字内容”的影响？

- 完全没有影响
- 有一点提高
- 有明显提高
- 有一点降低
- 有明显降低
- 我无法判断

18. 如果把文字替换为你完全看不懂、但保留相同字数和类似排版的文字，你认为自己的审美评价会：

- 明显降低
- 略微降低
- 基本不变
- 略微提高
- 明显提高
- 无法判断

### D. 审美原因
19. 你在评价这张图片时，最主要注意了哪些因素？可多选。

- 字形轮廓
- 粗细和比例
- 字距、行距或排列节奏
- 与图形/颜色的协调
- 现代感或传统感
- 高级感或品质感
- 是否容易识别
- 文字含义或语言联想
- 其他：______


### Persona 注入模板

```json
{
  "persona_id": "PXX",
  "age_band": "25-34",
  "region_context": "居住在文字环境多样的城市",
  "design_training": "none | basic | professional",
  "commercial_visual_exposure": "low | medium | high",
  "script_exposure": {
    "latin": {"reading": 6, "writing": 5, "commercial_exposure": 6},
    "han": {"reading": 5, "writing": 4, "commercial_exposure": 5},
    "hangul": {"reading": 2, "writing": 1, "commercial_exposure": 2},
    "katakana": {"reading": 2, "writing": 1, "commercial_exposure": 2}
  }
}
```

智能体提示中应明确：

- 先完成非语义视觉评价，再回答识别和熟悉度；
- 不因“不认识文字”自动给低分；
- 不因 persona 的地区背景预设喜好；
- 每个评分都输出数值和一句简短理由；
- 记录模型版本、采样参数、完整 prompt 和解析失败。

每个 persona 建议重复采样 20 次以上。分析单位不是单次回答，而是 `persona × stimulus × item` 的评分分布。

## 分析说明
### 推荐模型表达

```text
rating ~ stimulus_script
       + stimulus_condition
       + stimulus_script × familiarity
       + recognition
       + design_training
       + commercial_exposure
       + (1 | participant_or_persona)
       + (1 | stimulus)
```

真实研究中，`stimulus_condition = low_semantic_control` 的刺激必须有可追溯的制作规范和人工质量检查；当前 branch 的 synthetic fixture 只能用于工程测试，不能直接作为真人结论。

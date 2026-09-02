# 10项审美指标 CV 程序（MVP）

这是一个可运行的第一版图像特征提取程序：输入一张字体、书法或 Logo 图片，生成 A/B/C 三个分析通道，提取 10 项指标，输出 JSON、CSV 以及中间可视化图。

详细的分项公式和总分来源见 [SCORING.md](SCORING.md)。

## 安装

```bash
cd /root/lijie_aesthetic_cv/cv_program
python -m pip install -r requirements.txt
```

## 单张图片运行

```bash
python aesthetic_cv.py \
  --input /path/to/image.png \
  --output /path/to/result
```

输出文件：

```text
result/result.json       # 所有原始特征、10项分数和总分
result/result.csv        # 便于批量汇总
result/debug.png         # 前景、骨架、中心线等检查图
```

## 总分的定义

程序当前没有人工盲评校准数据，因此输出的是“规则代理分（proxy score）”，不是已经验证的客观高级感。

1. 每个维度先从其原始 CV 特征生成 0—100 的分项分。
2. 默认 10 个维度等权（每项 0.1）；不适用的维度不计入分母。
3. 总分是适用维度的加权平均：

\[
S=\frac{\sum_j a_j w_j s_j}{\sum_j a_j w_j}
\]

其中 `s_j` 是第 `j` 项 0—100 分，`w_j` 是权重（默认相等），`a_j` 是适用标记（适用为1，不适用为0）。

以后接入你的 SFT/盲评数据时，应通过 AutoResearch 搜索并替换 `weights` 和每项的分数变换；不要把当前默认分数当作已被验证的“高级感真值”。

## 处理边界

- A 通道保留原画布，主要用于平衡、比例、章法。
- B 通道等比例归一主体，主要用于对称、统一、笔法、结体、气韵代理。
- C 通道保留灰度，主要用于墨法。
- 程序不读取奖项、作者、品牌或文件名作为视觉分数输入。
- 对没有灰度层次的黑白图，墨法返回 `N/A`，不会无故扣分。

## 批量运行

```bash
python aesthetic_cv.py --input-dir /path/to/images --output /path/to/results
```

每张图一个子目录，并额外生成 `summary.csv`。

## 自检

```bash
cd /root/lijie_aesthetic_cv/cv_program
python -m unittest -v
```

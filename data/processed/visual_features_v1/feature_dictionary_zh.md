# GLYPH v1 特征字典

所有特征来自固定 2048 x 1024、sRGB 黑字白底图像；二值记录使用阈值 128，灰度记录使用阈值 254。比例同时保留分子、分母、单位、适用性和缺失原因。

核心量包括 `ink_coverage_ratio`、`whitespace_ratio`、`bbox_fill_ratio`、`bbox_aspect_ratio`、水平/垂直对称、归一化质心和多单位间距/一致性 CV。`straight_curve_ratio` 使用 Zhang-Suen 骨架：8 邻域骨架边计长度，局部二邻域方向转角不超过 15 度的长度计为直段。

`connected_component_count` 和 `closure_count` 是 mask 区域计数；`unit_area_cv` 使用各单位边界内的实际前景像素面积。单单位没有排版、节奏或统一度概念时字段为 `null`，并写入 `MEASURE_NOT_APPLICABLE`。序列少于四个间隔时周期性为 `null`，并写入 `MEASURE_SEQUENCE_TOO_SHORT`。

这些字段是可解释的视觉代理量，不是综合审美分数，也不代表真人可读性或审美判断。

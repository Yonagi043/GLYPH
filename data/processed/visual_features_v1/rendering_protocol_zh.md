# GLYPH v1 渲染协议

协议版本：`visual_features_v1.2.0`。文本先做 Unicode NFC 和 HarfBuzz cluster 校验，再以固定 Pillow/FreeType BASIC 后端栅格化；`-liga`、`-kern`，黑字白底、sRGB、96 DPI、2048 x 1024 画布，二值阈值 128。单单位 ink bbox 中心为 (1024, 512)，多单位水平中心为 x=1024、baseline 为 y=640。

`bbox_height_matched` 等比例缩放二值 ink bbox 高度到 320 px；`ink_area_matched` 等比例缩放二值 ink 面积到画布的 0.050。两个目标是在冻结矩阵和画布下逐刺激可行性审计后确定的保守值。任何缺字、cluster 不符、越界或目标无法满足的条件都保留为固定失败码，禁止 fallback、换字符、非等比例变形或覆盖既有 run。分辨率敏感性运行按画布比例同步缩放 bbox 高度目标和 anchors，面积比例保持不变。

当前栅格后端不提供 libraqm；HarfBuzz 用于协议级整形和缺字/cluster 验证，Pillow BASIC 用于确定性绘制，并在 run manifest 中记录实现边界。

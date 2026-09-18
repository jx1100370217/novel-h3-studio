# 上游致谢与范围

本地工作流的视频续接使用 NikoDemon80 的 ComfyUI-H3-Motion-Context，版权和 GPL-3.0 条款见 `vendor/ComfyUI-H3-Motion-Context/LICENSE`。

小说制作流程参考 ArcReel 的资产类型、角色衍生身份与内容/视觉分离设计。其源代码、AGPL-3.0 许可证和 NOTICE 保留于 `vendor/ArcReel`。`novel_h3/arcreel.py` 是本工程独立实现的适配器，并非 ArcReel 官方集成。

视频推理使用 Saganaki22 的 ComfyUI-VDN-H3，固定 v1.5.2 独立副本，Apache-2.0 条款见 `vendor/ComfyUI-VDN-H3/LICENSE`。模型权重不随代码重新授权。

固定版本与链接见 `upstream.json`。本工程未修改这些上游源码；完整部署 ArcReel 或传播修改版时，须继续保留并履行上游相应许可证要求。

小说正文、参考视频和生成素材没有随代码被赋予开源许可；代码许可不改变其各自权利状态。

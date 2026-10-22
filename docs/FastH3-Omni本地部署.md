# FastH3 Omni：FastVideo NVFP4 QAD

本仓库的 FastH3 Omni 使用 FastVideo 原生运行时。旧 FastH3 Omni ComfyUI INT8 ConvRot 入口已移除；VDN 和基础 H3 的 ComfyUI 组件保留。

## 固定组件

- 模型：`FastVideo/FastH3-Omni-NVFP4-QAD`
- 模型修订：`f01e6a23ac6066aa9eb622cf94b6259442e70ec2`
- FastVideo：`fa2d1324c60050cd65209c6aaeac470e7fb412f5`
- Python 3.12、PyTorch 2.12.0+cu130、固定源码构建的 fastvideo-kernel 0.3.5。
- 隔离环境：`runtime/fastvideo-venv`；源码：`runtime/FastVideo`。
- 模型目录：`runtime/models/FastH3-Omni-NVFP4-QAD`，下载清单：`runtime/fastvideo-model-download.json`。
- 隔离 CUDA 编译器：NVCC/CRT/NVVM 13.0.88、CCCL 13.0.85；另需 Ninja 和 CMake。不修改系统驱动。

官方 5090 配方使用 NVFP4 线性层、FP4 稀疏视频注意力和 FP8 条件前缀，启用 two-level P 与 K smoothing，固定 8 次 PDD 前向、guidance 1、视频/音频 shift 12/3。本机原生 768P 开启官方逐层卸载（含大型权重 buffer，常驻块数 0）、VAE 卸载、8192-token 前馈分块和 expandable_segments，CPU 不额外保留 pinned swap 镜像。不会自动更换模型或降低分辨率。

本机 glibc 2.42 与 CUDA 13.0 的 rsqrt/rsqrtf 异常声明冲突已在隔离 SDK 中对齐；只修改两个声明，补丁记录在 `runtime/fastvideo-migration/cuda-header-compat.patch`。CUDA wheel 的 lib 目录通过隔离环境中的 lib64 符号链接兼容标准工具链布局。

## 服务

`services/novel-h3-fastvideo.service` 启动 `start_fastvideo.py`，复用官方 5090 服务配方和共享 44GiB 模型内存隔离，监听 `127.0.0.1:8195`。本地媒体访问限于仓库的 `projects/`、`runtime/`。

官方 FastH3 extra 选择同一 checkout 的内核源码；不能只使用可能缺少最新稀疏接口的已发布轮子。通过 `UV_TORCH_BACKEND=cu130 uv pip install -e "runtime/FastVideo[fasth3]"` 安装固定源码和匹配内核。安装 `cuda-toolkit[nvcc,cccl]==13.0.2` 后，明确锁定 `nvidia-cuda-crt==13.0.88` 和 `nvidia-nvvm==13.0.88`，避免跨小版本组件。

`scripts/prepare_fastvideo_adaln.py MODEL_DIR` 使用官方 PDD 时序和时间嵌入，逐层预计算调制表，使 32GB 显卡不必常驻约 26GB 的 AdaLN 投影。请求记录模型文件和调制表 SHA-256。

服务使用 `MALLOC_ARENA_MAX=2` 和固定 64KiB mmap/trim 阈值，便于编码器反复卸载时归还 CPU 内存；仍受共享 40GiB 软阈值、44GiB 硬上限约束。

启动：`systemctl --user start novel-h3-fastvideo.service`。
检查：`python3 studio.py --project /absolute/project doctor`。
完整章节：`python3 produce_cinema_chapter.py /absolute/project /absolute/project/chapter_plan.json --seed 2026102201`。

官方默认验证画幅为 832×480，API 单帧上限为 1,032,192 像素。本项目正式章节使用 1344×768 原生生成、24fps，保留 768P 高度，不缩小后放大。768P 多参考和长片段运行结果以实际回执为准。

## 提示词与章节

每镜提供 `ref2va_sections`，依次为 `subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。编译器绑定素材标签并拒绝未上传引用、中文描述正文、非标准保留关系、缺少任务前缀或遗漏对白。中文仅在 `<d>[Chinese] ...</d>` 内，精确文字由后期合成。

完整原文、影视化交接与叙事检查仍是生成前提。FastVideo 生成原生联合音画；没有独立声线参考时，由提示词描述角色声音，不把 TTS 后配音冒充原生生成。逐镜保留请求、作业 ID、输出哈希、原始音轨及检查。首版完整保留镜头，语音异常作为审片警示，不自动重拍，也不标记人审通过。

上游指南：[FastH3 OmniRef](https://github.com/hao-ai-lab/FastVideo/blob/main/docs/inference/fasth3_omniref.md)。模型遵循 MiniMax H3 Community License。

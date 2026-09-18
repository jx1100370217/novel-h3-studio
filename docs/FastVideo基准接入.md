# FastVideo FastH3-8-Step-V2 接入说明

工作台保留生产用 VDN-H3 Turbo，并新增隔离的 FastVideo FastH3-8-Step-V2 基准路径。基准路径使用官方 FastVideo-FastH3-Comfy 提供的 INT8 convrot 权重，通过同一套 H3 音视频解码和保存节点执行；它不修改生产配置、镜头指纹或已生成视频。

同时接入了官方 FastVideo/VSA-H3 runner：`novel_h3/fastvideo_runner.py` 与 `scripts/run_fasth3_official.py`。runner 使用 FastVideo 的 `VideoGenerator`、VSA-H3 attention backend、DMD 8-step schedule、显存采样和 MP4 输出回写。启动前会严格检查 Diffusers 目录、三组权重索引、所有 shard 和 `checkpoint_content.json`；Comfy 单文件 repack 或未完成下载会直接阻止运行，避免把兼容路径误标成官方后端。

FastH3-8-Step-V2 官方蒸馏配方是 T2AV，视频调度偏移 10、音频调度偏移 3、8 次 transformer 前向。当前小说镜头是 Ref2VA，因此基准会取同一镜头的动作描述、运镜、分辨率、帧数和种子，改成不发送参考图的 T2AV 等效请求，只比较生成速度。这个对比不能作为 Ref2VA 画面质量等价结论；生产路径仍使用 VDN-H3。

基准结果写入 `projects/rendao-wuji/benchmarks/fasth3/<镜头>/`，包括两份视频、执行单、原始 Comfy prompt、单项耗时和 `comparison.json`。切换模型前必须暂停视频队列并重启 ComfyUI，避免模型缓存污染；基准完成后再次重启 ComfyUI，再恢复生产队列。

权重文件：`comfyui-minimax-h3/models/diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors`。FastVideo 原仓库仅作为实现和版本来源登记在 `config.json`，不把原始约 148GB 模型快照复制到生产目录。

## RTX 5090 官方 VSA 候选路径

不能把 RTX 5090 判定为“官方后端不支持”。FastVideo 官方卸载文档明确建议单 GPU 使用 `dit_layerwise_offload`，模型不适合一次性加载时使用 `lazy_module_load`；FastH3 配方文档也明确指出，没有 `sm100a` 扩展时可以使用 `--vsa-kernel triton`。本机的 runner 已切换为这一组合：单卡、`sp_size=1`、VSA tile 64、稀疏度 0.8、Triton、DiT 层级卸载、惰性组件加载、关闭 FA4/编译融合。

当前尚未执行官方 VSA 生成，是因为本机的官方模型目录仍缺少 `checkpoint_content.json`、Transformer/Text Encoder/VAE 权重索引及对应完整 shards。官方快照的权重文件约 148GB，且本机是 32GiB 显存、61GiB 物理内存；这说明“当前无法完成可靠的官方 smoke test”，不等同于“RTX 5090 硬件绝对跑不了”。补齐完整 Diffusers 快照并确认 FastVideo CUDA 依赖后，才可以进行真实单镜头测试。

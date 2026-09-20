# FastVideo FastH3-8-Step-V2 ComfyUI 基准

本项目保留 FastH3-8-Step-V2 的 **ComfyUI 兼容基准路径**，用于和当前生产引擎做同一镜头的速度对比。官方 VSA-H3 runner、Diffusers 多分片快照和 Triton 运行入口已移除；当前生产队列不会调用 FastH3。

## 权重来源

- 原始模型：[FastVideo/FastVideo-FastH3-8-Step-V2](https://huggingface.co/FastVideo/FastVideo-FastH3-8-Step-V2)
- ComfyUI 兼容文件：[FastVideo/FastVideo-FastH3-Comfy](https://huggingface.co/FastVideo/FastVideo-FastH3-Comfy)
- 本基准需要的文件：`diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors`

下载到 ComfyUI 根目录：

```bash
hf download FastVideo/FastVideo-FastH3-Comfy \
  diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors \
  --local-dir /home/jx/codes/comfyui-minimax-h3
```

该单文件是原始 FastH3-8-Step-V2 的 ComfyUI repack，不是官方 VSA Diffusers 快照。基准复用当前 ComfyUI 已安装的 H3 文本编码器、音频 VAE、视频 VAE、Motion Context 和保存节点。

## 运行方式

项目配置中的 `fastvideo` 段只用于基准，不会切换生产引擎：

```json
{
  "model_filename": "fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors",
  "model_variant": "int8_convrot",
  "production_enabled": false,
  "input_mode": "fl2va",
  "scheduler_shift_video": 10.0,
  "scheduler_shift_audio": 3.0
}
```

运行前暂停视频 worker，确保 ComfyUI 队列为空；运行后重新启动生产服务：

```bash
python3 scripts/run_fasth3_benchmark.py \
  --project /absolute/project/path \
  --episode chapter_s0004 \
  --shots C4D001,C4D002,C4D003 \
  --case fast
```

基准会把镜头转换为 FastH3 可接受的无参考图文本输入，只比较同一镜头的文本、帧数、分辨率和种子下的速度；不能把结果当作生产 Ref2VA 画面质量等价结论。输出写入项目 `benchmarks/fasth3/`，不纳入 Git。

## 预检

```bash
python3 studio.py --project /absolute/project/path doctor
```

预检需要确认 ComfyUI 可达、`fastvideo` 单文件存在、基础 H3 节点和 VAE 可用。FastH3 基准只走 ComfyUI 兼容 graph；项目不再检查或加载官方 VSA 权重、Triton kernel 或 FastVideo Python runtime。

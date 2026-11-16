# MiniMax Music 3 本地部署

本机用 **ComfyUI 核心节点 + Comfy-Org 重打包权重** 运行 MiniMax Music 3。
模型可从 ComfyUI 工作流模板 `Audio > MiniMax Music 3` 直接调用。

## 1. 模型文件

权重来自 `Comfy-Org/MiniMax-Music-3`（原始模型 `MiniMaxAI/MiniMax-Music3`）：

| 文件 | 大小 | 放置目录 |
|---|---:|---|
| `minimax_music3_dit_fp16.safetensors` | 4.9 GB | `models/diffusion_models/` |
| `minimax_music3_text_encoder_pruned_int8_convrot.safetensors` | 9.2 GB | `models/text_encoders/` |
| `minimax_music3_dav.safetensors` | 0.22 GB | `models/vae/` |

本机路径（ComfyUI 安装目录）：

```text
/home/jx/codes/comfyui-minimax-h3/models/
```

低显存可把 DiT 换成 `minimax_music3_dit_int8_convrot.safetensors`（2.5 GB），
并开启 tiled decode；32 GB 显存使用 fp16 DiT 即可。

## 2. 启动服务

先释放其他占显存的任务，再启动一个专用 ComfyUI：

```bash
cd /home/jx/codes/comfyui-minimax-h3
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  .venv/bin/python main.py \
  --listen 127.0.0.1 --port 8188 \
  --disable-all-custom-nodes --disable-api-nodes \
  --cache-ram 8 --reserve-vram 1
```

模型在第一次生成时加载，空闲时会保留约 5 GB 显存。需要给 FastH3 或其他
任务让路时，直接停止该进程即可。

## 3. 生成

仓库脚本：

```bash
python scripts/minimax_music3_generate.py \
  --caption projects/<id>/assets/music/prompts/painting.txt \
  --lyrics projects/<id>/assets/music/prompts/instrumental.txt \
  --duration 110 --seed 9201 \
  --prefix <project>/painting
```

输出在 ComfyUI 的 `output/<prefix>_00001.flac`。

### 纯器乐提示

MiniMax Music 3 是歌曲模型，必须明确写 **no vocals / no singing / no choir**
并在 lyrics 里使用 `[Instrumental]` 段。示例 lyrics：

```text
[Intro]
[Instrumental]
[Instrumental]
[Instrumental]
[Solo]
[Instrumental]
[Instrumental]
[Outro]
```

`max_duration` 只是上限，模型可能提前结束；需要 90 秒以上时，多写几个
`[Instrumental]` 段落，并在 caption 里写 “long-form, sustain the mood,
do not resolve or end early”。

## 4. 本机验证

- 显卡：RTX 5090 32 GB；fp16 DiT + int8 文本编码器可完整加载。
- 生成速度：15 秒音频约 13 秒；100 秒音频约 40–60 秒。
- 输出：44.1 kHz / 16-bit 立体声（ComfyUI 节点），保存为 FLAC。
- 生成的 stem 用 AST 音频分类检查过，无 Singing 标签；`[Instrumental]`
  提示可稳定得到纯器乐。

## 5. 许可

ComfyUI 文档写明 MiniMax Music 3 权重使用 **MiniMax-Music3 Community
License**：年收入低于 2000 万美元可商用；超过该门槛需要 MiniMax 商业许可。
发布前按实际主体确认许可，不要把模型名写进观众向发布文案。

## 6. 本片 A/B 产物

《画壁》用同一套镜头、卡片、cue 位置和侧链参数做了两版：

- `exports/huabi_final_ace.mp4`：ACE-Step 1.5 配乐
- `exports/huabi_final_minimax.mp4`：MiniMax Music 3 配乐
- `exports/score_compare/`：两版全片、画中段、片尾段的 MP3 对比

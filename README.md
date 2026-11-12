# novel-h3-studio

本地影视化制作仓库：**OpenMontage `cinematic` 工作流 + FastH3-Omni NVFP4 QAD 本地音画生成 + 中文 Backlot 制片看板**。

当前默认生产路径不是旧版 `novel-cinematic`，而是 OpenMontage 的 `cinematic` 流水线：

```text
research → proposal → script → scene_plan → assets → edit → compose → publish
```

每个阶段都有 checkpoint、正式产物和导演技能。工作流入口是 `studio.py`，阶段规范以
[`openmontage/AGENT_GUIDE.md`](openmontage/AGENT_GUIDE.md) 为准。

## 工作台

Backlot 中文制片看板直接读取 `projects/<id>/` 的阶段检查点、剧本、故事板、镜头版本与决策日志。

![片场 ·《聊斋志异·王六郎（Cinematic）》工作台：8 个阶段、剧本、故事板、决策日志与渲染版本](docs/images/backlot-production.jpg)

剧本审查视图：场次、台词归属与时间窗口。

![剧本审查：场次、角色台词与时间窗口](docs/images/backlot-script.jpg)

## 当前项目

```text
projects/liaozhai-wangliulang-cinematic/
├── project.json                  # pipeline_type: cinematic
├── config.json                   # FastH3 模型服务配置（模型路径/服务地址）
├── artifacts/                    # script / scene_plan / edit_decisions / render_report
├── assets/requests.json          # 45 个 FastH3 Ref2VA 请求（源数据）
├── assets/shots/                 # 每镜 native.mp4 + receipt + prompt
├── prompts/S01.txt ... S45.txt   # 可读的六段式提示词
├── public/
│   ├── props.json                # Remotion 时间线 / 字幕 / 片段
│   ├── shots/                    # Remotion 读取的镜头
│   └── fonts/                    # 毛笔字体
├── Composition.tsx / Root.tsx    # 项目本地 Remotion 合成
├── exports/wangliulang_final.mp4 # 成片
└── checkpoint_*.json             # 各阶段状态
```

参考素材路径以项目 `assets/requests.json` 里的 `reference_image_paths` /
`reference_audio_paths` 为准。FastH3 服务只接受其 `media_roots` 下的文件；默认是
`projects/` 和 `runtime/`，也可以用 `FASTVIDEO_EXTRA_MEDIA_ROOTS` 追加目录。

## 快速开始

### 环境

```bash
.venv-openmontage/bin/python studio.py doctor
```

### 初始化一个 cinematic 项目

```bash
.venv-openmontage/bin/python studio.py init my-film \
  --title "我的短片" --pipeline cinematic
```

### 启动中文看板

```bash
.venv-openmontage/bin/python studio.py serve --port 4751
# 浏览器打开 http://127.0.0.1:4751/
```

Backlot 默认中文；阶段、剧本、分镜、渲染、决策和检查点都从项目文件读取。

### 启动 FastH3 服务

```bash
runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-wangliulang-cinematic
```

服务监听 `127.0.0.1:8195`，输出 1344×768 / 24fps，带 H3 原生对白与音效。

### 按请求逐镜生成

`assets/requests.json` 是 cinematic 项目的镜头源；每项包含六段式 prompt、参考图/声线、
帧数、seed 和输出路径。

```bash
.venv-openmontage/bin/python scripts/render_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic \
  --force --restart-every 1
```

脚本只做批量调度：实际生成由 OpenMontage 的 `fastvideo_h3_video` 工具完成。每次成功后
会同步 `assets/shots` 与 `public/shots`，并更新 `assets/take_manifest.json` 和 checkpoint。

### 镜头 QC、字幕对齐与剪辑

```bash
# 每镜 LUFS / 真峰值 / 对白转写 → artifacts/asset_qc.json
.venv-openmontage/bin/python scripts/qc_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic

# Whisper 词级对齐 → artifacts/asr.json
.venv-dialogue/bin/python scripts/align_cinematic_dialogue.py \
  --project projects/liaozhai-wangliulang-cinematic

# 由 QC + ASR + edit_decisions 生成 props / edit_timing / subtitles.srt
.venv-openmontage/bin/python scripts/build_cinematic_edit.py \
  --project projects/liaozhai-wangliulang-cinematic

# 检测并裁切 H3 原生字幕镜头（只改 public/shots，保留 assets/shots）
.venv-dialogue/bin/python scripts/audit_cinematic_assets.py \
  --project projects/liaozhai-wangliulang-cinematic --crop
```

### 音乐床与混音

```bash
# 按 assets/music/cues.json 生成音乐床（-30 LUFS，4 个 cue）
.venv-openmontage/bin/python scripts/build_cinematic_music_bed.py \
  --project projects/liaozhai-wangliulang-cinematic
```

### 合成

Remotion atelier 只渲染画面 + H3 原生音轨，输出 `renders/wangliulang_picture.mp4`：

```bash
.venv-openmontage/bin/python studio.py tool video_compose @compose_picture_payload.json
```

然后把音乐床混入并重新封装：

```bash
# 提取原生音轨 → 每镜 gain → audio_mixer full_mix（ducking）→ alimiter 封装
.venv-openmontage/bin/python scripts/mix_cinematic_audio.py \
  --project projects/liaozhai-wangliulang-cinematic
```

最终文件是 `renders/wangliulang_final.mp4`，交付副本写到 `exports/wangliulang_final.mp4`。

### 最终校验

- `ffprobe`：1344×768 / 24fps / H.264 + AAC 192k
- `qc_cinematic_shots`：每镜 LUFS / 对白文本比
- `align_cinematic_dialogue`：Whisper 词级字幕对齐
- `subtitle_qc`：没有双层字幕；S12/S15/S25/S30 原生字幕已裁切
- `audio_mix_report`：音乐 bed、ducking、最终响度 / 真峰值
- `final_review`：画面、音频、字幕、runtime 合同

## 工作流原则

1. **源数据唯一。** cinematic 项目的 `assets/requests.json` 和 `prompts/S*.txt` 是镜头源；不要在
   version 脚本里另造一套 prompt。
2. **阶段化。** 按 OpenMontage cinematic 阶段推进，不跳 gated stage；每阶段写 checkpoint。
3. **原生音频。** 对白和现场音效来自 H3 原生音轨；音乐只做 bed，并在对白下 duck。
4. **项目本地合成。** 成片由项目自己的 Remotion composition 渲染；不要用通用 FFmpeg
   slideshow 替代。
5. **中文看板。** Backlot 是中文 observer/approval UI；新增标签保持中文。
6. **旧工作流已删除。** 旧的 `novel-cinematic` / anchor/chain/novel_h3 workflow 不再存在；
   不要从新代码里 import 它。

## 模型获取与部署（FastH3-Omni NVFP4 QAD）

本项目的生产链路用两个本地模型：**FastH3-Omni NVFP4 QAD**（画面 + H3 原生音频）和
**faster-whisper large-v3-turbo**（对白 QC 与字幕对齐）。音乐床来自项目内 Pixabay
音频，不使用生成模型。

### 1. 版本与硬件

| 项目 | 固定值 |
| --- | --- |
| 模型 | `FastVideo/FastH3-Omni-NVFP4-QAD` |
| 模型 revision | `f01e6a23ac6066aa9eb622cf94b6259442e70ec2` |
| FastVideo | `fa2d1324c60050cd65209c6aaeac470e7fb412f5` |
| 模型目录 | `runtime/models/FastH3-Omni-NVFP4-QAD` |
| 下载清单 | `runtime/fastvideo-model-download.json` |
| 运行时 | `runtime/FastVideo` + `runtime/fastvideo-venv` |
| Python / PyTorch / CUDA | 3.12 / 2.12.0+cu130 / 13.0 |
| 关键 wheel | `cuda-toolkit==13.0.2`、`fastvideo-kernel==0.3.5`、`flashinfer-python==0.7.2` |
| 显存 | RTX 5090 32GB（测试驱动 595.99.02，功耗上限 450W） |
| 内存 | 建议 ≥64GB；服务强制 44GiB systemd slice |
| 磁盘 | 模型目录约 72GB；含 venv 建议预留 ≥100GB |

模型许可：MiniMax H3 Community License，见
[模型卡](https://huggingface.co/FastVideo/FastH3-Omni-NVFP4-QAD)。本仓库不重新分发权重。

### 2. 系统依赖

Ubuntu / Debian 示例：

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs ffmpeg build-essential cmake ninja-build pkg-config libgl1
git lfs install
```

还需要：

- NVIDIA 驱动支持 CUDA 13（本机测试为 595.99.02）
- `uv`（本机测试为 0.11.26）
- Hugging Face CLI：`pip install -U "huggingface_hub[cli]"`
- 可用的 systemd user manager（`safety.py` 会把模型进程放进 44GiB slice）

### 3. 安装 FastVideo 运行时

```bash
git clone --recursive https://github.com/hao-ai-lab/FastVideo.git runtime/FastVideo
git -C runtime/FastVideo checkout fa2d1324c60050cd65209c6aaeac470e7fb412f5
git -C runtime/FastVideo submodule update --init --recursive

uv python install 3.12
uv venv --python 3.12 runtime/fastvideo-venv
source runtime/fastvideo-venv/bin/activate

FLASHINFER_CUDA_ARCH_LIST=12.0a MAX_JOBS=4 \
  UV_TORCH_BACKEND=cu130 \
  uv pip install -e "runtime/FastVideo[fasth3]"

uv pip install "cuda-toolkit[nvcc,cccl]==13.0.2" \
  "nvidia-cuda-crt==13.0.88" "nvidia-nvvm==13.0.88"
```

`MAX_JOBS=4` 避免内核编译把内存打满；RTX 5090 使用 `12.0a` 架构。安装完成后确认：

```bash
runtime/fastvideo-venv/bin/python -c \
  "import torch, fastvideo; print(torch.__version__, torch.version.cuda)"
# 2.12.0+cu130 13.0
```

> 在 glibc 2.42 + CUDA 13.0 的环境中，如果 NVCC 报 `rsqrt` / `rsqrtf` 异常声明冲突，
> 对隔离 CUDA 头应用仓库内补丁：
>
> ```bash
> patch -d runtime/fastvideo-venv/lib/python3.12/site-packages/nvidia/cu13/include \
>   -p1 < runtime/fastvideo-migration/cuda-header-compat.patch
> ```
>
> 普通 Ubuntu 24.04 / 22.04 环境通常不需要。

### 4. 下载模型

```bash
hf auth login   # 若模型页要求接受许可
hf download FastVideo/FastH3-Omni-NVFP4-QAD \
  --revision f01e6a23ac6066aa9eb622cf94b6259442e70ec2 \
  --local-dir runtime/models/FastH3-Omni-NVFP4-QAD
```

- 下载清单包含 51 个带大小 / SHA-256 的文件；完整模型目录约 72GB
- 国内网络可设置 `HF_ENDPOINT=https://hf-mirror.com`
- 下载完成后不要改目录名；项目 `config.json` 和下载清单都按这个路径校验

模型包含：

| 目录 / 文件 | 用途 |
| --- | --- |
| `transformer_ref/` | NVFP4 参考条件 transformer |
| `text_encoder/` | NVFP4 Qwen3-VL 文本 / 视觉编码器 |
| `vae/`、`audio_vae/` | 视频 / 音频 VAE |
| `vae_decoder_nvfp4/` | 36 层高质量视频解码器 |
| `vae_decoder_nvfp4_fast/` | 8 层快速解码器 |
| `scheduler/`、`processor/`、`tokenizer/` | 采样与输入处理 |
| `fastvideo_inference.json` | 8 次 PDD 推理配置 |
| `adaln_table.pt` | 由第 6 步生成，非下载文件 |

### 5. 校验模型完整性

```bash
.venv-openmontage/bin/python - <<'PY'
import json
from pathlib import Path

root = Path('runtime/models/FastH3-Omni-NVFP4-QAD')
manifest = json.loads(Path('runtime/fastvideo-model-download.json').read_text())
missing, wrong = [], []
for row in manifest['files']:
    if row['path'] == '.gitattributes':
        continue
    path = root / row['path']
    if not path.is_file():
        missing.append(row['path'])
    elif row['size'] and path.stat().st_size != row['size']:
        wrong.append(row['path'])
print('files', len(manifest['files']), 'missing', len(missing), 'size_mismatch', len(wrong))
if missing or wrong:
    print('missing', missing[:5])
    print('wrong', wrong[:5])
    raise SystemExit(1)
PY
```

`start_fastvideo.py` 启动前会检查 `fastvideo_inference.json`、
`transformer_ref/nvfp4_weights.safetensors`、`text_encoder/model.safetensors.index.json`、
`vae_decoder_nvfp4/decoder-nvfp4.safetensors` 和 `adaln_table.pt`。

### 6. 生成 AdaLN 表

```bash
runtime/fastvideo-venv/bin/python scripts/prepare_fastvideo_adaln.py \
  runtime/models/FastH3-Omni-NVFP4-QAD
```

输出 `runtime/models/FastH3-Omni-NVFP4-QAD/adaln_table.pt`（约 891MB）和 `.inputs`。
它把官方 PDD 时序和时间嵌入逐层预计算，避免 32GB 显卡常驻约 26GB 的 AdaLN 投影。
模型 revision 或 PDD 配置变化后需要重新生成。

### 7. 项目配置

每个要生成视频的项目目录需要 `config.json`。示例：

```json
{
  "video_engine": "fast_h3_omni",
  "fast_h3_omni": {
    "backend": "fastvideo",
    "model_repo": "FastVideo/FastH3-Omni-NVFP4-QAD",
    "revision": "f01e6a23ac6066aa9eb622cf94b6259442e70ec2",
    "runtime_commit": "fa2d1324c60050cd65209c6aaeac470e7fb412f5",
    "model_dir": "/path/to/novel-h3-studio/runtime/models/FastH3-Omni-NVFP4-QAD",
    "adaln_table": "/path/to/novel-h3-studio/runtime/models/FastH3-Omni-NVFP4-QAD/adaln_table.pt",
    "download_manifest": "/path/to/novel-h3-studio/runtime/fastvideo-model-download.json",
    "api_url": "http://127.0.0.1:8195",
    "production_enabled": true,
    "input_mode": "ref2va",
    "steps": 8,
    "scheduler_shift_video": 12.0,
    "scheduler_shift_audio": 3.0
  }
}
```

`model_dir`、`adaln_table`、`download_manifest` 必须是绝对路径。本机示例项目的配置在
`projects/liaozhai-wangliulang-cinematic/config.json`。

### 8. 配置内存隔离

`start_fastvideo.py` 启动前会调用 `safety.bounded_worker()`，要求当前用户有一个
`MemoryMax=44GiB` 的 slice；否则拒绝加载模型。

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/novel-h3-workloads.slice <<'EOF'
[Unit]
Description=Shared memory budget for novel video and audio model workers

[Slice]
MemoryAccounting=yes
MemoryHigh=40G
MemoryMax=44G
MemorySwapMax=1G
CPUQuota=600%
TasksMax=512
EOF
systemctl --user daemon-reload
systemctl --user show novel-h3-workloads.slice --property=MemoryMax --value
# 47244640256
```

如果通过 SSH 或无桌面会话启动，先确保 user manager 可用：

```bash
loginctl enable-linger "$USER"
```

### 9. 启动服务

```bash
cat > ~/.config/systemd/user/om-fastvideo.service <<'EOF'
[Unit]
Description=FastH3-Omni NVFP4 QAD service
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/novel-h3-studio
ExecStart=/path/to/novel-h3-studio/runtime/fastvideo-venv/bin/python /path/to/novel-h3-studio/start_fastvideo.py --project /path/to/novel-h3-studio/projects/liaozhai-wangliulang-cinematic
StandardOutput=append:/path/to/novel-h3-studio/runtime/om_fastvideo.log
StandardError=append:/path/to/novel-h3-studio/runtime/om_fastvideo.log
Restart=no
TimeoutStopSec=60

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now om-fastvideo
```

首次加载模型需要 1–3 分钟。检查：

```bash
curl -s http://127.0.0.1:8195/health
# {"status":"ok"}
curl -s http://127.0.0.1:8195/v1/model_info
```

也可以在前台启动：

```bash
runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-wangliulang-cinematic
```

本机批量生成时建议每镜重启服务，避免编码器反复卸载/加载累积内存：

```bash
.venv-openmontage/bin/python scripts/render_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic \
  --force --restart-every 1
```

### 10. 调用方式

OpenMontage 的标准入口是 `fastvideo_h3_video` 工具：

```bash
.venv-openmontage/bin/python studio.py tool fastvideo_h3_video @request.json
```

或按项目的 `assets/requests.json` 批量生成。服务契约：

- `POST /v1/videos`，`task=ref2va`
- `GET /v1/videos/{id}` 轮询
- `GET /v1/videos/{id}/content` 下载 MP4
- 画布 ≤ 1,032,192 像素；默认 1344×768
- 帧数 `17n+5`，范围 124–362（约 5.2–15.1 秒）
- 参考图 ≤3，参考音频 ≤3
- 参考文件必须在 `media_roots` 下：默认 `projects/`、`runtime/`；可用
  `FASTVIDEO_EXTRA_MEDIA_ROOTS=/abs/path1:/abs/path2` 追加
- 工具默认 `http://127.0.0.1:8195`，可用 `FASTVIDEO_H3_API_URL` 覆盖

### 11. 常见问题

- **`The isolated CUDA 13 compiler is missing`**：确认已安装
  `cuda-toolkit[nvcc,cccl]==13.0.2`，且 venv 路径是 `runtime/fastvideo-venv`。
- **`模型资源隔离未就绪，拒绝无保护启动`**：检查 `novel-h3-workloads.slice`，
  `MemoryMax` 必须是 `47244640256`。
- **`显卡功耗上限超过 450 W`**：`sudo nvidia-smi -pl 450` 后再启动。
- **`FastVideo NVFP4 QAD components or AdaLN table are incomplete`**：重新执行第 5、6 步。
- **`Port 8195 is serving a different model`**：停掉其他 FastVideo 服务，或修改 `api_url`。
- **显存不足**：保持 1344×768、`17n+5` 帧数；生成前关闭 ComfyUI 等其他 GPU 进程；
  长批次每镜重启服务。
- **启动脚本设置 `HF_HUB_OFFLINE=1`**：模型必须完整下载后才能启动。

### 12. 字幕与对白 QC 模型（faster-whisper）

字幕对齐和每镜对白 QC 使用 `mobiuslabsgmbh/faster-whisper-large-v3-turbo`（约 1.6GB），
CPU int8 即可，不占用显卡。本机测试版本为 faster-whisper 1.2.1 / CTranslate2 4.8.3。

```bash
hf download mobiuslabsgmbh/faster-whisper-large-v3-turbo \
  --local-dir runtime/models/faster-whisper-large-v3-turbo

uv venv --python 3.12 .venv-dialogue
source .venv-dialogue/bin/activate
uv pip install faster-whisper numpy
```

脚本默认读取本机 Hugging Face 缓存中的 large-v3-turbo；换机器或使用上面的本地目录时，
显式传 `--model`：

```bash
.venv-dialogue/bin/python scripts/qc_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic \
  --model runtime/models/faster-whisper-large-v3-turbo

.venv-dialogue/bin/python scripts/align_cinematic_dialogue.py \
  --project projects/liaozhai-wangliulang-cinematic \
  --model runtime/models/faster-whisper-large-v3-turbo
```

`qc_cinematic_shots.py` 检查每镜实际听到的对白与剧本是否一致；
`align_cinematic_dialogue.py` 用词级时间戳生成 `artifacts/asr.json`，再由
`build_cinematic_edit.py` 生成字幕。模型只需下载一次。

`docs/FastVideo基准接入.md` 中的 ComfyUI FastH3-8-Step-V2 单文件模型只用于历史速度基准，
不是 cinematic 生产链路依赖。

## 参考图生成：ChatGPT Image 2.5 Sunburst（Codex 订阅）

本仓库的人物/场景参考图使用本地 Codex 订阅里的 ChatGPT Image 2.5
Sunburst，不走 OpenAI API key，也不走 OpenCode 图像 provider。

```bash
# 1. Codex CLI 已用 ChatGPT 计划登录
codex --version
codex login status          # 期望：Logged in using ChatGPT

# 2. 终端代理（桌面 Codex 的代理不会自动继承）
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897

# 3. 通过注册工具生成一张参考图
.venv-openmontage/bin/python studio.py tool codex_image @ref_payload.json
```

`ref_payload.json` 的关键字段：

```json
{
  "prompt": "Use the attached head-and-shoulders portrait as the absolute identity reference...",
  "output_path": "projects/<project-id>/assets/refs/<name>.png",
  "reference_paths": ["projects/<project-id>/assets/refs/faces/<name>_face.png"],
  "model": "gpt-6-luna",
  "image_model": "gpt-image-2.5-sunburst",
  "timeout_seconds": 900,
  "extra_instructions": "Image 1 is the absolute face identity; preserve the face exactly."
}
```

`model` 是调用内置 image_gen 的 Codex 文本模型；`image_model` 只记录本次
使用的图像模型，不是 CLI 的选择参数。Codex 内置 `image_gen` 没有模型
选择器，实际使用订阅默认的 2.5 图像模型；不要在 prompt 里写
“请使用 gpt-image-2.6-sunburst”，否则 Codex agent 会拒绝执行。

一致性协议：每个角色先做 `assets/refs/faces/<name>_face.png` 脸部主参考；
官服/群像只从脸部主参考换装、换场景，逐人显式绑定；先出样图再批量；脸漂移
的旧图移入 `assets/refs/inconsistent_backup/`。完整配置、故障排查与边界见
`AGENTS.md` 的「Codex CLI / ChatGPT Image 2.5 Sunburst 配置」。

## 模型运行时

`novel_h3/` 只保留本地模型服务所需的模块：

```text
fastvideo.py          # FastVideo HTTP 配置/请求
project.py            # 路径、哈希、锁
safety.py             # 内存/功耗约束
previs.py / previs_render.py
transition_audit.py
ref2va.py
memory_guard.py
```

旧的分镜/锚帧/chain/连续性/合成脚本已移除。镜头级 prompt、参考和视频都由 cinematic
项目的 `assets/requests.json` 驱动。

## 备注

- `openmontage/` 是本仓库内的正式工作流代码；Backlot 中文 UI 在 `openmontage/backlot/ui/`。
- Remotion 需要 `openmontage/remotion-composer/node_modules`；本机已安装。
- 大文件（takes、renders、node_modules）不进入 Git。
- 生产数据和最终交付物在 `projects/` 下；不要写到仓库根目录。

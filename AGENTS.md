# novel-h3-studio — OpenMontage cinematic workflow

This repository is the local production host for the **OpenMontage cinematic
pipeline** plus the local FastH3-Omni NVFP4 QAD model service.

The binding workflow guide is [`openmontage/AGENT_GUIDE.md`](openmontage/AGENT_GUIDE.md).
Read it before any production work. The old `novel-cinematic` / `novel_h3`
chain workflow is removed; do not recreate it.

## Architecture

- `openmontage/` — the OpenMontage cinematic workflow: pipeline manifests,
  stage director skills, tools, schemas, checkpoints, Backlot board.
- `novel_h3/` — only the local model service backend:
  `fastvideo.py`, `project.py`, `safety.py`, `previs.py`,
  `previs_render.py`, `transition_audit.py`, `ref2va.py`, `memory_guard.py`.
- `projects/` — production data (scripts, scene plans, prompts, requests,
  shots, music, subtitles, renders).
- `runtime/` — model runtime, FastVideo service, caches.

## Defaults

- **Workflow: OpenMontage `cinematic`.** New projects use
  `studio.py init <project-id> --pipeline cinematic`.
- **Backlot is Chinese.** The board at `studio.py board` / `studio.py serve`
  is the Chinese observer UI; keep new labels in Chinese.
- **Video engine: FastH3-Omni NVFP4 QAD** on `127.0.0.1:8195`, 8 steps,
  1344×768 / 24 fps, native H3 audio.
- **One project = one project directory** with `project.json`,
  `artifacts/`, `assets/`, `prompts/`, `public/`, `renders/`, `exports/`.
- **Prompts/requests are project data.** For cinematic work the source of
  truth is `projects/<id>/assets/requests.json` and `prompts/S*.txt`; do not
  generate a competing prompt stack in a version script.
- **Composition:** project-local Remotion composition (atelier) via
  `video_compose`; use `CinematicRenderer` only when the project chooses the
  standard cut schema.
- **Final audio:** native H3 dialogue/sound effects, music bed ducked under
  speech, subtitles from the project's `.srt` / Remotion props.
- **Douyin publishing:** use the `douyin-publish` skill
  (`.agents/skills/douyin-publish/SKILL.md`); it encodes the creator-center
  flow, correct selectors, cover requirements, and the AI declaration.

## Commands

```bash
# Workflow environment
.venv-openmontage/bin/python studio.py doctor
.venv-openmontage/bin/python studio.py init <project-id> --title "..." --pipeline cinematic
.venv-openmontage/bin/python studio.py board <project-id>
.venv-openmontage/bin/python studio.py serve --port 4751

# FastH3 service
runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-wangliulang-cinematic
# Full model acquisition/deployment: README.md "模型获取与部署"

# Render the cinematic project's requests one shot at a time
.venv-openmontage/bin/python scripts/render_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic --force

# Measure takes, align dialogue, rebuild props/captions
.venv-openmontage/bin/python scripts/qc_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-dialogue/bin/python scripts/align_cinematic_dialogue.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-openmontage/bin/python scripts/build_cinematic_edit.py \
  --project projects/liaozhai-wangliulang-cinematic

# Build the music bed and mix it under the picture
.venv-openmontage/bin/python scripts/build_cinematic_music_bed.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-openmontage/bin/python scripts/mix_cinematic_audio.py \
  --project projects/liaozhai-wangliulang-cinematic

# Compose via the OpenMontage tool registry
.venv-openmontage/bin/python studio.py tool video_compose @compose_picture_payload.json

# Generate the poster + Douyin covers (4:3 + 3:4) in one pass.
# With an approved poster: poster_path. Without one: video_path + poster_time.
.venv-openmontage/bin/python studio.py tool publish_covers @covers_payload.json
```

## Cinematic pipeline rules

1. Run the OpenMontage stages in order: `research` → `proposal` → `script` →
   `scene_plan` → `assets` → `edit` → `compose` → `publish`.
2. Each stage writes its checkpoint and artifact under the project directory.
   Do not skip a gated stage or write a competing artifact format.
3. `scene_plan` defines the shot list and the visual/sound intent. `assets`
   must render the project's `assets/requests.json`, not a different prompt
   stack.
4. Whenever the publish poster is produced, immediately generate platform
   covers with `publish_covers` (4:3 horizontal + 3:4 vertical for Douyin).
   Upload those covers; never hand-crop on the platform upload page.
5. `video_compose` is the only final render path. Atelier composition uses the
   project-local `index.tsx` / `Composition.tsx` / `public/props.json`.
6. Backlot is an observer/approval UI. Keep it Chinese; do not replace it with
   the upstream English UI.
7. The old `novel-cinematic` coverage/anchor/chain scripts and their pipeline
   are removed. Do not import them from new work.

## Project-specific notes

- `projects/liaozhai-wangliulang-cinematic` is the approved Wang Liulang
  cinematic project: 45 shots, project-local Remotion composition, Chinese
  subtitles, native H3 audio.
- Character/scene/voice references live in
  `projects/liaozhai-wangliulang/assets/`.
- FastH3 request payloads use `reference_image_paths` (≤3), optional
  `reference_audio_paths` (≤3), on the `17n+5` frame grid.

## Codex CLI / ChatGPT Image 2.5 Sunburst 配置

本地参考图使用 **Codex 订阅里的 ChatGPT Image 2.5（Sunburst）**，不经过
OpenAI API key，也不走 OpenCode 图像 provider。工具入口是
`codex_image`（`openmontage/tools/graphics/codex_image.py`）。

### 1. 前置条件

- 本机已安装 Codex CLI，并已用 ChatGPT/Codex 计划登录：
  ```bash
  codex --version
  codex login status     # 期望输出：Logged in using ChatGPT
  ```
- 终端不会继承桌面 Codex 客户端的代理。跑任何 `codex` 命令前先导出：
  ```bash
  export HTTPS_PROXY=http://127.0.0.1:7897
  export HTTP_PROXY=http://127.0.0.1:7897
  export ALL_PROXY=http://127.0.0.1:7897
  ```
  代理地址按本机实际配置调整；不要把凭据或代理写进仓库。
- 如果 `codex login status` 不是已登录：先设置代理，再执行
  `codex login --device-auth`，打开它给出的 URL 输入一次性代码。
  **不要**为了“刷新”而先删 `~/.codex/auth.json`；该文件是 CLI 的凭据，
  删除会让 CLI 立刻变成未登录。确需重登时先备份：
  ```bash
  cp ~/.codex/auth.json ~/.codex/auth.json.bak
  ```

### 2. 调用方式

`codex_image` 的 `model` 是“能调用内置 image_gen 的 Codex 文本模型”，
默认 `gpt-6-luna`；`image_model` 只是记录本次生成使用的图像模型
（`gpt-image-2.5-sunburst`），**不是** CLI 的模型选择参数。

```json
{
  "prompt": "Use the attached head-and-shoulders portrait as the absolute identity reference...",
  "output_path": "projects/<project-id>/assets/refs/<name>.png",
  "reference_paths": [
    "projects/<project-id>/assets/refs/faces/<name>_face.png"
  ],
  "model": "gpt-6-luna",
  "image_model": "gpt-image-2.5-sunburst",
  "timeout_seconds": 900,
  "extra_instructions": "Image 1 is the absolute face identity; preserve the face exactly."
}
```

```bash
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 ALL_PROXY=http://127.0.0.1:7897 .venv-openmontage/bin/python studio.py tool codex_image @ref_payload.json
```

成功时返回 `provider=codex_subscription`、`model=gpt-image-2.5-sunburst`。
Codex 内置 `image_gen` 没有暴露图像模型选择器，实际生成使用订阅默认的
2.5 图像模型；不要在 prompt 里写“请使用 gpt-image-2.6-sunburst”之类的
模型选择句，Codex agent 会拒绝执行。

### 3. 参考图一致性协议（强制）

1. 每个角色先有且只有一张脸部主参考：
   `assets/refs/faces/<name>_face.png`。
2. 官服、群像、变体只从这张脸做“换装/换场景”，不重新文生图一个“同名人”。
3. 多参考图必须显式逐人绑定：
   - `Image 1 = Song Gong face identity`
   - `Image 2 = official robe/pose only`
   - `Image 3 = horse/prop only`
4. 群像图不要让“群像参考”决定名字脸；群像只提供构图。视频提示词只绑定
   个人参考。
5. 先出一张样图，人工确认脸、年龄、胡须、服装；通过后再批量。
6. 发现脸漂移就清掉旧图，放入 `assets/refs/inconsistent_backup/`，用脸部
   主参考重生成；不要用裁剪或换脸去掩盖身份错误。

### 4. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `401 Missing bearer authentication` | CLI 没有有效 auth | 设置代理后 `codex login status`；未登录则设备登录 |
| `403 Forbidden` / `workspace routing timed out` | 终端没走代理或工作区不可达 | 导出 `HTTPS_PROXY` 后重试 |
| `model_not_found` | Codex 文本模型不可用 | 用 `model: "gpt-6-luna"` |
| “无法核验 gpt-image-2.6-sunburst” | 本地 CLI 未暴露 2.6 | 改用 2.5 Sunburst；不要伪造 2.6 |
| 生成了图但脸不对 | 身份参考不够近 | 用脸部特写 `faces/<name>_face.png` 重生成 |

### 5. 成本与边界

- 走 ChatGPT/Codex 订阅额度，不产生 OpenAI API 账单；仍然消耗订阅配额，
  批量前先出一张样图。
- 不要声称 CLI 能精确切换 Flare/Sunburst；本机当前实际是 2.5 订阅默认。
- 参考图是生产资产，输出必须落在 `projects/<id>/assets/refs/`；
  生成后做 contact sheet 人工复核。

## 发布文案规范（强制）

- 作品发布描述只写观众向的故事钩子、看点和情绪，不写制作技术说明。
- 不写模型名、H3、原生对白/音效、旁白条数、分辨率、时长、帧率、参考图流程等
  内部信息；这些留在项目 README、artifacts 和复盘里。
- 发布描述保持 2–4 句，话题 3–5 个，AI 作品仍必须带“内容由AI生成”声明。

## 提交规范（强制）

- 所有 Git commit message 一律使用中文，不使用英文标题或英文正文。
- 不带英文类型前缀；直接写中文，例如：
  `文档：记录 Codex 图像鉴权与参考图来源规则`
- 代码、配置、文档、脚本的提交都适用；如果需要说明范围，用中文括号，例如：
  `修复（FastH3）：重启服务后等待健康检查`

Structural checks do not replace human story/audio review.

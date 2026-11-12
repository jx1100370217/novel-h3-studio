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

## Codex CLI / ChatGPT image auth (2026-11-11 incident)

- The terminal does **not** inherit the desktop Codex app's network proxy.
  Before any `codex` command, export
  `HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 ALL_PROXY=http://127.0.0.1:7897`.
- Do **not** run `codex login --device-auth` to "refresh" a working CLI session.
  It deletes `~/.codex/auth.json` and leaves the CLI logged out until the device
  code is completed; the desktop app's login is a separate credential store.
  Back up `~/.codex/auth.json` first if a re-login is truly required.
- Before reusing existing character/scene reference images, verify their
  provenance (which image model generated them). Do not silently substitute
  local MiniMax H3 images when the user asked for ChatGPT Image 2.5.
- `codex_image` needs a model supported by the current ChatGPT account. Verify
  with a one-image sample before batching; `gpt-6.1-sol` / `gpt-6-luna` may be
  rejected with `model_not_found` on a ChatGPT plan.
- **Image model (2026-11-12):** the local Codex subscription exposes ChatGPT
  Image 2.5 Sunburst. The CLI's built-in `image_gen` has no model selector;
  asking it to use `gpt-image-2.6-sunburst` is rejected as unverifiable. Use
  `codex_image` with `image_model="gpt-image-2.5-sunburst"` for metadata and let
  the subscription default generate; do not put a model-selection sentence in
  the prompt.
- **Character consistency protocol:** keep one face-crop master per character
  (`assets/refs/faces/<name>_face.png`). Generate costume variants and group
  images from that face master with explicit mapping ("Image 1 = face identity;
  Image 2 = costume only"); never let a group reference supply a named face.
  Review a one-image sample before batching, and clear/replace any reference
  whose face no longer matches the master.

## 提交规范（强制）

- 所有 Git commit message 一律使用中文，不使用英文标题或英文正文。
- 不带英文类型前缀；直接写中文，例如：
  `文档：记录 Codex 图像鉴权与参考图来源规则`
- 代码、配置、文档、脚本的提交都适用；如果需要说明范围，用中文括号，例如：
  `修复（FastH3）：重启服务后等待健康检查`

Structural checks do not replace human story/audio review.

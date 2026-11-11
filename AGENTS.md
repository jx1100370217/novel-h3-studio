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

## Commands

```bash
# Workflow environment
.venv-openmontage/bin/python studio.py doctor
.venv-openmontage/bin/python studio.py init <project-id> --title "..." --pipeline cinematic
.venv-openmontage/bin/python studio.py board <project-id>
.venv-openmontage/bin/python studio.py serve --port 4751

# FastH3 service
runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-wangliulang

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
```

## Cinematic pipeline rules

1. Run the OpenMontage stages in order: `research` → `proposal` → `script` →
   `scene_plan` → `assets` → `edit` → `compose` → `publish`.
2. Each stage writes its checkpoint and artifact under the project directory.
   Do not skip a gated stage or write a competing artifact format.
3. `scene_plan` defines the shot list and the visual/sound intent. `assets`
   must render the project's `assets/requests.json`, not a different prompt
   stack.
4. `video_compose` is the only final render path. Atelier composition uses the
   project-local `index.tsx` / `Composition.tsx` / `public/props.json`.
5. Backlot is an observer/approval UI. Keep it Chinese; do not replace it with
   the upstream English UI.
6. The old `novel-cinematic` coverage/anchor/chain scripts and their pipeline
   are removed. Do not import them from new work.

## Project-specific notes

- `projects/liaozhai-wangliulang-cinematic` is the approved Wang Liulang
  cinematic project: 45 shots, project-local Remotion composition, Chinese
  subtitles, native H3 audio.
- Character/scene/voice references live in
  `projects/liaozhai-wangliulang/assets/`.
- FastH3 request payloads use `reference_image_paths` (≤3), optional
  `reference_audio_paths` (≤3), on the `17n+5` frame grid.

Structural checks do not replace human story/audio review.

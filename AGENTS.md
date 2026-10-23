# novel-h3-studio monorepo — agent contract

This repository is now the single production monorepo:

- `novel_h3/` — model backends only (FastVideo NVFP4 QAD, strict Ref2VA,
  batch shot runner, safety/project utilities).
- `openmontage/` — the only production workflow: pipeline manifests, stage
  director skills, tool registry, checkpoints, schemas, and the Backlot board.
- `projects/` — production data (gitignored): scripts, shot specs, takes,
  renders, reports.
- `runtime/` — model runtimes and service venvs.
- `attic/` — archived old novel-h3 workflow code. Do not import it from new
  work; it is kept only for rollback/reference.

The binding workflow guide is [`openmontage/AGENT_GUIDE.md`](openmontage/AGENT_GUIDE.md).
Read it before any production work. All production goes through the
OpenMontage pipeline: manifests + stage director skills + checkpoints + tools.

## Defaults

- Video engine: **FastH3-Omni NVFP4 QAD** (FastVideo service on
  `127.0.0.1:8195`, 8 steps).
- Resolution: **1344x768 @ 24fps** (768P, official FastVideo canvas limit).
- Prompts: strict six-section **Ref2VA** English format; Chinese only inside
  `<d>[Chinese] ...</d>` dialogue.
- Audio: character dialogue and video sound effects are **native H3 take
  audio**; only narration uses TTS; music reuses the approved bed.
- Audio gate: `audio_qc` must pass (or every issue be explicitly resolved)
  before delivery; human listening remains the final gate.

## Commands

```bash
# Workflow environment (OpenMontage tools + Backlot board)
.venv-openmontage/bin/python studio.py doctor
.venv-openmontage/bin/python studio.py board <project-id>
.venv-openmontage/bin/python studio.py init <project-id> --title "..." --pipeline novel-cinematic
.venv-openmontage/bin/python studio.py tool fastvideo_h3_video @payload.json

# Model service (FastVideo NVFP4 QAD)
./runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-zhiyi-video-comparison/config.json

# Shot batch (official multi-speaker Ref2VA runner)
./runtime/fastvideo-venv/bin/python -m novel_h3.fastvideo_batch \
  --project projects/<project>-fastvideo --all --width 1344 --height 768
```

## Global optimization rule (binding)

Every fix or production optimization must land in the shared production code,
not in a one-off version script:

- shot construction: `novel_h3/ref2va_builder.py`
- voice references: `novel_h3/voice_refs.py`
- Blender blocking guides: `novel_h3/previs.py` + `novel_h3/previs_render.py`
- cast audit: `novel_h3/cast_audit.py`
- transition audit: `novel_h3/transition_audit.py`
- batch rendering: `novel_h3/render_batch.py`
- picture/audio compose: `novel_h3/compose_cut.py`
- official tools: `openmontage/tools/**`
- workflow rules: `openmontage/pipeline_defs/` + stage director skills

`scripts/*.py` are thin CLI wrappers only. Do not fork a new `v5_*`/`v6_*`
pipeline when the existing production module can be extended. Project-specific
blocking, cast and voice decisions belong in `projects/<id>/.../authoring.json`,
not in the core code.

## Locked shot contract (production default)

- Every speaking character must have a dedicated voice reference WAV; a
  speaker without one is a hard validation error.
- Every shot declares its **exact visible cast**; source-reference characters
  that are off-screen must not be marked visible.
- Every multi-person shot (two or more visible bodies) uses a silent Blender
  gray-model blocking guide unless the human explicitly waives it.
- Every shot carries the instance lock: a close-up and a full-body view of one
  person are the same person, never two; no unlisted servants, guards,
  silhouettes, portraits or background copies.
- Every cut with an action/state change records `open_state` / `close_state`
  handoffs in the authoring data.
- The assets stage runs `scripts/audit_cast.py` (or the global `cast_audit`
  module) and human-reviews every suspect frame; face-count false positives
  from statues, portraits and animals must be recorded as such.
- The edit stage runs `transition_audit`; every `needs_fix` cut is either
  re-rendered with a handoff or explicitly accepted by the human.
- `audio_qc` and a human listening pass remain the final audio gate.

## Rules

- Every new Ref2VA prompt follows
  [`.cursor/rules/h3-ref2va.mdc`](.cursor/rules/h3-ref2va.mdc); no exceptions
  for MiniMax H3, VDN-H3, FastH3 or FastVideo.
- Do not reintroduce the archived workflow (`attic/`) into new code.
- Keep production data under `projects/`; never write assets to the repo root
  or `/tmp`.
- Structural/technical checks do not replace human story and audio review.

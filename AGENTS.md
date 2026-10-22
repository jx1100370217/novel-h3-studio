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

## Rules

- Every new Ref2VA prompt follows
  [`.cursor/rules/h3-ref2va.mdc`](.cursor/rules/h3-ref2va.mdc); no exceptions
  for MiniMax H3, VDN-H3, FastH3 or FastVideo.
- Do not reintroduce the archived workflow (`attic/`) into new code.
- Keep production data under `projects/`; never write assets to the repo root
  or `/tmp`.
- Structural/technical checks do not replace human story and audio review.

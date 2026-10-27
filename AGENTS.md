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
  `127.0.0.1:8195`, 8 steps). This is the **default and required delivery engine**.
  VDN-H3 Turbo is comparison/fallback only; do not switch the default without an
  explicit user decision.
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
- Every multi-person shot uses individual character reference images, never a
  group photo as the only identity reference. If a reference image contains
  other people, the prompt must state that those people are not cast and must
  be ignored. A duplicate person is a generation defect: re-render with the
  cast-count/instance lock; never crop or paint the duplicate out of a
  delivered shot.
- Every cut with an action/state change records `open_state` / `close_state`
  handoffs in the authoring data.
- Same-scene continuation shots default to the previous story-state shot's
  silent 2–4 s tail as a `<Video N>` continuation reference (`video
  continuation` in the summary). Insert shots may anchor to the last
  story-state shot instead of the immediately preceding insert. The video
  reference must preserve only the ending pose, hand/prop position, costume,
  light and screen direction; it must not copy framing, cuts, camera movement,
  old dialogue or audio, and it never replaces the `open_state` / `close_state`
  text contract. A declared `<Video N>` without a real `video_reference` in the
  request is a hard validation error.
- Every hand/body-part insert declares exactly five fingers and one thumb per
  visible hand; the compiler injects a hand-anatomy lock. Extra, fused,
  duplicated or missing digits are a render defect, not a style choice.
- Every named person keeps one costume across adjacent shots unless an authored
  costume change is explicit; the compiler injects a costume-continuity lock.
  A robe colour change between cuts is a continuity error.
- Every multi-person or hand-only cut preserves camera side and hand ownership:
  a hand entering from camera-right belongs to the person on camera-right. The
  compiler injects a screen-direction lock; do not mirror an action in post to
  hide a generation error.
- A seated person behind a desk keeps the lower body hidden by the solid desk.
  No legs, knees, feet, stool, cushion or green cloth may appear below the desk;
  the compiler injects a lower-body occlusion lock.
- If narration describes a physical action (dressing, eating, mounting,
  drinking, etc.), the shot must visibly perform that action with the object in
  frame. If the generated take cannot show it, change the narration or re-render;
  do not leave the voiceover describing an action the picture omits.
- Music is a bed, not a lead voice. Normalize the bed to roughly -30 LUFS,
  default `music_volume` at or below 0.55, duck to at most 0.22 under speech
  (attack 250 ms, release 700 ms), and keep the final mix at -16 LUFS with true
  peak at or below -2 dBFS. Do not use one 5-minute loop for the whole film when
  the story changes act; use a cue map. Human listening remains the final gate.
- A video reference does not guarantee the target's first frame. If a take
  still stages an earlier state (for example a second wake-up or a lie-down
  before sitting), trim the lead-in at the first frame that matches
  `open_state`, retime the native line if it fell inside the removed span, and
  record the trim in the take metadata. Do not accept the earlier state just
  because the rest of the take is usable.
- Body-part shots (hand/forearm inserts) must use a body-part take and a
  body-part reference. Never substitute a full-body clip or a close-up that
  reveals the actor's face; verify the take with the face audit.
- Entrance/off-screen dialogue must be timed before the character enters or
  before the reveal. Verify native line onset with VAD/ASR; if the model places
  the line late, retime the native audio (mute the late span and insert the
  approved voice line) or re-render with an explicit early line timing.
- Kneeling/supplicant blocking must face the superior or high desk, with the
  back/profile toward camera; never let the character kneel facing away or
  sideways from the person being addressed.
- Wake/reveal handoffs must match the previous close state. If A23 ends sitting
  upright with the mother touching his cheek, A24 must open sitting upright,
  eyes open; never return to lying down or stage a second awakening.
- The assets stage runs `scripts/audit_cast.py` (or the global `cast_audit`
  module) and human-reviews every suspect frame; face-count false positives
  from statues, portraits and animals must be recorded as such.
- The edit stage runs `transition_audit`; every `needs_fix` cut is either
  re-rendered with a handoff or explicitly accepted by the human.
- `audio_qc` and a human listening pass remain the final audio gate.

## Rules

- **Single-best-version retention (binding):** once the user explicitly states
  that a version looks better than the historical versions, delete the older
  versions' media, takes, board media, artifacts, checkpoints/history and old
  exports; keep only the current best version plus the minimal inputs needed to
  reproduce it (source refs, voices, script/authoring, compose spec, current
  takes, final export and QC evidence). Do not let historical versions
  accumulate as "backups" unless the user explicitly asks to keep a comparison.
  Before deleting, confirm the best version is complete, playable and QC'd;
  record the deletion in `decision_log`.
- Every new Ref2VA prompt follows
  [`.cursor/rules/h3-ref2va.mdc`](.cursor/rules/h3-ref2va.mdc); no exceptions
  for MiniMax H3, VDN-H3, FastH3 or FastVideo.
- Do not reintroduce the archived workflow (`attic/`) into new code.
- Keep production data under `projects/`; never write assets to the repo root
  or `/tmp`.
- Structural/technical checks do not replace human story and audio review.

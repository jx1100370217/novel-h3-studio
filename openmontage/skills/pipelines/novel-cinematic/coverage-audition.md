# Coverage Audition — V6+ Animatic Gate

## Why this stage exists

Rendering is the most expensive and least reversible part of the pipeline.
`coverage_audition` builds a cheap 480p animatic from previs/anchor frames and
the authored shot durations, so the cut can be judged before any H3 take is
generated.

This is not a trailer and not a slideshow for clients. It is the edit.

## Inputs

- `artifacts/scene_plan.json`
- `continuity_bible.json`
- `shots/<shot>.json` (dialogue, frames, camera, props)
- `previs/<shot>.png` or `anchor_frames/<shot>.png`
- optional temp dialogue WAVs and music

## Output

- `animatic/<version>_animatic.mp4` — 480p, 24fps, burned temp subtitles
- `artifacts/coverage_audition.json` — per-cut report and verdicts

## Review checklist

Watch the animatic end to end, then answer:

1. Does every cut land on a new idea, or is it the same coverage again?
2. Do the eyelines match across the cut?
3. Does anyone change side, costume, hair or prop state?
4. Is there a master/establishing shot for every scene?
5. Are there more cuts than the scene needs?
6. Does the scene end on its turn, or does it linger?
7. Does the sequence end state hand off to the next sequence?
8. Is any dialogue scene carried by talking heads when a physical action would
   do the job?

## Gate

The animatic must be reviewed and either:

- `pass` — every cut is intentional and the scene plays; or
- `revise` — the shot list is rewritten before rendering; or
- `waived` — a human explicitly accepts a flagged cut and records why.

Do not start `assets` with an unreviewed animatic or a `revise` verdict.

## Command

```bash
PYTHONPATH=. .venv-openmontage/bin/python scripts/build_animatic.py \
  --project projects/<id>/v6 \
  --out projects/<id>/v6/animatic/v6_animatic.mp4 \
  --report projects/<id>/v6/artifacts/coverage_audition.json
```

The builder uses anchor/previs stills when present, and a labelled placeholder
when a shot has no keyframe. A placeholder is a gate failure, not a shortcut.

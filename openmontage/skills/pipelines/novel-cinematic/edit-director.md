# Edit Director - Edit Stage

## Inputs

- `scene_plan`, `asset_manifest`, `projects/<id>/shots/*.json`.
- Typography / name-plate cues from the adaptation (project `typography_cues.json`).

## Output

Schema-valid `edit_decisions` artifact with `render_runtime: "ffmpeg"`.

## Cuts

- One cut per shot, in shot order. `source` is the asset-manifest id
  (`shot_S01` ...), `in_seconds: 0`, `out_seconds` = the clip's measured duration.
- `transition_out` is `cut` unless the chapter author authored a fade; record the
  reason per cut.
- No trimming inside a take: the model's native audio is continuous and a trim breaks
  the sound sync.

## Overlays and typography

- Name plates and chapter titles come from the cue list. For each cue:
  - `asset_id` points at a transparent PNG rendered at the delivery width;
  - `start_seconds`/`end_seconds` fall strictly inside the target shot's window;
  - `position` uses frame-fraction coordinates `{x, y, width, height}`.
- If a cue asset does not exist yet, generate the PNG with ffmpeg/drawtext in the
  compose stage, not here. The edit stage only declares windows.

## Transition audit

Run the `transition_audit` tool on the assembled picture cut before compose:

```bash
python scripts/audit_transitions.py \
  --video projects/<id>/exports/<cut>.mp4 \
  --script projects/<id>/.../script.json \
  --shots-dir projects/<id>/.../shots \
  --out projects/<id>/artifacts/transitions \
  --verdicts projects/<id>/.../transition_verdicts.json
```

Every cut is judged on its actual last/first frame. A `needs_fix` cut is
resolved by re-rendering with an authored `open_state`/`close_state` handoff,
re-ordering/trimming, or explicit human acceptance recorded in the decision
log. Do not hand-wave a jump cut or a missing action beat.

## Self-check

- [ ] Cuts cover the full runtime with no gap larger than one frame
- [ ] Overlay windows sit inside their shot and never overlap each other
- [ ] Total runtime matches the sum of the shot durations
- [ ] `transition_audit` has run on the final picture cut
- [ ] Every `needs_fix` cut has a handoff, edit fix or recorded human acceptance

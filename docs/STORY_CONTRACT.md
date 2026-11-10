# Story contract: action coverage, blocking, time jumps and props

V2 of a film can pass every technical QC (audio, subtitles, cut frames) and
still fail as a story because the picture shows the **result** of an action but
not the action itself: a full net appears without anyone driving fish; a woman
is already in shallow water without a fall; villagers promise support but never
hand anything over; a god is announced only in dialogue.

`novel_h3/story_contract.py` is the gate that catches those failures before any
GPU time. It is enforced by `scripts/audit_story.py` and by the
`scene_plan` / `coverage_audition` / `assets` gates in
`openmontage/pipeline_defs/novel-cinematic.yaml`.

## Required scene fields

```json
{
  "id": "S01",
  "set_map": "river_night",
  "prop_manifest": {
    "allowed": ["boat", "bank", "water", "lantern", "cup", "jar", "net", "fish"],
    "forbidden": ["table", "bench", "chair", "canopy", "cabin"]
  },
  "action_beats": [
    {
      "id": "S01-B3",
      "description": "Wang drives fish toward Xu's net",
      "visual": "Wang raises both arms at the water; silver fish ripple toward the boat",
      "shots": ["S01D1"]
    }
  ],
  "time_jump": "half a year",
  "time_jump_visual": "green reeds turn dry and pale; colder moonlight",
  "transition": "fade"
}
```

Rules:

- `action_beats` are the physical actions the audience must see. A beat is not
  covered by a character describing it, a title card, or a shot that opens on
  its result.
- Every beat is assigned to at least one shot; that shot must declare
  `covers_beats`.
- `set_map` names the persistent spatial contract (who is on the boat/bank,
  which side is camera-left, what is forbidden). It is not a style note.
- `prop_manifest.forbidden` is hard: a table, bench, canopy, boat or food item
  that is not authored must not appear.
- A time jump needs `time_jump_visual` and a transition in
  `cut|fade|card|montage|dissolve`.

## Required shot fields

```json
{
  "id": "S01D1",
  "scene": "S01",
  "cast": ["xu", "wang"],
  "extras": [],
  "covers_beats": ["S01-B3"],
  "blocking_guide": "previs/S01D1.png",
  "blocking_waiver": "",
  "props": ["boat", "bank", "net", "fish", "lantern"]
}
```

Rules:

- Every multi-person shot has a silent Blender gray-model blocking guide
  (`blocking_guide`) or an explicit human waiver. The guide fixes body count,
  screen position, boat/bank/room side and camera.
- The guide is **not** a visual style reference. `previs_render.py` produces a
  gray Workbench still; the anchor generator uses it for blocking only, then
  adds identity/costume/set references.
- A shot with no `covers_beats` must declare `role` as `reaction`, `insert`,
  `plate` or `transition`; otherwise it is likely an orphan.
- `props` declares the actual set/props; forbidden items are rejected.

## Commands

```bash
PYTHONPATH=. .venv-openmontage/bin/python scripts/audit_story.py \
  --contract projects/<id>/vN/story_contract.json \
  --root projects/<id>/vN \
  --out projects/<id>/vN/artifacts/story_contract_audit.json
```

The gate must pass before anchors. The asset stage must not start with a
missing blocking guide, an uncovered action beat, or a scene whose only
time-jump marker is dialogue.

## Why this exists

The v2 王六郎 cut is technically complete but narratively incomplete:
the fish-driving action is replaced by a full net; the woman is already in
shallow water; the villagers promise support without giving anything; the
godhood and the whirlwind farewell are dialogue-only. The story contract makes
those omissions visible at the scene-plan stage, when they are cheap to fix.

# Continuity Supervisor — V6+ Pre-production Gate

## Why this stage exists

H3 renders every take from scratch. A treatment can be dramatically strong and
still cut together like a set of unrelated clips. This stage is the script
supervisor: it turns the script and shot plan into a machine-checkable
continuity ledger before any GPU time is spent.

Read `docs/SEQUENCE_AND_CONTINUITY.md` first. This skill is the production
check, not a second screenplay lecture.

## Inputs

- `script.json`
- `screenplay_treatment.json` (must contain `sequence_map` and per-scene
  `scene_sequel`)
- `artifacts/scene_plan.json`
- shot authoring data (`authoring.json` or per-scene masters)
- character / scene / prop reference manifest

## Output

`continuity_bible.json` with one block per scene and one entry per shot:

```json
{
  "scene_id": "S06",
  "sequence_id": "Q5",
  "story_day": 2,
  "time_of_day": "正午",
  "location": "河湾",
  "cast": ["xu", "wang", "woman"],
  "costume": {"xu": "dark patched robe, sleeves rolled, wet to the waist"},
  "props": ["one wrapped baby bundle", "river water"],
  "axis": "Xu camera-left, Wang across the river camera-right",
  "screen_direction": "woman enters from camera-right and falls toward camera-left",
  "light": "flat overcast noon, grey-green water",
  "shots": [
    {
      "shot_id": "S06E",
      "open_state": "Xu kneels in the shallows, right hand reaching over the water",
      "close_state": "the same hand is withdrawn to his chest; the water is empty",
      "cast": ["xu"],
      "costume_state": "wet to the waist, sleeves soaked",
      "prop_state": {},
      "hand_ownership": "Xu's right hand",
      "eyeline": "Xu looks down at the water, not at camera",
      "axis_side": "camera stays on Xu's bank",
      "screen_direction": "hand reaches camera-right, withdraws camera-left",
      "light_state": "same overcast noon",
      "time_state": "same story day, noon",
      "anchor_image": "previs/S06E.png",
      "continuity_in": "from S06D: baby bundle on the bank, Xu in the shallows",
      "continuity_out": "for S06F: Xu's hand at his chest, water empty"
    }
  ]
}
```

## Checks

Fail the gate on any of these:

1. A shot has no `anchor_image`.
2. A shot has no `open_state`, `close_state`, `eyeline`, `axis_side`,
   `screen_direction`, `costume_state` or `light_state`.
3. Consecutive shots in one scene do not match `close_state → open_state`.
4. A character changes costume, hair, wetness or injury without an authored
   costume change.
5. A prop changes state between shots without a visible action.
6. A hand enters from one side but is owned by the character on the other side.
7. The camera crosses the 180° line without `axis_cross: true` and a new line.
8. A shot has more visible people than its declared cast + authored extras.
9. A scene changes time-of-day or light without a transition beat.
10. Two consecutive shots are near-identical coverage (same size, same angle,
    same background) with no dramatic reason.

Warnings:

- a scene has more than 8 shots;
- two consecutive scenes share the same `scene_job`;
- a shot uses a previous take's tail but has no `continuity_in` note;
- a scene has no master/establishing shot.

## Procedure

1. Read the treatment and scene plan.
2. Write one scene block and one shot entry per scene/shot.
3. Resolve every `close_state → open_state` pair explicitly. If the states do
   not touch, insert a bridging shot or rewrite the cut.
4. Run:

```bash
PYTHONPATH=. .venv-openmontage/bin/python scripts/audit_continuity.py \
  --treatment projects/<id>/v6/screenplay_treatment.json \
  --script projects/<id>/v6/script.json \
  --scene-plan projects/<id>/v6/artifacts/scene_plan.json \
  --bible projects/<id>/v6/continuity_bible.json \
  --out projects/<id>/v6/artifacts/continuity_audit.json
```

5. Fix every issue. Then write the checkpoint with `status="awaiting_human"`.

Do not start `coverage_audition` or `assets` until this gate passes.

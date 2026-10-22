# Scene Director - Scene Plan Stage

## Inputs

- `script` artifact from breakdown.
- Approved reference assets already on disk
  (`projects/<id>/assets/refs/`), one file per character / location.

## Outputs

1. Schema-valid `scene_plan` artifact: one scene per shot, ids `S01`, `S02`, ...
2. Project-local shot contracts at `projects/<id>/shots/<shot_id>.json`. These hold
   the fields the VDN tool needs and that the scene_plan schema does not allow:

```json
{
  "id": "S01",
  "title": "病榻受召",
  "source_paragraph_ids": ["s0001_p0001"],
  "duration_seconds": 5.166666,
  "references": [
    {"asset_id": "songtao", "kind": "character", "path": "assets/refs/songtao.png"},
    {"asset_id": "song_home_room", "kind": "scene", "path": "assets/refs/song_home_room.png"}
  ],
  "prompt": "subject_definitions: ... full H3 prompt ...",
  "seed": 2026102101,
  "generation": {"width": 1024, "height": 576, "fps": 24, "steps": 8}
}
```

## Shot authoring rules

1. One continuous take per shot. No internal cuts, no montage inside a shot.
2. State the shot's `start_state` and `end_state`; the take must complete the authored
   action exactly once, with no pose reset.
3. Camera language: pick a shot size, lens, one movement, and a composition note.
   Motivate the movement with what the audience must learn or feel.
4. Cast count is exact. A shot with two people must never render a third person.
5. Screen direction and axis stay consistent between neighboring shots; record the
   axis id and the previous/next shot in `metadata`.
6. Durations are on the 24 fps frame grid: `frames = round(seconds * 24)`; the tool
   rounds to the nearest legal length.

## Prompt contract (VDN / MiniMax H3)

Build the per-shot prompt with these blocks, in order:

- `subject_definitions:` one line per `<Picture N>` reference. Characters: "preserve
  the face, age, hair and costume; the portrait background is not the location."
  Scenes: "use its architecture, materials and motivated light as the background."
- `summary:` one sentence, in the source language, naming the action.
- `retention_analysis:` one line per subject; keep identity and costume, one body only.
- `detailed_description:` shot size, lens, movement, composition, eyeline, opening
  state, action, ending state, spatial continuity, visible cast count.
- `overall_soundscape:` authored ambience and physical sound; repeat "no intelligible
  human voice" for wordless shots.
- `non_diegetic_music: N/A` unless music was explicitly approved.

Anchors must be identical across shots (same `<Subject N>` wording for the same
character) so identity survives coverage.

## Self-check

- [ ] Every script section maps to at least one shot
- [ ] Every shot has a matching `shots/<id>.json`
- [ ] Reference files exist and belong to the approved set
- [ ] No shot exceeds the model's tested duration envelope

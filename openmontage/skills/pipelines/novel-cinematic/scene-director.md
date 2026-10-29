# Scene Director - Scene Plan Stage

## Inputs

- `script` artifact: the enhanced script from the screenplay stage.
- `screenplay_treatment` artifact: motifs, added beats, shot opportunities,
  transitions, sound plan and fidelity ledger.
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

## Shot splitting

Each screenplay scene is a dramatic unit, not a single H3 take. Split every
scene into **3–12 shots (typically 3–7)**:

- an establishing/orienting shot;
- the dialogue exchange, often in two alternating sizes;
- a reaction or insert that carries the emotional turn;
- an exit/transition shot when the scene changes place or time.

No shot should be a 60-second take. On the current host, cap each H3 take at
**328 frames (13.667s) with ≤3 visual references, 260 frames (10.833s) with 4+**. Split long
scenes into motivated cuts at 3–10 shots per scene. Every shot gets a project-local contract at
`projects/<id>/shots/<shot_id>.json` with frames on the `17n+5` grid, camera,
lens, movement, lighting, blocking, dialogue lines, continuity and H3 prompt
notes. The scene plan's `description` must describe that shot, not repeat the
whole scene.

## Shot authoring rules

0. Read the `screenplay_treatment` first. Every added beat in the treatment must
   either become a shot or be explicitly dropped with a reason in the scene-plan
   metadata. Do not flatten the treatment back into uniform coverage.
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
- [ ] Every screenplay scene is split into 3–12 shots (typically 3–7)
- [ ] Every shot has a contract with frames, camera, light, blocking, dialogue, continuity and H3 notes
- [ ] Every treatment added beat is shot or explicitly dropped with a reason
- [ ] Visual motifs are planted and paid off in the planned shots
- [ ] Shot sizes vary; no two adjacent shots repeat the same size without intent
- [ ] Every shot has a matching `shots/<id>.json`
- [ ] Reference files exist and belong to the approved set
- [ ] No shot exceeds the model's tested duration envelope

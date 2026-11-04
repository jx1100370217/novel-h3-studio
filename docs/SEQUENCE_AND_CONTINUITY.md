# Sequence, Scene/Sequel and Continuity

This is the V6+ production standard for `novel-cinematic`. It exists because a
treatment can pass every dramatic checklist and still cut together badly. The
missing layer is not another theme worksheet; it is the work a script
supervisor and an animatic editor do before the first take is rendered.

## 1. Sequence map (binding)

Every feature treatment carries `sequence_map` with **8 sequences**. Each
sequence is a mini-film with its own goal, obstacle, turn and end state:

```json
{
  "sequence_id": "Q3",
  "purpose": "discovery and denial",
  "section_ids": ["S04"],
  "goal": "Xu wants to prove Wang is human",
  "obstacle": "the evidence points the other way",
  "turn": "Wang walks on water",
  "end_state": "Xu chooses to pretend he saw nothing"
}
```

Rules:

- Every scene belongs to exactly one sequence.
- Each sequence has a goal, obstacle, turn and end state.
- The end state of a sequence is the entering state of the next one; a sequence
  cannot reset the character or the relationship.
- The eight sequences cover: status quo/inciting incident, meeting/promise,
  discovery, revelation, crisis, loss, journey/opposition, climax/resolution.
  The exact boundaries follow the story, not a page count.

Source: the eight-sequence method (E.M. Welsh; Final Draft; USC tradition).

## 2. Scene / sequel (binding)

Every scene declares whether it is a **scene** or a **sequel**:

- **Scene**: `goal → conflict → disaster` (the character acts and fails).
- **Sequel**: `reaction → dilemma → decision` (the character absorbs the
  failure and chooses the next action).

```json
{
  "scene_type": "scene",
  "goal": "save the woman",
  "conflict": "saving her means Wang cannot leave",
  "disaster": "Xu withdraws his hand"
}
```

or:

```json
{
  "scene_type": "sequel",
  "reaction": "Xu cannot look at Wang",
  "dilemma": "confess or pretend",
  "decision": "he says he could have saved her"
}
```

Rules:

- A scene without a disaster is a location with people in it.
- A sequel without a decision is a mood, not a beat.
- Do not stack three scenes in a row with the same job. Alternate action and
  reaction, but keep the pressure rising.
- The decision at the end of a sequel is the goal of the next scene. This is
  the causal chain the audience follows.

Source: Dwight V. Swain, *Techniques of the Selling Writer*; scene/sequel
craft literature.

## 3. Continuity bible (binding)

`continuity_bible` is a per-scene, per-shot ledger. It is not prose. Every shot
must declare:

| Field | Meaning |
|---|---|
| `cast` | exact visible bodies, no unlisted extras |
| `costume_state` | robe, belt, hat, hair, wetness, blood, dust |
| `prop_state` | each handled prop and its state entering/leaving the shot |
| `hand_ownership` | which hand of which character holds/uses a prop |
| `eyeline` | who looks at whom, and which side of the frame |
| `axis_side` | which side of the 180° line the camera stays on |
| `screen_direction` | left→right / right→left movement and entrances |
| `light_state` | key, practicals, time-of-day, continuity of light |
| `time_state` | story day and time; no accidental time jump |
| `open_state` | the exact pose/prop/costume at the first frame |
| `close_state` | the exact pose/prop/costume at the last frame |
| `anchor_image` | the frozen first-frame keyframe used for image-to-video |

Rules:

- Physical continuity: props, wardrobe, hair, makeup, set dressing.
- Spatial continuity: 180° line, eyelines, screen direction, hand ownership.
- Temporal continuity: story day, time of day, light, wetness, wounds.
- Performance continuity: posture, energy, who is speaking, who is listening.
- A cut is legal only when the previous `close_state` and the next
  `open_state` describe the same body in the same place.
- If a shot intentionally crosses the axis, mark `axis_cross: true` and state
  the new line; never cross by accident.
- An unlisted table, chair, bowl, food service, extra person or duplicate body
  is a generation defect. Re-render; do not paint it out.

Source: script-supervisor practice (Wikipedia; Storyflow continuity guide;
Film Independent; StudioBinder).

## 4. Coverage audition / animatic (binding)

Before any GPU render, build a **480p animatic** from:

- previs blocking guides or frozen anchor keyframes;
- the authored shot durations;
- temp dialogue (TTS or silence) and burned temp subtitles;
- scene cards.

Review the animatic for:

- jump cuts and repeated near-identical coverage;
- eyeline and screen-direction mismatches;
- characters changing side, costume or prop state;
- scenes that are longer than their dramatic work;
- missing or redundant shots.

The animatic is the edit. If it does not cut together, rewrite the shot list.
Rendering is only allowed after the animatic gate passes or a human explicitly
waives a flagged cut.

## 5. Anchor-frame rendering (binding for V6+)

H3 has no memory between takes. A text-only shot starts from scratch. For every
shot:

1. Freeze one first-frame keyframe (`anchor_image`) from previs or an image
   model.
2. Generate with image-to-video, not pure text-to-video.
3. Use the previous take's silent tail only for motion/pose continuity, never
   as the only identity or framing reference.
4. Keep the same scene master, character refs, costume refs and prop refs for
   every shot in the scene.
5. Prefer fewer, longer, better-staged shots over wall-to-wall coverage. A
   scene with 14 independent cuts is a continuity risk; a scene with 4–7
   well-staged shots is usually stronger.

Source: current AI character-consistency practice (keyframe-first, last-frame
chaining, character/asset passports).

## 6. Gate order

```text
breakdown
  → screenplay (craft + sequence + scene/sequel)
  → scene_plan (coverage, anchor images, continuity fields)
  → continuity (continuity_bible audit)
  → coverage_audition (animatic)
  → assets (GPU render)
  → edit (transition audit)
  → compose (audio/subtitle QC)
  → publish
```

Do not collapse `continuity` or `coverage_audition` into the screenplay gate.
They catch different failures.

## 7. Further reading

- E.M. Welsh, “The Eight Sequence Method”.
- Dwight V. Swain, *Techniques of the Selling Writer* (scene/sequel).
- Story Grid, “The Story Grid Rule of 530” and the six core questions.
- Script supervisor: Wikipedia; Storyflow, “What Is Continuity in Film”;
  Film Independent, “Script Supervisor Tips”.
- AI consistency: keyframe-first / frame-chaining guides from Pixo, Vertical
  Motion and Plot Party (2026).
- Agent skills: `jtydhr88/screenwriting-skills` (structure, scene, dialogue,
  revision, story bible); `zenstory-ai/drama-skills` (assets, storyboard,
  spatial continuity, coverage audition, review).

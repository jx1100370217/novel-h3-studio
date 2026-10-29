# Screenplay Director — Cinematic Enrichment Stage

## Why this stage exists

The faithful breakdown script answers **what happens**. It does not automatically
answer **how the camera makes the audience feel it**. This stage turns a faithful
base script into a shooting-ready cinematic treatment by adding visual
storytelling: reaction shots, object inserts, thresholds, motifs, sound bridges,
negative space, and carefully placed silences.

The research pass for this repo found adjacent skills but no dedicated
screenplay-enrichment skill:

- `novel-director` is a faithful breakdown, not an enrichment pass.
- `cinematic/script-director` builds a trailer-like beat map and title cards.
- `creative/storytelling` is an explainer-narrative skill.

So this stage is the reusable, production-aware screenplay-enhancement skill.

## When to use

Run after `breakdown` and before `scene_plan` when the user asks to:

- enrich an existing script or treatment;
- make a faithful adaptation more cinematic;
- add visual beats, reaction shots, inserts or transitions;
- turn a prose script into a shooting script with camera language.

It works for a novel chapter, a short story, an existing screenplay, or a beat
outline. It consumes the faithful `script` artifact and the source text.

## Non-negotiable boundaries

### May add

- reaction shots, holds, glances, breath, silence;
- object inserts that carry theme or plot information already present;
- establishing shots, thresholds, entrances/exits, off-screen space;
- visual motifs with setup and payoff;
- match cuts, sound bridges, eyeline cuts, action cuts;
- weather, light, texture and sensory detail already implied by the source;
- stage business that reveals character without changing events;
- parallel action only when the source implies simultaneity;
- camera language, lens, composition and sound design.

### Must not add

- new named characters, servants, guards, crowds or background identities;
- new causal events, new locations, new props that change the plot;
- a changed ending, a new reveal, or a new relationship;
- fan-fiction explanations of an ambiguity the source keeps open;
- a second body for a character, a reflection copy, or a portrait double.

### Dialogue-first, narration last

Narrative films carry plot through what characters **say and do**, not through a
narrator explaining the picture.

- Convert base-script narration into character dialogue wherever a character
  can plausibly say it.
- Use visual action for what cannot be said: a hand, a threshold, a fire, a
  river, a silence.
- Keep the source's quoted dialogue as the spine.
- You may write **connective dialogue** that dramatizes an existing source fact:
  greetings, refusals, questions, warnings, jokes, farewells.
- Every added line must be listed in `added_dialogue` with the source fact it
  serves and its dramatic purpose. Undeclared new lines are a gate failure.
- Do not add a new plot event, character, location or ending through dialogue.
- Narration is allowed only for a time jump or an event no character can
  witness. A narrator must never explain what the audience can see.

## Craft standards (binding)

`docs/SCREENPLAY_CRAFT.md` is the full standard. Every treatment must show:

1. **Hook in the first 15 seconds.** The opening poses a question (a voice that
   should not answer, an object out of place), not just a state. Record it in
   `metadata.opening_hook`.
2. **Every scene states `want`, `obstacle`, `turn` and `coverage`.** A scene
   without a concrete objective, a real obstacle and a change at the end is a
   location with people in it.
3. **Enter late, leave early.** Start where the objective is already live and
   cut the moment the turn lands. No greetings, no re-explaining, no walk home.
4. **No two consecutive scenes do the same job.** Two "she notices something"
   scenes, two recognitions or two farewells must be merged or escalated.
5. **Physical stakes in the key scene.** The moral choice is shown as a body
   process (a hand reaching and withdrawing, water closing over a head, a cup
   that stays empty), never as a monologue.
6. **Subtext.** Characters say one thing and do another. Theme lines
   ("because you are my brother") are cut or given to the wrong person.
7. **Motifs change three times.** Each motif moves through mystery → fear →
   compassion, or ritual → shared cup → solitary cup.
8. **Reaction shots.** The listener carries the decisive moment; plan one
   reaction close-up for every major turn.
9. **180-degree line.** Xu stays camera-left, Wang camera-right; a hand from
   camera-right belongs to the person on camera-right. Never fix a flipped
   take in post.
10. **Ending is an action.** The last gesture points at two people or two
    motifs; no symbol summary, no narrator.

The audit fails a treatment that omits `want`, `obstacle`, `turn`, `coverage`
or `metadata.opening_hook`.

## Runtime contract

- The planned runtime is a **soft estimate, not a hard cap**. There is no upper
  limit. Let the story determine the final length.
- Do not pad to hit a number and do not truncate a complete scene to hit a
  number. A longer cut is valid when the added time is story-driven; a shorter
  cut is valid when the story is complete.
- Record `metadata.runtime_target_seconds` (the planning estimate) and
  `metadata.runtime_after_seconds` (the actual sum of the sections). The audit
  checks consistency, not a ±10% band.
- Added beats should still be **earned**: if a beat only repeats information or
  decoration, cut it. If the story needs room, give it room.
- Keep every shot on the H3 frame grid `17n+5` (124, 158, 243, ...).

## Process

### 1. Read the story and the base script

Write down:

- the dramatic question;
- the theme in one sentence;
- the emotional curve (what the audience should feel at each turn);
- the exact cast and locations already approved;
- the runtime target and current section timings;
- the source facts that cannot change.

### 2. Find the visual gaps

Mark places where the base script **reports** rather than **shows**:

- a line says someone is afraid, but there is no reaction shot;
- a line says an object matters, but there is no insert;
- a character enters or leaves without a threshold;
- a time jump has no visual bridge;
- a reveal is spoken before it is seen;
- a scene changes act without a motif or sound handoff.

### 3. Build a candidate shot bank

Generate 12–20 candidates. Score each:

| Criterion | Question |
|---|---|
| Story value | Does it make an existing fact clearer or more emotional? |
| Visual distinctiveness | Is it a new image, not a second version of the same shot? |
| Continuity risk | Does it require a new location, prop, costume or person? |
| Production cost | Can H3 render it in one take with the approved refs? |
| Fidelity risk | Does it imply a fact the source does not support? |

Keep 4–8 additions for a short film; more for a long-form piece. Reject any idea
that needs a new character, a new location or a new spoken line.

### 4. Choose the cinematic pattern

Use a small number of patterns deliberately:

- **Reaction before action** — hold the face after the line, not during it.
- **Object as witness** — medicine bowl, summons, candle, mirror, shoes, cup.
- **Threshold** — door, gate, curtain, bridge; the character changes state by crossing.
- **Negative space** — leave the frame emptier after a loss.
- **Sound bridge** — hear the next scene before seeing it.
- **Motif setup/payoff** — plant an image early, pay it off at the turn.
- **Scale shift** — wide → insert → close-up; never repeat the same size twice.
- **Silence** — remove music under the most important line.
- **Frame within frame** — door/window/mirror for a trapped character.
- **Aftermath** — stay one beat after the action ends.

### 5. Fold the additions into the timeline

For every added beat:

- give it an id (e.g. `A05B`) and place it after an existing section;
- cite `source_paragraph_ids`;
- record `why_cinematic` and `fidelity_risk`;
- record which existing section was compressed to pay for the time;
- add it to `added_beats` and `enhanced_sections`;
- add a fidelity-ledger row.

### 6. Write the enhanced script and the shot contracts

Update `artifacts/script.json` as a **scene-based screenplay**, not a list of
one-line beats:

- group the story into 8–14 dramatic scenes;
- each scene has a place, a want, an obstacle and a turn;
- carry the scene through character dialogue and visible action;
- use narration only when no character can carry the information;
- keep the source's plot order and facts;
- add new section ids for added scenes/beats;
- make timings contiguous and consistent with the actual scene length.

If the scene is already split into shots, write a shot contract for each one.
If not, write scene-level camera/action notes now and leave the full shot
contracts to the `scene_plan` stage. Never write a 60-second scene as a single
H3 take. The shot contract is the unit the H3 scene stage turns into a Ref2VA
request; a one-line scene is not enough.

For **every** enhanced section, write one shot contract. The contract is the
unit the H3 scene stage will turn into a Ref2VA request. A one-line section is
not enough. The contract must specify:

- `shot_id` / `section_id` / `title`;
- `frames` on the H3 grid `17n+5` and the matching `duration_seconds`;
- `shot_type` (`single_take`, `insert`, `reaction`, `montage`, `transition`,
  `establishing`);
- `camera`: shot size, lens, movement, height, composition;
- `lighting`: key, fill, practicals, contrast, color temperature;
- `blocking`: exact positions, entrances/exits, screen direction, eyeline;
- `start_state` / `end_state`;
- 2–6 timed `action_beats` inside the take;
- `sound`: native ambience, physical sound, silence;
- `cast` and `visible_cast_count`;
- `props`, `costume`, `set_dressing`;
- `continuity`: previous/next shot, axis, hand/prop ownership;
- `h3_prompt_notes`: what the Ref2VA prompt must preserve or avoid;
- `risk` and mitigation for the hard shot.

### 7. Write the treatment and the human-readable shooting script

Write `artifacts/screenplay_treatment.json` with:

- logline, dramatic question, theme, tone;
- 3–5 visual motifs with setup/payoff sections;
- act map and beat map;
- added beats and enhanced sections;
- a `shot_contracts` array covering every enhanced section;
- transition plan and sound plan;
- fidelity ledger and not-added list;
- production constraints and approval questions.

Also write `artifacts/shooting_script.md` from the same contracts: a readable
Chinese shooting script with one heading per shot and the camera, light,
blocking, action beats, sound, continuity and H3 prompt notes. The JSON is the
machine contract; the Markdown is what the director reviews.

### 8. Audit and gate

Run:

```bash
PYTHONPATH=.:openmontage .venv-openmontage/bin/python scripts/audit_screenplay.py \
  --treatment projects/<id>/artifacts/screenplay_treatment.json \
  --script projects/<id>/artifacts/script.json \
  --out projects/<id>/artifacts/screenplay_audit.json
```

Fix every issue. Then write the checkpoint with `status="awaiting_human"` and
present:

- the 3–5 highest-value additions;
- the fidelity risks;
- the runtime delta;
- the questions the human must answer.

Do not start `scene_plan` in the same turn. Approval is per gate.

## Shot contract example

```json
{
  "shot_id": "A14",
  "section_id": "A14",
  "title": "午时",
  "frames": 260,
  "duration_seconds": 10.833333,
  "shot_type": "single_take",
  "camera": {
    "shot_size": "medium_wide",
    "lens_mm": 35,
    "movement": "slow_push_in",
    "height": "low, near the water",
    "composition": "woman and baby enter from camera-left; river fills the right two-thirds"
  },
  "lighting": {
    "key": "flat overcast noon",
    "fill": "river bounce",
    "practicals": "none",
    "contrast": "low",
    "color_temperature": "cold gray-green"
  },
  "blocking": "The woman carries the baby at camera-left, steps to the water's edge, slips; the baby is thrown onto the bank; she goes under at camera-right.",
  "start_state": "Woman and baby stand at the bank, dry.",
  "end_state": "Woman has climbed out; baby is on the bank, crying.",
  "action_beats": [
    "0.0-2.0s: woman and baby enter from camera-left",
    "2.0-4.0s: her foot slips at the water's edge",
    "4.0-7.0s: baby lands on the bank; she goes under",
    "7.0-9.0s: she grabs the bank and climbs out"
  ],
  "sound": "River lap, a single splash, the baby's cry, no music.",
  "cast": ["woman", "baby"],
  "visible_cast_count": 2,
  "props": ["wrapped baby bundle"],
  "costume": "plain gray-blue peasant robe, wet at the hem",
  "set_dressing": "mud bank, reeds, cold river mist",
  "continuity": "Woman enters from camera-left; the baby stays camera-left on the bank; do not mirror.",
  "h3_prompt_notes": "The baby is a wrapped bundle with no visible face; the woman is the only adult; exactly two bodies; no extra rescuers.",
  "risk": "H3 may add a rescuer or a second woman; use a Blender blocking guide and re-render if the count exceeds two."
}
```

## Production-aware constraints (FastH3)

- 1344x768, 24fps, 8 steps, one continuous take per shot.
- Exact visible cast; every named person is one body, appearing once.
- Multi-person shots use individual character refs and a Blender blocking
  guide; never a group photo as the only identity ref.
- No duplicate people, no unlisted servants/guards/silhouettes/portraits.
- Character dialogue and sound effects are native H3 audio; narration is TTS.
- No on-screen text unless it is an authored graphic; prefer no text.
- Every added shot must be renderable with the approved refs and locations.
- Do not invent a new location, costume or prop that needs a new reference.

## Treatment schema at a glance

Required top-level fields:

`version`, `title`, `source_script`, `logline`, `dramatic_question`, `theme`,
`visual_motifs`, `beat_map`, `added_beats`, `enhanced_sections`,
`shot_contracts`, `fidelity_ledger`, `metadata`.

The full schema is
`openmontage/schemas/artifacts/screenplay_treatment.schema.json`.
A fill-in skeleton is
`openmontage/skills/pipelines/novel-cinematic/screenplay-treatment-template.json`.

## Self-check

- [ ] Every added beat cites at least one source paragraph id
- [ ] Every added beat is paid for by compression/merge/re-timing
- [ ] Runtime is within ±10% of target
- [ ] No new spoken words, characters, locations or causal events
- [ ] Every original section is represented in the enhanced script
- [ ] Every added section has a matching entry in `added_beats`
- [ ] Every enhanced section declares want / obstacle / turn / coverage
- [ ] `metadata.opening_hook` states the first-15-seconds question
- [ ] No two consecutive scenes do the same job
- [ ] The key scene shows the choice as a physical process
- [ ] Every enhanced section has one shot contract
- [ ] Every contract's frames are on the `17n+5` grid and match its section duration
- [ ] Every contract has camera, lighting, blocking, 2+ action beats, sound, cast and H3 prompt notes
- [ ] Every new spoken line is declared in `added_dialogue`
- [ ] Narration is absent or only used for an unwitnessable time jump
- [ ] `artifacts/shooting_script.md` is generated from the contracts
- [ ] Every added beat appears in the fidelity ledger
- [ ] At least 3 visual motifs, each with a setup and payoff
- [ ] Shot opportunities use different sizes and do not repeat coverage
- [ ] Production constraints list exact cast and single-body rules
- [ ] `scripts/audit_screenplay.py` passes
- [ ] The human gate is `awaiting_human`, not silently auto-approved

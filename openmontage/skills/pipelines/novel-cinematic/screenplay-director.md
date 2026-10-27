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
- new dialogue, narration words, letters, signs or on-screen text;
- new causal events, new locations, new props that change the plot;
- a changed ending, a new reveal, or a new relationship;
- fan-fiction explanations of an ambiguity the source keeps open;
- a second body for a character, a reflection copy, or a portrait double.

Dialogue and narration text are immutable. You may re-time, split, merge or
assign existing words; never write new spoken words.

## Runtime contract

- The enhanced script must stay within **±10%** of the approved runtime target.
- Added beats must be **absorbed** by compressing, merging or re-timing existing
  coverage. Do not simply append time.
- Keep every shot on the H3 frame grid `17n+5` (124, 158, 243, ...).
- If an added beat cannot fit, cut a lower-value beat or reject the idea.

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

### 6. Write the enhanced script

Update `artifacts/script.json`:

- keep existing section ids and their spoken text;
- add new section ids for added beats;
- make timings contiguous and within runtime;
- keep `text` as on-screen action/narration, not prose summary;
- do not add captions, signs or letters.

### 7. Write the treatment artifact

Write `artifacts/screenplay_treatment.json` with:

- logline, dramatic question, theme, tone;
- 3–5 visual motifs with setup/payoff sections;
- act map and beat map;
- added beats and enhanced sections;
- shot opportunities (size, lens, movement, composition, light, sound);
- transition plan and sound plan;
- fidelity ledger and not-added list;
- production constraints and approval questions.

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
`fidelity_ledger`, `metadata`.

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
- [ ] Every added beat appears in the fidelity ledger
- [ ] At least 3 visual motifs, each with a setup and payoff
- [ ] Shot opportunities use different sizes and do not repeat coverage
- [ ] Production constraints list exact cast and single-body rules
- [ ] `scripts/audit_screenplay.py` passes
- [ ] The human gate is `awaiting_human`, not silently auto-approved

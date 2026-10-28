# Novel Director - Breakdown Stage

## Inputs

- The source text (`.txt` or `.md`) with stable paragraph ids (for 聊斋志异-style
  anthologies: `s<NNNN>_p<NNNN>`).
- A planned runtime in seconds (a soft estimate, not a hard cap).
- Any previously approved adaptation material for the same source.

## Output

A schema-valid `script` artifact. Each section maps to one or more source paragraphs
and one dramatic beat of the chapter. This is the **faithful base script**; the
next stage (`screenplay-director`) adds cinematic visual beats without changing
the source facts or spoken words.

## Process

1. Split the source into paragraphs and assign ids if the source lacks them.
2. Identify the chapter's dramatic question, turning point, and ending. Write them in
   `metadata`.
3. Divide the chapter into 4-8 narrative scenes. For each, record `goal`, `conflict`,
   `turn`, `change`, and a one-line `script`.
4. Expand each scene into script sections whose `text` is the on-screen action, not
   prose summary. Keep the source's cause-and-effect order.
5. Set `start_seconds`/`end_seconds` so the total serves the story. The planned
   runtime is a soft estimate; expand or contract it when the material needs it.
   There is no hard upper limit and no padding to hit a number.

## Fidelity rules

- Characters keep the source's names, titles, ages and relationships.
- Dialogue is only used when the source quotes it; otherwise shots are wordless and
  the H3 native audio carries ambience and physical sound.
- The author's closing note (if any) stays in `metadata.source_notes`; it is not filmed.
- Do not merge two source events into one shot if that changes who learns what.

## Self-check

- [ ] Every section cites at least one source paragraph id
- [ ] No new location, character, object or causal link
- [ ] Runtime is justified by the story (planned estimate, no hard cap)
- [ ] Ending matches the source exactly

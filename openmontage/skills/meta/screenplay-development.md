# Screenplay Development

Use this before `scene_plan` when the source is a short story, a synopsis, or a
skeleton outline. The goal is not to write more plot; it is to turn the source
into a **playable, visual, tightly paced screenplay** that a shot list can be
derived from.

## Output

`screenplay_develop` writes two artifacts into the project's `artifacts/`:

- `screenplay.json` — canonical, schema-validated screenplay.
- `screenplay.md` — the same screenplay as a readable Chinese script.

The existing `script` artifact remains the beat/timing contract for the
pipeline. The screenplay is the richer upstream document; the scene plan must
be traceable to it.

## Process

1. **Find the spine.** Write one sentence each for:
   - what the protagonist wants,
   - what blocks it,
   - what forces a choice,
   - what the ending leaves the audience with.
2. **Choose a time structure.** Linear is default; use a frame, a countdown, or
   a repeated ritual only if it creates pressure. Do not add a twist that the
   source does not support.
3. **Expand into acts and scenes.** Each scene must have a turn: a decision, a
   reversal, a reveal, or a cost. If a scene only explains, merge it.
4. **Add production detail, not new lore.** Specify weather, light, props,
   costume state, distance, sound, and the one physical action that carries the
   scene. Every added detail must be consistent with the source.
5. **Plant and pay off.** Choose 3–5 visual motifs and repeat them at least
   three times with a change in meaning (e.g., paper: exam → summons → poem →
   death notice).
6. **Write sparse dialogue.** Keep the source's key lines; cut exposition that
   the image can carry. Put subtext in the JSON, not in the spoken line.
7. **Add narration only where the image cannot carry time or causality.**
   Three to five short lines maximum, placed over shots with no on-screen
   speaker. Narration must not duplicate dialogue.
8. **Mark transitions.** Hard cut by default; fade through black only for a
   time jump or a death. Name the time jump explicitly in the scene.
9. **Plan the title/name/time cards.** First appearance of a named character
   gets a vertical name card; a time jump gets a vertical time card. Cards are
   post-production overlays, never generated inside the video.
10. **Derive the shot list.** Three to six shots per scene. For every shot,
    write subject, subject motion, scene, spatial framing, camera, and the
    opening/closing state. Bind each named character to their **individual**
    reference image. Do not use a group reference as the identity source for a
    named face; group references drift.

## Quality bar

- Every act changes the pressure on the protagonist.
- Every scene has a turn and a reason to exist.
- The ending has a human aftermath and a final image, not just a plot answer.
- Dialogue is speakable in one breath; long speeches are split by action.
- Narration is ≤5 lines and never explains what the audience can see.
- Runtime is honest: roughly 8–10 seconds per shot for this pipeline.
- No new characters, facts, or endings that contradict the source.

## Tool call

```bash
python studio.py tool screenplay_develop @screenplay_payload.json
```

Payload:

```json
{
  "screenplay": { "...": "schema-valid screenplay" },
  "output_dir": "projects/<project-id>/artifacts",
  "write_markdown": true
}
```

Validate the JSON against `schemas/artifacts/screenplay.schema.json` before
sending it. After the tool succeeds, read `screenplay.md` once as a human:
does each scene turn, and does the ending land?

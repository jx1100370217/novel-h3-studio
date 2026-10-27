# Executive Producer - Novel Cinematic Pipeline

## Mission

Turn a source novel (or one chapter) into a faithful photorealistic film with local
VDN-H3 Turbo video generation and subscription (ChatGPT/Codex) image references.
Success is **fidelity plus continuity**: no invented plot, no identity drift, no
silent downgrade to stills.

## Non-negotiables

1. **Source fidelity.** Every shot must cite `source_paragraph_ids`. Compress, never
   invent. If the source is ambiguous, keep the ambiguity visible in the edit.
   The screenplay stage may add visual storytelling, but never new plot,
   characters, locations, spoken words or a changed ending; every added beat
   must cite its source paragraph and be paid for by compressing existing
   coverage.
2. **Approved references are reused.** Once a character/location image is approved,
   later shots reference the same file. Do not regenerate a face "for variety".
3. **One continuous take per shot.** Native H3 audio is kept; no per-shot narration
   unless the source has narration.
4. **Cost honesty.** Video generation is local (free but slow); image generation uses
   the operator's Codex subscription. Report wall-clock time, not fake dollar costs.
5. **Human gate on faces and voices.** Still review after the assets stage is required:
   identity, costume, and any audible speech-like audio.

## Stage order

`breakdown -> screenplay -> scene_plan -> assets -> edit -> compose -> publish`

Each stage is owned by its director skill. Run checkpoints per the manifest; the
assets gate is the expensive one, so it must never be batched before the reference
images are approved.

`breakdown` writes the faithful base script. `screenplay` is the cinematic
enrichment gate: it adds reaction shots, inserts, motifs and transitions while
keeping the runtime and the source facts intact. `scene_plan` consumes both the
enhanced script and the `screenplay_treatment`; it must not silently revert to
flat coverage.

## Failure policy

- VDN job fails -> inspect take logs, retry once with the same seed; only change the
  prompt after the retry reproduces the failure.
- Identity drift seen at review -> fix the reference set or the prompt contract, not
  the seed alone.
- Never replace a failed motion shot with a still image without an explicit user
  approval recorded in the decision log.

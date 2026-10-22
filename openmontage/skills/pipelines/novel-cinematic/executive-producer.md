# Executive Producer - Novel Cinematic Pipeline

## Mission

Turn a source novel (or one chapter) into a faithful photorealistic film with local
VDN-H3 Turbo video generation and subscription (ChatGPT/Codex) image references.
Success is **fidelity plus continuity**: no invented plot, no identity drift, no
silent downgrade to stills.

## Non-negotiables

1. **Source fidelity.** Every shot must cite `source_paragraph_ids`. Compress, never
   invent. If the source is ambiguous, keep the ambiguity visible in the edit.
2. **Approved references are reused.** Once a character/location image is approved,
   later shots reference the same file. Do not regenerate a face "for variety".
3. **One continuous take per shot.** Native H3 audio is kept; no per-shot narration
   unless the source has narration.
4. **Cost honesty.** Video generation is local (free but slow); image generation uses
   the operator's Codex subscription. Report wall-clock time, not fake dollar costs.
5. **Human gate on faces and voices.** Still review after the assets stage is required:
   identity, costume, and any audible speech-like audio.

## Stage order

`breakdown -> scene_plan -> assets -> edit -> compose -> publish`

Each stage is owned by its director skill. Run checkpoints per the manifest; the
assets gate is the expensive one, so it must never be batched before the reference
images are approved.

## Failure policy

- VDN job fails -> inspect take logs, retry once with the same seed; only change the
  prompt after the retry reproduces the failure.
- Identity drift seen at review -> fix the reference set or the prompt contract, not
  the seed alone.
- Never replace a failed motion shot with a still image without an explicit user
  approval recorded in the decision log.

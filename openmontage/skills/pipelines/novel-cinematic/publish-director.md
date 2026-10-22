# Publish Director - Publish Stage

## Inputs

- `render_report`, `final_review`, `script`.

## Outputs

- Export package under `projects/<id>/exports/`:
  - `final.mp4` (delivery master),
  - `subtitles.srt` (name plates and titles as timed subtitles),
  - `metadata.json` (title, source chapter, runtime, resolution, cast, engine notes),
  - `poster.png` (generated with `codex_image`).
- Schema-valid `publish_log` artifact.

## Metadata rules

- `source` fields carry the original document sha256 and the covered paragraph ids.
- `engine` lists the exact video model, VDN turbo adapter, steps, sampler, seed grid.
- `warnings` must include any unresolved human-review item (e.g. speech-like audio,
  identity drift candidates) - never clear a warning without a recorded human pass.
- If the chapter is the first of an anthology, mark it `series_index: 1` and keep the
  source path and sha256 stable for later chapters.

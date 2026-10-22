# Compose Director - Compose Stage

## Inputs

- `edit_decisions` (ffmpeg runtime), `asset_manifest`.
- Per-shot clips with native audio.

## Outputs

- `renders/<id>_final.mp4` - H.264/AAC delivery master.
- Schema-valid `render_report` and `final_review` artifacts.

## Process

1. **Stitch.** Call `video_stitch` with the ordered clip paths, `transition: cut`,
   `auto_normalize: true`, `target_resolution: 1024x576`, `target_fps: 24`. Native
   audio is preserved; do not mux an external track.
2. **Overlay.** Build transparent PNG overlays for each typography cue
   (`ffmpeg -f lavfi` or `drawtext` with `fontfile`), then call `video_compose` with
   `operation: "overlay"` and the cue windows. Keep every overlay inside its shot.
3. **Encode.** Final file must be `libx264`, `yuv420p`, AAC stereo, faststart.
4. **QC.** ffprobe: duration exact to the frame grid, one video + one audio stream,
   1024x576, 24 fps. Extract one frame per shot and confirm no black/duplicate frames.

## Hard rules

- Native audio is the only audio. No narration, no music bed, unless the source
  explicitly has it and the user approved it.
- If a clip fails QC, fix the shot in the assets stage and re-stitch; never hide a
  broken clip under an overlay.
- Report the human audio-review warning as-is when the model-generated track contains
  speech-like material.

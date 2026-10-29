# Compose Director - Compose Stage

## Runtime

`render_runtime: ffmpeg`. This pipeline is fixed to the FFmpeg compose path and
does not select Remotion or HyperFrames.

## Inputs

- `edit_decisions` (ffmpeg runtime), `asset_manifest`.
- Native H3 takes under `projects/<id>/takes/<shot_id>/native.mp4`.
- Narration manifest and audio files (`voiceover/*_48.wav`).
- Approved music bed segments.
- Strict Ref2VA shot specs and the v4 timeline.

## Outputs

- `exports/<id>_v4.mp4` - H.264/AAC delivery master at 1344x768 / 24fps.
- `v4/audio_qc/report.json` - the audio QC gate report.
- Schema-valid `render_report` and `final_review` artifacts.

## Process

1. **Trim to the timeline.** For every shot, cut the native take to the exact
   frame count from the v4 script (`124` / `158` / `243` frames) and scale to
   `1344x768`. Use the official `video_trimmer` tool; never hand-edit frames.
2. **Stitch picture.** Call `video_stitch` with the ordered clip paths,
   `transition: cut`, `auto_normalize: true`, `target_resolution: 1344x768`,
   `target_fps: 24`.
3. **Mix audio.** Build the mix with `audio_mixer`:
   - character dialogue and sound effects: the native H3 take audio;
   - narration: the existing TTS files, placed on the v4 timeline;
   - music: the approved bed, ducked under speech.
   Do not replace character dialogue with TTS.
4. **Voice identity audit.** Run
   `python scripts/audit_voices.py --specs-dir ... --takes-dir ...` before
   delivery. Every `review` line means the take's timbre is closer to another
   character's reference; re-listen or re-render that shot. This is triage for
   the human listening pass, not a replacement for it.
5. **Audio QC gate.** Run `audio_qc` with the v4 script, narration manifest,
   shots directory, native take root, and report path. The compose stage must
   not deliver while the report is `revise` unless every issue is explicitly
   resolved and recorded.
6. **Subtitle gate.** Align every authored line to the native speech with
   word-level ASR (`novel_h3.dialogue_audit.align_words`); never place a cue by
   nominal offset. A line split by pauses starts at its first word. If a take
   carries a native H3 caption, skip post subtitles for that whole shot.
   After composing a chapter, `novel_h3.subtitle_qc.scan_duplicate_captions`
   must report `clean`; a two-row frame is a delivery defect.
7. **Encode.** Final file must be `libx264`, `yuv420p`, AAC stereo, faststart,
   `1344x768`, 24fps.
8. **Self-review.** ffprobe the final file, extract one frame per shot, confirm
   no black/duplicate frames, and write `final_review`.

## Hard rules

- Character dialogue and video sound effects are native H3 audio. TTS is only
  for narration.
- Music is the approved existing bed; do not add a different track.
- The `audio_qc` report is a gate, not a suggestion. Human listening is the
  final gate and must be recorded as `human_listening_confirmed`.
- If a take fails QC, fix the shot in the assets stage and re-stitch; never hide
  a broken take under an overlay or a louder music bed.
- Never burn a post subtitle on a shot that already has a native H3 caption;
  skip the whole shot and keep the native caption. Two caption rows in one
  frame is a delivery defect.
- A subtitle cue must start at the first spoken word and end at the last;
  nominal offsets and single-segment ASR matches are not acceptable.
- Report the human audio-review warning as-is when the native track contains
  speech-like material.

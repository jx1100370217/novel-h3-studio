# Asset Director - Assets Stage

## Inputs

- `scene_plan` + `projects/<id>/shots/*.json` shot contracts.
- Strict Ref2VA shot specs under `projects/<id>/shots/`.
- Approved references in `projects/<id>/assets/refs/`.
- Project authoring data: cast, scene, voice plan, extras and blocking (`projects/<id>/.../authoring.json`).
- Character voice references (`assets/voices/*_ref.wav`) and `voice_manifest.json`.
- Silent Blender blocking guides (`previs/<shot>.png`) for multi-person shots.

## Outputs

- One native take per shot under `projects/<id>/takes/<shot_id>/native.mp4`
  (picture + H3 native dialogue and sound effects).
- Schema-valid `asset_manifest` artifact: one `video` entry per take, plus one
  `image` entry per approved reference.

## Tools

| Tool | Use | Notes |
|---|---|---|
| `fastvideo_h3_video` | **Default.** Render each shot | Local FastH3-Omni NVFP4 QAD on the FastVideo service; strict Ref2VA; native H3 dialogue + SFX |
| `blender_previs` | **Multi-person default.** Render a silent gray blocking guide | Locks body count, screen position, pose and camera; never supplies final appearance |
| `vdn_h3_video` | Fallback only | Local MiniMax H3 + VDN Turbo on ComfyUI; use only when the FastVideo service is unavailable or a shot explicitly needs VDN |
| `codex_image` | New references, title art, posters | Codex/ChatGPT subscription; no API key |
| `image_selector` | Optional provider fallback | Only if `codex_image` is unavailable |

## Rendering contract

Author each shot as the official six-section Ref2VA format in English:

1. `subject_definitions`
2. `summary` (task-type prefix, e.g. `[reference generation]`)
3. `retention_analysis` (`fully_preserved` / `partially_preserved` / `attribute_transfer` / `weak_reference`; audio `fully_copy` / `partially_copy` / `reference` / `weak_reference`)
4. `detailed_description` (style introduction + `[Shot 1]`; character dialogue in `<d>[Chinese] ...</d>`)
5. `overall_soundscape`
6. `non_diegetic_music` (`N/A` for this project)

Call `fastvideo_h3_video` with:

- `shot_spec_path`: the strict Ref2VA spec JSON;
- `project`: the monorepo project directory that owns `takes/`;
- `output_path`: optional explicit take path;
- `width` / `height`: `1344` / `768`;
- `force`: only for an intentional re-render.

- Build every spec through `novel_h3.ref2va_builder.build_spec` (or the `scripts/build_ref2va_specs.py` CLI). Do not hand-assemble a spec that bypasses voice and cast validation.
- Every speaking character must have a dedicated voice reference in `voices`; `fastvideo_h3_video` rejects a speaker with no voice reference.
- Every multi-person shot must use a `blender_previs` guide. The guide fixes only body count, positions, poses, screen direction and camera; identity/costume/lighting come from the approved references.
- Use `python -m novel_h3.render_batch ... --board-media-dir board_media/v5` so Backlot sees each completed revision take immediately; do not point the board at the previous cut.
- After the batch, run `python scripts/audit_cast.py --takes-dir ... --expected ... --out ...`; treat it as triage, not a verdict. Confirm duplicate people by opening the annotated suspect frames.
- If a shot still burns a caption after `strong_no_text` and a fresh seed, use `python scripts/remove_subtitles.py --video ... --out ... --start ... --end ... --box x0,y0,x1,y1` (LaMa) while preserving the raw take and native audio. Prefer removing an invented line entirely if the source has no direct quote.
- One shot at a time; the local GPU cannot run two H3 jobs at once.
- Frame counts must land on the H3 causal-VAE grid `17n+5`
  (`124` = 5.1667s, `158` = 6.5833s, `243` = 10.125s).
- Character dialogue and sound effects are **native H3 audio**; do not replace
  them with TTS. Narration is handled in compose.
- After each render, verify with ffprobe: exact frame count, a video stream, and
  an audio stream. Keep the returned job id and sha256 in the manifest metadata.
- The FastVideo service can hold a large host-memory working set after a
  3-reference long take; restart it between heavy shots if memory pressure appears.

## Reference policy

- Characters and locations already approved are **reused verbatim**.
- Every image reference must be bound with an explicit `<Subject N>` /
  `<Picture N>` label and listed in `retention_analysis`.
- The population contract is generated from the actual cast metadata; never
  hand-edit it away.
- Regenerate only when the approved asset is wrong (identity, costume,
  architecture), and record the reason in the decision log.
- New stills from `codex_image` land in `assets/refs/` and become approved only
  after human review at the assets checkpoint.

## Quality gate

- [ ] Every shot in the plan has exactly one native take
- [ ] All takes share width, height, fps (1344x768 / 24)
- [ ] Native H3 dialogue and sound effects are present in every take
- [ ] Cast count matches the Ref2VA population contract
- [ ] No duplicate people, no missing referenced subject
- [ ] Every speaking character is bound to a dedicated voice reference
- [ ] Every multi-person shot has a Blender blocking guide and exactly the authored body count
- [ ] Instance lock is present: no close-up + full-body duplicate, no unlisted servant/guard/silhouette
- [ ] `scripts/audit_cast.py` has run and every suspect frame is human-reviewed
- [ ] Dialogue lines name the speaker and the audio reference explicitly
- [ ] Manifest paths are project-relative and all files exist

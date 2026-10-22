# Asset Director - Assets Stage

## Inputs

- `scene_plan` + `projects/<id>/shots/*.json` shot contracts.
- Strict Ref2VA shot specs under `projects/<id>/shots/`.
- Approved references in `projects/<id>/assets/refs/`.

## Outputs

- One native take per shot under `projects/<id>/takes/<shot_id>/native.mp4`
  (picture + H3 native dialogue and sound effects).
- Schema-valid `asset_manifest` artifact: one `video` entry per take, plus one
  `image` entry per approved reference.

## Tools

| Tool | Use | Notes |
|---|---|---|
| `fastvideo_h3_video` | **Default.** Render each shot | Local FastH3-Omni NVFP4 QAD on the FastVideo service; strict Ref2VA; native H3 dialogue + SFX |
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
- [ ] Manifest paths are project-relative and all files exist

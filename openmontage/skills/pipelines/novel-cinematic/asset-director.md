# Asset Director - Assets Stage

## Inputs

- `scene_plan` + `projects/<id>/shots/*.json` shot contracts.
- Approved references in `projects/<id>/assets/refs/`.

## Outputs

- One clip per shot under `projects/<id>/assets/video/<shot_id>.mp4`.
- Schema-valid `asset_manifest` artifact: one `video` entry per clip, plus one `image`
  entry per approved reference.

## Tools

| Tool | Use | Notes |
|---|---|---|
| `vdn_h3_video` | Render each shot | Local MiniMax H3 + VDN Turbo on ComfyUI; keeps native audio |
| `codex_image` | New references, title art, posters | Codex/ChatGPT subscription; no API key |
| `image_selector` | Optional provider fallback | Only if `codex_image` is unavailable |

## Rendering contract

Call `vdn_h3_video` with the shot contract fields: `prompt`, `reference_images`
(path + asset_id + kind), `width`, `height`, `duration_seconds`, `fps`, `steps`,
`seed`, `output_path`. Do not hand-build a ComfyUI graph; the tool owns the graph.

- Render order is sequential. The GPU cannot run two H3 jobs at once.
- One shot at a time; a failure is retried once with the same seed before any prompt edit.
- After each render, verify with ffprobe: duration within one frame of the contract,
  a video stream, and an audio stream.
- Keep the returned prompt id in the manifest metadata for traceability.

## Reference policy

- Characters and locations already approved are **reused verbatim**; the tool uploads
  them to the ComfyUI input directory under a content-hashed name.
- Regenerate only when the approved asset is wrong (identity, costume, architecture),
  and record the reason in the decision log. Then update every later shot that uses it.
- New stills from `codex_image` land in `assets/refs/` and become approved only after
  human review at the assets checkpoint.

## Quality gate

- [ ] Every shot in the plan has exactly one clip
- [ ] All clips share width, height, fps (1024x576 / 24)
- [ ] Native audio present in every clip
- [ ] Cast count matches the prompt contract
- [ ] Manifest paths are project-relative and all files exist

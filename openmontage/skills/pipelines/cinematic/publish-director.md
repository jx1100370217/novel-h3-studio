# Publish Director - Cinematic Pipeline

## When To Use

Package the cinematic piece and any cutdowns so the hero version stays clear and the distribution intent is obvious.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["proposal"]["proposal_packet"]`, `state.artifacts["research"]["research_brief"]`, `state.artifacts["script"]["script"]` | Final outputs and beat map |
| Tools | `publish_covers`, `export_bundle` | Platform covers and export packaging |
| Playbook | Active style playbook | Tone and naming consistency |

## Process

### 1. Separate Hero And Derivatives

Typical deliverables:

- hero trailer or brand film,
- teaser cut,
- social cutdown,
- poster-frame or thumbnail concept.

### 2. Generate Platform Covers From The Poster

The approved poster is the source of truth for every social cover. Do not
hand-crop a random video frame on the upload page.

If a designed poster already exists, crop both required aspect ratios from it.
If no poster exists yet, pass `video_path` + `poster_time` instead of
`poster_path`; the tool extracts the poster frame and writes the poster plus
both covers in one call.

For Douyin:

```bash
.venv-openmontage/bin/python studio.py tool publish_covers @covers_payload.json
```

`covers_payload.json`:

```json
{
  "poster_path": "projects/<id>/exports/<name>_poster.jpg",
  "output_dir": "projects/<id>/exports",
  "base_name": "<name>",
  "platform": "douyin",
  "horizontal_focus": "left",
  "vertical_focus": "center"
}
```

Outputs: `<name>_cover_4x3.jpg` (1440x1080), `<name>_cover_3x4.jpg`
(1080x1440), and `<name>_covers.json`. Use `left` when the poster title is
left-aligned; use `center` for a centered title. Douyin rejects vertical
covers at or below 600x800, so never downscale below 1080x1440.

### 3. Match Metadata To Tone

Packaging should reflect the actual mood:

- dramatic,
- premium,
- mysterious,
- reflective,
- urgent.

### 4. Preserve Editorial Truth

Store in `publish_log.metadata`:

- `hero_output`
- `derivative_outputs`
- `poster_frame_notes`
- `cover_paths` (horizontal and vertical)
- `distribution_notes`

### 5. Quality Gate

- hero export is clearly identified,
- derivative exports are labeled by purpose,
- metadata fits the tone,
- the package is usable without manual cleanup,
- both platform covers exist at the required aspect ratios and the title is not
  cropped,
- Douyin vertical cover is larger than 600x800.

## Common Pitfalls

- Mixing teaser and hero outputs without clear naming.
- Writing generic metadata that ignores the mood.
- Treating all cutdowns as interchangeable.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.

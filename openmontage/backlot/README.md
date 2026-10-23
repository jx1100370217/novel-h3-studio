# Backlot — the living storyboard

A read-only local board that shows a production happening: pipeline stages
lighting up, the script as a screenplay page, the scene plan as a filmstrip
that fills in as assets generate, decisions, spend, and activity — all
derived from what the pipeline already writes to `projects/<id>/`.

```bash
python -m backlot open <project-id>   # start server if needed + open browser
python -m backlot open                # library view (all projects)
python -m backlot serve --port 4750   # run the server in the foreground
```

## How it stays live

No agent involvement. A `watchfiles` watcher on `projects/` publishes change
notifications over SSE; the browser refetches board state. State sources:

| Board element | Disk source |
|---|---|
| identity / rail order | `project.json` + `pipeline_defs/<type>.yaml` |
| stage states, gates, versions | `checkpoint_<stage>.json` + `history/` |
| script card / modal | `artifacts/script.json` |
| filmstrip cards | `scene_plan × script × checkpoint live_assets` (falls back to `asset_manifest`) |
| generating shimmer, activity | `events.jsonl` (written by `BaseTool` instrumentation) |
| cost meter | checkpoint `cost_snapshot` |
| renders | `exports/*.mp4` + `renders/*.mp4` (newest first) |

Projects without checkpoints degrade gracefully to a "what the watcher
found" view — media, snapshots, renders.

## Live revision takes

During a new revision the old cut must not masquerade as current. `render_batch`
accepts `--board-media-dir board_media/v5`; after every completed shot it
hardlinks/copies the take into the project and writes
`checkpoint_assets.metadata.live_assets`. Backlot serves only in-project media,
so the storyboard shows the new take immediately and marks unfinished shots
`V5 待生成`. While the assets stage is in progress and no V5 export exists,
the Renders section shows the live progress instead of the previous cut, with
an explicit link to the previous export.

**Replay**: a completed run can be scrubbed end-to-end (▶ REPLAY RUN on the
board) — reconstructed from checkpoint history and event timestamps.

Try it without a real production:

```bash
python scripts/backlot_simulate_run.py          # live demo run (~1 min)
python -m backlot open backlot-demo-run
```

Design doc: `internal/design/LIVING_STORYBOARD.md`.

"""Read-only full-book preparation counters; drafts are not reviewed chapters."""
import json
from pathlib import Path
from .project import read, digest


def summary(root):
    root = Path(root)
    cfg = read(root/'config.json')
    state = read(root/'state.json')
    inventory = read(root/'bible/assets.json')
    voices = read(root/'bible/voices.json')
    chapters = [c for c in read(root/'book.json')['chapters'] if c.get('kind') == 'story']
    written = reviewed = 0
    for chapter in chapters:
        eid = 'chapter_' + chapter['id']
        path = root/'content_plans'/f'{eid}.json'
        if not path.exists():
            continue
        plan = read(path)
        if plan.get('creative_revision') != cfg.get('creative_revision') or not plan.get('script', {}).get('scenes'):
            continue
        written += 1
        ep_path = root/'episodes'/f'{eid}.json'
        visual_path = root/'analysis'/f'{eid}_speaker_visual.json'
        if not ep_path.exists() or not visual_path.exists():
            continue
        ep, visual = read(ep_path), read(visual_path)
        rhythm = plan.get('rhythm_review', {})
        if (rhythm.get('reviewed') and rhythm.get('version') == 2
                and rhythm.get('source_sequence_verified')
                and plan.get('speaker_audit', {}).get('status') == 'reviewed'
                and ep.get('content_sha256') == visual.get('content_sha256') == digest(plan)
                and state.get('approvals', {}).get(eid, {}).get('sha256') == digest(ep)):
            reviewed += 1
    def count(items, lookup):
        result = dict(total=len(items), present=0, approved=0)
        for item in items:
            record = lookup(item)
            if record.get('path') and (root/record['path']).is_file():
                result['present'] += 1
                result['approved'] += bool(record.get('approved'))
        result['missing'] = result['total'] - result['present']
        result['pending_review'] = result['present'] - result['approved']
        return result
    assets = {}
    for bucket in ('characters', 'scenes', 'props'):
        cards = list(inventory.get(bucket, {}).values())
        cards += [d for card in inventory.get(bucket, {}).values() for d in card.get('derivatives', {}).values()]
        assets[bucket] = count(cards, lambda card: state['assets'].get(card['id'], {}))
    from .character_views import registry as character_view_registry
    view_registry = character_view_registry(root).get('characters', {})
    character_appearances = list(inventory.get('characters', {}).values())
    character_appearances += [d for card in inventory.get('characters', {}).values()
                              for d in card.get('derivatives', {}).values()]
    def view_state(card):
        value = view_registry.get(card['id'], {})
        views = value.get('views', {})
        present = len(views) == 4 and all((root / row.get('path', '')).is_file() for row in views.values())
        master = state.get('assets', {}).get(value.get('master_asset_id'), {})
        return {'path': next(iter(views.values()), {}).get('path') if present else None,
                'approved': bool(present and master.get('approved'))}
    assets['character_views'] = count(character_appearances, view_state)
    names = list(inventory.get('characters', {}))
    names += [n for n,v in voices.items() if v.get('collective') and n not in names]
    assets['voices'] = count(names, lambda name: voices.get(name, {}))
    coverage_path = root/'analysis/dialogue_only_v3_coverage_review.json'
    coverage = read(coverage_path) if coverage_path.exists() else {}
    coverage_verified = (coverage.get('creative_revision') == cfg.get('creative_revision')
                         and coverage.get('all_chapters_and_assets_reviewed') is True)
    ready = (bool(chapters) and reviewed == len(chapters) and coverage_verified
             and all(a['approved'] == a['total'] for a in assets.values()))
    activity_path = root/'analysis/preparation_activity.json'
    from .preparation_control import status
    activity = status(root)
    batch_dir = activity.get('batch_dir')
    if batch_dir:
        events_path = root / batch_dir / 'events.jsonl'
        try:
            activity['events_updated_at'] = events_path.stat().st_mtime
            for raw in reversed(events_path.read_bytes()[-131072:].splitlines()):
                try:
                    event = json.loads(raw.decode('utf-8', errors='replace'))
                except json.JSONDecodeError:
                    continue
                item = event.get('item', event) if isinstance(event, dict) else {}
                text = item.get('title') or item.get('text')
                if not text and item.get('type') == 'mcp_tool_call':
                    args = item.get('arguments', {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    text = args.get('title') if isinstance(args, dict) else ''
                    if text:
                        text = f"{item.get('server', '工具')}/{item.get('tool', '调用')}：{text}"
                text = text or item.get('type') or event.get('type', '')
                if text:
                    activity['last_event'] = str(text).replace('\n', ' ')[:240]
                    break
        except OSError:
            pass
    return dict(activity=activity, chapters=dict(total=len(chapters), written=written, reviewed=reviewed,
                              remaining=len(chapters)-written), assets=assets,
                policy='视频按章节启动：当前待生成章节的剧本、分镜和所需资产核对通过后即可生成；其他章节准备任务可并行。',
                scope_note='资产分母按当前已登记名册统计（含衍生图和集体声音），会随全书审读补充；文件存在与审批状态不等于全书覆盖验收。',
                ready_to_generate=ready, full_book_ready=ready, video_gate='chapter', coverage_verified=coverage_verified,
                gate_reason='全书准备核对已完成；视频仍按章节独立检查。' if ready else '全书准备统计尚未完成；不阻止已具备本章资料的章节视频，当前章缺项会单独拦截。')

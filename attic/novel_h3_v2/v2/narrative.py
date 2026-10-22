"""Check authored story delivery, without claiming machine checks prove a film works."""
from pathlib import Path

from ..project import digest, read, write

BEATS = ('setup', 'conflict', 'choice', 'turn', 'outcome', 'closure')


def check(root, plan, contract, timeline=None):
    root = Path(root)
    problems, pending = [], []
    source = read(root / 'paragraphs.json')
    paragraphs = {p['id']: p['text'] for p in source}
    section = str(plan.get('chapter_id', '')).removeprefix('chapter_')
    complete = {p['id'] for p in source if p.get('section') == section}
    declared = set(plan.get('source_paragraph_ids', []))
    if not section or not complete or declared != complete:
        problems.append('必须绑定同一篇完整原文，不能只读取开头或借用其他篇的段落')
    if (root / 'book.json').is_file() and plan.get('source_document_sha256') != read(root/'book.json').get('source_sha256'):
        problems.append('剧本与当前小说原文版本不一致')
    facts = {f['id']: f for f in contract.get('facts', [])}
    ledger = {f['id'] for f in plan.get('source_fact_ledger', [])}
    if ledger and ledger != set(facts):
        problems.append('叙事交付事实清单与原文核心事实清单不一致')
    shots = {s['id']: s for s in plan['shots']}
    order = {s['id']: i for i, s in enumerate(plan['shots'])}
    cues = {c['id']: c for c in plan.get('typography_cues', [])}
    delivered, positions, end_positions = set(), {}, {}
    spans = {}
    cursor = 0
    for segment in (timeline or {}).get('tracks', [{}])[0].get('segments', []):
        sid = segment.get('shot_id')
        spans[sid] = dict(segment, timeline_start=cursor)
        cursor += segment['source_out_frame'] - segment['source_in_frame']
    for fact in facts.values():
        paragraph = paragraphs.get(fact.get('paragraph_id'), '')
        if fact.get('paragraph_id') not in declared:
            problems.append(f"{fact['id']} 的证据不属于当前篇原文")
        if not fact.get('evidence') or fact['evidence'] not in paragraph:
            problems.append(f"{fact['id']} 缺少匹配原文的证据")
    covered = {f.get('paragraph_id') for f in facts.values()}
    dispositions = {p['paragraph_id']: p for p in contract.get('paragraph_disposition', [])}
    for pid in declared - covered:
        disposition = dispositions.get(pid, {})
        if disposition.get('kind') not in ('commentary', 'reference') or not disposition.get('reason'):
            problems.append('原文段落未核对剧情或说明省略理由：' + pid)
    requirements = contract.get('requirements', [])
    ids = {r['id'] for r in requirements}
    present_beats = {r.get('beat') for r in requirements}
    for beat in BEATS:
        if beat not in present_beats:
            problems.append('故事缺少结构节点：' + beat)
    for requirement in requirements:
        rid = requirement['id']
        if not requirement.get('audience_question') or not requirement.get('answer'):
            problems.append(rid + ' 未写清观众需要理解的问题和答案')
        refs = requirement.get('facts', [])
        if not refs or any(fid not in facts for fid in refs):
            problems.append(rid + ' 缺少有效的原文事实绑定')
        deliveries = requirement.get('deliveries', [])
        if not deliveries:
            problems.append(rid + ' 只有制作说明，没有画面或声音交付')
        has_explicit_delivery = False
        valid_positions = []
        for delivery in deliveries:
            sid, kind = delivery.get('shot_id'), delivery.get('kind')
            delivered_facts = delivery.get('facts', [])
            if not delivered_facts or any(fid not in refs for fid in delivered_facts):
                problems.append(rid + ' 的每条交付必须绑定其具体原文事实')
            else:
                delivered.update(delivered_facts)
            shot = shots.get(sid)
            if not shot:
                problems.append(rid + ' 引用不存在的镜头：' + str(sid)); continue
            valid_positions.append(order[sid])
            if kind == 'dialogue':
                actual = ''.join(line['text'] for line in shot.get('spoken_lines', []))
                if not delivery.get('text') or delivery['text'] not in actual:
                    problems.append(rid + ' 的关键信息未写进实际对白：' + sid)
                else:
                    has_explicit_delivery = True
            elif kind == 'text':
                cue = cues.get(delivery.get('cue_id'), {})
                if cue.get('shot_id') != sid or not delivery.get('text') or delivery['text'] not in cue.get('text', ''):
                    problems.append(rid + ' 缺少实际文字合成指令：' + sid)
                else:
                    has_explicit_delivery = True
                    if not 0 <= cue.get('start_seconds', -1) < cue.get('end_seconds', -1):
                        problems.append(rid + ' 的文字窗口无效：' + sid)
                    if shot.get('duration_seconds') is not None and cue.get('end_seconds', 0) > shot['duration_seconds']:
                        problems.append(rid + ' 的关键文字超出镜头计划时长：' + sid)
            elif kind == 'visual':
                action = delivery.get('action_evidence')
                if not action or action not in shot.get('action', ''):
                    problems.append(rid + ' 的动作只存在于剧情摘要：' + sid)
                pending.append({'requirement': rid, 'shot_id': sid, 'event': delivery.get('event'),
                                'status': 'needs_actual_visual_review'})
            else:
                problems.append(rid + ' 的交付类型无效')
            if timeline is not None:
                span = spans.get(sid)
                if span is None:
                    problems.append(rid + ' 的关键镜头被剪辑删除：' + sid); continue
                if kind == 'text':
                    retained = [c for c in timeline.get('typography', []) if c.get('id') == delivery.get('cue_id')]
                    minimum = delivery.get('minimum_seconds', 0)
                    if not retained or any((c['end_frame']-c['start_frame'])/24 < minimum for c in retained):
                        problems.append(rid + ' 的关键文字未保留足够阅读时间：' + sid)
                elif kind == 'visual':
                    interval = delivery.get('source_interval_frames')
                    if not interval or not span['source_in_frame'] <= interval[0] < interval[1] <= span['source_out_frame']:
                        problems.append(rid + ' 的必要动作入出点尚未确认或被剪掉：' + sid)
                elif kind == 'dialogue':
                    # The edit's subtitle window must carry the exact locked line.
                    if not any(delivery['text'] in c['text']
                            and span['timeline_start'] <= c['start_frame'] < c['end_frame']
                            <= span['timeline_start'] + span['source_out_frame'] - span['source_in_frame']
                            for c in timeline.get('subtitles', [])):
                        problems.append(rid + ' 的关键对白未完整留在剪辑时间线：' + sid)
        if requirement.get('explicit_required') and not has_explicit_delivery:
            problems.append(rid + ' 必须通过对白或可读文字明确传达，不能只靠未验看的动作')
        if valid_positions:
            positions[rid] = min(valid_positions)
            end_positions[rid] = max(valid_positions)
    for requirement in requirements:
        rid = requirement['id']
        for previous in requirement.get('depends_on', []):
            if previous not in ids:
                problems.append(rid + ' 引用未知因果前提：' + previous)
            elif rid in positions and previous in positions and positions[previous] > positions[rid]:
                problems.append(rid + ' 出现在其因果前提之前：' + previous)
    for fact in facts.values():
        if fact.get('required', True) and fact['id'] not in delivered:
            problems.append('原文核心事实未落实到观众交付：' + fact['id'])
    ordered = [r for r in requirements if r['id'] in positions]
    if ordered:
        setups = [positions[r['id']] for r in ordered if r['beat'] == 'setup']
        closures = [end_positions[r['id']] for r in ordered if r['beat'] == 'closure']
        if setups and min(setups) > 1:
            problems.append('开场背景直到后段才出现')
        if closures and max(closures) < len(plan['shots']) - 3:
            problems.append('结尾落点未出现在最后一段')
    return {'schema': 'chapter_narrative_check_v1', 'passed': not problems,
            'scope': 'Authored source, causal order and retained edit delivery; not viewer comprehension or film acceptance',
            'phase': 'edit' if timeline is not None else 'script', 'problems': problems,
            'requirements': len(requirements), 'facts': len(facts), 'pending_visual_review': pending,
            'contract_sha256': digest(contract), 'plan_sha256': digest(plan),
            'human_understood_story': False, 'release_approved': False}


def preflight(root, plan_path, timeline=None):
    plan_path = Path(plan_path)
    plan = read(plan_path)
    contract_path = plan_path.parent / 'narrative_contract.json'
    if not contract_path.is_file():
        raise ValueError('Missing narrative_contract.json: author the opening, causal chain and ending before chapter production')
    report = check(root, plan, read(contract_path), timeline)
    write(plan_path.parent / ('narrative_edit_check.json' if timeline is not None else 'narrative_script_check.json'), report)
    if not report['passed']:
        raise ValueError('Story completeness check failed: ' + '; '.join(report['problems']))
    return report

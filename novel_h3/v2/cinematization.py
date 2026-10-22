"""Source-bound filmable screenplay between adaptation and native H3 production."""
from pathlib import Path

from ..project import file_hash, inside, read, safe_id, write
from ..ref2va import AUTHORING_INSTRUCTION

VERSION = 'filmable_screenplay_v1'
INSTRUCTION = """完整阅读原文与已有白话剧本，然后进行剧本影视化，不按句子配漂亮画面。
用场景目标、阻力、关键选择、转折及后果组织因果；压缩重复反应和无信息的行进。
身份、关系、地点、时间跳转和结局必须通过实际对白、动作或后期文字向观众交代。
每镜只拍一个可完成的动作节拍，明确起止状态、空间轴线、屏幕方向和有动机的运镜。
continuous 镜头须继承同地点、同轴线和前镜结束状态；coverage 为同一时刻换视点，
ellipsis 为明确交代的时间省略，scene_change 为有原因的换场。每个转场填写观众能看见或听见的承接。
H3 每段4–15秒、一个发声者。对白自然白话，不改变原文事实、顺序、数量、动机和结果。
完整保留考题、卷文及现存诗句；不要虚构缺失情节或让字幕代替全部表演。默认无配乐。
返回 request_sha256、plan、editorial_notes。plan 是完整新版拍摄计划。
scenes 包含 id、title、source_paragraph_ids、goal、conflict、turn、change、causal_transition、script。
每镜含 narrative_scene_id、source_paragraph_ids、facts 和 cinematic_execution：
beat_id、axis_id、screen_direction、transition{type,previous_shot_id,reason,audience_cue}。
实际 action、start_state、end_state、camera、eyeline、spoken_lines、soundscape 必须与影视剧本一致。
同时更新 narrative_contract.json 和 editorial_blueprint.json；结构通过不能标为影视人审通过。
""" + '\n' + AUTHORING_INSTRUCTION


def prepare(root, source_plan, directory):
    root = Path(root).resolve()
    source_plan = Path(source_plan).resolve()
    directory = Path(directory).resolve()
    if not source_plan.is_relative_to(root) or not directory.is_relative_to(root):
        raise ValueError('Film screenplay must belong to this project')
    if source_plan.parent == directory:
        raise ValueError('Keep the input script in its original revision; use a new output directory')
    plan = read(source_plan)
    section = plan['chapter_id'].removeprefix('chapter_')
    paragraphs = [p for p in read(root / 'paragraphs.json') if p.get('section') == section]
    if not paragraphs or {p['id'] for p in paragraphs} != set(plan['source_paragraph_ids']):
        raise ValueError('Film screenplay requires the complete chapter source')
    script = source_plan.parent / 'screenplay.md'
    request = {'schema': VERSION, 'chapter_id': plan['chapter_id'], 'instruction': INSTRUCTION,
        'source_plan_path': str(source_plan.relative_to(root)), 'source_plan_sha256': file_hash(source_plan),
        'paragraphs': paragraphs, 'input_plan': plan,
        'source_script_path': str(script.relative_to(root)) if script.is_file() else None,
        'source_script_sha256': file_hash(script) if script.is_file() else None,
        'source_script': script.read_text() if script.is_file() else ''}
    path = directory / 'cinematization_request.json'
    if path.exists() and read(path) != request:
        raise ValueError('Film screenplay request changed; use a new revision')
    write(path, request)
    return path


def _text(row, fields):
    if any(not isinstance(row.get(k), str) or not row[k].strip() for k in fields):
        raise ValueError('Film screenplay requires nonempty fields: ' + ', '.join(fields))


def validate(request, plan):
    if (plan.get('chapter_id') != request['chapter_id']
            or set(plan.get('source_paragraph_ids', [])) != {p['id'] for p in request['paragraphs']}
            or plan.get('source_document_sha256') != request['input_plan'].get('source_document_sha256')):
        raise ValueError('Film screenplay changed its complete source binding')
    scenes, shots = plan.get('scenes', []), plan.get('shots', [])
    if not scenes or not shots:
        raise ValueError('Film screenplay requires scenes and actionable shots')
    scene_ids, covered, shot_ids, beat_ids = set(), set(), set(), set()
    source_ids = set(plan['source_paragraph_ids'])
    facts = {f['id'] for f in plan.get('source_fact_ledger', [])}
    for scene in scenes:
        _text(scene, ('id', 'title', 'goal', 'conflict', 'turn', 'change', 'causal_transition', 'script'))
        safe_id(scene['id'])
        if scene['id'] in scene_ids or not set(scene.get('source_paragraph_ids', [])) or not set(scene['source_paragraph_ids']) <= source_ids:
            raise ValueError('Film scene IDs and source paragraphs must be valid')
        scene_ids.add(scene['id'])
        covered.update(scene['source_paragraph_ids'])
    if covered != source_ids:
        raise ValueError('Film scenes must cover the complete source including the ending')
    previous = None
    seen_scenes = []
    for shot in shots:
        safe_id(shot['id'])
        _text(shot, ('action', 'start_state', 'end_state', 'eyeline', 'soundscape'))
        if shot['id'] in shot_ids or shot.get('narrative_scene_id') not in scene_ids:
            raise ValueError('Film shots must bind unique IDs and known scenes')
        shot_ids.add(shot['id'])
        if not seen_scenes or seen_scenes[-1] != shot['narrative_scene_id']:
            seen_scenes.append(shot['narrative_scene_id'])
        pids = set(shot.get('source_paragraph_ids', []))
        scene = next(s for s in scenes if s['id'] == shot['narrative_scene_id'])
        if not pids or not pids <= set(scene['source_paragraph_ids']) or not shot.get('facts') or not set(shot['facts']) <= facts:
            raise ValueError('Film beat requires scene-local source paragraphs and facts')
        camera = shot.get('camera')
        if not isinstance(camera, (str, dict)) or not camera:
            raise ValueError('Film beat requires an authored camera')
        execution = shot.get('cinematic_execution', {})
        _text(execution, ('beat_id', 'axis_id', 'screen_direction'))
        safe_id(execution['beat_id'])
        if execution['beat_id'] in beat_ids:
            raise ValueError('Film beat IDs must be unique')
        beat_ids.add(execution['beat_id'])
        transition = execution.get('transition', {})
        _text(transition, ('reason', 'audience_cue'))
        mode = transition.get('type')
        if (mode not in ('opening', 'continuous', 'coverage', 'ellipsis', 'scene_change')
                or (mode == 'opening') != (previous is None)
                or transition.get('previous_shot_id') != (previous['id'] if previous else None)):
            raise ValueError('Film transition must bind the actual previous shot')
        if previous and mode in ('continuous', 'coverage'):
            if (shot['scene_id'] != previous['scene_id']
                    or any(execution[k] != previous['cinematic_execution'][k] for k in ('axis_id', 'screen_direction'))):
                raise ValueError('Continuous coverage must preserve location, axis and direction')
            if mode == 'continuous' and shot['start_state'] != previous['end_state']:
                raise ValueError('Continuous action resets the previous end state')
        previous = shot
    if seen_scenes != [s['id'] for s in scenes]:
        raise ValueError('Film shots must follow the causal scene order without orphan scenes')
    return {'passed': True, 'scenes': len(scenes), 'beats': len(shots),
        'scope': 'Authored source, action and transition bindings only; actual film continuity needs viewing',
        'human_understood_story': False, 'release_approved': False}


def screenplay_text(plan):
    lines = [f"# {plan.get('title', '剧本影视化')}", '', '本稿为影视化编排；成片理解与影视质量须实际看片。', '']
    for scene in plan['scenes']:
        lines.extend([f"## {scene['id']} · {scene['title']}", f"目标：{scene['goal']}",
            f"阻力：{scene['conflict']}", f"转折：{scene['turn']}", f"后果：{scene['change']}",
            f"承接：{scene['causal_transition']}", '', scene['script'], ''])
        for shot in (s for s in plan['shots'] if s['narrative_scene_id'] == scene['id']):
            transition = shot['cinematic_execution']['transition']
            lines.extend([f"### {shot['id']} · {shot.get('title', '')}",
                f"观众承接：{transition['audience_cue']}", f"动作：{shot['action']}",
                f"起始：{shot['start_state']}", f"结束：{shot['end_state']}", f"摄影：{shot['camera']}",
                *[f"{line['speaker']}：{line['text']}" for line in shot.get('spoken_lines', [])], ''])
    return '\n'.join(lines)


def accept(root, directory, response):
    root, directory = Path(root).resolve(), Path(directory).resolve()
    path = directory / 'cinematization_request.json'
    request = read(path)
    if response.get('request_sha256') != file_hash(path) or not response.get('editorial_notes'):
        raise ValueError('Film screenplay response needs matching request and editorial notes')
    plan = response['plan']
    if plan.get('cinematization'):
        raise ValueError('Film screenplay response must not contain a previous binding')
    report = validate(request, plan)
    screenplay = directory / 'cinematic_screenplay.json'
    write(screenplay, plan)
    (directory / 'cinematic_screenplay.md').write_text(screenplay_text(plan), encoding='utf-8')
    write(directory / 'cinematization_check.json', dict(report, editorial_notes=response['editorial_notes']))
    binding = {'path': str(screenplay.relative_to(root)), 'sha256': file_hash(screenplay),
        'request_sha256': file_hash(path), 'check_sha256': file_hash(directory / 'cinematization_check.json')}
    bound = dict(plan, cinematization_required=True, cinematization=binding)
    write(directory / 'chapter_plan.json', bound)
    require(root, bound)
    return directory / 'chapter_plan.json'


def shot_content(shot):
    keys = ('id', 'scene_id', 'narrative_scene_id', 'source_paragraph_ids', 'facts', 'cast', 'references',
        'views', 'action', 'start_state', 'end_state', 'camera', 'eyeline', 'soundscape',
        'performance_direction', 'cinematic_execution')
    content = {**{k: shot.get(k) for k in keys}, 'spoken_lines': [
        {k: line.get(k) for k in ('speaker', 'text', 'offscreen')} for line in shot.get('spoken_lines', [])]}
    if shot.get('visual_reference_scope') is not None:
        content['visual_reference_scope'] = shot['visual_reference_scope']
    if shot.get('generation_prompt_focus') is not None:
        content['generation_prompt_focus'] = shot['generation_prompt_focus']
    if shot.get('ref2va_sections') is not None:
        content['ref2va_sections'] = shot['ref2va_sections']
    if shot.get('additional_visible_people') is not None:
        content['additional_visible_people'] = shot['additional_visible_people']
    return content


def require(root, plan):
    binding = plan.get('cinematization', {})
    if not binding.get('path'):
        raise ValueError('Missing filmable screenplay: run prepare_cinematic_chapter.py before production')
    path = inside(root, binding['path'])
    request_path, check_path = path.parent / 'cinematization_request.json', path.parent / 'cinematization_check.json'
    if (file_hash(path) != binding['sha256'] or file_hash(request_path) != binding['request_sha256']
            or file_hash(check_path) != binding['check_sha256']):
        raise ValueError('Film screenplay or validation binding is stale')
    request, original = read(request_path), read(path)
    current = [p for p in read(Path(root) / 'paragraphs.json') if p.get('section') == request['chapter_id'].removeprefix('chapter_')]
    if (current != request['paragraphs'] or file_hash(inside(root, request['source_plan_path'])) != request['source_plan_sha256']
            or request['source_script_path'] and file_hash(inside(root, request['source_script_path'])) != request['source_script_sha256']):
        raise ValueError('Source changed after screenplay cinematization')
    report = validate(request, original)
    if (plan.get('chapter_id') != original['chapter_id']
            or plan.get('typography_cues', []) != original.get('typography_cues', [])
            or plan.get('source_paragraph_ids') != original['source_paragraph_ids']):
        raise ValueError('Production plan differs from its film screenplay')
    authored = {s['id']: s for s in original['shots']}
    order = [s['id'] for s in original['shots']]
    actual = [s['id'] for s in plan['shots']]
    if actual != [sid for sid in order if sid in actual]:
        raise ValueError('Production changed film beat order')
    for shot in plan['shots']:
        if shot_content(shot) != shot_content(authored[shot['id']]):
            raise ValueError('Production changed film action or dialogue: ' + shot['id'])
    return report

"""Render and check the official six-section full-reference prompt contract."""
import re

SECTIONS = ('subject_definitions', 'summary', 'retention_analysis',
            'detailed_description', 'overall_soundscape', 'non_diegetic_music')
LABEL = r'<(?:Subject|Picture|Video|Audio) \d+>'
POLICY_VERSION = 'official_ref2va_six_sections_v1'
AUTHORING_INSTRUCTION = """本仓库所有 H3、VDN-H3、FastH3 的新 Ref2VA 提示词均遵守官方全参考规范。
每镜编写 ref2va_sections，按顺序包含 subject_definitions、summary、retention_analysis、
detailed_description、overall_soundscape、non_diegetic_music 六个非空英文段落。
使用 {subject:asset_id}、{picture:asset_id}、{audio:asset_id} 绑定真实素材，禁止猜测上传编号。
summary 以实际任务类型开头，如 [reference generation + audio reference]；无音频参考不可虚构音频关系。
保留关系使用官方 fully_preserved、partially_preserved、attribute_transfer、weak_reference；音频使用
fully_copy、partially_copy、reference、weak_reference。注明实际出现镜头，不在保留分析中分配 S 编号。
详细描述先写英文风格开场，再写 [Shot 1]；后续切镜写 [Shot N] At MM:SS.mmm 并符合实际时长。
按可见动作、构图、光线、起止状态、镜头运动和同步声音展开，生成任务通常为350–500英文词；
对白密集时优先完整承载对白时间线，禁止截断、填充或压缩叙事来机械凑字数。
实际发声者按首次发声顺序使用稳定的 (S1)、(S2)，声音参考定义复用同一编号。
对白和歌词只写在 <d>[原语言] 原文</d> 内；可见文字用英文双引号保留原文，正文保持英文。
完整保留既定对白、角色归属、源文事实和因果，不得用泛泛占位文本替代动作或翻译后遗漏信息。
默认 non_diegetic_music 为 N/A；只有明确要求配乐时才描述配乐。成片质量仍须实际审片。
cast 只列本镜实际可见的人物，群体按真实成员数量计数。画外人物只能描述为画外，不得粘贴全场人物站位。
无名人物（包括只露手臂者）逐人列入 additional_visible_people；一个角色身份只对应一个身体，不能填充其他考生或官员。
场景参考仅提供建筑和光线；检查实际图片中的人像、神像、倒影，不能把生成图的无人物提示词当成图片审查结果。
"""


def population_text(visuals, additional_visible_people=()):
    """Keep physical people distinct from image count and voice-only identities."""
    if not visuals or any('kind' not in ref for ref in visuals):
        return ''  # Raw format-only callers have no cast inventory.
    if not isinstance(additional_visible_people, (list, tuple)) or any(
            not isinstance(person, str) or not person.strip() or re.search(r'[\u3400-\u9fff{}<>]', person)
            for person in additional_visible_people):
        raise ValueError('Additional visible people must be individual English descriptions')
    cast = [ref for ref in visuals if ref['kind'] == 'character' and ref.get('visible', True)]
    if any(type(ref.get('instances', 1)) is not int or ref.get('instances', 1) < 1 for ref in cast):
        raise ValueError('Visible character instances must be positive integers')
    count = sum(ref.get('instances', 1) for ref in cast) + len(additional_visible_people)
    lines = [f'Visible population: exactly {count} people in this shot, including partly visible bodies.']
    for ref in cast:
        n = ref.get('instances', 1)
        lines.append(f"{ref['subject']} contributes exactly {n} distinct person(s), each appearing once with one physical body.")
    for i, person in enumerate(additional_visible_people, 1):
        lines.append(f'Additional person {i}: {person.strip()}')
    if count == 0:
        lines.append('No people are visible, including hands or partial bodies.')
    lines.append('Keep different people distinct in face, costume and position. A foreground identity has no second copy in the background. '
                 'The scene reference supplies architecture, materials and light only; human likenesses in it do not supply cast. '
                 'All people outside this visible population remain fully offscreen, without extra faces, bodies, portraits, human-shaped statues, reflections or silhouettes.')
    return ' '.join(lines)


def with_population(prompt, visuals, additional_visible_people=()):
    text = population_text(visuals, additional_visible_people)
    if text and text not in prompt:
        head, marker, detail = prompt.partition('detailed_description:\n')
        prompt = head + marker + detail.replace('[Shot 1]', '[Shot 1] ' + text + '\n', 1)
    return prompt


def render(sections, visuals, voices, spoken_lines, *, videos=(), duration_seconds=None, single_shot=False, no_music=True,
           additional_visible_people=()):
    if list(sections) != list(SECTIONS):
        raise ValueError('Ref2VA requires all six official sections in their fixed order')
    labels = {}
    for ref in visuals:
        labels['subject:' + ref['asset_id']] = ref['subject']
        labels['picture:' + ref['asset_id']] = ref['picture']
    for ref in voices:
        labels['audio:' + ref['asset_id']] = ref['audio']
    for ref in videos:
        labels['video:' + ref['asset_id']] = ref['video']

    def bind(match):
        name = match.group(1)
        if name not in labels:
            raise ValueError('Unbound Ref2VA asset: ' + name)
        return labels[name]

    if any(not isinstance(value, str) or not value.strip() for value in sections.values()):
        raise ValueError('Ref2VA sections must contain nonempty authored text')
    bound = {k: re.sub(r'\{((?:subject|picture|audio|video):[^{}]+)\}', bind, v)
             for k, v in sections.items()}
    prompt = '\n\n'.join(k + ':\n' + bound[k].strip() for k in SECTIONS)
    prompt = with_population(prompt, visuals, additional_visible_people)
    validate(prompt, visuals, voices, spoken_lines, videos=videos, duration_seconds=duration_seconds,
             single_shot=single_shot, no_music=no_music, additional_visible_people=additional_visible_people)
    return prompt


def validate(prompt, visuals, voices, spoken_lines=(), *, videos=(), duration_seconds=None,
             single_shot=False, no_music=False, additional_visible_people=(), require_population=False,
             require_voice_bindings=False):
    if not (visuals or voices or videos):
        raise ValueError('Ref2VA requires actual reference media')
    if re.search(r'\{(?:subject|picture|audio|video):[^{}]+\}', prompt):
        raise ValueError('Ref2VA contains an unresolved asset placeholder')
    headings = re.findall(r'(?m)^([a-z_]+):\s*$', prompt)
    if headings != list(SECTIONS):
        raise ValueError('Ref2VA section names/order do not match the official guide')
    parts = re.split(r'(?m)^[a-z_]+:\s*\n', prompt)[1:]
    sections = dict(zip(SECTIONS, parts))
    if any(not text.strip() for text in sections.values()):
        raise ValueError('Ref2VA sections must not be empty')
    if require_population and any(ref.get('kind') not in ('character', 'scene', 'prop') for ref in visuals):
        raise ValueError('Ref2VA submission requires complete visible population metadata')
    ids = [ref['asset_id'] for ref in visuals]
    hashes = [ref['generation_sha256'] for ref in visuals if ref.get('generation_sha256')]
    if len(ids) != len(set(ids)) or len(hashes) != len(set(hashes)):
        raise ValueError('Ref2VA duplicate image inputs cannot create distinct subjects')
    population = population_text(visuals, additional_visible_people)
    if population and population not in sections['detailed_description']:
        raise ValueError('Ref2VA visible population contract is missing or changed')
    prose = re.sub(r'<d>.*?</d>', '', prompt, flags=re.S)
    # The official guide preserves visible scene text inside English quotes.
    prose = re.sub(r'(?i)\b(?:reading|reads|text|label|sign|inscription)\s*:?\s*"[^"\n]*"', '', prose)
    if re.search(r'[\u3400-\u9fff]', prose):
        raise ValueError('Ref2VA descriptive prose must be English')
    prefix = re.match(r'\[([^\]]+)\]', sections['summary'].strip())
    tasks = prefix[1].split(' + ') if prefix else []
    allowed = {'reference generation', 'audio reference', 'audio reuse', 'keyframe completion', 'video editing', 'video continuation'}
    if not tasks or len(set(tasks)) != len(tasks) or set(tasks) - allowed:
        raise ValueError('Ref2VA summary requires the official task-type prefix')
    if bool(set(tasks) & {'audio reference', 'audio reuse'}) != bool(voices):
        raise ValueError('Ref2VA audio task types must match actual audio inputs')
    if set(tasks) & {'video editing', 'video continuation'} and not videos:
        raise ValueError('Ref2VA video task types require an actual video input')
    known = {r[k] for r in visuals for k in ('subject', 'picture')}
    known.update(r['audio'] for r in voices)
    known.update(r['video'] for r in videos)
    references = re.findall(r'<(?:Subject|Picture|Video|Audio)\b[^>]*>', prompt, flags=re.I)
    if any(not re.fullmatch(LABEL, label) for label in references):
        raise ValueError('Ref2VA contains a malformed reference label')
    if set(re.findall(LABEL, prompt)) - known:
        raise ValueError('Ref2VA prompt contains a reference without a media input')
    for ref in visuals:
        if ref['subject'] not in sections['subject_definitions'] or ref['picture'] not in sections['subject_definitions']:
            raise ValueError('Every image must have an explicit subject/source binding')
        if not re.search(re.escape(ref['subject']) + r' \(appears in \[Shot \d+\](?:, \[Shot \d+\])*\): (?:fully_preserved|partially_preserved|attribute_transfer|weak_reference) - ', sections['retention_analysis']):
            raise ValueError('Ref2VA visual retention requires a fixed relationship marker and shot')
    for ref in voices:
        if not re.search(re.escape(ref['audio']) + r': (?:fully_copy|partially_copy|reference|weak_reference) - ', sections['retention_analysis']):
            raise ValueError('Ref2VA audio retention requires a fixed relationship marker')
        if ref['audio'] not in sections['subject_definitions']:
            raise ValueError('Every audio reference needs an explicit source definition')
    if re.search(r'\(S\d+\)', sections['retention_analysis']):
        raise ValueError('Ref2VA retention analysis must not assign speaker IDs')
    for ref in videos:
        if ref['video'] not in sections['subject_definitions'] or not re.search(
                re.escape(ref['video']) + r' \(appears in \[Shot \d+\]\): (?:fully_preserved|partially_preserved|attribute_transfer|weak_reference) - ', sections['retention_analysis']):
            raise ValueError('Every video reference needs its source definition and retention relationship')
    detail = sections['detailed_description']
    appearance_detail = detail.replace(population, '', 1) if population else detail
    if '[Shot 1]' not in detail or not detail.split('[Shot 1]')[0].strip():
        raise ValueError('Ref2VA needs a style introduction before the opening shot')
    shots = [int(n) for n in re.findall(r'(?m)^\[Shot (\d+)\]', detail)]
    if shots != list(range(1, len(shots) + 1)):
        raise ValueError('Ref2VA shots must appear once in consecutive playback order')
    if single_shot and len(shots) != 1:
        raise ValueError('This production plan authors one continuous shot per model request')
    if set(map(int, re.findall(r'\[Shot (\d+)\]', sections['retention_analysis']))) - set(shots):
        raise ValueError('Ref2VA retention analysis names an absent shot')
    for ref in [*visuals, *voices, *videos]:
        label = ref.get('subject') if ref in visuals else ref.get('audio') if ref in voices else ref.get('video')
        if label not in appearance_detail:
            raise ValueError('A defined subject must be bound at its actual appearance')
    spoken = re.findall(r'<d>\[([^\]]+)\]\s*(.*?)</d>', detail, flags=re.S)
    if (len(spoken) != detail.count('<d>') or len(spoken) != detail.count('</d>')
            or any(not words.strip() for _, words in spoken)):
        raise ValueError('Every Ref2VA dialogue block needs a language and exact spoken text')
    if ''.join(words for _, words in spoken) != ''.join(line['text'] for line in spoken_lines):
        raise ValueError('The literal authored dialogue is missing or changed in the model prompt')
    speaker_order, speaker_subjects = [], {}
    for event in re.finditer(r'<d>', detail):
        before = detail[:event.start()]
        ids = list(re.finditer(r'\(S(\d+)\)', before))
        if not ids:
            raise ValueError('Every Ref2VA vocal event needs its actual speaker ID')
        sid = int(ids[-1][1])
        if sid not in speaker_order:
            speaker_order.append(sid)
        owner = re.search(r'(<Subject \d+>)\s*$', before[:ids[-1].start()])
        if owner:
            if sid in speaker_subjects and speaker_subjects[sid] != owner[1]:
                raise ValueError('One Ref2VA speaker ID cannot refer to different subjects')
            speaker_subjects[sid] = owner[1]
    if speaker_order != list(range(1, len(speaker_order) + 1)):
        raise ValueError('Ref2VA speaker IDs must follow actual first-vocal order')
    declared_speakers = list(dict.fromkeys(line['speaker'] for line in spoken_lines))
    by_asset = {v['asset_id']: v['subject'] for v in visuals if v.get('asset_id')}
    for sid, speaker in enumerate(declared_speakers, 1):
        line = next(line for line in spoken_lines if line['speaker'] == speaker)
        expected = line.get('speaker_subject') or by_asset.get(speaker)
        if expected and speaker_subjects.get(sid) != expected:
            raise ValueError('Ref2VA vocal event does not belong to its declared subject')
    if require_voice_bindings and spoken_lines:
        voice_subjects = {voice.get('subject') for voice in voices}
        for line in spoken_lines:
            expected = line.get('speaker_subject')
            if expected is None:
                if None not in voice_subjects:
                    raise ValueError('Every speaker needs a voice reference; off-screen speakers need an explicit voice-only reference')
            elif expected not in voice_subjects:
                raise ValueError(f'Speaker subject {expected} has no voice reference')
        for event in re.finditer(r'<d>', detail):
            before = detail[:event.start()]
            if not re.search(r'<Audio \d+>[^\n]{0,300}$', before):
                raise ValueError('Every spoken line needs an explicit <Audio N> voice binding before the dialogue')
    for voice in voices:
        subject = voice.get('subject')
        if subject and subject in speaker_subjects.values():
            sid = next(s for s, owner in speaker_subjects.items() if owner == subject)
            if not re.search(re.escape(voice['audio']) + r'[^\n]*' + re.escape(subject) + rf' \(S{sid}\)', sections['subject_definitions']):
                raise ValueError('Audio definition and actual speaker ID disagree')
    cut_times = []
    for number in shots[1:]:
        cut = re.search(rf'\[Shot {number}\] At (\d+):(\d{{2}})\.(\d{{3}})', detail)
        if not cut:
            raise ValueError('Later Ref2VA shots need exact cut timestamps')
        cut_times.append(int(cut[1]) * 60 + int(cut[2]) + int(cut[3]) / 1000)
    if cut_times != sorted(set(cut_times)):
        raise ValueError('Ref2VA cut timestamps must increase')
    if duration_seconds is not None:
        times = [int(m) * 60 + int(s) + int(ms) / 1000 for m, s, ms in re.findall(r'(?<!\d)(\d+):(\d{2})\.(\d{3})', detail)]
        # End timestamps use millisecond notation for a rational 24 fps frame boundary.
        if any(t > duration_seconds + .0005 for t in times) or any(t >= duration_seconds for t in cut_times):
            raise ValueError('Ref2VA timing exceeds the actual generated duration')
    if no_music and sections['non_diegetic_music'].strip() != 'N/A':
        raise ValueError('This chapter must not contain background music')
    return {'passed': True, 'schema': POLICY_VERSION,
            'scope': 'Prompt syntax and asset bindings; not model output quality'}


def legacy_inputs(shot):
    package = {r['asset_id']: r for r in shot.get('asset_package', {}).get('visual_assets', []) if r.get('asset_id')}
    visuals = []
    for i, ref in enumerate(shot.get('references', []), 1):
        visual = {'asset_id': ref['asset_id'], 'subject': f'<Subject {i}>', 'picture': f'<Picture {i}>'}
        if ref['asset_id'] in package:
            item = package[ref['asset_id']]
            visual.update(kind=item['kind'], instances=item.get('expected_instances') or 1,
                          visible=item.get('role') != 'offscreen_voice_identity',
                          generation_sha256=item.get('generation_sha256'))
        visuals.append(visual)
    voices = [{'asset_id': b.get('asset_id') or b['speaker'], 'audio': f"<Audio {b['audio']}>",
               'subject': f"<Subject {b['picture']}>" if b.get('picture') else None}
              for b in shot.get('speech_bindings', [])]
    videos = [{'asset_id': 'spatial_guide', 'video': '<Video 1>'}] if shot.get('spatial_guide') else []
    return visuals, voices, videos


def validate_legacy(shot, prompt, *, require_population=False):
    if shot.get('mode') != 'ref2va':
        return None
    visuals, voices, videos = legacy_inputs(shot)
    bindings = {b['speaker']: b for b in shot.get('speech_bindings', [])}
    lines = [dict(line, speaker_subject=(f"<Subject {bindings[line['speaker']]['picture']}>"
        if bindings.get(line['speaker'], {}).get('picture') else None)) for line in shot.get('dialogue', [])]
    return validate(prompt, visuals, voices, lines, videos=videos,
                    duration_seconds=shot.get('frames', 360) / 24, no_music=True,
                    additional_visible_people=shot.get('additional_visible_people', []), require_population=require_population)

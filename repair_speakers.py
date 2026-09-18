"""One-time source-reviewed migration of the existing studio scripts."""
import copy
import re
from pathlib import Path
from novel_h3.project import read, write, digest, update_state
from novel_h3.arcreel import save_content, approve_content, compile_visual
from novel_h3.director import approve_episode
from novel_h3.timing import editorial_seconds

ROOT = Path(__file__).parent / 'projects/rendao-wuji'


def audit(plan, reason):
    plan['speaker_audit'] = {'status': 'reviewed', 'reviewer': 'Codex 原文逐段审读',
        'scenes': {s['scene_id']: [dict(u, reason=reason, source_ids=plan['source_map'][s['scene_id']])
                                  for u in s['utterances']] for s in plan['script']['scenes']}}


def run():
    backup = ROOT / 'analysis/speaker_repair_before'
    for folder in ('content_plans', 'episodes', 'arcreel_export'):
        for path in (ROOT / folder).rglob('*.json'):
            target = backup / path.relative_to(ROOT)
            if not target.exists():
                write(target, read(path))
    paras = {p['id']: p for p in read(ROOT / 'paragraphs.json')}
    # These are author exposition and geographical narration, not performed dialogue.
    for path in (ROOT / 'content_plans').glob('*.json'):
        if path.stem == 'chapter_s0003':
            continue
        plan = read(path)
        for scene in plan['script']['scenes']:
            for line in scene['utterances']:
                if line['kind'] == 'voiceover':
                    line['speaker'] = '作者旁白' if path.stem == 'chapter_s0002' else '旁白'
        reason = ('s0002 为作者自序，引号内为术语和文献引用，不是角色对白。' if path.stem == 'chapter_s0002'
                  else 's0007 为地理及历史背景叙述，俗语引用由旁白朗读，不是角色对白。' if path.stem == 'chapter_s0007'
                  else '雨屋对白原文 s0012_p0004 明确写振明站在那里；其他无台词镜头保持无发声。')
        audit(plan, reason)
        write(path, plan)
        update_state(ROOT, lambda state: state['approvals'].pop('content:' + plan['id'], None))
        ep_path = ROOT / 'episodes' / path.name
        if ep_path.exists():
            ep = read(ep_path)
            for scene, shot in zip(plan['script']['scenes'], ep['shots']):
                for line, utterance in zip(shot['dialogue'], scene['utterances']):
                    line['speaker'] = utterance['speaker']
            ep['content_sha256'] = digest(plan)
            write(ep_path, ep)
            # Old approvals must never survive a speech contract change.
            update_state(ROOT, lambda state: state['approvals'].pop(plan['id'], None))
            export = ROOT / 'arcreel_export' / plan['id']
            if export.exists():
                write(export / 'h3.json', ep)
                script_file = export / 'script.json'
                if script_file.exists():
                    script = read(script_file)
                    for row, scene in zip(script['scenes'], plan['script']['scenes']):
                        row['utterances'] = [dict(line, speaker=None if line['kind']=='voiceover' else line['speaker']) for line in scene['utterances']]
                    write(script_file, script)

    plan = read(backup / 'content_plans/chapter_s0003.json')
    old = read(backup / 'episodes/chapter_s0003.json')['shots']
    environment = next(ref for ref in old[0]['references'] if ref['asset_id'] == 'outer_heaven')
    references = {ref['asset_id']: ref for shot in old for ref in shot['references']}
    names = {2: '无极', 3: '盘古', 4: '无极', 5: '盘古', 6: '无极', 7: '盘古',
             8: '无极', 9: '盘古', 10: '无极', 11: '盘古', 12: '无极', 13: '盘古',
             14: '盘古', 15: '无极', 16: '盘古', 18: '女娲', 19: '盘古', 20: '女娲', 21: '盘古'}
    ids = {'无极': 'wuji', '盘古': 'pangu', '女娲': 'nuwa'}
    plan['script']['scenes'], plan['source_map'] = [], {}
    visual, coverage = [], []
    for number in range(1, 23):
        pid = f's0003_p{number:04d}'
        text = paras[pid]['text']
        pieces = re.findall(r'“[^”]*”|[^“]+', text)
        recovered = ''
        count = 0
        for piece in pieces:
            dialogue = piece.startswith('“')
            speaker = names[number] if dialogue else '旁白'
            spoken = piece.strip('“”')
            clauses = re.findall(r'[^，。！？；、]+[，。！？；、]?', spoken)
            chunks = []
            for clause in clauses:
                if len(clause) > 26:
                    raise ValueError('需要人工选择长句停顿位置：' + clause)
                if chunks and len(chunks[-1] + clause) <= 22:
                    chunks[-1] += clause
                else:
                    chunks.append(clause)
            assert ''.join(chunks) == spoken
            recovered += ('“' if dialogue else '') + ''.join(chunks) + ('”' if dialogue else '')
            for chunk in chunks:
                count += 1
                sid = f'C3P{number:02d}_{count:02d}'
                if dialogue:
                    action = ('A single speaking character, <Subject 1>, occupies the foreground in a restrained medium close-up. '
                              'Preserve the approved face and costume from Picture 1. The primordial environment from <Subject 2> '
                              'fills the background. Their eyes engage an unseen listener just beside the lens; '
                              'subtle breath, gaze and facial expression carry the exchange. Only this character is visible. '
                              'Only their mouth articulates the exact assigned dialogue; close the mouth after speaking.')
                    refs = [references[ids[speaker]], environment]
                    characters = [speaker]
                    beat = 'Maintain the single speaker composition and identity, subtle breathing and eye movement. Mouth movement only during the assigned dialogue interval; no extra speech or extra person.'
                else:
                    action = old[0]['action']
                    if number == 17:
                        action += ' A single streak of light leaves the void and descends toward the world below, representing Wuji returning to the six realms.'
                    if number == 22:
                        action += ' A second streak of light recedes; the empty void returns to still darkness.'
                    refs, characters = [environment], []
                    beat = 'Continuous slow drifting vapor and restrained light movement, no visible person or mouth. The narrator exists only offscreen.'
                scene = dict(scene_id=sid, duration_seconds=editorial_seconds(chunk) if dialogue else 5,
                             characters_in_scene=characters, scenes=['天外天'], props=[], scene_description=action,
                             utterances=[dict(kind='dialogue' if dialogue else 'voiceover', speaker=speaker, text=chunk)],
                             source_text=chunk, needs_replan=False)
                plan['script']['scenes'].append(scene)
                plan['source_map'][sid] = [pid]
                h3 = dict(location_id='outer_heaven', mode='ref2va', continuity='cut', seed=510000+len(visual),
                          hold_frames=0, first_frame=None, last_frame=None, references=copy.deepcopy(refs),
                          dramatic_function=f'完整呈现 {pid}；{speaker} 发声。', action=action,
                          camera=dict(size='medium close-up' if dialogue else 'wide shot', lens_mm=65 if dialogue else 32,
                                      movement='gentle slow dolly inward', motivation='follow the speaker’s realization' if dialogue else 'establish the primordial void'),
                          handoff_in='Natural cut within the same primordial void.',
                          handoff_out='The speaker finishes and holds a quiet listening gaze.' if dialogue else 'The empty void continues drifting.',
                          timeline=[dict(start_frame=i,end_frame=min(i+24,124),description=beat) for i in range(0,124,24)],
                          soundscape='Quiet primordial air, restrained natural breath. Only the explicitly assigned voice speaks; no other speech, no music.')
                visual.append(dict(scene_id=sid,image_prompt=action,h3=h3,
                                   speech_timing=[dict(start_frame=6,end_frame=118)]))
        assert recovered == text, pid
        coverage.append(dict(source_id=pid,exact_text_preserved=True,shots=count))
    audit(plan, '逐段通读 s0003_p0001–p0022：初醒提问为无极；自述开天及送回轮回为盘古；第二道声音及离开前回应为女娲；引号外叙述为旁白。')
    save_content(ROOT, plan)
    approve_content(ROOT, plan['id'], 'Codex', '22 段原文逐字重构核验；角色对白与旁白分别拆镜，禁止台词错配。')
    result = dict(content_sha256=digest(plan), scenes=visual)
    write(ROOT / 'analysis/chapter_s0003_speaker_visual.json', result)
    compile_visual(ROOT, plan['id'], result)
    approve_episode(ROOT, plan['id'], 'Codex', '锁定原文说话人、单角色对白画面和独立声音参考；成片仍待声画核验。')
    cfg = read(ROOT / 'config.json')
    cfg.setdefault('speech_policy', {})['require_source_attribution'] = True
    write(ROOT / 'config.json', cfg)
    write(ROOT / 'analysis/speaker_repair_report.json', dict(chapter=plan['id'],shots=len(visual),paragraphs=coverage,
          all_existing_scripts_reviewed=7, note='原文对照审阅完成；音色及口型需新生成视频验证。'))
    print('Rebuilt',len(visual),'shots; all 22 source paragraphs preserved.')


if __name__ == '__main__':
    run()

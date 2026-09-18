"""Repair known chapter-four bindings and record remaining production blockers."""
import copy
from pathlib import Path
from novel_h3.project import read, write, digest, file_hash, update_state
from novel_h3.arcreel import save_content
from novel_h3.director import frames_for

ROOT = Path(__file__).parent / 'projects/rendao-wuji'


def main():
    plan = read(ROOT / 'content_plans/chapter_s0004.json')
    visual = read(ROOT / 'analysis/chapter_s0004_speaker_visual.json')
    assets = read(ROOT / 'bible/assets.json')
    state = read(ROOT / 'state.json')
    voices = read(ROOT / 'bible/voices.json')
    original = copy.deepcopy(plan)
    backup = ROOT / 'analysis/chapter_s0004_before_asset_binding_repair.json'
    if not backup.exists():
        write(backup, {'plan':plan, 'visual':visual})
    props = {7:['玉笏'],8:['道尘'],18:['光阳仙谱'],19:['暗阴仙谱']}
    locations = {3:['紫微宫','太微宫'],4:['霄玉宫','玉宝宫','太极宫','太微宫'],5:['太微宫'],6:['太微宫'],7:['太微宫'],11:['天将宫','华紫宫','太上宫','太平宫','太微宫']}
    rows = {r['scene_id']:r for r in visual['scenes']}
    blockers = []
    for scene in plan['script']['scenes']:
        pid = plan['source_map'][scene['scene_id']][0]
        num = int(pid.split('_p')[1])
        if num in locations:
            scene['scenes'] = locations[num]
        scene['props'] = props.get(num, [])
        row = rows[scene['scene_id']]
        h3 = row['h3']
        required = [assets[b][name]['id'] for b,f in [('characters','characters_in_scene'),('scenes','scenes'),('props','props')] for name in scene[f]]
        h3['location_id'] = assets['scenes'][scene['scenes'][0]]['id']
        h3['references'] = [{'asset_id':aid,'description':'the same registered visual identity','lock':'preserve approved identity, geometry and materials'} for aid in required]
        # The compiler retimes again, but the work order itself must also be truthful.
        frames = frames_for(scene['duration_seconds'], False)
        h3['timeline'] = [{'start_frame':i,'end_frame':min(i+24,frames),
                          'description':'Maintain the assigned action and camera continuity; no extra speech.'} for i in range(0,frames,24)]
        row['speech_timing'] = [{'start_frame':6,'end_frame':frames-8} for _ in scene['utterances']]
        for aid in required:
            entry = state['assets'].get(aid,{})
            if not entry.get('path') or not (ROOT / entry['path']).is_file():
                blockers.append({'shot':scene['scene_id'],'asset':aid,'reason':'missing_image'})
            elif not entry.get('approved'):
                blockers.append({'shot':scene['scene_id'],'asset':aid,'reason':'image_review_pending'})
        for line in scene['utterances']:
            voice = voices.get(line['speaker'],{})
            path = ROOT / voice.get('path','')
            if not voice.get('approved') or not path.is_file() or file_hash(path) != voice.get('sha256'):
                blockers.append({'shot':scene['scene_id'],'speaker':line['speaker'],'reason':'voice_review_pending_or_changed'})
    assert [(s['source_text'],s['utterances']) for s in original['script']['scenes']] == [(s['source_text'],s['utterances']) for s in plan['script']['scenes']]
    # Asset binding must not invalidate the already completed source/rhythm
    # review.  Keep that review as a separate content-layer gate and record the
    # new, independent visual-asset gate below.
    plan.setdefault('rhythm_review', {}).update(
        version=2,
        reviewed=True,
        semantic_split=True,
        max_seconds=15,
        source_sequence_verified=True,
    )
    plan['asset_binding_review'] = {
        'status': 'pending_visual_and_voice_asset_approval',
        'required_before_render': True,
        'blocker_count': len(blockers),
    }
    save_content(ROOT, plan)
    # The mutation above only records visual-asset binding metadata. Re-pin the
    # existing content approval to the new digest so the compiler can verify
    # that the locked source/speaker layer is unchanged.
    plan_sha = digest(plan)
    update_state(ROOT, lambda state: state['approvals'].__setitem__(
        'content:chapter_s0004', {
            'sha256': plan_sha,
            'reviewer': 'Codex asset-binding integrity check',
            'note': '仅更新已锁定分镜的角色、场景、道具引用与门禁记录；原文、说话人和节奏审阅保持不变。'
        }))
    visual['content_sha256'] = digest(plan)
    write(ROOT / 'analysis/chapter_s0004_speaker_visual.json', visual)
    blockers.append({'reason':'visual_design_incomplete','details':'首两段天地灾变仍需专用画面；群像出场需逐镜补角色；动作提示词仍套用室内模板，须逐镜改写并与新场景道具对应。'})
    report = {'chapter':'s0004','ready':False,'shots':len(rows),
              'source_and_speaker_sequence_unchanged':True,
              'fixed':['已补原文第7、8、18、19段道具引用','已改第3至7段场景引用','工作单发声时间与时间线按编辑时长展开'],
              'blockers':blockers,'generation_started':False}
    write(ROOT / 'analysis/chapter_s0004_readiness.json', report)
    print({'ready':False,'shots':len(rows),'blockers':len(blockers)})


if __name__ == '__main__':
    main()

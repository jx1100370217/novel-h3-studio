"""Reblock existing scripts without changing source words or speaker attribution."""
import copy, math
from pathlib import Path
from novel_h3.project import read, write, digest
from novel_h3.timing import speech_seconds
from novel_h3.director import frames_for, validate_episode
from novel_h3.arcreel import save_content, approve_content

ROOT=Path(__file__).parent/'projects/rendao-wuji'
BACKUP=ROOT/'analysis/rhythm_before_20260915'
# Editorial breaks: opening reveal, explanation, creation acts and departures.
GROUPS={1:[[1],[2,3,4],[5,6]],5:[[1,2]],11:[[1,2,3]],13:[[1,2,3]],
14:[[1],[2,3,4],[5],[6,7],[8,9],[10],[11,12]],
16:[[1,2],[3,4,5]],19:[[1,2,3]],20:[[1,2,3],[4,5,6]],21:[[1,2]],22:[[1,2,3]]}

def first_chapter():
    eid='chapter_s0003'
    ep=read(ROOT/'episodes'/f'{eid}.json');plan=read(ROOT/'content_plans'/f'{eid}.json')
    for bucket,obj in [('episodes',ep),('content_plans',plan)]:
        path=BACKUP/bucket/f'{eid}.json'
        if not path.exists():write(path,obj)
    original=ep['shots']; byid={s['id']:s for s in original}
    scenes={s['scene_id']:s for s in plan['script']['scenes']}
    groups=[];used=set()
    for s in original:
        if s['id'] in used:continue
        para=int(s['id'].split('P')[1].split('_')[0]);num=int(s['id'].split('_')[1])
        nums=next((g for g in GROUPS.get(para,[]) if num in g),[num])
        ids=[f'C3P{para:02d}_{n:02d}' for n in nums]
        groups.append(ids);used.update(ids)
    out=[];newscenes=[];audit={};source_map={}
    for index,ids in enumerate(groups,1):
        shots=[byid[i] for i in ids];lines=[d for s in shots for d in s['dialogue']]
        assert len({(d['speaker'],d['kind']) for d in lines})==1
        assert all(s['references']==shots[0]['references'] for s in shots)
        shot=copy.deepcopy(shots[0]);sid=f'C3R{index:03d}';shot['id']=sid
        text=''.join(d['text'] for d in lines);end=12+math.ceil(speech_seconds(text)*24)
        frames=frames_for((end+12)/24);shot['frames']=frames
        shot['dialogue']=[dict(lines[0],text=text,start_frame=12,end_frame=end)]
        shot['source_ids']=list(dict.fromkeys(p for s in shots for p in s['source_ids']))
        shot['action']=' '.join(dict.fromkeys(s['action'] for s in shots))
        # Carry every action beat into the new continuous shot, in original order.
        beats=[b for s in shots for b in s['timeline']];old=sum(b['end_frame']-b['start_frame'] for b in beats)
        cursor=0;weight=0;timeline=[]
        for b in beats:
            weight+=b['end_frame']-b['start_frame'];stop=round(weight*frames/old)
            while cursor<stop:
                nxt=min(cursor+24,stop);timeline.append(dict(b,start_frame=cursor,end_frame=nxt));cursor=nxt
        shot['timeline']=timeline;shot['handoff_out']=shots[-1]['handoff_out']
        shot['rhythm_policy']={'version':2,'source_shots':ids,'reviewed':True,'reason':'同一说话人完整语义；在解释、创世动作及离别转折处切镜'}
        shot.pop('timing_policy',None)
        scene=copy.deepcopy(scenes[ids[0]]);scene['scene_id']=sid
        scene['duration_seconds']=min(15,math.ceil(frames/24));scene['utterances']=[{k:shot['dialogue'][0][k] for k in ('kind','speaker','text')}]
        scene['source_text']=''.join(scenes[i]['source_text'] for i in ids)
        scene['scene_description']=shot['action']
        records=[r for i in ids for r in plan['speaker_audit']['scenes'][i]]
        audit[sid]=[dict(scene['utterances'][0],reason='合并前后逐字及说话人一致。'+' '.join(dict.fromkeys(r['reason'] for r in records)),source_ids=shot['source_ids'])]
        source_map[sid]=shot['source_ids'];out.append(shot);newscenes.append(scene)
    def stream(shots):return [(d['speaker'],d['kind'],c) for s in shots for d in s['dialogue'] for c in d['text']]
    assert stream(original)==stream(out),'原文或说话人发生变化'
    assert set(p for s in original for p in s['source_ids'])==set(p for s in out for p in s['source_ids'])
    plan['script']['scenes']=newscenes;plan['source_map']=source_map;plan['speaker_audit']['scenes']=audit
    ep['shots']=out;ep['content_sha256']=digest(plan);ep['rhythm_review']={'version':2,'reviewed':True,'source_shots':len(original),'shots':len(out)}
    errors=validate_episode(ROOT,ep)
    if errors:raise ValueError(errors)
    save_content(ROOT,plan);approve_content(ROOT,eid,'Codex 节奏重编审阅','用户授权全书重新编排；首章逐字及说话人序列、原文覆盖、图片和声音绑定检查通过。')
    write(ROOT/'timing_workorders'/f'{eid}.json',ep)
    write(ROOT/'episodes'/f'{eid}.json',ep)
    report={'episode':eid,'before':len(original),'after':len(out),'durations':[round(s['frames']/24,3) for s in out],'source_and_speakers_unchanged':True}
    write(ROOT/'analysis/rhythm_reblock_report.json',report);print(report)

if __name__=='__main__':first_chapter()

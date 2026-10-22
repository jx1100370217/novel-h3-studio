"""Persist content-timed shot work orders; leave approved renders traceable."""
import json
from pathlib import Path
from novel_h3.project import read,write
from novel_h3.timing import retime
from novel_h3.safety import check_shot_budget

ROOT=Path(__file__).parent/'projects/rendao-wuji'

def run():
    cfg=read(ROOT/'config.json')
    report={'policy':'按内容安排，生成上限362帧；对白及原文不变', 'episodes':[], 'changed_shots':0, 'resource_blocked':0, 'needs_semantic_split':[]}
    for path in sorted((ROOT/'episodes').glob('*.json')):
        ep=read(path)
        if ep.get('release_role','episode')!='episode': continue
        rows=[]
        for shot in ep['shots']:
            try: candidate=retime(shot)
            except ValueError as exc:
                report['needs_semantic_split'].append({'episode':ep['id'],'shot':shot['id'],'reason':str(exc)})
                rows.append(dict(shot,timing_status='needs_semantic_split'));continue
            reason=None
            try: check_shot_budget(cfg,candidate)
            except ValueError as exc: reason=str(exc);report['resource_blocked']+=1
            if candidate!=shot:report['changed_shots']+=1
            candidate['timing_status']='needs_resource_validation' if reason else 'ready_for_timing_review'
            if reason:candidate['resource_reason']=reason
            rows.append(candidate)
        ep['shots']=rows
        ep['timing_review_required']=True
        write(ROOT/'timing_workorders'/path.name,ep)
        report['episodes'].append({'id':ep['id'],'shots':len(rows)})
    write(ROOT/'timing_workorders/report.json',report)
    cfg['timing_policy']={'content_based':True,'max_frames':362,'fps':24,'requires_resource_validation':True}
    write(ROOT/'config.json',cfg)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':run()

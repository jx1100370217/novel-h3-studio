"""User-authorized conditional reset: successful capacity test, then ordered reshoot."""
import subprocess,time
from pathlib import Path
from novel_h3.project import read,write,update_state,digest
from novel_h3.comfy import config,api
from novel_h3.director import validate_episode,approve_episode
from novel_h3.arcreel import content_current
from novel_h3.safety import check_shot_budget

REPO=Path(__file__).resolve().parent
ROOT=REPO/'projects/rendao-wuji'
STATUS=REPO/'runtime/restart_book_1366/status.json'
TEST=REPO/'runtime/speech_root_cause/capacity_1366x768/status.json'

def status(stage,**details):
    write(STATUS,dict(stage=stage,time=time.time(),**details));print(stage,details,flush=True)

def prepared(eid):
    path=ROOT/'timing_workorders'/f'{eid}.json'
    if not path.exists():raise ValueError('缺少按内容时长编排的分镜')
    ep=read(path)
    if ep.get('rhythm_review',{}).get('version') != 2 or not ep['rhythm_review'].get('reviewed'):
        raise ValueError('缺少全章语义与镜头节奏重编审阅')
    if any(s.get('timing_status')=='needs_semantic_split' for s in ep['shots']):raise ValueError('对白尚需按语义拆镜')
    ep.pop('timing_review_required',None)
    for s in ep['shots']:
        s.pop('timing_status',None);s.pop('resource_reason',None)
        check_shot_budget(config(ROOT),s)
    content_current(ROOT,ep)
    errors=validate_episode(ROOT,ep)
    if errors:raise ValueError('; '.join(errors[:8]))
    return ep

def main():
    status('waiting_capacity_test')
    while True:
        result=read(TEST)
        if result['status']=='failed':status('capacity_failed_no_deletion',test=result);return
        if result['status']=='complete':break
        time.sleep(10)
    qc=result.get('qc',{})
    if not qc.get('passed') or qc.get('width')!=1366 or qc.get('height')!=768 or qc.get('frames')!=362:
        status('capacity_not_verified_no_deletion',test=result);return
    # Prepare the first chapter completely before deleting any existing movie.
    ep=prepared('chapter_s0003')
    cfg=config(ROOT)
    q=api(cfg['comfy_url'],'/queue')
    if q['queue_running'] or q['queue_pending']:raise RuntimeError('队列非空，拒绝清理')
    buckets=[ROOT/x for x in ('renders','chapter_videos','final','previews')]+[Path(cfg['output_dir'])/'novel_h3']
    paths=[]
    for bucket in buckets:
        if bucket.is_symlink():raise RuntimeError('拒绝符号链接目录')
        if not bucket.exists():continue
        for p in bucket.rglob('*'):
            if p.is_symlink():raise RuntimeError('拒绝符号链接路径')
            if p.is_file() and p.suffix.lower() in {'.mp4','.mov','.webm','.mkv','.avi'}:paths.append(p)
    manifest=[{'path':str(p),'bytes':p.stat().st_size} for p in paths]
    write(STATUS.parent/'deletion_manifest.json',manifest)
    write(STATUS.parent/'state_before_reset.json',read(ROOT/'state.json'))
    for p in paths:p.unlink()
    def retire(state):
        for take in state['takes'].values():
            take.update(status='removed_by_user',retired=True,video_deleted=True,deletion_reason='按用户要求重新组织短句与镜头节奏，清空旧视频从正文开头重拍')
    update_state(ROOT,retire)
    status('history_cleared',videos=len(paths))
    chapters=[c for c in read(ROOT/'book.json')['chapters'] if c.get('kind')=='story']
    for chapter in chapters:
        eid='chapter_'+chapter['id']
        while True:
            try:ep=prepared(eid);break
            except (ValueError,FileNotFoundError) as exc:
                status('waiting_chapter_materials',episode=eid,reason=str(exc));time.sleep(60)
        write(ROOT/'episodes'/f'{eid}.json',ep)
        approve_episode(ROOT,eid,'Codex 时长编排检查','用户授权1366×768从头重拍；保留锁定原文、说话人与参考资产，时长及逐秒时间线检查通过；视频仍需审片。')
        status('rendering',episode=eid)
        subprocess.run(['/home/jx/miniconda3/bin/python3',str(REPO/'render_chapter.py'),eid],cwd=REPO,check=True)
        status('chapter_rendered_pending_review',episode=eid)
    status('all_available_story_chapters_rendered_pending_review')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        status('failed',reason=str(exc));raise

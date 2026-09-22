"""User-controlled serial preparation batches, with real process-backed status."""
import json,os,signal,subprocess,sys,time
from pathlib import Path
from novel_h3.project import read,write,locked,file_hash
from novel_h3.preparation_control import REPO
from novel_h3.timing import retime_content_plan
root=Path(sys.argv[1]).resolve()
target_episode = next((value for index, value in enumerate(sys.argv[2:], start=2)
                       if value == '--episode' and index + 1 < len(sys.argv)), None)
stop=root/'analysis'/(f'PREPARATION_PAUSED_{target_episode}' if target_episode else 'PREPARATION_PAUSED')
activity=root/'analysis'/(f'preparation_activity_{target_episode}.json' if target_episode else 'preparation_activity.json')
def update(state,message,**extra):
    write(activity,dict(status=state,worker_pid=os.getpid(),updated_at=time.time(),message=message,**extra))

def latest_event(path):
    try:
        lines=path.read_bytes()[-131072:].splitlines()
        for raw in reversed(lines):
            try:
                event=json.loads(raw.decode('utf-8',errors='replace'))
            except json.JSONDecodeError:
                continue
            item=event.get('item',event) if isinstance(event,dict) else {}
            text=item.get('title') or item.get('text') or item.get('type') or event.get('type','')
            if text:
                return str(text).replace('\n',' ')[:240]
    except OSError:
        pass
    return ''

def main():
    # Avoid startup race with controller's status write.
    with locked(root,'preparation_control'):
        pass
    with locked(root, f'preparation_worker_{target_episode or "book"}'):
        while not stop.exists():
            chapters=[c for c in read(root/'book.json')['chapters'] if c.get('kind')=='story']
            chapter = next((c for c in chapters if 'chapter_' + c['id'] == target_episode), None) if target_episode else next((c for c in chapters if not (root/'content_plans'/f"chapter_{c['id']}.json").exists() or not (root/'analysis'/f"chapter_{c['id']}_speaker_visual.json").exists()),None)
            if chapter is None:
                update('waiting_review','全书初稿已存在；需要逐章核对和图片工具补充，不自动验收或启动视频。');return
            eid='chapter_'+chapter['id'];stamp=str(time.time_ns());folder=root/'analysis/preparation_runs'/stamp;folder.mkdir(parents=True)
            prompt=f'''在项目 {root} 完成 {eid}《{chapter['title']}》的 dialogue_only_v3 剧本和用于视频生成的视觉分镜。必须逐段读取 paragraphs.json 本章全部原文，不能用模板短句或未经审读的正则归属冒充创作。人物对白逐字保留、明确正确说话人；叙述转换为具体画面动作和剪辑，不发旁白声音。按对白实际内容和语义停顿决定对白镜头时长，不设置5秒最低时长；H3采用5帧起的17k+5网格，单镜头上限约15秒，超过上限必须在语义边界拆镜，不能截断或补写对白。无对白镜头按动作完成所需时长安排；出场、反应、过渡通常2–4秒，内容层editorial_purpose标注entrance/reaction/transition，真正复杂动作不强行压短。相邻同场出场按一个完整动作合并，不逐人重复六至八秒肖像展示。对白拆段后不得重复起身、入座、进门动作；后续段延续上段最终姿态。同一场谈话必须固定场景资产、光线、角色座位/站位、视线轴线及相同说话人的机位和背景锚点，记录到bible/scene_staging.json（locations按场景ID，layout英文空间描述，characters按角色ID写英文位置与机位）。这是可更新的制作资料，不是资产审批；已有位置不能无理由改写。不猜补遮蔽词，疑点记录待处理。参考已完成的 content_plans/chapter_s0003.json、analysis/chapter_s0003_speaker_visual.json 和 novel_h3/arcreel.py 字段契约，但不得复制旧章画面。写入本章 content_plans 与 speaker_visual，核对原文覆盖、对白序列和资产引用；缺资产逐项写 analysis/{eid}_readiness.json，不虚造文件或审批。所有角色和参考音频必须保留实际审批状态；需要图片则写待当前对话image_gen执行的工作单，禁止其他生图路线。禁止启动视频、取消GENERATION_PAUSED、修改源代码、重写已有章节、删除资产或编辑审批状态。不调用任何自动化或其他任务工具。剧本creative_revision必须为dialogue_only_v3，rhythm_review.reviewed保持false直到真正审阅；完整原文不能删节。使用原子写入，最后汇报实际新增分镜数及缺项。本轮只完成这一章，不自行启动另一个进程。'''
            prompt += '''\n多人互动与资产绑定规则：多人交谈或共同动作的镜头，characters_in_scene 必须列出同场可见的说话人和听者，不得只保留当前说话人；优先设计双人镜头、过肩镜头、群像关系镜头及必要反应镜头，明确左右站位、视线、嘴部状态和动作接续。凡原文动作实际使用道具，props 必须登记对应道具，分镜动作要明确持有人、手、位置、朝向和前后状态。不得为凑资产虚构原文不存在的人物或道具。每镜所有角色、场景、道具和说话人参考音频都必须进入可核验的绑定清单，再编译为 H3 提示词。'''
            started_at=time.time()
            update('running',f"正在创作 {chapter['title']}",episode=eid,phase='starting',started_at=started_at,
                   elapsed_seconds=0,child_pid=None,batch_dir=str(folder.relative_to(root)),
                   events_bytes=0,result_bytes=0,last_heartbeat=started_at,child_alive=False)
            command=['/usr/lib/chatgpt/resources/codex','exec','--skip-git-repo-check','--ephemeral','--sandbox','workspace-write','-c','approval_policy="never"','--json','-C',str(REPO),'-o',str(folder/'result.txt'),prompt]
            with (folder/'events.jsonl').open('w') as log:
                child=subprocess.Popen(command,cwd=REPO,stdout=log,stderr=log,start_new_session=True)
                last_report=0.0
                while child.poll() is None:
                    if stop.exists():
                        os.killpg(child.pid,signal.SIGTERM)
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                        update('paused','准备任务已暂停；已落盘内容保留。',episode=eid,phase='paused',child_pid=None,
                               batch_dir=str(folder.relative_to(root)),elapsed_seconds=round(time.time()-started_at,1),
                               last_heartbeat=time.time(),child_alive=False);return
                    now=time.time()
                    if now-last_report>=2.0:
                        events_path=folder/'events.jsonl';result_path=folder/'result.txt'
                        update('running',f"正在创作 {chapter['title']}",episode=eid,phase='codex_exec',
                               started_at=started_at,elapsed_seconds=round(now-started_at,1),child_pid=child.pid,
                               child_alive=True,batch_dir=str(folder.relative_to(root)),
                               events_bytes=events_path.stat().st_size if events_path.exists() else 0,
                               result_bytes=result_path.stat().st_size if result_path.exists() else 0,
                               last_event=latest_event(events_path),
                               last_heartbeat=now)
                        last_report=now
                    time.sleep(.5)
            if child.returncode:
                update('failed','准备执行失败，请查看本批记录后重试。',episode=eid,phase='codex_failed',child_pid=None,
                       batch_dir=str(folder.relative_to(root)),elapsed_seconds=round(time.time()-started_at,1),
                       last_heartbeat=time.time(),child_alive=False,log=str((folder/'events.jsonl').relative_to(root)));return
            plan=root/'content_plans'/f'{eid}.json';visual=root/'analysis'/f'{eid}_speaker_visual.json'
            if not plan.exists() or not visual.exists() or read(plan).get('creative_revision')!='dialogue_only_v3':
                update('waiting_review','本批未形成完整剧本与分镜，需要处理执行记录中的缺项。',episode=eid,phase='waiting_review',child_pid=None,
                       batch_dir=str(folder.relative_to(root)),elapsed_seconds=round(time.time()-started_at,1),
                               last_heartbeat=time.time(),child_alive=False,log=str((folder/'result.txt').relative_to(root)));return
            # Enforce the timing rule at the point a new workorder lands. This
            # is a direct authoring normalization, not a later migration.
            authored = read(plan)
            normalized, _, blocked_timing = retime_content_plan(authored)
            write(plan, normalized)
            if blocked_timing:
                write(root/'analysis'/f'{eid}_timing_readiness.json', {
                    'episode': eid, 'status': 'waiting_review',
                    'blockers': blocked_timing, 'updated_at': time.time(),
                })
            update('running',f"{chapter['title']} 初稿已落盘，继续下一章。",last_output=eid,phase='chapter_saved',child_pid=None,
                   batch_dir=str(folder.relative_to(root)),elapsed_seconds=round(time.time()-started_at,1),
                   last_heartbeat=time.time(),child_alive=False,log=str((folder/'result.txt').relative_to(root)))
            if target_episode:
                update('completed_batch',f"章节 {chapter['title']} 制作准备已完成，等待资料核对。",episode=eid,phase='completed_batch',
                       child_pid=None,batch_dir=str(folder.relative_to(root)),elapsed_seconds=round(time.time()-started_at,1),
                       last_heartbeat=time.time(),child_alive=False,log=str((folder/'result.txt').relative_to(root)))
                return
        update('paused','准备任务已暂停。')
try:main()
except Exception as exc:update('failed',str(exc));raise

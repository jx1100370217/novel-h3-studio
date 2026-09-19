#!/usr/bin/env python3
"""Serial generation of independent cuts; strict speech failures are retained and flagged."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from novel_h3.comfy import config, submit_next, sync
from novel_h3.rework_queue import claim as claim_rework, complete as complete_rework, release as release_rework, snapshot as rework_snapshot
from novel_h3.project import locked, write, read, update_state, load_state, inside
from novel_h3.safety import PAUSE, SLICE, check_paused, check_power_cap, user_service_env

MAX_SPEECH_RETRIES = 3
AUDIO_QC_TIMEOUT = 300


def run_speech_check(repo, root, take_id):
    """Run Whisper outside the GPU model cgroup.

    The H3 model remains resident for throughput.  Audio QC is CPU-bound and
    gets its own transient slice so model memory cannot starve Whisper.
    """
    unit = f'novel-h3-audio-qc-{take_id}'
    command = [
        'systemd-run', '--user', '--wait', '--collect', '--pipe',
        '--unit', unit,
        '--slice', 'novel-h3-audio.slice',
        '--property=MemoryMax=12G',
        '--property=OOMPolicy=kill',
        '--setenv=NOVEL_H3_AUDIO_QC=1',
        '--', str(repo / '.venv-audio/bin/python'),
        str(repo / 'check_generated_speech.py'), str(root), take_id,
    ]
    return subprocess.run(command, capture_output=True, text=True,
                          timeout=AUDIO_QC_TIMEOUT,
                          env=user_service_env())


def snapshot():
    raw = subprocess.check_output([
        'nvidia-smi', '-i', '0', '--query-gpu=temperature.gpu,power.draw,memory.used',
        '--format=csv,noheader,nounits'], text=True, timeout=10).strip().split(',')
    mem = {line.split(':')[0]: int(line.split()[1]) * 1024
           for line in Path('/proc/meminfo').read_text().splitlines()}
    cg = subprocess.check_output(['systemctl', '--user', 'show', SLICE,
                                  '-p', 'ControlGroup', '--value'], text=True, timeout=10, env=user_service_env()).strip()
    if not cg:
        raise RuntimeError('模型资源隔离组不存在')
    folder = Path('/sys/fs/cgroup') / cg.lstrip('/')
    return dict(time=time.time(), temperature_c=float(raw[0]), power_w=float(raw[1]),
                gpu_mib=float(raw[2]), available_gib=mem['MemAvailable']/2**30,
                model_memory_gib=int((folder/'memory.current').read_text())/2**30,
                memory_events=(folder/'memory.events').read_text())


def stop(reason):
    PAUSE.write_text(reason)
    subprocess.run(['systemctl', '--user', 'stop', SLICE], timeout=45, check=True, env=user_service_env())


def discard_speech_failure(root, take_id):
    """Remove only this failed take's videos; retain its diagnostic reports."""
    take = load_state(root)['takes'][take_id]
    if take.get('speech_check', {}).get('passed') is not False:
        raise ValueError('只能清理已确认转写不通过的镜头')
    folder = inside(config(root)['output_dir'], take['prefix'])
    paths = [inside(root, take['video']), *folder.glob('video*.mp4')]
    for path in paths:
        if path.is_symlink():
            raise ValueError('拒绝清理符号链接视频')
    for path in paths:
        path.unlink(missing_ok=True)
    update_state(root, lambda state: state['takes'][take_id].update(
        status='rejected', retired=True, speech_retry=True,
        video_deleted=True, deletion_reason='转写核对未通过，自动重生成'))


def retain_speech_failure(root, take_id):
    """Keep the third failed render and allow the serial queue to advance."""
    take = load_state(root)['takes'][take_id]
    if take.get('speech_check', {}).get('passed') is not False:
        raise ValueError('只能保留已确认转写不通过的镜头')
    update_state(root, lambda state: state['takes'][take_id].update(
        status='rendered', retired=False, speech_retry_exhausted=True,
        speech_retry_failures=MAX_SPEECH_RETRIES,
        review_required='speech_qc_failed_after_3_retries',
        video_deleted=False,
        retention_note='严格转写连续三次失败后保留，必须人工复核；未放宽转写条件'))


def retain_speech_qc_failure(root, take_id):
    """Keep any strict transcription failure and advance without re-rendering."""
    take = load_state(root)['takes'][take_id]
    if take.get('speech_check', {}).get('passed') is not False:
        raise ValueError('只能保留已确认转写不通过的镜头')
    attempt = int(take.get('speech_retry_attempt', 0)) + 1
    update_state(root, lambda state: state['takes'][take_id].update(
        status='rendered', retired=False, speech_qc_failed_retained=True,
        speech_retry_attempt=attempt, speech_retry_failures=attempt,
        review_required='speech_qc_failed_retained', video_deleted=False,
        retention_note='严格转写核对失败；已保留视频并继续后续镜头，不自动重新生成'))


def run(root, episode, rework_only=False):
    cfg = config(root)
    if episode.startswith('chapter_') and not rework_only:
        from novel_h3.video_control import require_ready
        require_ready(root, episode)
    # Use nanosecond precision so a retry started in the same second as a
    # crashed renderer cannot collide with its abandoned batch directory.
    dest = root / 'renders' / f'batch_{episode}_{time.time_ns()}'
    dest.mkdir(parents=True)
    with locked(root, 'batch'), (dest/'resources.jsonl').open('a', buffering=1) as log:
        current_rework = None
        try:
            while True:
                current_rework = claim_rework(root)
                if rework_only and not current_rework:
                    # A review retake is a standalone high-priority unit. Once
                    # the queue is drained, return to the serial chapter gate
                    # instead of submitting an ordinary shot under a stale or
                    # unrelated asset blocker.
                    return
                work_episode = current_rework['episode'] if current_rework else episode
                if current_rework:
                    if not rework_only:
                        from novel_h3.video_control import require_ready
                        require_ready(root, work_episode)
                check_paused()
                check_power_cap(450)
                # Fail before submission if monitoring is unavailable or already unsafe.
                sample = snapshot()
                if sample['temperature_c'] >= 82 or sample['available_gib'] < 4:
                    raise RuntimeError('提交前资源超出保护阈值')
                # The chapter gate is checked once before the rendering loop;
                # each shot still revalidates its pinned asset hashes in the
                # fingerprint path without repeating the whole chapter audit.
                take = submit_next(root, work_episode, independent_cuts=True,
                                   check_preparation=False, rework_item=current_rework)
                write(dest/'status.json', {**take, 'rework': current_rework})
                if take.get('status') == 'episode_rendered_pending_review':
                    if rework_snapshot(root)['total']:
                        current_rework = None
                        continue
                    print('CHAPTER_RENDERED_PENDING_REVIEW', episode, flush=True)
                    return
                print('SUBMITTED', take['id'], take['shot'],
                      'REWORK' if current_rework else 'NORMAL', flush=True)
                started = time.monotonic()
                while True:
                    check_paused()
                    sample = snapshot()
                    sample['take_id'] = take['id']
                    log.write(json.dumps(sample) + '\n')
                    if sample['temperature_c'] >= 82 or sample['available_gib'] < 4:
                        raise RuntimeError('生成中资源超出保护阈值：' + json.dumps(sample))
                    if time.monotonic() - started > 1500:
                        raise RuntimeError('单镜头超过25分钟，停止生成')
                    result = sync(root).get(take['id'])
                    if result:
                        write(dest/'status.json', dict(id=take['id'], shot=take['shot'],
                                                       rework=current_rework, **result))
                        if result['status'] != 'rendered':
                            raise RuntimeError('镜头生成或技术检查失败：' + str(result))
                        print('RENDERED_PENDING_REVIEW', take['id'], flush=True)
                        if cfg.get('speech_policy', {}).get('require_audio_transcription'):
                            repo=Path(__file__).resolve().parent
                            try:
                                result = run_speech_check(repo, root, take['id'])
                            except subprocess.TimeoutExpired as exc:
                                # A QC timeout is a review exception, not a
                                # reason to stop ComfyUI and the whole book.
                                # Keep the generated take and continue the
                                # serial queue; strict transcription remains
                                # failed until a later manual check completes.
                                report_path = root/'renders'/take['id']/'speech_check.json'
                                timeout_report = {
                                    'passed': False,
                                    'qc_status': 'timeout',
                                    'qc_timeout_seconds': AUDIO_QC_TIMEOUT,
                                    'qc_error': str(exc),
                                    'expected': ''.join(line.get('text', '') for line in take.get('assigned_dialogue', [])),
                                    'transcript': '',
                                    'edit_distance': None,
                                    'allowed_distance': 0,
                                    'scope': '严格转写核对未完成；保留镜头并继续队列，不能视为通过。',
                                    'video_sha256': take.get('video_sha256'),
                                }
                                write(report_path, timeout_report)
                                update_state(root, lambda state: state['takes'][take['id']].update(
                                    speech_check=timeout_report,
                                    review_required='speech_qc_timeout_retained'))
                                retain_speech_qc_failure(root, take['id'])
                                write(dest/'status.json', {
                                    'id': take['id'], 'shot': take['shot'], 'status': 'rendered',
                                    'speech_qc_timeout_retained': True,
                                    'review_required': 'speech_qc_timeout_retained'})
                                if current_rework:
                                    complete_rework(root, current_rework['id'], take['id'])
                                print('SPEECH_QC_TIMEOUT_RETAINED_CONTINUING', take['id'], flush=True)
                                break
                            report_path=root/'renders'/take['id']/'speech_check.json'
                            if report_path.exists():
                                report = read(report_path)
                                # Audio cleanup replaces the media file. Keep the
                                # integrity hash in sync before submit_next checks it.
                                policy_path = root/'renders'/take['id']/'audio_policy.json'
                                update_state(root,lambda state: state['takes'][take['id']].update(
                                    speech_check=report,
                                    video_sha256=report.get('video_sha256', state['takes'][take['id']].get('video_sha256')),
                                    audio_policy=read(policy_path) if policy_path.exists() else state['takes'][take['id']].get('audio_policy')))
                            if result.returncode == 2 and report_path.exists() and read(report_path).get('passed') is False:
                                retain_speech_qc_failure(root, take['id'])
                                write(dest/'status.json', {
                                      'id': take['id'], 'shot': take['shot'], 'status': 'rendered',
                                      'speech_qc_failed_retained': True,
                                      'review_required': 'speech_qc_failed_retained'})
                                if current_rework:
                                    complete_rework(root, current_rework['id'], take['id'])
                                print('SPEECH_FAILED_RETAINED_CONTINUING', take['id'], flush=True)
                                break
                            if result.returncode:
                                detail = ('目标：' + read(report_path)['expected'] + '；实际转写：' + read(report_path)['transcript']) if report_path.exists() else '本地转写程序失败，需检查日志。'
                                raise RuntimeError('生成台词未通过转写核对；保留镜头待审片：' + take['id'] + '。' + detail)
                            cleanup = read(report_path).get('audio_cleanup', {}) if report_path.exists() else {}
                            gate = read(report_path).get('lip_sync_gate', {}) if report_path.exists() else {}
                            if gate.get('status') == 'blocked':
                                print('LIP_SYNC_GATE_BLOCKED_RETAINED', take['id'], gate.get('reason', ''), flush=True)
                            elif cleanup.get('status') == 'applied':
                                print('AUDIO_CLEANED_CONTINUING', take['id'], flush=True)
                            else:
                                print('SPEECH_TEXT_CHECKED_CONTINUING', take['id'], flush=True)
                        if current_rework:
                            complete_rework(root, current_rework['id'], take['id'])
                        # The next shot is independent and can be submitted immediately.
                        # Do not leave a fixed cooldown that looks like a stalled queue.
                        time.sleep(0.5)
                        break
                    time.sleep(5)
        except Exception as exc:
            if current_rework:
                release_rework(root, current_rework['id'], str(exc))
            write(dest/'status.json', {'status': 'paused', 'reason': str(exc)})
            stop('章节生成暂停：' + str(exc))
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('episode')
    parser.add_argument('--project', type=Path, default=Path(__file__).parent/'projects/rendao-wuji')
    parser.add_argument('--rework-only', action='store_true',
                        help='仅处理高优先级重拍队列，队列清空后返回')
    args = parser.parse_args()
    run(args.project.resolve(), args.episode, rework_only=args.rework_only)

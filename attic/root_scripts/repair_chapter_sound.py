"""Repair three failed silent shots without replacing the other chapter takes."""
import argparse
import copy
import math
from pathlib import Path
import time

from novel_h3.project import file_hash, inside, locked, read, write


def prepare(root):
    import numpy as np
    import soundfile as sf
    from audio_review import decode_audio, model_path, MODELS
    from novel_h3.voice_gate import detect_speech
    from novel_h3.v2.compiler import frames_for
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification
    torch.set_num_threads(4)
    base = root / 'production_v2/chapter_s0002'
    state = read(base / 'production.json')
    original = read(base / 'chapter_production_plan.json')
    plan = copy.deepcopy(original)
    plan.update(id='kaochenghuang_v2_nonspeech_repair', title='考城隍 · 三个无对白镜头重拍',
                source_plan_sha256=file_hash(base / 'chapter_production_plan.json'), reused_takes={})
    plan['shots'] = [s for s in plan['shots'] if s['id'] in ('S307', 'P05', 'P09')]
    folder = base / 'sound_repairs/r1'
    folder.mkdir(parents=True, exist_ok=True)
    floor_dir = base / 'takes/c_66a4997396b44b04'
    floor_receipt = read(floor_dir / 'take.json')
    if floor_receipt['speech_screening'].get('passed') is not True:
        raise ValueError('Hall floor source is not speech-screened')
    floor_source = floor_dir / 'native_audio.flac'
    if file_hash(floor_source) != floor_receipt['native_audio_sha256']:
        raise ValueError('Hall source changed')
    floor, sr = sf.read(floor_source, dtype='float32', always_2d=True)
    if sr != 32000 or floor.shape[1] != 2:
        raise ValueError('Use the immutable 32k stereo hall source')
    events = ASTFeatureExtractor.from_pretrained(model_path('events'), local_files_only=True)
    detector = ASTForAudioClassification.from_pretrained(model_path('events'), local_files_only=True).eval()
    for shot in plan['shots']:
        frames = frames_for(shot['duration_seconds'])
        length = math.ceil(frames * sr / 24)
        if shot['id'] == 'S307':
            audio = np.zeros((length, 2), dtype=np.float32)
            retained = min(length, len(floor))
            audio[:retained] = floor[:retained]
            provenance = {'source_path': str(floor_source.relative_to(root)),
                          'source_sha256': file_hash(floor_source), 'source_start_sample': 0,
                          'retained_samples': retained, 'silent_tail_samples': length - retained}
            shot['soundscape'] = 'Quiet continuous hall air and a faint natural cloth movement. Neither person speaks. Sound from another shot is handled only by the editor; generate no words or music.'
        else:
            source = base / 'takes' / state['takes'][shot['id']] / 'native_audio.flac'
            receipt = read(source.parent / 'take.json')
            if file_hash(source) != receipt['native_audio_sha256']:
                raise ValueError('Repair source changed')
            native, rate = sf.read(source, dtype='float32', always_2d=True)
            if rate != sr or native.shape[1] != 2:
                raise ValueError('Repair source format differs')
            boundary = round((4.75 if shot['id'] == 'P05' else 4.4) * sr)
            audio = np.zeros((length, 2), dtype=np.float32)
            audio[:boundary] = native[:boundary]
            fade = round(.025 * sr)
            tail = length - boundary + fade
            if tail > len(floor):
                raise ValueError('Hall tail would require repeating source audio')
            ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
            audio[boundary-fade:boundary] = audio[boundary-fade:boundary] * (1-ramp) + floor[:fade] * ramp
            audio[boundary:] = floor[fade:tail]
            provenance = {'source_path': str(source.relative_to(root)), 'source_sha256': file_hash(source),
                'retained_prefix_seconds': boundary / sr, 'excluded_unassigned_voice_tail': True,
                'hall_tail_path': str(floor_source.relative_to(root)), 'hall_tail_sha256': file_hash(floor_source),
                'crossfade_seconds': fade / sr, 'time_stretch': False, 'gain_changed': False}
        path = folder / (shot['id'] + '_nonverbal_target.wav')
        sf.write(path, audio, sr, subtype='FLOAT')
        proxy = folder / (shot['id'] + '_inspection_proxy.wav')
        decode_audio(path, proxy)
        samples, rate = sf.read(proxy, dtype='float32')
        vad = detect_speech(samples, rate)
        with torch.inference_mode():
            inputs = events(samples, sampling_rate=rate, return_tensors='pt')
            scores = detector(**inputs).logits[0].sigmoid()
        labels = detector.config.id2label
        music = float(scores[next(i for i, name in labels.items() if name == 'Music')])
        top = scores.topk(6)
        report = {'schema': 'nonspeech_source_check_v1', 'target_sha256': file_hash(path),
            'passed': vad.get('available') is True and vad.get('speech_detected') is False and music < .25,
            'speech_gate': vad, 'music_screen': {'model': MODELS['events'], 'score': music,
                'suspected_music_threshold': .25, 'calibrated': False,
                'top_events': [{'label': labels[int(i)], 'score': float(v)} for i,v in zip(top.indices,top.values)]},
            'provenance': provenance, 'human_listened': False, 'release_approved': False,
            'scope': 'No-speech source screening; neither an acoustic/foley acceptance nor a proof of absence of music.'}
        proof = path.with_suffix('.inspection.json')
        write(proof, report)
        if not report['passed']:
            raise ValueError('Nonverbal condition is not ready: ' + shot['id'])
        shot['audio_target'] = {'kind': 'nonverbal', 'path': str(path.relative_to(root)),
            'sha256': file_hash(path), 'text': '', 'speaker': None,
            'verification_path': str(proof.relative_to(root)), 'verification_sha256': file_hash(proof),
            'provenance': provenance, 'generation_use': 'Input during H3 sampling; never postdub a rejected source.'}
        if shot['id'] == 'P05':
            shot['camera'].update(lens_mm=65, size='tight waist-up two-shot',
                composition='Imperial Judge is seated left and Long-Bearded Clerk stands close right, his bearded profile and the book visible. Their bodies and hands fill the frame. Show only soft pillars behind them; no open doorway, corridor, background attendant or other person enters the crop.')
    path = base / 'chapter_sound_repair_plan.json'
    write(path, plan)
    return path


def run_repair(root):
    from novel_h3.v2.runner import run
    from novel_h3.v2.chapter_edit import chapter_timeline
    from novel_h3.v2.production import job, phase
    from novel_h3.safety import REPO
    root = Path(root).resolve()
    base = root / 'production_v2/chapter_s0002'
    state_path = base / 'production.json'
    with locked(root, 'cinema_production'):
        state = read(state_path)
        write(base / 'production_history' / f'pre_sound_repair_{time.time_ns()}.json', state)
        plan_path = base / 'chapter_sound_repair_plan.json'
        if not plan_path.exists():
            result = job([REPO / '.venv-audio/bin/python', Path(__file__).resolve(), root, '--prepare-only'],
                         base / 'production_logs/nonverbal_target_check.log', cpu=True)
            if result:
                raise RuntimeError('Nonverbal source preparation failed; see nonverbal_target_check.log')
        state.update(status='targeted_sound_repair', unresolved_speech=['S307','P05','P09'], error=None)
        write(state_path, state)
        batch = read(run(root, plan_path, None, 202610091401))
        for sid, tid in batch['takes'].items():
            receipt = read(base / 'takes' / tid / 'take.json')
            if receipt['speech_screening'].get('passed') is not True:
                raise ValueError('Conditioned silent retake remains unresolved: ' + sid)
            state['takes'][sid] = tid
        state.update(status='editing', unresolved_speech=[], sound_repair_plan=str(plan_path.relative_to(root)))
        write(state_path, state)
        original = base / 'chapter_production_plan.json'
        phase(root, base, original, 'editing', note='50镜头已具备完整台词/无对白检查结果，正在构建全章初剪与准确文字。')
        timeline = chapter_timeline(root, original, state['takes'], base / 'editorial_blueprint.json')
        write(base / 'chapter_review_timeline.json', timeline)
        from novel_h3.v2.edit import export_review
        review = export_review(root, timeline)
        state.update(status='chapter_review_ready', review=review, completed_at=time.time(), error=None)
        write(state_path, state)
        phase(root, base, original, 'chapter_review_ready', completed=50, total=50,
              review_video=review['video'], note='全章初剪已导出，影视表演、连贯性、纸面几何和最终混音仍需审阅。')
        print('CHAPTER_REVIEW_READY', review['video'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        print(prepare(args.project.resolve()), flush=True)
    else:
        from novel_h3.safety import bounded_worker
        bounded_worker()
        try:
            run_repair(args.project)
        except BaseException as exc:
            from novel_h3.v2.production import phase
            root = args.project.resolve()
            base = root / 'production_v2/chapter_s0002'
            state = read(base / 'production.json')
            state.update(status='failed', error=str(exc), updated_at=time.time())
            write(base / 'production.json', state)
            phase(root, base, base / 'chapter_production_plan.json', 'failed', error=str(exc))
            raise

"""CPU-only, unapproved SyncNet diagnostics using a pinned author checkout.

This is a measurement tool, not a lip-generation or audio-offset repair tool.
The author demo must pass locally before a candidate's numbers are interpreted.
"""
import argparse
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import pickle
import re
import subprocess
import sys
from types import SimpleNamespace

from ..project import file_hash, read, write

REPO = Path(__file__).resolve().parents[2]
COMMIT = '907c0b579c2e2d83f0eae1b2ac9e720cde4e5623'
RUNTIME = REPO / 'runtime/diagnostics/syncnet'


def cpu_environment(runtime):
    environment = dict(os.environ)
    environment.update(CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
                       OPENBLAS_NUM_THREADS='4', PYTHONPATH=str(runtime / 'deps'))
    return environment


def smoke_result(log):
    values = {}
    for name, pattern in [('offset_frames', r'AV offset:\s*([+-]?\d+)'),
                          ('min_distance', r'Min dist:\s*([\d.]+)'),
                          ('confidence', r'Confidence:\s*([\d.]+)')]:
        match = re.search(pattern, log)
        values[name] = float(match.group(1)) if match else None
    values['passed'] = (values['offset_frames'] == 3
                        and values['min_distance'] is not None and abs(values['min_distance'] - 5.353) <= 1
                        and values['confidence'] is not None and abs(values['confidence'] - 10.021) <= 2)
    values['reference_expected'] = {'offset_frames': 3, 'min_distance': 5.353, 'confidence': 10.021}
    values['tolerance'] = {'offset_frames': 0, 'min_distance': 1, 'confidence': 2}
    return values


def interpretation(offset, confidence, face_min_dimension, duration_seconds, smoke_passed):
    reasons = []
    if not smoke_passed:
        reasons.append('Author demo has not passed on this runtime')
    if face_min_dimension < 100:
        reasons.append('Face is under 100 native pixels in its smaller dimension')
    if duration_seconds < 2:
        reasons.append('Face track is shorter than two seconds')
    if not math.isfinite(confidence) or confidence < 4:
        reasons.append('Low cross-modal confidence; generated Mandarin domain is uncalibrated')
    if abs(offset) >= 15:
        reasons.append('Estimated offset reaches the search boundary')
    return {'status': 'not_evaluated' if reasons else 'measured_needs_review', 'reasons': reasons,
            'offset_frames_at_25fps': int(offset), 'offset_seconds': float(offset) / 25,
            'confidence': float(confidence), 'confidence_threshold': 4,
            'threshold_scope': 'Conservative diagnostic screen, not a calibrated acceptance threshold',
            'can_approve_av_sync': False, 'release_approved': False, 'human_listened': False}


def _verify_runtime(runtime):
    source = runtime / 'source'
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != COMMIT:
        raise ValueError('Diagnostic source commit changed')
    if subprocess.check_output(['git', '-C', str(source), 'diff', '--name-only'], text=True).strip():
        raise ValueError('Author implementation is modified; repeat validation explicitly')
    receipt = read(runtime / 'download_receipt.json')
    for item in receipt['files']:
        path = REPO / item['path']
        if file_hash(path) != item['sha256']:
            raise ValueError('Diagnostic model/sample SHA mismatch: ' + str(path))
    return receipt


def validate_smoke(evidence, receipt, versions):
    if evidence.get('source_commit') != COMMIT or not evidence.get('passed'):
        raise ValueError('Run and pass the pinned author demo before candidate scoring')
    if evidence.get('versions') != versions:
        raise ValueError('Diagnostic environment changed; repeat the author demo')
    tested = {Path(item['path']).name: item['sha256'] for item in evidence.get('asset_receipt', {}).get('files', [])}
    current = {Path(item['path']).name: item['sha256'] for item in receipt['files']}
    for name in ('syncnet_v2.model', 'example.avi'):
        if not tested.get(name) or tested[name] != current.get(name):
            raise ValueError('SyncNet weights or demo changed; repeat the author demo')


def _execute(command, cwd, environment, log_path):
    with log_path.open('w') as output:
        result = subprocess.run(command, cwd=cwd, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, timeout=600)
    if result.returncode:
        raise RuntimeError('CPU diagnostic failed; inspect ' + str(log_path))


def smoke(runtime=RUNTIME):
    runtime = Path(runtime).resolve()
    receipt = _verify_runtime(runtime)
    output = runtime / 'smoke'
    output.mkdir(exist_ok=True)
    command = [str(REPO / '.venv-audio/bin/python'), 'demo_syncnet.py', '--videofile', 'data/example.avi',
               '--initial_model', 'data/syncnet_v2.model', '--batch_size', '8',
               '--tmp_dir', str(output / 'frames'), '--reference', 'author_example']
    _execute(command, runtime / 'source', cpu_environment(runtime), output / 'author_demo.log')
    result = smoke_result((output / 'author_demo.log').read_text())
    result.update(schema='syncnet_author_smoke_v1', command=command, source_commit=COMMIT,
                  device='cpu', cuda_visible_devices='', asset_receipt=receipt,
                  versions={name: version(name) for name in ('torch', 'numpy', 'scipy', 'opencv-python')})
    write(output / 'result.json', result)
    return result


def diagnose(source_video, output, runtime=RUNTIME):
    runtime, output, source_video = Path(runtime).resolve(), Path(output).resolve(), Path(source_video).resolve()
    if not output.is_relative_to(runtime):
        raise ValueError('Diagnostic output must stay in the isolated runtime')
    receipt = _verify_runtime(runtime)
    smoke_evidence = read(runtime / 'smoke/result.json')
    validate_smoke(smoke_evidence, receipt,
                   {name: version(name) for name in ('torch', 'numpy', 'scipy', 'opencv-python')})
    before = file_hash(source_video)
    output.mkdir(parents=True, exist_ok=False)
    command = [str(REPO / '.venv-audio/bin/python'), 'run_pipeline.py', '--videofile', str(source_video),
               '--reference', 'candidate', '--data_dir', str(output / 'pipeline'),
               '--min_track', '50', '--min_face_size', '100']
    environment = cpu_environment(runtime)
    _execute(command, runtime / 'source', environment, output / 'face_pipeline.log')
    # Set CPU isolation before importing model libraries in this process too.
    os.environ.update({key: environment[key] for key in ('CUDA_VISIBLE_DEVICES', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')})
    sys.path[:0] = [str(runtime / 'deps'), str(runtime / 'source')]
    import cv2
    import numpy as np
    import torch
    from SyncNetInstance import SyncNetInstance
    if torch.cuda.is_initialized():
        raise RuntimeError('Use a fresh CPU-only diagnostic process')
    torch.set_num_threads(4)
    model = SyncNetInstance(device='cpu')
    model.loadParameters(str(runtime / 'source/data/syncnet_v2.model'))
    with (output / 'pipeline/pywork/candidate/tracks.pckl').open('rb') as handle:
        tracks = pickle.load(handle)  # Locally produced by the pinned author pipeline.
    results = []
    for index, record in enumerate(tracks):
        crop = output / 'pipeline/pycrop/candidate' / f'{index:05d}.avi'
        options = SimpleNamespace(tmp_dir=str(output / 'measurements'), reference=f'track_{index:05d}',
                                  batch_size=8, vshift=15)
        with torch.inference_mode():
            offset, confidence, distances = model.evaluate(options, str(crop))
        np.save(output / f'track_{index:05d}_distances.npy', distances)
        track = record['track']
        indices, boxes = track['frame'], track['bbox']
        widths, heights = boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]
        start, end = float(indices[0]) / 25, float(indices[-1] + 1) / 25
        assessment = interpretation(int(offset), float(confidence),
                                    float(min(np.mean(widths), np.mean(heights))), end - start, True)
        mean_distances = distances.mean(axis=0)
        best = int(np.argmin(mean_distances))
        local_confidence = np.median(mean_distances) - distances[:, best]
        selected = [0, len(indices) // 2, len(indices) - 1]
        cap = cv2.VideoCapture(str(crop))
        contact = []
        for local_index in selected:
            cap.set(cv2.CAP_PROP_POS_FRAMES, local_index)
            ok, frame = cap.read()
            if ok:
                cv2.putText(frame, f'{(indices[0] + local_index) / 25:.2f}s', (8, 215),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1)
                contact.append(frame)
        cap.release()
        if contact:
            cv2.imwrite(str(output / f'track_{index:05d}_contact.jpg'), np.concatenate(contact, axis=1))
        results.append(dict(assessment, track_index=index, crop=str(crop.relative_to(output)), crop_sha256=file_hash(crop),
                            source_start_seconds=start, source_end_seconds=end,
                            mean_native_face_width=float(np.mean(widths)), mean_native_face_height=float(np.mean(heights)),
                            face_boxes_25fps=[{'frame': int(frame), 'time_seconds': float(frame) / 25,
                                              'bbox': [float(value) for value in box]} for frame, box in zip(indices, boxes)],
                            min_distance=float(mean_distances[best]),
                            window_confidences=[{'start_seconds': start + i / 25, 'end_seconds': start + (i + 5) / 25,
                                                 'confidence_at_global_offset': float(value)}
                                                for i, value in enumerate(local_confidence)]))
    if file_hash(source_video) != before:
        raise RuntimeError('Native candidate changed during read-only diagnosis')
    report = {'schema': 'syncnet_cpu_diagnostic_v1', 'source_video': str(source_video), 'source_video_sha256': before,
              'source_commit': COMMIT, 'device': 'cpu', 'cuda_visible_devices': '', 'command': command,
              'analysis_fps': 25, 'native_media_modified': False, 'audio_shift_applied': False,
              'smoke_result': smoke_evidence, 'tracks': results,
              'status': 'measured_needs_review' if any(t['status'] == 'measured_needs_review' for t in results) else 'not_evaluated',
              'reason': None if results else 'No face track satisfies the author detector/tracker criteria',
              'human_listened': False, 'release_approved': False, 'can_approve_av_sync': False,
              'limitations': ['Offsets refer to a resampled 25 fps analysis copy, not the 24 fps native timeline.',
                              'Confidence is a learned audio-visual matching margin, not an accuracy probability.',
                              'Generated Mandarin period-drama faces are not calibrated by the author\'s single demo.',
                              'A score does not establish dialogue accuracy, actor identity, emotion, or human approval.']}
    write(output / 'report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.smoke:
        result = smoke()
        print(json.dumps({key: result[key] for key in ('passed', 'offset_frames', 'confidence', 'min_distance')}))
    elif args.source and args.output:
        result = diagnose(args.source, args.output)
        print(json.dumps({'status': result['status'], 'tracks': [{key: t[key] for key in
              ('track_index', 'status', 'offset_frames_at_25fps', 'confidence')} for t in result['tracks']]}))
    else:
        parser.error('Use --smoke or --source and --output')

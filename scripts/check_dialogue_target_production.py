#!/usr/bin/env python3
"""CPU source checks for full dialogue targets, separate from timbre references.

Accepts {target, expected_text} or {audio_target: {path, sha256, text}}, with
optional audio_vae_roundtrip{path,sha256}. No reference-duration limit applies.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

os.environ.update(CUDA_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_h3.project import file_hash, inside, read, write


def prepare_sources(project, manifest):
    target = manifest.get('target') or manifest.get('audio_target')
    if not isinstance(target, dict):
        raise ValueError('Manifest needs target or audio_target')
    expected = manifest.get('expected_text') or target.get('text')
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError('Target dialogue text is missing')
    if target.get('text') and target['text'] != expected:
        raise ValueError('Target text conflicts with expected_text')
    entries = [('audio_target', target)]
    if manifest.get('audio_vae_roundtrip'):
        entries.append(('audio_vae_roundtrip', manifest['audio_vae_roundtrip']))
    verified = []
    for role, entry in entries:
        source = inside(project, entry['path'])
        before = file_hash(source)
        if before != entry.get('sha256'):
            raise ValueError('Source hash does not match manifest: ' + role)
        verified.append((role, source, before))
    return expected, verified


def load_transcriber():
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
    from audio_review import model_path
    torch.set_num_threads(4)
    model = WhisperForConditionalGeneration.from_pretrained(
        model_path('speech'), local_files_only=True, dtype=torch.float32)
    processor = WhisperProcessor.from_pretrained(model_path('speech'), local_files_only=True)
    return pipeline('automatic-speech-recognition', model=model, tokenizer=processor.tokenizer,
                    feature_extractor=processor.feature_extractor, device='cpu')


def transcript_evidence(project, expected, heard, source_sha256, secondary=None):
    from novel_h3.v2.speech import compare_spoken
    result = compare_spoken(expected, heard)
    result['primary_transcript_passed'] = result['passed']
    if not result['passed'] and secondary:
        path = inside(project, secondary['path'])
        if file_hash(path) != secondary['sha256']:
            raise ValueError('Independent transcription receipt changed')
        evidence = read(path)
        if (evidence.get('schema') != 'independent_audio_transcription_v1'
                or evidence.get('source_sha256') != source_sha256
                or evidence.get('target_text_supplied') is not False
                or evidence.get('source_unchanged') is not True):
            raise ValueError('Independent transcription is not bound to this audio')
        comparison = compare_spoken(expected, evidence.get('transcript', ''))
        result['secondary_transcription'] = dict(comparison, receipt_path=secondary['path'],
            receipt_sha256=secondary['sha256'], model=evidence['model'], revision=evidence['revision'])
        if comparison['passed']:
            result.update(passed=True, match_type='independent_transcription_confirmed')
    return result


def refresh_cached_source(project, row, expected, secondary=None):
    source = inside(project, row['path'])
    unchanged = file_hash(source) == row['sha256']
    comparison = transcript_evidence(project, expected, row['transcript'], row['sha256'], secondary)
    native, vad = row['native_audio'], row['speech_gate']
    result = dict(row)
    result.update(comparison)
    result.update(transcript_passed=comparison['passed'], cached_recognition=True,
        passed=bool(comparison['passed'] and unchanged and native.get('samples_finite')
            and native.get('sample_peak_check_passed') and vad.get('available') and vad.get('speech_detected')),
        original_unchanged=unchanged)
    return result


def inspect_source(project, role, source, before, expected, transcribe, proxy, secondary=None):
    import numpy as np
    import soundfile as sf
    from audio_review import decode_audio
    from novel_h3.v2.speech import compare_spoken
    from novel_h3.voice_gate import detect_speech

    info = sf.info(source)
    native, native_rate = sf.read(source, dtype='float64', always_2d=True)
    finite = bool(native.size and np.isfinite(native).all())
    peak = float(np.max(np.abs(native))) if finite else None
    rms = float(np.sqrt(np.mean(native ** 2))) if finite else None
    bits = {'PCM_16': 16, 'PCM_24': 24, 'PCM_32': 32}.get(info.subtype)
    clip_level = 1 - 2 ** (1 - bits) if bits else 1.0
    peak_ok = finite and peak < clip_level
    native_report = {'sample_rate': native_rate, 'channels': info.channels, 'subtype': info.subtype,
                     'frames': info.frames, 'duration_seconds': info.duration, 'samples_finite': finite,
                     'sample_peak': peak, 'peak_dbfs': float(20 * np.log10(peak)) if peak else None,
                     'rms_dbfs': float(20 * np.log10(rms)) if rms else None,
                     'format_full_scale_level': clip_level, 'sample_peak_check_passed': peak_ok,
                     'samples_at_format_limit': int(np.sum(np.abs(native) >= clip_level)) if finite else None,
                     'peak_measurement': 'native multichannel sample peak, not a true-peak measurement'}
    vad = {'available': False, 'speech_detected': None, 'reason': 'Invalid native samples'}
    recognition = {'text': '', 'chunks': []}
    if finite:
        decode_audio(source, proxy)
        samples, rate = sf.read(proxy, dtype='float32')
        vad = detect_speech(samples, rate)
        if vad.get('available') and vad.get('speech_detected'):
            recognition = transcribe({'raw': samples, 'sampling_rate': rate}, return_timestamps='word',
                                     generate_kwargs={'language': 'zh', 'task': 'transcribe'})
    comparison = transcript_evidence(project, expected, recognition.get('text', ''), before, secondary)
    transcript_ok = comparison['passed']
    unchanged = file_hash(source) == before
    return dict(comparison, passed=bool(transcript_ok and vad.get('available') and vad.get('speech_detected')
                                       and peak_ok and unchanged),
                transcript_passed=transcript_ok, role=role, path=str(source.relative_to(project)), sha256=before,
                source_hash_matches_manifest=True, original_unchanged=unchanged, native_audio=native_report,
                speech_gate=vad, transcript_chunks=recognition.get('chunks', []),
                human_listened=False, release_approved=False)


def check(project, manifest_path):
    from audio_review import MODELS
    project = Path(project).resolve()
    manifest_path = inside(project, str(manifest_path))
    manifest_hash = file_hash(manifest_path)
    manifest = read(manifest_path)
    expected, verified = prepare_sources(project, manifest)
    transcribe = load_transcriber()
    rows = []
    with tempfile.TemporaryDirectory(prefix='.dialogue_target_check_', dir=manifest_path.parent) as work:
        for role, source, before in verified:
            rows.append(inspect_source(project, role, source, before, expected, transcribe,
                                       Path(work) / (role + '.wav')))
    unchanged = file_hash(manifest_path) == manifest_hash and all(file_hash(p) == h for _, p, h in verified)
    target = manifest.get('target') or manifest['audio_target']
    report = {'schema': 'dialogue_target_source_check_v1', 'device': 'cpu', 'cuda_visible_devices': '',
              'purpose': 'Check delivered target speech, separate from timbre-reference validation',
              'manifest': str(manifest_path.relative_to(project)), 'manifest_sha256': manifest_hash,
              'expected_text': expected, 'speaker_asset_id': manifest.get('speaker_asset_id') or target.get('speaker'),
              'asr_model': {'id': MODELS['speech'][0], 'revision': MODELS['speech'][1], 'loads': 1},
              'passed': unchanged and all(row['passed'] for row in rows), 'sources': rows,
              'originals_unchanged': unchanged, 'reference_duration_limit_applied': False,
              'audio_vae_roundtrip_checked': len(verified) == 2,
              'human_listened': False, 'release_approved': False,
              'av_sync_review': {'status': 'not_evaluated', 'video_examined': False}}
    output = manifest_path.with_name(manifest_path.stem + '.speech_check.json')
    write(output, report)
    return report, output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('manifest', type=Path, help='Absolute path or path relative to the project')
    arguments = parser.parse_args()
    result, output = check(arguments.project, arguments.manifest)
    print({'report': str(output), 'passed': result['passed'], 'originals_unchanged': result['originals_unchanged'],
           'sources': [{'role': row['role'], 'passed': row['passed'], 'transcript': row['transcript']}
                       for row in result['sources']]}, flush=True)
    raise SystemExit(0 if result['passed'] else 1)

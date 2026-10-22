#!/usr/bin/env python3
"""Check chapter_audio/manifest.json entries on CPU with one Whisper load.

Each entry supplies shot_id, expected_text, target{path,sha256}, optional
audio_vae_roundtrip{path,sha256}, and optional speaker_asset_id/manifest_path.
Source audio and the input manifest remain immutable; the adjacent
manifest.speech_check.json is diagnostic evidence, never human approval.
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile

os.environ.update(CUDA_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_h3.project import file_hash, inside, read, write
from scripts.check_dialogue_target import inspect_source, load_transcriber, prepare_sources


def reusable_source(row):
    """Cache only passed source evidence under the unchanged comparison rules."""
    native, vad = row.get('native_audio', {}), row.get('speech_gate', {})
    if not (row.get('passed') is True and row.get('transcript_passed') is True
            and row.get('comparison_schema') == 'mandarin_spoken_compare_v1'
            and row.get('source_hash_matches_manifest') is True and row.get('original_unchanged') is True
            and native.get('samples_finite') is True and native.get('sample_peak_check_passed') is True
            and vad.get('available') is True and vad.get('speech_detected') is True
            and isinstance(row.get('expected'), str) and isinstance(row.get('transcript'), str)):
        return False
    from novel_h3.v2.speech import compare_spoken
    current = compare_spoken(row['expected'], row['transcript'])
    return current['passed'] and all(row.get(key) == value for key, value in current.items())


def check_batch(project, manifest_path, progress=None):
    from audio_review import MODELS
    project = Path(project).resolve()
    manifest_path = inside(project, str(manifest_path))
    manifest_hash = file_hash(manifest_path)
    manifest = read(manifest_path)
    output = manifest_path.with_name(manifest_path.stem + '.speech_check.json')
    previous = read(output) if output.exists() else {}
    previous_hash = file_hash(output) if output.exists() else None
    cache = {}
    if (previous.get('asr_model', {}).get('id') == MODELS['speech'][0]
            and previous.get('asr_model', {}).get('revision') == MODELS['speech'][1]):
        for entry in previous.get('entries', []):
            for source in entry.get('sources', []):
                if reusable_source(source) and source['expected'] == entry.get('expected_text'):
                    cache[(source['role'], source['sha256'], source['expected'])] = source
    entries = manifest.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Chapter audio manifest needs non-empty entries[]')
    identifiers = [entry.get('shot_id') for entry in entries]
    if any(not isinstance(value, str) or not value for value in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError('Each audio entry needs a unique shot_id')
    prepared, results = [], []
    for entry in entries:
        result = {key: entry.get(key) for key in ('shot_id', 'speaker_asset_id', 'expected_text', 'manifest_path')}
        result.update(passed=False, sources=[], human_listened=False, release_approved=False,
                      audio_vae_roundtrip_checked=False)
        try:
            expected, sources = prepare_sources(project, entry)
            result['expected_text'] = expected
            prepared.append((result, expected, sources, entry.get('secondary_transcripts', {})))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['preflight_error'] = f'{type(exc).__name__}: {exc}'
        results.append(result)
    fresh = any((role, before, expected) not in cache for _, expected, sources, _ in prepared
                for role, _, before in sources)
    transcribe = load_transcriber() if fresh else None
    with tempfile.TemporaryDirectory(prefix='.chapter_audio_check_', dir=manifest_path.parent) as work:
        for index, (result, expected, sources, secondary) in enumerate(prepared):
            for role, source, before in sources:
                try:
                    cached = cache.get((role, before, expected))
                    if cached:
                        row = deepcopy(cached)
                        row.update(path=str(source.relative_to(project)), asr_reused=True,
                                   asr_cache_source_report_sha256=previous_hash,
                                   asr_cache_source_sha256=before,
                                   human_listened=False, release_approved=False)
                    else:
                        if transcribe is None:
                            transcribe = load_transcriber()
                        row = inspect_source(project, role, source, before, expected, transcribe,
                                             Path(work) / f'{index}_{role}.wav', secondary.get(role))
                        row['asr_reused'] = False
                except Exception as exc:
                    row = {'role': role, 'path': str(source.relative_to(project)), 'sha256': before,
                           'passed': False, 'analysis_error': f'{type(exc).__name__}: {exc}',
                           'asr_reused': False, 'human_listened': False, 'release_approved': False}
                result['sources'].append(row)
            result['passed'] = all(row['passed'] for row in result['sources'])
            result['audio_vae_roundtrip_checked'] = len(sources) == 2
            if progress:
                progress(f"CHECKED_DIALOGUE {result['shot_id']} passed={result['passed']}")
    manifest_unchanged = file_hash(manifest_path) == manifest_hash
    sources_unchanged = True
    for result, _, sources, _ in prepared:
        for role, source, before in sources:
            same = source.is_file() and file_hash(source) == before
            sources_unchanged = sources_unchanged and same
            row = next(item for item in result['sources'] if item['role'] == role)
            row['original_unchanged'] = same
            if not same:
                row['passed'] = result['passed'] = False
    passed_count = sum(entry['passed'] for entry in results)
    report = {'schema': 'chapter_dialogue_target_source_check_v1',
              'manifest': str(manifest_path.relative_to(project)), 'manifest_sha256': manifest_hash,
              'passed': bool(manifest_unchanged and sources_unchanged and passed_count == len(results)),
              'device': 'cpu', 'cuda_visible_devices': '',
              'asr_model': {'id': MODELS['speech'][0], 'revision': MODELS['speech'][1], 'loads': int(transcribe is not None)},
              'previous_report_sha256': previous_hash,
              'entries': results, 'counts': {'entries': len(results), 'passed': passed_count,
                  'failed': len(results) - passed_count,
                  'targets_checked': sum(any(row['role'] == 'audio_target' for row in item['sources']) for item in results),
                  'roundtrips_checked': sum(item['audio_vae_roundtrip_checked'] for item in results),
                  'asr_reused_sources': sum(row.get('asr_reused') is True for item in results for row in item['sources']),
                  'new_sources_checked': sum(row.get('asr_reused') is False for item in results for row in item['sources'])},
              'manifest_unchanged': manifest_unchanged, 'originals_unchanged': sources_unchanged and manifest_unchanged,
              'reference_duration_limit_applied': False, 'human_listened': False, 'release_approved': False,
              'av_sync_review': {'status': 'not_evaluated', 'video_examined': False},
              'scope': 'Native sample peak/finite, VAD, strict transcript and source hash checks only; not voice identity, performance, room acoustics, or audiovisual approval.'}
    if previous:
        archive = manifest_path.parent / 'check_history' / (file_hash(output) + '.json')
        write(archive, previous)
    write(output, report)
    return report, output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('manifest', type=Path)
    arguments = parser.parse_args()
    result, output = check_batch(arguments.project, arguments.manifest, progress=lambda text: print(text, flush=True))
    print({'report': str(output), 'passed': result['passed'], 'counts': result['counts'],
           'originals_unchanged': result['originals_unchanged']}, flush=True)
    raise SystemExit(0 if result['passed'] else 1)

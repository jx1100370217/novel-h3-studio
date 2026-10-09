#!/usr/bin/env python3
"""CPU chapter-audio checks with strict per-source reuse of passed evidence.

CLI: check_dialogue_batch_strict.py PROJECT MANIFEST
Output: MANIFEST_STEM.speech_check.json. Native files and old report archives
are never rewritten. Unknown secondary-transcript fields are not consumed.
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile

os.environ.update(CUDA_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from novel_h3.project import file_hash, inside, read, write
from novel_h3.v2.speech import compare_spoken
from scripts.check_dialogue_target_production import inspect_source, load_transcriber, prepare_sources


def reusable_source(row):
    native, vad = row.get('native_audio', {}), row.get('speech_gate', {})
    if not (row.get('passed') is True and row.get('transcript_passed') is True
            and row.get('comparison_schema') == 'mandarin_spoken_compare_v1'
            and row.get('source_hash_matches_manifest') is True and row.get('original_unchanged') is True
            and native.get('samples_finite') is True and native.get('sample_peak_check_passed') is True
            and vad.get('available') is True and vad.get('speech_detected') is True
            and isinstance(row.get('expected'), str) and isinstance(row.get('transcript'), str)):
        return False
    current = compare_spoken(row['expected'], row['transcript'])
    # Recompare text only. Changed normalization/readings or a prior secondary
    # override cannot silently become an ASR cache hit under this strict policy.
    return current['passed'] and all(row.get(key) == value for key, value in current.items())


def check_batch(project, manifest_path, progress=None):
    from audio_review import MODELS
    code_paths = [Path(__file__), REPO / 'scripts/check_dialogue_target_production.py',
                  REPO / 'novel_h3/v2/speech.py', REPO / 'novel_h3/speech_qc.py',
                  REPO / 'audio_review.py', REPO / 'novel_h3/voice_gate.py']
    code_hashes = {path.resolve(): file_hash(path) for path in code_paths}
    project = Path(project).resolve()
    manifest_path = inside(project, str(manifest_path))
    manifest_hash = file_hash(manifest_path)
    manifest = read(manifest_path)
    output = manifest_path.with_name(manifest_path.stem + '.speech_check.json')
    previous_bytes = output.read_bytes() if output.exists() else None
    previous = read(output) if previous_bytes is not None else {}
    previous_hash = file_hash(output) if previous_bytes is not None else None
    cache = {}
    if (previous.get('asr_model', {}).get('id') == MODELS['speech'][0]
            and previous.get('asr_model', {}).get('revision') == MODELS['speech'][1]):
        for entry in previous.get('entries', []):
            for row in entry.get('sources', []):
                if reusable_source(row) and row['expected'] == entry.get('expected_text'):
                    cache[(row['role'], row['sha256'], row['expected'])] = row
    entries = manifest.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('Chapter audio manifest needs non-empty entries[]')
    ids = [entry.get('shot_id') for entry in entries]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Each audio entry needs a unique shot_id')
    prepared, results = [], []
    for entry in entries:
        result = {key: entry.get(key) for key in ('shot_id', 'speaker_asset_id', 'expected_text', 'manifest_path')}
        result.update(passed=False, sources=[], human_listened=False, release_approved=False,
                      audio_vae_roundtrip_checked=False)
        try:
            expected, sources = prepare_sources(project, entry)
            result['expected_text'] = expected
            prepared.append((result, expected, sources))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['preflight_error'] = f'{type(exc).__name__}: {exc}'
        results.append(result)
    needs_model = any((role, before, expected) not in cache for _, expected, sources in prepared
                      for role, _, before in sources)
    transcribe = load_transcriber() if needs_model else None
    reused_count, checked_count = 0, 0
    with tempfile.TemporaryDirectory(prefix='.strict_audio_check_', dir=manifest_path.parent) as work:
        for index, (result, expected, sources) in enumerate(prepared):
            for role, source, before in sources:
                cached = cache.get((role, before, expected))
                if cached is not None:
                    row = deepcopy(cached)
                    row.update(path=str(source.relative_to(project)), asr_reused=True,
                               asr_cache_source_report_sha256=previous_hash,
                               human_listened=False, release_approved=False)
                    reused_count += 1
                else:
                    try:
                        # Deliberately omit secondary evidence: only this source's
                        # freshly observed primary transcript is checked here.
                        row = inspect_source(project, role, source, before, expected, transcribe,
                                             Path(work) / f'{index}_{role}.wav')
                        row['asr_reused'] = False
                    except Exception as exc:
                        row = {'role': role, 'path': str(source.relative_to(project)), 'sha256': before,
                               'passed': False, 'asr_reused': False,
                               'analysis_error': f'{type(exc).__name__}: {exc}',
                               'human_listened': False, 'release_approved': False}
                    checked_count += 1
                result['sources'].append(row)
            result['passed'] = all(row['passed'] for row in result['sources'])
            result['audio_vae_roundtrip_checked'] = len(sources) == 2
            if progress:
                progress(f"CHECKED_DIALOGUE {result['shot_id']} passed={result['passed']}")
    sources_unchanged = True
    for result, _, sources in prepared:
        for role, source, before in sources:
            same = source.is_file() and file_hash(source) == before
            sources_unchanged = sources_unchanged and same
            row = next(row for row in result['sources'] if row['role'] == role)
            row['original_unchanged'] = same
            if not same:
                row['passed'] = result['passed'] = False
    manifest_unchanged = file_hash(manifest_path) == manifest_hash
    code_sources = [{'path': str(path), 'sha256': before, 'unchanged': file_hash(path) == before}
                    for path, before in code_hashes.items()]
    code_unchanged = all(item['unchanged'] for item in code_sources)
    passed_count = sum(row['passed'] for row in results)
    report = {'schema': 'chapter_dialogue_target_source_check_v1', 'checker': 'strict_per_source_cache_v1',
              'manifest': str(manifest_path.relative_to(project)), 'manifest_sha256': manifest_hash,
              'passed': bool(sources_unchanged and manifest_unchanged and code_unchanged and passed_count == len(results)),
              'device': 'cpu', 'cuda_visible_devices': '', 'entries': results,
              'asr_model': {'id': MODELS['speech'][0], 'revision': MODELS['speech'][1], 'loads': int(needs_model)},
              'previous_report_sha256': previous_hash, 'code_sources': code_sources, 'code_sources_unchanged': code_unchanged,
              'counts': {'entries': len(results), 'passed': passed_count, 'failed': len(results) - passed_count,
                         'targets_checked': sum(any(r['role'] == 'audio_target' for r in row['sources']) for row in results),
                         'roundtrips_checked': sum(row['audio_vae_roundtrip_checked'] for row in results),
                         'asr_reused_sources': reused_count, 'new_sources_checked': checked_count},
              'originals_unchanged': sources_unchanged and manifest_unchanged, 'manifest_unchanged': manifest_unchanged,
              'reference_duration_limit_applied': False, 'secondary_evidence_consumed': False,
              'human_listened': False, 'release_approved': False,
              'av_sync_review': {'status': 'not_evaluated', 'video_examined': False}}
    current_report_hash = file_hash(output) if output.exists() else None
    if current_report_hash != previous_hash:
        raise RuntimeError('QC report changed concurrently; refusing to overwrite another result')
    if previous_bytes is not None:
        archive = manifest_path.parent / 'strict_check_history' / (previous_hash + '.json')
        archive.parent.mkdir(exist_ok=True)
        if not archive.exists():
            archive.write_bytes(previous_bytes)
        elif file_hash(archive) != previous_hash:
            raise ValueError('Existing report archive has changed; refusing overwrite')
    write(output, report)
    return report, output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    report, output = check_batch(args.project, args.manifest, progress=lambda text: print(text, flush=True))
    print({'report': str(output), 'passed': report['passed'], 'counts': report['counts'],
           'asr_model_loads': report['asr_model']['loads'], 'originals_unchanged': report['originals_unchanged']}, flush=True)
    raise SystemExit(0 if report['passed'] else 1)

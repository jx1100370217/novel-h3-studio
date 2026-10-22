#!/usr/bin/env python3
"""Prepare/resume this chapter's dialogue targets; default is a read-only dry run.

--execute loads Qwen3-TTS Base once. --shots explicitly retries only those
dialogue shots, retaining all other successful entries and every old media file.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_dialogue_target as target
from novel_h3.project import file_hash, inside, locked, read, write

BASE = target.PROJECT / 'production_v2/chapter_s0002'
OUTPUT = BASE / 'chapter_audio'
MANIFEST = OUTPUT / 'manifest.json'


def candidate_matches(spec, candidate):
    if (candidate.get('expected_text') != spec['expected_text']
            or candidate.get('speaker_asset_id') != spec['speaker_asset_id']
            or candidate.get('source_reference', {}).get('sha256') != spec['source_reference']['sha256']):
        return False
    for key in ('raw', 'target'):
        media = candidate.get(key, {})
        if not media.get('path') or not media.get('sha256'):
            return False
        path = inside(target.PROJECT, media['path'])
        if not path.is_file() or file_hash(path) != media['sha256']:
            return False
    timing = candidate.get('timing', {})
    frames = timing.get('frames', 0)
    if not isinstance(frames, int) or frames % 17 != 5 or not 4 <= frames / 24 <= 15:
        return False
    audio = candidate['target']
    if (audio.get('sample_rate') != 32000 or audio.get('channels') != 2
            or audio.get('duration_seconds', 0) < frames / 24):
        return False
    if spec['shot_id'] != 'P03' and frames / 24 < spec['authored_duration_seconds']:
        return False
    if spec['shot_id'] != 'P03' and timing.get('lead_seconds', 0.5) != spec.get('lead_seconds', 0.5):
        return False
    return True


def verified_pilot_target(spec):
    """Reuse the validated P03 asset by reference, never by copying its audio."""
    if spec['shot_id'] != 'P03':
        return None
    for path in sorted((BASE / 'dialogue_targets').glob('P03_*/manifest.json'), reverse=True):
        candidate = read(path)
        if not candidate_matches(spec, candidate):
            continue
        evidence = candidate.get('speech_check', {})
        if not evidence.get('path') or not evidence.get('sha256'):
            continue
        report_path = inside(target.PROJECT, evidence['path'])
        if not report_path.is_file() or file_hash(report_path) != evidence['sha256']:
            continue
        report = read(report_path)
        if (report.get('passed') is not True or report.get('expected_text') != spec['expected_text']
                or report.get('speaker_asset_id') != spec['speaker_asset_id']):
            continue
        source = next((row for row in report.get('sources', []) if row.get('role') == 'audio_target'), {})
        if not (source.get('passed') is True and source.get('edit_distance') == 0
                and source.get('allowed_distance') == 0 and source.get('sha256') == candidate['target']['sha256']):
            continue
        result = dict(candidate, action='reuse', reused=True, status='reused_verified_target',
                      manifest_path=str(path.relative_to(target.PROJECT)),
                      reused_from_manifest=str(path.relative_to(target.PROJECT)),
                      source_asr_report=dict(evidence), requested_seed=spec['seed'],
                      authored_duration_seconds=spec['authored_duration_seconds'],
                      duration_exception='Use the actual validated P03 performance duration; do not pad its 8s source to the authored 11s.')
        return result
    return None


def plan_batch(plan_path='chapter_plan.json', shots=None, seed=2026100901):
    path = target.resolve_plan(plan_path)
    plan = read(path)
    dialogue = [shot for shot in plan['shots'] if shot.get('spoken_lines')]
    ids = {shot['id'] for shot in dialogue}
    if shots is not None and (not shots or not set(shots).issubset(ids)):
        raise ValueError('--shots must name dialogue shots in the selected plan')
    previous = read(MANIFEST) if MANIFEST.is_file() else {}
    old = {entry['shot_id']: entry for entry in previous.get('entries', [])}
    for sid, entry in list(old.items()):
        if entry.get('manifest_path'):
            saved = inside(target.PROJECT, entry['manifest_path'])
            if saved.is_file():
                candidate = read(saved)
                if candidate.get('shot_id') == sid and candidate.get('target'):
                    old[sid] = dict(entry, **candidate)
    report_path = MANIFEST.with_name('manifest.speech_check.json')
    failures = set()
    if report_path.is_file():
        report = read(report_path)
        for entry in report.get('entries', []):
            if entry.get('passed') is not False:
                continue
            prior = old.get(entry.get('shot_id'), {})
            if any(source.get('sha256') == prior.get('target', {}).get('sha256')
                   for source in entry.get('sources', []) if source.get('role') == 'audio_target'):
                failures.add(entry['shot_id'])
    entries, blocked = [], []
    for index, shot in enumerate(plan['shots']):
        if not shot.get('spoken_lines'):
            continue
        sid = shot['id']
        selected = shots is None or sid in shots
        try:
            spec = target.prepare(seed + index, sid, path)
            spec['minimum_generation_seconds'] = spec['authored_duration_seconds']
        except (ValueError, KeyError, OSError) as exc:
            entry = dict(old.get(sid, {}), shot_id=sid, action='blocked' if selected else 'not_selected', error=str(exc))
            entries.append(entry)
            if selected:
                blocked.append({'shot_id': sid, 'error': str(exc)})
            continue
        prior = old.get(sid)
        can_reuse = prior and sid not in failures and candidate_matches(spec, prior)
        if can_reuse and (shots is None or not selected):
            entries.append(dict(prior, action='reuse', reused=True))
        elif not selected:
            entries.append(dict(spec, action='not_selected', status='not_selected'))
        else:
            reused = verified_pilot_target(spec) if shots is None else None
            entries.append(reused or dict(spec, action='generate', status='planned'))
    return {
        'schema': 'cinema_chapter_audio_v1', 'plan_path': str(path.relative_to(target.PROJECT)),
        'plan_sha256': file_hash(path), 'plan_id': plan['id'], 'status': 'dry_run',
        'total_shots': len(plan['shots']), 'dialogue_shots': len(dialogue),
        'base_seed': seed, 'requested_shots': shots,
        'model': target.MODEL, 'revision': target.REVISION, 'model_loads': 0,
        'audio_route': 'h3_audio_conditioned', 'provenance': 'generated_tts',
        'approved': False, 'human_listened': False, 'release_approved': False,
        'entries': entries, 'blocked': blocked,
        'duration_risks': [
            {'shot_id': shot['id'], 'han_characters': len(re.findall(r'[\u4e00-\u9fff]', ''.join(x['text'] for x in shot['spoken_lines']))),
             'note': 'Long line: measured natural speech plus 1.5s handles must fit <=345 frames / 14.375s. Keep raw and fail if too long; no acceleration.',
             'estimate_basis': 'Risk screen only: 2.5 Chinese characters/second, not a measured runtime.'}
            for shot in dialogue if len(re.findall(r'[\u4e00-\u9fff]', ''.join(x['text'] for x in shot['spoken_lines']))) / 2.5 + 1.5 > 345 / 24
        ],
    }


def execute_batch(plan_path='chapter_plan.json', shots=None, seed=2026100901):
    from novel_h3.safety import bounded_worker, check_paused, check_power_cap

    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    bounded_worker()
    with locked(target.PROJECT, 'batch'):
        # Reload the manifest under the same serial lock used by H3 and single-shot TTS.
        batch = plan_batch(plan_path, shots, seed)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        if MANIFEST.is_file():
            write(OUTPUT / 'manifests' / f'manifest_{time.time_ns()}.json', read(MANIFEST))
        batch.update(status='preparing', started_at=time.time(), script_sha256=file_hash(__file__))
        write(MANIFEST, batch)
        if batch['blocked']:
            batch['status'] = 'blocked_voice_inputs'
            write(MANIFEST, batch)
            raise ValueError('Voice inputs are not ready: ' + json.dumps(batch['blocked'], ensure_ascii=False))
        pending = [i for i, entry in enumerate(batch['entries']) if entry['action'] == 'generate']
        model = None
        try:
            if pending:
                check_paused()
                check_power_cap(450)
                preflight = target.require_idle_gpu()
                model = target.load_voice_model()
                batch.update(model_loads=1, resource_preflight=preflight)
            for index in pending:
                check_paused()
                spec = batch['entries'][index]
                sid = spec['shot_id']
                output = OUTPUT / f'{sid}_{time.time_ns()}'
                spec.update(status='generating', manifest_path=str((output / 'manifest.json').relative_to(target.PROJECT)))
                batch.update(status='generating', active_shot=sid, updated_at=time.time())
                write(MANIFEST, batch)
                try:
                    record = target.generate_candidate(spec, model, output, preflight)
                    record.update(action='generated', reused=False)
                    batch['entries'][index] = record
                except Exception as exc:
                    partial_path = output / 'manifest.json'
                    partial = read(partial_path) if partial_path.is_file() else dict(spec)
                    partial.update(action='failed', error=str(exc), manifest_path=str(partial_path.relative_to(target.PROJECT)))
                    batch['entries'][index] = partial
                    write(MANIFEST, batch)
                    if not partial.get('raw'):
                        raise
                write(MANIFEST, batch)
            failed = [e['shot_id'] for e in batch['entries'] if e.get('action') == 'failed']
            missing = [e['shot_id'] for e in batch['entries'] if not e.get('target')]
            status = 'partial_failed' if failed else ('partial_targets_ready_pending_asr' if missing else 'targets_ready_pending_asr')
            batch.update(status=status, not_generated_shots=missing,
                         active_shot=None, failed_shots=failed, completed_at=time.time())
            write(MANIFEST, batch)
            print(str(MANIFEST), flush=True)
            if failed:
                raise RuntimeError('Raw candidates retained; retry these shots after repair: ' + ', '.join(failed))
            return MANIFEST
        except BaseException as exc:
            batch.update(status='partial_failed', error=str(exc), updated_at=time.time())
            write(MANIFEST, batch)
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=target.PROJECT)
    parser.add_argument('--plan')
    parser.add_argument('--shots', nargs='+', help='Explicitly retry only these shots; keep other successful entries')
    parser.add_argument('--seed', type=int, default=2026100901)
    parser.add_argument('--execute', action='store_true', help='Actually synthesize after the controller yields the GPU')
    args = parser.parse_args()
    target.PROJECT = args.project.resolve()
    plan = args.plan or target.PROJECT / 'production_v2/chapter_s0002/chapter_plan.json'
    BASE = target.resolve_plan(plan).parent
    OUTPUT = BASE / 'chapter_audio'
    MANIFEST = OUTPUT / 'manifest.json'
    if args.execute:
        execute_batch(plan, args.shots, args.seed)
    else:
        result = plan_batch(plan, args.shots, args.seed)
        print(json.dumps({**{k: v for k, v in result.items() if k != 'entries'},
                          'entries': [{k: entry.get(k) for k in ('shot_id', 'speaker_asset_id', 'expected_text', 'action', 'error', 'manifest_path')}
                                      for entry in result['entries']]}, ensure_ascii=False, indent=2))

"""Resolve an authored chapter blueprint into a provisional, frame-based cut."""
import math
from pathlib import Path

from ..project import file_hash, inside, read


def chapter_timeline(root, plan_path, selected, blueprint_path, *, first_cut=False):
    root = Path(root).resolve()
    plan, blueprint = read(plan_path), read(blueprint_path)
    if plan.get('cinematization_required'):
        from .cinematization import require
        require(root, plan)
    entries = {e['shot_id']: e for e in blueprint['entries']}
    segments, typography, subtitles, pending, audio_warnings, cursor = [], [], [], [], [], 0
    for shot in plan['shots']:
        sid, authored = shot['id'], entries[shot['id']]
        reused = plan.get('reused_takes', {}).get(sid)
        folder = inside(root, reused) if reused else plan_path.parent / 'takes' / selected[sid]
        receipt = read(folder / 'take.json')
        if reused and receipt.get('id') != selected[sid]:
            raise ValueError('Selected reused take differs from the explicit source: ' + sid)
        screening = receipt['speech_screening']
        if screening.get('passed') is not True and shot.get('spoken_lines') and not first_cut:
            raise ValueError('Known speech problem cannot enter the chapter review: ' + sid)
        audio_warning = None
        if screening.get('passed') is not True:
            audio_warning = {'shot_id': sid, 'take_id': selected[sid],
                'report_path': str((folder / 'analysis/speech.json').relative_to(root)),
                'transcript': screening.get('transcript', ''),
                'speech_gate': screening.get('speech_gate', {}),
                'status': 'needs_human_audio_review'}
            audio_warnings.append(audio_warning)
        frames = receipt['technical_qc']['frames']
        start, end = 0, frames
        lines = shot.get('spoken_lines', [])
        chunks = screening.get('transcript_chunks', [])
        vad = screening.get('speech_gate', {}).get('speech_segments', [])
        speech = [(v['start'], v['end']) for v in vad]
        speech += [c['timestamp'] for c in chunks if len(c.get('timestamp', [])) == 2
                   and all(isinstance(t, (float, int)) and math.isfinite(t) for t in c['timestamp'])]
        if lines and speech and not authored['retain_entire_source']:
            start = max(0, math.floor((min(a for a, _ in speech) - authored['speech_pre_handle_seconds']) * 24))
            end = min(frames, math.ceil((max(b for _, b in speech) + authored['speech_post_handle_seconds']) * 24))
        elif not lines and not authored['retain_entire_source']:
            length = min(frames, max(1, round(authored['silent_target_seconds'] * 24)))
            start = min(6, max(0, (frames - length) // 2))
            end = start + length
        for protected in authored.get('hard_retain_source_intervals', []):
            start = min(start, max(0, math.floor(protected['start_seconds'] * 24)))
            end = max(end, math.ceil(protected['end_seconds'] * 24))
        observed = authored.get('observed_source_window')
        if observed:
            if lines:
                raise ValueError('Observed source windows require a silent shot: ' + sid)
            if (observed['take_id'] != selected[sid] or
                    observed['video_sha256'] != receipt.get('video_sha256') or
                    file_hash(folder / 'native.mp4') != observed['video_sha256']):
                raise ValueError('Observed cut marks belong to different media: ' + sid)
            evidence = inside(root, observed['evidence_path'])
            if file_hash(evidence) != observed['evidence_sha256']:
                raise ValueError('Observed cut evidence changed: ' + sid)
            start, end = observed['source_in_frame'], observed['source_out_frame']
            if type(start) is not int or type(end) is not int:
                raise ValueError('Observed cut marks must use integer frames: ' + sid)
            for protected in authored.get('hard_retain_source_intervals', []):
                if not (start <= math.floor(protected['start_seconds'] * 24) <
                        math.ceil(protected['end_seconds'] * 24) <= end):
                    raise ValueError('Observed cut loses a protected interval: ' + sid)
        if authored.get('speech_start_constraint') and vad:
            constraint = authored['speech_start_constraint']
            cue = next(c for c in plan['typography_cues'] if c['id'] == constraint['must_follow_cue_id'])
            if min(v['start'] for v in vad) < cue['end_seconds'] + constraint['minimum_gap_seconds']:
                raise ValueError('Time caption precedes insufficient clean dialogue handle: ' + sid)
        if not 0 <= start < end <= frames:
            raise ValueError('Authored protected interval does not fit the rendered source: ' + sid)
        segments.append({'shot_id': sid, 'take_dir': str(folder.relative_to(root)),
                         'source_in_frame': start, 'source_out_frame': end,
                         **({'audio_screening_warning': audio_warning} if audio_warning else {})})
        if observed:
            segments[-1]['observed_cut'] = observed
        for cue in [c for c in plan.get('typography_cues', []) if c['shot_id'] == sid]:
            if cue.get('must_follow_speech') and (not speech or
                    max(b for _, b in speech) + cue.get('minimum_gap_seconds', .4) > cue['start_seconds']):
                raise ValueError('Closing text would interrupt the key dialogue or lacks measured speech timing: ' + sid)
            a, b = math.floor(cue['start_seconds'] * 24), math.ceil(cue['end_seconds'] * 24)
            if not start <= a < b <= end:
                raise ValueError('The cut loses required readable text: ' + cue['id'])
            typography.append(dict(cue, start_frame=cursor + a - start, end_frame=cursor + b - start))
        if lines and speech:
            first = min(a for a, _ in speech)
            if authored.get('speech_start_constraint') and vad:
                constraint = authored['speech_start_constraint']
                cue = next(c for c in plan['typography_cues'] if c['id'] == constraint['must_follow_cue_id'])
                if first < cue['end_seconds'] + constraint['minimum_gap_seconds']:
                    # A coarse ASR chunk may include the whole caption's silent lead-in.
                    if first != 0:
                        raise ValueError('ASR onset conflicts with the protected time caption: ' + sid)
                    first = min(v['start'] for v in vad)
            a = max(start, math.floor(first * 24))
            b = min(end, math.ceil(max(b for _, b in speech) * 24))
            subtitles.append({'start_frame': cursor + a - start, 'end_frame': cursor + b - start,
                              'text': ''.join(line['text'] for line in lines)})
        elif lines and first_cut:
            subtitles.append({'start_frame': cursor + max(start, round(lines[0].get('start_seconds', .5) * 24)) - start,
                              'end_frame': cursor + end - start,
                              'text': ''.join(line['text'] for line in lines),
                              'timing_source': 'authored_window_pending_speech_review'})
        pending.append({'shot_id': sid, 'take_id': selected[sid],
                        'scope': 'Actual action, pose, composition, continuity, paper geometry and final sound mix'})
        cursor += end - start
    result = {'fps': 24, 'tracks': [{'kind': 'av', 'segments': segments}], 'subtitles': subtitles,
            'typography': typography, 'final_loudnorm': False,
            'status': 'provisional_edit_needs_review', 'release_approved': False,
            'pending_visual_marks': pending, 'blueprint_sha256': file_hash(blueprint_path),
            'plan_sha256': file_hash(plan_path),
            'audio_screening_warnings': audio_warnings,
            'sound_mix_status': ('Native per-shot sound retained; automated speech warnings need human review.'
                if audio_warnings else 'Native dialogue and shot sound retained; scene mix still needs review')}
    if plan.get('narrative_contract_required'):
        from .narrative import preflight
        try:
            result['narrative_check'] = preflight(root, plan_path, result)
        except ValueError:
            report = read(plan_path.parent / 'narrative_edit_check.json')
            if report.get('passed') is not False:
                raise
            result['narrative_check'] = report
            result['narrative_review_status'] = 'blocked_pending_actual_visual_evidence'
    return result

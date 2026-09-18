"""Content-based timing proposals. Never change words, speakers or source links."""
import copy
import math
import re

from .director import FPS, CONTEXT, frames_for, delivered_frames


def speech_seconds(text):
    # Editorial estimate, not measured speech: 4 Chinese characters/s, 2.5 words/s.
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    words = len(re.findall(r'[A-Za-z0-9]+', text))
    pauses = len(re.findall(r'[，,；;：:。.!！?？]', text)) * .18
    return max(.6, chinese / 4 + words / 2.5 + pauses)


def retime(shot):
    result = copy.deepcopy(shot)
    lines = result.get('dialogue', [])
    if not lines:
        return result  # Silent action duration remains an editorial decision.
    lead = max(6, result.get('hold_frames', 48)) if result['continuity'] == 'continue' else 6
    cursor = lead
    for line in lines:
        length = math.ceil(speech_seconds(line['text']) * FPS)
        line.update(start_frame=cursor, end_frame=cursor + length)
        cursor += length + 8  # pause for a speaker change, and breathing room at the tail
    overlap = CONTEXT if result['continuity'] == 'continue' else 0
    # The previous `max(..., delivered_frames(shot))` preserved the legacy
    # 124-frame floor even after timing became content based.  That left
    # short utterances with several seconds of unconstrained H3 audio, which
    # is where repeated or off-screen speech was most often introduced.
    # Silent shots keep their editorial duration above; dialogue shots end
    # after the locked utterances plus the explicit breathing tail.
    required = cursor
    if required + overlap > 362:
        raise ValueError(f"{shot['id']}: 完整对白及动作超过约15秒，须按语义拆镜，不能截断台词")
    result['frames'] = frames_for(required / FPS, bool(overlap))
    total = delivered_frames(result)
    # Keep every existing action beat; stretch the timeline without deleting actions.
    old_total = shot['timeline'][-1]['end_frame']
    timeline = []
    start = 0
    for i, beat in enumerate(shot['timeline']):
        end = total if i == len(shot['timeline']) - 1 else round(beat['end_frame'] * total / old_total)
        while start < end:
            stop = min(start + FPS, end)
            timeline.append(dict(beat, start_frame=start, end_frame=stop))
            start = stop
    result['timeline'] = timeline
    result['timing_policy'] = {'version': 1, 'method': 'content_estimate',
                               'speech_seconds': round((cursor-lead)/FPS, 3),
                               'requires_performance_review': True}
    return result


def dialogue_frames(texts, continuation=False):
    """Return the H3 frame grid required by the supplied dialogue lines."""
    lines = [text for text in texts if text]
    if not lines:
        raise ValueError("对白不能为空")
    lead = max(6, 48) if continuation else 6
    cursor = lead
    for text in lines:
        cursor += math.ceil(speech_seconds(text) * FPS) + 8
    overlap = CONTEXT if continuation else 0
    if cursor + overlap > 362:
        raise ValueError("完整对白及动作超过约15秒，须按语义拆镜，不能截断台词")
    return frames_for(cursor / FPS, continuation)


def dialogue_duration_seconds(texts, continuation=False):
    """Return the integer editorial target matching the content-based H3 grid."""
    frames = dialogue_frames(texts, continuation)
    delivered = frames - (CONTEXT if continuation else 0)
    return max(1, min(15, math.ceil(delivered / FPS)))


def retime_content_plan(plan):
    """Migrate dialogue scene targets away from the legacy five-second floor.

    Silent scenes retain their editorial duration because their timing is an
    action and visual decision rather than a speech-length calculation.
    """
    result = copy.deepcopy(plan)
    changes, blocked = [], []
    for scene in result.get('script', {}).get('scenes', []):
        lines = [u.get('text', '') for u in scene.get('utterances', [])
                 if u.get('kind') == 'dialogue' and u.get('text')]
        if not lines:
            continue
        old = scene.get('duration_seconds')
        try:
            new = dialogue_duration_seconds(lines)
        except ValueError as exc:
            blocked.append({'scene_id': scene.get('scene_id'), 'reason': str(exc)})
            continue
        scene['duration_seconds'] = new
        if old != new:
            changes.append({'scene_id': scene.get('scene_id'), 'old_seconds': old,
                            'new_seconds': new,
                            'dialogue_count': len(lines)})
    return result, changes, blocked


def semantic_chunks(text, max_seconds=13.5):
    """Split only at punctuation, preserving the source byte-for-byte."""
    parts = re.findall(r'[^，,。.!！?？；;：:]+[，,。.!！?？；;：:]*|[，,。.!！?？；;：:]+', text)
    result, current = [], ''
    for part in parts:
        if speech_seconds(part) > max_seconds:
            raise ValueError('单个无停顿长句超过镜头时限，需要人工按语义设置停顿：' + part)
        if current and speech_seconds(current + part) > max_seconds:
            result.append(current)
            current = ''
        current += part
    if current:
        result.append(current)
    assert ''.join(result) == text
    return result


def editorial_seconds(text):
    return min(15, max(1, math.ceil(speech_seconds(text) + .6)))

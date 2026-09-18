"""Keep narration as visual reference, never as generated speech."""
import copy

def content(plan):
    plan = copy.deepcopy(plan)
    for scene in plan['script']['scenes']:
        narration = [u for u in scene.get('utterances', []) if u.get('kind') == 'voiceover']
        if narration:
            scene['visual_narration'] = ''.join(u['text'] for u in narration)
        scene['utterances'] = [u for u in scene.get('utterances', []) if u.get('kind') != 'voiceover']
        records = plan.get('speaker_audit', {}).get('scenes', {}).get(scene['scene_id'])
        if records is not None:
            plan['speaker_audit']['scenes'][scene['scene_id']] = [u for u in records if u.get('kind') != 'voiceover']
    return plan

def shot(value):
    value = copy.deepcopy(value)
    narration = [u for u in value.get('dialogue', []) if u.get('kind') == 'voiceover']
    if narration:
        value['visual_narration'] = ''.join(u['text'] for u in narration)
    value['dialogue'] = [u for u in value.get('dialogue', []) if u.get('kind') != 'voiceover']
    return value

"""Source-reviewed narration work order for s0007; visual assets remain gated."""
import re
from pathlib import Path
from novel_h3.project import read, write
from novel_h3.timing import semantic_chunks, editorial_seconds

ROOT = Path(__file__).parent / 'projects/rendao-wuji'


def run():
    paragraphs = [p for p in read(ROOT / 'paragraphs.json') if p['section'] == 's0007']
    shots, source_map = [], {}
    for p in paragraphs:
        text = p['text']
        # Parenthetical author commentary is retained as an author note, never spoken.
        notes = re.findall(r'（[^）]*）', text)
        spoken_source = re.sub(r'（[^）]*）', '', text)
        parts = semantic_chunks(spoken_source)
        for part in parts:
            sid = f'C7R{len(shots)+1:03d}'
            shots.append({
                'scene_id': sid, 'source_ids': [p['id']], 'source_text': part,
                'duration_seconds': editorial_seconds(part),
                'utterances': [{'kind':'voiceover', 'speaker':'旁白', 'text':part,
                                'speaker_status':'source_reviewed_narration'}],
                'author_notes': notes,
                'visual_order': {
                    'location_candidates':['通天峰','墨河','灵山山脉'] if p['id'] in ('s0007_p0001','s0007_p0007','s0007_p0008') else ['神州大地'],
                    'action_evidence': text,
                    'camera':'按地理说明使用有动机的航拍/地面推进/地图式空间转场；旁白不绑定画面人口型。',
                    'required_asset_names':['通天峰','墨河','灵山山脉'],
                    'status':'pending_shot_specific_visual_design'
                },
                'status':'pending_visual_asset_review'
            })
            source_map.setdefault(p['id'], []).append(sid)
    assert {p['id'] for p in paragraphs} == set(source_map)
    assert all(1 <= x['duration_seconds'] <= 15 for x in shots)
    report = {
        'chapter':'s0007', 'title':'第五节：三国鼎立',
        'source_paragraphs':len(paragraphs), 'source_coverage_verified':True,
        'speaker_audit_status':'source_reviewed_narration', 'unresolved_dialogues':0,
        'author_note_policy':'括号内作者插话保留为 author_notes，不进入旁白音频。',
        'timing_status':'semantic_split_applied_pending_performance_review',
        'timing_policy':'完整保留原文；按标点和语义停顿拆分，单镜头上限15秒。',
        'source_map':source_map, 'shots':shots,
        'status':'preparation_not_production_ready',
        'missing_requirements':['逐镜视觉编排及验收','场景与道具图像验收','旁白试音审听']
    }
    write(ROOT / 'analysis/chapter_s0007_reviewed_workorder.json', report)
    print({'shots':len(shots),'notes':sum(len(s['author_notes']) for s in shots),
           'durations':sorted(set(s['duration_seconds'] for s in shots))})


if __name__ == '__main__':
    run()

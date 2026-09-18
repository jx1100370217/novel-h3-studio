"""Source-attributed preparation only; does not approve voices or enqueue renders."""
import re
from pathlib import Path
from novel_h3.project import read, write, file_hash
from novel_h3.timing import semantic_chunks, editorial_seconds

ROOT = Path(__file__).parent / 'projects/rendao-wuji'
SPEAKERS = {9:'魔尊',11:'魔尊',12:'魔祖',13:'魔尊',14:'魔祖',15:'魔尊',
            16:'魔祖',17:'魔祖',18:'魔祖',19:'魔尊',20:'魔祖',21:'魔尊',
            22:'魔祖',24:'魔祖',25:'魔尊',26:'魔祖',28:'魔尊'}


def run():
    voices = read(ROOT / 'bible/voices.json')
    paragraphs = [p for p in read(ROOT / 'paragraphs.json') if p['section'] == 's0006']
    scenes, evidence = [], []
    for p in paragraphs:
        number = int(p['id'].split('_p')[1])
        pieces = re.findall(r'“[^”]*”|[^“]+', p['text'])
        assert ''.join(pieces) == p['text']
        for piece in pieces:
            quoted = piece.startswith('“')
            speaker = SPEAKERS[number] if quoted else '旁白'
            text = piece[1:-1] if quoted else piece
            parts = semantic_chunks(text)
            assert ''.join(parts) == text
            evidence.append({'source_id':p['id'], 'text':text, 'speaker':speaker,
                             'kind':'dialogue' if quoted else 'narration', 'parts':parts})
            for part in parts:
                masked = '**' in part
                scene = {
                    'scene_id':f'C6R{len(scenes)+1:03d}', 'source_ids':[p['id']],
                    'source_text':part, 'duration_seconds':editorial_seconds(part),
                    'utterances':[{'kind':'dialogue' if quoted else 'voiceover',
                                   'speaker':speaker, 'text':part}],
                    'speaker_status':'source_attribution_reviewed',
                    'source_issue':'原文含遮蔽字符，须确认可发声改编；不猜补原词' if masked else None,
                    'voice_reference':{'path':voices[speaker]['path'],
                                       'sha256':file_hash(ROOT / voices[speaker]['path']),
                                       'approved':voices[speaker].get('approved',False)},
                    'visual_order':{
                        'location':'魔宫内景' if number not in (3,27,28) else '魔界外景',
                        'action_evidence':p['text'],
                        'camera':'说话者近景与听者反应镜头；魔祖飞行段跟随，挥翼击倒处保留动作转折' if quoted else '依据本段动作安排环境全景或动作镜头，旁白不绑定画面人口型',
                        'required_asset_names':['魔祖','魔尊','魔宫','魔座'],
                        'status':'pending_shot_specific_visual_design'},
                    'status':'blocked_source_mask' if masked else 'pending_visual_and_voice_review'
                }
                scenes.append(scene)
    assert {p['id'] for p in paragraphs} == {s['source_ids'][0] for s in scenes}
    assert all(1 <= s['duration_seconds'] <= 15 for s in scenes)
    report = {'chapter':'s0006', 'title':'第四节：魔祖魔尊',
              'source_paragraphs':len(paragraphs), 'source_coverage_verified':True,
              'speaker_unresolved_quotes':0, 'speaker_audit_status':'source_attribution_reviewed',
              'timing_status':'semantic_split_applied_pending_performance_review',
              'timing_policy':'完整保留原文；同一发声段按语义停顿组合，上限15秒；动作与说话人变化不跨越合并。',
              'status':'preparation_not_production_ready', 'scenes':scenes,
              'source_reconstruction':evidence,
              'missing_requirements':['逐镜视觉编排及验收','角色与场景道具图像验收','专属声音审听','原文遮蔽字符处理']}
    write(ROOT / 'analysis/chapter_s0006_reviewed_workorder.json',report)
    print({'shots':len(scenes),'durations':sorted(set(s['duration_seconds'] for s in scenes)),
           'masked_segments':sum(bool(s['source_issue']) for s in scenes),'unresolved_speakers':0})


if __name__ == '__main__':
    run()

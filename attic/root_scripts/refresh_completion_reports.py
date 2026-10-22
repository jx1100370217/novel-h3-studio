"""Refresh explicit completion reports without promoting pending assets."""
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'projects/rendao-wuji'
assets = json.loads((ROOT / 'bible/assets.json').read_text())
state = json.loads((ROOT / 'state.json').read_text())
voices = json.loads((ROOT / 'bible/voices.json').read_text())

report = {}
for bucket in ('characters', 'scenes', 'props'):
    real, approved = [], []
    for name, item in assets[bucket].items():
        current = state.get('assets', {}).get(item['id'], {})
        path = ROOT / current['path'] if current.get('path') else None
        if path and path.is_file():
            real.append(name)
            if current.get('approved'):
                approved.append(name)
    report[bucket] = {'inventory':len(assets[bucket]), 'real_images':len(real),
                      'approved':len(approved), 'missing_images':sorted(set(assets[bucket])-set(real))}
report['character_voices'] = {
    'inventory':len(assets['characters']), 'voice_entries':len(voices),
    'approved':sum(1 for n in assets['characters'] if voices.get(n,{}).get('approved')),
    'independent_or_dedicated_pending':sum(1 for n in assets['characters'] if voices.get(n,{}).get('selection_status') in ('pending_character_audio_review','generated_pending_listening')),
    'shared_placeholder_pending':sum(1 for n in assets['characters'] if voices.get(n,{}).get('selection_status') == 'pending_shared_voice_review'),
    'creature_or_collective_pending':sum(1 for n in assets['characters'] if voices.get(n,{}).get('selection_status') in ('pending_creature_voice_design','pending_collective_voice_design')),
}
report['reviewed_workorders'] = {}
for section in ('s0004', 's0006', 's0007'):
    path = ROOT / f'analysis/chapter_{section}_reviewed_workorder.json'
    if section == 's0004' and not path.exists():
        path = ROOT / 'analysis/chapter_s0004_workorder.json'
    if path.exists():
        d = json.loads(path.read_text())
        if section == 's0004':
            plan = json.loads((ROOT / 'content_plans/chapter_s0004.json').read_text())
            shot_list = plan.get('script',{}).get('scenes',[])
        else:
            shot_list = d.get('scenes',d.get('shots',[]))
        report['reviewed_workorders'][section] = {'shots':len(shot_list),
          'source_coverage_verified': (bool(plan.get('rhythm_review', {}).get('reviewed')) if section == 's0004' else d.get('source_coverage_verified',False)),
          'speaker_audit_status':('reviewed' if section == 's0004' else d.get('speaker_audit_status')), 'timing_status':('semantic_split_applied' if section == 's0004' else d.get('timing_status')),
          'production_ready':False, 'missing_requirements':d.get('missing_requirements',[])}
report['complete'] = False
report['completion_rule'] = '只有图像已登记且已验收、专属音频已审听、逐镜视觉与声音门禁通过，才算生产就绪。'
(ROOT / 'analysis/current_asset_completion.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

rhythm_path = ROOT / 'analysis/book_rhythm_workorders.json'
rhythm = json.loads(rhythm_path.read_text())
for entry in rhythm.get('chapters',[]):
    if entry.get('id') == 'chapter_s0006':
        entry.update(status='source_speaker_reviewed_pending_visual_and_voice', has_script=True)
    elif entry.get('id') == 'chapter_s0007':
        entry.update(status='source_speaker_reviewed_pending_visual_and_voice', has_script=True)
    elif entry.get('id') == 'chapter_s0004':
        entry.update(status='rhythm_reviewed_pending_voice_asset_review', has_script=True)
rhythm['status_note'] = 's0006、s0007 已完成源文说话人和语义时长整理；仍未满足资产、声音审听和逐镜视觉门禁。'
rhythm_path.write_text(json.dumps(rhythm,ensure_ascii=False,indent=2)+'\n')

coverage_path = ROOT / 'analysis/full_book_script_coverage.json'
coverage = json.loads(coverage_path.read_text())
coverage['reviewed_workorders'] = {'s0004':'rhythm_reviewed_pending_voice_asset_review', 's0006':'source_speaker_reviewed_pending_visual_and_voice', 's0007':'source_speaker_reviewed_pending_visual_and_voice'}
coverage['full_book_flexible_timing_status'] = 'in_progress'
coverage['full_book_timing_policy'] = '按语义停顿组织短句；动作转折和说话人变化切镜；单镜头上限15秒；不截断原文。'
coverage['ready_for_production'] = False
coverage_path.write_text(json.dumps(coverage,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'characters':report['characters'], 'scenes':report['scenes'],
                  'props':report['props'], 'character_voices':report['character_voices'],
                  'reviewed_workorders':report['reviewed_workorders'], 'complete':report['complete']}, ensure_ascii=False))

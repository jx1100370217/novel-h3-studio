"""Audit candidate and reviewed work orders against the flexible timing policy."""
import json
from pathlib import Path

ROOT = Path(__file__).parent / 'projects/rendao-wuji'
candidate_dir = ROOT / 'analysis/full_book_workorders'
all_workorders = list(candidate_dir.glob('*.json'))
candidate_shots = sum(json.loads(p.read_text()).get('candidate_shots', 0) for p in all_workorders)
candidate_unresolved = sum(json.loads(p.read_text()).get('speaker_unresolved_quotes', 0) for p in all_workorders)
reviewed = {}
paths = list(ROOT.glob('analysis/chapter_s*_reviewed_workorder.json'))
if (ROOT / 'analysis/chapter_s0004_workorder.json').exists():
    paths.append(ROOT / 'analysis/chapter_s0004_workorder.json')
for p in paths:
    d = json.loads(p.read_text())
    if d.get('chapter') == 's0004':
        plan = json.loads((ROOT / 'content_plans/chapter_s0004.json').read_text())
        shots = plan.get('script', {}).get('scenes', [])
    else:
        shots = d.get('shots', d.get('scenes', []))
    source_verified = d.get('source_coverage_verified', False)
    if d.get('chapter') == 's0004':
        source_verified = bool(plan.get('rhythm_review', {}).get('reviewed'))
    reviewed[d['chapter']] = {
        'shots': len(shots),
        'source_coverage_verified': source_verified,
        'unresolved_dialogues': d.get('unresolved_dialogues', d.get('speaker_unresolved_quotes', 0)),
        'timing_min_seconds': min((s['duration_seconds'] for s in shots), default=None),
        'timing_max_seconds': max((s['duration_seconds'] for s in shots), default=None),
        'within_15_seconds': all(0 < s.get('duration_seconds', 0) <= 15 for s in shots),
        'production_ready': False,
    }
report = {
    'policy': '按内容和语义停顿决定时长；动作转折、说话人变化和场景切换切镜；单镜头上限15秒；不截断原文。',
    'candidate_workorders': len(all_workorders), 'candidate_shots': candidate_shots,
    'candidate_unresolved_quotes': candidate_unresolved,
    'reviewed_workorders': reviewed,
    'full_book_status': 'in_progress',
    'production_ready': False,
    'reason': '其余章节仍是候选工作单或尚未建立源文复核工作单；此外尚有图像、专属声音和逐镜视觉验收门禁。'
}
(ROOT / 'analysis/full_book_flexible_timing_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False))

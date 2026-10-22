"""Register evidence-backed omissions; name matching is NOT semantic coverage proof."""
import hashlib
from pathlib import Path

from novel_h3.arcreel import save_inventory
from novel_h3.director import image_job
from novel_h3.project import read, write, load_state

ROOT = Path(__file__).resolve().parent / 'projects/rendao-wuji'


def main():
    paragraphs = read(ROOT / 'paragraphs.json')
    inventory = read(ROOT / 'bible/assets.json')
    names = read(ROOT / 'analysis/asset_expansion_names.json')
    backup = ROOT / 'analysis/assets_before_full_book_expansion.json'
    if not backup.exists():
        write(backup, inventory)
    known = {name for bucket in names for name in inventory[bucket]}
    added, absent = [], []
    role = {'characters': 'character', 'scenes': 'scene', 'props': 'prop'}
    for bucket, values in names.items():
        for name in values:
            if name in known:
                continue
            hits = [p for p in paragraphs if name in p['text'] and p['section'] != 's0002']
            if not hits:
                absent.append(name)
                continue
            story = [p for p in hits if p['section'] > 's0002']
            first = (story or hits)[0]
            start = first['text'].index(name)
            quote = first['text'][max(0, start - 30):start + len(name) + 90]
            aid = role[bucket] + '_' + hashlib.sha256(name.encode()).hexdigest()[:12]
            description = '待逐段核对外貌和形态后定稿；中国神话写实电影风格。未注明的外观属于美术设计，不视为原文事实。'
            if name == '太微宫':
                description = '天界宫阙外景；云海之上中轴对称的中国传统宫殿建筑，丹柱、金色琉璃瓦、白石台阶。布局为美术设计，留出神祇乘云抵达与进入大殿的路线。无人物。'
            elif name == '太微殿':
                description = '太微宫议事大殿内景；后方高台中央一个玉皇神座，阶下两侧各四个神座，共九座；中央留出迎客行礼的通道。丹柱、金色构件和石地面与太微宫外景统一，无人物。'
            elif name == '玉笏':
                description = '玉皇怀抱的玉质笏板，单块修长温润白玉、圆润上端、细微天然玉纹，素雅而庄重；不添加文字和西式符号。形制细节为美术设计。'
            item = {'id': aid, 'aliases': [], 'source_ids': [first['id']], 'evidence': quote,
                    'source_facts': '原文摘录：' + quote, 'design_description': description,
                    'derivatives': {}, 'review_status': 'evidence_registered_design_review_pending',
                    'first_story_mention': story[0]['id'] if story else None,
                    'appearance_status': 'mention_requires_scene_review' if story else 'reference_only',
                    'mention_source_ids': [p['id'] for p in hits]}
            if bucket == 'characters':
                item['voice_style'] = '待角色与声音审阅；同一身份各形态保持声音一致。'
                item['portrait_policy'] = inventory.get('portrait_policy', '')
            inventory[bucket][name] = item
            known.add(name)
            added.append({'name': name, 'id': aid, 'bucket': bucket})
            # Deliberately create only NEW jobs: existing images retain their provenance hashes.
            prompt = f"Use case: historical-scene. Asset: {name}. Source evidence: {quote}. Art direction: {description}. No watermark."
            job = image_job(ROOT, aid, prompt, role=role[bucket])
            job['status'] = 'needs_source_and_design_review'
            write(ROOT / 'jobs' / f'image_{aid}.json', job)
    inventory['status'] = 'full_book_asset_expansion_in_progress_not_complete'
    inventory['scope'] = '已启动全书资产补录；登记不等于已生成。现有清单仍需逐章核对出场、别名、变身、换装与无名群演，不能据此宣称全书覆盖。'
    save_inventory(ROOT, inventory)
    state = load_state(ROOT)
    sections = {}
    for p in paragraphs:
        if p['section'] <= 's0002':
            continue
        matches = [item['id'] for bucket in names for name, item in inventory[bucket].items()
                   if any(term in p['text'] for term in [name] + item.get('aliases', []))]
        chapter = sections.setdefault(p['section'], {'matched_paragraphs': [], 'unmatched_paragraph_ids': [],
                                                     'semantic_review': 'pending'})
        if matches:
            chapter['matched_paragraphs'].append({'paragraph_id': p['id'], 'asset_ids': matches})
        else:
            chapter['unmatched_paragraph_ids'].append(p['id'])
    baseline = read(backup)
    additions = [{'name': name, 'id': item['id'], 'bucket': bucket}
                 for bucket in names for name, item in inventory[bucket].items()
                 if name not in baseline[bucket]]
    report = {'complete': False, 'method': 'Reviewed seed names plus literal full-source index; not exhaustive entity extraction.',
              'source_sha256': read(ROOT / 'book.json')['source_sha256'], 'added': additions,
              'names_without_evidence': absent, 'counts': {k: len(inventory[k]) for k in names},
              'missing_image_ids': [item['id'] for bucket in names for item in inventory[bucket].values()
                                    if item['id'] not in state['assets']], 'sections': sections}
    write(ROOT / 'analysis/full_book_asset_audit.json', report)
    print({k: v for k, v in report.items() if k not in ('sections', 'added', 'missing_image_ids')})
    print('Added:', len(added), 'Missing base images:', len(report['missing_image_ids']))


if __name__ == '__main__':
    main()

from pathlib import Path
import json, shutil, hashlib, datetime, re
ROOT=Path('/home/jx/codes/novel-h3-studio/projects/rendao-wuji')
assets=json.loads((ROOT/'bible/assets.json').read_text())
voices=json.loads((ROOT/'bible/voices.json').read_text())
# Bring the local, already available H3 voice references inside the project.
src_dir=Path('/home/jx/codes/comfyui-minimax-h3/input/aimixer')
copy_map={
 'cast_ziwei_voice.wav':src_dir/'ch0006/cast_ziwei_voice.wav',
 'cast_donghua_voice.wav':src_dir/'ch0006/cast_donghua_voice.wav',
 'cast_xiwangmu_voice.wav':src_dir/'ch0006/cast_xiwangmu_voice.wav',
 'cast_doumu_voice.wav':src_dir/'ch0006/cast_doumu_voice.wav',
 'cast_huaguang_voice.wav':src_dir/'ch0006/cast_huaguang_voice.wav',
 'cast_dongji_voice.wav':src_dir/'ch0006/cast_dongji_voice.wav',
 'cast_nanji_voice.wav':src_dir/'ch0006/cast_nanji_voice.wav',
 'cast_yuhuang_voice.wav':src_dir/'ch0006/cast_yuhuang_voice.wav',
 'cast_goucheng_voice.wav':src_dir/'ch0006/cast_goucheng_voice.wav',
 'cast_mozun_voice.wav':src_dir/'ch0008/cast_mozun_voice.wav',
 'cast_mozu_voice.wav':src_dir/'ch0008/cast_mozu_voice.wav',
 'cast_lingbao_voice.wav':src_dir/'ch0007/cast_lingbao_voice.wav',
 'cast_hongjun_voice.wav':src_dir/'ch0007/cast_hongjun_voice.wav',
 'cast_yuanshi_voice.wav':src_dir/'ch0007/cast_yuanshi_voice.wav',
 'cast_daode_voice.wav':src_dir/'ch0007/cast_daode_voice.wav',
}
voice_dir=ROOT/'voices'; voice_dir.mkdir(exist_ok=True)
for name,src in copy_map.items():
    dst=voice_dir/name
    if not dst.exists(): shutil.copy2(src,dst)
# Explicitly named cast files. These remain pending until that character's audio is reviewed.
exact={
 '北极紫微大帝':'cast_ziwei_voice.wav','东华大帝':'cast_donghua_voice.wav','西王母':'cast_xiwangmu_voice.wav',
 '斗母大帝':'cast_doumu_voice.wav','华光大帝':'cast_huaguang_voice.wav','东极青华大帝':'cast_dongji_voice.wav',
 '南极长生大帝':'cast_nanji_voice.wav','玉皇大帝':'cast_yuhuang_voice.wav','西极勾陈大帝':'cast_goucheng_voice.wav',
 '魔尊':'cast_mozun_voice.wav','魔祖':'cast_mozu_voice.wav','灵宝天尊':'cast_lingbao_voice.wav','鸿钧老祖':'cast_hongjun_voice.wav',
 '元始天尊':'cast_yuanshi_voice.wav','道德天尊':'cast_daode_voice.wav',
}
# Conservative style routing for characters without a named local cast reference.
female_markers=set('冷月 素灵儿 羲和 夸娥 精卫 红梅 白兰 益灵 春阳夫人 燕妃 漫嫣 岳翎 文君 离珠 屏翳'.split())
creature_markers=set('火龟 九灵狮 三青兽 玄灵白虎 封真火凤 金色血鲤 万年尸王 僵尸亡灵 噬髓蜘蛛 人面蜘蛛 勾魂娲萝 金翼蝙蝠 金翼蝠王 红翼蝙蝠 尸魔元婴 骷髅 公狼 狈 天兵 军士 村民'.split())
# Existing canonical entries are retained and not downgraded.
existing_approved={'无极','盘古','女娲','旁白','振明','冰雨','作者旁白','作者'}
report=[]
for name,item in assets['characters'].items():
    aid=item['id']
    if name in voices and voices[name].get('approved'):
        report.append({'character':name,'asset_id':aid,'path':voices[name]['path'],'status':'approved_existing','canonical_voice':voices[name].get('canonical_voice',name)})
        continue
    if name in exact:
        fn=exact[name]; status='pending_character_audio_review'; canonical=fn.removesuffix('_voice.wav')
    elif name in female_markers:
        fn='nuwa_local_female.wav'; status='pending_shared_voice_review'; canonical='女娲参考音色'
    elif name in creature_markers:
        fn='pangu.wav'; status='pending_creature_voice_design'; canonical='盘古参考音色（待生物音色设计）'
    else:
        fn='wuji.wav'; status='pending_shared_voice_review'; canonical='无极参考音色'
    path='voices/'+fn
    full=ROOT/path
    if not full.exists():
        raise SystemExit(f'missing local ref {full}')
    sha=hashlib.sha256(full.read_bytes()).hexdigest()
    voices[name]={
      'asset_id':aid,'identity':name,'path':path,'sha256':sha,
      'source':str(full),'transcript':'仅作为音色参考，不复制参考台词。',
      'approved':False,'reviewer':'','review_scope':'角色资产补齐阶段登记；必须逐角色审听并确认后才能生成对白镜头。',
      'canonical_voice':canonical,'selection_status':status,
      'selection_note':'本地参考音频已登记；当前角色专属音色尚未逐一审阅，生成前会被绑定校验拦截。'
    }
    report.append({'character':name,'asset_id':aid,'path':path,'status':status,'canonical_voice':canonical})
(ROOT/'bible/voices.json').write_text(json.dumps(voices,ensure_ascii=False,indent=2)+'\n')
summary={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'characters_total':len(assets['characters']),'voice_entries_total':len(voices),'approved_existing':sum(1 for x in report if x['status']=='approved_existing'),'pending':sum(1 for x in report if x['status']!='approved_existing'),'report':report,'policy':'每个角色卡均有本地参考音频；approved=false 的角色不允许进入 VDN-H3 生成。'}
(ROOT/'analysis/character_voice_coverage.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ('characters_total','voice_entries_total','approved_existing','pending')},ensure_ascii=False))

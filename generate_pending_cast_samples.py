"""Generate separate audition files; never automatically approve voice identity."""
import asyncio
import subprocess
from pathlib import Path
import edge_tts
from novel_h3.project import read, write, file_hash

ROOT = Path(__file__).parent / 'projects/rendao-wuji'
PROFILES = {
    '冷月': ('zh-CN-XiaoyiNeural', '+2%', '+2Hz', '别着急，把事情从头告诉我。我会认真听，也会想办法帮你。'),
    '寒星': ('zh-CN-YunjianNeural', '-4%', '+0Hz', '先让大家平安离开，其他的事情交给我。凡事都要查明缘由，再做决定。'),
    '素灵儿': ('zh-CN-XiaoxiaoNeural', '-2%', '-2Hz', '既然已经做了决定，就应当把事情做好。我会仔细考虑，也不会轻易退缩。'),
    '千里眼': ('zh-CN-YunjianNeural', '-6%', '-2Hz', '我已经看见远处的动静，魔界的变化正在向四方扩散。'),
    '顺风耳': ('zh-CN-YunxiNeural', '-5%', '+1Hz', '我听见了异常的声响，方向在更远的天外。'),
    '四海龙王': ('zh-CN-YunjianNeural', '-8%', '-4Hz', '四海水势失控，定海神针已经无法镇住潮汐。'),
    '轮回王': ('zh-CN-YunxiNeural', '-3%', '+0Hz', '轮回有其秩序，来者必须先说明来处。'),
    '刑天': ('zh-CN-YunjianNeural', '-10%', '-6Hz', '战意未熄，纵然失去旧日形骸，也绝不退后。'),
    '后羿': ('zh-CN-YunjianNeural', '-6%', '-2Hz', '弓在手中，目标便不会从视线里消失。'),
    '羲和': ('zh-CN-XiaoxiaoNeural', '-4%', '-3Hz', '日行有度，天地的秩序不能被轻易打乱。'),
}


async def run():
    for name, (voice, rate, pitch, text) in PROFILES.items():
        bank = read(ROOT / 'bible/voices.json')
        if bank[name].get('approved') or bank[name].get('selection_status') == 'generated_pending_listening':
            continue
        assets = read(ROOT / 'bible/assets.json')
        aid = assets['characters'][name]['id']
        target = ROOT / 'voices' / (aid + '_audition.wav')
        mp3 = target.with_suffix('.mp3')
        await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(mp3)), 60)
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(mp3),'-ar','24000','-ac','1',str(target)],check=True)
        relative = str(target.relative_to(ROOT))
        old = bank[name]
        bank[name] = {**old, 'path':relative, 'sha256':file_hash(target),
                      'source':'edge_tts synthetic audition', 'transcript':text,
                      'canonical_voice':name, 'approved':False,
                      'selection_status':'generated_pending_listening',
                      'selection_note':'新生成独立试音文件；商用合成音色，不代表唯一克隆音色；须审听后使用。',
                      'synthesis':{'voice':voice,'rate':rate,'pitch':pitch,
                                   'sample_text_is_novel_dialogue':False},
                      'previous_placeholder_path':old['path']}
        write(ROOT / 'bible/voices.json', bank)
        assets['characters'][name]['reference_audio'] = {
            'voice_id':name,'path':relative,'sha256':file_hash(target),
            'approved':False,'status':'generated_pending_listening'}
        write(ROOT / 'bible/assets.json', assets)
        print(name, relative, flush=True)


if __name__ == '__main__':
    asyncio.run(run())

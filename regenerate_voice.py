"""Generate an unapproved synthetic audition without loading a GPU model."""
import asyncio
import sys
import time
import subprocess
from pathlib import Path
import edge_tts
from novel_h3.project import read, write, locked, file_hash

async def run(root, name):
    with locked(root, 'voice_generation'):
        bank = read(root/'bible/voices.json')
        old = bank[name]
        if old.get('collective') or old.get('selection_status') == 'pending_creature_voice_design':
            raise ValueError('群体或异兽声音需要专门声线设计，不能以单个人类音色冒充')
        profile = old.get('synthesis', {})
        voice = profile.get('voice', 'zh-CN-XiaoxiaoNeural' if '女娲' in old.get('canonical_voice','') else 'zh-CN-YunxiNeural')
        text = '请听清我的声音。事情尚未结束，我们先查明来由，再决定下一步如何行动。'
        aid = old.get('asset_id') or 'narrator'
        output = root/'voices'/f'{aid}_audition_{time.time_ns()}.wav'
        mp3 = output.with_suffix('.mp3')
        await asyncio.wait_for(edge_tts.Communicate(text,voice,rate=profile.get('rate','-5%'),pitch=profile.get('pitch','+0Hz')).save(str(mp3)),90)
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(mp3),'-ar','24000','-ac','1',str(output)],check=True,timeout=30)
        with locked(root):
            bank = read(root/'bible/voices.json');assets=read(root/'bible/assets.json')
            bank[name] = {**bank[name], 'path':str(output.relative_to(root)), 'sha256':file_hash(output),
                          'approved':False,'selection_status':'generated_pending_listening',
                          'source':'edge_tts synthetic audition','transcript':text,
                          'synthesis':{'voice':voice,'rate':profile.get('rate','-5%'),'pitch':profile.get('pitch','+0Hz')},
                          'selection_note':'合成试音候选；不是唯一克隆声线，须审听确认。'}
            write(root/'bible/voices.json',bank)
            if name in assets['characters']:
                assets['characters'][name]['reference_audio']={k:bank[name][k] for k in ('path','sha256','approved')}
                assets['characters'][name]['reference_audio'].update(voice_id=name,status='generated_pending_listening')
                write(root/'bible/assets.json',assets)
        print(output)

if __name__=='__main__':
    asyncio.run(run(Path(sys.argv[1]).resolve(),sys.argv[2]))

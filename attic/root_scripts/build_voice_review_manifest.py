"""Create a playable, non-approval audition manifest for the next chapter."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent / 'projects/rendao-wuji'
NAMES = ['北极紫微大帝','南极长生大帝','东极青华大帝','西极勾陈大帝','玉皇大帝','东华大帝','西王母','华光大帝','斗母大帝']

def main():
    voices = json.loads((ROOT/'bible/voices.json').read_text())
    rows = []
    for name in NAMES:
        item = voices[name]
        path = ROOT / item['path']
        info = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=sample_rate,channels','-of','json',str(path)]))
        rows.append({'speaker':name, 'path':item['path'], 'duration_seconds':float(info['format']['duration']),
                     'sample_rate':int(info['streams'][0]['sample_rate']), 'channels':int(info['streams'][0]['channels']),
                     'machine_transcript':json.loads((ROOT/'analysis/cast_transcripts'/f'{name}.json').read_text()).get('recognition',{}).get('text'),
                     'approval':item.get('approved',False), 'status':item.get('selection_status','pending_character_audio_review'),
                     'review_instruction':'在工作台“角色·场景·道具”页播放；确认音色身份后再将 approved 改为 true。'})
    report = {'chapter':'s0004', 'purpose':'九位天帝参考音频逐角色审听入口', 'approval_policy':'仅审听后批准；机器转写不能代替听音。', 'voices':rows}
    (ROOT/'analysis/chapter_s0004_voice_review_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print({'voices':len(rows),'approved':sum(x['approval'] for x in rows),'pending':sum(not x['approval'] for x in rows)})

if __name__ == '__main__': main()

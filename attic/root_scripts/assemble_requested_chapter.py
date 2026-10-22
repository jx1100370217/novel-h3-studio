"""User-requested complete review cut; retains QC exceptions without approving takes."""
from pathlib import Path
from novel_h3.project import read, write, file_hash, inside
from novel_h3.comfy import current_takes, config
from novel_h3.media import concatenate, write_subtitles, assemble_latest

ROOT = Path(__file__).parent / 'projects/rendao-wuji'


def main():
    episode = read(ROOT / 'episodes/chapter_s0003.json')
    rows = current_takes(ROOT, episode)
    paths, exceptions, ids = [], [], []
    for shot, _, take in rows:
        if not take or take['status'] not in ('rendered', 'approved', 'rejected') or not take.get('qc', {}).get('passed'):
            raise ValueError('Missing technically valid shot: ' + shot['id'])
        path = inside(ROOT, take['video'])
        if file_hash(path) != take['video_sha256']:
            raise ValueError('Changed media: ' + shot['id'])
        paths.append(path)
        ids.append(take['id'])
        if take.get('speech_retry_exhausted') or take.get('speech_qc_failed_retained'):
            exceptions.append({'shot':shot['id'], 'take':take['id'], 'reason':take.get('review_required', 'speech_qc_failed_retained'), 'review':take.get('review')})
    delivery = config(ROOT)['delivery']
    out = ROOT / 'chapter_videos/chapter_s0003.mp4'
    qc = concatenate(paths, out, delivery['width'], delivery['height'])
    chapter = next(c for c in read(ROOT / 'book.json')['chapters'] if c['id'] == 's0003')
    write(out.with_suffix('.json'), {'kind':'chapter_video', 'section':'s0003',
        'source_number':chapter['source_number'], 'title':chapter['title'],
        'take_ids':ids, 'release_approved':False, 'audio_listening':'pending',
        'speech_exceptions':exceptions, 'sha256':file_hash(out), 'qc':qc,
        'note':'用户要求合成全部已生成镜头的审片版；保留转写异常，不修改镜头验收状态。'})
    write_subtitles(ROOT, episode, out.with_suffix('.srt'))
    print(out, qc, flush=True)
    print(assemble_latest(ROOT), flush=True)


if __name__ == '__main__':
    main()

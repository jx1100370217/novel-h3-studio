"""Offline auditory observations without a supplied target transcript or media edits."""
import argparse
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main():
    from novel_h3.safety import bounded_worker
    bounded_worker()
    parser = argparse.ArgumentParser()
    parser.add_argument('media', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    import audio_review
    from novel_h3.project import file_hash, write
    before = file_hash(args.media)
    audio_review.PROMPT += ('\n另外加入 performance_observations 字段：仅凭听到的声音，按实际秒数描述语气、停顿、重音、'
                           '含混发音、明显机械感或突然截断；听不清时明确不确定。不得猜测人物面容、嘴型或剧情，'
                           '不得把模型判断写成人工验收。不要猜测应该说的台词。')
    result = audio_review.analyze(args.media, args.output, device='cuda', language='zh')
    if file_hash(args.media) != before:
        raise RuntimeError('Auditory analysis changed the native source')
    result['native_source_unchanged'] = True
    write(args.output / 'report.json', result)
    print(result['summary'], flush=True)


if __name__ == '__main__':
    main()

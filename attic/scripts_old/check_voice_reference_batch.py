"""Read-only CPU text/voice-presence checks for generated reference candidates."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    import soundfile as sf
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
    from audio_review import decode_audio, model_path
    from novel_h3.project import read, write, file_hash, inside
    from novel_h3.speech_qc import compare
    from novel_h3.voice_gate import detect_speech
    root, manifest = args.project.resolve(), read(args.manifest)
    torch.set_num_threads(4)
    model = WhisperForConditionalGeneration.from_pretrained(model_path('speech'), local_files_only=True, dtype=torch.float32)
    proc = WhisperProcessor.from_pretrained(model_path('speech'), local_files_only=True)
    pipe = pipeline('automatic-speech-recognition', model=model, tokenizer=proc.tokenizer,
                    feature_extractor=proc.feature_extractor, device='cpu')
    reports = []
    out = args.manifest.parent / 'analysis'
    out.mkdir(exist_ok=True)
    for voice in manifest['voices']:
        source = inside(root, voice['path'])
        if file_hash(source) != voice['sha256']:
            raise ValueError('Reference hash changed')
        proxy = out / (voice['asset_id'] + '_proxy.wav')
        decode_audio(source, proxy)
        audio, sr = sf.read(proxy, dtype='float32')
        vad = detect_speech(audio, sr)
        heard = pipe({'raw': audio, 'sampling_rate': sr},
                     generate_kwargs={'language': 'zh', 'task': 'transcribe'})['text']
        report = dict(compare(voice['text'], heard), asset_id=voice['asset_id'],
                      source_sha256=voice['sha256'], speech_gate=vad, human_listened=False)
        report['passed'] = (report['passed'] and vad.get('speech_detected') is True
                            and 2 <= voice['duration_seconds'] <= 15 and not voice['technical_issues'])
        if file_hash(source) != voice['sha256']:
            raise RuntimeError('Inspection changed reference media')
        reports.append(report)
        print(voice['speaker'], report['passed'], heard, flush=True)
    write(out / 'voice_qc.json', {'passed': all(r['passed'] for r in reports),
          'reports': reports, 'human_listened': False, 'references_modified': False})


if __name__ == '__main__': main()

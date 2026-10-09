"""Read-only native-clip speech screening. Never edits production media."""
import argparse
from pathlib import Path

from ..project import file_hash, read, write


def inspect(take_dir):
    import soundfile as sf
    from audio_review import decode_audio, model_path
    from ..voice_gate import detect_speech
    from .speech import compare_spoken

    take_dir = Path(take_dir).resolve()
    source = take_dir / 'native.mp4'
    before = file_hash(source)
    request = read(take_dir / 'request.json')
    output = take_dir / 'analysis'
    output.mkdir(exist_ok=True)
    from .frames import make_contact
    frame_samples = make_contact(take_dir)
    decode_audio(source, output / 'asr_proxy_16k_mono.wav')
    samples, sr = sf.read(output / 'asr_proxy_16k_mono.wav', dtype='float32')
    vad = detect_speech(samples, sr)
    expected = ''.join(line['text'] for line in request['shot'].get('spoken_lines', []))
    transcript, chunks = '', []
    if expected or vad.get('speech_detected'):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
        torch.set_num_threads(4)
        model = WhisperForConditionalGeneration.from_pretrained(model_path('speech'), local_files_only=True, dtype=torch.float32)
        processor = WhisperProcessor.from_pretrained(model_path('speech'), local_files_only=True)
        pipe = pipeline('automatic-speech-recognition', model=model, tokenizer=processor.tokenizer,
                        feature_extractor=processor.feature_extractor, device='cpu')
        result = pipe({'raw': samples, 'sampling_rate': sr}, return_timestamps='word',
                      generate_kwargs={'language': 'zh', 'task': 'transcribe'})
        transcript, chunks = result.get('text', ''), result.get('chunks', [])
    comparison = compare_spoken(expected, transcript)
    if not expected:
        comparison['passed'] = vad.get('available') is True and vad.get('speech_detected') is False
    if file_hash(source) != before:
        raise RuntimeError('Native media changed during read-only inspection')
    report = dict(comparison, schema='native_av_screening_v1', video_sha256=before,
                  frame_samples=frame_samples,
                  speech_gate=vad, transcript_chunks=chunks, audio_route=request['audio_route'],
                  native_media_modified=False, human_listened=False, release_approved=False,
                  av_sync_review={'status': 'not_evaluated', 'video_examined': False,
                                  'note': 'VAD and ASR do not evaluate visible articulation.'})
    write(output / 'speech.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('take_dir', type=Path)
    args = parser.parse_args()
    result = inspect(args.take_dir)
    print({'text_passed': result['passed'], 'expected': result['expected'],
           'transcript': result['transcript'], 'native_media_modified': False}, flush=True)

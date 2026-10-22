"""Read-only native-clip speech screening. Never edits production media."""
import argparse
from pathlib import Path

from ..project import file_hash, read, write

VERSION = 'native_av_screening_v2'


def audio_master(take_dir):
    """Inspect the immutable native soundtrack actually used by the chapter edit."""
    take_dir = Path(take_dir)
    source = take_dir / 'native_audio.flac'
    if file_hash(source) != read(take_dir / 'take.json').get('native_audio_sha256'):
        raise ValueError('Native audio master differs from its take receipt')
    return source


def inspect(take_dir):
    import soundfile as sf
    from audio_review import decode_audio, model_path
    from ..voice_gate import detect_speech
    from .speech import compare_spoken

    take_dir = Path(take_dir).resolve()
    source = take_dir / 'native.mp4'
    before = file_hash(source)
    master = audio_master(take_dir)
    master_before = file_hash(master)
    request = read(take_dir / 'request.json')
    output = take_dir / 'analysis'
    output.mkdir(exist_ok=True)
    from .frames import make_contact
    frame_samples = make_contact(take_dir)
    decode_audio(master, output / 'asr_proxy_16k_mono.wav')
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
    if file_hash(master) != master_before:
        raise RuntimeError('Native audio master changed during read-only inspection')
    report = dict(comparison, schema=VERSION, video_sha256=before,
                  analysis_audio_source='native_audio.flac', analysis_audio_sha256=master_before,
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

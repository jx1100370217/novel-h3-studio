#!/usr/bin/env python3
"""Prepare one pilot shot's speech condition; default mode never loads a model.

Use --execute only when the main controller has yielded the GPU. The generated
WAV is input to H3 video synthesis, never a post-production replacement track.
"""
import argparse
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
PROJECT = REPO / 'projects/liaozhai-zhiyi'
sys.path.insert(0, str(REPO))

from novel_h3.project import file_hash, inside, locked, read, safe_id, write

MODEL = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
REVISION = 'fd4b254389122332181a7c3db7f27e918eec64e3'
MODEL_PATH = Path.home() / '.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/snapshots' / REVISION
RATE = 32000
LEAD_SECONDS = 0.5
MIN_TAIL_SECONDS = 1.0
PARAMETERS = {
    'non_streaming_mode': True, 'do_sample': True, 'temperature': 0.5,
    'top_p': 0.9, 'top_k': 40, 'repetition_penalty': 1.08,
    'max_new_tokens': 512, 'subtalker_dosample': True,
    'subtalker_temperature': 0.5, 'subtalker_top_p': 0.9, 'subtalker_top_k': 40,
}


def choose_frames(natural_seconds, min_seconds=4.0, lead_seconds=LEAD_SECONDS):
    if not math.isfinite(natural_seconds) or natural_seconds <= 0:
        raise ValueError('The generated speech must have a positive finite natural duration')
    if not math.isfinite(min_seconds) or min_seconds < 0:
        raise ValueError('The authored minimum duration must be finite and nonnegative')
    if not math.isfinite(lead_seconds) or lead_seconds < 0:
        raise ValueError('The speech lead must be finite and nonnegative')
    required = max(4.0, min_seconds, lead_seconds + natural_seconds + MIN_TAIL_SECONDS)
    frames = 5 + 17 * math.ceil((required * 24 - 5) / 17)
    if frames / 24 > 15:
        raise ValueError('Natural speech plus lead/tail space exceeds the 4–15s H3 frame grid; preserve the raw WAV and split the authored shot, never accelerate or truncate speech')
    return frames


def pad_target_audio(raw, sample_rate, min_seconds=4.0, lead_seconds=LEAD_SECONDS):
    import numpy as np
    from scipy.signal import resample_poly

    raw = np.asarray(raw, dtype=np.float32)
    if raw.ndim != 1 or not raw.size or not np.isfinite(raw).all() or sample_rate <= 0:
        raise ValueError('Expected finite, nonempty mono model output and a valid sample rate')
    if sample_rate == RATE:
        speech = raw.copy()
    else:
        divisor = math.gcd(int(sample_rate), RATE)
        speech = resample_poly(raw, RATE // divisor, int(sample_rate) // divisor).astype(np.float32)
    frames = choose_frames(len(speech) / RATE, min_seconds, lead_seconds)
    lead = round(lead_seconds * RATE)
    length = math.ceil(frames * RATE / 24)
    target = np.zeros((length, 2), dtype=np.float32)
    target[lead:lead + len(speech)] = speech[:, None]
    tail = length - lead - len(speech)
    if tail < round(MIN_TAIL_SECONDS * RATE):
        raise ValueError('Frame planning did not leave the required unmodified speech tail')
    return target, {
        'frames': frames, 'fps': 24, 'generated_clip_seconds': frames / 24,
        'raw_duration_seconds': len(raw) / int(sample_rate),
        'resampled_speech_seconds': len(speech) / RATE,
        'speech_start_sample': lead, 'speech_end_sample_exclusive': lead + len(speech),
        'lead_seconds': lead / RATE, 'tail_seconds': tail / RATE,
        'final_duration_seconds': length / RATE,
        'audio_samples': length, 'sample_rate': RATE, 'channels': 2,
        'resampling': 'sample-rate conversion only; no tempo change',
        'time_stretch_applied': False, 'speech_trimmed': False, 'gain_changed': False,
        'minimum_generation_seconds': min_seconds,
        'editorial_handles': {
            'speech_end_seconds': (lead + len(speech)) / RATE,
            'speech_plus_tail_seconds': lead / RATE + len(speech) / RATE + MIN_TAIL_SECONDS,
            'full_padded_duration_is_not_required_edit_length': True,
            'policy': 'Preserve the complete spoken performance; use silent handles only for meaningful visible action/reaction, not automatic full-length concatenation.',
        },
    }


def resolve_plan(plan_path=None):
    path = Path(plan_path) if plan_path is not None else PROJECT / 'production_v2/chapter_s0002/pilot.json'
    if not path.is_absolute() and not path.is_file():
        path = PROJECT / path
    path = path.resolve()
    if not path.is_relative_to(PROJECT):
        raise ValueError('The dialogue plan must belong to this project')
    return path


def prepare(seed, shot_id='P03', plan_path=None):
    shot_id = safe_id(shot_id)
    plan_path = resolve_plan(plan_path)
    plan = read(plan_path)
    shot = next((item for item in plan['shots'] if item['id'] == shot_id), None)
    if shot is None:
        raise ValueError(f'Unknown dialogue shot: {shot_id}')
    lines = shot.get('spoken_lines', [])
    speakers = {line.get('speaker') for line in lines}
    if not lines or len(speakers) != 1 or not all(speakers):
        raise ValueError('Select one dialogue shot with exactly one registered speaker; silent or multi-speaker shots are not supported')
    if any(not line.get('text', '').strip() for line in lines):
        raise ValueError('Every selected dialogue line must contain literal text')
    speaker = next(iter(speakers))
    text = ''.join(line['text'] for line in lines)
    authored_start = float(lines[0].get('start_seconds', LEAD_SECONDS))
    if not math.isfinite(authored_start) or authored_start < 0:
        raise ValueError('The authored speech start must be finite and nonnegative')
    lead_seconds = max(LEAD_SECONDS, authored_start)
    bank = read(PROJECT / 'bible/voices.json')
    matches = [voice for voice in bank.values() if voice.get('asset_id') == speaker]
    if len(matches) != 1 or matches[0].get('approved') is not True:
        raise ValueError(f'{speaker} must have exactly one existing approved voice reference')
    voice = matches[0]
    reference = inside(PROJECT, voice['path'])
    if file_hash(reference) != voice['sha256']:
        raise ValueError('Approved voice reference has changed')
    if not voice.get('transcript') or voice.get('strict_asr_passed') is not True:
        raise ValueError('Voice-clone ICL requires the verified reference transcript')
    for required in ('model.safetensors', 'config.json', 'generation_config.json',
                     'speech_tokenizer/model.safetensors', 'speech_tokenizer/config.json'):
        if not (MODEL_PATH / required).is_file():
            raise FileNotFoundError(MODEL_PATH / required)
    return {
        'schema': 'cinema_dialogue_target_v1', 'status': 'prepared_not_generated',
        'shot_id': shot_id, 'speaker_asset_id': speaker, 'expected_text': text,
        'authored_duration_seconds': float(shot.get('duration_seconds', 4)),
        'minimum_generation_seconds': 4.0,
        'lead_seconds': lead_seconds,
        'plan_path': str(plan_path.relative_to(PROJECT)), 'plan_sha256': file_hash(plan_path),
        'model': MODEL, 'revision': REVISION, 'model_path': str(MODEL_PATH),
        'seed': int(seed), 'parameters': PARAMETERS,
        'source_reference': {'path': voice['path'], 'sha256': voice['sha256'],
                             'transcript': voice['transcript'], 'approved': True,
                             'source': voice.get('source'), 'canonical_voice': voice.get('canonical_voice')},
        'provenance': 'generated_tts', 'method': 'Qwen3-TTS Base ICL voice clone',
        'x_vector_only_mode': False, 'audio_route': 'h3_audio_conditioned',
        'purpose': 'Full timed target waveform supplied during H3 video sampling',
        'post_production_dubbing': False, 'reference_words_for_film': False,
        'source_voice_reference_reused': True,
        'voice_similarity_verified': False, 'exact_transcript_verified': False,
        'approved': False, 'human_listened': False,
        'av_sync_review': {'status': 'not_evaluated'},
    }


def require_idle_gpu():
    from novel_h3.comfy import api, config

    queue = api(config(PROJECT)['comfy_url'], '/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise RuntimeError('Comfy queue is not empty; the main controller must finish H3 work first')
    reading = subprocess.run([
        'nvidia-smi', '-i', '0', '--query-gpu=utilization.gpu,memory.used',
        '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True, timeout=10)
    utilization, memory = map(float, reading.stdout.strip().split(','))
    # This shared desktop has 4–5 GiB of graphics/context memory even with no
    # inference task running; require the queue to be empty and H3 unloaded.
    # Desktop rendering can raise utilization while no inference job exists.
    # The exclusive project lock, empty Comfy queue and memory limit determine readiness.
    if memory > 6144:
        raise RuntimeError(f'GPU is not idle/unloaded: {utilization}% utilization, {memory} MiB used; no voice model was loaded')
    return {'queue_empty': True, 'gpu_utilization_percent': utilization, 'gpu_memory_mib': memory,
            'utilization_used_as_inference_gate': False, 'maximum_memory_mib': 6144, 'sampled_at': time.time()}


def load_voice_model():
    import torch
    from qwen_tts import Qwen3TTSModel

    torch.set_num_threads(2)
    return Qwen3TTSModel.from_pretrained(str(MODEL_PATH), local_files_only=True,
        device_map='cuda:0', dtype=torch.bfloat16, attn_implementation='sdpa')


def generate_candidate(spec, model, output, preflight):
    """One output bundle using an already loaded model; raw always lands first."""
    import numpy as np
    import soundfile as sf
    import torch

    reference = inside(PROJECT, spec['source_reference']['path'])
    if file_hash(reference) != spec['source_reference']['sha256']:
        raise ValueError('Approved voice reference changed before synthesis')
    shot_id = safe_id(spec['shot_id'])
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(spec, status='generating', created_at=time.time(), resource_preflight=preflight,
                    script_sha256=file_hash(__file__))
    manifest_path = output / 'manifest.json'
    write(manifest_path, manifest)
    try:
        seed = spec['seed']
        random.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        started = time.monotonic()
        waves, sr = model.generate_voice_clone(
            text=spec['expected_text'], language='Chinese', ref_audio=str(reference),
            ref_text=spec['source_reference']['transcript'], x_vector_only_mode=False,
            **spec['parameters'])
        raw = np.asarray(waves[0], dtype=np.float32)
        if raw.ndim != 1 or not raw.size or not np.isfinite(raw).all():
            raise ValueError('Voice clone did not return a finite mono waveform')
        original = output / f'{shot_id}_generated_original.wav'
        sf.write(original, raw, int(sr), subtype='FLOAT')
        manifest.update(status='raw_saved', synthesis_seconds=time.monotonic() - started,
                        raw={'path': str(original.relative_to(PROJECT)), 'sha256': file_hash(original),
                             'sample_rate': int(sr), 'channels': 1, 'duration_seconds': len(raw) / sr,
                             'peak': float(np.abs(raw).max()), 'rms': float(np.sqrt(np.mean(raw.astype(np.float64) ** 2)))})
        write(manifest_path, manifest)
        target, timing = pad_target_audio(raw, int(sr), spec.get('minimum_generation_seconds', 4.0),
                                         spec.get('lead_seconds', LEAD_SECONDS))
        final = output / f'{shot_id}_h3_fulltrack_target_32k_stereo.wav'
        sf.write(final, target, RATE, subtype='FLOAT')
        manifest.update(status='generated_pending_asr_roundtrip_and_canary', timing=timing,
                        target={'path': str(final.relative_to(PROJECT)), 'sha256': file_hash(final),
                                'sample_rate': RATE, 'channels': 2, 'duration_seconds': len(target) / RATE,
                                'peak': float(np.abs(target).max()), 'rms': float(np.sqrt(np.mean(target.astype(np.float64) ** 2)))},
                        completed_at=time.time())
        write(manifest_path, manifest)
        print(str(manifest_path), flush=True)
        return dict(manifest, manifest_path=str(manifest_path.relative_to(PROJECT)))
    except BaseException as exc:
        manifest.update(status='incomplete_raw_retained' if 'raw' in manifest else 'failed_before_audio',
                        error=str(exc), updated_at=time.time())
        write(manifest_path, manifest)
        raise


def execute(spec):
    from novel_h3.safety import bounded_worker, check_paused, check_power_cap

    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    bounded_worker()
    with locked(PROJECT, 'batch'):
        check_paused()
        check_power_cap(450)
        preflight = require_idle_gpu()
        model = load_voice_model()
        output = inside(PROJECT, spec['plan_path']).parent / 'dialogue_targets' / f"{safe_id(spec['shot_id'])}_{time.time_ns()}"
        return generate_candidate(spec, model, output, preflight)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true', help='Validate local inputs without model/GPU access (default)')
    mode.add_argument('--execute', action='store_true', help='Run only after the main controller has yielded the GPU')
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--shot', default='P03', help='One dialogue shot (default: P03)')
    parser.add_argument('--plan', help='Project-local plan path (default: pilot.json)')
    parser.add_argument('--seed', type=int, default=202610080301)
    args = parser.parse_args()
    PROJECT = args.project.resolve()
    specification = prepare(args.seed, args.shot, args.plan)
    if args.execute:
        execute(specification)
    else:
        print(json.dumps(specification, ensure_ascii=False, indent=2))

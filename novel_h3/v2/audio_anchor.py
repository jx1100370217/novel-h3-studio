"""Build existing Comfy H3 audio-latent conditioning nodes; never run inference.

The input is a complete, already timed dialogue WAV. H3 sees its encoded audio
during video sampling. This is not free audio generation or replacement dubbing.
Graph construction and CPU mask checks do not establish audiovisual quality.
"""
import math
from pathlib import PurePosixPath

VERSION = 'h3_audio_conditioned_mask_v1'
AUDIO_ROUTE = 'h3_audio_conditioned'


def _staged_wav(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.suffix.lower() != '.wav':
        raise ValueError('Target audio must be a relative staged WAV inside the Comfy input directory')
    return str(path)


def validate_target_audio(frames, target_duration_seconds):
    """Short audio makes ConcatAVLatent generate its padded tail; reject it."""
    if isinstance(frames, bool) or not isinstance(frames, int) or frames < 5 or frames % 17 != 5:
        raise ValueError('Use the actual H3 generation frame count on its 17k+5 grid')
    if isinstance(target_duration_seconds, bool):
        raise ValueError('Target WAV duration must be measured in seconds')
    duration = float(target_duration_seconds)
    clip_seconds = frames / 24.0
    if not math.isfinite(duration) or duration < clip_seconds:
        raise ValueError(
            f'Target WAV must cover the complete generated clip ({clip_seconds:.6f}s); '
            'pad the waveform with intentional lead/tail silence before VAE encoding, '
            'otherwise the audio latent tail is unmasked and can generate extra speech')
    return clip_seconds


def add_audio_anchor(nodes, *, staged_audio_name, frames, target_duration_seconds,
                     joint_latent=('6', 1), audio_vae=('4', 0), first_node_id=300):
    """Add five native nodes and return (sampling_latent_reference, route_record).

    Rewire only SamplerCustomAdvanced.latent_image to the returned reference.
    Keep the Ref2VA conditioning, images and H3 model on the existing graph.
    Full-track padding occurs in waveform space, never by pinning zero latents.
    """
    name = _staged_wav(staged_audio_name)
    clip_seconds = validate_target_audio(frames, target_duration_seconds)
    ids = [str(first_node_id + offset) for offset in range(5)]
    if any(node_id in nodes for node_id in ids):
        raise ValueError('Audio anchor node IDs collide with the existing H3 graph')
    audio, encoded, mask, masked, joined = ids
    additions = {
        audio: {'class_type': 'LoadAudio', 'inputs': {'audio': name}},
        encoded: {'class_type': 'VAEEncodeAudio', 'inputs': {'audio': [audio, 0], 'vae': list(audio_vae)}},
        mask: {'class_type': 'SolidMask', 'inputs': {'value': 0.0, 'width': 1, 'height': 1}},
        masked: {'class_type': 'SetLatentNoiseMask', 'inputs': {'samples': [encoded, 0], 'mask': [mask, 0]}},
        joined: {'class_type': 'LTXVConcatAVLatent', 'inputs': {
            'video_latent': list(joint_latent), 'audio_latent': [masked, 0]}},
    }
    nodes.update(additions)
    return [joined, 0], {
        'schema': VERSION, 'audio_route': AUDIO_ROUTE,
        'target_staged_audio': name, 'target_duration_seconds': float(target_duration_seconds),
        'generated_frames': frames, 'generated_seconds': clip_seconds,
        'target_audio_latent_frames': round(clip_seconds * 40),
        'video_noise_mask': 1.0, 'audio_noise_mask': 0.0,
        'target_audio_used_during_video_sampling': True, 'postdub': False,
        'requires_new_candidate': True, 'quality_verified': False,
        'av_sync_review': {'status': 'not_evaluated'},
        'waveform_bit_exact': False,
        'note': 'Audio latents are held during H3 video generation; VAE reconstruction and decoder gain can change the waveform. Retain the original native candidate and verify roundtrip ASR and actual visible articulation.',
    }


def audio_vae_roundtrip_graph(staged_audio_name, audio_vae_name, output_prefix):
    """Return a small encode/decode/FLAC graph and an unverified test record.

    Use the same H3 audio VAE and standard VAEDecodeAudio as the final graph.
    That decoder can attenuate high-RMS audio; this test deliberately includes
    the same path. It creates no video and cannot establish lip synchronization.
    """
    name = _staged_wav(staged_audio_name)
    prefix = PurePosixPath(output_prefix)
    if prefix.is_absolute() or '..' in prefix.parts or not prefix.name:
        raise ValueError('Roundtrip output prefix must be relative to the Comfy output directory')
    nodes = {
        '1': {'class_type': 'VAELoader', 'inputs': {'vae_name': audio_vae_name}},
        '2': {'class_type': 'LoadAudio', 'inputs': {'audio': name}},
        '3': {'class_type': 'VAEEncodeAudio', 'inputs': {'audio': ['2', 0], 'vae': ['1', 0]}},
        '4': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['3', 0], 'vae': ['1', 0]}},
        '5': {'class_type': 'SaveAudio', 'inputs': {'audio': ['4', 0], 'filename_prefix': str(prefix)}},
    }
    return nodes, {
        'schema': VERSION, 'audio_route': AUDIO_ROUTE, 'purpose': 'h3_audio_vae_roundtrip_validation',
        'target_staged_audio': name, 'audio_vae': audio_vae_name, 'output_node': '5',
        'output_extension': '.flac', 'output_prefix': str(prefix),
        'video_generated': False, 'quality_verified': False, 'postdub': False,
        'av_sync_review': {'status': 'not_evaluated'},
    }

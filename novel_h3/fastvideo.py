"""FastVideo's native NVFP4 QAD HTTP route and immutable chapter candidates."""
import json
from pathlib import Path
import urllib.error
import urllib.request

from .project import file_hash, inside, locked, read, write


def default_profile():
    runtime = Path(__file__).resolve().parents[1] / 'runtime'
    return {'backend': 'fastvideo', 'model_repo': 'FastVideo/FastH3-Omni-NVFP4-QAD',
            'revision': 'f01e6a23ac6066aa9eb622cf94b6259442e70ec2',
            'runtime_commit': 'fa2d1324c60050cd65209c6aaeac470e7fb412f5',
            'model_dir': str(runtime / 'models/FastH3-Omni-NVFP4-QAD'),
            'adaln_table': str(runtime / 'models/FastH3-Omni-NVFP4-QAD/adaln_table.pt'),
            'download_manifest': str(runtime / 'fastvideo-model-download.json'),
            'api_url': 'http://127.0.0.1:8195', 'production_enabled': True,
            'input_mode': 'ref2va', 'steps': 8,
            'scheduler_shift_video': 12.0, 'scheduler_shift_audio': 3.0}


def selected(cfg):
    return cfg.get('video_engine') == 'fast_h3_omni' and cfg.get('fast_h3_omni', {}).get('backend') == 'fastvideo'


def available(cfg):
    p = cfg.get('fast_h3_omni', {})
    root = Path(p.get('model_dir', '/nonexistent'))
    return (p.get('backend') == 'fastvideo' and p.get('production_enabled') is True
            and all((root / name).is_file() for name in (
                'fastvideo_inference.json', 'transformer_ref/nvfp4_weights.safetensors',
                'text_encoder/model.safetensors.index.json',
                'vae_decoder_nvfp4/decoder-nvfp4.safetensors'))
            and Path(p.get('adaln_table', '/nonexistent')).is_file())


def api(cfg, route, payload=None):
    base = cfg['fast_h3_omni']['api_url'].rstrip('/')
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + route, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def model_lock(root, cfg):
    p = cfg['fast_h3_omni']
    model = Path(p['model_dir'])
    manifest = read(p['download_manifest'])
    if manifest['model_repo'] != p['model_repo'] or manifest['revision'] != p['revision']:
        raise ValueError('FastVideo checkpoint revision differs from the download manifest')
    cache_path = Path(root) / 'production_v2/fastvideo_model_lock.json'
    previous = read(cache_path) if cache_path.exists() else {}
    files = {}
    paths = [(row['path'], model / row['path'], row) for row in manifest['files']
             if row['path'] != '.gitattributes']
    paths.append(('adaln_table', Path(p['adaln_table']), {}))
    for name, path, expected in paths:
        stat = path.stat()
        identity = {'path': str(path.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        old = previous.get('files', {}).get(name, {})
        sha = old.get('sha256') if old.get('identity') == identity else file_hash(path)
        if expected.get('size') is not None and expected['size'] != stat.st_size:
            raise ValueError('Incomplete FastVideo component: ' + name)
        if expected.get('sha256') and sha != expected['sha256']:
            raise ValueError('FastVideo component SHA-256 mismatch: ' + name)
        files[name] = {'identity': identity, 'sha256': sha}
    result = {'model_repo': p['model_repo'], 'revision': p['revision'], 'actual_model': p['model_repo'],
              'runtime': 'FastVideo', 'runtime_commit': p['runtime_commit'],
              'runtime_launcher_sha256': file_hash(Path(__file__).resolve().parents[1] / 'start_fastvideo.py'),
              'quantization': 'NVFP4 QAD', 'attention_prefix': 'fp8', 'files': files}
    if result != previous:
        write(cache_path, result)
    return result


def request_payload(root, request):
    root = Path(root)
    from .ref2va import validate
    validate(request['prompt'], request['visuals'], request['voices'], request['shot'].get('spoken_lines', []),
             duration_seconds=request['frames'] / 24, single_shot=True, no_music=True,
             additional_visible_people=request['shot'].get('additional_visible_people', []), require_population=True)
    if request['generation']['width'] * request['generation']['height'] > 1032192:
        raise ValueError('FastVideo MiniMax-H3 canvas exceeds the official 1032192-pixel limit')
    return {'model': 'fasth3-omni-nvfp4-qad', 'task': 'ref2va', 'prompt': request['prompt'],
            'width': request['generation']['width'], 'height': request['generation']['height'],
            'num_frames': request['frames'], 'fps': 24, 'num_inference_steps': 8,
            'guidance_scale': 1.0, 'seed': request['seed'],
            'image_reference': [{'image_url': str(inside(root, ref['generation_path']))}
                                for ref in request['visuals']],
            'audio_reference': [{'audio_url': str(inside(root, ref['path']))}
                                for ref in request['voices']]}

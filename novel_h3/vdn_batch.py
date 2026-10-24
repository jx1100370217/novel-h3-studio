"""Global VDN-H3 batch driver for strict-Ref2VA shot specs.

The VDN-H3 ComfyUI graph supports reference images and up to three standalone
audio references. We build the exact same locked Ref2VA prompt as FastVideo,
then submit it through the official ``vdn_h3_video`` tool. Takes live under
``takes_vdn/<shot>/native.mp4`` so the VDN cut can be composed independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENMONTAGE = ROOT / 'openmontage'
if str(OPENMONTAGE) not in sys.path:
    sys.path.insert(0, str(OPENMONTAGE))

from novel_h3.fastvideo_batch import build_payload, load_spec  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    from tools.video.vdn_h3_video import VdnH3VideoTool

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='OpenMontage project for progress/receipts')
    parser.add_argument('--fastvideo-project', type=Path, required=True, help='project holding shots and assets')
    parser.add_argument('--specs-dir', type=Path, default=None)
    parser.add_argument('--takes-subdir', default='takes_vdn')
    parser.add_argument('--shots', default='')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--width', type=int, default=1344)
    parser.add_argument('--height', type=int, default=768)
    parser.add_argument('--comfy-url', default='http://127.0.0.1:8191')
    parser.add_argument('--timeout', type=int, default=2400)
    parser.add_argument('--progress', type=Path, default=None)
    args = parser.parse_args(argv)

    project = args.project.resolve()
    fastvideo_project = args.fastvideo_project.resolve()
    specs_dir = (args.specs_dir or fastvideo_project / 'shots_v5').resolve()
    specs = sorted(specs_dir.glob('*.json'))
    if args.shots:
        wanted = {s.strip() for s in args.shots.split(',') if s.strip()}
        specs = [p for p in specs if p.stem in wanted]
    if not specs:
        parser.error('no specs found')
    progress_path = (args.progress or project / 'v5' / 'vdn_render_progress.json').resolve()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress = {'phase': 'render', 'done': 0, 'total': len(specs), 'current': '',
                'updated_at': time.time(), 'failures': []}
    tool = VdnH3VideoTool()

    for index, spec_path in enumerate(specs, 1):
        spec = load_spec(spec_path)
        sid = spec['shot']
        outdir = fastvideo_project / args.takes_subdir / sid
        outdir.mkdir(parents=True, exist_ok=True)
        native = outdir / 'native.mp4'
        audio = outdir / 'native_audio.flac'
        receipt_path = outdir / 'receipt.json'
        payload = build_payload(ROOT, spec, width=args.width, height=args.height)
        prompt_sha = payload.pop('_prompt_sha256')
        image_refs = [ref['image_url'] for ref in payload.get('image_reference', [])]
        audio_refs = [ref['audio_url'] for ref in payload.get('audio_reference', [])]
        key = {'prompt_sha256': prompt_sha, 'width': args.width, 'height': args.height,
               'frames': payload['num_frames'], 'seed': payload['seed'],
               'image_refs': image_refs, 'audio_refs': audio_refs}
        if native.is_file() and receipt_path.is_file() and not args.force:
            old = json.loads(receipt_path.read_text(encoding='utf-8'))
            if all(old.get(k) == v for k, v in key.items()):
                progress['done'] += 1
                print(f'[{index}/{len(specs)}] {sid} CACHED', flush=True)
                continue
        progress['current'] = sid
        progress['updated_at'] = time.time()
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
        started = time.time()
        result = tool.execute({
            'prompt': payload['prompt'],
            'reference_images': [{'path': p, 'asset_id': Path(p).stem} for p in image_refs],
            'audio_references': [{'path': p, 'asset_id': Path(p).stem} for p in audio_refs],
            'output_path': str(native),
            'audio_output_path': str(audio),
            'width': args.width, 'height': args.height,
            'frames': payload['num_frames'], 'fps': 24, 'seed': payload['seed'],
            'comfy_url': args.comfy_url,
            'filename_prefix': f'openmontage/kaochenghuang_vdn/{sid}',
            'timeout_seconds': args.timeout,
        })
        if not result.success:
            progress['failures'].append({'shot': sid, 'error': result.error})
            print(f'[{index}/{len(specs)}] {sid} FAILED: {result.error}', flush=True)
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
            continue
        receipt = {
            **key,
            'shot': sid,
            'tool': 'vdn_h3_video',
            'model': 'minimax_h3_ref2va + vdn_h3_turbo',
            'sha256': sha256(native),
            'audio_sha256': sha256(audio) if audio.is_file() else None,
            'inference_time_s': result.data.get('duration_seconds'),
            'wall_seconds': round(time.time() - started, 2),
        }
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        progress['done'] += 1
        progress['updated_at'] = time.time()
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[{index}/{len(specs)}] {sid} {receipt["wall_seconds"]}s {args.width}x{args.height}', flush=True)
    progress['phase'] = 'render_done'
    progress['current'] = ''
    progress['updated_at'] = time.time()
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'VDN DONE {progress["done"]}/{progress["total"]} failures={len(progress["failures"])}', flush=True)
    return 1 if progress['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

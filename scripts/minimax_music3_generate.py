#!/usr/bin/env python3
"""Generate instrumental music with a locally served MiniMax Music 3.

The model is served by ComfyUI using the Comfy-Org repack:

- minimax_music3_dit_fp16.safetensors -> models/diffusion_models/
- minimax_music3_text_encoder_pruned_int8_convrot.safetensors -> models/text_encoders/
- minimax_music3_dav.safetensors -> models/vae/

Example:
    python scripts/minimax_music3_generate.py \
      --caption assets/music/prompts/painting.txt \
      --lyrics assets/music/prompts/instrumental.txt \
      --duration 110 --seed 9201 --prefix huabi_m3/painting

The output is written under ComfyUI's ``output/<prefix>_00001.<format>``.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def load_workflow(
    *,
    caption: str,
    lyrics: str,
    duration: float,
    seed: int,
    prefix: str,
    output_format: str,
) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "minimax_music3_dit_fp16.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
                "type": "minimax",
                "device": "default",
            },
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "minimax_music3_dav.safetensors"},
        },
        "4": {
            "class_type": "MiniMaxMusic3TextEncode",
            "inputs": {
                "clip": ["2", 0],
                "caption": caption,
                "lyrics": lyrics,
                "seed": seed,
                "max_duration": duration,
                "cfg_scale": 1.5,
                "top_k": 50,
            },
        },
        "5": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["4", 0]},
        },
        "6": {
            "class_type": "EmptyMiniMaxMusic3LatentAudio",
            "inputs": {"seconds": ["4", 1], "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 1.5,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveAudioAdvanced",
            "inputs": {
                "audio": ["8", 0],
                "filename_prefix": prefix,
                "format": output_format,
            },
        },
    }


def submit(server: str, workflow: dict) -> str:
    request = urllib.request.Request(
        f"{server.rstrip('/')}/prompt",
        data=json.dumps({"prompt": workflow}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("node_errors"):
        raise SystemExit(f"ComfyUI rejected the workflow: {payload['node_errors']}")
    return payload["prompt_id"]


def wait(server: str, prompt_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"{server.rstrip('/')}/history/{prompt_id}", timeout=15
        ) as response:
            raw = response.read().decode("utf-8")
        if raw != "{}":
            history = json.loads(raw, strict=False)
            entry = history.get(prompt_id, {})
            if entry.get("outputs") or entry.get("status", {}).get("completed"):
                return entry
        time.sleep(3)
    raise SystemExit(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caption", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prefix", default="minimax_music3/take")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--format", choices=["flac", "mp3", "opus"], default="flac")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()

    caption = args.caption.read_text(encoding="utf-8").strip()
    lyrics = args.lyrics.read_text(encoding="utf-8").strip()
    workflow = load_workflow(
        caption=caption,
        lyrics=lyrics,
        duration=args.duration,
        seed=args.seed,
        prefix=args.prefix,
        output_format=args.format,
    )
    prompt_id = submit(args.server, workflow)
    print(f"submitted {prompt_id}")
    entry = wait(args.server, prompt_id, args.timeout)
    print(json.dumps(entry.get("outputs", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

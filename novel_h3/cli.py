import argparse
import json
from pathlib import Path
import sys

from .project import (ingest, read, write, status, analysis_packet, accept_analysis,
                      register_asset, approve_asset, update_state, safe_id)
from .arcreel import save_inventory, create_asset_jobs, save_content, approve_content, visual_packet, compile_visual
from .director import approve_episode, validate_episode, episode_path, coverage, series_packet
from .comfy import doctor, submit_next, sync, cancel, review_take, config, graph, schema_check, api
from .media import assemble_episode, assemble_book, assemble_preview, assemble_chapter, assemble_latest

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO / "projects/rendao-wuji"


def configure(root):
    runtime = REPO / "runtime"
    for name in ("comfy-input", "comfy-output", "comfy-user"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    # A new project must be immediately readable by the workbench.  Keep the
    # registries empty until the authoring steps fill them; do not make an
    # empty project look as if it already has approved assets.
    (Path(root) / "bible").mkdir(parents=True, exist_ok=True)
    write(Path(root) / "bible/assets.json", {"characters": {}, "scenes": {}, "props": {}})
    write(Path(root) / "bible/voices.json", {})
    write(Path(root) / "bible/character_views.json", {"schema": "character_four_views_v1", "characters": {}})
    write(Path(root) / "config.json", {
        "comfy_root": "/home/jx/codes/comfyui-minimax-h3", "comfy_url": "http://127.0.0.1:8191",
        "input_dir": str(runtime / "comfy-input"), "output_dir": str(runtime / "comfy-output"),
        "upstream_commit": "5335715abe54c1a9bfbe3494da29aae3e8635ce3",
        "models": {"fl2va": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                   "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                   "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                   "video_vae": "minimax_h3_video_vae_fp16.safetensors", "audio_vae": "minimax_h3_audio_vae_fp32.safetensors"},
        "generation": {"width": 1376, "height": 768, "steps": 8, "fps": 24, "sampler": "er_sde", "scheduler": "beta", "crop_to_delivery": True},
        "vdn": read(REPO / "examples/vdn_profile.json"),
        "delivery": {"width": 1366, "height": 768, "audio_sample_rate": 48000,
                     "scaling": "1376×768生成，左右各裁5像素交付1366×768", "super_resolution_model": "VOSR2 one-step 1.4B", "super_resolution_enabled": False},
        "image_provider": {"provider": "codex_image_gen", "subscription": "ChatGPT 5x", "requested_model": "Images 2.5", "model_selection": "managed_by_codex", "verified_route_available": False},
        "asset_policy": {"require_every_scene": True, "require_approved_assets": True,
                         "generation_route": "Codex 当前对话 image_gen；人物、场景、道具逐项生成并登记后才可进入正式镜头"},
        "arcreel_commit": "93f14642506f13a6ee78c4b7c6d54ce3dfa8ad7c",
        "style": "Photorealistic Chinese mythological period cinema. Natural skin and weathered materials, motivated practical lighting, restrained saturation, grounded scale, controlled camera inertia, subtle acting. No game rendering, no anime, no floating camera without motivation, no captions or storyboard graphics.",
        "bgm": {"source_type": "douyin_library", "enabled": False},
        "reference": {"title": "问苍生", "author": "青瓜蛋", "url": "https://www.douyin.com/video/7674459865061887267",
                      "observed_duration": "26:14", "review_scope": "浏览器核对标题、时长并抽查部分画面；未完成全片逐镜和听音分析"}
    })
    write(Path(root) / "series.json", {"status": "awaiting_full_book_analysis", "episode_ids": [],
                                      "target_episode_minutes": [12, 20], "ending_policy": "保留连载结尾，不伪造完结"})


def prepare_packets(root):
    root = Path(root)
    book = read(root / "book.json")
    for chapter in book["chapters"]:
        write(root / "jobs" / f"analysis_{chapter['id']}.json", analysis_packet(root, chapter["id"]))
    return {"chapter_packets": len(book["chapters"]), "next": "逐章分析完成后整合 bible 与 series，再按剧情生成 episodes"}


def main():
    parser = argparse.ArgumentParser(description="多项目影视制片工作台")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init"); p.add_argument("source", type=Path)
    for name in ("status", "doctor", "prepare", "coverage", "sync", "cancel", "assemble-book", "series-packet", "asset-jobs"):
        sub.add_parser(name)
    p = sub.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("packet"); p.add_argument("section")
    p = sub.add_parser("import-analysis"); p.add_argument("file", type=Path)
    for name in ("import-assets", "import-content"):
        p = sub.add_parser(name); p.add_argument("file", type=Path)
    p = sub.add_parser("visual-packet"); p.add_argument("episode")
    p = sub.add_parser("compile-visual"); p.add_argument("episode"); p.add_argument("file", type=Path)
    p = sub.add_parser("approve-content"); p.add_argument("episode"); p.add_argument("--reviewer", required=True); p.add_argument("--note", required=True)
    p = sub.add_parser("register-image"); p.add_argument("asset"); p.add_argument("file", type=Path); p.add_argument("receipt", type=Path)
    p = sub.add_parser("approve-image"); p.add_argument("asset"); p.add_argument("--reviewer", required=True); p.add_argument("--note", required=True)
    for name in ("validate", "submit", "submit-preview", "assemble", "assemble-preview"):
        p = sub.add_parser(name); p.add_argument("episode")
    p = sub.add_parser("assemble-chapter"); p.add_argument("section")
    sub.add_parser("assemble-latest")
    p = sub.add_parser("approve-plan"); p.add_argument("episode"); p.add_argument("--reviewer", required=True); p.add_argument("--note", required=True)
    p = sub.add_parser("review-take"); p.add_argument("take"); p.add_argument("review", type=Path)
    p = sub.add_parser("listen"); p.add_argument("file", type=Path); p.add_argument("--device", choices=("cuda", "cpu"), default="cuda"); p.add_argument("--language", choices=("zh", "auto", "en"), default="zh")
    args = parser.parse_args()
    root = args.project.resolve()
    try:
        if args.command == "init":
            result = ingest(args.source, root); configure(root); prepare_packets(root)
            result = {"project": str(root), "chapters": len(result["chapters"]), "issues": result["issues"]}
        elif args.command == "serve":
            from .server import serve
            serve(root, args.port, not args.no_browser); return
        elif args.command == "status": result = status(root)
        elif args.command == "doctor": result = doctor(root)
        elif args.command == "prepare": result = prepare_packets(root)
        elif args.command == "coverage": result = coverage(root)
        elif args.command == "series-packet": result = series_packet(root)
        elif args.command == "packet": result = analysis_packet(root, args.section)
        elif args.command == "import-analysis": result = accept_analysis(root, read(args.file))
        elif args.command == "import-assets": result = save_inventory(root, read(args.file))
        elif args.command == "asset-jobs": result = create_asset_jobs(root)
        elif args.command == "import-content": result = save_content(root, read(args.file))
        elif args.command == "approve-content": result = approve_content(root, args.episode, args.reviewer, args.note)
        elif args.command == "visual-packet": result = visual_packet(root, args.episode)
        elif args.command == "compile-visual": result = compile_visual(root, args.episode, read(args.file))
        elif args.command == "register-image": result = register_asset(root, args.asset, args.file, read(args.receipt))
        elif args.command == "approve-image":
            result = approve_asset(root, args.asset, args.reviewer, args.note)
        elif args.command == "validate": result = {"errors": validate_episode(root, read(episode_path(root, args.episode)))}
        elif args.command == "approve-plan": result = approve_episode(root, args.episode, args.reviewer, args.note)
        elif args.command == "submit": result = submit_next(root, args.episode)
        elif args.command == "submit-preview": result = submit_next(root, args.episode, preview=True)
        elif args.command == "sync": result = sync(root)
        elif args.command == "cancel": result = cancel(root)
        elif args.command == "review-take":
            review = read(args.review)
            result = review_take(root, args.take, review["approved"], review["note"], review["reviewer"], review["checks"])
        elif args.command == "assemble": result = assemble_episode(root, args.episode)
        elif args.command == "assemble-preview": result = assemble_preview(root, args.episode)
        elif args.command == "assemble-chapter": result = assemble_chapter(root, args.section)
        elif args.command == "assemble-latest": result = assemble_latest(root)
        elif args.command == "assemble-book": result = assemble_book(root)
        elif args.command == "listen":
            from .listening import start_audio
            result = start_audio(root, args.file, args.device, args.language)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "validate" and result["errors"]:
            sys.exit(1)
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

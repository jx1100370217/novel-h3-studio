"""Replace H3-native speech with the project's exact local dialogue tracks."""
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .project import file_hash, inside, read, write


def apply(root, take, shot, source, out, samples, sr, recognition, transcribe):
    root, source, out = Path(root).resolve(), Path(source).resolve(), Path(out).resolve()
    config = read(root / "config.json")
    policy = config.get("speech_policy", {})
    manifest_path = inside(root, policy.get(
        "dialogue_dub_manifest",
        f"voices/{take['episode']}_qwen3_dubs/manifest.json"))
    if not manifest_path.is_file():
        return {"status": "blocked", "reason": "本地对白配音清单不存在"}
    manifest = read(manifest_path)
    rows = [row for row in manifest.get("lines", [])
            if row.get("episode") == take["episode"] and row.get("shot") == shot["id"]]
    expected = "".join(line.get("text", "") for line in shot.get("dialogue", []))
    speakers = {line.get("speaker") for line in shot.get("dialogue", [])}
    if len(rows) != 1 or len(speakers) != 1:
        return {"status": "blocked", "reason": "配音清单必须为本镜唯一说话人提供一条完整对白"}
    row = rows[0]
    if row.get("text") != expected or row.get("speaker") not in speakers:
        return {"status": "blocked", "reason": "配音台词或说话人与当前锁定分镜不一致"}
    if row.get("strict_asr_passed") is not True:
        return {"status": "blocked", "reason": "配音清单中的严格转写尚未通过"}
    voice = inside(root, row.get("path", ""))
    if not voice.is_file() or file_hash(voice) != row.get("sha256"):
        return {"status": "blocked", "reason": "配音文件缺失或 SHA-256 与清单不符"}

    from .audio_cleanup import clean_unbound_speech, alignment_evidence, preserve_audio_master
    from .voice_gate import detect_speech

    source_sha = file_hash(source)
    original_master = preserve_audio_master(source, out)
    backup = out / "audio_before_cleanup.flac"
    if not backup.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                        "-map", "0:a:0", "-vn", "-c:a", "flac", str(backup)],
                       check=True, timeout=90, capture_output=True)

    cleanup = {"status": "not_applied", "reason": "原始音轨未检测到人声"}
    if recognition and recognition.get("text", "").strip():
        cleanup = clean_unbound_speech(source, out, recognition, samples, sr,
                                       expected="", dialogue=None, aggressive=True)
    elif recognition and recognition.get("chunks"):
        cleanup = clean_unbound_speech(source, out, recognition, samples, sr,
                                       expected="", dialogue=None, aggressive=True)

    fallback_muted = False
    # A blocked mask cannot prove that H3 speech was removed. Silence the H3
    # bed in that case; the exact registered Qwen line is still added below.
    if cleanup.get("status") == "blocked":
        fallback_muted = True
    elif cleanup.get("status") == "applied":
        cleaned_path = out / "dialogue_cleaned_mono.wav"
        from audio_review import decode_audio
        decode_audio(source, cleaned_path)
        cleaned_samples, cleaned_sr = sf.read(cleaned_path, dtype="float32")
        residual_vad = detect_speech(cleaned_samples, cleaned_sr)
        if residual_vad.get("speech_detected"):
            residual = transcribe(cleaned_samples, cleaned_sr, timestamps=True)
            if residual.get("text", "").strip():
                fallback_muted = True
        cleaned_path.unlink(missing_ok=True)
    elif cleanup.get("status") == "not_applied" and recognition and recognition.get("text", "").strip():
        fallback_muted = True

    scratch = out / "dialogue_dub_work"
    scratch.mkdir(parents=True, exist_ok=True)
    ambient_path = scratch / "ambient_48k_stereo.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                    "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000",
                    "-c:a", "pcm_f32le", str(ambient_path)],
                   check=True, timeout=90, capture_output=True)
    ambient, ambient_sr = sf.read(ambient_path, dtype="float32")
    if ambient.ndim == 1:
        ambient = np.column_stack((ambient, ambient))
    if fallback_muted:
        ambient[:] = 0.0

    lines = shot.get("dialogue", [])
    start_frame = min(line["start_frame"] for line in lines)
    end_frame = max(line["end_frame"] for line in lines)
    window_start, window_end = start_frame / 24.0, end_frame / 24.0
    window_duration = window_end - window_start
    voice_samples, voice_sr = sf.read(voice, dtype="float32")
    if voice_samples.ndim == 2:
        voice_samples = voice_samples.mean(axis=1)
    if voice_samples.size == 0 or voice_sr <= 0:
        return {"status": "blocked", "reason": "配音文件无有效音频"}
    raw_duration = len(voice_samples) / voice_sr
    raw_vad = detect_speech(voice_samples, voice_sr)
    if not raw_vad.get("available") or not raw_vad.get("speech_detected"):
        return {"status": "blocked", "reason": "对白配音未通过独立人声检测"}
    desired_voice_end = window_duration - 0.12
    raw_voice_end = max(span["end"] for span in raw_vad["speech_segments"])
    if desired_voice_end <= 0:
        return {"status": "blocked", "reason": "对白锁定时窗过短"}
    # Match the measured Qwen speech span to the authored dialogue window. The
    # source audio has already passed strict ASR; only small tempo changes are
    # allowed, and the per-shot VAD is checked again after time stretching.
    tempo = min(1.25, max(0.75, raw_voice_end / desired_voice_end))
    tempo_path = scratch / "dialogue_tempo.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(voice),
                    "-af", f"atempo={tempo:.6f},aresample=48000", "-ac", "2", "-ar", "48000",
                    "-c:a", "pcm_f32le", str(tempo_path)],
                   check=True, timeout=90, capture_output=True)
    dub, dub_sr = sf.read(tempo_path, dtype="float32")
    if dub.ndim == 1:
        dub = np.column_stack((dub, dub))
    mixed_vad = detect_speech(dub, dub_sr)
    if not mixed_vad.get("available") or not mixed_vad.get("speech_detected"):
        return {"status": "blocked", "reason": "时长调整后的对白未通过人声复核"}
    speech_windows = [[round(window_start + span["start"], 3),
                       round(window_start + span["end"], 3)]
                      for span in mixed_vad["speech_segments"]]
    from .audio_cleanup import timing_alignment
    timing_gate = timing_alignment(speech_windows, lines)
    if timing_gate.get("status") != "passed":
        return {"status": "blocked", "reason": "Qwen 配音与分镜锁定时窗不匹配",
                **alignment_evidence(timing_gate)}
    offset = round(window_start * ambient_sr)
    if offset + len(dub) > len(ambient):
        return {"status": "blocked", "reason": "配音超出镜头音轨长度，禁止截断后交付"}
    ambient[offset:offset + len(dub)] += dub
    peak = float(np.max(np.abs(ambient))) if ambient.size else 0.0
    if peak > 0.92:
        ambient *= 0.92 / peak

    mixed = out / "dialogue_qwen_postdub.wav"
    sf.write(mixed, ambient, ambient_sr, subtype="PCM_24")
    candidate = out / "dialogue_dub_candidate.mp4"
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-i", str(mixed),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                        "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart",
                        str(candidate)], check=True, timeout=120, capture_output=True)
        candidate.replace(source)
    finally:
        candidate.unlink(missing_ok=True)

    report = {
        "status": "applied",
        "source_video_sha256": source_sha,
        "video_sha256": file_hash(source),
        "original_h3_audio": str(backup.name),
        "original_audio_master": original_master,
        "h3_speech_cleanup": cleanup,
        "fallback_muted_h3_bed": fallback_muted,
        "manifest": str(manifest_path.relative_to(root)),
        "speaker": row["speaker"],
        "expected": expected,
        "voice_path": str(voice.relative_to(root)),
        "voice_sha256": row["sha256"],
        "voice_raw_duration": round(raw_duration, 3),
        "voice_mixed_duration": round(len(dub) / dub_sr, 3),
        "tempo": round(tempo, 4),
        "locked_window": [round(window_start, 3), round(window_end, 3)],
        "mix_start_seconds": round(window_start, 3),
        "speech_windows": speech_windows,
        **alignment_evidence(timing_gate),
        "ambient_sample_rate": ambient_sr,
        "bgm": False,
        "human_listened": False,
    }
    policy_path = out / "audio_policy.json"
    audio_policy = read(policy_path) if policy_path.is_file() else {}
    audio_policy.update(status="preserved", policy="diegetic_only_with_exact_dialogue",
                        dialogue_audio_source="qwen3_tts_local_postdub", bgm=False,
                        audio_before_cleanup=backup.name, video_sha256=report["video_sha256"])
    write(policy_path, audio_policy)
    return report

"""Human-voice activity detection before ASR.

Whisper is a generative recognizer and may invent a common outro phrase when
fed silence or effects.  This module provides a small, language-independent
gate so the recognizer is only called after an actual speech interval is
detected.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def _silero_model():
    from silero_vad import load_silero_vad

    return load_silero_vad()


def _resample_mono(samples, sample_rate):
    import numpy as np
    import torch
    import torchaudio

    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if data.size == 0:
        return torch.zeros(0, dtype=torch.float32), 16000
    tensor = torch.from_numpy(data)
    if int(sample_rate) != 16000:
        tensor = torchaudio.functional.resample(tensor, int(sample_rate), 16000)
    return tensor.contiguous(), 16000


def detect_speech(samples, sample_rate, *, threshold=0.5,
                  min_speech_duration_ms=120, min_silence_duration_ms=150):
    """Return Silero VAD spans and a fail-closed availability state."""
    try:
        import torch
        from silero_vad import get_speech_timestamps

        audio, rate = _resample_mono(samples, sample_rate)
        if audio.numel() == 0:
            return {
                "available": True,
                "detector": "silero_vad",
                "model": "silero-vad",
                "speech_detected": False,
                "speech_segments": [],
                "speech_seconds": 0.0,
                "speech_ratio": 0.0,
                "threshold": threshold,
            }
        with torch.inference_mode():
            raw = get_speech_timestamps(
                audio,
                _silero_model(),
                sampling_rate=rate,
                threshold=threshold,
                min_speech_duration_ms=min_speech_duration_ms,
                min_silence_duration_ms=min_silence_duration_ms,
                return_seconds=True,
            )
        spans = [
            {"start": round(float(item["start"]), 3),
             "end": round(float(item["end"]), 3)}
            for item in raw
            if float(item["end"]) > float(item["start"])
        ]
        speech_seconds = sum(item["end"] - item["start"] for item in spans)
        duration = audio.numel() / rate
        return {
            "available": True,
            "detector": "silero_vad",
            "model": "silero-vad",
            "speech_detected": bool(spans),
            "speech_segments": spans,
            "speech_seconds": round(speech_seconds, 3),
            "speech_ratio": round(speech_seconds / max(duration, 1e-6), 4),
            "threshold": threshold,
            "min_speech_duration_ms": min_speech_duration_ms,
            "min_silence_duration_ms": min_silence_duration_ms,
        }
    except Exception as exc:  # pragma: no cover - exercised by broken installs
        return {
            "available": False,
            "detector": "silero_vad",
            "speech_detected": None,
            "speech_segments": [],
            "speech_seconds": 0.0,
            "speech_ratio": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }

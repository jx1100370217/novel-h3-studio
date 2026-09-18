"""Conservative speech-only track with a dialogue timing/lip-sync gate."""
import math
import os
import re
import subprocess
import zlib
from difflib import SequenceMatcher
from pathlib import Path


def speech_windows(chunks, duration, padding=.25):
    windows = []
    for chunk in chunks:
        if not chunk.get('text', '').strip():
            continue
        start, end = chunk.get('timestamp', (None, None))
        if start is None or end is None or not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= duration + .1:
            raise ValueError('语音时间边界不完整，不能自动静音')
        start, end = max(0, start-padding), min(duration, end+padding)
        if windows and start < windows[-1][0]:
            raise ValueError('语音时间顺序异常')
        if windows and start <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])
    if not windows:
        raise ValueError('没有可信的语音时间段')
    return windows


def matching_dialogue_span(chunks, expected):
    """Return the contiguous ASR chunk span for one complete utterance."""
    from .speech_qc import compare
    if not expected.strip():
        return None
    for start in range(len(chunks)):
        text = ''
        for end in range(start, len(chunks)):
            text += chunks[end].get('text', '')
            if compare(expected, text)['passed']:
                return start, end + 1
    return None


def matching_dialogue_chunks(chunks, expected):
    """Keep a complete exact utterance span, never splice fragments into new speech."""
    span = matching_dialogue_span(chunks, expected)
    return chunks[span[0]:span[1]] if span else []


def _spoken_text(text):
    """Normalize text only for a conservative cleanup safety check.

    This is deliberately separate from ``speech_qc.compare``.  The strict
    transcription gate still requires an exact match; this helper is used
    only to decide whether it is unsafe to destroy a likely-correct take.
    """
    return ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', str(text))).lower().translate(
        str.maketrans({'她': '他', '它': '他', '祂': '他'}))


def likely_dialogue_span(chunks, expected):
    """Find a probable locked-dialogue span without changing strict QC.

    Whisper commonly substitutes one character or omits punctuation.  When
    that happens, treating every ASR chunk as an unbound voice would attenuate
    the actor's entire line.  A high-similarity span therefore blocks cleanup
    and preserves the source for review.  It never makes a failed comparison
    pass and it is intentionally conservative for short lines.
    """
    target = _spoken_text(expected)
    if not target:
        return None
    # Very short utterances have too little information for a similarity
    # fallback; exact matching remains the only safe decision there.
    threshold = .96 if len(target) <= 8 else .86
    best = None
    for start in range(len(chunks)):
        text = ''
        for end in range(start, len(chunks)):
            text += str(chunks[end].get('text', ''))
            actual = _spoken_text(text)
            if not actual:
                continue
            # Reject fragments and spans dominated by appended narration.
            coverage = len(actual) / max(len(target), 1)
            if coverage < .68 or coverage > 1.45:
                continue
            score = SequenceMatcher(None, target, actual, autojunk=False).ratio()
            candidate = (score, -abs(len(actual) - len(target)), start, end + 1, text)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    if best is None or best[0] < threshold:
        return None
    return {
        'start_chunk': best[2],
        'end_chunk': best[3],
        'transcript': best[4],
        'similarity': round(best[0], 4),
        'threshold': threshold,
    }


def dialogue_windows(dialogue, fps=24):
    """Return the locked picture-time windows for the shot's dialogue."""
    windows = []
    for line in dialogue or []:
        start, end = line.get('start_frame'), line.get('end_frame')
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError('分镜对白时间边界不完整，不能自动静音')
        windows.append([start / fps, end / fps])
    return windows


def normalize_diegetic_mix(source, out, samples, sr, target_db=-18.0, peak_db=-1.0):
    """Raise an unusually quiet H3 mix without flattening its dynamics.

    H3 may return an otherwise valid dialogue/effects track at -24 dBFS RMS.
    Apply make-up gain only below the target and cap true sample peak at
    -1 dBFS, leaving the relative speech/effect balance untouched.
    """
    import numpy as np
    import soundfile as sf
    from .project import file_hash
    from audio_review import decode_audio

    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        return {'status': 'not_applied', 'reason': '音轨为空'}
    if data.ndim == 1:
        data = np.column_stack((data, data))
    if data.shape[1] > 2:
        data = data[:, :2]
    rms = float(np.sqrt(np.mean(data ** 2)))
    peak = float(np.max(np.abs(data)))
    if rms <= 1e-7 or peak <= 1e-7:
        return {'status': 'not_applied', 'reason': '音轨近似静音'}
    rms_db = 20.0 * math.log10(rms)
    peak_dbfs = 20.0 * math.log10(peak)
    requested_db = max(0.0, float(target_db) - rms_db)
    headroom_db = float(peak_db) - peak_dbfs
    gain_db = min(requested_db, max(0.0, headroom_db))
    if gain_db < .1:
        return {'status': 'not_applied', 'reason': '响度已在目标范围',
                'rms_db_before': round(rms_db, 3), 'peak_db_before': round(peak_dbfs, 3)}
    gain = 10.0 ** (gain_db / 20.0)
    data *= gain
    candidate = Path(out) / 'audio_mix_candidate.mp4'
    wav = Path(out) / 'audio_mix_normalized.wav'
    before_audio = Path(out) / 'audio_before_mix_normalization.flac'
    try:
        sf.write(wav, data.astype(np.float32), sr, subtype='PCM_24')
        if not before_audio.exists():
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-vn',
                            '-c:a', 'flac', str(before_audio)], check=True, timeout=60)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-i', str(wav),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                        '-shortest', str(candidate)], check=True, timeout=90)
        decode_audio(candidate, Path(out) / 'audio_mix_check.wav')
        checked, _ = sf.read(Path(out) / 'audio_mix_check.wav', dtype='float32')
        before = file_hash(source)
        os.replace(candidate, source)
        final_peak = float(np.max(np.abs(checked))) if checked.size else 0.0
        final_rms = float(np.sqrt(np.mean(np.asarray(checked, dtype=np.float64) ** 2))) if checked.size else 0.0
        result = {'status': 'applied', 'policy': 'quiet_mix_makeup_gain',
                'gain_db': round(gain_db, 3), 'target_rms_db': float(target_db),
                'rms_db_before': round(rms_db, 3), 'rms_db_after': round(20 * math.log10(max(final_rms, 1e-9)), 3),
                'peak_db_before': round(peak_dbfs, 3), 'peak_db_after': round(20 * math.log10(max(final_peak, 1e-9)), 3),
                'original_video_sha256': before, 'video_sha256': file_hash(source),
                'audio_peak': final_peak}
        policy_path = Path(out) / 'audio_policy.json'
        if policy_path.exists():
            from .project import read, write
            policy = read(policy_path)
            policy.update(video_sha256=result['video_sha256'], audio_normalization=result)
            write(policy_path, policy)
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        return {'status': 'blocked', 'reason': '音量补偿未完成，保留原视频：' + str(exc)}
    finally:
        candidate.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
        (Path(out) / 'audio_mix_check.wav').unlink(missing_ok=True)


def timing_alignment(speech, dialogue, tolerance=.45):
    """Check that generated speech starts/ends near the locked mouth window.

    Audio-only muting is unsafe when H3 has shifted the utterance in time: the
    video mouth motion follows the original generated audio, not the post-QC
    muted track. In that case the caller must keep the original audio or
    request a dedicated lip-sync retake.
    """
    expected = dialogue_windows(dialogue)
    if not expected:
        return {'status': 'not_applicable', 'planned_windows': [], 'speech_windows': speech}
    planned_start, planned_end = expected[0][0], expected[-1][1]
    actual_start, actual_end = speech[0][0], speech[-1][1]
    overlap = any(max(a, c) < min(b, d) for a, b in speech for c, d in expected)
    start_delta = round(actual_start - planned_start, 3)
    end_delta = round(actual_end - planned_end, 3)
    passed = overlap and abs(start_delta) <= tolerance and abs(end_delta) <= tolerance
    return {
        'status': 'passed' if passed else 'blocked',
        'planned_windows': expected,
        'speech_windows': speech,
        'start_delta_seconds': start_delta,
        'end_delta_seconds': end_delta,
        'tolerance_seconds': tolerance,
        'reason': (None if passed else
                   '生成语音与锁定对白时段偏移，不能只清理音频；否则会出现嘴动无声'),
    }


def _diegetic_layers(shot, duration):
    """List the physical foley layers selected from the shot's action."""
    text = " ".join(str(shot.get(key, "")) for key in ("action", "visual_narration", "soundscape"))
    flags = {
        "thunder": bool(re.search(r"雷|闪电|雷鸣|雷霆|霹雳|thunder|lightning", text, re.I)),
        "rumble": bool(re.search(r"震动|震荡|山崩|地裂|坍塌|碎石|rumble|collapse|fracture", text, re.I)),
        "surf": bool(re.search(r"海水|海浪|水面|倾覆|潮|water|wave|surf|flood", text, re.I)),
        "wind": bool(re.search(r"金光|光芒|飞落|飞去|飞射|腾云|金云|云|wind|whoosh|cloud", text, re.I)),
        "steps": bool(re.search(r"走|脚踏|进入|点头|躬身|跪|站|walk|step|enter|kneel|stand", text, re.I)),
        "space": bool(re.search(r"天兵|神将|铠甲|玉笏|宫|殿|门|guard|armor|palace|hall|gate", text, re.I)),
    }
    names = [name for name, enabled in flags.items() if enabled]
    return names or ["room"]


def _render_diegetic_wav(path, shot, duration, sample_rate=32000):
    """Render shaped, time-varying foley instead of a continuous noise bed."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import butter, sosfilt

    duration = max(float(duration), 0.2)
    count = max(1, int(round(duration * sample_rate)))
    rng = np.random.default_rng(zlib.adler32(str(shot.get("id", "shot")).encode()) & 0xffffffff)
    audio = np.zeros((count, 2), dtype=np.float64)
    labels = _diegetic_layers(shot, duration)

    def filtered_noise(length, low=None, high=None):
        data = rng.normal(0.0, 1.0, max(1, int(length))).astype(np.float64)
        if low is not None and high is not None:
            sos = butter(4, [low, high], btype="bandpass", fs=sample_rate, output="sos")
        elif high is not None:
            sos = butter(4, high, btype="lowpass", fs=sample_rate, output="sos")
        elif low is not None:
            sos = butter(4, low, btype="highpass", fs=sample_rate, output="sos")
        else:
            return data
        return sosfilt(sos, data)

    def add(signal, start, gain=1.0, pan=0.0):
        signal = np.asarray(signal, dtype=np.float64)
        first = max(0, int(round(start * sample_rate)))
        if first >= count:
            return
        end = min(count, first + len(signal))
        signal = signal[:end - first] * gain
        left, right = (1.0 - pan) * 0.5, (1.0 + pan) * 0.5
        audio[first:end, 0] += signal * left
        audio[first:end, 1] += signal * right

    def burst(length, low, high, attack=0.05, decay=0.8):
        n = max(1, int(round(length * sample_rate)))
        data = filtered_noise(n, low, high)
        t = np.arange(n) / sample_rate
        env = np.minimum(1.0, t / max(attack, 1e-3)) * np.exp(-t / max(decay, 1e-3))
        data /= max(np.max(np.abs(data)), 1e-9)
        return data * env

    def damped_tone(length, frequencies, decay=0.8, attack=0.01, drop=0.0):
        """Give an effect a stable tonal body so it does not read as white noise."""
        n = max(1, int(round(length * sample_rate)))
        t = np.arange(n, dtype=np.float64) / sample_rate
        env = np.minimum(1.0, t / max(attack, 1e-3)) * np.exp(-t / max(decay, 1e-3))
        body = np.zeros(n, dtype=np.float64)
        for index, frequency in enumerate(frequencies):
            phase = index * 0.71
            glide = frequency - drop * (t / max(length, 1e-3))
            body += np.sin(2 * np.pi * glide * t + phase) / (index + 1)
        body /= max(np.max(np.abs(body)), 1e-9)
        return body * env

    text = " ".join(str(shot.get(key, "")) for key in ("action", "visual_narration", "soundscape"))
    if "thunder" in labels:
        for when in np.arange(0.55, duration, 2.8):
            boom_len = min(2.2, duration - when)
            add(damped_tone(boom_len, (42, 57, 73), 1.25, .01, 10), when, .72, -0.12)
            add(burst(boom_len, 28, 115, .03, 1.0), when, .18, -0.12)
            crack = burst(min(.11, duration - when), 1500, 9000, .002, .035)
            add(crack, when, .62, 0.10 if int(when * 10) % 2 else -0.10)
    if "rumble" in labels:
        # Impacts are separated by quiet gaps; a tiny floor keeps the room from
        # becoming digitally dead without turning the track into a noise drone.
        for when in np.arange(0.7, duration, 2.45):
            length = min(1.65, duration - when)
            add(damped_tone(length, (33, 49, 68), 1.0, .015, 6), when, .54, 0)
            add(burst(length, 28, 90, .02, .85), when, .12, 0)
        add(filtered_noise(count, 35, 85) / 18.0, 0, .14, 0)
    if "surf" in labels:
        for when in np.arange(0.15, duration, 1.45):
            length = min(1.28, duration - when)
            pan = -0.18 if int(when) % 2 else .16
            # A wave has a rounded low body, a noisy crest, then a short foam tail.
            add(damped_tone(length, (105, 145, 205), .55, .16, 8), when, .22, pan)
            add(burst(length, 120, 1550, .20, .52), when, .34, pan)
            if length > .35:
                add(burst(min(.24, length - .24), 1100, 4200, .01, .12), when + length - .24, .16, -pan)
        add(filtered_noise(count, 70, 380) / 22.0, 0, .13, 0)
    if "wind" in labels:
        data = filtered_noise(count, 280, 4200)
        t = np.arange(count) / sample_rate
        modulation = 0.04 + 0.045 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.16 * t))
        data /= max(np.max(np.abs(data)), 1e-9)
        add(data * modulation, 0, .34, 0.0)
        for when in np.arange(.4, duration, 2.6):
            length = min(1.1, duration - when)
            add(burst(length, 500, 5000, .25, .45), when, .38, -.45 if int(when) % 2 else .45)
    if "steps" in labels:
        for when in np.arange(.35, duration, 1.35):
            add(burst(min(.16, duration - when), 65, 700, .002, .055), when, .72, -.12 if int(when * 2) % 2 else .12)
            n = max(1, int(.22 * sample_rate))
            t = np.arange(n) / sample_rate
            add(np.sin(2 * np.pi * 78 * t) * np.exp(-t / .045), when, .28, 0)
    if "space" in labels:
        data = filtered_noise(count, 160, 2400)
        data /= max(np.max(np.abs(data)), 1e-9)
        add(data, 0, .10, 0)
        # Short early reflections create a room without turning into a drone.
        for delay, gain in ((.09, .08), (.17, .045)):
            add(data[:-int(delay * sample_rate)] if count > int(delay * sample_rate) else data,
                delay, gain, 0)
    if labels == ["room"]:
        data = filtered_noise(count, 90, 1700)
        data /= max(np.max(np.abs(data)), 1e-9)
        add(data, 0, .055, 0)
    if not audio.any():
        audio[:, :] = 0.012

    # Gentle final fades and peak control prevent clicks while preserving the
    # transient contrast that distinguishes thunder, surf and footsteps.
    fade = min(int(.08 * sample_rate), count // 2)
    if fade:
        audio[:fade] *= np.linspace(0, 1, fade)[:, None]
        audio[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = float(np.max(np.abs(audio)))
    if peak > .82:
        audio *= .82 / peak
    sf.write(path, audio.astype(np.float32), sample_rate, subtype="PCM_24")
    return labels


def clean_non_dialogue(source, out, shot, samples, sr):
    """Replace a no-dialogue clip's contaminated language track with foley."""
    from .project import file_hash
    from audio_review import decode_audio
    import soundfile as sf

    duration = len(samples) / sr
    result = {
        "status": "not_applied",
        "scope": "无对白镜头仅移除可识别语言声，保留或补入与画面动作对应的拟音；不生成旁白、配乐或台词。",
    }
    candidate = out / "audio_clean_candidate.mp4"
    wav = out / "audio_clean_check.wav"
    fallback_wav = out / "diegetic_fallback.wav"
    before_audio = out / "audio_before_cleanup.flac"
    layers = _render_diegetic_wav(fallback_wav, shot, duration)
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-i", str(fallback_wav),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", str(candidate)],
                       check=True, timeout=90)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-vn",
                        "-c:a", "flac", str(before_audio)], check=True, timeout=60)
        decode_audio(candidate, wav)
        cleaned, rate = sf.read(wav, dtype="float32")
        before = file_hash(source)
        os.replace(candidate, source)
        return dict(result, status="applied", policy="diegetic_fallback",
                    effect_layers=layers,
                    original_video_sha256=before,
                    audio_peak=float(abs(cleaned).max()) if cleaned.size else 0.0,
                    duration_seconds=round(duration, 3),
                    audio_before_cleanup=str(before_audio.name))
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(result, reason="音效回填未完成，保留原视频：" + str(exc))
    finally:
        candidate.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)


def clean_unbound_speech(source, out, recognition, samples, sr, expected='', dialogue=None,
                         aggressive=False):
    """Attenuate only ASR-timed speech that is not in the locked script.

    H3 mixes voices and effects into one track.  Hard muting a whole interval
    would also remove thunder or water, so this keeps the stereo side signal
    and attenuates only the centre-channel speech band with short crossfades.
    The original track is retained for audit and strict transcription remains
    unchanged. A second, aggressive pass may be requested when the first pass
    still produces recognizable words; it keeps non-speech channels/bands but
    drives the centre speech band close to silence.
    """
    from .project import file_hash
    from audio_review import decode_audio
    import numpy as np
    import soundfile as sf
    from scipy.signal import istft, stft

    duration = len(samples) / sr
    chunks = recognition.get('chunks', []) or []
    extras = []
    if expected.strip():
        span = matching_dialogue_span(chunks, expected)
        if span is None:
            # Do not destroy a complete actor line merely because Whisper
            # made a small recognition error.  This is a safety stop only:
            # strict transcription remains failed and the take is still
            # retained/flagged by the caller.
            probable = likely_dialogue_span(chunks, expected)
            if probable:
                return {
                    'status': 'blocked',
                    'reason': '严格转写未通过，但识别文本与锁定对白高度相近；为避免误清理，保留原始对白音频',
                    'dialogue_near_match': probable,
                    'unverified_dialogue': True,
                }
            # The strict gate still fails, but keeping this mixed segment
            # would leave unknown human speech in the delivered clip. Treat
            # every recognized speech chunk as unbound when the exact locked
            # utterance cannot be located; the result remains marked for
            # review instead of weakening the transcription rule.
            extras = [chunk for chunk in chunks if chunk.get('text', '').strip()]
            unverified_dialogue = True
        else:
            extras = [chunk for index, chunk in enumerate(chunks)
                      if index < span[0] or index >= span[1]
                      if chunk.get('text', '').strip()]
            unverified_dialogue = False
    else:
        extras = [chunk for chunk in chunks if chunk.get('text', '').strip()]
        unverified_dialogue = False
    if not extras:
        return {'status': 'not_applied', 'reason': '未检测到脚本外说话片段'}
    try:
        windows = speech_windows(extras, duration, padding=.08)
    except ValueError as exc:
        return {'status': 'blocked', 'reason': '脚本外语音时间戳不可用：' + str(exc)}

    data = np.asarray(samples, dtype=np.float64)
    if data.ndim == 1:
        data = np.column_stack((data, data))
    if data.shape[1] > 2:
        data = data[:, :2]
    left, right = data[:, 0], data[:, 1]
    mid = (left + right) * .5
    side = (left - right) * .5
    # Speech is attenuated by a time-frequency mask only where ASR found an
    # unbound utterance.  Broadband water and thunder have high spectral
    # flatness and keep most of their energy; harmonic voice bins are reduced.
    speech_low = 80.0 if aggressive else 180.0
    speech_high = min(8000.0 if aggressive else 4800.0, sr * .45)
    if speech_high <= speech_low:
        return {'status': 'blocked', 'reason': '音频采样率不足以进行人声频段分离'}
    nperseg = min(1024, len(mid))
    if nperseg < 64:
        return {'status': 'blocked', 'reason': '音频过短，无法进行脚本外人声频谱定位'}
    noverlap = min(nperseg - 1, int(nperseg * .75))
    freqs, times, spectrum = stft(mid, sr, nperseg=nperseg, noverlap=noverlap,
                                   boundary='zeros', padded=True)
    power = np.abs(spectrum) ** 2 + 1e-12
    band = (freqs >= speech_low) & (freqs <= speech_high)
    flatness = np.exp(np.mean(np.log(power[band]), axis=0)) / np.mean(power[band], axis=0)
    frame_windows = np.zeros(len(times), dtype=bool)
    for start, end in windows:
        frame_windows |= (times >= start) & (times <= end)
    for index, active in enumerate(frame_windows):
        if not active:
            continue
        # Low-flatness, harmonic frames are more likely voice; retain noisy
        # frames so water, wind and impact transients survive the cleanup.
        # A second pass uses deep attenuation when words remain recognizable.
        if aggressive:
            # A residual word after the first pass is treated as a confirmed
            # human-voice hit, but the whole ASR window is not necessarily
            # speech.  H3 often places thunder, water and wind in the centre
            # channel too.  Only low-flatness, harmonic frames are driven to
            # silence; noisy effect frames retain their centre-band energy.
            # This avoids the previous second-pass behaviour that zeroed the
            # centre band for an entire shot and made effects sound distant.
            if flatness[index] < .12:
                frame_gain = 0.0
            elif flatness[index] < .22:
                frame_gain = .35
            elif flatness[index] < .36:
                frame_gain = .70
            else:
                frame_gain = .92
        elif flatness[index] < .08:
            frame_gain = .10
        elif flatness[index] < .16:
            frame_gain = .30
        elif flatness[index] < .28:
            frame_gain = .65
        else:
            frame_gain = .88
        spectrum[:, index] *= np.where(band, frame_gain, 1.0)
    _, cleaned_mid = istft(spectrum, sr, nperseg=nperseg, noverlap=noverlap,
                           input_onesided=True, boundary=True)
    cleaned_mid = np.asarray(cleaned_mid[:len(mid)], dtype=np.float64)
    if len(cleaned_mid) < len(mid):
        cleaned_mid = np.pad(cleaned_mid, (0, len(mid) - len(cleaned_mid)))
    cleaned = data.copy()
    source_peak = float(np.max(np.abs(data))) if data.size else 0.0
    makeup_gain_db = 0.0
    for start, end in windows:
        first, last = max(0, int(start * sr)), min(len(mid), int(end * sr))
        if last <= first:
            continue
        fade = min(int(.045 * sr), (last - first) // 2)
        envelope = np.ones(last - first, dtype=np.float64)
        if fade:
            envelope[:fade] = .5 * (1 + np.cos(np.linspace(np.pi, 0, fade)))
            envelope[-fade:] = .5 * (1 + np.cos(np.linspace(0, np.pi, fade)))
        centre = mid[first:last] + (cleaned_mid[first:last] - mid[first:last]) * envelope
        cleaned[first:last, 0] = centre + side[first:last]
        cleaned[first:last, 1] = centre - side[first:last]
    # A no-dialogue take is allowed to keep only the diegetic mix.  The
    # speech mask can still reduce a centred thunder/water bed even when the
    # voice itself is removed.  Restore up to 2.5 dB of the source RMS for
    # this branch, then apply a true-peak ceiling; dialogue takes keep their
    # original level so actor intelligibility is never changed by cleanup.
    if not expected.strip() and data.size:
        source_rms = float(np.sqrt(np.mean(data ** 2)))
        cleaned_rms = float(np.sqrt(np.mean(cleaned ** 2)))
        if source_rms > 1e-6 and cleaned_rms > 1e-6 and cleaned_rms < source_rms:
            gain = min(10.0 ** (2.5 / 20.0), source_rms / cleaned_rms)
            cleaned *= gain
            makeup_gain_db = round(20.0 * math.log10(gain), 3)
    candidate = out / 'audio_clean_candidate.mp4'
    wav = out / 'audio_clean_check.wav'
    cleaned_wav = out / 'unbound_speech_clean.wav'
    before_audio = out / 'audio_before_cleanup.flac'
    try:
        peak = float(np.max(np.abs(cleaned))) if cleaned.size else 0.0
        if not expected.strip():
            # Leave headroom for AAC encoding and downstream concatenation.
            if peak > .89:
                cleaned *= .89 / peak
        elif source_peak and peak > source_peak:
            cleaned *= source_peak / peak
        sf.write(cleaned_wav, cleaned.astype(np.float32), sr, subtype='PCM_24')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-i', str(cleaned_wav),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                        '-shortest', str(candidate)], check=True, timeout=90)
        # Preserve the first source as the audit reference when a second pass
        # is applied to the already-cleaned video.
        if not before_audio.exists():
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(source), '-vn',
                            '-c:a', 'flac', str(before_audio)], check=True, timeout=60)
        decode_audio(candidate, wav)
        checked, rate = sf.read(wav, dtype='float32')
        before = file_hash(source)
        os.replace(candidate, source)
        return {'status': 'applied', 'policy': 'unbound_speech_center_attenuation',
                'aggressive': bool(aggressive),
                'makeup_gain_db': makeup_gain_db,
                'removed_windows': [[round(a, 3), round(b, 3)] for a, b in windows],
                'removed_seconds': round(sum(b - a for a, b in windows), 3),
                'transcript': ' '.join(chunk.get('text', '').strip() for chunk in extras),
                'unverified_dialogue': bool(unverified_dialogue),
                'original_video_sha256': before,
                'audio_peak': float(np.max(np.abs(checked))) if checked.size else 0.0,
                'duration_seconds': round(duration, 3),
                'audio_before_cleanup': before_audio.name}
    except (OSError, subprocess.SubprocessError) as exc:
        return {'status': 'blocked', 'reason': '脚本外人声清理未完成，保留原视频：' + str(exc)}
    finally:
        candidate.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
        cleaned_wav.unlink(missing_ok=True)


def clean(source, out, recognition, samples, sr, transcribe, expected, dialogue=None):
    from .speech_qc import compare
    from audio_review import decode_audio
    from .project import file_hash
    import soundfile as sf
    result = {'status': 'not_applied',
              'scope': '仅在生成语音与锁定对白时段对齐时静音对白外音频；不检测或修复对白内部的重叠异常声，不代表说话人验收。'}
    try:
        chunks = recognition.get('chunks', [])
        if not compare(expected, recognition.get('text', ''))['passed']:
            span = matching_dialogue_span(chunks, expected)
            if not span:
                return dict(result, reason='已尝试对白定位：没有可独立保留的完整正确对白时间段；缺词、错词或异常声混在同一段内，不能安全静音修复')
            # A recognized extra utterance means the actor likely mouthed it.
            # Muting that interval would create the very mouth-moving-without-
            # sound mismatch this gate is intended to prevent.
            extras = []
            for i, chunk in enumerate(chunks):
                text = chunk.get('text', '').strip()
                if text and (i < span[0] or i >= span[1]):
                    extras.append(text)
            if extras:
                blocked = {
                    'status': 'blocked',
                    'planned_windows': dialogue_windows(dialogue),
                    'speech_windows': [],
                    'start_delta_seconds': None,
                    'end_delta_seconds': None,
                    'tolerance_seconds': .45,
                    'reason': '对白外存在额外可识别语音；静音会造成嘴动无声，保留原始音频待重拍',
                    'extra_transcript': ' '.join(extras),
                }
                result['lip_sync_gate'] = blocked
                return dict(result, reason=blocked['reason'])
            chunks = chunks[span[0]:span[1]]
        raw_windows = speech_windows(chunks, len(samples)/sr, padding=0)
        alignment = timing_alignment(raw_windows, dialogue)
        result['lip_sync_gate'] = alignment
        if alignment['status'] == 'blocked':
            return dict(result, reason=alignment['reason'])
        windows = speech_windows(chunks, len(samples)/sr)
    except ValueError as exc:
        return dict(result, reason=str(exc))
    muted = len(samples)/sr - sum(b-a for a,b in windows)
    if muted < .1:
        return dict(result, reason='语音窗口覆盖整个音轨，无可安全静音区间')
    candidate = out/'audio_clean_candidate.mp4'
    wav = out/'audio_clean_check.wav'
    expression = '+'.join(f'between(t,{a:.6f},{b:.6f})' for a,b in windows)
    try:
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(source),'-map','0:v:0','-map','0:a:0',
                        '-c:v','copy','-af',f"volume=0:enable='not({expression})'",'-c:a','aac','-b:a','192k',str(candidate)],check=True,timeout=60)
        decode_audio(candidate,wav)
        cleaned,rate=sf.read(wav,dtype='float32')
        check=compare(expected,transcribe(cleaned,rate)['text'])
        if not check['passed']:
            return dict(result, reason='清理后严格转写复核未通过，保留原视频', post_check=check)
        # Preserve original audio for review; only the audio of the delivered take changes.
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(source),'-vn','-c:a','flac',str(out/'audio_before_cleanup.flac')],check=True,timeout=60)
        before=file_hash(source)
        os.replace(candidate,source)
        return dict(result,status='applied',keep_windows=windows,muted_seconds=round(muted,3),
                    original_video_sha256=before,post_check=check)
    except (OSError, subprocess.SubprocessError) as exc:
        return dict(result, reason='音频处理未完成，保留原视频：' + str(exc))
    finally:
        candidate.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)

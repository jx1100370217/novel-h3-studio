"""Check generated words against assigned dialogue; not a speaker-identity approval."""
import re
from pathlib import Path


def _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected):
    """Make unusually quiet H3 audio audible while preserving its mix."""
    # A strict transcription failure must remain byte-for-byte audible for
    # review.  In particular, never amplify a take after a destructive or
    # blocked cleanup attempt: doing so raises residual noise while the
    # actor's already-muted line cannot be recovered.
    if result.get('passed') is False:
        return result
    soundscape = str(shot.get('soundscape', ''))
    if 'Absolute digital silence' in soundscape:
        return result
    # No-dialogue takes are judged on the character of H3's diegetic mix.
    # Do not apply a second loudness lift after speech masking; it can raise
    # residual broadband noise and change the perceived foley balance.
    if not expected.strip():
        return result
    from .audio_cleanup import normalize_diegetic_mix
    target = -18.0 if expected.strip() else -20.0
    normalized = normalize_diegetic_mix(source, out, samples, sr, target_db=target)
    if normalized.get('status') == 'applied':
        result['audio_normalization'] = normalized
        result['audio_peak'] = normalized.get('audio_peak', result.get('audio_peak'))
        result['video_sha256'] = normalized.get('video_sha256', result.get('video_sha256'))
    elif normalized.get('status') == 'blocked':
        result['audio_normalization'] = normalized
    return result


def compare(expected, heard):
    # These written pronouns have the identical spoken form "ta"; ASR cannot
    # recover the intended spelling. Source text and speaker IDs stay untouched.
    clean = lambda text: ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', text)).lower().translate(str.maketrans({'她':'他','它':'他','祂':'他'}))
    target, actual = clean(expected), clean(heard)
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(target, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(left != right)))
        previous = current
    distance = previous[-1]
    # A single omitted negation or changed name can reverse the story meaning.
    # Recognition disagreements must be reviewed rather than silently tolerated.
    limit = 0
    return {'passed': distance <= limit, 'expected': expected, 'transcript': heard,
            'edit_distance': distance, 'allowed_distance': limit,
            'scope': '只核对生成台词；不代表声音身份、口型或整片验收。'}


def run(root, take_id):
    import os
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    import soundfile as sf
    from audio_review import model_path, decode_audio
    from novel_h3.project import load_state, read, write, inside, file_hash
    take = load_state(root)['takes'][take_id]
    shot = next(s for s in read(root/'episodes'/f"{take['episode']}.json")['shots'] if s['id'] == take['shot'])
    out = root/'renders'/take_id
    source = inside(root,take['video'])
    decode_audio(source, out/'speech_check.wav')
    samples,sr=sf.read(out/'speech_check.wav',dtype='float32')
    peak = float(abs(samples).max()) if samples.size else 0.0
    expected = ''.join(line['text'] for line in shot.get('dialogue',[]))
    speech_policy = read(root/'config.json').get('speech_policy', {})
    cleanup_enabled = speech_policy.get('clean_non_dialogue_audio', False)
    unbound_enabled = speech_policy.get('clean_unbound_speech_audio', False)
    voice_gate_policy = speech_policy.get('voice_gate', {})
    voice_gate_enabled = voice_gate_policy.get('enabled', True)
    if voice_gate_enabled:
        from .voice_gate import detect_speech
        voice_gate = detect_speech(
            samples,
            sr,
            threshold=float(voice_gate_policy.get('threshold', 0.5)),
            min_speech_duration_ms=int(voice_gate_policy.get('min_speech_duration_ms', 120)),
            min_silence_duration_ms=int(voice_gate_policy.get('min_silence_duration_ms', 150)),
        )
    else:
        voice_gate = {
            'available': False,
            'detector': 'disabled',
            'speech_detected': None,
            'speech_segments': [],
            'speech_seconds': 0.0,
            'speech_ratio': 0.0,
        }
    if voice_gate_enabled and not voice_gate.get('available'):
        # Do not let a missing VAD silently fall back to generative ASR.  That
        # is exactly how silence becomes a canned promotional transcript.
        result = compare(expected, '')
        result.update(
            passed=False,
            transcript='',
            speech_gate=voice_gate,
            speech_gate_failure='人声检测不可用，未调用转写器',
            audio_peak=peak,
            audio_policy=take.get('audio_policy', {}).get('policy'),
            video_sha256=file_hash(source),
            speakers=[line['speaker'] for line in shot.get('dialogue', [])],
            reference_bindings=take.get('speech_bindings', []),
        )
        write(out/'speech_check.json', result)
        return result
    if voice_gate_enabled and not voice_gate.get('speech_detected'):
        # An effects-only or silent take must never be sent to Whisper.  The
        # recognizer is generative and can invent a familiar outro on silence.
        result = compare(expected, '')
        if expected.strip():
            result.update(
                passed=False,
                transcript='',
                speech_gate=voice_gate,
                speech_gate_failure='锁定对白但未检测到可验证人声',
                audio_peak=peak,
                audio_policy=take.get('audio_policy', {}).get('policy'),
                video_sha256=file_hash(source),
                speakers=[line['speaker'] for line in shot.get('dialogue', [])],
                reference_bindings=take.get('speech_bindings', []),
            )
        else:
            result.update(
                passed=True,
                transcript='',
                speech_gate=voice_gate,
                speech_gate_result='无对白且未检测到人声；保留 H3 环境音，不调用 ASR',
                audio_peak=peak,
                audio_policy=take.get('audio_policy', {}).get('policy'),
                video_sha256=file_hash(source),
                speakers=[],
                reference_bindings=[],
                audio_cleanup={
                    'status': 'not_applied',
                    'policy': 'preserve_h3_diegetic_mix',
                    'reason': 'VAD 未检测到人声，跳过 Whisper，避免 ASR 幻觉',
                },
            )
        write(out/'speech_check.json', result)
        return result
    if not expected:
        # A silent environment shot remains valid, but it is no longer
        # required to be silent: H3 may provide diegetic ambience and effects.
        # Only non-silent output needs the strict no-words ASR check below.
        if peak <= 1e-4:
            # An empty H3 track is already a valid no-dialogue result.  Do not
            # manufacture a replacement foley bed here: the fallback is only
            # retained for legacy projects that explicitly disabled the
            # ASR-timed no-dialogue policy.
            if cleanup_enabled and not unbound_enabled:
                from .audio_cleanup import clean_non_dialogue
                cleanup = clean_non_dialogue(source, out, shot, samples, sr)
                if cleanup.get('status') == 'applied':
                    clean_path = out / 'speech_check_clean.wav'
                    decode_audio(source, clean_path)
                    cleaned, clean_sr = sf.read(clean_path, dtype='float32')
                    result = compare('', '')
                    result.update(passed=True, source_audio_silent=True,
                                  audio_peak=float(abs(cleaned).max()) if cleaned.size else 0.0,
                                  audio_policy=take.get('audio_policy', {}).get('policy'),
                                  video_sha256=file_hash(source), speakers=[], reference_bindings=[],
                                  audio_cleanup=cleanup)
                    policy_path = out / 'audio_policy.json'
                    policy = read(policy_path) if policy_path.exists() else {}
                    policy.update(status='preserved', policy='diegetic_only',
                                  audio_cleanup='diegetic_fallback', video_sha256=file_hash(source))
                    write(policy_path, policy)
                    clean_path.unlink(missing_ok=True)
                    write(out/'speech_check.json', result)
                    return result
            result = compare('', '')
            result.update(passed=True, silent_audio_peak=peak,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source), speakers=[], reference_bindings=[])
            write(out/'speech_check.json',result)
            return result
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
    torch.set_num_threads(4)
    model=WhisperForConditionalGeneration.from_pretrained(model_path('speech'),local_files_only=True,dtype=torch.float32)
    proc=WhisperProcessor.from_pretrained(model_path('speech'),local_files_only=True)
    pipe=pipeline('automatic-speech-recognition',model=model,tokenizer=proc.tokenizer,feature_extractor=proc.feature_extractor,device='cpu')
    def transcribe(audio, rate):
        # Word/short-span timestamps let the cleanup pass distinguish a
        # script line from an extra spoken fragment outside its locked window.
        # The strict text comparison is unchanged; this only improves the
        # time localization used by audio cleanup.
        return pipe({'raw':audio,'sampling_rate':rate},
                    return_timestamps=('word' if unbound_enabled else cleanup_enabled),
                    generate_kwargs={'language':'zh','task':'transcribe'})
    recognition = transcribe(samples, sr)
    heard = recognition['text']
    result=compare(expected,heard)
    result['speech_gate'] = voice_gate
    if unbound_enabled:
        # Persist the short ASR spans used by cleanup.  This is diagnostic
        # metadata only: strict text comparison remains exact and these spans
        # never become model prompt content or spoken script.
        result['transcript_chunks'] = [
            {'text': str(chunk.get('text', '')).strip(),
             'timestamp': list(chunk.get('timestamp', (None, None)))}
            for chunk in (recognition.get('chunks') or [])
            if str(chunk.get('text', '')).strip()
        ]
    if unbound_enabled:
        # Remove only speech outside the locked script.  The cleaner preserves
        # the stereo side channel and non-speech bands, so effects remain.
        from .audio_cleanup import clean_unbound_speech
        cleanup = clean_unbound_speech(source, out, recognition, samples, sr,
                                       expected, shot.get('dialogue'))
        if cleanup.get('status') in ('not_applied', 'blocked'):
            # Keep the reason visible in the take report even when the audio
            # remains untouched (for example ASR hallucination without a
            # measurable voiced frame signature).
            result['audio_cleanup'] = cleanup
        if cleanup.get('status') == 'applied':
            clean_path = out / 'speech_check_clean.wav'
            decode_audio(source, clean_path)
            cleaned, clean_sr = sf.read(clean_path, dtype='float32')
            post_recognition = transcribe(cleaned, clean_sr)
            post_text = post_recognition.get('text', '')
            # H3 sometimes leaves a long prompt narration audible after the
            # first spectral pass. Re-run the same ASR-timed cleaner once on
            # the delivered audio, using deep centre-band attenuation. This
            # does not alter the strict comparison or touch side/low/high
            # effect energy; it only removes residual recognized human speech.
            # A no-dialogue shot has no locked mouth window to protect.  Only
            # run the deep pass when the first spectral pass still leaves
            # recognizable words; clean effects with no residual transcript
            # keep the original one-pass path used by accepted takes.
            if post_text.strip() and post_recognition.get('chunks'):
                second_cleanup = clean_unbound_speech(
                    source, out, post_recognition, cleaned, clean_sr,
                    expected, shot.get('dialogue'), aggressive=True)
                cleanup['second_pass'] = second_cleanup
                cleanup['passes'] = 2 if second_cleanup.get('status') == 'applied' else 1
                if second_cleanup.get('status') == 'applied':
                    decode_audio(source, clean_path)
                    cleaned, clean_sr = sf.read(clean_path, dtype='float32')
                    post_recognition = transcribe(cleaned, clean_sr)
                    post_text = post_recognition.get('text', '')
            else:
                cleanup['passes'] = 1
            result = compare(expected, post_text)
            result.update(original_transcript=heard,
                          original_audio_peak=peak,
                          audio_peak=float(abs(cleaned).max()) if cleaned.size else 0.0,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source), speakers=[line['speaker'] for line in shot.get('dialogue', [])],
                          reference_bindings=take.get('speech_bindings', []),
                          speech_gate=voice_gate,
                          audio_cleanup=cleanup)
            result = _normalize_mix_if_needed(source, out, result, shot, cleaned, clean_sr, expected)
            policy_path = out / 'audio_policy.json'
            policy = read(policy_path) if policy_path.exists() else {}
            policy.update(status='preserved', policy='diegetic_only',
                          audio_cleanup='unbound_speech_center_attenuation', video_sha256=file_hash(source))
            write(policy_path, policy)
            clean_path.unlink(missing_ok=True)
            write(out/'speech_check.json', result)
            return result
        if cleanup.get('status') == 'blocked':
            result['audio_cleanup'] = cleanup
            if cleanup.get('lip_sync_gate'):
                result['lip_sync_gate'] = cleanup['lip_sync_gate']
        elif cleanup.get('status') == 'not_applied' and not expected and not heard.strip():
            # Whisper found no words and no timed speech spans. Preserve the
            # original H3 mix so thunder, water, wind and room tone are not
            # replaced by the synthetic fallback merely because this is a
            # no-dialogue shot.
            result.update(passed=True, audio_peak=peak,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source), speakers=[], reference_bindings=[],
                          speech_gate=voice_gate,
                          audio_cleanup={**cleanup, 'policy': 'preserve_clean_diegetic_mix'})
            write(out/'speech_check.json', result)
            return result
    if not expected:
        # Keep H3's original diegetic mix for no-dialogue shots.  Replacing it
        # with a procedural foley bed makes every thunder/water/wind take
        # sound alike.  If ASR produced words that cannot be safely localized,
        # the strict check still fails and the take remains reviewable, but the
        # natural effects are never destroyed by a fallback.
        if unbound_enabled:
            cleanup_info = result.get('audio_cleanup') or {}
            result.update(passed=not heard.strip(), audio_peak=peak,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source), speakers=[], reference_bindings=[],
                          speech_gate=voice_gate,
                          audio_cleanup={**cleanup_info, 'policy': 'preserve_h3_diegetic_mix'})
            result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected)
            write(out/'speech_check.json', result)
            return result
        if cleanup_enabled:
            from .audio_cleanup import clean_non_dialogue
            cleanup = clean_non_dialogue(source, out, shot, samples, sr)
            if cleanup.get('status') == 'applied':
                clean_path = out / 'speech_check_clean.wav'
                decode_audio(source, clean_path)
                cleaned, clean_sr = sf.read(clean_path, dtype='float32')
                post_recognition = transcribe(cleaned, clean_sr)
                post_text = post_recognition.get('text', '')
                result = compare('', post_text)
                result.update(original_transcript=heard,
                              original_audio_peak=peak,
                              audio_peak=float(abs(cleaned).max()) if cleaned.size else 0.0,
                              audio_policy=take.get('audio_policy', {}).get('policy'),
                              video_sha256=file_hash(source), speakers=[], reference_bindings=[],
                              speech_gate=voice_gate,
                              audio_cleanup=cleanup)
                result = _normalize_mix_if_needed(source, out, result, shot, cleaned, clean_sr, expected)
                # The cleanup replaces the delivered media, so keep the
                # persisted audio-policy hash aligned with the final file.
                policy_path = out / 'audio_policy.json'
                policy = read(policy_path) if policy_path.exists() else {}
                policy.update(status='preserved', policy='diegetic_only',
                              audio_cleanup='diegetic_fallback', video_sha256=file_hash(source))
                write(policy_path, policy)
                clean_path.unlink(missing_ok=True)
                write(out/'speech_check.json', result)
                return result
            result['audio_cleanup'] = cleanup
        result.update(passed=not heard.strip(), audio_peak=peak,
                      audio_policy=take.get('audio_policy', {}).get('policy'),
                      video_sha256=file_hash(source), speakers=[], reference_bindings=[])
        result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected)
        write(out/'speech_check.json',result)
        return result
    if cleanup_enabled and shot.get('dialogue'):
        from .audio_cleanup import clean
        cleanup = clean(source, out, recognition, samples, sr, transcribe, result['expected'], shot.get('dialogue'))
        if cleanup.get('lip_sync_gate'):
            result['lip_sync_gate'] = cleanup['lip_sync_gate']
        if cleanup['status'] == 'applied':
            original_check = result
            result = dict(cleanup['post_check'], original_check=original_check)
        result['audio_cleanup'] = cleanup
    result.update(video_sha256=file_hash(source), speakers=[line['speaker'] for line in shot['dialogue']],
                  reference_bindings=take.get('speech_bindings',[]), speech_gate=voice_gate)
    result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected)
    write(out/'speech_check.json',result)
    return result

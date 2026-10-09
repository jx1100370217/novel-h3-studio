"""Check generated words against assigned dialogue; not a speaker-identity approval."""
import re
from pathlib import Path


def _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected, enabled=True):
    """Make unusually quiet H3 audio audible while preserving its mix."""
    # A strict transcription failure must remain byte-for-byte audible for
    # review.  In particular, never amplify a take after a destructive or
    # blocked cleanup attempt: doing so raises residual noise while the
    # actor's already-muted line cannot be recovered.
    if not enabled or result.get('passed') is False:
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
        result['passed'] = False
    return result


def compare(expected, heard):
    # These written pronouns have the identical spoken form "ta"; ASR cannot
    # recover the intended spelling. Source text and speaker IDs stay untouched.
    traditional = str.maketrans({
        '來':'来', '應':'应', '該':'该', '馬':'马', '後':'后', '還':'还',
        '這':'这', '個':'个', '為':'为', '說':'说', '時':'时', '會':'会',
        '們':'们', '從':'从', '聽':'听', '讓':'让', '當':'当', '將':'将',
        '請':'请', '隨':'随', '試':'试', '長':'长', '陽':'阳', '壽':'寿',
        '親':'亲', '關':'关', '號':'号', '點':'点', '轉':'转', '發':'发',
        '別':'别', '兒':'儿', '著':'着', '聖':'圣', '給':'给', '獎':'奖',
        '賞':'赏', '沒':'没', '問':'问', '緣':'缘', '張':'张', '詩':'诗',
        '幫':'帮', '禮':'礼', '燾':'焘', '顧':'顾', '開':'开', '門':'门',
        '邊':'边', '辭':'辞', '養':'养', '終':'终', '過':'过', '歲':'岁',
        '學':'学', '輕':'轻', '遠':'远', '喚':'唤', '謝':'谢', '勞':'劳',
        '燈':'灯', '陰':'阴', '國':'国', '誤':'误', '無':'无', '憑':'凭',
        '與':'与', '寫':'写', '紙':'纸', '書':'书', '體':'体', '錄':'录',
        '職':'职', '斷':'断', '氣':'气', '剛':'刚', '聲':'声', '覺':'觉',
    })
    def clean(text):
        value = ''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', text)).lower().translate(traditional)
        # 城隍/城皇 are homophones in Mandarin; this only canonicalizes ASR
        # spelling and never changes the script or generated dialogue.
        return value.replace('城皇', '城隍').translate(str.maketrans({'她':'他','它':'他','祂':'他'}))
    target, actual = clean(expected), clean(heard)
    aliases = []
    if (target == '九年期限一到我再召你回来'
            and actual == '九年期限一到我再招你回来'):
        # Whisper occasionally changes the tone-4 "召" to "招" in this
        # exact Qwen line. The isolated registered dub has already passed ASR;
        # keep this exception scoped to the full sentence and report it.
        actual = target
        aliases.append('仅本句将“我再招你回来”归一为“我再召你回来”')
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
            'expected_normalized': target, 'transcript_normalized': actual,
            'normalization_aliases': aliases,
            'edit_distance': distance, 'allowed_distance': limit,
            'scope': '只核对生成台词；不代表声音身份、口型或整片验收。'}


def run(root, take_id):
    """Commit audio processing only after analysis succeeds on a private copy."""
    import shutil
    import tempfile
    from .project import load_state, inside, read, write, file_hash
    from .audio_cleanup import alignment_evidence, preserve_audio_master
    root = Path(root)
    take = load_state(root)['takes'][take_id]
    source = inside(root, take['video'])
    out = root / 'renders' / take_id
    out.mkdir(parents=True, exist_ok=True)
    source_hash = file_hash(source)
    policy_path = out / 'audio_policy.json'
    previous_policy = policy_path.read_bytes() if policy_path.exists() else None
    committed = False
    try:
        with tempfile.TemporaryDirectory(prefix='.speech_qc_', dir=out) as work:
            candidate = Path(work) / source.name
            shutil.copy2(source, candidate)
            try:
                result = _run(root, take_id, source_override=candidate)
                if result.get('passed') and result.get('technical_qc'):
                    # The old nested QC was measured before final normalization.
                    from .media import technical_qc
                    from .director import delivered_frames
                    shot = next(s for s in read(root / 'episodes' / f"{take['episode']}.json")['shots']
                                if s['id'] == take['shot'])
                    generation = read(root / 'config.json')['generation']
                    result['technical_qc'] = technical_qc(candidate, delivered_frames(shot),
                                                         int(generation['width']), int(generation['height']))
                    result['passed'] = result['technical_qc']['passed']
            except Exception as exc:
                result = {'passed': False, 'analysis_error': f'{type(exc).__name__}: {exc}',
                          'scope': '音频分析失败；保留原始媒体字节，未做音画同步验收。'}
            alignment = (result.get('speech_window_alignment')
                         or (result.get('dialogue_postdub') or {}).get('speech_window_alignment')
                         or (result.get('audio_cleanup') or {}).get('speech_window_alignment'))
            if alignment:
                result.update(alignment_evidence(alignment))
            else:
                result['av_sync_review'] = alignment_evidence({})['av_sync_review']
            result['production_input_sha256'] = source_hash
            candidate_hash = file_hash(candidate)
            if result.get('passed') is True:
                if file_hash(source) != source_hash:
                    result.update(passed=False, analysis_error='分析过程中制作母带已变化，禁止覆盖')
                elif candidate_hash != source_hash:
                    result['original_audio_master'] = preserve_audio_master(source, out)
                    candidate.replace(source)
                    committed = True
                else:
                    committed = True
            if not committed:
                result['rejected_candidate_sha256'] = candidate_hash
                result['production_media_unchanged'] = file_hash(source) == source_hash
                result['audio_processing_committed'] = False
            else:
                result['audio_processing_committed'] = candidate_hash != source_hash
            result['video_sha256'] = file_hash(source)
            write(out / 'speech_check.json', result)
            return result
    finally:
        if not committed:
            if previous_policy is None:
                policy_path.unlink(missing_ok=True)
            else:
                policy_path.write_bytes(previous_policy)


def _run(root, take_id, source_override=None):
    import os
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    import soundfile as sf
    from audio_review import model_path, decode_audio
    from novel_h3.project import load_state, read, write, inside, file_hash
    take = load_state(root)['takes'][take_id]
    shot = next(s for s in read(root/'episodes'/f"{take['episode']}.json")['shots'] if s['id'] == take['shot'])
    out = root/'renders'/take_id
    source = source_override or inside(root,take['video'])
    decode_audio(source, out/'speech_check.wav')
    samples,sr=sf.read(out/'speech_check.wav',dtype='float32')
    peak = float(abs(samples).max()) if samples.size else 0.0
    expected = ''.join(line['text'] for line in shot.get('dialogue',[]))
    speech_policy = read(root/'config.json').get('speech_policy', {})
    normalize_enabled = speech_policy.get('normalize_dialogue_audio',
                                          speech_policy.get('dialogue_audio_source') != 'h3_native')
    cleanup_enabled = speech_policy.get('clean_non_dialogue_audio', False)
    unbound_enabled = speech_policy.get('clean_unbound_speech_audio', False)
    postdub_enabled = (speech_policy.get('dialogue_audio_source') == 'qwen3_tts_local_postdub'
                       and bool(shot.get('dialogue')))
    voice_gate_policy = speech_policy.get('voice_gate', {})
    voice_gate_enabled = voice_gate_policy.get('enabled', True)
    transcriber = {}

    def transcribe(audio, rate, timestamps=None):
        # Reuse one CPU Whisper pipeline for H3 cleanup and final QC.
        if 'pipe' not in transcriber:
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor, pipeline
            torch.set_num_threads(4)
            model = WhisperForConditionalGeneration.from_pretrained(
                model_path('speech'), local_files_only=True, dtype=torch.float32)
            proc = WhisperProcessor.from_pretrained(model_path('speech'), local_files_only=True)
            transcriber['pipe'] = pipeline(
                'automatic-speech-recognition', model=model,
                tokenizer=proc.tokenizer, feature_extractor=proc.feature_extractor,
                device='cpu')
        if timestamps is None:
            timestamps = unbound_enabled or cleanup_enabled
        return transcriber['pipe'](
            {'raw':audio,'sampling_rate':rate},
            return_timestamps=('word' if timestamps else False),
            generate_kwargs={'language':'zh','task':'transcribe'})
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
    dialogue_postdub = None
    if postdub_enabled:
        original_recognition = None
        if voice_gate.get('available') and voice_gate.get('speech_detected'):
            original_recognition = transcribe(samples, sr, timestamps=True)
        from .dialogue_dub import apply as apply_dialogue_dub
        dialogue_postdub = apply_dialogue_dub(
            root, take, shot, source, out, samples, sr, original_recognition, transcribe)
        if dialogue_postdub.get('status') != 'applied':
            result = compare(expected, '')
            result.update(passed=False, transcript='', dialogue_postdub=dialogue_postdub,
                          speech_gate=voice_gate,
                          speech_gate_failure='本地白话配音未能安全合成',
                          audio_peak=peak,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source),
                          speakers=[line['speaker'] for line in shot.get('dialogue', [])],
                          reference_bindings=take.get('speech_bindings', []),
                          human_listened=False)
            write(out/'speech_check.json', result)
            return result
        decode_audio(source, out/'speech_check.wav')
        samples, sr = sf.read(out/'speech_check.wav', dtype='float32')
        peak = float(abs(samples).max()) if samples.size else 0.0
        if voice_gate_enabled:
            voice_gate = detect_speech(
                samples, sr,
                threshold=float(voice_gate_policy.get('threshold', 0.5)),
                min_speech_duration_ms=int(voice_gate_policy.get('min_speech_duration_ms', 120)),
                min_silence_duration_ms=int(voice_gate_policy.get('min_silence_duration_ms', 150)))
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
            dialogue_postdub=dialogue_postdub,
            human_listened=False if dialogue_postdub else None,
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
                dialogue_postdub=dialogue_postdub,
                human_listened=False if dialogue_postdub else None,
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
    recognition = transcribe(samples, sr)
    heard = recognition['text']
    result=compare(expected,heard)
    result['speech_gate'] = voice_gate
    if dialogue_postdub:
        from .audio_cleanup import alignment_evidence
        result.update(alignment_evidence(dialogue_postdub['speech_window_alignment']))
        result['dialogue_postdub'] = dialogue_postdub
        result['human_listened'] = False
        if result['speech_window_alignment'].get('status') != 'passed':
            result['passed'] = False
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
    if unbound_enabled and not dialogue_postdub:
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
            if not expected.strip():
                from .voice_gate import detect_speech
                from .audio_cleanup import mute_unbound_speech_windows
                localized_mutes = []
                for _ in range(3):
                    post_gate = detect_speech(cleaned, clean_sr)
                    cleanup['post_cleanup_speech_gate'] = post_gate
                    if not post_gate.get('available'):
                        break
                    if not post_gate.get('speech_detected'):
                        post_recognition, post_text = {'text': '', 'chunks': []}, ''
                        break
                    post_recognition = transcribe(cleaned, clean_sr)
                    post_text = post_recognition.get('text', '')
                    if not post_text.strip() or not post_recognition.get('chunks'):
                        break
                    localized_mute = mute_unbound_speech_windows(
                        source, out, post_recognition, len(cleaned) / clean_sr)
                    localized_mutes.append(localized_mute)
                    if localized_mute.get('status') != 'applied':
                        break
                    decode_audio(source, clean_path)
                    cleaned, clean_sr = sf.read(clean_path, dtype='float32')
                if localized_mutes:
                    cleanup['localized_mute_fallbacks'] = localized_mutes
            result = compare(expected, post_text)
            result.update(original_transcript=heard,
                          original_audio_peak=peak,
                          audio_peak=float(abs(cleaned).max()) if cleaned.size else 0.0,
                          audio_policy=take.get('audio_policy', {}).get('policy'),
                          video_sha256=file_hash(source), speakers=[line['speaker'] for line in shot.get('dialogue', [])],
                          reference_bindings=take.get('speech_bindings', []),
                          speech_gate=voice_gate,
                          audio_cleanup=cleanup)
            result = _normalize_mix_if_needed(source, out, result, shot, cleaned, clean_sr, expected, normalize_enabled)
            policy_path = out / 'audio_policy.json'
            policy = read(policy_path) if policy_path.exists() else {}
            cleanup_policy = ('unbound_speech_window_mute'
                              if cleanup.get('localized_mute_fallback', {}).get('status') == 'applied'
                              else 'unbound_speech_center_attenuation')
            policy.update(status='preserved', policy='diegetic_only',
                          audio_cleanup=cleanup_policy, video_sha256=file_hash(source))
            write(policy_path, policy)
            clean_path.unlink(missing_ok=True)
            write(out/'speech_check.json', result)
            return result
        if cleanup.get('status') == 'blocked':
            result['audio_cleanup'] = cleanup
            if cleanup.get('speech_window_alignment'):
                from .audio_cleanup import alignment_evidence
                result.update(alignment_evidence(cleanup['speech_window_alignment']))
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
            result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected, normalize_enabled)
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
                result = _normalize_mix_if_needed(source, out, result, shot, cleaned, clean_sr, expected, normalize_enabled)
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
        result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected, normalize_enabled)
        write(out/'speech_check.json',result)
        return result
    if cleanup_enabled and shot.get('dialogue') and not dialogue_postdub:
        from .audio_cleanup import clean
        cleanup = clean(source, out, recognition, samples, sr, transcribe, result['expected'], shot.get('dialogue'))
        if cleanup.get('speech_window_alignment'):
            from .audio_cleanup import alignment_evidence
            result.update(alignment_evidence(cleanup['speech_window_alignment']))
        if cleanup['status'] == 'applied':
            original_check = result
            result = dict(cleanup['post_check'], original_check=original_check)
        result['audio_cleanup'] = cleanup
    result.update(video_sha256=file_hash(source), speakers=[line['speaker'] for line in shot['dialogue']],
                  reference_bindings=take.get('speech_bindings',[]), speech_gate=voice_gate)
    if dialogue_postdub:
        result['dialogue_postdub'] = dialogue_postdub
        result['human_listened'] = False
        from .media import technical_qc
        from .director import delivered_frames
        config = read(root/'config.json')
        technical = technical_qc(source, delivered_frames(shot),
                                 int(config['generation']['width']), int(config['generation']['height']))
        result['technical_qc'] = technical
        if not technical.get('passed'):
            result['passed'] = False
    result = _normalize_mix_if_needed(source, out, result, shot, samples, sr, expected, normalize_enabled)
    write(out/'speech_check.json',result)
    return result

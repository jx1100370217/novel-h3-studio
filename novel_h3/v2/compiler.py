"""Compile a film shot into a small, mode-specific native audiovisual request.

Creative plans and evidence remain outside the model prompt. This first route
deliberately supports Ref2VA only; mode changes must not retain phantom inputs.
"""
import math
import re
import subprocess
from pathlib import Path

from ..comfy import asset_for, config, generation_reference
from ..project import digest, file_hash, inside, read, safe_id, write
from .audio_anchor import AUDIO_ROUTE, VERSION as ANCHOR_VERSION, add_audio_anchor, validate_target_audio

VERSION = 'cinema_ref2va_native_v2'
GRAPH_PROFILE = {'version': 1, 'shift_video': 12.0, 'shift_audio': 3.0,
                 'ref_image_size': 'match', 'trim_frames': 0}


def pinned_models(root, cfg):
    """Hash immutable weights once, refreshing the cache if filesystem identity changes."""
    cache_path = Path(root) / 'production_v2/model_lock.json'
    old = read(cache_path) if cache_path.exists() else {}
    result = {}
    for key, folder in (('ref2va', 'diffusion_models'), ('clip', 'text_encoders'),
                        ('video_vae', 'vae'), ('audio_vae', 'vae')):
        path = (Path(cfg['comfy_root']) / 'models' / folder / cfg['models'][key]).resolve(strict=True)
        stat = path.stat()
        identity = {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
                    'device': stat.st_dev, 'inode': stat.st_ino}
        previous = old.get(key, {})
        sha = previous.get('sha256') if previous.get('identity') == identity else None
        result[key] = {'identity': identity, 'sha256': sha or file_hash(path)}
    if result != old:
        write(cache_path, result)
    return result


def frames_for(seconds):
    if isinstance(seconds, bool) or not 4 <= float(seconds) <= 15:
        raise ValueError('H3 production clips must request 4–15 seconds; shorter edits use source in/out')
    return 5 + 17 * math.ceil((float(seconds) * 24 - 5) / 17)


def inventory(root):
    result = {}
    for bucket, kind in (('characters', 'character'), ('scenes', 'scene'), ('props', 'prop')):
        for name, item in read(Path(root) / 'bible/assets.json').get(bucket, {}).items():
            result[item['id']] = dict(item, name=name, kind=kind)
    return result


def validate_shot(shot, assets):
    safe_id(shot['id'])
    frames_for(shot['duration_seconds'])
    cast = shot.get('cast', [])
    if len(cast) != len(set(cast)):
        raise ValueError('Each visible character must be bound once')
    if any(assets.get(a, {}).get('kind') != 'character' for a in cast):
        raise ValueError('Visible cast must refer to registered character IDs')
    if assets.get(shot.get('scene_id'), {}).get('kind') != 'scene':
        raise ValueError('The shot must have exactly one registered scene')
    speakers = {line['speaker'] for line in shot.get('spoken_lines', [])}
    if any(type(line.get('offscreen', False)) is not bool for line in shot.get('spoken_lines', [])):
        raise ValueError('The offscreen flag must be a boolean, not an inferred speaker location')
    voice_locations = {line.get('offscreen', False) for line in shot.get('spoken_lines', [])}
    offscreen = voice_locations == {True}
    if len(voice_locations) > 1:
        raise ValueError('A clip must keep one consistent onscreen or offscreen speech source')
    if offscreen and speakers.intersection(cast):
        raise ValueError('An offscreen voice identity cannot also be in the visible cast')
    if (len(speakers) > 1 or any(assets.get(a, {}).get('kind') != 'character' for a in speakers)
            or not offscreen and not speakers.issubset(cast)):
        raise ValueError('This native pilot supports one visible speaker per clip, with reactions edited separately')
    for line in shot.get('spoken_lines', []):
        if not line.get('text', '').strip() or any(t in line['text'] for t in ('<', '>')):
            raise ValueError('Dialogue must be literal, nonempty text without prompt markup')
    camera = shot.get('camera')
    if not isinstance(camera, (str, dict)) or not camera:
        raise ValueError('Missing authored camera direction')
    for field in ('action', 'start_state', 'end_state', 'soundscape'):
        if not isinstance(shot.get(field), str) or not shot[field].strip():
            raise ValueError(f'Missing authored shot field: {field}')
        if re.search(r'<(?:Picture|Subject|Audio|Video)\s', shot[field]):
            raise ValueError('Reference ordinals belong to the compiler, not free-text directions')
    refs = cast + [shot['scene_id']] + shot.get('references', [])
    if len(set(refs)) > 9:
        raise ValueError('H3 accepts at most nine reference images')
    if any(a not in assets for a in refs):
        raise ValueError('Unregistered image reference')


def audio_duration(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'default=nw=1:nk=1', str(path)],
                            capture_output=True, text=True, check=True, timeout=15)
    return float(result.stdout.strip())


def compile_shot(root, plan, shot, seed):
    if plan.get('cinematization_required'):
        from .cinematization import require, shot_content
        require(root, plan)
        bound = next((s for s in plan['shots'] if s['id'] == shot['id']), None)
        if bound is None or shot_content(bound) != shot_content(shot):
            raise ValueError('Requested shot differs from its film screenplay')
    root = Path(root).resolve()
    safe_id(plan['id'])
    assets = inventory(root)
    validate_shot(shot, assets)
    cfg = config(root)
    target = shot.get('audio_target')
    if target:
        target = dict(target)
        target_path = inside(root, target['path'])
        if target_path.suffix.lower() != '.wav' or file_hash(target_path) != target['sha256']:
            raise ValueError('Dialogue target must be an unchanged project WAV')
        if target.get('kind') == 'nonverbal':
            if shot.get('spoken_lines') or target.get('speaker') or target.get('text'):
                raise ValueError('A nonverbal target cannot carry assigned dialogue or a speaker')
            proof_path = inside(root, target['verification_path'])
            proof = read(proof_path)
            if (file_hash(proof_path) != target['verification_sha256']
                    or proof.get('target_sha256') != target['sha256'] or proof.get('passed') is not True
                    or proof.get('speech_gate', {}).get('speech_detected') is not False):
                raise ValueError('Nonverbal target lacks a matching no-speech inspection')
        else:
            if not shot.get('spoken_lines'):
                raise ValueError('A dialogue target requires assigned spoken lines')
            if target.get('speaker') != shot['spoken_lines'][0]['speaker'] or target.get('text') != ''.join(line['text'] for line in shot['spoken_lines']):
                raise ValueError('Dialogue target speaker and literal text must match the authored shot')
        target['duration_seconds'] = audio_duration(target_path)
        validate_target_audio(frames_for(shot['duration_seconds']), target['duration_seconds'])
        target['conditioning_schema'] = ANCHOR_VERSION
    camera = shot['camera']
    if isinstance(camera, dict):
        camera_text = f"{camera.get('size', 'medium shot')}, {camera.get('lens_mm', 50)}mm lens. {camera.get('movement', '')}. {camera.get('composition', '')}"
    else:
        camera_text = camera
    speaking = [line['speaker'] for line in shot.get('spoken_lines', [])]
    offscreen = bool(shot.get('spoken_lines')) and all(line.get('offscreen') is True for line in shot['spoken_lines'])
    reference_scope = shot.get('visual_reference_scope')
    prompt_focus = shot.get('generation_prompt_focus')
    if prompt_focus is not None:
        if prompt_focus == 'static_court':
            if reference_scope != 'seated_court' or speaking or target:
                raise ValueError('Static court focus requires the strict silent seated-court scope and no audio target')
        elif prompt_focus == 'single_actor_tableau':
            if (reference_scope != 'single_actor_props' or speaking or target
                    or len(shot.get('references', [])) != 1 or not isinstance(camera, dict)
                    or not any(word in camera.get('movement', '').lower() for word in ('fixed', 'locked', 'rigid'))):
                raise ValueError('Single actor tableau focus requires the strict silent single-actor-props scope, one prop, fixed camera and no audio target')
        elif (prompt_focus != 'static_prop' or reference_scope != 'props_only'
                or shot['cast'] or speaking or target or len(shot.get('references', [])) != 1
                or not isinstance(camera, dict) or 'insert' not in camera.get('size', '').lower()
                or float(camera.get('lens_mm', 0)) < 75
                or not any(word in camera.get('movement', '').lower() for word in ('fixed', 'locked', 'rigid'))):
            raise ValueError('Static prop focus requires a silent person-free single-prop fixed insert with props-only references and no audio target')
    setting_ids = [shot['scene_id']]
    if reference_scope is not None:
        references = shot.get('references', [])
        if reference_scope == 'props_only':
            if shot['cast'] or speaking or not references or any(assets[a]['kind'] != 'prop' for a in references):
                raise ValueError('Props-only framing requires a silent, person-free prop insert')
        elif reference_scope == 'speaker_portrait':
            if (len(shot['cast']) != 1 or offscreen or set(speaking) != set(shot['cast'])
                    or int(assets[shot['cast'][0]].get('instances', 1)) != 1
                    or shot.get('views', {}).get(shot['cast'][0]) != 'face'
                    or not isinstance(camera, dict) or 'close' not in camera.get('size', '').lower()
                    or float(camera.get('lens_mm', 0)) < 75
                    or any(assets[a]['kind'] != 'prop' for a in references)):
                raise ValueError('Speaker portrait requires one visible speaker, an explicit face view, a close-up and only prop references')
        elif reference_scope == 'single_actor_props':
            if (len(shot['cast']) != 1 or speaking or target
                    or int(assets[shot['cast'][0]].get('instances', 1)) != 1
                    or shot.get('views', {}).get(shot['cast'][0]) != 'face'
                    or not isinstance(camera, dict) or 'medium' not in camera.get('size', '').lower()
                    or float(camera.get('lens_mm', 0)) < 50 or not references
                    or any(assets[a]['kind'] != 'prop' for a in references)):
                raise ValueError('Single actor props requires one silent individual, an explicit face view, a medium shot and prop references only')
        elif reference_scope == 'seated_court':
            if (speaking or target or references
                    or sorted(int(assets[a].get('instances', 1)) for a in shot['cast']) != [1, 1, 1, 9]
                    or any(shot.get('views', {}).get(a) != 'front' for a in shot['cast'])
                    or not isinstance(camera, dict)
                    or not all(word in camera.get('size', '').lower() for word in ('complete', 'seated', 'court'))
                    or any(word in camera.get('size', '').lower() for word in ('close', 'portrait'))
                    or float(camera.get('lens_mm', 0)) < 85
                    or not any(word in camera.get('movement', '').lower() for word in ('fixed', 'locked', 'rigid'))):
                raise ValueError('Seated court requires three silent individuals plus one nine-person ensemble, explicit front views, fixed court framing and character references only')
        else:
            raise ValueError('Unknown visual reference scope')
        setting_ids = []
    image_ids = list(dict.fromkeys(speaking + shot['cast'] + setting_ids + shot.get('references', [])))
    aliases = plan.get('subject_aliases', {})
    visuals, subjects = [], {}
    for i, asset_id in enumerate(image_ids, 1):
        ref = {'asset_id': asset_id}
        if assets[asset_id]['kind'] == 'character':
            ref['view'] = shot.get('views', {}).get(asset_id, 'front')
        if assets[asset_id]['kind'] == 'character':
            resolved = generation_reference(root, ref, camera={'size': camera_text})
            if reference_scope == 'single_actor_props' and resolved.get('selected_view') != 'face':
                raise ValueError('Single actor props requires a resolved approved face view')
            if reference_scope == 'seated_court' and resolved.get('selected_view') != 'front':
                raise ValueError('Seated court requires resolved approved front views')
        else:
            path, sha = asset_for(root, asset_id)
            resolved = {'asset_id': asset_id, 'generation_path': str(path.relative_to(root)),
                        'generation_sha256': sha, 'source_sha256': sha, 'variant': 'approved_full_image'}
        role = aliases.get(asset_id, f'registered {assets[asset_id]["kind"]} {i}')
        visuals.append(dict(resolved, kind=assets[asset_id]['kind'], alias=role,
                            instances=int(assets[asset_id].get('instances', 1)),
                            picture=f'<Picture {i}>', subject=f'<Subject {i}>'))
        subjects[asset_id] = f'<Subject {i}>'

    voice_bank = {v.get('asset_id'): dict(v, speaker_name=n) for n, v in read(root / 'bible/voices.json').items()}
    voices = []
    for asset_id in dict.fromkeys(speaking):
        voice = voice_bank.get(asset_id)
        if not voice or voice.get('approved') is not True:
            raise ValueError(f'Voice reference is not ready: {asset_id}')
        path = inside(root, voice['path'])
        if file_hash(path) != voice['sha256']:
            raise ValueError('Voice reference changed after review')
        seconds = audio_duration(path)
        if not 2 <= seconds <= 15:
            raise ValueError('H3 voice references must be 2–15 seconds')
        voices.append({'asset_id': asset_id, 'path': voice['path'], 'sha256': voice['sha256'],
                       'seconds': seconds, 'audio': f'<Audio {len(voices)+1}>',
                       'subject': subjects[asset_id]})
    if len(voices) > 3 or sum(v['seconds'] for v in voices) > 15 or len(visuals) + len(voices) > 12:
        raise ValueError('H3 mixed-reference capacity exceeded')

    def bind(text):
        # Aliases in authored camera/action text are bound by one shared map.
        pairs = [(aliases.get(a, a), subjects[a]) for a in image_ids]
        for alias, label in sorted(pairs, key=lambda item: -len(item[0])):
            text = re.sub(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', label, text)
        return text

    definitions, retention = [], []
    for ref in visuals:
        if ref['kind'] == 'character':
            if offscreen and ref['asset_id'] in speaking:
                definitions.append(f"{ref['subject']} is the offscreen voice identity associated with {ref['picture']}; do not show this person, face, body or portrait in this shot. The reference identifies the voice source, not a visible cast member.")
                retention.append(f"{ref['subject']}: retain the assigned vocal identity only; exclude this subject's visible appearance from the entire shot.")
            elif ref['instances'] > 1:
                definitions.append(f"{ref['subject']} is the ensemble of exactly {ref['instances']} distinct members in {ref['picture']}; preserve their individual faces and costumes. Use them in the authored coherent scene, not as a portrait grid.")
                retention.append(f"{ref['subject']}: exactly {ref['instances']} distinct group members, no second group or cloned member; follow the authored seating and reaction.")
            else:
                definitions.append(f"{ref['subject']} is {ref['alias']}, the single person in {ref['picture']}; preserve the face, age, hair and costume. The reference portrait background is not the location.")
                retention.append(f"{ref['subject']}: preserve identity and costume, one body only; perform the authored action and eyeline.")
        elif ref['kind'] == 'scene':
            definitions.append(f"{ref['subject']} is the location in {ref['picture']}; use its architecture, materials and motivated light as the scene background.")
            retention.append(f"{ref['subject']}: preserve the same location and lighting between coverage angles.")
        else:
            definitions.append(f"{ref['subject']} is the single prop in {ref['picture']}; preserve its shape, scale and physical ownership.")
            retention.append(f"{ref['subject']}: one physical prop, used only as described in the action.")
    for voice in voices:
        definitions.append(f"{voice['audio']} is the voice-timbre reference for {voice['subject']} (S1); use its vocal identity with the new dialogue below, not the reference recording's words.")
        retention.append(f"{voice['audio']}: reference vocal timbre; generate fresh, naturally synchronized speech for its subject.")
    dialogue = []
    lines = shot.get('spoken_lines', [])
    if lines:
        text = ''.join(line['text'] for line in lines)
        intention = bind(shot.get('performance_direction', 'Address the listener truthfully with restrained, natural emotion.'))
        start = float(lines[0].get('start_seconds', 0.5))
        if start < 0 or start >= shot['duration_seconds']:
            raise ValueError('Speech start falls outside the generated clip')
        milliseconds = round(start * 1000)
        timestamp = f"00:{milliseconds // 1000:02d}.{milliseconds % 1000:03d}"
        if offscreen:
            dialogue.append(f"At {timestamp}, the offscreen voice of {subjects[lines[0]['speaker']]} (S1) says: <d>[Chinese] {text}</d>. Performance: {intention}. The sound comes from the authored offscreen location, not any visible person's mouth. Speak the complete line once. All visible characters keep their lips at rest and react by listening; do not reveal the unseen voice source.")
        else:
            dialogue.append(f"At {timestamp}, {subjects[lines[0]['speaker']]} (S1) says: <d>[Chinese] {text}</d>. Performance: {intention}. Speak this complete line once with natural phrasing and synchronized visible articulation; finish with a motivated listening reaction. Other visible characters listen without speaking.")
    elif target and target.get('kind') == 'nonverbal':
        dialogue.append('No spoken dialogue; follow only the authored physical action or stillness and the verified complete nonverbal audio target.')
    else:
        dialogue.append('No spoken dialogue in this clip; play the authored reaction with natural breathing and physical sound.'
                        if shot['cast'] else 'No spoken dialogue; use only the authored room ambience and physical prop sounds.')
    visible = ', '.join(f"{subjects[a]} ({int(assets[a].get('instances', 1))} person(s))" for a in shot['cast'])
    body_count = sum(int(assets[a].get('instances', 1)) for a in shot['cast'])
    cast_instruction = (f'Visible people: {visible}. Keep their count, faces, eyelines and physical positions coherent.'
                        if shot['cast'] else 'No people are visible in this insert; preserve the authored prop and setting.')
    if body_count:
        cast_instruction += f' The authored visible cast contains exactly {body_count} people in total.'
    material_policy = ('Natural materials; follow the authored movement or stillness;'
        if reference_scope in ('props_only', 'single_actor_props') else 'Natural materials and motivated movement;')
    sound_policy = (' Use only the authored ambience and prop sounds; do not add an unrequested handling event or voices. No narration, unassigned words or music.'
        if reference_scope == 'props_only' else ' Clear native dialogue when assigned, coherent room ambience and synchronous physical sound. No narration, unassigned words or music.')
    execution = shot.get('cinematic_execution', {})
    continuity = ''
    if execution:
        continuity = ('\nSpatial continuity: ' + bind(execution['axis_id']) + '; ' + bind(execution['screen_direction'])
            + '. ' + bind(execution['transition']['audience_cue'])
            + '\nComplete the authored action once. Preserve the opening and ending blocking; no pose reset, repeated entrance or internal cut.')
    prompt = '\n\n'.join([
        'subject_definitions:\n' + '\n'.join(definitions),
        'summary:\nOne continuous photorealistic Chinese period drama shot. ' + bind(shot['action']),
        'retention_analysis:\n' + '\n'.join(retention),
        'detailed_description:\n' +
        f"[Shot 1] Duration approximately {shot['duration_seconds']} seconds. " +
        bind(camera_text) + '\nEyeline: ' + bind(shot.get('eyeline', 'Follow the established scene axis.')) + '\nOpening: ' + bind(shot['start_state']) +
        '\nAction: ' + bind(shot['action']) + '\n' + '\n'.join(dialogue) +
        '\nEnding: ' + bind(shot['end_state']) +
        continuity +
        f'\n{cast_instruction} {material_policy} no unrequested cut, extra person, clone, subtitles or graphic overlay.',
        'overall_soundscape:\n' + bind(shot['soundscape']) + sound_policy,
        'non_diegetic_music:\nN/A',
    ])
    if prompt_focus == 'static_prop':
        ref = visuals[0]
        prompt = '\n\n'.join([
            f"subject_definitions:\n{ref['subject']} is the single stationary prop in {ref['picture']}; preserve its material, contour and texture in the authored resting pose.",
            'summary:\nOne continuous photorealistic stationary material still life. ' + bind(shot['action']),
            f"retention_analysis:\n{ref['subject']}: one stationary physical prop, continuously exposed in the same authored arrangement.",
            f"detailed_description:\n[Shot 1] Duration approximately {shot['duration_seconds']} seconds. " + bind(camera_text) + '\nAction: ' + bind(shot['action']),
            'overall_soundscape:\n' + bind(shot['soundscape']) + ' No speech or music.',
            'non_diegetic_music:\nN/A',
        ])
    elif prompt_focus == 'static_court':
        principals = [ref['subject'] for ref in visuals if ref['instances'] == 1]
        ensemble = next(ref for ref in visuals if ref['instances'] == 9)
        prompt = '\n\n'.join([
            'subject_definitions:\n' + '\n'.join(definitions),
            'summary:\nOne continuous photorealistic stationary seated court. ' + bind(shot['action']),
            'retention_analysis:\n' + ', '.join(principals) + ': three separate principal individuals. '
            + ensemble['subject'] + ': nine additional ordinary individuals, distinct from all three principals. '
            + 'The twelve individuals occupy twelve separate chairs in the one authored row.',
            f"detailed_description:\n[Shot 1] Duration approximately {shot['duration_seconds']} seconds. "
            + bind(camera_text) + '\nAction: ' + bind(shot['action']),
            'overall_soundscape:\n' + bind(shot['soundscape']),
            'non_diegetic_music:\nN/A',
        ])
    elif prompt_focus == 'single_actor_tableau':
        prompt = '\n\n'.join([
            'subject_definitions:\n' + '\n'.join(definitions),
            'summary:\nOne continuous photorealistic fixed medium tableau. ' + bind(shot['action']),
            'retention_analysis:\n' + '\n'.join(retention),
            f"detailed_description:\n[Shot 1] Duration approximately {shot['duration_seconds']} seconds. "
            + bind(camera_text) + '\nAction: ' + bind(shot['action']),
            'overall_soundscape:\n' + bind(shot['soundscape']),
            'non_diegetic_music:\nN/A',
        ])
    for label, count in (('Picture', len(visuals)), ('Audio', len(voices)), ('Subject', len(visuals)), ('Video', 0)):
        if any(not 1 <= int(i) <= count for i in re.findall(r'<' + label + r' (\d+)>', prompt)):
            raise ValueError(f'Unresolved {label} reference')
    if 'All bound mouths stay closed' in prompt and lines:
        raise ValueError('Dialogue contradicts mouth-rest instructions')
    request = {'schema': VERSION, 'plan_id': plan['id'], 'shot_id': shot['id'],
               'plan_sha256': digest(plan), 'shot_sha256': digest(shot), 'shot': shot,
               'mode': 'ref2va', 'audio_route': AUDIO_ROUTE if target else 'h3_native_joint', 'seed': int(seed),
               'frames': frames_for(shot['duration_seconds']), 'fps': 24,
               'generation': dict(cfg['generation']), 'models': dict(cfg['models']),
               'model_lock': pinned_models(root, cfg), 'graph_profile': dict(GRAPH_PROFILE),
               'visuals': visuals, 'voices': voices, 'prompt': prompt,
               'prompt_sha256': digest(prompt), 'bgm': False}
    if target:
        request['audio_target'] = target
    if reference_scope is not None:
        request['visual_reference_scope'] = reference_scope
    if prompt_focus is not None:
        request['generation_prompt_focus'] = prompt_focus
    request['request_sha256'] = digest(request)
    return request


def graph(request, take_id):
    """Native H3 graph, independent shot, no latent inheritance or replacement TTS."""
    safe_id(take_id)
    gen, models = request['generation'], request['models']
    prefix = f"novel_h3/cinema_v2/{request['plan_id']}/{request['shot_id']}/{take_id}"
    nodes = {}

    def add(n, kind, **inputs):
        nodes[str(n)] = {'class_type': kind, 'inputs': inputs}
        return [str(n), 0]

    model = add(1, 'UNETLoader', unet_name=models['ref2va'], weight_dtype='default')
    clip = add(2, 'CLIPLoader', clip_name=models['clip'], type='minimax', device='default')
    vae = add(3, 'VAELoader', vae_name=models['video_vae'])
    avae = add(4, 'VAELoader', vae_name=models['audio_vae'])
    profile = request['graph_profile']
    model = add(5, 'MiniMaxH3SigmaShift', model=model,
                shift_video=profile['shift_video'], shift_audio=profile['shift_audio'])
    inputs = {'clip': clip, 'vae': vae, 'audio_vae': avae, 'prompt': request['prompt'],
              'width': gen['width'], 'height': gen['height'], 'length': request['frames'],
              'ref_image_size': profile['ref_image_size']}
    for i, ref in enumerate(request['visuals']):
        inputs[f'ref_images.ref_image_{i}'] = add(100+i, 'LoadImage', image=ref['staged_name'])
    for i, voice in enumerate(request['voices']):
        inputs[f'ref_audios.ref_audio_{i}'] = add(200+i, 'LoadAudio', audio=voice['staged_name'])
    cond = add(6, 'MiniMaxH3ReferenceToVideo', **inputs)
    noise = add(9, 'RandomNoise', noise_seed=request['seed'])
    guider = add(10, 'BasicGuider', model=model, conditioning=cond)
    sampler = add(11, 'KSamplerSelect', sampler_name=gen['sampler'])
    sigmas = add(12, 'BasicScheduler', model=model, scheduler=gen['scheduler'], steps=gen['steps'], denoise=1.0)
    latent = ['6', 1]
    if request.get('audio_target'):
        target = request['audio_target']
        latent, _ = add_audio_anchor(nodes, staged_audio_name=target['staged_name'],
                                    frames=request['frames'], target_duration_seconds=target['duration_seconds'])
    sampled = add(13, 'SamplerCustomAdvanced', noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=latent)
    images = add(15, 'VAEDecode', samples=sampled, vae=vae)
    audio = add(16, 'VAEDecodeAudio', samples=sampled, vae=avae)
    add(17, 'SaveAudio', audio=audio, filename_prefix=prefix+'/native_audio')
    trimmed = add(18, 'MiniMaxH3MotionContextTrim', images=images, audio=audio,
                  trim_frames=profile['trim_frames'], fps=24.0, match_tail=True)
    video = add(19, 'CreateVideo', images=trimmed, audio=['18', 1], fps=24.0)
    add(20, 'SaveVideo', video=video, filename_prefix=prefix+'/native_video', format='mp4', **{'format.codec': 'h264'})
    return nodes, prefix

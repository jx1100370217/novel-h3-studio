import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3.project import file_hash, write
from novel_h3.v2.compiler import compile_shot, frames_for, graph
from novel_h3.v2.frames import sample_indices


class CinemaCompilerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root / 'config.json', {
            'generation': {'width': 1376, 'height': 768, 'steps': 20, 'fps': 24,
                           'sampler': 'er_sde', 'scheduler': 'beta'},
            'models': {'ref2va': 'ref.safetensors', 'clip': 'clip.safetensors',
                       'video_vae': 'video.safetensors', 'audio_vae': 'audio.safetensors'},
        })
        write(self.root / 'bible/assets.json', {
            'characters': {'甲': {'id': 'actor_a'}, '乙': {'id': 'actor_b'}},
            'scenes': {'殿': {'id': 'hall'}}, 'props': {'册': {'id': 'book'}},
        })
        (self.root / 'voice.wav').write_bytes(b'voice-fixture')
        write(self.root / 'bible/voices.json', {'甲': {
            'asset_id': 'actor_a', 'path': 'voice.wav',
            'sha256': file_hash(self.root / 'voice.wav'), 'approved': True,
        }})
        self.shot = {'id': 'P01', 'scene_id': 'hall', 'cast': ['actor_a', 'actor_b'],
                     'references': ['book'], 'duration_seconds': 6,
                     'spoken_lines': [{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}],
                     'camera': {'size': 'medium two-shot', 'lens_mm': 50,
                                'composition': 'Alpha looks toward Beta, not the lens.'},
                     'action': 'Alpha holds the book; Beta receives the request without speaking.',
                     'start_state': 'The two people face each other.',
                     'end_state': 'Beta lowers his gaze in thought.',
                     'soundscape': 'Quiet hall ambience and soft cloth movement.',
                     'performance_direction': 'An earnest request to the listener, with one restrained breath.'}
        self.plan = {'id': 'pilot', 'subject_aliases': {'actor_a': 'Alpha', 'actor_b': 'Beta'},
                     'shots': [self.shot]}
        self.image = patch('novel_h3.v2.compiler.generation_reference',
                           side_effect=lambda root, ref, **kw: {'asset_id': ref['asset_id'],
                               'generation_path': ref['asset_id']+'.png', 'generation_sha256': 'image-hash',
                               'selected_view': ref.get('view', 'front')})
        self.image.start()
        self.addCleanup(self.image.stop)
        self.full_image = patch('novel_h3.v2.compiler.asset_for',
                                side_effect=lambda root, a: (root / (a+'.png'), 'full-image-hash'))
        self.full_image.start()
        self.addCleanup(self.full_image.stop)
        self.model_lock = patch('novel_h3.v2.compiler.pinned_models', return_value={'ref2va': {'sha256': 'weights'}})
        self.model_lock.start()
        self.addCleanup(self.model_lock.stop)
        self.duration = patch('novel_h3.v2.compiler.audio_duration', return_value=8.0)
        self.duration.start()
        self.addCleanup(self.duration.stop)

    def test_native_prompt_binds_every_reference_and_keeps_dialogue(self):
        req = compile_shot(self.root, self.plan, self.shot, 123)
        text = req['prompt']
        self.assertIn('<d>[Chinese] 让我先照顾母亲。</d>', text)
        self.assertIn('<Subject 1> holds the <Subject 4>; <Subject 2> receives', text)
        self.assertIn('At 00:00.500', text)
        self.assertIn('<Audio 1> is the voice-timbre reference for <Subject 1> (S1)', text)
        self.assertIn('<Subject 1> (S1) says:', text)
        self.assertNotIn('All bound mouths stay closed', text)
        self.assertNotIn('MOUTH_AUDIO_LINK=OFF', text)
        self.assertNotIn('asset_id', text)
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertEqual([r['variant'] for r in req['visuals'] if r['kind'] != 'character'],
                         ['approved_full_image', 'approved_full_image'])
        for i, ref in enumerate(req['visuals']): ref['staged_name'] = f'image{i}.png'
        req['voices'][0]['staged_name'] = 'voice.wav'
        nodes, _ = graph(req, 'candidate')
        self.assertEqual(nodes['6']['class_type'], 'MiniMaxH3ReferenceToVideo')
        self.assertEqual(nodes['18']['inputs']['trim_frames'], 0)
        self.assertEqual(nodes['19']['inputs']['audio'], ['18', 1])
        self.assertEqual(nodes['17']['class_type'], 'SaveAudio')
        self.assertNotIn('ApplyVDNH3', [n['class_type'] for n in nodes.values()])

    def test_voice_hash_change_blocks_submission(self):
        (self.root / 'voice.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Voice reference changed'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_props_only_insert_uses_only_bound_prop_images(self):
        self.shot.update(cast=[], spoken_lines=[], visual_reference_scope='props_only',
                         action='The book rests still on bare wood.')
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], ['book'])
        self.assertEqual(req['shot']['scene_id'], 'hall')
        self.assertEqual(req['visual_reference_scope'], 'props_only')
        self.assertEqual(req['voices'], [])
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertNotIn('the location in', req['prompt'])
        self.assertIn('No people are visible', req['prompt'])
        self.assertNotIn('Natural materials and motivated movement', req['prompt'])
        self.assertIn('authored movement or stillness', req['prompt'])

    def test_props_only_scope_cannot_hide_a_speaker_or_visible_cast(self):
        self.shot['visual_reference_scope'] = 'props_only'
        with self.assertRaisesRegex(ValueError, 'person-free prop insert'):
            compile_shot(self.root, self.plan, self.shot, 123)
        self.shot.update(cast=[], spoken_lines=[], references=['actor_a'])
        with self.assertRaisesRegex(ValueError, 'person-free prop insert'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def static_prop_shot(self):
        self.shot.update(cast=[], spoken_lines=[], visual_reference_scope='props_only',
                         generation_prompt_focus='static_prop',
                         camera={'size': 'overhead insert', 'lens_mm': 85, 'movement': 'rigid fixed camera'},
                         action='The book already rests still on bare wood.',
                         start_state='After Alpha gave the book, it is already resting on wood.',
                         cinematic_execution={'axis_id': 'table', 'screen_direction': 'neutral',
                             'transition': {'audience_cue': 'The earlier handover and placing are complete.'}})

    def test_static_prop_focus_keeps_native_inputs_and_film_states_without_transfer_prompt(self):
        self.static_prop_shot()
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], ['book'])
        self.assertEqual(req['mode'], 'ref2va')
        self.assertEqual(req['visual_reference_scope'], 'props_only')
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertEqual(req['shot']['start_state'], self.shot['start_state'])
        self.assertEqual(req['shot']['cinematic_execution'], self.shot['cinematic_execution'])
        self.assertEqual(req['shot']['action'], self.shot['action'])
        self.assertIn('The <Subject 1> already rests still on bare wood.', req['prompt'])
        self.assertIn('85mm lens', req['prompt'])
        for text in ['Alpha', 'handover', 'placing', 'Opening:', 'Spatial continuity:', 'physical ownership']:
            self.assertNotIn(text, req['prompt'])

    def test_static_prop_focus_rejects_other_modes_people_speech_refs_and_camera(self):
        self.static_prop_shot()
        for changes in [dict(generation_prompt_focus='free_text'), dict(visual_reference_scope=None),
                        dict(cast=['actor_a']), dict(spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}]),
                        dict(references=['book', 'book']),
                        dict(camera={'size': 'wide shot', 'lens_mm': 85, 'movement': 'fixed'}),
                        dict(camera={'size': 'insert', 'lens_mm': 50, 'movement': 'fixed'}),
                        dict(camera={'size': 'insert', 'lens_mm': 85, 'movement': 'pan'})]:
            with self.subTest(changes=changes):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaises(ValueError): compile_shot(self.root, self.plan, shot, 123)

    def test_static_prop_focus_cannot_substitute_nonverbal_target_audio(self):
        self.static_prop_shot()
        quiet = self.root / 'quiet.wav'
        quiet.write_bytes(b'nonverbal-fixture')
        proof = self.root / 'quiet_check.json'
        write(proof, {'passed': True, 'target_sha256': file_hash(quiet),
                      'speech_gate': {'speech_detected': False}})
        self.shot['audio_target'] = {'kind': 'nonverbal', 'path': 'quiet.wav',
            'sha256': file_hash(quiet), 'speaker': None, 'text': '',
            'verification_path': 'quiet_check.json', 'verification_sha256': file_hash(proof)}
        with self.assertRaisesRegex(ValueError, 'Static prop focus requires'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_speaker_portrait_retains_face_prop_voice_and_exact_dialogue(self):
        self.shot.update(cast=['actor_a'], views={'actor_a': 'face'},
                         visual_reference_scope='speaker_portrait',
                         camera={'size': 'fixed chest-up close-up', 'lens_mm': 85})
        self.dialogue_target()
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], ['actor_a', 'book'])
        self.assertEqual(req['shot']['scene_id'], 'hall')
        self.assertEqual(req['voices'][0]['asset_id'], 'actor_a')
        self.assertEqual(req['audio_target']['text'], '让我先照顾母亲。')
        self.assertEqual(req['audio_route'], 'h3_audio_conditioned')
        self.assertEqual(req['visual_reference_scope'], 'speaker_portrait')
        self.assertIn('<d>[Chinese] 让我先照顾母亲。</d>', req['prompt'])
        self.assertNotIn('the location in', req['prompt'])

    def test_speaker_portrait_rejects_unbound_cast_view_or_framing(self):
        self.shot.update(cast=['actor_a'], views={'actor_a': 'face'},
                         visual_reference_scope='speaker_portrait',
                         camera={'size': 'fixed chest-up close-up', 'lens_mm': 85})
        for changes in [dict(cast=['actor_a', 'actor_b']), dict(spoken_lines=[]),
                        dict(views={'actor_a': 'front'}), dict(references=['actor_b']),
                        dict(camera={'size': 'wide shot', 'lens_mm': 85}),
                        dict(camera={'size': 'close-up', 'lens_mm': 50}),
                        dict(cast=['actor_b'], spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。', 'offscreen': True}])]:
            with self.subTest(changes=changes):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaisesRegex(ValueError, 'Speaker portrait requires'):
                    compile_shot(self.root, self.plan, shot, 123)

    def test_speaker_portrait_rejects_an_ensemble_face(self):
        self.shot.update(cast=['actor_a'], views={'actor_a': 'face'},
                         visual_reference_scope='speaker_portrait',
                         camera={'size': 'fixed chest-up close-up', 'lens_mm': 85})
        with patch('novel_h3.v2.compiler.inventory', return_value={
                'actor_a': {'kind': 'character', 'instances': 9},
                'hall': {'kind': 'scene'}, 'book': {'kind': 'prop'}}):
            with self.assertRaisesRegex(ValueError, 'Speaker portrait requires'):
                compile_shot(self.root, self.plan, self.shot, 123)

    def test_single_actor_props_keeps_silent_actor_props_and_logical_scene(self):
        self.shot.update(cast=['actor_a'], spoken_lines=[], views={'actor_a': 'face'},
                         visual_reference_scope='single_actor_props',
                         camera={'size': 'fixed single-person medium shot', 'lens_mm': 55})
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], ['actor_a', 'book'])
        self.assertEqual(req['shot']['scene_id'], 'hall')
        self.assertEqual(req['voices'], [])
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertNotIn('the location in', req['prompt'])
        self.assertNotIn('<d>', req['prompt'])
        self.assertIn('exactly 1 people in total', req['prompt'])
        self.assertIn('authored movement or stillness', req['prompt'])

    def test_single_actor_props_rejects_voice_extra_people_or_wrong_inputs(self):
        self.shot.update(cast=['actor_a'], spoken_lines=[], views={'actor_a': 'face'},
                         visual_reference_scope='single_actor_props',
                         camera={'size': 'fixed single-person medium shot', 'lens_mm': 55})
        for changes in [dict(cast=[]), dict(cast=['actor_a', 'actor_b']),
                        dict(spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}]),
                        dict(spoken_lines=[{'speaker': 'actor_b', 'text': '让我先照顾母亲。', 'offscreen': True}]),
                        dict(views={'actor_a': 'front'}), dict(references=[]), dict(references=['hall']),
                        dict(camera={'size': 'wide shot', 'lens_mm': 55}),
                        dict(camera={'size': 'medium shot', 'lens_mm': 35})]:
            with self.subTest(changes=changes):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaisesRegex(ValueError, 'Single actor props requires'):
                    compile_shot(self.root, self.plan, shot, 123)

    def test_single_actor_props_rejects_ensemble_or_face_fallback(self):
        self.shot.update(cast=['actor_a'], spoken_lines=[], views={'actor_a': 'face'},
                         visual_reference_scope='single_actor_props',
                         camera={'size': 'fixed single-person medium shot', 'lens_mm': 55})
        with patch('novel_h3.v2.compiler.inventory', return_value={
                'actor_a': {'kind': 'character', 'instances': 9},
                'hall': {'kind': 'scene'}, 'book': {'kind': 'prop'}}):
            with self.assertRaisesRegex(ValueError, 'Single actor props requires'):
                compile_shot(self.root, self.plan, self.shot, 123)
        with patch('novel_h3.v2.compiler.generation_reference', return_value={
                'asset_id': 'actor_a', 'generation_path': 'actor_a.png',
                'generation_sha256': 'image-hash', 'selected_view': 'front'}):
            with self.assertRaisesRegex(ValueError, 'resolved approved face'):
                compile_shot(self.root, self.plan, self.shot, 123)
        quiet = self.root / 'quiet.wav'
        quiet.write_bytes(b'nonverbal-fixture')
        proof = self.root / 'quiet_check.json'
        write(proof, {'passed': True, 'target_sha256': file_hash(quiet),
                      'speech_gate': {'speech_detected': False}})
        self.shot['audio_target'] = {'kind': 'nonverbal', 'path': 'quiet.wav',
            'sha256': file_hash(quiet), 'speaker': None, 'text': '',
            'verification_path': 'quiet_check.json', 'verification_sha256': file_hash(proof)}
        with self.assertRaisesRegex(ValueError, 'Single actor props requires'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def dialogue_target(self):
        path = self.root / 'target.wav'
        path.write_bytes(b'full-length-dialogue-fixture')
        self.shot['audio_target'] = {'path': 'target.wav', 'sha256': file_hash(path),
                                     'speaker': 'actor_a', 'text': '让我先照顾母亲。'}

    def court_shot(self):
        self.shot.update(cast=['actor_a', 'actor_b', 'actor_c', 'officials'],
                         spoken_lines=[], references=[], visual_reference_scope='seated_court',
                         views={a: 'front' for a in ['actor_a', 'actor_b', 'actor_c', 'officials']},
                         camera={'size': 'complete twelve-person seated court view', 'lens_mm': 85,
                                 'movement': 'rigid fixed tripod'})
        return {'actor_a': {'kind': 'character'}, 'actor_b': {'kind': 'character'},
                'actor_c': {'kind': 'character'}, 'officials': {'kind': 'character', 'instances': 9},
                'hall': {'kind': 'scene'}, 'book': {'kind': 'prop'}}

    def test_seated_court_retains_twelve_people_and_logical_scene_without_hall_image(self):
        with patch('novel_h3.v2.compiler.inventory', return_value=self.court_shot()):
            req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], self.shot['cast'])
        self.assertEqual(req['shot']['scene_id'], 'hall')
        self.assertEqual(req['voices'], [])
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertNotIn('the location in', req['prompt'])
        self.assertIn('exactly 12 people in total', req['prompt'])

    def test_seated_court_rejects_speech_population_views_and_unfixed_inputs(self):
        assets = self.court_shot()
        for changes in [dict(cast=['actor_a', 'actor_b', 'officials']),
                        dict(spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}]),
                        dict(references=['hall']), dict(references=['book']),
                        dict(views={'actor_a': 'face', 'actor_b': 'front', 'actor_c': 'front', 'officials': 'front'}),
                        dict(camera={'size': 'wide shot', 'lens_mm': 85, 'movement': 'fixed'}),
                        dict(camera={'size': 'complete seated court close-up', 'lens_mm': 85, 'movement': 'fixed'}),
                        dict(camera={'size': 'seated court', 'lens_mm': 55, 'movement': 'fixed'}),
                        dict(camera={'size': 'seated court', 'lens_mm': 85, 'movement': 'pan'})]:
            with self.subTest(changes=changes), patch('novel_h3.v2.compiler.inventory', return_value=assets):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaisesRegex(ValueError, 'Seated court requires'):
                    compile_shot(self.root, self.plan, shot, 123)
        assets['officials']['instances'] = 8
        with patch('novel_h3.v2.compiler.inventory', return_value=assets):
            with self.assertRaisesRegex(ValueError, 'Seated court requires'):
                compile_shot(self.root, self.plan, self.shot, 123)

    def test_seated_court_rejects_target_audio_and_front_view_fallback(self):
        assets = self.court_shot()
        with patch('novel_h3.v2.compiler.inventory', return_value=assets), patch(
                'novel_h3.v2.compiler.generation_reference', return_value={
                    'asset_id': 'actor_a', 'generation_path': 'actor_a.png',
                    'generation_sha256': 'image-hash', 'selected_view': 'face'}):
            with self.assertRaisesRegex(ValueError, 'resolved approved front'):
                compile_shot(self.root, self.plan, self.shot, 123)
        quiet = self.root / 'quiet.wav'
        quiet.write_bytes(b'nonverbal-fixture')
        proof = self.root / 'quiet_check.json'
        write(proof, {'passed': True, 'target_sha256': file_hash(quiet),
                      'speech_gate': {'speech_detected': False}})
        self.shot['audio_target'] = {'kind': 'nonverbal', 'path': 'quiet.wav',
            'sha256': file_hash(quiet), 'speaker': None, 'text': '',
            'verification_path': 'quiet_check.json', 'verification_sha256': file_hash(proof)}
        with patch('novel_h3.v2.compiler.inventory', return_value=assets):
            with self.assertRaisesRegex(ValueError, 'Seated court requires'):
                compile_shot(self.root, self.plan, self.shot, 123)

    def test_static_court_focus_preserves_twelve_inputs_without_generic_speech_or_arrival(self):
        assets = self.court_shot()
        self.shot.update(generation_prompt_focus='static_court',
                         action='The twelve seated people remain still in one row.',
                         soundscape='Soft distant room air.',
                         cinematic_execution={'axis_id': 'court', 'screen_direction': 'west side',
                             'transition': {'audience_cue': 'The arriving candidate crosses the hall.'}})
        with patch('novel_h3.v2.compiler.inventory', return_value=assets):
            req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], self.shot['cast'])
        self.assertEqual(sum(v['instances'] for v in req['visuals']), 12)
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertEqual(req['voices'], [])
        self.assertEqual(req['shot']['cinematic_execution'], self.shot['cinematic_execution'])
        self.assertIn('nine additional ordinary individuals', req['prompt'])
        self.assertIn('Soft distant room air.', req['prompt'])
        for text in ['Clear native dialogue', 'natural breathing', 'Opening:', 'Spatial continuity:', 'arriving candidate']:
            self.assertNotIn(text, req['prompt'])

    def test_static_court_focus_rejects_other_scopes_and_invalid_court_population(self):
        assets = self.court_shot()
        self.shot['generation_prompt_focus'] = 'static_court'
        for changes in [dict(visual_reference_scope='props_only'),
                        dict(visual_reference_scope='speaker_portrait'),
                        dict(cast=['actor_a', 'actor_b', 'officials']),
                        dict(references=['hall']),
                        dict(camera={'size': 'complete seated court', 'lens_mm': 85, 'movement': 'pan'}),
                        dict(spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}])]:
            with self.subTest(changes=changes), patch('novel_h3.v2.compiler.inventory', return_value=assets):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaises(ValueError): compile_shot(self.root, self.plan, shot, 123)

    def test_static_court_focus_cannot_substitute_nonverbal_target_audio(self):
        assets = self.court_shot()
        self.shot['generation_prompt_focus'] = 'static_court'
        quiet = self.root / 'quiet.wav'
        quiet.write_bytes(b'nonverbal-fixture')
        proof = self.root / 'quiet_check.json'
        write(proof, {'passed': True, 'target_sha256': file_hash(quiet),
                      'speech_gate': {'speech_detected': False}})
        self.shot['audio_target'] = {'kind': 'nonverbal', 'path': 'quiet.wav',
            'sha256': file_hash(quiet), 'speaker': None, 'text': '',
            'verification_path': 'quiet_check.json', 'verification_sha256': file_hash(proof)}
        with patch('novel_h3.v2.compiler.inventory', return_value=assets):
            with self.assertRaisesRegex(ValueError, 'Static court focus requires'):
                compile_shot(self.root, self.plan, self.shot, 123)

    def tableau_shot(self):
        self.shot.update(cast=['actor_a'], spoken_lines=[], views={'actor_a': 'face'},
                         visual_reference_scope='single_actor_props', generation_prompt_focus='single_actor_tableau',
                         camera={'size': 'medium head-and-table master', 'lens_mm': 55, 'movement': 'rigid fixed camera'},
                         cinematic_execution={'axis_id': 'table', 'screen_direction': 'west side',
                             'transition': {'audience_cue': 'The following overhead insert shows the page.'}})

    def test_single_actor_tableau_preserves_inputs_and_source_without_following_insert_prompt(self):
        self.tableau_shot()
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual([v['asset_id'] for v in req['visuals']], ['actor_a', 'book'])
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertEqual(req['voices'], [])
        self.assertEqual(req['shot']['cinematic_execution'], self.shot['cinematic_execution'])
        self.assertIn('55mm lens', req['prompt'])
        for text in ['overhead insert', 'Spatial continuity:', 'Opening:', 'Ending:', 'natural breathing']:
            self.assertNotIn(text, req['prompt'])

    def test_single_actor_tableau_rejects_wrong_scope_speech_props_or_camera(self):
        self.tableau_shot()
        for changes in [dict(visual_reference_scope='speaker_portrait'), dict(cast=['actor_a', 'actor_b']),
                        dict(spoken_lines=[{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}]),
                        dict(references=['book', 'book']), dict(references=['hall']),
                        dict(camera={'size': 'medium', 'lens_mm': 55, 'movement': 'tilt'}),
                        dict(camera={'size': 'wide', 'lens_mm': 55, 'movement': 'fixed'})]:
            with self.subTest(changes=changes):
                shot = copy.deepcopy(self.shot)
                shot.update(changes)
                with self.assertRaises(ValueError): compile_shot(self.root, self.plan, shot, 123)

    def test_single_actor_tableau_rejects_nonverbal_target_audio(self):
        self.tableau_shot()
        quiet = self.root / 'quiet.wav'
        quiet.write_bytes(b'nonverbal-fixture')
        proof = self.root / 'quiet_check.json'
        write(proof, {'passed': True, 'target_sha256': file_hash(quiet),
                      'speech_gate': {'speech_detected': False}})
        self.shot['audio_target'] = {'kind': 'nonverbal', 'path': 'quiet.wav',
            'sha256': file_hash(quiet), 'speaker': None, 'text': '',
            'verification_path': 'quiet_check.json', 'verification_sha256': file_hash(proof)}
        with self.assertRaisesRegex(ValueError, 'Single actor tableau focus requires'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_dialogue_target_is_seen_by_h3_during_sampling(self):
        self.dialogue_target()
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['audio_route'], 'h3_audio_conditioned')
        for i, ref in enumerate(req['visuals']): ref['staged_name'] = f'image{i}.png'
        req['voices'][0]['staged_name'] = 'voice.wav'
        req['audio_target']['staged_name'] = 'dialogue/target.wav'
        nodes, _ = graph(req, 'candidate')
        self.assertEqual(nodes['13']['inputs']['latent_image'], ['304', 0])
        self.assertEqual(nodes['302']['inputs']['value'], 0.0)
        self.assertEqual(nodes['304']['inputs']['video_latent'], ['6', 1])
        self.assertEqual(nodes['301']['class_type'], 'VAEEncodeAudio')
        self.assertEqual(nodes['17']['inputs']['audio'], ['16', 0])

    def test_wrong_target_words_or_speaker_are_rejected(self):
        self.dialogue_target()
        self.shot['audio_target']['text'] = '另外一句。'
        with self.assertRaisesRegex(ValueError, 'literal text'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_nonverbal_conditioning_requires_actual_no_speech_evidence(self):
        self.dialogue_target()
        self.shot['spoken_lines'] = []
        target = self.shot['audio_target']
        target.update(kind='nonverbal', text='', speaker=None)
        proof = self.root / 'no_speech.json'
        write(proof, {'passed': True, 'target_sha256': target['sha256'],
                      'speech_gate': {'speech_detected': False}})
        target.update(verification_path='no_speech.json', verification_sha256=file_hash(proof))
        request = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(request['audio_route'], 'h3_audio_conditioned')
        self.assertEqual(request['voices'], [])
        self.assertNotIn('<d>', request['prompt'])
        self.assertNotIn('natural breathing', request['prompt'])
        write(proof, {'passed': True, 'target_sha256': target['sha256'],
                      'speech_gate': {'speech_detected': True}})
        target['verification_sha256'] = file_hash(proof)
        with self.assertRaisesRegex(ValueError, 'no-speech inspection'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_short_or_changed_target_is_rejected(self):
        self.dialogue_target()
        with patch('novel_h3.v2.compiler.audio_duration', return_value=2.0):
            with self.assertRaisesRegex(ValueError, 'cover the complete'):
                compile_shot(self.root, self.plan, self.shot, 123)
        (self.root / 'target.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'unchanged project WAV'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_unbound_or_second_speaker_is_rejected(self):
        self.shot['spoken_lines'].append({'speaker': 'actor_b', 'text': '答复。'})
        with self.assertRaisesRegex(ValueError, 'one visible speaker'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_unsupported_short_generation_is_not_silently_clamped(self):
        with self.assertRaises(ValueError): frames_for(2)
        self.assertEqual((frames_for(7)-5) % 17, 0)

    def test_undeclared_ordinals_are_rejected_before_prompt_building(self):
        self.shot['action'] = '<Picture 9> appears suddenly.'
        with self.assertRaisesRegex(ValueError, 'compiler'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_reaction_clip_does_not_receive_voice_or_reference_words(self):
        self.shot['spoken_lines'] = []
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['voices'], [])
        self.assertNotIn('<d>', req['prompt'])
        self.assertNotIn('<Audio', req['prompt'])
        self.assertIn('natural breathing', req['prompt'])

    def test_offscreen_ear_voice_does_not_turn_the_listener_into_the_speaker(self):
        self.shot['cast'] = ['actor_b']
        self.shot['spoken_lines'][0]['offscreen'] = True
        self.shot['soundscape'] = 'A faint close voice is heard from the listening character ear.'
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertIn('the offscreen voice of <Subject 1> (S1)', req['prompt'])
        self.assertIn('All visible characters keep their lips at rest', req['prompt'])
        self.assertIn('exactly 1 people in total', req['prompt'])
        self.assertNotIn('synchronized visible articulation', req['prompt'])
        self.assertEqual(req['voices'][0]['asset_id'], 'actor_a')

    def test_offscreen_permission_cannot_allow_an_unregistered_or_mixed_speaker(self):
        self.shot['spoken_lines'][0]['offscreen'] = 1
        with self.assertRaisesRegex(ValueError, 'boolean'):
            compile_shot(self.root, self.plan, self.shot, 123)
        self.shot['spoken_lines'][0]['offscreen'] = True
        self.shot['spoken_lines'].append({'speaker': 'actor_a', 'text': '答复。', 'offscreen': False})
        with self.assertRaisesRegex(ValueError, 'consistent'):
            compile_shot(self.root, self.plan, self.shot, 123)
        self.shot['spoken_lines'] = [{'speaker':'unknown','text':'耳语。','offscreen':True}]
        with self.assertRaises(ValueError):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_creative_change_invalidates_the_request(self):
        first = compile_shot(self.root, self.plan, self.shot, 123)
        changed = copy.deepcopy(self.shot)
        changed['action'] += ' He sits down.'
        second = compile_shot(self.root, self.plan, changed, 123)
        self.assertNotEqual(first['request_sha256'], second['request_sha256'])

    def test_paper_insert_has_no_phantom_actor_or_voice(self):
        self.shot.update(cast=[], spoken_lines=[], action='A blank paper lies flat on the desk.')
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['voices'], [])
        self.assertIn('No people are visible in this insert', req['prompt'])
        self.assertNotIn('natural breathing', req['prompt'])

    def test_sampling_covers_last_frame_of_long_clip(self):
        frames = sample_indices(277)
        self.assertEqual(len(frames), 24)
        self.assertEqual(frames[0], 0)
        self.assertEqual(frames[-1], 276)

    def test_ensemble_reference_is_not_misdeclared_as_one_person(self):
        write(self.root / 'bible/assets.json', {
            'characters': {'众官': {'id': 'ensemble', 'instances': 9}},
            'scenes': {'殿': {'id': 'hall'}}, 'props': {},
        })
        self.shot.update(cast=['ensemble'], references=[], spoken_lines=[],
                         action='The ensemble is seated in one coherent row.')
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertIn('ensemble of exactly 9 distinct members', req['prompt'])
        self.assertIn('exactly 9 people in total', req['prompt'])


if __name__ == '__main__':
    unittest.main()

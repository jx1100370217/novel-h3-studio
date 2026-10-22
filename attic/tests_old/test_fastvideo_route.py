import copy
from pathlib import Path
import tempfile
import unittest

from novel_h3.fastvideo import request_payload, selected
from novel_h3.ref2va import render
from novel_h3.project import write
from novel_h3.v2.chapter_edit import chapter_timeline


class FastVideoRouteTests(unittest.TestCase):
    def setUp(self):
        self.visuals = [{'asset_id': 'actor', 'subject': '<Subject 1>', 'picture': '<Picture 1>', 'kind': 'character'}]
        self.sections = {
            'subject_definitions': '{subject:actor} is the man in {picture:actor}.',
            'summary': '[reference generation] {subject:actor} greets the listener.',
            'retention_analysis': '{subject:actor} (appears in [Shot 1]): fully_preserved - Keep his face and robe.',
            'detailed_description': 'A realistic period drama.\n[Shot 1] {subject:actor} (S1) says <d>[Chinese] 你好。</d>',
            'overall_soundscape': 'Quiet room tone.',
            'non_diegetic_music': 'N/A'}
        self.lines = [{'speaker': 'actor', 'text': '你好。'}]

    def test_native_route_does_not_select_an_old_comfy_profile(self):
        self.assertFalse(selected({'video_engine': 'fast_h3_omni', 'fast_h3_omni': {'model_variant': 'int8_convrot'}}))
        self.assertTrue(selected({'video_engine': 'fast_h3_omni', 'fast_h3_omni': {'backend': 'fastvideo'}}))

    def test_reference_order_and_native_dimensions_survive_http_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('a.png', 'b.png', 'voice.wav'):
                (Path(tmp) / name).write_bytes(b'media')
            visuals = [dict(self.visuals[0], generation_path='b.png'),
                       {'asset_id': 'room', 'subject': '<Subject 2>', 'picture': '<Picture 2>', 'generation_path': 'a.png', 'kind': 'scene'}]
            voices = [{'asset_id': 'actor', 'audio': '<Audio 1>', 'subject': '<Subject 1>', 'path': 'voice.wav'}]
            sections = copy.deepcopy(self.sections)
            sections['subject_definitions'] += '\n{subject:room} is the room in {picture:room}.\n{audio:actor} is the voice-timbre reference for {subject:actor} (S1).'
            sections['summary'] = '[reference generation + audio reference] {subject:actor} greets the listener.'
            sections['retention_analysis'] += '\n{subject:room} (appears in [Shot 1]): fully_preserved - Retain its layout.\n{audio:actor}: reference - Retain vocal identity.'
            sections['detailed_description'] += ' He remains in {subject:room}, using the vocal identity from {audio:actor}.'
            request = {'prompt': render(sections, visuals, voices, self.lines), 'seed': 4, 'frames': 243,
                       'shot': {'spoken_lines': self.lines},
                       'generation': {'width': 1344, 'height': 768},
                       'visuals': visuals, 'voices': voices}
            body = request_payload(tmp, request)
            self.assertEqual([Path(x['image_url']).name for x in body['image_reference']], ['b.png', 'a.png'])
            self.assertEqual(body['height'], 768)
            self.assertEqual(body['num_frames'], 243)
            self.assertEqual(body['task'], 'ref2va')
            self.assertEqual(body['model'], 'fasth3-omni-nvfp4-qad')
            request['generation']['width'] = 1376
            with self.assertRaisesRegex(ValueError, 'pixel limit'):
                request_payload(tmp, request)

    def test_chinese_is_preserved_only_inside_authored_dialogue(self):
        prompt = render(self.sections, self.visuals, [], self.lines)
        self.assertIn('<Subject 1> (S1)', prompt)
        bad = copy.deepcopy(self.sections)
        bad['summary'] += ' 他微笑。'
        with self.assertRaisesRegex(ValueError, 'English'):
            render(bad, self.visuals, [], self.lines)

    def test_unknown_reference_and_nonstandard_retention_are_rejected(self):
        bad = copy.deepcopy(self.sections)
        bad['summary'] += ' <Audio 1>'
        with self.assertRaisesRegex(ValueError, 'media input'):
            render(bad, self.visuals, [], self.lines)
        bad = copy.deepcopy(self.sections)
        bad['retention_analysis'] = '{subject:actor}: preserve him.'
        with self.assertRaisesRegex(ValueError, 'relationship marker'):
            render(bad, self.visuals, [], self.lines)

    def test_missing_dialogue_and_missing_body_binding_are_rejected(self):
        bad = copy.deepcopy(self.sections)
        bad['detailed_description'] = 'Realistic drama.\n[Shot 1] A man speaks.'
        with self.assertRaises(ValueError):
            render(bad, self.visuals, [], self.lines)

    def test_explicit_first_cut_retains_flagged_audio_without_approving_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            write(plan, {'shots': [{'id': 'S1', 'spoken_lines': [{'text': '请先奉母。'}]}]})
            write(blueprint, {'entries': [{'shot_id': 'S1', 'retain_entire_source': True}]})
            write(plan.parent / 'takes/f1/take.json', {'technical_qc': {'frames': 124},
                  'speech_screening': {'passed': False, 'transcript': 'unresolved words'}})
            with self.assertRaisesRegex(ValueError, 'speech problem'):
                chapter_timeline(root, plan, {'S1': 'f1'}, blueprint)
            timeline = chapter_timeline(root, plan, {'S1': 'f1'}, blueprint, first_cut=True)
            self.assertEqual(timeline['tracks'][0]['segments'][0]['source_out_frame'], 124)
            self.assertEqual(len(timeline['audio_screening_warnings']), 1)
            self.assertFalse(timeline['release_approved'])
            self.assertEqual(timeline['subtitles'][0]['timing_source'], 'authored_window_pending_speech_review')


if __name__ == '__main__':
    unittest.main()

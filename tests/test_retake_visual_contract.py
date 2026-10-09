from pathlib import Path
import tempfile
import unittest

from novel_h3.comfy import _retake_shot_contract
from novel_h3.director import h3_prompt
from novel_h3.project import write
from novel_h3.shot_package import _camera_execution
from novel_h3.storyboard_design import h3_instruction


class RetakeVisualContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write(self.root / 'bible/assets.json', {
            'characters': {
                '宋焘': {'id': 'character_song'},
                '听者': {'id': 'character_listener'},
            },
            'scenes': {'考殿': {'id': 'scene_hall'}},
            'props': {'寿籍': {'id': 'prop_register'}},
        })
        write(self.root / 'bible/voices.json', {
            '宋焘': {'asset_id': 'character_song'},
        })

    def test_dialogue_visual_retake_is_speaker_only_from_first_frame(self):
        shot = {
            'id': 'S-test', 'mode': 'ref2va', 'frames': 107, 'continuity': 'cut',
            'scene_id': 'scene_hall',
            'sequence_id': 'courtroom_response', 'beat_function': 'answer the official',
            'axis_id': 'conversation_axis',
            'screen_direction': 'reverse camera across the official-speaker conversation axis',
            'transition': 'reverse shot to the official',
            'references': [
                {'asset_id': 'scene_hall'},
                {'asset_id': 'character_song'},
                {'asset_id': 'character_listener'},
            ],
            'required_assets': ['scene_hall', 'character_song', 'character_listener'],
            'dialogue': [{'speaker': '宋焘', 'text': '一句白话。', 'start_frame': 6, 'end_frame': 48}],
            'action': '宋焘转向听者并回答。',
            'scene_continuity_contract': {'prompt': 'reverse shot on the official-speaker conversation axis'},
            'camera': {'size': 'close-up', 'movement': 'slow push-in',
                       'position': {'x': 1, 'y': 2, 'z': 3},
                       'look_at': {'x': 0, 'y': 0, 'z': 1},
                       'path': [{'frame': 0, 'position': {'x': 1, 'y': 2, 'z': 3},
                                 'look_at': {'x': 0, 'y': 0, 'z': 1}}]},
            'blocking_plan': {'expected_actor_count': 2, 'expected_body_count': 2,
                              'actors': [{'asset_id': 'character_song',
                                          'start_position': {'x': 1, 'y': 2, 'z': 0},
                                          'heading': 0}],
                              'offscreen_listeners': [{'asset_id': 'character_listener'}]},
        }
        note = '抽帧发现说话人过小且听者肩背入镜；改为单人近景，听者不入镜。'
        retake = _retake_shot_contract(shot, {'note': note}, self.root)
        self.assertEqual(retake['speaker_focus_mode'], 'speaker_only')
        self.assertEqual(retake['camera']['movement'], 'locked tripod')
        self.assertIn('frame zero', retake['action'])
        self.assertEqual(retake['blocking_plan']['expected_body_count'], 1)
        self.assertEqual(retake['blocking_plan']['offscreen_listeners'], [])
        self.assertAlmostEqual(retake['camera']['position']['x'], 1.0)
        self.assertAlmostEqual(retake['camera']['position']['y'], -0.8)
        self.assertAlmostEqual(retake['camera']['position']['z'], 1.65)
        self.assertEqual(retake['camera']['look_at'], {'x': 1.0, 'y': 2.0, 'z': 1.35})
        self.assertEqual([ref['asset_id'] for ref in retake['references']],
                         ['scene_hall', 'character_song'])
        self.assertTrue(retake['retake_visual_contract']['visible_body_count'] == 1)
        camera = _camera_execution(retake, [{'expected_instances': 1}], [])
        self.assertIn('frame zero is already a tight head-and-shoulders close-up',
                      camera['model_instruction'])
        self.assertNotIn('rule-of-thirds point with natural look room',
                         camera['model_instruction'])
        self.assertNotIn('听者', retake['action'])
        self.assertNotIn('听者', retake['action_beats'][0]['action'])
        instruction = h3_instruction(retake)
        self.assertIn('head-and-shoulders close-up', instruction)
        self.assertNotIn('conversation_axis', instruction)
        self.assertNotIn('reverse camera across the official-speaker conversation axis', instruction)
        self.assertEqual(retake['timeline'][0]['end_frame'], 107)
        prompt_shot = dict(retake)
        prompt_shot['references'] = [
            {'asset_id': 'character_song', 'lock': 'registered Song identity'},
            {'asset_id': 'scene_hall', 'lock': 'background only'},
        ]
        prompt_shot['asset_package'] = {
            'visual_assets': [
                {'asset_id': 'character_song', 'kind': 'character', 'subject_label': 'Subject 1'},
                {'asset_id': 'scene_hall', 'kind': 'scene', 'subject_label': 'Subject 2'},
            ],
            'camera_execution': {'model_instruction': camera['model_instruction']},
        }
        visual_prompt = h3_prompt(prompt_shot, 'cinematic style')
        self.assertNotIn('reverse shot on the official-speaker conversation axis', visual_prompt)
        self.assertEqual(shot['references'][2]['asset_id'], 'character_listener')

    def test_blank_paper_retake_removes_written_page_references(self):
        shot = {
            'id': 'S-paper', 'mode': 'ref2va', 'frames': 73, 'scene_id': 'scene_hall',
            'references': [
                {'asset_id': 'scene_hall'}, {'asset_id': 'character_song'},
                {'asset_id': 'prop_register'}, {'asset_id': 'prop_song_essay'},
            ],
            'required_assets': ['scene_hall', 'character_song', 'prop_register', 'prop_song_essay'],
            'dialogue': [], 'action': '两个人交卷。',
        }
        write(self.root / 'bible/assets.json', {
            'characters': {'宋焘': {'id': 'character_song'}},
            'scenes': {'考殿': {'id': 'scene_hall'}},
            'props': {'宋焘试文': {'id': 'prop_song_essay'}, '寿籍': {'id': 'prop_register'}},
        })
        retake = _retake_shot_contract(
            shot, {'note': '纸面完全空白，所有笔迹都不得出现。'}, self.root)
        self.assertEqual(retake['retake_visual_contract']['mode'], 'blank_paper')
        self.assertNotIn('prop_song_essay', [ref['asset_id'] for ref in retake['references']])
        self.assertIn('prop_register', [ref['asset_id'] for ref in retake['references']])

    def test_single_speaker_retake_keeps_required_register_in_frame(self):
        shot = {
            'id': 'S-prop', 'mode': 'ref2va', 'frames': 107, 'continuity': 'cut',
            'scene_id': 'scene_hall',
            'references': [
                {'asset_id': 'scene_hall'}, {'asset_id': 'character_song'},
                {'asset_id': 'prop_register'},
            ],
            'required_assets': ['scene_hall', 'character_song', 'prop_register'],
            'dialogue': [{'speaker': '宋焘', 'text': '她还能活九年。',
                          'start_frame': 6, 'end_frame': 55}],
            'action': '宋焘手持寿籍报出寿数。',
            'camera': {'size': 'medium shot', 'movement': 'slow push-in'},
            'blocking_plan': {'expected_actor_count': 1, 'expected_body_count': 1,
                              'actors': [{'asset_id': 'character_song',
                                          'start_position': {'x': 1, 'y': 2, 'z': 0},
                                          'heading': 0}]},
        }
        note = ('抽帧复核发现 S016虽已解决远景和红衣人物，但长须吏手中的寿籍被裁出画面，缺少“持册报寿数”的关键动作。'
                '重拍为单人近景，听者不入镜；采用胸口以上中近景：从第0帧开始，长须吏面部与口型保持清晰，双手持同一本寿籍并让册子持续显示在画面下部；'
                '册页完全空白、不可读。听者和其他人物全程在镜外，不得出现肩背、第二张脸、红衣人物、反射、空殿开场、远景、反打、切镜或字幕。')
        retake = _retake_shot_contract(shot, {'note': note}, self.root)
        self.assertEqual(retake['speaker_focus_mode'], 'speaker_only')
        self.assertTrue(retake['speaker_frame_prop'])
        self.assertIn('both hands', retake['action'])
        self.assertIn('prop_register', [ref['asset_id'] for ref in retake['references']])
        self.assertIn('medium close-up', retake['camera']['size'])
        camera = _camera_execution(retake, [{'expected_instances': 1}], [])
        self.assertIn('both hands hold the same blank longevity register',
                      camera['model_instruction'])
        instruction = h3_instruction(retake)
        self.assertIn('longevity register', instruction)
        self.assertIn('exact visible registered body count=1', instruction)

    def test_exact_cast_blank_paper_retake_blocks_foreground_extras(self):
        write(self.root / 'bible/assets.json', {
            'characters': {
                '宋焘': {'id': 'character_song'},
                '张生': {'id': 'character_zhang'},
                '监考者': {'id': 'character_examiner'},
            },
            'scenes': {'考殿': {'id': 'scene_hall'}},
            'props': {
                '考桌': {'id': 'prop_desks'},
                '宋焘试文': {'id': 'prop_song_essay'},
            },
        })
        shot = {
            'id': 'S-paper-pair', 'mode': 'ref2va', 'frames': 192,
            'continuity': 'cut', 'scene_id': 'scene_hall', 'dialogue': [],
            'references': [
                {'asset_id': 'scene_hall'}, {'asset_id': 'character_song'},
                {'asset_id': 'character_zhang'}, {'asset_id': 'character_examiner'},
                {'asset_id': 'prop_desks'}, {'asset_id': 'prop_song_essay'},
            ],
            'required_assets': ['scene_hall', 'character_song', 'character_zhang',
                                'character_examiner', 'prop_desks', 'prop_song_essay'],
            'action': '宋焘举起试文交给监考者。',
            'timeline': [
                {'start_frame': 0, 'end_frame': 96, 'description': '继续写字。'},
                {'start_frame': 96, 'end_frame': 192, 'description': '举起试文准备呈交。'},
            ],
            'camera': {'size': 'wide', 'lens_mm': 65, 'movement': 'slow push-in',
                       'position': {'x': -6.3, 'y': -8.5, 'z': 1.65},
                       'look_at': {'x': 0, 'y': -1, 'z': 1.3}},
            'blocking_plan': {
                'expected_actor_count': 2, 'expected_body_count': 2,
                'actors': [
                    {'asset_id': 'character_song', 'mark': '宋焘; seated'},
                    {'asset_id': 'character_zhang', 'mark': '张生; seated'},
                ],
                'offscreen_listeners': [],
            },
        }
        note = '画面只能出现宋焘和张生，不得出现第三人；两份试文纸面必须完全空白，禁止有人上前接收。'
        retake = _retake_shot_contract(shot, {'note': note}, self.root)
        self.assertEqual(retake['retake_visual_contract']['mode'], 'exact_cast')
        self.assertEqual(retake['retake_visual_contract']['visible_body_count'], 2)
        self.assertTrue(retake['retake_visual_contract']['blank_paper'])
        self.assertEqual(retake['blocking_plan']['expected_body_count'], 2)
        self.assertEqual([ref['asset_id'] for ref in retake['references']],
                         ['scene_hall', 'character_song', 'character_zhang', 'prop_desks'])
        self.assertIn('不得有第三个人', retake['action'])
        self.assertNotIn('交给监考者', retake['action'])
        self.assertTrue(all(t['end_frame'] > t['start_frame'] for t in retake['timeline']))
        prompt_shot = dict(retake)
        prompt_shot['references'] = [
            {'asset_id': 'character_song', 'lock': 'registered Song identity'},
            {'asset_id': 'character_zhang', 'lock': 'registered Zhang identity'},
        ]
        prompt_shot['asset_package'] = {'visual_assets': [
            {'asset_id': 'character_song', 'kind': 'character', 'subject_label': 'Subject 2'},
            {'asset_id': 'character_zhang', 'kind': 'character', 'subject_label': 'Subject 3'},
        ]}
        prompt = h3_prompt(prompt_shot, 'cinematic style')
        self.assertIn('EXACT_REGISTERED_CAST_RETAKE', prompt)
        self.assertIn('only the registered visual subjects Subject 2, Subject 3', prompt)
        self.assertIn('BLANK_PAPER_RETAKE', prompt)
        self.assertNotIn('reverse shot on the official-speaker conversation axis', prompt)


if __name__ == '__main__':
    unittest.main()

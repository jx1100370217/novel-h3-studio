import unittest
from pathlib import Path
import tempfile

from novel_h3.comfy import asset_for, register_h3_video_frame, _retake_shot_contract
from novel_h3.director import h3_prompt
from novel_h3.project import file_hash, write, update_state
from novel_h3.voices import bindings


class H3VideoFrameAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.video = self.root / 'renders' / 'source.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'checked H3 video')
        self.frame = self.root / 'analysis' / 'closeup.png'
        self.frame.parent.mkdir(parents=True)
        self.frame.write_bytes(b'extracted H3 frame')
        write(self.root / 'state.json', {'assets': {}, 'takes': {
            't-source': {
                'status': 'rendered', 'video': 'renders/source.mp4',
                'video_sha256': file_hash(self.video),
                'qc': {'passed': True, 'frames': 48},
            },
        }})
        write(self.root / 'bible/assets.json', {
            'characters': {'宋焘': {'id': 'character_song'}},
            'scenes': {'考殿': {'id': 'scene_hall'}},
            'props': {'考桌': {'id': 'prop_desk'}},
        })
        write(self.root / 'bible/voices.json', {'宋焘': {'asset_id': 'character_song'}})

    def test_registers_frame_with_source_take_provenance(self):
        result = register_h3_video_frame(
            self.root, 'keyframe_s013', 't-source', 24,
            'analysis/closeup.png', 'Checked actor close-up extracted for H3 first-frame conditioning.')
        self.assertFalse(result['reused'])
        path, sha256 = asset_for(self.root, 'keyframe_s013')
        self.assertEqual(path, self.frame)
        self.assertEqual(sha256, file_hash(self.frame))

    def test_rejects_frame_if_source_take_hash_changes(self):
        register_h3_video_frame(
            self.root, 'keyframe_s013', 't-source', 24,
            'analysis/closeup.png', 'Checked actor close-up extracted for H3 first-frame conditioning.')
        update_state(self.root, lambda state: state['takes']['t-source'].__setitem__(
            'video_sha256', '0' * 64))
        with self.assertRaisesRegex(ValueError, '来源镜头或帧哈希不匹配'):
            asset_for(self.root, 'keyframe_s013')

    def test_speaker_retake_uses_registered_video_frame_as_fl2va_first_frame(self):
        register_h3_video_frame(
            self.root, 'keyframe_s013', 't-source', 24,
            'analysis/closeup.png', 'Checked H3 close-up keyframe.')
        shot = {
            'id': 'S013', 'mode': 'ref2va', 'continuity': 'cut', 'frames': 107,
            'scene_id': 'scene_hall',
            'references': [{'asset_id': 'scene_hall'}, {'asset_id': 'character_song'}],
            'required_assets': ['scene_hall', 'character_song'],
            'dialogue': [{'speaker': '宋焘', 'text': '一句白话。', 'start_frame': 6, 'end_frame': 48}],
            'action': '原始对答动作。',
            'scene_continuity_contract': {'prompt': 'The speaker walks away to the dais with the clerk.'},
            'camera': {'size': 'medium', 'lens_mm': 50, 'movement': 'static'},
            'blocking_plan': {'actors': [{'asset_id': 'character_song',
                                          'mark': '宋焘; standing',
                                          'start_position': {'x': 1, 'y': 2, 'z': 0},
                                          'heading': 0}]},
        }
        retake = _retake_shot_contract(shot, {
            'note': '改为单人近景从第0帧开始，听者不入镜。',
            'first_frame_asset_id': 'keyframe_s013',
        }, self.root)
        self.assertEqual(retake['mode'], 'fl2va')
        self.assertEqual(retake['first_frame'], 'keyframe_s013')
        self.assertEqual(retake['last_frame'], 'keyframe_s013')
        self.assertNotIn('原始对答动作', retake['action'])
        retake['asset_package'] = {
            'visual_assets': [{'asset_id': 'character_song', 'kind': 'character',
                               'subject_label': 'Subject 1'}],
            'audio_bindings': [{'speaker': '宋焘', 'audio_label': 'Audio 1'}],
            'identity_bindings': [{'asset_id': 'character_song', 'role': 'speaker'}],
            'interaction_contract': {
                'speakers': ['宋焘'],
                'speaker_visual_bindings': [{'asset_id': 'character_song', 'audio_label': 'Audio 1'}],
                'dialogue_event_bindings': [{'text': '一句白话。'}],
            },
            'camera_execution': {'model_instruction': 'tight static close-up'},
            'character_identity_lock': {'present_time_only': True},
        }
        prompt = h3_prompt(retake, 'period cinema')
        self.assertNotIn('<d>[Chinese] 一句白话。</d>', prompt)
        self.assertNotIn('一句白话。', prompt)
        self.assertNotIn('walks away to the dais', prompt)
        self.assertIn('AUDIO_MODE=DIEGETIC_EFFECTS_ONLY', prompt)
        self.assertIn('MUSIC_MODE=OFF', prompt)

    def test_fl2va_dialogue_is_allowed_only_with_local_postdub(self):
        audio = self.root / 'voices' / 'song.wav'
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b'voice reference')
        write(self.root / 'config.json', {'speech_policy': {
            'dialogue_audio_source': 'qwen3_tts_local_postdub',
        }})
        write(self.root / 'bible/voices.json', {'宋焘': {
            'asset_id': 'character_song', 'path': 'voices/song.wav',
            'sha256': file_hash(audio), 'approved': True,
        }})
        shot = {'mode': 'fl2va', 'references': [{'asset_id': 'character_song'}],
                'dialogue': [{'speaker': '宋焘', 'text': '一句白话。'}]}
        self.assertEqual(bindings(self.root, shot)[0]['speaker'], '宋焘')
        write(self.root / 'config.json', {'speech_policy': {
            'dialogue_audio_source': 'h3_reference',
        }})
        with self.assertRaisesRegex(ValueError, '必须使用支持声音参考的 Ref2VA'):
            bindings(self.root, shot)


if __name__ == '__main__':
    unittest.main()

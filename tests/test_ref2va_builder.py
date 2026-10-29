import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from novel_h3.ref2va_builder import (
    AnchorImage, CastMember, LockedShot, SceneRef, ShotLine, VideoRef, VoiceBinding, build_spec,
)
from novel_h3.ref2va import population_text
from novel_h3.voice_refs import VoiceRef


class Ref2VABuilderTests(unittest.TestCase):
    def shot(self, voices):
        return LockedShot(
            shot_id='A13', title='Two candidates', frames=158, seed=1,
            visual_core='[Shot 1] Song Tao and Zhang Sheng stand before the hall.',
            soundscape='Stone hall reverb and robes.',
            cast=(
                CastMember('songtao', 'Song Tao', 'older man with a short beard and navy robe', 'projects/p/song.png', x=-1, y=1),
                CastMember('zhang_sheng', 'Zhang Sheng', 'younger clean-shaven man in a pale blue robe', 'projects/p/zhang.png', x=1, y=1),
            ),
            scene=SceneRef('hall', 'the hall', 'red columns and stone floor', 'projects/p/hall.png'),
            voices=voices,
            lines=(
                ShotLine('zhang', '兄台也是来应考的？', 1.9, 'zhang_sheng'),
                ShotLine('songtao', '长山宋焘。', 3.7, 'songtao'),
            ),
        )

    def test_builder_binds_each_speaker_to_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (
                VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),
                VoiceBinding('songtao', VoiceRef('songtao', 'voice_songtao', root / 'song.wav'), 'songtao'),
            )
            spec = build_spec(self.shot(voices))
            self.assertEqual(len(spec['voices']), 2)
            # Audio references follow subject/cast order so H3 cannot pair the
            # first audio with the first subject while a later cast member speaks.
            self.assertEqual([v['subject'] for v in spec['voices']], ['<Subject 1>', '<Subject 2>'])
            self.assertEqual([v['audio'] for v in spec['voices']], ['<Audio 1>', '<Audio 2>'])
            self.assertIn('<Subject 2> (S1) speaks with <Audio 2>', spec['sections']['detailed_description'])
            self.assertIn('<Subject 1> (S2) speaks with <Audio 1>', spec['sections']['detailed_description'])
            self.assertIn('<Audio 1> is the voice reference for <Subject 1> (S2), Song Tao',
                          spec['sections']['subject_definitions'])
            self.assertIn('<Audio 2> is the voice reference for <Subject 2> (S1), Zhang Sheng',
                          spec['sections']['subject_definitions'])

    def test_builder_rejects_missing_speaker_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),)
            with self.assertRaisesRegex(ValueError, 'no voice reference'):
                build_spec(self.shot(voices))

    def test_builder_binds_previous_video_as_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (
                VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),
                VoiceBinding('songtao', VoiceRef('songtao', 'voice_songtao', root / 'song.wav'), 'songtao'),
            )
            shot = replace(self.shot(voices), videos=(
                VideoRef('prev_A12', 'projects/p/takes_v5/A12/native.mp4',
                         'the final 3 seconds of shot A12, the immediately preceding shot in the same scene'),
            ))
            spec = build_spec(shot)
            self.assertEqual(spec['videos'][0]['video'], '<Video 1>')
            self.assertIn('<Video 1> is the final 3 seconds', spec['sections']['subject_definitions'])
            self.assertIn('<Video 1> (appears in [Shot 1]): partially_preserved', spec['sections']['retention_analysis'])
            self.assertIn('Continuity source: the target video opens from the exact ending state of <Video 1>',
                          spec['sections']['detailed_description'])
            self.assertTrue(spec['sections']['summary'].startswith(
                '[video continuation + reference generation + audio reference]'))
            self.assertIn('Costume continuity lock', spec['sections']['detailed_description'])
            self.assertIn('Screen-direction lock', spec['sections']['detailed_description'])

    def test_builder_adds_anatomy_and_desk_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (
                VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),
                VoiceBinding('songtao', VoiceRef('songtao', 'voice_songtao', root / 'song.wav'), 'songtao'),
            )
            shot = replace(
                self.shot(voices),
                visual_core='[Shot 1] Guandi sits behind the high desk; his hand rests on the paper.',
            )
            detail = build_spec(shot)['sections']['detailed_description']
            self.assertIn('Hand anatomy lock', detail)
            self.assertIn('Lower-body occlusion lock', detail)
            self.assertIn('no legs, knees, feet, stool or green cloth', detail)

    def test_builder_binds_keyframe_anchor_for_sitting_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (
                VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),
                VoiceBinding('songtao', VoiceRef('songtao', 'voice_songtao', root / 'song.wav'), 'songtao'),
            )
            anchor = AnchorImage('A06_firstframe', 'projects/p/firstframe.jpg',
                                 'Song Tao already sitting upright on the edge of the bed with the summons.')
            spec = build_spec(replace(self.shot(voices), anchor_image=anchor))
            self.assertIn('<Picture 4>', spec['sections']['subject_definitions'])
            self.assertIn('<Subject 4> (appears in [Shot 1]): fully_preserved',
                          spec['sections']['retention_analysis'])
            self.assertIn('The first frame of the target video is exactly <Picture 4>',
                          spec['sections']['detailed_description'])
            self.assertTrue(spec['sections']['summary'].startswith(
                '[keyframe completion + reference generation + audio reference]'))

    def test_population_contract_forbids_reference_duplicates(self):
        text = population_text([
            {'kind': 'character', 'subject': '<Subject 1>', 'instances': 1},
            {'kind': 'character', 'subject': '<Subject 2>', 'instances': 1},
            {'kind': 'scene', 'subject': '<Subject 3>'},
        ])
        self.assertIn('Visible population: exactly 2 people', text)
        self.assertIn('identity reference for that named person only', text)
        self.assertIn('No named person is duplicated', text)

    def test_builder_embeds_population_lock_in_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (
                VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),
                VoiceBinding('songtao', VoiceRef('songtao', 'voice_songtao', root / 'song.wav'), 'songtao'),
            )
            detail = build_spec(self.shot(voices))['sections']['detailed_description']
            self.assertIn('Visible population: exactly 2 people', detail)
            self.assertIn('identity reference for that named person only', detail)
            self.assertIn('No named person is duplicated', detail)


if __name__ == '__main__':
    unittest.main()

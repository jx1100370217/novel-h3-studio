import tempfile
import unittest
from pathlib import Path

from novel_h3.ref2va_builder import CastMember, LockedShot, SceneRef, ShotLine, VoiceBinding, build_spec
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
            self.assertIn('<Audio 1>', spec['sections']['detailed_description'])
            self.assertIn('<Subject 2> (S1) speaks with <Audio 1>', spec['sections']['detailed_description'])
            self.assertIn('<Subject 1> (S2) speaks with <Audio 2>', spec['sections']['detailed_description'])

    def test_builder_rejects_missing_speaker_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voices = (VoiceBinding('zhang', VoiceRef('zhang', 'voice_zhang', root / 'zhang.wav'), 'zhang_sheng'),)
            with self.assertRaisesRegex(ValueError, 'no voice reference'):
                build_spec(self.shot(voices))


if __name__ == '__main__':
    unittest.main()

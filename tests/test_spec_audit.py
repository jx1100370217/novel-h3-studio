import json
import tempfile
import unittest
from pathlib import Path

from novel_h3.fastvideo_batch import load_spec
from novel_h3.spec_audit import audit_spec


def spec(voices, definitions=None, spoken=None):
    visuals = [
        {'asset_id': 'xu', 'subject': '<Subject 1>', 'kind': 'character'},
        {'asset_id': 'wang', 'subject': '<Subject 2>', 'kind': 'character'},
    ]
    if definitions is None:
        definitions = '\n'.join(
            (f"{voice['audio']} is the voice reference for {voice['subject']} (S{i}), speaker."
             if voice.get('subject') else
             f"{voice['audio']} is the off-screen voice for {voice.get('role', '?')}.")
            for i, voice in enumerate(voices, 1))
    return {
        'voices': voices,
        'visuals': visuals,
        'spoken_lines': spoken or [],
        'sections': {'subject_definitions': definitions},
    }


class SpecAuditTests(unittest.TestCase):
    def test_cast_ordered_binding_passes(self):
        data = spec([
            {'audio': '<Audio 1>', 'subject': '<Subject 1>', 'role': 'xu'},
            {'audio': '<Audio 2>', 'subject': '<Subject 2>', 'role': 'wang'},
        ])
        self.assertEqual(audit_spec(data), [])

    def test_audio_label_must_match_payload_order(self):
        data = spec([
            {'audio': '<Audio 2>', 'subject': '<Subject 2>', 'role': 'wang'},
        ])
        self.assertTrue(any('audio order' in issue for issue in audit_spec(data)))

    def test_later_subject_must_not_take_an_earlier_audio_slot(self):
        data = spec([
            {'audio': '<Audio 1>', 'subject': '<Subject 2>', 'role': 'wang'},
        ])
        self.assertTrue(any('wrong voice' in issue for issue in audit_spec(data)))

    def test_definition_must_name_the_bound_subject(self):
        data = spec(
            [{'audio': '<Audio 1>', 'subject': '<Subject 1>', 'role': 'xu'}],
            definitions='<Audio 1> is the voice reference for <Subject 2> (S1), Wang.',
        )
        self.assertTrue(any('does not name' in issue for issue in audit_spec(data)))

    def test_offscreen_voice_before_visible_speaker_is_allowed(self):
        data = spec([
            {'audio': '<Audio 1>', 'subject': None, 'role': 'villager'},
            {'audio': '<Audio 2>', 'subject': '<Subject 1>', 'role': 'xu'},
        ])
        self.assertEqual(audit_spec(data), [])

    def test_spoken_line_needs_a_voice(self):
        data = spec(
            [{'audio': '<Audio 1>', 'subject': '<Subject 1>', 'role': 'xu'}],
            spoken=[{'speaker': 'wang', 'text': '坐。', 'speaker_subject': '<Subject 2>'}],
        )
        self.assertTrue(any('no matching voice' in issue for issue in audit_spec(data)))

    def test_load_spec_rejects_a_swapped_spec_before_render(self):
        data = spec([
            {'audio': '<Audio 1>', 'subject': '<Subject 2>', 'role': 'wang',
             'path': 'missing.wav'},
        ])
        data.update({'shot': 'S02A', 'seed': 1, 'frames': 22})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'S02A.json'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'voice binding audit failed'):
                load_spec(path)


if __name__ == '__main__':
    unittest.main()

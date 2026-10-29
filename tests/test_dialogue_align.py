import unittest

from novel_h3.dialogue_audit import align_words


class AlignWordsTests(unittest.TestCase):
    def test_line_span_starts_at_its_first_word(self):
        # "姓王，没字。叫我六郎。" is split into three Whisper pieces; the cue
        # must start at 姓王, not at the last piece.
        words = [
            {'start': 0.98, 'end': 2.18, 'text': '你叫什么'},
            {'start': 2.18, 'end': 4.0, 'text': '姓王'},
            {'start': 4.0, 'end': 8.91, 'text': '没字'},
            {'start': 8.91, 'end': 12.31, 'text': '叫我六郎'},
        ]
        lines = [{'speaker': 'xu', 'text': '你叫什么？'},
                 {'speaker': 'wang', 'text': '姓王，没字。叫我六郎。'}]
        cues = align_words(lines, words, 13.0)
        self.assertAlmostEqual(cues[0][0], 0.93)
        self.assertAlmostEqual(cues[1][0], 2.13)
        self.assertGreater(cues[1][1], 12.0)

    def test_short_span_does_not_drop_the_line_onset(self):
        # ASR drops/mishears the first characters; the cue still opens on the
        # earliest word of the line instead of jumping to the clean tail.
        words = [
            {'start': 8.48, 'end': 9.0, 'text': '做'},
            {'start': 10.02, 'end': 11.38, 'text': '和尚规矩'},
            {'start': 12.24, 'end': 13.26, 'text': '见者有分'},
        ]
        lines = [{'speaker': 'xu', 'text': '坐。河上规矩，见者有份。'}]
        cues = align_words(lines, words, 13.0)
        self.assertAlmostEqual(cues[0][0], 8.43)
        self.assertGreater(cues[0][1], 12.5)

    def test_no_speech_falls_back_to_none(self):
        self.assertEqual(align_words([{'speaker': 'a', 'text': '啊？'}], [], 5.0), [None])


if __name__ == '__main__':
    unittest.main()

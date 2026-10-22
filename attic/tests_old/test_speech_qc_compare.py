import unittest

from novel_h3.speech_qc import compare


class SpeechComparisonTests(unittest.TestCase):
    def test_traditional_dialogue_spelling_does_not_force_a_retake(self):
        self.assertTrue(compare('先歇着，别急着起来。', '先歇著，別急著起來。')['passed'])
        self.assertTrue(compare('我姓张，长山人。送你一首诗，留个念想。',
                                '我姓張，長山人。送你一首詩，留個念想。')['passed'])
        self.assertFalse(compare('没有存心害人。', '存心害人。')['passed'])

    def test_normalizes_only_script_variants_and_known_homophones(self):
        self.assertTrue(compare('你本来应该马上去上任。', '你本來應該馬上去上任')['passed'])
        self.assertTrue(compare('让张生替你当九年城隍。', '让张生替你当九年城皇')['passed'])
        self.assertTrue(compare('九年期限一到，我再召你回来。',
                                '九年期限一到我再招你回来')['passed'])
        self.assertFalse(compare('你本来应该马上去上任。', '你本来不该马上去上任')['passed'])
        self.assertFalse(compare('九年期限一到，我再召你回来。', '九年期限一到我再招人回来')['passed'])

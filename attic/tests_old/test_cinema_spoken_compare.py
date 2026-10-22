import unittest

from novel_h3.v2.speech import compare_spoken


class CinemaSpokenCompareTests(unittest.TestCase):
    def test_equal_tone_syllables_allow_only_spelling_differences(self):
        for expected, heard in [('那不是关圣帝君吗？', '那不是官圣帝君吗？'),
                                ('你这是邀功。', '你这是妖宫。'),
                                ('我是长山的张生。', '我是常山的张生。'),
                                ('宋焘', '宋涛')]:
            with self.subTest(expected=expected, heard=heard):
                result = compare_spoken(expected, heard)
                self.assertTrue(result['passed'])
                self.assertTrue(result['phonetic_equivalent'])
                self.assertEqual(result['match_type'], 'phonetic_equivalent')
                self.assertGreater(result['edit_distance'], 0)
                self.assertEqual(result['phonetic_comparison']['edit_distance'], 0)
                self.assertEqual(result['expected'], expected)
                self.assertEqual(result['transcript'], heard)
                self.assertFalse(result['human_listened'])
                self.assertFalse(result['release_approved'])
                print(f"{expected} / {heard}: characters={result['edit_distance']}, "
                      f"tone_syllables={result['phonetic_comparison']['edit_distance']}, "
                      f"match={result['match_type']}")

    def test_tone_or_pronunciation_changes_are_rejected(self):
        for expected, heard in [('您', '你'), ('任职', '任之'), ('宋焘', '送他'),
                                ('宋焘', '宋道'), ('长山', '掌山'), ('可以', '可疑')]:
            with self.subTest(expected=expected, heard=heard):
                result = compare_spoken(expected, heard)
                self.assertFalse(result['passed'])
                self.assertGreater(result['phonetic_comparison']['edit_distance'], 0)
                print(f"{expected} / {heard}: characters={result['edit_distance']}, "
                      f"tone_syllables={result['phonetic_comparison']['edit_distance']}, rejected")

    def test_omissions_insertions_negation_and_repetition_never_get_a_tolerance(self):
        for expected, heard in [('我不去', '我去'), ('请您来', '请您您来'),
                                ('她还能活九年', '她还能活年'), ('宋焘', '宋涛啊')]:
            with self.subTest(expected=expected, heard=heard):
                result = compare_spoken(expected, heard)
                self.assertFalse(result['passed'])
                self.assertFalse(result['phonetic_comparison']['equal_character_and_syllable_counts'])
                self.assertEqual(result['phonetic_comparison']['allowed_distance'], 0)

    def test_legacy_zhao_sentence_exception_cannot_pass(self):
        expected, heard = '九年期限一到，我再召你回来。', '九年期限一到，我再招你回来。'
        result = compare_spoken(expected, heard)
        self.assertTrue(result['legacy_orthographic_comparison']['passed'])
        self.assertTrue(result['ignored_legacy_sentence_aliases'])
        self.assertEqual(result['edit_distance'], 1)
        self.assertEqual(result['phonetic_comparison']['edit_distance'], 1)
        self.assertFalse(result['passed'])
        self.assertIn('zhao4', result['phonetic_comparison']['expected_syllables'])
        self.assertIn('zhao1', result['phonetic_comparison']['transcript_syllables'])

    def test_existing_orthography_normalization_and_raw_transcript_are_preserved(self):
        result = compare_spoken('请给她养老送终。', '請給他養老送終')
        self.assertTrue(result['passed'])
        self.assertEqual(result['match_type'], 'orthographic_normalized')
        self.assertGreater(result['raw_character_edit_distance'], 0)
        self.assertEqual(result['edit_distance'], 0)
        self.assertEqual(result['transcript'], '請給他養老送終')
        self.assertFalse(result['source_text_modified'])

    def test_readings_are_local_and_do_not_enable_arbitrary_heteronyms(self):
        from pypinyin import lazy_pinyin, Style
        before = lazy_pinyin('长山宋焘', style=Style.TONE3)
        result = compare_spoken('长山宋焘', '常山宋涛')
        self.assertEqual(result['phonetic_comparison']['expected_syllables'], ['chang2', 'shan1', 'song4', 'tao1'])
        self.assertFalse(result['phonetic_comparison']['heteronym_matching'])
        self.assertEqual(lazy_pinyin('长山宋焘', style=Style.TONE3), before)

    def test_uncommon_inserted_characters_are_not_silently_discarded(self):
        result = compare_spoken('你好', '你好𠮷')
        self.assertFalse(result['passed'])
        self.assertEqual(result['edit_distance'], 1)
        self.assertFalse(result['phonetic_comparison']['equal_character_and_syllable_counts'])


if __name__ == '__main__':
    unittest.main()

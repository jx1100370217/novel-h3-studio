import unittest

from novel_h3.take_audit import dialogue_text, normalise, similarity


class DialogueTextTests(unittest.TestCase):
    def test_strips_speaker_and_stage_direction(self):
        shot = {'dialogue': '许某：河里各位，天冷了。\n王六郎（低声）：老丈，一个人喝酒？'}
        self.assertEqual(dialogue_text(shot), '河里各位，天冷了。老丈，一个人喝酒？')

    def test_ignores_lines_without_a_speaker(self):
        self.assertEqual(dialogue_text({'dialogue': '（无对白）'}), '')


class SimilarityTests(unittest.TestCase):
    def test_normalise_keeps_only_cjk(self):
        self.assertEqual(normalise('许某：河里各位，天冷了！'), '许某河里各位天冷了')
        self.assertEqual(normalise('河里各位，天冷了！'), '河里各位天冷了')

    def test_similarity_tolerates_asr_mishearing(self):
        authored = normalise('河里各位天冷了喝一口')
        heard = normalise('合理各位天冷了喝一口')
        self.assertGreater(similarity(authored, heard), 0.5)

    def test_empty_side_scores_zero(self):
        self.assertEqual(similarity('', '天冷'), 0.0)


if __name__ == '__main__':
    unittest.main()

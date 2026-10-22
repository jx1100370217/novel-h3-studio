import unittest
from novel_h3.audio_cleanup import speech_windows, timing_alignment, lip_sync_overlap

class CleanupTests(unittest.TestCase):
    def test_padding_and_merge(self):
        self.assertEqual(speech_windows([{'text':'a','timestamp':(1,2)},{'text':'b','timestamp':(2.1,3)}],5),[[.75,3.25]])
    def test_incomplete_boundary_rejected(self):
        with self.assertRaises(ValueError):
            speech_windows([{'text':'a','timestamp':(1,None)}],5)
    def test_does_not_use_assigned_dialogue_times(self):
        self.assertEqual(speech_windows([{'text':'a','timestamp':(2,4)}],5),[[1.75,4.25]])

    def test_timing_alignment_allows_safe_cleanup(self):
        result = timing_alignment([[1.05, 2.95]], [{'start_frame': 24, 'end_frame': 72}])
        self.assertEqual(result['status'], 'passed')

    def test_timing_alignment_blocks_audio_only_cleanup_when_shifted(self):
        result = timing_alignment([[2.0, 3.0]], [{'start_frame': 24, 'end_frame': 48}])
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('嘴动无声', result['reason'])

    def test_lip_sync_overlap_blocks_audio_only_cleanup_inside_dialogue(self):
        result = lip_sync_overlap([[2.0, 3.0]], [{'start_frame': 24, 'end_frame': 96}])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['unsafe_windows'], [[2.0, 3.0]])
        self.assertIn('嘴动无声', result['reason'])

    def test_lip_sync_overlap_allows_audio_outside_dialogue(self):
        result = lip_sync_overlap([[0.0, .5]], [{'start_frame': 24, 'end_frame': 96}])
        self.assertEqual(result['status'], 'passed')

class FailedSpeechCleanupTests(unittest.TestCase):
    def test_extra_speech_outside_complete_line_can_be_removed(self):
        from novel_h3.audio_cleanup import matching_dialogue_chunks
        chunks=[{'text':'嗯嗯'}, {'text':'这里是'}, {'text':'天外天。'}, {'text':'谢谢观看'}]
        self.assertEqual(matching_dialogue_chunks(chunks,'这里是天外天。'),chunks[1:3])

    def test_missing_words_cannot_be_repaired(self):
        from novel_h3.audio_cleanup import matching_dialogue_chunks
        self.assertEqual(matching_dialogue_chunks([{'text':'这里天外天'}],'这里是天外天'),[])

    def test_does_not_splice_around_inserted_wrong_words(self):
        from novel_h3.audio_cleanup import matching_dialogue_chunks
        self.assertEqual(matching_dialogue_chunks([{'text':'这里是'},{'text':'错误'},{'text':'天外天'}],'这里是天外天'),[])

    def test_repetition_keeps_one_complete_copy(self):
        from novel_h3.audio_cleanup import matching_dialogue_chunks
        chunks=[{'text':'这里是天外天','timestamp':(0,2)},{'text':'这里是天外天','timestamp':(3,5)}]
        self.assertEqual(matching_dialogue_chunks(chunks,'这里是天外天'),chunks[:1])

    def test_matching_span_exposes_extra_speech_for_lip_sync_gate(self):
        from novel_h3.audio_cleanup import matching_dialogue_span
        chunks=[{'text':'嗯嗯','timestamp':(0,0.4)},
                {'text':'你是谁','timestamp':(0.5,1.4)},
                {'text':'别走','timestamp':(1.5,2.0)}]
        self.assertEqual(matching_dialogue_span(chunks,'你是谁'),(1,2))

    def test_near_match_is_only_a_cleanup_safety_stop(self):
        from novel_h3.audio_cleanup import likely_dialogue_span
        chunks=[{'text':'我们都是混沌所生光束所幻化我只有创造到的力量',
                 'timestamp':(0,4.0)}]
        probable=likely_dialogue_span(
            chunks, '我们都是混沌所生光所幻化我只有创造的力量')
        self.assertIsNotNone(probable)
        self.assertGreaterEqual(probable['similarity'], probable['threshold'])

    def test_unrelated_voice_is_not_protected_by_near_match(self):
        from novel_h3.audio_cleanup import likely_dialogue_span
        chunks=[{'text':'请不吝点赞订阅转发打赏支持明镜与点点栏目',
                 'timestamp':(0,4.0)}]
        self.assertIsNone(likely_dialogue_span(
            chunks, '我们都是混沌所生光所幻化我只有创造的力量'))

    def test_near_match_extracts_inserted_voice_chunks(self):
        from novel_h3.audio_cleanup import aligned_unbound_chunks
        chunks = [
            {'text': '永无休止的轮回', 'timestamp': (0.0, 1.38)},
            {'text': '已经证明你已经看清', 'timestamp': (1.62, 3.38)},
            {'text': '竟且永远的无极下', 'timestamp': (3.9, 5.4)},
            {'text': '弯字激起了', 'timestamp': (5.84, 6.84)},
            {'text': '突那伤面撕着点着', 'timestamp': (7.14, 8.62)},
            {'text': '你彻底地破灭', 'timestamp': (8.94, 10.1)},
            {'text': '又成为了混沌出生时的样子', 'timestamp': (10.36, 12.42)},
            {'text': '不再受无极的轮回', 'timestamp': (12.68, 14.16)},
        ]
        expected = '永无休止的轮回已经证明你已经看清，并且永远的无极了，你彻底的破灭，又成为了混沌初生时的样子，不再受无极的轮回。'
        extras = aligned_unbound_chunks(chunks, expected)
        self.assertEqual([item['text'] for item in extras], ['弯字激起了', '突那伤面撕着点着'])

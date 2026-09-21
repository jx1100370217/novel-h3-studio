import copy
import unittest
from novel_h3.timing import (retime, semantic_chunks, dialogue_duration_seconds,
                              retime_content_plan, split_dialogue, speech_seconds,
                              MAX_CONTINUOUS_SPEECH_SECONDS)

class TimingTests(unittest.TestCase):
    def shot(self,text):
        return dict(id='timing',frames=124,continuity='cut',dialogue=[dict(text=text,speaker='旁白',kind='voiceover',start_frame=6,end_frame=118)],timeline=[dict(start_frame=i,end_frame=min(i+24,124),description='drifting cloud') for i in range(0,124,24)])

    def test_long_dialogue_gets_time_without_changing_words(self):
        shot=self.shot('天外天一片黑暗，看不见一点光明，其实不是天外天没有光明，是因为天外天处处都是光。')
        original=copy.deepcopy(shot); result=retime(shot)
        self.assertEqual(shot,original)
        self.assertGreater(result['frames'],124)
        self.assertLessEqual(result['frames'],362)
        self.assertEqual(result['dialogue'][0]['text'],shot['dialogue'][0]['text'])
        self.assertEqual(result['timeline'][-1]['end_frame'],result['frames'])
        self.assertTrue(all(b['end_frame']-b['start_frame']<=24 for b in result['timeline']))

    def test_short_line_does_not_fill_whole_shot(self):
        result=retime(self.shot('这是哪里？'))
        self.assertLess(result['dialogue'][0]['end_frame'],118)
        self.assertLess(result['frames'],124)

    def test_content_target_uses_dialogue_length(self):
        self.assertEqual(dialogue_duration_seconds(['你是谁？']), 2)

    def test_content_plan_migration_preserves_silent_scene(self):
        plan={'script': {'scenes': [
            {'scene_id': 'D1', 'duration_seconds': 5, 'utterances': []},
            {'scene_id': 'D2', 'duration_seconds': 5,
             'utterances': [{'kind': 'dialogue', 'speaker': '甲', 'text': '你是谁？'}]},
        ]}}
        result, changes, blocked=retime_content_plan(plan)
        self.assertEqual(result['script']['scenes'][0]['duration_seconds'], 5)
        self.assertEqual(result['script']['scenes'][1]['duration_seconds'], 2)
        self.assertEqual(len(changes), 1)
        self.assertFalse(blocked)

    def test_overflow_cannot_silently_truncate(self):
        with self.assertRaisesRegex(ValueError,'拆镜'):
            retime(self.shot('这是需要完整保留的对白。'*12))

    def test_semantic_splits_preserve_source(self):
        text='这是第一段完整对白，后面还有解释。'*10
        parts=semantic_chunks(text)
        self.assertEqual(''.join(parts),text)
        self.assertTrue(all(p[-1] in '，。' for p in parts))
        with self.assertRaises(ValueError): semantic_chunks('光'*100)

    def test_long_dialogue_is_split_into_short_semantic_events(self):
        text = '永无休止的轮回已经证明你已经看清，并且永远的无极了，你彻底的破灭，又成为了混沌初生时的样子，不再受无极的轮回。'
        parts = split_dialogue(text)
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(speech_seconds(part) <= MAX_CONTINUOUS_SPEECH_SECONDS for part in parts))

    def test_content_plan_migration_splits_audited_dialogue_together(self):
        text = '我走了，我将同时幻化成十个状态，同时在六界经正邪的磨灭，让无极从新悟道，从新定神伦，再次创世。'
        plan = {'script': {'scenes': [{'scene_id': 'D1', 'duration_seconds': 5,
                                       'utterances': [{'kind': 'dialogue', 'speaker': '盘古', 'text': text}]}]},
                'speaker_audit': {'scenes': {'D1': [{'kind': 'dialogue', 'speaker': '盘古', 'text': text,
                                                     'reason': '原文明确说话人'}]}}}
        result, changes, blocked = retime_content_plan(plan)
        utterances = result['script']['scenes'][0]['utterances']
        audits = result['speaker_audit']['scenes']['D1']
        self.assertEqual(len(utterances), len(audits))
        self.assertEqual(''.join(row['text'] for row in utterances), text)
        self.assertEqual([row['text'] for row in utterances], [row['text'] for row in audits])
        self.assertTrue(all('按语义停顿拆分连续发声段' in row['reason'] for row in audits))
        self.assertFalse(blocked)

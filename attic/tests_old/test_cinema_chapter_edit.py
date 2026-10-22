import tempfile
import unittest
from pathlib import Path

from novel_h3.project import file_hash, write
from novel_h3.v2.chapter_edit import chapter_timeline


class ChapterEditTests(unittest.TestCase):
    def test_observed_action_cut_is_bound_to_the_actual_candidate_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            folder = plan.parent / 'takes/selected'
            folder.mkdir(parents=True)
            (folder / 'native.mp4').write_bytes(b'observed picture')
            (folder / 'evidence.jpg').write_bytes(b'action frames')
            write(plan, {'shots': [{'id': 'S205', 'spoken_lines': []}]})
            marks = {'take_id': 'selected', 'video_sha256': file_hash(folder / 'native.mp4'),
                     'source_in_frame': 30, 'source_out_frame': 145,
                     'evidence_path': str((folder / 'evidence.jpg').relative_to(root)),
                     'evidence_sha256': file_hash(folder / 'evidence.jpg')}
            write(blueprint, {'entries': [{'shot_id': 'S205', 'retain_entire_source': True,
                                          'observed_source_window': marks}]})
            write(folder / 'take.json', {'id': 'selected', 'video_sha256': marks['video_sha256'],
                                        'technical_qc': {'frames': 175},
                                        'speech_screening': {'passed': True}})
            result = chapter_timeline(root, plan, {'S205': 'selected'}, blueprint)
            segment = result['tracks'][0]['segments'][0]
            self.assertEqual((segment['source_in_frame'], segment['source_out_frame']), (30, 145))
            (folder / 'native.mp4').write_bytes(b'different picture')
            with self.assertRaisesRegex(ValueError, 'different media'):
                chapter_timeline(root, plan, {'S205': 'selected'}, blueprint)
            (folder / 'native.mp4').write_bytes(b'observed picture')
            (folder / 'evidence.jpg').write_bytes(b'different marks')
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                chapter_timeline(root, plan, {'S205': 'selected'}, blueprint)

    def test_observed_cut_cannot_remove_a_required_action_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            folder = plan.parent / 'takes/selected'
            folder.mkdir(parents=True)
            (folder / 'native.mp4').write_bytes(b'picture')
            (folder / 'evidence.jpg').write_bytes(b'frames')
            write(plan, {'shots': [{'id': 'S205', 'spoken_lines': []}]})
            marks = {'take_id': 'selected', 'video_sha256': file_hash(folder / 'native.mp4'),
                     'source_in_frame': 30, 'source_out_frame': 145,
                     'evidence_path': str((folder / 'evidence.jpg').relative_to(root)),
                     'evidence_sha256': file_hash(folder / 'evidence.jpg')}
            write(blueprint, {'entries': [{'shot_id': 'S205', 'retain_entire_source': True,
                'observed_source_window': marks, 'hard_retain_source_intervals': [
                    {'start_seconds': 5, 'end_seconds': 6.5}]}]})
            write(folder / 'take.json', {'video_sha256': marks['video_sha256'],
                'technical_qc': {'frames': 175}, 'speech_screening': {'passed': True}})
            with self.assertRaisesRegex(ValueError, 'protected interval'):
                chapter_timeline(root, plan, {'S205': 'selected'}, blueprint)

    def test_retake_revision_edits_original_candidates_without_copying_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'production_v2/old/takes/original'
            write(folder/'take.json',{'id':'original','technical_qc':{'frames':124},'speech_screening':{'passed':True}})
            plan=root/'production_v2/revised/plan.json';blueprint=plan.with_name('blueprint.json')
            write(plan,{'shots':[{'id':'S1','spoken_lines':[]}],
                        'reused_takes':{'S1':str(folder.relative_to(root))}})
            write(blueprint,{'entries':[{'shot_id':'S1','retain_entire_source':True}]})
            result=chapter_timeline(root,plan,{'S1':'original'},blueprint)
            self.assertEqual(result['tracks'][0]['segments'][0]['take_dir'],str(folder.relative_to(root)))
            self.assertFalse((plan.parent/'takes/original').exists())
            with self.assertRaisesRegex(ValueError,'explicit source'):
                chapter_timeline(root,plan,{'S1':'other'},blueprint)

    def test_closing_caption_cannot_cover_the_last_critical_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            source = {'shots': [{'id': 'END', 'spoken_lines': [{'text': '他已过世，却又来拜别。'}]}],
                      'typography_cues': [{'id': 'closing', 'shot_id': 'END', 'start_seconds': 2,
                                           'end_seconds': 5, 'text': '守约赴任', 'must_follow_speech': True,
                                           'minimum_gap_seconds': .4}]}
            write(plan, source)
            write(blueprint, {'entries': [{'shot_id': 'END', 'retain_entire_source': True}]})
            write(plan.parent/'takes/selected/take.json', {
                'technical_qc': {'frames': 192}, 'speech_screening': {'passed': True,
                'speech_gate': {'speech_segments': [{'start': .6, 'end': 3.2}]}}})
            with self.assertRaisesRegex(ValueError, 'Closing text would interrupt'):
                chapter_timeline(root, plan, {'END': 'selected'}, blueprint)
            source['typography_cues'][0].update(start_seconds=4, end_seconds=7)
            write(plan, source)
            result = chapter_timeline(root, plan, {'END': 'selected'}, blueprint)
            self.assertEqual(result['typography'][0]['start_frame'], 96)
            self.assertFalse(result['release_approved'])

    def test_time_caption_constraint_reads_vad_dictionary_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            write(plan, {'shots': [{'id': 'S506', 'spoken_lines': [{'text': '娘，您睡了多久？'}]}],
                         'typography_cues': [{'id': 'half_day', 'shot_id': 'S506', 'start_seconds': 0,
                                              'end_seconds': 2, 'text': '半日后'}]})
            write(blueprint, {'entries': [{'shot_id': 'S506', 'retain_entire_source': True,
                                          'speech_start_constraint': {'must_follow_cue_id': 'half_day',
                                                                      'minimum_gap_seconds': .2}}]})
            take = plan.parent / 'takes/selected/take.json'
            receipt = {'technical_qc': {'frames': 168}, 'speech_screening': {'passed': True,
                       'speech_gate': {'speech_segments': [{'start': 3.3, 'end': 6.8}]}}}
            write(take, receipt)
            result = chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)
            self.assertEqual(result['typography'][0]['end_frame'], 48)
            self.assertEqual(result['subtitles'][0]['start_frame'], 79)
            self.assertFalse(result['release_approved'])
            receipt['speech_screening']['speech_gate']['speech_segments'][0]['start'] = 2.1
            write(take, receipt)
            with self.assertRaisesRegex(ValueError, 'clean dialogue handle'):
                chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)

    def test_coarse_asr_start_does_not_put_dialogue_subtitle_before_time_caption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            write(plan, {'shots': [{'id': 'S506', 'spoken_lines': [{'text': '娘，帮我问问长山那个张秀才。'}]}],
                         'typography_cues': [{'id': 'half_day', 'shot_id': 'S506', 'start_seconds': .2,
                                              'end_seconds': 2.2, 'text': '半日后'}]})
            write(blueprint, {'entries': [{'shot_id': 'S506', 'retain_entire_source': True,
                'speech_start_constraint': {'must_follow_cue_id': 'half_day', 'minimum_gap_seconds': .2}}]})
            take = plan.parent / 'takes/selected/take.json'
            receipt = {
                'technical_qc': {'frames': 243}, 'speech_screening': {'passed': True,
                    'speech_gate': {'speech_segments': [{'start': 3.8, 'end': 4.2}, {'start': 4.8, 'end': 6.4}]},
                    'transcript_chunks': [{'text': '娘', 'timestamp': [0.0, 4.02]},
                                          {'text': '帮我问问长山那个张秀才', 'timestamp': [4.7, 6.26]}]}}
            write(take, receipt)
            result = chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)
            self.assertEqual(result['subtitles'][0]['start_frame'], 91)
            self.assertGreater(result['subtitles'][0]['start_frame'], result['typography'][0]['end_frame'])
            self.assertEqual(result['subtitles'][0]['text'], '娘，帮我问问长山那个张秀才。')
            self.assertEqual(result['tracks'][0]['segments'][0]['source_out_frame'], 243)
            receipt['speech_screening']['transcript_chunks'][0]['timestamp'][0] = 2.0
            write(take, receipt)
            with self.assertRaisesRegex(ValueError, 'ASR onset conflicts'):
                chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)


if __name__ == '__main__': unittest.main()

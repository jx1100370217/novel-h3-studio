import unittest
from novel_h3.dialogue_only import content, shot

class DialogueOnlyTests(unittest.TestCase):
    def test_narration_is_reference_and_character_dialogue_is_unchanged(self):
        narration={'kind':'voiceover','speaker':'旁白','text':'门开了。'}
        line={'kind':'dialogue','speaker':'甲','text':'谁在那里？'}
        original={'script':{'scenes':[{'scene_id':'s','utterances':[narration,line],'source_text':'门开了。谁在那里？'}]},'speaker_audit':{'scenes':{'s':[narration,line]}}}
        result=content(original)
        self.assertEqual(result['script']['scenes'][0]['utterances'],[line])
        self.assertEqual(result['script']['scenes'][0]['visual_narration'],'门开了。')
        self.assertEqual(len(original['script']['scenes'][0]['utterances']),2)
        self.assertEqual(result['speaker_audit']['scenes']['s'],[line])
        self.assertEqual(shot({'dialogue':[narration]})['dialogue'],[])
        self.assertEqual(content(result),result)

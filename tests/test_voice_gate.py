import unittest

import numpy as np

from novel_h3.voice_gate import detect_speech


class VoiceGateTests(unittest.TestCase):
    def test_silence_is_not_sent_to_asr(self):
        result = detect_speech(np.zeros(16000, dtype=np.float32), 16000)
        self.assertTrue(result['available'])
        self.assertFalse(result['speech_detected'])
        self.assertEqual(result['speech_segments'], [])


if __name__ == '__main__':
    unittest.main()

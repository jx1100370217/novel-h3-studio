import unittest

import numpy as np

from novel_h3.voice_audit import mfcc_stats


def tone(hz: float, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(16000 * seconds)) / 16000
    return np.sin(2 * np.pi * hz * t).astype(np.float64)


class VoiceAuditTests(unittest.TestCase):
    def test_same_tone_is_closer_than_a_different_tone(self):
        low = mfcc_stats(tone(180))
        low_again = mfcc_stats(tone(180))
        high = mfcc_stats(tone(520))
        self.assertGreater(float(np.dot(low, low_again)), float(np.dot(low, high)))

    def test_short_audio_is_unknown(self):
        self.assertIsNone(mfcc_stats(np.zeros(100, dtype=np.float64)))


if __name__ == '__main__':
    unittest.main()

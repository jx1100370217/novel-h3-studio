from pathlib import Path
import tempfile
import unittest

from novel_h3.project import file_hash, write
from novel_h3.v2.qc import audio_master


class NativeQCMasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'native.mp4').write_bytes(b'lossy-player-audio')
        (self.root / 'native_audio.flac').write_bytes(b'lossless-production-master')
        write(self.root / 'take.json', {'native_audio_sha256': file_hash(self.root / 'native_audio.flac')})

    def test_analysis_uses_the_same_native_master_as_the_edit(self):
        self.assertEqual(audio_master(self.root), self.root / 'native_audio.flac')

    def test_changed_or_missing_master_cannot_fall_back_to_player_audio(self):
        (self.root / 'native_audio.flac').write_bytes(b'wrong-master')
        with self.assertRaisesRegex(ValueError, 'take receipt'): audio_master(self.root)
        (self.root / 'native_audio.flac').unlink()
        with self.assertRaises(FileNotFoundError): audio_master(self.root)


if __name__ == '__main__': unittest.main()

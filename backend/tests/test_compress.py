"""文字起こし前の音声圧縮のユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.audio.compress import compress_for_transcription
from wav_fixtures import tone, write_float_wav


class CompressTest(unittest.TestCase):
    """25MB制限に収める圧縮処理を検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_keeps_original_when_small_enough(self) -> None:
        """上限に収まっている音声は変換せずそのまま渡す。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=0.1))

        self.assertEqual(compress_for_transcription(path, max_bytes=10_000_000), path)

    def test_compresses_audio_over_the_limit(self) -> None:
        """上限を超える音声はm4aへ変換して上限内に収める。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=1))
        statuses: list[str] = []

        compressed = compress_for_transcription(path, max_bytes=100_000, on_status=statuses.append)

        self.assertEqual(compressed.suffix, ".m4a")
        self.assertLessEqual(compressed.stat().st_size, 100_000)
        self.assertLess(compressed.stat().st_size, path.stat().st_size)
        self.assertTrue(statuses[0].startswith("文字起こし用に音声を圧縮中..."))

    def test_missing_file_is_left_to_the_provider(self) -> None:
        """存在しないファイルは、STTプロバイダ側の検査に委ねる。"""
        path = self.directory / "missing.wav"

        self.assertEqual(compress_for_transcription(path, max_bytes=1), path)


if __name__ == "__main__":
    unittest.main()

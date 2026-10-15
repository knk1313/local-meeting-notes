"""文字起こし前の音声圧縮のユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.audio import compress
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

        self.assertEqual(compress_for_transcription(path, max_bytes=10_000_000, work_dir=self.directory / 'work'), path)

    def test_compresses_audio_over_the_limit(self) -> None:
        """上限を超える音声はm4aへ変換して上限内に収める。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=1))
        statuses: list[str] = []

        compressed = compress_for_transcription(
            path, max_bytes=100_000, work_dir=self.directory / 'work', on_status=statuses.append
        )

        self.assertEqual(compressed.suffix, ".m4a")
        # 元ファイルの隣ではなく、指定した作業ディレクトリへ書き出す。
        self.assertEqual(compressed.parent, self.directory / "work")
        self.assertFalse((self.directory / "recording.m4a").exists())
        self.assertLessEqual(compressed.stat().st_size, 100_000)
        self.assertLess(compressed.stat().st_size, path.stat().st_size)
        self.assertTrue(statuses[0].startswith("文字起こし用に音声を圧縮中..."))
        # 余裕のある上限なら、最も高いビットレートで1回だけ変換する。
        self.assertEqual(statuses, ["文字起こし用に音声を圧縮中... (128kbps)"])

    def test_skips_bitrates_estimated_over_the_limit(self) -> None:
        """長さから上限を超えると見積もれるビットレートは試さない。"""
        path = self.directory / "recording.wav"
        # 30分なら、25MBに収まるのは96kbpsまで。
        with mock.patch.object(compress, "audio_duration_seconds", return_value=1800.0):
            bitrates = compress._candidate_bitrates(path, 25 * 1024 * 1024)

        self.assertEqual(bitrates, (96_000, 64_000, 32_000, 24_000, 16_000))

    def test_tries_lowest_bitrate_when_nothing_fits(self) -> None:
        """どれも収まらない見積もりなら、最も低いビットレートだけを試す。"""
        path = self.directory / "recording.wav"
        with mock.patch.object(compress, "audio_duration_seconds", return_value=100_000.0):
            bitrates = compress._candidate_bitrates(path, 25 * 1024 * 1024)

        self.assertEqual(bitrates, (16_000,))

    def test_tries_all_bitrates_when_duration_is_unknown(self) -> None:
        """長さが分からなければ、高い方から順にすべて試す。"""
        path = self.directory / "recording.wav"
        with mock.patch.object(compress, "audio_duration_seconds", return_value=None):
            bitrates = compress._candidate_bitrates(path, 25 * 1024 * 1024)

        self.assertEqual(bitrates, compress.COMPRESSION_BITRATES)

    def test_missing_file_is_left_to_the_provider(self) -> None:
        """存在しないファイルは、STTプロバイダ側の検査に委ねる。"""
        path = self.directory / "missing.wav"

        self.assertEqual(compress_for_transcription(path, max_bytes=1, work_dir=self.directory / 'work'), path)


if __name__ == "__main__":
    unittest.main()

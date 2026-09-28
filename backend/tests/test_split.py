"""長い音声の分割処理のユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import struct

from app.audio.split import split_for_transcription
from app.audio.wav import read_info
from wav_fixtures import silence, tone, write_float_wav


class SplitTest(unittest.TestCase):
    """文字起こしAPIの長さ上限に合わせた分割を検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)
        self.parts_dir = self.directory / "parts"
        self.addCleanup(self._temporary.cleanup)

    def test_treats_a_broken_header_as_unreadable(self) -> None:
        """壊れたヘッダは0除算で落とさず、読めない音声として扱う。"""
        path = self.directory / "broken.wav"
        data = b"\x00" * 64
        header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
        header += b"fmt " + struct.pack("<IHHIIHH", 16, 3, 0, 48_000, 0, 0, 32)  # チャンネル数0
        header += b"data" + struct.pack("<I", len(data))
        path.write_bytes(header + data)

        self.assertIsNone(read_info(path))
        # 分割処理も例外ではなく、そのまま渡す判断にする。
        parts = split_for_transcription(path, parts_dir=self.parts_dir, max_seconds=1, target_seconds=1)
        self.assertEqual([part.path for part in parts], [path])

    def test_keeps_short_audio_as_is(self) -> None:
        """上限に収まる音声は分割せず、元のファイルをそのまま渡す。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=1))

        parts = split_for_transcription(path, parts_dir=self.parts_dir, max_seconds=2, target_seconds=1)

        self.assertEqual([(parts[0].path, parts[0].start_seconds)], [(path, 0.0)])

    def test_splits_long_audio_within_the_limit(self) -> None:
        """上限を超える音声は、上限以下の連続した断片へ分割する。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=3))

        parts = split_for_transcription(path, parts_dir=self.parts_dir, max_seconds=2, target_seconds=1.2, search_seconds=0.3)

        self.assertEqual(len(parts), 2)
        durations = [read_info(part.path).duration_seconds for part in parts]
        self.assertAlmostEqual(sum(durations), 3.0, places=3)
        for duration in durations:
            self.assertLessEqual(duration, 2)
        # 2本目の開始位置は、1本目の長さと一致する。
        self.assertAlmostEqual(parts[0].start_seconds, 0.0, places=3)
        self.assertAlmostEqual(parts[1].start_seconds, durations[0], places=3)

    def test_cuts_on_frame_boundaries_for_multi_channel_audio(self) -> None:
        """ステレオでも、チャンネルの並びが崩れない位置で区切る。"""
        path = self.directory / "stereo.wav"
        write_float_wav(path, tone(seconds=3) + tone(seconds=3), channels=2)

        parts = split_for_transcription(
            path, parts_dir=self.parts_dir, max_seconds=2, target_seconds=1.2, search_seconds=0.3
        )

        self.assertGreater(len(parts), 1)
        for part in parts:
            info = read_info(part.path)
            self.assertEqual(info.channels, 2)
            self.assertEqual(info.data_size % info.bytes_per_frame, 0)

    def test_cuts_at_the_quietest_position(self) -> None:
        """発話の途中で切らないよう、区切りは周辺で最も静かな位置に置く。"""
        path = self.directory / "recording.wav"
        write_float_wav(path, tone(seconds=1) + silence(seconds=0.4) + tone(seconds=1.6))

        parts = split_for_transcription(path, parts_dir=self.parts_dir, max_seconds=2, target_seconds=1.2, search_seconds=0.3)

        first = read_info(parts[0].path).duration_seconds
        self.assertGreaterEqual(first, 1.0)
        self.assertLessEqual(first, 1.4)


if __name__ == "__main__":
    unittest.main()

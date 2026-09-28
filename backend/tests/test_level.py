"""録音チャンクの音量判定のユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.audio.level import SILENCE_RMS_THRESHOLD, is_silent, rms_level
from wav_fixtures import silence, tone, write_float_wav


class LevelTest(unittest.TestCase):
    """無音チャンクをSTTへ送らないための判定を検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_detects_silence(self) -> None:
        """振幅ゼロのチャンクは無音と判定する。"""
        path = self.directory / "silent.wav"
        write_float_wav(path, silence())

        self.assertEqual(rms_level(path), 0.0)
        self.assertTrue(is_silent(path))

    def test_keeps_audible_chunk(self) -> None:
        """発話相当の音量があるチャンクは無音と判定しない。"""
        path = self.directory / "tone.wav"
        write_float_wav(path, tone())

        level = rms_level(path)
        self.assertIsNotNone(level)
        self.assertGreater(level, SILENCE_RMS_THRESHOLD)
        self.assertFalse(is_silent(path))

    def test_measures_correctly_when_the_size_is_not_a_multiple_of_the_window(self) -> None:
        """データ長が窓の倍数でなくても、サンプル境界からずれずに測る。"""
        path = self.directory / "odd.wav"
        samples = tone(seconds=0.5)[:12_345]  # 窓の倍数にならない長さ
        write_float_wav(path, samples)
        expected = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5

        level = rms_level(path)

        self.assertIsNotNone(level)
        self.assertAlmostEqual(level, expected, delta=0.01)

    def test_unknown_format_is_not_treated_as_silence(self) -> None:
        """読み取れないファイルは、取りこぼさないようSTTへ送る。"""
        path = self.directory / "broken.wav"
        path.write_bytes(b"not a wav file")

        self.assertIsNone(rms_level(path))
        self.assertFalse(is_silent(path))


if __name__ == "__main__":
    unittest.main()

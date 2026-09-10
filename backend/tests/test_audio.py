"""macOS録音プロバイダのユニットテスト。"""

from __future__ import annotations

import unittest

from app.audio import AudioCaptureError
from app.audio.macos import _validate_chunk_seconds


class MacOsAudioRecorderTest(unittest.TestCase):
    """録音ヘルパーを起動する前の入力検証を確認する。"""

    def test_accepts_chunk_length_within_supported_range(self) -> None:
        """5〜60秒のチャンク長を受け付ける。"""
        _validate_chunk_seconds(5)
        _validate_chunk_seconds(60)

    def test_rejects_chunk_length_outside_supported_range(self) -> None:
        """範囲外のチャンク長には分かりやすい例外を返す。"""
        with self.assertRaises(AudioCaptureError):
            _validate_chunk_seconds(4)
        with self.assertRaises(AudioCaptureError):
            _validate_chunk_seconds(61)


if __name__ == "__main__":
    unittest.main()

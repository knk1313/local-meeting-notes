"""macOS録音プロバイダのユニットテスト。"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.audio import AudioCaptureError
from app.audio.macos import MacOsAudioRecorder, _validate_chunk_seconds


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


class RecorderFailureTest(unittest.TestCase):
    """録音ヘルパーが失敗したとき、その理由を取得できることを確認する。"""

    def test_keeps_helper_stderr_as_failure_reason(self) -> None:
        """ヘルパーがstderrへ出した理由をlast_errorから読み出せる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            helper = temporary_path / "failing-recorder"
            helper.write_text(
                '#!/bin/sh\necho "録音を開始できませんでした: マイクへのアクセスが許可されていません" >&2\nexit 1\n',
                encoding="utf-8",
            )
            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
            recorder = MacOsAudioRecorder()

            with patch.object(MacOsAudioRecorder, "_build_binary", return_value=helper):
                exit_code = recorder.record(temporary_path / "recording", 15)

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                recorder.last_error,
                "録音を開始できませんでした: マイクへのアクセスが許可されていません",
            )

    def test_last_error_is_none_without_output(self) -> None:
        """stderrへの出力が無ければ失敗理由は持たない。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            helper = temporary_path / "silent-recorder"
            helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
            recorder = MacOsAudioRecorder()

            with patch.object(MacOsAudioRecorder, "_build_binary", return_value=helper):
                exit_code = recorder.record(temporary_path / "recording", 15)

            self.assertEqual(exit_code, 0)
            self.assertIsNone(recorder.last_error)


if __name__ == "__main__":
    unittest.main()

"""macOS録音プロバイダのユニットテスト。"""

from __future__ import annotations

import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from threading import Thread

from app.audio import AudioCaptureError
from app.audio.macos import MacOsAudioRecorder, _validate_block_seconds


STUBBORN_HELPER = """#!/bin/sh
# 1回目の停止シグナルは受け取り損ね、2回目で終了する録音ヘルパー。
count=0
handle() {
    count=$((count + 1))
    echo "$count" > "$RECEIVED"
    if [ "$count" -ge 2 ]; then
        exit 0
    fi
}
trap handle INT
echo ready > "$READY"
while true; do
    sleep 0.05
done
"""


class MacOsAudioRecorderTest(unittest.TestCase):
    """録音ヘルパーを起動する前の入力検証を確認する。"""

    def test_accepts_block_length_within_supported_range(self) -> None:
        """5〜60秒の書き出し単位を受け付ける。"""
        _validate_block_seconds(5)
        _validate_block_seconds(60)

    def test_rejects_block_length_outside_supported_range(self) -> None:
        """範囲外の書き出し単位には分かりやすい例外を返す。"""
        with self.assertRaises(AudioCaptureError):
            _validate_block_seconds(4)
        with self.assertRaises(AudioCaptureError):
            _validate_block_seconds(61)


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

    def test_ignores_warnings_when_reporting_the_failure_reason(self) -> None:
        """録音が続く旨の注意書きは、失敗理由として扱わない。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            helper = temporary_path / "warning-recorder"
            helper.write_text(
                "#!/bin/sh\n"
                'echo "警告: 録音の停止処理に失敗しました（録音データは保存済みです）" >&2\n'
                'echo "録音を開始できませんでした: 画面収録の許可がありません" >&2\n'
                "exit 1\n",
                encoding="utf-8",
            )
            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
            recorder = MacOsAudioRecorder()

            with patch.object(MacOsAudioRecorder, "_build_binary", return_value=helper):
                recorder.record(temporary_path / "recording", 15)

            self.assertEqual(recorder.last_error, "録音を開始できませんでした: 画面収録の許可がありません")

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


class RecorderStopTest(unittest.TestCase):
    """停止シグナルが取りこぼされても録音が止まることを確認する。"""

    def test_resends_the_stop_signal_until_the_helper_exits(self) -> None:
        """1回目のシグナルが効かなくても、送り直して停止させる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            received = temporary_path / "received"
            ready = temporary_path / "ready"
            helper = temporary_path / "stubborn-recorder"
            helper.write_text(STUBBORN_HELPER, encoding="utf-8")
            helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
            os.environ["RECEIVED"] = str(received)
            os.environ["READY"] = str(ready)
            self.addCleanup(os.environ.pop, "RECEIVED", None)
            self.addCleanup(os.environ.pop, "READY", None)

            recorder = MacOsAudioRecorder()
            exit_codes: list[int] = []

            with (
                patch.object(MacOsAudioRecorder, "_build_binary", return_value=helper),
                patch("app.audio.macos.STOP_RETRY_SECONDS", 0.1),
            ):
                worker = Thread(target=lambda: exit_codes.append(recorder.record(temporary_path / "out", 15)))
                worker.start()
                # シグナルを受け取れる状態になるまで待つ。
                _wait_until(ready.exists)
                recorder.request_stop()
                worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(exit_codes, [0])
            self.assertGreaterEqual(int(received.read_text(encoding="utf-8").strip()), 2)


def _wait_until(condition, timeout: float = 5.0) -> None:
    """条件が満たされるまで待つ。"""
    limit = time.time() + timeout
    while time.time() < limit:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("録音ヘルパーが停止シグナルを受け取れる状態になりませんでした。")


if __name__ == "__main__":
    unittest.main()

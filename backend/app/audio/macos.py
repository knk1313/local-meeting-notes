"""macOS標準Frameworkを使う録音ヘルパーの起動処理。"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from threading import Lock, Thread
from pathlib import Path

from app.audio.base import AudioCaptureError, AudioRecorder
from app.settings import PROJECT_ROOT


SWIFT_SOURCE_PATH = Path(__file__).resolve().parent / "native" / "macos_recorder.swift"
BUILD_DIR = PROJECT_ROOT / "backend" / ".build"
BINARY_PATH = BUILD_DIR / "macos-recorder"
MINIMUM_CHUNK_SECONDS = 5
MAXIMUM_CHUNK_SECONDS = 60

# 失敗理由として保持する、録音ヘルパーのstderr末尾の行数。
RETAINED_ERROR_LINES = 5

# 録音は続いている旨の注意書きにつく接頭辞。失敗理由としては扱わない。
WARNING_PREFIX = "警告:"

# 停止シグナルを送り直す間隔（秒）と回数。起動直後は取りこぼされることがある。
STOP_RETRY_SECONDS = 1.0
STOP_RETRY_LIMIT = 5


class MacOsAudioRecorder(AudioRecorder):
    """macOSのシステム音声と既定マイクを録音するプロバイダ。"""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._stop_requested = False
        self._process_lock = Lock()
        self._error_lines: deque[str] = deque(maxlen=RETAINED_ERROR_LINES)
        self._error_reader: Thread | None = None

    @property
    def last_error(self) -> str | None:
        """録音ヘルパーがstderrへ出力した直近の内容を返す。"""
        return "\n".join(self._error_lines) or None

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """ネイティブ録音ヘルパーを起動し、停止されるまで待機する。"""
        process = self.start(output_dir, chunk_seconds)
        try:
            return process.wait()
        except KeyboardInterrupt:
            self.request_stop()
            return process.wait()
        finally:
            if self._error_reader is not None:
                self._error_reader.join(timeout=2)
            self._clear_process(process)

    def start(self, output_dir: Path, chunk_seconds: int) -> subprocess.Popen[bytes]:
        """録音ヘルパーを非同期で起動し、停止用のプロセスを返す。"""
        _validate_chunk_seconds(chunk_seconds)
        binary_path = self._build_binary()
        output_dir.mkdir(parents=True, exist_ok=True)

        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                raise AudioCaptureError("すでに録音中です。")
            self._error_lines.clear()
            self._process = subprocess.Popen(
                [
                    str(binary_path),
                    "--output-dir",
                    str(output_dir),
                    "--chunk-seconds",
                    str(chunk_seconds),
                ],
                stderr=subprocess.PIPE,
            )
            # 権限拒否などの失敗理由をstderrから拾い、呼び出し元へ伝える。
            self._error_reader = Thread(
                target=self._read_errors, args=(self._process,), name="recorder-stderr", daemon=True
            )
            self._error_reader.start()
            if self._stop_requested:
                self._process.send_signal(signal.SIGINT)
            return self._process

    def _read_errors(self, process: subprocess.Popen[bytes]) -> None:
        """ヘルパーのstderrを端末へ流しつつ、失敗理由として保持する。"""
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.decode("utf-8", errors="replace").rstrip()
            if not message:
                continue
            print(message, file=sys.stderr)
            # 注意書きは失敗理由ではないため、last_error には残さない。
            if not message.startswith(WARNING_PREFIX):
                self._error_lines.append(message)

    def request_stop(self) -> None:
        """録音ヘルパーへ停止シグナルを送る。完了処理は呼び出し元で待機する。"""
        with self._process_lock:
            self._stop_requested = True
            process = self._process
        if process is None or process.poll() is not None:
            return

        self._send_stop(process)
        # 起動直後はシグナルを受け取れないことがあるため、終了するまで送り直す。
        Thread(target=self._resend_stop, args=(process,), name="recorder-stop", daemon=True).start()

    def _resend_stop(self, process: subprocess.Popen[bytes]) -> None:
        """停止シグナルが効くまで、間隔をあけて送り直す。"""
        for _ in range(STOP_RETRY_LIMIT):
            time.sleep(STOP_RETRY_SECONDS)
            if process.poll() is not None:
                return
            self._send_stop(process)

    def _send_stop(self, process: subprocess.Popen[bytes]) -> None:
        """停止シグナルを送る。すでに終了していれば何もしない。"""
        try:
            process.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            return

    def _clear_process(self, process: subprocess.Popen[bytes]) -> None:
        with self._process_lock:
            if self._process is process:
                self._process = None

    def _build_binary(self) -> Path:
        """Swiftソースに変更がある場合だけ、録音ヘルパーをビルドする。"""
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            raise AudioCaptureError(
                "Swiftコンパイラが見つかりません。Xcode Command Line Toolsをインストールしてください。"
            )
        if not SWIFT_SOURCE_PATH.is_file():
            raise AudioCaptureError(f"macOS録音ヘルパーが見つかりません: {SWIFT_SOURCE_PATH}")

        if BINARY_PATH.exists() and BINARY_PATH.stat().st_mtime >= SWIFT_SOURCE_PATH.stat().st_mtime:
            return BINARY_PATH

        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    swiftc,
                    str(SWIFT_SOURCE_PATH),
                    "-framework",
                    "AVFoundation",
                    "-framework",
                    "ScreenCaptureKit",
                    "-o",
                    str(BINARY_PATH),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise AudioCaptureError("macOS録音ヘルパーのビルドに失敗しました。") from exc
        return BINARY_PATH


def _validate_chunk_seconds(chunk_seconds: int) -> None:
    """扱いやすい範囲のチャンク長か検証する。"""
    if MINIMUM_CHUNK_SECONDS <= chunk_seconds <= MAXIMUM_CHUNK_SECONDS:
        return
    raise AudioCaptureError(
        f"チャンク長は{MINIMUM_CHUNK_SECONDS}〜{MAXIMUM_CHUNK_SECONDS}秒で指定してください: {chunk_seconds}"
    )

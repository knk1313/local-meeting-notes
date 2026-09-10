"""macOS標準Frameworkを使う録音ヘルパーの起動処理。"""

from __future__ import annotations

import shutil
import signal
import subprocess
from pathlib import Path

from app.audio.base import AudioCaptureError, AudioRecorder
from app.settings import PROJECT_ROOT


SWIFT_SOURCE_PATH = Path(__file__).resolve().parent / "native" / "macos_recorder.swift"
BUILD_DIR = PROJECT_ROOT / "backend" / ".build"
BINARY_PATH = BUILD_DIR / "macos-recorder"
MINIMUM_CHUNK_SECONDS = 5
MAXIMUM_CHUNK_SECONDS = 60


class MacOsAudioRecorder(AudioRecorder):
    """macOSのシステム音声と既定マイクを録音するプロバイダ。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """ネイティブ録音ヘルパーを起動し、停止されるまで待機する。"""
        _validate_chunk_seconds(chunk_seconds)
        binary_path = self._build_binary()
        output_dir.mkdir(parents=True, exist_ok=True)

        process = subprocess.Popen(
            [
                str(binary_path),
                "--output-dir",
                str(output_dir),
                "--chunk-seconds",
                str(chunk_seconds),
            ]
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            return process.wait()

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

"""文字起こしAPIへ渡せるサイズまで音声を圧縮する処理。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from app.audio.base import AudioCaptureError


#: macOS標準の音声変換コマンド。追加の依存を増やさずAACへ変換できる。
AFCONVERT_PATH = Path("/usr/bin/afconvert")

#: 上から順に試すAACのビットレート。25MBに収まる長さは 32kbps で約100分、16kbps で約200分。
COMPRESSION_BITRATES = (32_000, 24_000, 16_000)


def compress_for_transcription(
    path: Path,
    *,
    max_bytes: int,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """上限に収まる音声ファイルのパスを返す。元ファイルが収まっていればそのまま返す。"""
    # 見つからない場合は、分かりやすい失敗を返せるSTTプロバイダ側の検査に任せる。
    if not path.is_file() or path.stat().st_size <= max_bytes:
        return path
    if not AFCONVERT_PATH.is_file():
        raise AudioCaptureError(
            f"音声を圧縮できません。{AFCONVERT_PATH} が見つかりません。"
        )

    destination = path.with_suffix(".m4a")
    for bitrate in COMPRESSION_BITRATES:
        if on_status is not None:
            on_status(f"文字起こし用に音声を圧縮中... ({bitrate // 1000}kbps)")
        _encode(path, destination, bitrate)
        if destination.stat().st_size <= max_bytes:
            return destination

    raise AudioCaptureError(
        "録音が長すぎるため、文字起こしAPIへ渡せるサイズまで圧縮できませんでした: "
        f"{path}"
    )


def _encode(source: Path, destination: Path, bitrate: int) -> None:
    """afconvertでモノラルAAC(m4a)へ変換する。"""
    try:
        subprocess.run(
            [
                str(AFCONVERT_PATH),
                "-f", "m4af",
                "-d", "aac",
                "-b", str(bitrate),
                "-c", "1",
                str(source),
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise AudioCaptureError(f"音声の圧縮に失敗しました: {detail or source}") from exc

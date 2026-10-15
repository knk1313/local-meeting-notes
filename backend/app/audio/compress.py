"""文字起こしAPIへ渡せるサイズまで音声を圧縮する処理。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from app.audio.base import AudioCaptureError


#: macOS標準の音声変換コマンド。追加の依存を増やさずAACへ変換できる。
AFCONVERT_PATH = Path("/usr/bin/afconvert")

#: macOS標準の音声情報コマンド。WAV以外の長さを調べるのに使う。
AFINFO_PATH = Path("/usr/bin/afinfo")

#: 分割のためにWAVへ展開するときの形式（16bit整数・モノラル）。
DECODED_SAMPLE_FORMAT = "LEI16"

#: 上から順に試すAACのビットレート。音質を落とすほど文字起こしの精度も落ちるため、
#: 上限に収まる範囲で最も高いものを使う。25MBに収まる長さは 128kbps で約27分、
#: 32kbps で約100分、16kbps で約200分。
COMPRESSION_BITRATES = (128_000, 96_000, 64_000, 32_000, 24_000, 16_000)

#: 長さから見積もったサイズに上乗せする余裕。コンテナのヘッダなどで実際は少し大きくなる。
ESTIMATE_MARGIN = 1.05


def compress_for_transcription(
    path: Path,
    *,
    max_bytes: int,
    work_dir: Path,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """上限に収まる音声ファイルのパスを返す。元ファイルが収まっていればそのまま返す。

    変換後のファイルは ``work_dir`` へ書き出す。元ファイルの隣に置くと、
    利用者が持っている同名ファイルを上書きしてしまうため。
    """
    # 見つからない場合は、分かりやすい失敗を返せるSTTプロバイダ側の検査に任せる。
    if not path.is_file() or path.stat().st_size <= max_bytes:
        return path
    if not AFCONVERT_PATH.is_file():
        raise AudioCaptureError(
            f"音声を圧縮できません。{AFCONVERT_PATH} が見つかりません。"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    destination = work_dir / f"{path.stem}.m4a"
    for bitrate in _candidate_bitrates(path, max_bytes):
        if on_status is not None:
            on_status(f"文字起こし用に音声を圧縮中... ({bitrate // 1000}kbps)")
        _encode(path, destination, bitrate)
        if destination.stat().st_size <= max_bytes:
            return destination

    raise AudioCaptureError(
        "録音が長すぎるため、文字起こしAPIへ渡せるサイズまで圧縮できませんでした: "
        f"{path}"
    )


def _candidate_bitrates(path: Path, max_bytes: int) -> tuple[int, ...]:
    """試すビットレートを返す。明らかに上限を超えるものは変換せずに飛ばす。

    長さが分からない場合はすべて試す。どれも収まらない見積もりの場合は、
    最も低いものだけを試す（収まらなければ呼び出し側で失敗として扱う）。
    """
    duration = audio_duration_seconds(path)
    if duration is None:
        return COMPRESSION_BITRATES
    fitting = tuple(
        bitrate
        for bitrate in COMPRESSION_BITRATES
        if bitrate / 8 * duration * ESTIMATE_MARGIN <= max_bytes
    )
    return fitting or COMPRESSION_BITRATES[-1:]


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


def audio_duration_seconds(path: Path) -> float | None:
    """音声の長さ（秒）を返す。取得できない場合はNone。"""
    if not AFINFO_PATH.is_file() or not path.is_file():
        return None
    try:
        result = subprocess.run([str(AFINFO_PATH), str(path)], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return None

    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        if "estimated duration:" in line:
            try:
                return float(line.split("estimated duration:")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def decode_to_wav(source: Path, destination: Path) -> Path:
    """分割できるよう、音声をWAVへ展開する。"""
    try:
        subprocess.run(
            [
                str(AFCONVERT_PATH),
                "-f", "WAVE",
                "-d", DECODED_SAMPLE_FORMAT,
                "-c", "1",
                str(source),
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise AudioCaptureError(f"音声をWAVへ展開できませんでした: {detail or source}") from exc
    return destination

"""長い録音を、文字起こしAPIが受け付ける長さへ分割する処理。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from app.audio.base import AudioCaptureError
from app.audio.compress import audio_duration_seconds, decode_to_wav
from app.audio.wav import WavInfo, read_info, read_samples, write_slice


#: gpt-4o-transcribe-diarize が1回で受け付ける音声の長さ（秒）。
API_MAX_SECONDS = 1400

#: AAC化すると先頭に1フレーム（約0.03秒）の余白が付き、API側は元の音声より長く数える。
#: 上限ぎりぎりの音声が弾かれないよう、判定にはこの余裕を引いた長さを使う。
TRANSCRIPTION_MARGIN_SECONDS = 20

#: 分割するかどうかの判断と、1本あたりの上限に使う長さ（秒）。
MAX_TRANSCRIPTION_SECONDS = API_MAX_SECONDS - TRANSCRIPTION_MARGIN_SECONDS

#: 分割するときの1本あたりの目安。区切り位置を探す余地と符号化の誤差ぶんを残す。
SPLIT_TARGET_SECONDS = 1200

#: 区切り位置を探す範囲（秒）と、音量を測る窓の長さ（秒）。
CUT_SEARCH_SECONDS = 15
CUT_WINDOW_SECONDS = 0.2


@dataclass(frozen=True)
class AudioPart:
    """文字起こしへ渡す音声と、録音全体における開始位置。"""

    path: Path
    start_seconds: float


def split_for_transcription(
    path: Path,
    *,
    parts_dir: Path,
    max_seconds: float = MAX_TRANSCRIPTION_SECONDS,
    target_seconds: float = SPLIT_TARGET_SECONDS,
    search_seconds: float = CUT_SEARCH_SECONDS,
    on_status: Callable[[str], None] | None = None,
) -> list[AudioPart]:
    """上限を超える録音を分割して返す。収まっていれば元のファイルをそのまま返す。

    区切りは目安の位置ではなく、その周辺で最も静かなところに置く。
    発話の途中で切ると、その前後の文字起こしが崩れるため。
    """
    info = read_info(path)
    duration = info.duration_seconds if info is not None else audio_duration_seconds(path)
    if duration is None or duration <= max_seconds:
        return [AudioPart(path=path, start_seconds=0.0)]

    if on_status is not None:
        on_status(
            f"音声が{duration / 60:.0f}分あるため、"
            f"{max_seconds / 60:.0f}分の上限に合わせて分割します。"
        )

    try:
        parts_dir.mkdir(parents=True, exist_ok=True)
        if info is None:
            # WAV以外はそのままでは切り出せないため、一度WAVへ展開する。
            path = decode_to_wav(path, parts_dir / f"{path.stem}-decoded.wav")
            info = read_info(path)
            if info is None:
                return [AudioPart(path=path, start_seconds=0.0)]
        return _write_parts(path, info, parts_dir, max_seconds, target_seconds, search_seconds)
    except OSError as exc:
        raise AudioCaptureError(f"録音を分割できませんでした: {exc}") from exc


def _write_parts(
    path: Path,
    info: WavInfo,
    parts_dir: Path,
    max_seconds: float,
    target_seconds: float,
    search_seconds: float,
) -> list[AudioPart]:
    """録音を分割し、書き出した順に返す。"""
    max_bytes = _align(int(max_seconds * info.bytes_per_second), info.bytes_per_frame)
    target_bytes = _align(int(target_seconds * info.bytes_per_second), info.bytes_per_frame)
    search_bytes = _align(int(search_seconds * info.bytes_per_second), info.bytes_per_frame)

    # 区切りを探す範囲は必ず前進させる。静かな位置が手前にあっても戻らないようにする。
    minimum_bytes = _align(max(target_bytes // 2, info.bytes_per_frame), info.bytes_per_frame)
    parts: list[AudioPart] = []
    start = 0
    with path.open("rb") as audio:
        while info.data_size - start > max_bytes:
            target = min(start + target_bytes, info.data_size)
            low = max(start + minimum_bytes, target - search_bytes)
            high = min(start + max_bytes, target + search_bytes, info.data_size)
            cut = _quietest_cut(audio, info, low, high) if high > low else high
            parts.append(_write_part(path, info, parts_dir, len(parts) + 1, start, cut))
            start = cut

    parts.append(_write_part(path, info, parts_dir, len(parts) + 1, start, info.data_size))
    return parts


def _write_part(
    path: Path, info: WavInfo, parts_dir: Path, number: int, start: int, end: int
) -> AudioPart:
    """指定範囲を単体のWAVとして書き出す。"""
    destination = parts_dir / f"{path.stem}-{number:02d}.wav"
    write_slice(path, info, destination, start, end)
    return AudioPart(path=destination, start_seconds=start / info.bytes_per_second)


def _quietest_cut(audio: BinaryIO, info: WavInfo, low: int, high: int) -> int:
    """``[low, high)`` の範囲で最も静かな位置を返す。測れない場合は ``high``。"""
    sample_type = info.sample_type
    window = _align(int(CUT_WINDOW_SECONDS * info.bytes_per_second), info.bytes_per_frame)
    if sample_type is None or window <= 0 or high - low < window * 2:
        return high

    typecode, _ = sample_type
    bytes_per_sample = info.bits // 8
    audio.seek(info.data_offset + low)
    samples = read_samples(audio, typecode, high - low)
    samples_per_window = window // bytes_per_sample

    quietest = high
    quietest_energy: float | None = None
    for index in range(0, len(samples) - samples_per_window + 1, samples_per_window):
        energy = sum(float(sample) * float(sample) for sample in samples[index : index + samples_per_window])
        if quietest_energy is None or energy < quietest_energy:
            quietest_energy = energy
            quietest = low + (index + samples_per_window // 2) * bytes_per_sample
    # 位置はサンプル単位で求めているため、最後にフレーム境界へ揃える。
    # 途中で切るとチャンネルの並びがずれ、以降の音声が入れ替わる。
    return _align(min(max(quietest, low), high), info.bytes_per_frame)


def _align(position: int, bytes_per_frame: int) -> int:
    """フレームの境界へ丸める。"""
    return position // bytes_per_frame * bytes_per_frame

"""録音音声の音量を測る処理。発話が無い録音をSTTへ送らないために使う。"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from app.audio.wav import WavInfo, read_info, read_samples


#: これを下回る実効値(RMS)の音声は、発話が含まれていないとみなす。
#: 実測では通常の会話が 0.012〜0.047、キャプチャ停止後の無音が 0.0000〜0.0002 だった。
SILENCE_RMS_THRESHOLD = 0.0005

#: 長時間録音でも一定時間で判定できるよう、全体から等間隔に抜き出して測る。
SAMPLE_WINDOWS = 24
SAMPLE_WINDOW_BYTES = 64 * 1024


def is_silent(path: Path, threshold: float = SILENCE_RMS_THRESHOLD) -> bool:
    """音声に発話が含まれていないとみなせるかを返す。判定できない場合はFalse。"""
    level = rms_level(path)
    return level is not None and level < threshold


def rms_level(path: Path) -> float | None:
    """WAVの実効値(RMS)を0.0〜1.0で返す。読み取れない形式ならNoneを返す。

    ファイル全体は読まず、等間隔に抜き出した窓だけを測る。
    """
    info = read_info(path)
    if info is None or info.sample_type is None or info.data_size <= 0:
        return None

    typecode, scale = info.sample_type
    try:
        with path.open("rb") as audio:
            level = _sampled_rms(audio, info, typecode)
    except OSError:
        return None
    return None if level is None else level * scale


def _sampled_rms(audio: BinaryIO, info: WavInfo, typecode: str) -> float | None:
    """data部を等間隔に抜き出し、その実効値を返す。"""
    window = min(SAMPLE_WINDOW_BYTES, info.data_size)
    step = max(window, info.data_size // SAMPLE_WINDOWS)
    total = 0.0
    count = 0

    for offset in range(0, info.data_size, step):
        audio.seek(info.data_offset + offset)
        samples = read_samples(audio, typecode, min(window, info.data_size - offset))
        if not samples:
            break
        total += sum(float(sample) * float(sample) for sample in samples)
        count += len(samples)

    return (total / count) ** 0.5 if count else None

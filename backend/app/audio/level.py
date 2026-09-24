"""録音音声の音量を測る処理。発話が無い録音をSTTへ送らないために使う。"""

from __future__ import annotations

import array
import struct
import sys
from pathlib import Path


#: これを下回る実効値(RMS)の音声は、発話が含まれていないとみなす。
#: 実測では通常の会話が 0.012〜0.047、キャプチャ停止後の無音が 0.0000〜0.0002 だった。
SILENCE_RMS_THRESHOLD = 0.0005

#: 長時間録音でも一定時間で判定できるよう、全体から等間隔に抜き出して測る。
SAMPLE_WINDOWS = 24
SAMPLE_WINDOW_BYTES = 64 * 1024

_PCM_INTEGER_FORMAT = 1
_PCM_FLOAT_FORMAT = 3
_RIFF_HEADER_SIZE = 12
_CHUNK_HEADER_SIZE = 8
_SAMPLE_TYPES = {(_PCM_FLOAT_FORMAT, 32): ("f", 1.0), (_PCM_INTEGER_FORMAT, 16): ("h", 1.0 / 32768.0)}


def is_silent(path: Path, threshold: float = SILENCE_RMS_THRESHOLD) -> bool:
    """音声に発話が含まれていないとみなせるかを返す。判定できない場合はFalse。"""
    level = rms_level(path)
    return level is not None and level < threshold


def rms_level(path: Path) -> float | None:
    """WAVの実効値(RMS)を0.0〜1.0で返す。読み取れない形式ならNoneを返す。

    ファイル全体を読まず、等間隔に抜き出した窓だけを測る。
    """
    try:
        with path.open("rb") as audio:
            header = audio.read(_RIFF_HEADER_SIZE)
            if len(header) < _RIFF_HEADER_SIZE or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return None
            return _scan_chunks(audio, path.stat().st_size)
    except OSError:
        return None


def _scan_chunks(audio, file_size: int) -> float | None:
    """RIFFチャンクをたどり、fmtとdataから実効値を求める。"""
    sample_type: tuple[str, float] | None = None
    while True:
        chunk_header = audio.read(_CHUNK_HEADER_SIZE)
        if len(chunk_header) < _CHUNK_HEADER_SIZE:
            return None

        identifier, size = struct.unpack("<4sI", chunk_header)
        if identifier == b"fmt ":
            body = audio.read(size + size % 2)
            if len(body) < 16:
                return None
            format_tag, _, _, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
            sample_type = _SAMPLE_TYPES.get((format_tag, bits))
        elif identifier == b"data":
            if sample_type is None:
                return None
            # 録音が異常終了してヘッダのサイズが0のままでも、末尾まで読んで測る。
            length = size if size > 0 else file_size - audio.tell()
            return _sampled_rms(audio, length, *sample_type)
        else:
            audio.seek(size + size % 2, 1)


def _sampled_rms(audio, length: int, typecode: str, scale: float) -> float | None:
    """data部を等間隔に抜き出し、その実効値を返す。"""
    if length <= 0:
        return None

    window_size = min(SAMPLE_WINDOW_BYTES, length)
    step = max(window_size, length // SAMPLE_WINDOWS)
    start = audio.tell()
    total = 0.0
    count = 0

    for offset in range(0, length, step):
        audio.seek(start + offset)
        block = audio.read(min(window_size, length - offset))
        if not block:
            break
        samples = array.array(typecode)
        samples.frombytes(block[: len(block) // samples.itemsize * samples.itemsize])
        if sys.byteorder == "big":  # WAVはリトルエンディアン固定。
            samples.byteswap()
        total += sum(float(sample) * float(sample) for sample in samples)
        count += len(samples)

    if count == 0:
        return None
    return (total / count) ** 0.5 * scale

"""録音チャンクの音量を測る処理。無音チャンクをSTTへ送らないために使う。"""

from __future__ import annotations

import array
import struct
import sys
from pathlib import Path


#: これを下回る実効値(RMS)のチャンクは、発話が含まれていないとみなす。
#: 実測では通常の会話が 0.012〜0.047、キャプチャ停止後の無音が 0.0000〜0.0002 だった。
SILENCE_RMS_THRESHOLD = 0.0005

_PCM_INTEGER_FORMAT = 1
_PCM_FLOAT_FORMAT = 3
_RIFF_HEADER_SIZE = 12
_CHUNK_HEADER_SIZE = 8


def is_silent(path: Path, threshold: float = SILENCE_RMS_THRESHOLD) -> bool:
    """WAVに発話が含まれていないとみなせるかを返す。判定できない場合はFalse。"""
    level = rms_level(path)
    return level is not None and level < threshold


def rms_level(path: Path) -> float | None:
    """WAVの実効値(RMS)を0.0〜1.0で返す。読み取れない形式ならNoneを返す。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < _RIFF_HEADER_SIZE or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return None

    sample_format: tuple[int, int] | None = None
    data = b""
    position = _RIFF_HEADER_SIZE
    while position + _CHUNK_HEADER_SIZE <= len(raw):
        identifier, size = struct.unpack_from("<4sI", raw, position)
        body = raw[position + _CHUNK_HEADER_SIZE: position + _CHUNK_HEADER_SIZE + size]
        if identifier == b"fmt " and len(body) >= 16:
            format_tag, _, _, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
            sample_format = (format_tag, bits)
        elif identifier == b"data":
            data = body
        position += _CHUNK_HEADER_SIZE + size + (size % 2)

    if sample_format is None or not data:
        return None
    return _rms(data, *sample_format)


def _rms(data: bytes, format_tag: int, bits: int) -> float | None:
    """サンプル列の実効値を求める。未対応のビット深度ならNoneを返す。"""
    if format_tag == _PCM_FLOAT_FORMAT and bits == 32:
        samples = array.array("f")
        scale = 1.0
    elif format_tag == _PCM_INTEGER_FORMAT and bits == 16:
        samples = array.array("h")
        scale = 1.0 / 32768.0
    else:
        return None

    samples.frombytes(data[: len(data) // samples.itemsize * samples.itemsize])
    if not samples:
        return None
    if sys.byteorder == "big":  # WAVはリトルエンディアン固定。
        samples.byteswap()
    total = sum(float(sample) * float(sample) for sample in samples)
    return (total / len(samples)) ** 0.5 * scale

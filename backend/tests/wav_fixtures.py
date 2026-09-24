"""テスト用のWAVファイルを組み立てるヘルパー。"""

from __future__ import annotations

import array
import math
import struct
from pathlib import Path


SAMPLE_RATE = 48_000
_PCM_FLOAT_FORMAT = 3


def write_float_wav(path: Path, samples: list[float]) -> None:
    """録音ヘルパーと同じ float32 モノラル WAV を書き出す。"""
    data = array.array("f", samples).tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, _PCM_FLOAT_FORMAT, 1, SAMPLE_RATE, SAMPLE_RATE * 4, 4, 32)
    header += b"data" + struct.pack("<I", len(data))
    path.write_bytes(header + data)


def silence(seconds: float = 0.1) -> list[float]:
    """完全な無音のサンプル列を返す。"""
    return [0.0] * int(SAMPLE_RATE * seconds)


def tone(seconds: float = 0.1, amplitude: float = 0.2) -> list[float]:
    """発話相当の音量を持つサンプル列を返す。"""
    frames = int(SAMPLE_RATE * seconds)
    return [amplitude * math.sin(2 * math.pi * 440 * frame / SAMPLE_RATE) for frame in range(frames)]

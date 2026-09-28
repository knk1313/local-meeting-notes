"""WAVファイルの読み取りと切り出し。音量判定と分割で共有する。"""

from __future__ import annotations

import array
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


PCM_INTEGER_FORMAT = 1
PCM_FLOAT_FORMAT = 3
RIFF_HEADER_SIZE = 12
CHUNK_HEADER_SIZE = 8

#: 扱えるサンプル形式と、array のタイプコード・1.0 へ正規化する係数。
SAMPLE_TYPES = {
    (PCM_FLOAT_FORMAT, 32): ("f", 1.0),
    (PCM_INTEGER_FORMAT, 16): ("h", 1.0 / 32768.0),
}


@dataclass(frozen=True)
class WavInfo:
    """WAVのフォーマットと、data部の位置・大きさ。"""

    format_tag: int
    channels: int
    sample_rate: int
    bits: int
    data_offset: int
    data_size: int

    @property
    def bytes_per_frame(self) -> int:
        """1フレーム（全チャンネル分）のバイト数。"""
        return self.channels * self.bits // 8

    @property
    def bytes_per_second(self) -> int:
        """1秒あたりのバイト数。"""
        return self.bytes_per_frame * self.sample_rate

    @property
    def duration_seconds(self) -> float:
        """音声の長さ（秒）。"""
        return self.data_size / self.bytes_per_second

    @property
    def sample_type(self) -> tuple[str, float] | None:
        """array のタイプコードと正規化係数。未対応の形式ならNone。"""
        return SAMPLE_TYPES.get((self.format_tag, self.bits))


def read_info(path: Path) -> WavInfo | None:
    """WAVのヘッダを読む。WAVでない、または壊れている場合はNoneを返す。"""
    try:
        with path.open("rb") as audio:
            header = audio.read(RIFF_HEADER_SIZE)
            if len(header) < RIFF_HEADER_SIZE or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                return None
            return _read_chunks(audio, path.stat().st_size)
    except OSError:
        return None


def read_samples(audio: BinaryIO, typecode: str, size: int) -> array.array:
    """開いているWAVから、現在位置のサンプル列を読み出す。"""
    samples = array.array(typecode)
    block = audio.read(size)
    samples.frombytes(block[: len(block) // samples.itemsize * samples.itemsize])
    if sys.byteorder == "big":  # WAVはリトルエンディアン固定。
        samples.byteswap()
    return samples


def write_slice(source: Path, info: WavInfo, destination: Path, start: int, end: int) -> None:
    """data部の[start, end)バイトを、単体のWAVファイルとして書き出す。"""
    length = end - start
    with source.open("rb") as audio, destination.open("wb") as output:
        audio.seek(info.data_offset + start)
        output.write(_header(info, length))
        remaining = length
        while remaining > 0:
            block = audio.read(min(1024 * 1024, remaining))
            if not block:
                break
            output.write(block)
            remaining -= len(block)


def _header(info: WavInfo, data_size: int) -> bytes:
    """切り出したdata部に対応するWAVヘッダを組み立てる。"""
    block_align = info.bytes_per_frame
    header = b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
    header += b"fmt " + struct.pack(
        "<IHHIIHH",
        16,
        info.format_tag,
        info.channels,
        info.sample_rate,
        info.sample_rate * block_align,
        block_align,
        info.bits,
    )
    return header + b"data" + struct.pack("<I", data_size)


def _read_chunks(audio: BinaryIO, file_size: int) -> WavInfo | None:
    """RIFFチャンクをたどり、fmtとdataからWavInfoを組み立てる。"""
    sample_format: tuple[int, int, int, int] | None = None
    while True:
        chunk_header = audio.read(CHUNK_HEADER_SIZE)
        if len(chunk_header) < CHUNK_HEADER_SIZE:
            return None

        identifier, size = struct.unpack("<4sI", chunk_header)
        if identifier == b"fmt ":
            body = audio.read(size + size % 2)
            if len(body) < 16:
                return None
            format_tag, channels, sample_rate, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
            sample_format = (format_tag, channels, sample_rate, bits)
        elif identifier == b"data":
            if sample_format is None:
                return None
            offset = audio.tell()
            # 録音が異常終了してヘッダのサイズが0のままでも、末尾まで使えるようにする。
            return WavInfo(*sample_format, data_offset=offset, data_size=size if size > 0 else file_size - offset)
        else:
            audio.seek(size + size % 2, 1)

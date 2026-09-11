"""録音中に出力される音声チャンクを順次文字起こしする処理。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from app.stt.base import Segment


ChunkTranscriber = Callable[[Path], list[Segment]]
StatusCallback = Callable[[str], None]
SegmentsCallback = Callable[[list[Segment]], None]


class IncrementalChunkTranscriber:
    """連番WAVチャンクを順番に文字起こしし、時刻を会議全体へ補正する。"""

    def __init__(
        self,
        chunks_dir: Path,
        *,
        chunk_seconds: int,
        transcribe: ChunkTranscriber,
        on_status: StatusCallback | None = None,
        on_segments: SegmentsCallback | None = None,
    ) -> None:
        """逐次文字起こしセッションを初期化する。"""
        self._chunks_dir = chunks_dir
        self._chunk_seconds = chunk_seconds
        self._transcribe = transcribe
        self._on_status = on_status
        self._on_segments = on_segments
        self._handled_paths: set[Path] = set()
        self._segments: list[Segment] = []
        self._failed_paths: list[Path] = []

    @property
    def segments(self) -> list[Segment]:
        """処理済みチャンクから得た、会議全体の時刻へ補正済みSegmentを返す。"""
        return list(self._segments)

    @property
    def failed_paths(self) -> list[Path]:
        """文字起こしに失敗したチャンクを返す。"""
        return list(self._failed_paths)

    def transcribe_available(self) -> None:
        """保存済みの未処理チャンクを連番順に処理する。

        録音側が一時ファイルを完成後にリネームするため、ここでは最終的な
        ``chunk-*.wav`` だけを対象にする。
        """
        for path in sorted(self._chunks_dir.glob("chunk-*.wav")):
            if path in self._handled_paths:
                continue

            self._handled_paths.add(path)
            chunk_index = _chunk_index(path)
            self._status(f"文字起こし中: {path.name}")
            try:
                segments = self._transcribe(path)
            except Exception as exc:  # 後続チャンクを失わないため、ここで継続する。
                self._failed_paths.append(path)
                self._status(f"文字起こしに失敗: {path.name}（{exc}）")
                continue

            offset = chunk_index * self._chunk_seconds
            adjusted_segments = [_offset_segment(segment, offset) for segment in segments]
            self._segments.extend(adjusted_segments)
            if self._on_segments is not None and adjusted_segments:
                self._on_segments(adjusted_segments)
            self._status(f"文字起こしを追加: {path.name}（{len(adjusted_segments)}件）")

    def _status(self, message: str) -> None:
        if self._on_status is not None:
            self._on_status(message)


def _chunk_index(path: Path) -> int:
    """``chunk-00001.wav`` 形式のファイル名から0始まりの番号を取得する。"""
    try:
        return int(path.stem.removeprefix("chunk-")) - 1
    except ValueError as exc:
        raise ValueError(f"チャンク名が不正です: {path.name}") from exc


def _offset_segment(segment: Segment, offset: int) -> Segment:
    """チャンク内の時刻を、録音セッション全体の時刻へ補正する。"""
    return replace(
        segment,
        start=None if segment.start is None else segment.start + offset,
        end=None if segment.end is None else segment.end + offset,
    )

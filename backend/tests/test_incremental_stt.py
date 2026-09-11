"""逐次STTチャンク処理のユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.stt import IncrementalChunkTranscriber, Segment


class IncrementalChunkTranscriberTest(unittest.TestCase):
    """録音チャンクの順序・時刻補正・失敗継続を検証する。"""

    def test_continues_after_a_failed_chunk_and_offsets_timestamps(self) -> None:
        """失敗チャンクを記録しつつ、後続チャンクの文字起こしを保持する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            chunks_dir = Path(temporary_directory)
            for name in ("chunk-00003.wav", "chunk-00001.wav", "chunk-00002.wav"):
                (chunks_dir / name).write_bytes(b"audio")

            calls: list[str] = []

            def transcribe(path: Path) -> list[Segment]:
                calls.append(path.name)
                if path.name == "chunk-00002.wav":
                    raise RuntimeError("temporary API error")
                return [Segment(speaker="A", start=1.0, end=2.0, text=path.stem)]

            transcriber = IncrementalChunkTranscriber(
                chunks_dir,
                chunk_seconds=20,
                transcribe=transcribe,
            )
            transcriber.transcribe_available()

            self.assertEqual(calls, ["chunk-00001.wav", "chunk-00002.wav", "chunk-00003.wav"])
            self.assertEqual([path.name for path in transcriber.failed_paths], ["chunk-00002.wav"])
            self.assertEqual(
                [(segment.start, segment.end, segment.text) for segment in transcriber.segments],
                [(1.0, 2.0, "chunk-00001"), (41.0, 42.0, "chunk-00003")],
            )


if __name__ == "__main__":
    unittest.main()

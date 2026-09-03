"""会議ノート生成CLIのユニットテスト。"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from app.cli import format_transcript, run_pipeline
from app.llm import MeetingAnalysis, Task
from app.stt import Segment, SttProvider


class FakeSttProvider(SttProvider):
    """外部APIを呼ばずに文字起こし結果を返すテスト用プロバイダ。"""

    def transcribe(self, path: Path) -> list[Segment]:
        """固定の話者ラベル付き文字起こしを返す。"""
        return [
            Segment(speaker="A", start=0.0, end=1.25, text="次回までに資料を作成します。"),
            Segment(speaker="B", start=1.5, end=2.0, text="確認しました。"),
        ]


class FakeAnalyzer:
    """外部APIを呼ばずに会議分析結果を返すテスト用分析器。"""

    def analyze(self, transcript: str) -> MeetingAnalysis:
        """固定の会議分析結果を返す。"""
        return MeetingAnalysis(
            summary=["資料作成について確認した。"],
            decisions=["次回までに資料を作成する。"],
            open_questions=[],
            tasks=[Task(title="資料を作成する", assignee="A", due_date="次回会議")],
        )


class CliTest(unittest.TestCase):
    """CLIの一気通貫処理を検証する。"""

    def test_format_transcript(self) -> None:
        """話者と時刻を含む文字起こし本文を生成できる。"""
        transcript = format_transcript(
            [Segment(speaker="A", start=0.0, end=1.25, text=" 発言です ")]
        )
        self.assertEqual(transcript, "[A] 0.00s–1.25s: 発言です")

    def test_run_pipeline_writes_note_and_debug_transcript(self) -> None:
        """API層を差し替え、一気通貫でMarkdownとデバッグ用文字起こしを保存できる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            notes_dir = Path(temporary_directory)
            args = argparse.Namespace(
                audio_path=Path("sample.m4a"),
                title="定例MTG",
                participants=["田中"],
                tags=["project-a"],
                notes_dir=notes_dir,
                keep_transcript=True,
            )
            output_path = run_pipeline(args, stt_provider=FakeSttProvider(), analyzer=FakeAnalyzer())
            self.assertTrue(output_path.is_file())
            self.assertIn("title: \"定例MTG\"", output_path.read_text(encoding="utf-8"))
            self.assertTrue(output_path.with_suffix(".transcript.txt").is_file())


if __name__ == "__main__":
    unittest.main()

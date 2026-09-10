"""会議ノート生成CLIのユニットテスト。"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.cli import (
    build_record_parser,
    format_transcript,
    run_pipeline,
    run_record,
)
from app.llm import MeetingAnalysis, Task
from app.settings import settings
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


class FakeRecorder:
    """録音を起動せず、受け取った設定を記録するテスト用録音器。"""

    def __init__(self) -> None:
        self.output_dir: Path | None = None
        self.chunk_seconds: int | None = None

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """受け取った録音設定を保存し、成功終了する。"""
        self.output_dir = output_dir
        self.chunk_seconds = chunk_seconds
        return 0


class CliTest(unittest.TestCase):
    """CLIの一気通貫処理を検証する。"""

    def test_format_transcript(self) -> None:
        """話者と時刻を含む文字起こし本文を生成できる。"""
        transcript = format_transcript(
            [Segment(speaker="A", start=0.0, end=1.25, text=" 発言です ")]
        )
        self.assertEqual(transcript, "[A] 0.00s–1.25s: 発言です")

    def test_record_parser_accepts_meeting_metadata(self) -> None:
        """録音コマンドは会議ノート用のメタデータを受け付ける。"""
        args = build_record_parser().parse_args(
            ["--title", "定例MTG", "--participant", "田中", "--tag", "project-a", "--keep-transcript"]
        )
        self.assertEqual(args.title, "定例MTG")
        self.assertEqual(args.participants, ["田中"])
        self.assertEqual(args.tags, ["project-a"])
        self.assertTrue(args.keep_transcript)

    def test_run_record_resolves_timestamped_output_below_project_root(self) -> None:
        """既定の録音出力先をリポジトリ直下の日時付きディレクトリへ解決する。"""
        recorder = FakeRecorder()
        args = argparse.Namespace(title=None, participants=[], tags=[], keep_transcript=False)

        with patch("app.cli.settings", replace(settings, recording_chunk_seconds=20)):
            exit_code = run_record(args, recorder=recorder)

        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(recorder.output_dir)
        self.assertEqual(recorder.output_dir.parent, Path(__file__).resolve().parents[2] / "data")
        self.assertRegex(recorder.output_dir.name, r"^recordings_\d{12}$")
        self.assertEqual(recorder.chunk_seconds, 20)

    def test_run_pipeline_writes_note_and_debug_transcript(self) -> None:
        """API層を差し替え、一気通貫でMarkdownとデバッグ用文字起こしを保存できる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            notes_dir = Path(temporary_directory)
            args = argparse.Namespace(
                audio_path=Path("sample.m4a"),
                title="定例MTG",
                participants=["田中"],
                tags=["project-a"],
                keep_transcript=True,
            )
            output_path = run_pipeline(
                args,
                stt_provider=FakeSttProvider(),
                analyzer=FakeAnalyzer(),
                notes_dir=notes_dir,
            )
            self.assertTrue(output_path.is_file())
            self.assertIn("title: \"定例MTG\"", output_path.read_text(encoding="utf-8"))
            self.assertTrue(output_path.with_suffix(".transcript.txt").is_file())

if __name__ == "__main__":
    unittest.main()

"""会議ノート生成CLIのユニットテスト。"""

from __future__ import annotations

import argparse
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.cli import (
    EXIT_FAILED,
    EXIT_NO_SPEECH,
    RECORDING_FILENAME,
    TRANSCRIPT_FILENAME,
    build_note_parser,
    build_record_parser,
    format_transcript,
    run_note,
    run_pipeline,
    run_record,
)
from app.audio import AudioRecorder
from app.llm import LlmError, MeetingAnalysis, Task
from app.settings import settings
from app.stt import Segment, SttError, SttProvider
from wav_fixtures import silence, tone, write_float_wav


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


class InterruptedRecorder(AudioRecorder):
    """途中まで録音したところで、キャプチャ中断により異常終了する録音器。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """発話のある録音を残したまま異常終了する。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        write_float_wav(output_dir / RECORDING_FILENAME, tone())
        return 3

    @property
    def last_error(self) -> str | None:
        """キャプチャが中断された理由を返す。"""
        return "録音が中断されました: 取り込みを行うディスプレイまたはウインドウが見つかりませんでした"


class FailingRecorder(AudioRecorder):
    """録音を開始できずに終了する録音器。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """音声を残さずに失敗する。"""
        return 1

    @property
    def last_error(self) -> str | None:
        """ヘルパーが出力した失敗理由を返す。"""
        return "録音を開始できませんでした: 画面収録の許可がありません"


class FakeRecorder(AudioRecorder):
    """録音を起動せず、受け取った設定を記録するテスト用録音器。"""

    def __init__(self) -> None:
        self.output_dir: Path | None = None
        self.chunk_seconds: int | None = None

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """受け取った録音設定を保存し、音声を残さず成功終了する。"""
        self.output_dir = output_dir
        self.chunk_seconds = chunk_seconds
        return 0


class NeverCalledRecorder(AudioRecorder):
    """呼び出されてはいけないテスト用録音器。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """設定不足のまま録音が始まったことを検知する。"""
        raise AssertionError("設定が足りない場合は、録音を始めてはいけない。")


class FakeMeetingRecorder(AudioRecorder):
    """発話のある録音を1ファイル残すテスト用録音器。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """会議全体の音声を書き出して正常終了する。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        write_float_wav(output_dir / RECORDING_FILENAME, tone())
        return 0


class SilentRecorder(AudioRecorder):
    """発話が含まれない録音を残すテスト用録音器。"""

    def record(self, output_dir: Path, chunk_seconds: int) -> int:
        """無音だけの音声を書き出して正常終了する。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        write_float_wav(output_dir / RECORDING_FILENAME, silence())
        return 0


class RecordingSttProvider(SttProvider):
    """呼び出し順を保持するテスト用STTプロバイダ。"""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def transcribe(self, path: Path) -> list[Segment]:
        """ファイル名に応じた文字起こし結果を返す。"""
        self.paths.append(path)
        return [Segment(speaker="A", start=0.0, end=1.0, text=path.stem)]


class SilentSttProvider(SttProvider):
    """発話を検出できなかった場合を再現するテスト用STTプロバイダ。"""

    def transcribe(self, path: Path) -> list[Segment]:
        """文字起こし結果なしを返す。"""
        return []


class FailingSttProvider(SttProvider):
    """STT呼び出しが失敗する場合を再現するテスト用STTプロバイダ。"""

    def transcribe(self, path: Path) -> list[Segment]:
        """常に失敗する。"""
        raise SttError("OpenAI の文字起こしに失敗しました")


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

        # チャンクが1つも出ないまま停止した録音は、ノートを作らず破棄する。
        self.assertEqual(exit_code, EXIT_NO_SPEECH)
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

    def test_run_record_stops_before_recording_without_stt_key(self) -> None:
        """STTのキーが無い場合は、録音を始める前に止める。"""
        args = argparse.Namespace(title="設定テスト", participants=[], tags=[], keep_transcript=False)

        with patch("app.cli.settings", replace(settings, openai_api_key=None)):
            with self.assertRaises(SttError) as raised:
                run_record(args, recorder=NeverCalledRecorder(), analyzer=FakeAnalyzer())

        self.assertIn("OPENAI_API_KEY", str(raised.exception))

    def test_run_record_stops_before_recording_without_llm_key(self) -> None:
        """要約用のキーが無い場合も、録音を始める前に止める。"""
        args = argparse.Namespace(title="設定テスト", participants=[], tags=[], keep_transcript=False)

        with patch("app.llm.anthropic.settings", replace(settings, anthropic_api_key=None)):
            with self.assertRaises(LlmError) as raised:
                run_record(args, recorder=NeverCalledRecorder(), stt_provider=FakeSttProvider())

        self.assertIn("ANTHROPIC_API_KEY", str(raised.exception))

    def test_run_record_transcribes_whole_recording_and_writes_note(self) -> None:
        """録音停止後、会議全体の音声を1回だけ文字起こししてノートを生成する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            recording_dir = temporary_path / "recording"
            notes_dir = temporary_path / "notes"
            provider = RecordingSttProvider()
            args = argparse.Namespace(title="一括文字起こし", participants=[], tags=[], keep_transcript=False)

            with patch("app.cli._resolve_recording_output_dir", return_value=recording_dir):
                exit_code = run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=provider,
                    analyzer=FakeAnalyzer(),
                    notes_dir=notes_dir,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual([path.name for path in provider.paths], [RECORDING_FILENAME])
            note = next(notes_dir.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("[A] 0.00s–1.00s: recording", note)

    def test_run_record_keeps_transcript_before_summarizing(self) -> None:
        """要約が失敗しても作り直せるよう、文字起こしを録音ディレクトリへ残す。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            recording_dir = temporary_path / "recording"
            args = argparse.Namespace(title="保存テスト", participants=[], tags=[], keep_transcript=False)

            with patch("app.cli._resolve_recording_output_dir", return_value=recording_dir):
                run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=RecordingSttProvider(),
                    analyzer=FakeAnalyzer(),
                    notes_dir=temporary_path / "notes",
                )

            transcript = (recording_dir / TRANSCRIPT_FILENAME).read_text(encoding="utf-8")
            self.assertEqual(transcript.splitlines(), ["[A] 0.00s–1.00s: recording"])

    def test_run_record_writes_note_when_recording_is_interrupted(self) -> None:
        """録音が途中で切れても、取得できた音声から会議ノートを作る。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            notes_dir = temporary_path / "notes"
            warnings: list[str] = []
            args = argparse.Namespace(title="中断テスト", participants=[], tags=[], keep_transcript=False)

            with patch("app.cli._resolve_recording_output_dir", return_value=temporary_path / "recording"):
                exit_code = run_record(
                    args,
                    recorder=InterruptedRecorder(),
                    stt_provider=RecordingSttProvider(),
                    analyzer=FakeAnalyzer(),
                    notes_dir=notes_dir,
                    on_warning=warnings.append,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(next(notes_dir.glob("*.md")).is_file())
            self.assertEqual(
                warnings,
                [
                    "録音が途中で終了しました（録音が中断されました: "
                    "取り込みを行うディスプレイまたはウインドウが見つかりませんでした）。"
                    "取得できたぶんで会議ノートを作成します。"
                ],
            )

    def test_run_record_reports_recorder_failure_reason(self) -> None:
        """録音ヘルパーが失敗した場合は、終了コードではなく理由を伝える。"""
        exit_code, statuses, _, _ = self._run_record(FailingRecorder(), FakeSttProvider())

        self.assertEqual(exit_code, EXIT_FAILED)
        self.assertEqual(statuses[-1], "録音に失敗しました: 録音を開始できませんでした: 画面収録の許可がありません")

    def test_run_record_discards_silent_recording(self) -> None:
        """発話が無い録音はSTTへ送らず、録音データごと破棄する。"""
        provider = RecordingSttProvider()
        exit_code, statuses, notes_dir, recording_dir = self._run_record(SilentRecorder(), provider)

        self.assertEqual(exit_code, EXIT_NO_SPEECH)
        self.assertEqual(provider.paths, [])
        self.assertEqual(statuses[-1], "発話を検出できませんでした。会議ノートは作成せず、録音データは破棄しました。")
        self.assertFalse(notes_dir.exists())
        self.assertFalse(recording_dir.exists())

    def test_run_record_discards_recording_without_speech(self) -> None:
        """文字起こし結果が空の場合も、会議ノートを作らず録音データを破棄する。"""
        exit_code, statuses, notes_dir, recording_dir = self._run_record(FakeMeetingRecorder(), SilentSttProvider())

        self.assertEqual(exit_code, EXIT_NO_SPEECH)
        self.assertEqual(statuses[-1], "発話を検出できませんでした。会議ノートは作成せず、録音データは破棄しました。")
        self.assertFalse(notes_dir.exists())
        self.assertFalse(recording_dir.exists())

    def test_run_record_keeps_recording_when_transcription_fails(self) -> None:
        """文字起こしに失敗したときは、再試行できるよう録音データを残す。"""
        exit_code, statuses, notes_dir, recording_dir = self._run_record(FakeMeetingRecorder(), FailingSttProvider())

        self.assertEqual(exit_code, EXIT_FAILED)
        self.assertIn("文字起こしに失敗しました", statuses[-1])
        self.assertIn(RECORDING_FILENAME, statuses[-1])
        self.assertFalse(notes_dir.exists())
        self.assertTrue((recording_dir / RECORDING_FILENAME).is_file())

    def _run_record(self, recorder: AudioRecorder, provider: SttProvider) -> tuple[int, list[str], Path, Path]:
        """録音ディレクトリとノート出力先を一時領域に向けて録音処理を実行する。"""
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        temporary_path = Path(temporary_directory.name)
        recording_dir = temporary_path / "recording"
        notes_dir = temporary_path / "notes"
        statuses: list[str] = []
        args = argparse.Namespace(title="テスト", participants=[], tags=[], keep_transcript=False)

        with patch("app.cli._resolve_recording_output_dir", return_value=recording_dir):
            exit_code = run_record(
                args,
                recorder=recorder,
                stt_provider=provider,
                analyzer=FakeAnalyzer(),
                notes_dir=notes_dir,
                on_status=statuses.append,
            )

        return exit_code, statuses, notes_dir, recording_dir

    def test_run_note_rebuilds_note_from_saved_transcript(self) -> None:
        """保存済みの文字起こしから会議ノートを作り直せる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            transcript_path = temporary_path / TRANSCRIPT_FILENAME
            transcript_path.write_text("[A] 0.00s–1.00s: 復旧テストです\n", encoding="utf-8")
            args = build_note_parser().parse_args([str(transcript_path), "--title", "復旧した会議"])

            note_path = run_note(args, analyzer=FakeAnalyzer(), notes_dir=temporary_path / "notes")

            self.assertIn("復旧した会議", note_path.read_text(encoding="utf-8"))
            self.assertIn("[A] 0.00s–1.00s: 復旧テストです", note_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

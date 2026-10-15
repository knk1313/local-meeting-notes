"""会議ノート生成CLIのユニットテスト。"""

from __future__ import annotations

import argparse
import tempfile
import time
import unittest
from threading import Barrier
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.cli import (
    EXIT_FAILED,
    _transcribe_audio,
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
from app.audio.split import AudioPart
from app.llm import LlmError, MeetingAnalysis, Task
from app.settings import settings
from app.stt import ProgressCallback, Segment, SttError, SttProvider
from wav_fixtures import silence, tone, write_float_wav


class FakeSttProvider(SttProvider):
    """外部APIを呼ばずに文字起こし結果を返すテスト用プロバイダ。"""

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
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

    def record(self, output_dir: Path, block_seconds: int) -> int:
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

    def record(self, output_dir: Path, block_seconds: int) -> int:
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
        self.block_seconds: int | None = None

    def record(self, output_dir: Path, block_seconds: int) -> int:
        """受け取った録音設定を保存し、音声を残さず成功終了する。"""
        self.output_dir = output_dir
        self.block_seconds = block_seconds
        return 0


class NeverCalledRecorder(AudioRecorder):
    """呼び出されてはいけないテスト用録音器。"""

    def record(self, output_dir: Path, block_seconds: int) -> int:
        """設定不足のまま録音が始まったことを検知する。"""
        raise AssertionError("設定が足りない場合は、録音を始めてはいけない。")


class NeverCalledAnalyzer:
    """呼び出されてはいけないテスト用の要約器。"""

    def analyze(self, transcript: str) -> MeetingAnalysis:
        """要約を呼ばない指定なのに呼ばれたことを検知する。"""
        raise AssertionError("文字起こしで止める指定では、要約を呼んではいけない。")


class FakeMeetingRecorder(AudioRecorder):
    """発話のある録音を1ファイル残すテスト用録音器。"""

    def record(self, output_dir: Path, block_seconds: int) -> int:
        """会議全体の音声を書き出して正常終了する。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        write_float_wav(output_dir / RECORDING_FILENAME, tone())
        return 0


class SilentRecorder(AudioRecorder):
    """発話が含まれない録音を残すテスト用録音器。"""

    def record(self, output_dir: Path, block_seconds: int) -> int:
        """無音だけの音声を書き出して正常終了する。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        write_float_wav(output_dir / RECORDING_FILENAME, silence())
        return 0


class RecordingSttProvider(SttProvider):
    """呼び出し順を保持するテスト用STTプロバイダ。"""

    def __init__(self) -> None:
        self.paths: list[Path] = []

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
        """ファイル名に応じた文字起こし結果を返す。"""
        self.paths.append(path)
        return [Segment(speaker="A", start=0.0, end=1.0, text=path.stem)]


class SilentSttProvider(SttProvider):
    """発話を検出できなかった場合を再現するテスト用STTプロバイダ。"""

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
        """文字起こし結果なしを返す。"""
        return []


class SecondPartFailingSttProvider(SttProvider):
    """2本目の断片で失敗するテスト用STTプロバイダ。"""

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
        """1本目だけ成功し、以降は失敗する。"""
        self.calls += 1
        if self.calls > 1:
            raise SttError("OpenAIのクレジット残高が不足しています。")
        return [Segment(speaker="A", start=0.0, end=1.0, text="前半")]


class FailingSttProvider(SttProvider):
    """STT呼び出しが失敗する場合を再現するテスト用STTプロバイダ。"""

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
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
        # 実行中の録音を消さないよう、削除処理だけ差し替える。
        self.enterContext(patch("app.cli._discard_recording"))
        args = argparse.Namespace(title=None, participants=[], tags=[], keep_transcript=False, transcribe_only=False)

        with patch("app.cli.settings", replace(settings, recording_block_seconds=20)):
            exit_code = run_record(args, recorder=recorder)

        # チャンクが1つも出ないまま停止した録音は、ノートを作らず破棄する。
        self.assertEqual(exit_code, EXIT_NO_SPEECH)
        self.assertIsNotNone(recorder.output_dir)
        self.assertEqual(recorder.output_dir.parent, Path(__file__).resolve().parents[2] / "data")
        self.assertRegex(recorder.output_dir.name, r"^recordings_\d{14}$")
        self.assertEqual(recorder.block_seconds, 20)

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
                transcribe_only=False,
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
        args = argparse.Namespace(title="設定テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

        with patch("app.cli.settings", replace(settings, openai_api_key=None)):
            with self.assertRaises(SttError) as raised:
                run_record(args, recorder=NeverCalledRecorder(), analyzer=FakeAnalyzer())

        self.assertIn("OPENAI_API_KEY", str(raised.exception))

    def test_run_record_stops_before_recording_without_llm_key(self) -> None:
        """要約用のキーが無い場合も、録音を始める前に止める。"""
        args = argparse.Namespace(title="設定テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

        with patch("app.llm.anthropic.settings", replace(settings, anthropic_api_key=None)):
            with self.assertRaises(LlmError) as raised:
                run_record(args, recorder=NeverCalledRecorder(), stt_provider=FakeSttProvider())

        self.assertIn("ANTHROPIC_API_KEY", str(raised.exception))

    def test_shows_what_it_is_waiting_for_while_the_api_responds(self) -> None:
        """API の応答待ちの間は、待っている理由が分かる表示を出したままにする。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "recording.wav"
            write_float_wav(path, tone(seconds=0.2))
            statuses: list[str] = []
            shown_while_waiting: list[str] = []

            class WatchingSttProvider(SttProvider):
                """呼び出された時点で表示されているステータスを記録する。"""

                def transcribe(self, audio_path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
                    shown_while_waiting.append(statuses[-1])
                    return [Segment(speaker="A", start=0.0, end=1.0, text="発言")]

            _transcribe_audio(path, WatchingSttProvider(), report_status=statuses.append)

            self.assertEqual(
                shown_while_waiting,
                ["文字起こしAPIへ送信中... 完了まで数分かかることがあります"],
            )

    def test_transcribes_parts_concurrently_and_keeps_their_order(self) -> None:
        """分割した断片は同時に送り、結果と通知は元の順序で扱う。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "recording.wav"
            write_float_wav(path, tone(seconds=0.2))
            statuses: list[str] = []
            shown_while_waiting: list[str] = []
            both_started = Barrier(2, timeout=5)

            class ConcurrentSttProvider(SttProvider):
                """2本が同時に呼ばれたことを確かめ、2本目を先に返す。"""

                def transcribe(self, audio_path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
                    shown_while_waiting.append(statuses[-1])
                    both_started.wait()  # 直列なら2本目が来ず、ここで待ち続ける
                    if audio_path.name.endswith("-01.wav"):
                        time.sleep(0.05)
                    return [Segment(speaker="A", start=0.0, end=1.0, text=audio_path.stem)]

            def split(source: Path, *, parts_dir: Path, **_keywords: object) -> list[AudioPart]:
                parts_dir.mkdir(parents=True, exist_ok=True)
                first = parts_dir / "recording-01.wav"
                second = parts_dir / "recording-02.wav"
                write_float_wav(first, tone(seconds=0.1))
                write_float_wav(second, tone(seconds=0.1))
                return [AudioPart(path=first, start_seconds=0.0), AudioPart(path=second, start_seconds=600.0)]

            received: list[list[Segment]] = []
            with patch("app.cli.split_for_transcription", side_effect=split):
                segments = _transcribe_audio(
                    path, ConcurrentSttProvider(), report_status=statuses.append, on_part=received.append
                )

            self.assertEqual(
                shown_while_waiting,
                ["文字起こしAPIへ送信中... (2本を並行して処理) 完了まで数分かかることがあります"] * 2,
            )
            # 2本目が先に終わっても、結果は1本目から順に並ぶ。
            self.assertEqual([segment.text for segment in segments], ["recording-01", "recording-02"])
            self.assertEqual([part[0].start for part in received], [0.0, 600.0])
            self.assertTrue(any(status.startswith("文字起こし完了 (1/2)") for status in statuses))

    def test_run_record_transcribes_whole_recording_and_writes_note(self) -> None:
        """録音停止後、会議全体の音声を1回だけ文字起こししてノートを生成する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            recording_dir = temporary_path / "recording"
            notes_dir = temporary_path / "notes"
            provider = RecordingSttProvider()
            args = argparse.Namespace(title="一括文字起こし", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

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
            args = argparse.Namespace(title="保存テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

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

    def test_run_record_offsets_timestamps_of_later_parts(self) -> None:
        """分割して文字起こしした場合も、時刻は録音全体の位置に揃える。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            recording_dir = temporary_path / "recording"
            args = argparse.Namespace(title="分割テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

            def split(path: Path, **_keywords: object) -> list[AudioPart]:
                return [AudioPart(path=path, start_seconds=0.0), AudioPart(path=path, start_seconds=600.0)]

            with (
                patch("app.cli._resolve_recording_output_dir", return_value=recording_dir),
                patch("app.cli.split_for_transcription", side_effect=split),
            ):
                run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=RecordingSttProvider(),
                    analyzer=FakeAnalyzer(),
                    notes_dir=temporary_path / "notes",
                )

            transcript = (recording_dir / TRANSCRIPT_FILENAME).read_text(encoding="utf-8")
            self.assertEqual(
                transcript.splitlines(),
                ["[A] 0.00s–1.00s: recording", "[A] 600.00s–601.00s: recording"],
            )

    def test_run_record_keeps_transcript_of_finished_parts_on_failure(self) -> None:
        """分割の途中で失敗しても、成功した断片の文字起こしは残して案内する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            recording_dir = temporary_path / "recording"
            statuses: list[str] = []
            args = argparse.Namespace(title="途中失敗テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

            def split(path: Path, **_keywords: object) -> list[AudioPart]:
                return [AudioPart(path=path, start_seconds=0.0), AudioPart(path=path, start_seconds=600.0)]

            with (
                patch("app.cli._resolve_recording_output_dir", return_value=recording_dir),
                patch("app.cli.split_for_transcription", side_effect=split),
            ):
                exit_code = run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=SecondPartFailingSttProvider(),
                    analyzer=FakeAnalyzer(),
                    notes_dir=temporary_path / "notes",
                    on_status=statuses.append,
                )

            self.assertEqual(exit_code, EXIT_FAILED)
            transcript_path = recording_dir / TRANSCRIPT_FILENAME
            self.assertEqual(transcript_path.read_text(encoding="utf-8").splitlines(), ["[A] 0.00s–1.00s: 前半"])
            self.assertIn("クレジット残高が不足しています", statuses[-1])
            self.assertIn(f"python -m app note {transcript_path}", statuses[-1])
            self.assertTrue((recording_dir / RECORDING_FILENAME).is_file())

    def test_run_record_writes_note_when_recording_is_interrupted(self) -> None:
        """録音が途中で切れても、取得できた音声から会議ノートを作る。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            notes_dir = temporary_path / "notes"
            statuses: list[str] = []
            args = argparse.Namespace(title="中断テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

            with patch("app.cli._resolve_recording_output_dir", return_value=temporary_path / "recording"):
                exit_code = run_record(
                    args,
                    recorder=InterruptedRecorder(),
                    stt_provider=RecordingSttProvider(),
                    analyzer=FakeAnalyzer(),
                    notes_dir=notes_dir,
                    on_status=statuses.append,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(next(notes_dir.glob("*.md")).is_file())
            # 理由は録音ヘルパーが表示済みなので、画面には続きだけを出す。
            self.assertIn("録音は途中で終了しましたが、取得できた0分00秒ぶんから会議ノートを作成します。", statuses)

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
        args = argparse.Namespace(title="テスト", participants=[], tags=[], keep_transcript=False, transcribe_only=False)

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

    def test_record_parser_accepts_transcribe_only(self) -> None:
        """録音コマンドで、文字起こしで止める指定を受け付ける。"""
        self.assertTrue(build_record_parser().parse_args(["--transcribe-only"]).transcribe_only)
        self.assertFalse(build_record_parser().parse_args([]).transcribe_only)

    def test_run_record_stops_after_transcription_when_requested(self) -> None:
        """文字起こしで止める指定では、要約を呼ばず文字起こしだけを保存する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            notes_dir = temporary_path / "notes"
            statuses: list[str] = []
            args = argparse.Namespace(
                title="要約なし", participants=[], tags=[], keep_transcript=False, transcribe_only=True
            )

            with patch("app.cli._resolve_recording_output_dir", return_value=temporary_path / "recording"):
                exit_code = run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=RecordingSttProvider(),
                    analyzer=NeverCalledAnalyzer(),
                    notes_dir=notes_dir,
                    on_status=statuses.append,
                )

            self.assertEqual(exit_code, 0)
            saved = sorted(path.name for path in notes_dir.iterdir())
            self.assertEqual(len(saved), 1)
            self.assertTrue(saved[0].endswith("-要約なし.transcript.txt"))
            self.assertEqual((notes_dir / saved[0]).read_text(encoding="utf-8"), "[A] 0.00s–1.00s: recording\n")
            self.assertIn("python -m app note", statuses[-1])
            self.assertIn('--title "要約なし"', statuses[-1])

    def test_run_record_does_not_require_llm_settings_when_transcribe_only(self) -> None:
        """文字起こしで止めるなら、要約用のキーが無くても録音を始められる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            args = argparse.Namespace(
                title="設定なし", participants=[], tags=[], keep_transcript=False, transcribe_only=True
            )

            with (
                patch("app.llm.anthropic.settings", replace(settings, anthropic_api_key=None)),
                patch("app.cli._resolve_recording_output_dir", return_value=temporary_path / "recording"),
            ):
                exit_code = run_record(
                    args,
                    recorder=FakeMeetingRecorder(),
                    stt_provider=RecordingSttProvider(),
                    notes_dir=temporary_path / "notes",
                )

            self.assertEqual(exit_code, 0)

    def test_run_pipeline_stops_after_transcription_when_requested(self) -> None:
        """音声ファイルからの生成でも、文字起こしで止められる。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            notes_dir = Path(temporary_directory)
            args = argparse.Namespace(
                audio_path=Path("sample.m4a"),
                title="定例MTG",
                participants=[],
                tags=[],
                keep_transcript=False,
                transcribe_only=True,
            )

            output_path = run_pipeline(
                args, stt_provider=FakeSttProvider(), analyzer=NeverCalledAnalyzer(), notes_dir=notes_dir
            )

            self.assertTrue(output_path.name.endswith("-定例MTG.transcript.txt"))
            self.assertEqual([path.name for path in notes_dir.iterdir()], [output_path.name])

    def test_reports_transcription_progress_as_percentage(self) -> None:
        """区間が確定するたびの位置から、全体に対する割合を表示する。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "recording.wav"
            write_float_wav(path, tone(seconds=2))
            statuses: list[str] = []

            class ProgressingSttProvider(SttProvider):
                """区間の確定を順に知らせる。"""

                def transcribe(self, audio_path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
                    for seconds in (0.1, 0.5, 0.55, 1.0, 2.0):
                        on_progress(seconds)
                    return [Segment(speaker="A", start=0.0, end=2.0, text="発言")]

            _transcribe_audio(path, ProgressingSttProvider(), report_status=statuses.append)

            progress = [status for status in statuses if status.startswith("文字起こし中... ")]
            # 10%の区切りをまたいだときだけ出す。5%（最初の区切りの手前）と
            # 27%（25%と同じ区切りの中）は間引かれる。
            self.assertEqual(
                progress,
                [
                    "文字起こし中... 25% (0分00秒 / 0分02秒)",
                    "文字起こし中... 50% (0分01秒 / 0分02秒)",
                    "文字起こし中... 100% (0分02秒 / 0分02秒)",
                ],
            )


if __name__ == "__main__":
    unittest.main()

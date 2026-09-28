"""音声ファイルから会議ノートを生成するコマンドラインインターフェース。"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Sequence

from app.audio import AudioCaptureError, AudioRecorder, MacOsAudioRecorder
from app.audio.compress import compress_for_transcription
from app.audio.level import is_silent
from app.audio.split import split_for_transcription
from app.llm import LlmError, MeetingAnalyzer, create_default_analyzer
from app.output import MeetingMetadata, write_meeting_note
from app.settings import PROJECT_ROOT, settings
from app.stt import Segment, SttError, SttProvider
from app.stt.openai import MAX_FILE_SIZE_BYTES, OpenAiSttProvider


#: 録音ヘルパーが書き出す、会議全体の音声ファイル名。
RECORDING_FILENAME = "recording.wav"

#: 文字起こし全文を残すファイル名。要約が失敗しても会議ノートを作り直せるようにする。
TRANSCRIPT_FILENAME = "transcript.txt"

#: 録音が正常に終わり、会議ノートを保存した。
EXIT_SUCCESS = 0
#: 録音または文字起こしに失敗した。録音データは調査のため残す。
EXIT_FAILED = 1
#: 発話を検出できず、会議ノートを生成しなかった。録音データは破棄する。
EXIT_NO_SPEECH = 2


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(
        description="音声ファイルを文字起こし・要約し、会議ノートをMarkdownで保存します。"
    )
    parser.add_argument("audio_path", type=Path, metavar="AUDIO_PATH", help="音声ファイルのパス")
    _add_metadata_arguments(parser)
    return parser


def build_note_parser() -> argparse.ArgumentParser:
    """保存済み文字起こしから会議ノートを作るコマンドの引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(
        description="録音中に保存した文字起こし(transcript.txt)から会議ノートを生成します。"
    )
    parser.add_argument(
        "transcript_path", type=Path, metavar="TRANSCRIPT_PATH", help="文字起こしファイルのパス"
    )
    _add_metadata_arguments(parser)
    return parser


def build_record_parser() -> argparse.ArgumentParser:
    """macOS録音コマンド用の引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(
        description="Macのシステム音声と既定マイクを録音し、会議全体のWAVとSTT用チャンクを保存します。"
    )
    _add_metadata_arguments(parser)
    return parser


def _add_metadata_arguments(parser: argparse.ArgumentParser) -> None:
    """会議ノートに付与する共通メタデータ引数を追加する。"""
    parser.add_argument("--title", help="会議タイトル（未指定時は日時から自動生成）")
    parser.add_argument(
        "--participant", dest="participants", action="append", default=[], metavar="NAME", help="参加者名（複数指定可）"
    )
    parser.add_argument(
        "--tag", dest="tags", action="append", default=[], metavar="TAG", help="タグ（複数指定可）"
    )
    parser.add_argument(
        "--keep-transcript", action="store_true", help="デバッグ用に文字起こしだけの .transcript.txt も保存する"
    )


def default_title() -> str:
    """``--title`` 未指定時の会議タイトルを生成する。"""
    return datetime.now().strftime("meeting-%Y%m%d-%H%M%S")


def format_transcript(segments: list[Segment]) -> str:
    """話者・時刻付きのSegment列をMarkdownに保存する文字起こし本文へ変換する。"""
    lines: list[str] = []
    for segment in segments:
        speaker = segment.speaker or "不明"
        timestamp = _format_timestamp_range(segment.start, segment.end)
        text = segment.text.strip()
        if text:
            lines.append(f"[{speaker}] {timestamp}: {text}")
    return "\n".join(lines)


def run_pipeline(
    args: argparse.Namespace,
    *,
    stt_provider: SttProvider | None = None,
    analyzer: MeetingAnalyzer | None = None,
    notes_dir: Path | None = None,
) -> Path:
    """文字起こしから要約、Markdown出力までを順に実行する。"""
    audio_path = args.audio_path.expanduser()

    print("文字起こし中...")
    provider = stt_provider if stt_provider is not None else OpenAiSttProvider()
    transcript = format_transcript(_transcribe_audio(audio_path, provider, report_status=print))
    if not transcript:
        raise RuntimeError("文字起こし結果が空です。")

    return _write_analysis_result(args, transcript, notes_dir=notes_dir or settings.notes_dir, analyzer=analyzer)


def run_note(
    args: argparse.Namespace,
    *,
    analyzer: MeetingAnalyzer | None = None,
    notes_dir: Path | None = None,
) -> Path:
    """録音時に保存した文字起こしから、会議ノートを作り直す。"""
    transcript_path = args.transcript_path.expanduser()
    transcript = transcript_path.read_text(encoding="utf-8").strip()
    if not transcript:
        raise ValueError(f"文字起こしが空です: {transcript_path}")

    return _write_analysis_result(args, transcript, notes_dir=notes_dir or settings.notes_dir, analyzer=analyzer)


def run_record(
    args: argparse.Namespace,
    *,
    recorder: AudioRecorder | None = None,
    stt_provider: SttProvider | None = None,
    analyzer: MeetingAnalyzer | None = None,
    notes_dir: Path | None = None,
    on_status: Callable[[str], None] | None = None,
    on_segments: Callable[[list[Segment]], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> int:
    """録音を1ファイルとして取り、停止後にまとめて文字起こしして会議ノートを保存する。"""
    _ensure_providers_configured(stt_provider, analyzer)
    output_dir = _resolve_recording_output_dir()
    recording_path = output_dir / RECORDING_FILENAME
    active_recorder = recorder if recorder is not None else MacOsAudioRecorder()

    def report_status(message: str) -> None:
        print(message)
        if on_status is not None:
            on_status(message)

    def report_warning(message: str) -> None:
        print(message)
        if on_warning is not None:
            on_warning(message)

    report_status(f"録音セッションの出力先: {output_dir}")
    report_status("録音中... 停止すると文字起こしと会議ノートを生成します。")
    exit_code = active_recorder.record(output_dir, settings.recording_chunk_seconds)

    # 権限拒否や画面スリープによる中断は、録音ヘルパーのstderrにしか理由が出ない。
    reason = active_recorder.last_error or f"終了コード {exit_code}"
    if exit_code != EXIT_SUCCESS and not recording_path.is_file():
        report_status(f"録音に失敗しました: {reason}")
        return EXIT_FAILED
    if exit_code != EXIT_SUCCESS:
        report_warning(f"録音が途中で終了しました（{reason}）。取得できたぶんで会議ノートを作成します。")

    if not recording_path.is_file() or is_silent(recording_path):
        _discard_recording(output_dir, report_status)
        report_status("発話を検出できませんでした。会議ノートは作成せず、録音データは破棄しました。")
        return EXIT_NO_SPEECH

    report_status("文字起こし中...")
    provider = stt_provider if stt_provider is not None else OpenAiSttProvider()
    try:
        segments = _transcribe_audio(recording_path, provider, report_status=report_status)
    except SttError as exc:
        # 録音は残すので、同じ音声から何度でもやり直せる。
        report_status(
            f"文字起こしに失敗しました: {exc}\n"
            f"録音は残してあります。`python -m app.cli {recording_path}` で再実行できます。"
        )
        return EXIT_FAILED
    if on_segments is not None and segments:
        on_segments(segments)

    transcript = format_transcript(segments)
    if not transcript:
        _discard_recording(output_dir, report_status)
        report_status("発話を検出できませんでした。会議ノートは作成せず、録音データは破棄しました。")
        return EXIT_NO_SPEECH

    # 要約が失敗しても作り直せるよう、文字起こしを録音ディレクトリへ残す。
    _write_transcript(output_dir / TRANSCRIPT_FILENAME, transcript)
    report_status(f"文字起こしを保存しました: {output_dir / TRANSCRIPT_FILENAME}")

    _write_analysis_result(
        args,
        transcript,
        notes_dir=notes_dir or settings.notes_dir,
        analyzer=analyzer,
        report_status=report_status,
    )
    return EXIT_SUCCESS


def _transcribe_audio(
    path: Path,
    provider: SttProvider,
    *,
    report_status: Callable[[str], None],
) -> list[Segment]:
    """音声全体を文字起こしする。API の上限を超える場合だけ分割して順に渡す。"""
    with tempfile.TemporaryDirectory(prefix="local-meeting-notes-") as work_dir:
        parts = split_for_transcription(path, parts_dir=Path(work_dir), on_status=report_status)
        segments: list[Segment] = []
        for number, part in enumerate(parts, start=1):
            if len(parts) > 1:
                report_status(f"文字起こし中... ({number}/{len(parts)})")
            audio_path = compress_for_transcription(
                part.path, max_bytes=MAX_FILE_SIZE_BYTES, work_dir=Path(work_dir), on_status=report_status
            )
            segments.extend(_shift_segments(provider.transcribe(audio_path), part.start_seconds))
        return segments


def _shift_segments(segments: list[Segment], offset: float) -> list[Segment]:
    """分割した音声の時刻を、録音全体の時刻へ補正する。"""
    if not offset:
        return segments
    return [
        replace(
            segment,
            start=None if segment.start is None else segment.start + offset,
            end=None if segment.end is None else segment.end + offset,
        )
        for segment in segments
    ]


def _ensure_providers_configured(
    stt_provider: SttProvider | None, analyzer: MeetingAnalyzer | None
) -> None:
    """録音を始める前に、設定不足で必ず失敗する状態を見つけて止める。

    1時間録音したあとにキーの不備で会議ノートを作れない、という事態を避ける。
    """
    if stt_provider is None and not settings.openai_api_key:
        raise SttError("OPENAI_API_KEY が設定されていません。.env を確認してください。")
    if analyzer is None:
        # 生成時にキーとモデルの不足を検査するため、ここで一度作って捨てる。
        create_default_analyzer()


def _write_transcript(path: Path, transcript: str) -> None:
    """文字起こし全文をファイルへ書き出す。失敗しても後続の処理は続ける。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{transcript}\n", encoding="utf-8")
    except OSError:
        return


def _discard_recording(output_dir: Path, report_status: Callable[[str], None]) -> None:
    """会議ノートにならなかった録音データを削除する。失敗しても処理は続ける。"""
    if not output_dir.exists():
        return
    try:
        shutil.rmtree(output_dir)
    except OSError as exc:
        report_status(f"録音データを削除できませんでした: {output_dir}（{exc}）")


def _resolve_recording_output_dir() -> Path:
    """録音出力先を解決し、開始日時付きのディレクトリ名を生成する。"""
    directory_name = datetime.now().strftime("recordings_%Y%m%d%H%M")
    return PROJECT_ROOT / "data" / directory_name


def _write_analysis_result(
    args: argparse.Namespace,
    transcript: str,
    *,
    notes_dir: Path,
    analyzer: MeetingAnalyzer | None,
    report_status: Callable[[str], None] = print,
) -> Path:
    """文字起こし全文を分析して会議ノートを保存する。"""
    report_status("要約・タスクを抽出中...")
    meeting_analyzer = analyzer if analyzer is not None else create_default_analyzer()
    analysis = meeting_analyzer.analyze(transcript)

    report_status("Markdownを書き出し中...")
    metadata = MeetingMetadata(
        title=args.title or default_title(),
        date=date.today(),
        participants=args.participants,
        tags=args.tags,
    )
    output_path = write_meeting_note(metadata, analysis, transcript, notes_dir=notes_dir)

    if args.keep_transcript:
        transcript_path = output_path.with_suffix(".transcript.txt")
        transcript_path.write_text(transcript + "\n", encoding="utf-8")
        report_status(f"デバッグ用文字起こし: {transcript_path}")

    report_status(f"会議ノートを保存しました: {output_path}")
    return output_path


def _format_timestamp_range(start: float | None, end: float | None) -> str:
    """開始・終了秒を表示用の時刻範囲に変換する。"""
    if start is None and end is None:
        return "時刻不明"
    start_text = f"{start:.2f}s" if start is not None else "不明"
    end_text = f"{end:.2f}s" if end is not None else "不明"
    return f"{start_text}–{end_text}"


def main(argv: Sequence[str] | None = None) -> int:
    """CLIを実行する。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments[:1] == ["record"]:
            args = build_record_parser().parse_args(arguments[1:])
            return run_record(args)
        if arguments[:1] == ["note"]:
            run_note(build_note_parser().parse_args(arguments[1:]))
            return 0
        args = build_parser().parse_args(arguments)
        run_pipeline(args)
    except (AudioCaptureError, SttError, LlmError, OSError, ValueError) as exc:
        # 想定済みの失敗は、traceback ではなく理由だけを表示する。
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

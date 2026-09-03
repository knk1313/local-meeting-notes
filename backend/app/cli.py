"""音声ファイルから会議ノートを生成するコマンドラインインターフェース。"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from app.llm import MeetingAnalyzer, create_default_analyzer
from app.output import MeetingMetadata, write_meeting_note
from app.settings import PROJECT_ROOT, settings
from app.stt import Segment, SttProvider
from app.stt.openai import OpenAiSttProvider


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(
        description="音声ファイルを文字起こし・要約し、会議ノートをMarkdownで保存します。"
    )
    parser.add_argument("audio_path", type=Path, metavar="AUDIO_PATH", help="音声ファイルのパス")
    parser.add_argument("--title", help="会議タイトル（未指定時は日時から自動生成）")
    parser.add_argument(
        "--participant", dest="participants", action="append", default=[], metavar="NAME", help="参加者名（複数指定可）"
    )
    parser.add_argument(
        "--tag", dest="tags", action="append", default=[], metavar="TAG", help="タグ（複数指定可）"
    )
    parser.add_argument("--notes-dir", type=Path, help="出力先ディレクトリ（未指定時は NOTES_DIR）")
    parser.add_argument(
        "--keep-transcript", action="store_true", help="デバッグ用に文字起こしだけの .transcript.txt も保存する"
    )
    return parser


def default_title() -> str:
    """``--title`` 未指定時の会議タイトルを生成する。"""
    return datetime.now().strftime("meeting-%Y%m%d-%H%M%S")


def resolve_notes_dir(notes_dir: Path | None) -> Path:
    """CLI指定値または設定済みの出力先ディレクトリを解決する。"""
    if notes_dir is None:
        return settings.notes_dir
    if notes_dir.is_absolute():
        return notes_dir
    return PROJECT_ROOT / notes_dir


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
) -> Path:
    """文字起こしから要約、Markdown出力までを順に実行する。"""
    audio_path = args.audio_path.expanduser()
    notes_dir = resolve_notes_dir(args.notes_dir)

    print("文字起こし中...")
    provider = stt_provider if stt_provider is not None else OpenAiSttProvider()
    transcript = format_transcript(provider.transcribe(audio_path))
    if not transcript:
        raise RuntimeError("文字起こし結果が空です。")

    print("要約・タスクを抽出中...")
    meeting_analyzer = analyzer if analyzer is not None else create_default_analyzer()
    analysis = meeting_analyzer.analyze(transcript)

    print("Markdownを書き出し中...")
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
        print(f"デバッグ用文字起こし: {transcript_path}")

    print(f"会議ノートを保存しました: {output_path}")
    return output_path


def _format_timestamp_range(start: float | None, end: float | None) -> str:
    """開始・終了秒を表示用の時刻範囲に変換する。"""
    if start is None and end is None:
        return "時刻不明"
    start_text = f"{start:.2f}s" if start is not None else "不明"
    end_text = f"{end:.2f}s" if end is not None else "不明"
    return f"{start_text}–{end_text}"


def main(argv: Sequence[str] | None = None) -> int:
    """CLIを実行する。``start`` は従来の呼び出し方との互換エイリアス。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["start"]:
        arguments.pop(0)

    args = build_parser().parse_args(arguments)
    run_pipeline(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

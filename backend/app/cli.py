"""会議ノートのコマンドラインインターフェース。"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Sequence

from app.settings import PROJECT_ROOT, settings


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数パーサーを作成する。"""
    parser = argparse.ArgumentParser(description="ローカル会議ノートを開始します。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="会議ノートの記録を開始する")
    start_parser.add_argument("--title", help="会議タイトル（未指定時は日時から自動生成）")
    start_parser.add_argument(
        "--participant",
        dest="participants",
        action="append",
        default=[],
        metavar="NAME",
        help="参加者名（複数指定可）",
    )
    start_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        metavar="TAG",
        help="タグ（複数指定可）",
    )
    start_parser.add_argument(
        "--notes-dir",
        type=Path,
        help="出力先ディレクトリ（未指定時は NOTES_DIR）",
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


def run_start(args: argparse.Namespace) -> int:
    """録音実装までの暫定処理として会議設定を解決・表示する。"""
    title = args.title or default_title()
    notes_dir = resolve_notes_dir(args.notes_dir)

    print("会議ノートの開始準備ができました。")
    print(f"タイトル: {title}")
    print(f"参加者: {', '.join(args.participants) or '未指定'}")
    print(f"タグ: {', '.join(args.tags) or '未指定'}")
    print(f"出力先: {notes_dir}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLIを実行する。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        return run_start(args)

    parser.error(f"未対応のコマンドです: {args.command}")
    return 2

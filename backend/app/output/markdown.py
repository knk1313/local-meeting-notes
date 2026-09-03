"""会議分析結果をMarkdownファイルへ変換して保存する。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.llm import MeetingAnalysis
from app.settings import settings


TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "meeting_note.md"
INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class MeetingMetadata:
    """会議ノートのfrontmatterに記録するメタデータ。"""

    title: str
    date: date
    participants: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def render_meeting_note(
    metadata: MeetingMetadata,
    analysis: MeetingAnalysis,
    transcript: str,
    *,
    template_path: Path = TEMPLATE_PATH,
) -> str:
    """メタデータ・会議分析・文字起こしからMarkdown本文を生成する。"""
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"出力テンプレートを読み込めません: {template_path}") from exc

    values = {
        "title": json.dumps(metadata.title, ensure_ascii=False),
        "date": metadata.date.isoformat(),
        "participants": json.dumps(metadata.participants, ensure_ascii=False),
        "tags": json.dumps(metadata.tags, ensure_ascii=False),
        "summary": _render_list(analysis.summary),
        "decisions": _render_list(analysis.decisions),
        "open_questions": _render_list(analysis.open_questions),
        "tasks": _render_tasks(analysis),
        "transcript": transcript.strip(),
    }

    for name, value in values.items():
        placeholder = f"{{{{{name}}}}}"
        if placeholder not in template:
            raise ValueError(f"出力テンプレートに {placeholder} がありません: {template_path}")
        template = template.replace(placeholder, value)

    return template.rstrip() + "\n"


def write_meeting_note(
    metadata: MeetingMetadata,
    analysis: MeetingAnalysis,
    transcript: str,
    *,
    notes_dir: Path | None = None,
) -> Path:
    """会議ノートをNOTES_DIRへ書き出し、保存先パスを返す。"""
    destination = notes_dir if notes_dir is not None else settings.notes_dir
    destination.mkdir(parents=True, exist_ok=True)
    content = render_meeting_note(metadata, analysis, transcript)

    for suffix in range(1, 10_000):
        candidate = destination / _filename(metadata, suffix)
        try:
            with candidate.open("x", encoding="utf-8", newline="\n") as output_file:
                output_file.write(content)
        except FileExistsError:
            continue
        return candidate

    raise RuntimeError("会議ノートの保存先ファイル名を決定できません。")


def _render_list(items: list[str]) -> str:
    """文字列一覧をMarkdownの箇条書きへ変換する。"""
    if not items:
        return "なし"
    return "\n".join(f"- {item}" for item in items)


def _render_tasks(analysis: MeetingAnalysis) -> str:
    """タスク一覧をMarkdownのチェックボックス形式へ変換する。"""
    if not analysis.tasks:
        return "なし"

    rendered_tasks: list[str] = []
    for task in analysis.tasks:
        details = []
        if task.assignee:
            details.append(f"担当: {task.assignee}")
        if task.due_date:
            details.append(f"期限: {task.due_date}")
        detail_text = f"（{'、'.join(details)}）" if details else ""
        rendered_tasks.append(f"- [ ] {task.title}{detail_text}")
    return "\n".join(rendered_tasks)


def _filename(metadata: MeetingMetadata, suffix: int) -> str:
    """日付・会議名・連番から衝突しない候補ファイル名を生成する。"""
    title = INVALID_FILENAME_CHARACTERS.sub("-", metadata.title).strip(" .-")
    normalized_title = re.sub(r"[-\s]+", "-", title) or "meeting"
    serial = "" if suffix == 1 else f"-{suffix}"
    return f"{metadata.date.isoformat()}-{normalized_title}{serial}.md"

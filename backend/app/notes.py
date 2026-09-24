"""保存済み会議ノートの一覧・本文を読み取る処理。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# 文字起こし行に埋め込まれた「12.00s–34.50s」形式の時間範囲。
TIMESTAMP_RANGE = re.compile(r"(\d+(?:\.\d+)?)s\s*[-–—]\s*(\d+(?:\.\d+)?)s")


@dataclass(frozen=True)
class StoredNote:
    """Markdown会議ノートを画面へ返すための情報。"""

    id: str
    title: str
    date: str
    participants: list[str]
    tags: list[str]
    excerpt: str
    duration_seconds: float | None
    markdown: str


def list_notes(notes_dir: Path) -> list[StoredNote]:
    """ノートを新しい日付順に読み込む。壊れたファイルは一覧表示を妨げない。"""
    if not notes_dir.exists():
        return []
    notes: list[StoredNote] = []
    for path in sorted(notes_dir.glob("*.md"), reverse=True):
        try:
            notes.append(_read_note(path))
        except (OSError, ValueError):
            continue
    return notes


def get_note(notes_dir: Path, note_id: str) -> StoredNote:
    """ファイル名のstemをIDとして、単一ノートを安全に取得する。"""
    if Path(note_id).name != note_id or note_id in {"", ".", ".."}:
        raise LookupError("指定された会議ノートが見つかりません。")
    path = notes_dir / f"{note_id}.md"
    if not path.is_file():
        raise LookupError("指定された会議ノートが見つかりません。")
    return _read_note(path)


def _read_note(path: Path) -> StoredNote:
    content = path.read_text(encoding="utf-8")
    metadata, markdown = _split_frontmatter(content)
    title = _string_metadata(metadata, "title") or path.stem
    date = _string_metadata(metadata, "date") or path.stem[:10]
    return StoredNote(
        id=path.stem,
        title=title,
        date=date,
        participants=_list_metadata(metadata, "participants"),
        tags=_list_metadata(metadata, "tags"),
        excerpt=_excerpt(markdown),
        duration_seconds=_duration_seconds(markdown),
        markdown=markdown,
    )


def _split_frontmatter(content: str) -> tuple[dict[str, object], str]:
    if not content.startswith("---\n"):
        return {}, content
    frontmatter, separator, rest = content[4:].partition("\n---\n")
    if not separator:
        return {}, content
    values: dict[str, object] = {}
    for line in frontmatter.splitlines():
        key, delimiter, value = line.partition(":")
        if not delimiter:
            continue
        values[key.strip()] = _parse_value(value.strip())
    return values, rest


def _parse_value(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip('"')


def _string_metadata(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _list_metadata(metadata: dict[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _duration_seconds(markdown: str) -> float | None:
    """文字起こしのタイムスタンプから会議の長さを推定する。無い場合はNone。"""
    ends = [float(match.group(2)) for match in TIMESTAMP_RANGE.finditer(markdown)]
    return max(ends) if ends else None


def _excerpt(markdown: str) -> str:
    for line in markdown.splitlines():
        candidate = line.removeprefix("- ").strip()
        if candidate and not candidate.startswith("#"):
            return candidate
    return "要約はありません。"

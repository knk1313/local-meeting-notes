"""保存済み会議ノートの読み取りとAPIのユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api
from app.notes import get_note, list_notes


NOTE = """---
title: "定例MTG"
date: 2026-09-10
participants: ["田中", "鈴木"]
tags: ["project-a"]
---

## 要約

- 解析対象の範囲を確認した。

## タスク

- [ ] 仕様書を作成する

## 文字起こし

[A] 0.00s–12.50s: 本日の論点を確認します。
[B] 12.75s–90.00s: 次回までに整理します。
"""


class NotesTest(unittest.TestCase):
    """NOTES_DIRのMarkdownを一覧・本文として読み出せることを検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.notes_dir = Path(self._temporary.name)
        (self.notes_dir / "2026-09-10-定例MTG.md").write_text(NOTE, encoding="utf-8")
        self.addCleanup(self._temporary.cleanup)

    def test_lists_note_metadata(self) -> None:
        """frontmatterと要約の先頭行を一覧向けに取り出す。"""
        notes = list_notes(self.notes_dir)

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].id, "2026-09-10-定例MTG")
        self.assertEqual(notes[0].title, "定例MTG")
        self.assertEqual(notes[0].date, "2026-09-10")
        self.assertEqual(notes[0].participants, ["田中", "鈴木"])
        self.assertEqual(notes[0].tags, ["project-a"])
        self.assertEqual(notes[0].excerpt, "解析対象の範囲を確認した。")
        self.assertEqual(notes[0].duration_seconds, 90.0)

    def test_returns_markdown_body_without_frontmatter(self) -> None:
        """本文はfrontmatterを除いたMarkdownとして返す。"""
        note = get_note(self.notes_dir, "2026-09-10-定例MTG")

        self.assertTrue(note.markdown.startswith("\n## 要約"))
        self.assertIn("- [ ] 仕様書を作成する", note.markdown)

    def test_rejects_path_traversal(self) -> None:
        """ディレクトリを跨ぐIDは受け付けない。"""
        with self.assertRaises(LookupError):
            get_note(self.notes_dir, "../secret")

    def test_missing_notes_dir_is_empty(self) -> None:
        """NOTES_DIRが未作成でも一覧は空で返す。"""
        self.assertEqual(list_notes(self.notes_dir / "missing"), [])


class NotesApiTest(unittest.TestCase):
    """会議ノートAPIがNOTES_DIRの内容を返すことを検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.notes_dir = Path(self._temporary.name)
        (self.notes_dir / "2026-09-10-定例MTG.md").write_text(NOTE, encoding="utf-8")
        self.addCleanup(self._temporary.cleanup)
        self.client = TestClient(api.app)
        patcher = patch.object(api, "settings", replace(api.settings, notes_dir=self.notes_dir))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lists_and_reads_notes(self) -> None:
        """一覧と本文をAPI経由で取得できる。"""
        listed = self.client.get("/api/notes")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["title"], "定例MTG")
        self.assertEqual(listed.json()[0]["duration_seconds"], 90.0)

        detail = self.client.get("/api/notes/2026-09-10-定例MTG")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("## タスク", detail.json()["markdown"])

    def test_returns_404_for_unknown_note(self) -> None:
        """存在しないノートIDは404として返す。"""
        response = self.client.get("/api/notes/unknown")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "指定された会議ノートが見つかりません。")


if __name__ == "__main__":
    unittest.main()

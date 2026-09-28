"""会議ノートのMarkdown生成のユニットテスト。"""

from __future__ import annotations

import unittest
from datetime import date

from app.llm import MeetingAnalysis, Task
from app.output.markdown import MeetingMetadata, render_meeting_note


class RenderMeetingNoteTest(unittest.TestCase):
    """テンプレートへの差し込みを検証する。"""

    def _render(self, analysis: MeetingAnalysis, title: str = "定例MTG") -> str:
        return render_meeting_note(
            MeetingMetadata(title=title, date=date(2026, 9, 28)),
            analysis,
            "[A] 0.00s–1.00s: 文字起こし本文です",
        )

    def test_writes_each_section(self) -> None:
        """要約・決定事項・タスク・文字起こしをそれぞれの位置へ差し込む。"""
        note = self._render(
            MeetingAnalysis(
                summary=["範囲を確認した。"],
                decisions=["仕様書を作る。"],
                open_questions=["担当は未定。"],
                tasks=[Task(title="仕様書を作成する", assignee="田中", due_date="次回")],
            )
        )

        self.assertIn('title: "定例MTG"', note)
        self.assertIn("- 範囲を確認した。", note)
        self.assertIn("- [ ] 仕様書を作成する（担当: 田中、期限: 次回）", note)
        self.assertIn("[A] 0.00s–1.00s: 文字起こし本文です", note)

    def test_does_not_expand_placeholders_inside_values(self) -> None:
        """差し込んだ文字列の中のプレースホルダは展開しない。"""
        note = self._render(
            MeetingAnalysis(
                summary=["{{transcript}} の扱いについて話した。"],
                decisions=[],
                open_questions=[],
                tasks=[],
            )
        )

        summary_section = note.split("### 決定事項")[0]
        self.assertIn("{{transcript}} の扱いについて話した。", summary_section)
        self.assertNotIn("文字起こし本文です", summary_section)


if __name__ == "__main__":
    unittest.main()

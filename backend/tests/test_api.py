"""ローカル会議APIのユニットテスト。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import api


class ApiTest(unittest.TestCase):
    """録音ヘルパーを起動せず、会議セッションAPIを検証する。"""

    def setUp(self) -> None:
        self.client = TestClient(api.app)
        self.previous_service = api.service
        api.service = api.MeetingService()

    def tearDown(self) -> None:
        api.service = self.previous_service

    def test_starts_and_returns_current_meeting(self) -> None:
        """会議名・参加者を受け取り、現在の会議として返せる。"""
        with patch.object(api.MeetingSession, "start"):
            response = self.client.post(
                "/api/meetings",
                json={"title": "定例MTG", "participants": ["田中", " 鈴木 "]},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["title"], "定例MTG")
        self.assertEqual(response.json()["participants"], ["田中", "鈴木"])
        self.assertEqual(response.json()["phase"], "recording")

        current = self.client.get("/api/meetings/current")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["id"], response.json()["id"])

        meeting = self.client.get(f"/api/meetings/{response.json()['id']}")
        self.assertEqual(meeting.status_code, 200)
        self.assertEqual(meeting.json()["title"], "定例MTG")

    def test_maps_exit_code_to_phase(self) -> None:
        """録音処理の終了コードから、会議の最終状態を決める。"""
        for exit_code, phase in [(api.EXIT_SUCCESS, "completed"), (api.EXIT_NO_SPEECH, "no_speech"), (9, "failed")]:
            with self.subTest(exit_code=exit_code):
                session = api.MeetingSession(id="test", title="定例MTG", participants=[])

                with patch("app.api.run_record", return_value=exit_code):
                    session._run()

                self.assertEqual(session.snapshot().phase, phase)

    def test_exposes_partial_transcription_warning(self) -> None:
        """一部のチャンクが文字起こしできなかった場合、警告を画面へ返す。"""
        session = api.MeetingSession(id="test", title="定例MTG", participants=[])

        def run_with_warning(*_args: object, **keywords: object) -> int:
            keywords["on_warning"](" 欠落があります。")  # type: ignore[operator]
            return api.EXIT_SUCCESS

        with patch("app.api.run_record", side_effect=run_with_warning):
            session._run()

        self.assertEqual(session.snapshot().warning, " 欠落があります。")
        self.assertEqual(session.snapshot().phase, "completed")

    def test_keeps_the_status_when_stopping_after_recording_finished(self) -> None:
        """文字起こしに入ったあとの停止要求では、表示を書き換えない。"""
        session = api.MeetingSession(id="test", title="定例MTG", participants=[])
        session.phase = "transcribing"
        session.message = "文字起こしAPIへ送信中..."

        with patch.object(session.recorder, "request_stop") as request_stop:
            session.request_stop()

        self.assertEqual(session.snapshot().message, "文字起こしAPIへ送信中...")
        request_stop.assert_not_called()

    def test_tracks_progress_from_callbacks(self) -> None:
        """会議の段階と保存先は、メッセージ文言ではなく通知から決める。"""
        session = api.MeetingSession(id="test", title="定例MTG", participants=[])

        def run_with_progress(*_args: object, **keywords: object) -> int:
            keywords["on_stage"]("transcribing")  # type: ignore[operator]
            self.assertEqual(session.snapshot().phase, "transcribing")
            keywords["on_stage"]("summarizing")  # type: ignore[operator]
            keywords["on_note"](Path("/tmp/2026-09-28-定例MTG.md"))  # type: ignore[operator]
            return api.EXIT_SUCCESS

        with patch("app.api.run_record", side_effect=run_with_progress):
            session._run()

        snapshot = session.snapshot()
        self.assertEqual(snapshot.phase, "completed")
        self.assertEqual(snapshot.note_path, "/tmp/2026-09-28-定例MTG.md")


if __name__ == "__main__":
    unittest.main()

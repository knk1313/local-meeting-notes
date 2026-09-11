"""ローカル会議APIのユニットテスト。"""

from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()

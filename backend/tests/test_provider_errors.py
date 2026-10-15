"""STT・LLMプロバイダの失敗理由の伝え方を検証するユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
from anthropic import APIStatusError as AnthropicApiStatusError
from anthropic import AuthenticationError as AnthropicAuthenticationError
from openai import AuthenticationError as OpenAiAuthenticationError
from openai import RateLimitError

from app.llm import LlmError
from app.llm.anthropic import ClaudeMeetingAnalyzer
from app.stt import SttError
from app.stt.openai import OpenAiSttProvider
from wav_fixtures import tone, write_float_wav


def _response(status_code: int) -> httpx.Response:
    """SDKの例外が必要とする最小限のHTTPレスポンスを作る。"""
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "https://example.test"))


class OpenAiSttErrorTest(unittest.TestCase):
    """OpenAIの失敗理由を、利用者が次の行動を取れる文言へ変換する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.audio_path = Path(self._temporary.name) / "recording.wav"
        write_float_wav(self.audio_path, tone(seconds=0.1))

    def _transcribe_raising(self, error: Exception) -> str:
        client = MagicMock()
        client.audio.transcriptions.create.side_effect = error
        with self.assertRaises(SttError) as raised:
            OpenAiSttProvider(client=client).transcribe(self.audio_path)
        return str(raised.exception)

    def test_reports_insufficient_quota(self) -> None:
        """残高不足は、レート制限と分けてクレジット不足として伝える。"""
        error = RateLimitError(
            "quota", response=_response(429), body={"error": {"code": "insufficient_quota"}}
        )

        self.assertIn("クレジット残高が不足しています", self._transcribe_raising(error))

    def test_reports_rate_limit(self) -> None:
        """一時的なレート制限は、待てば回復するものとして伝える。"""
        error = RateLimitError("slow down", response=_response(429), body={"error": {"code": "rate_limit_exceeded"}})

        self.assertIn("レート制限", self._transcribe_raising(error))

    def test_reports_invalid_api_key(self) -> None:
        """キーが拒否された場合は、設定を見直す案内を出す。"""
        error = OpenAiAuthenticationError("bad key", response=_response(401), body=None)

        self.assertIn("OPENAI_API_KEY", self._transcribe_raising(error))


class ClaudeAnalyzerErrorTest(unittest.TestCase):
    """Anthropicの失敗理由を、利用者が次の行動を取れる文言へ変換する。"""

    def _analyze_raising(self, error: Exception) -> str:
        client = MagicMock()
        client.messages.create.side_effect = error
        analyzer = ClaudeMeetingAnalyzer(model="claude-test", client=client)
        with self.assertRaises(LlmError) as raised:
            analyzer.analyze("[A] 0.00s–1.00s: テストです")
        return str(raised.exception)

    def test_reports_insufficient_credit(self) -> None:
        """残高不足は、支払い設定を確認する案内として伝える。"""
        error = AnthropicApiStatusError(
            "Your credit balance is too low to access the Anthropic API",
            response=_response(400),
            body=None,
        )

        self.assertIn("クレジット残高が不足しています", self._analyze_raising(error))

    def test_reports_invalid_api_key(self) -> None:
        """キーが拒否された場合は、設定を見直す案内を出す。"""
        error = AnthropicAuthenticationError("bad key", response=_response(401), body=None)

        self.assertIn("ANTHROPIC_API_KEY", self._analyze_raising(error))


class OpenAiSttStreamTest(unittest.TestCase):
    """ストリームで受け取った区間を組み立て、進み具合を伝えることを検証する。"""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.audio_path = Path(self._temporary.name) / "recording.wav"
        write_float_wav(self.audio_path, tone(seconds=0.1))

    def _transcribe(self, events: list[SimpleNamespace]) -> tuple[list, list[float]]:
        client = MagicMock()
        client.audio.transcriptions.create.return_value = iter(events)
        progress: list[float] = []
        segments = OpenAiSttProvider(client=client).transcribe(self.audio_path, on_progress=progress.append)
        self.assertTrue(client.audio.transcriptions.create.call_args.kwargs["stream"])
        # 自動判定で相づちが英語にならないよう、日本語を指定して送る。
        self.assertEqual(client.audio.transcriptions.create.call_args.kwargs["language"], "ja")
        return segments, progress

    def test_builds_segments_and_reports_progress(self) -> None:
        """区間が届くたびに組み立て、その終了時刻を進み具合として渡す。"""
        segments, progress = self._transcribe(
            [
                SimpleNamespace(type="transcript.text.segment", speaker="A", start=0.0, end=4.5, text="前半"),
                SimpleNamespace(type="transcript.text.segment", speaker="B", start=4.5, end=9.0, text="後半"),
                SimpleNamespace(type="transcript.text.done", text="前半後半"),
            ]
        )

        self.assertEqual([(s.speaker, s.start, s.end, s.text) for s in segments], [("A", 0.0, 4.5, "前半"), ("B", 4.5, 9.0, "後半")])
        self.assertEqual(progress, [4.5, 9.0])

    def test_rejects_text_without_speaker_segments(self) -> None:
        """本文だけで区間が無い応答は、発話なしと取り違えず失敗にする。"""
        with self.assertRaises(SttError):
            self._transcribe([SimpleNamespace(type="transcript.text.done", text="話者分離なしの本文")])

    def test_returns_empty_for_silence(self) -> None:
        """本文も区間も無ければ、発話なしとして空を返す。"""
        segments, progress = self._transcribe([SimpleNamespace(type="transcript.text.done", text="")])

        self.assertEqual((segments, progress), ([], []))


if __name__ == "__main__":
    unittest.main()

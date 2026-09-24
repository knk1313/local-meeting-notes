"""STT・LLMプロバイダの失敗理由の伝え方を検証するユニットテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()

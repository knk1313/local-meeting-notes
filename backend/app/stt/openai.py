"""OpenAI Audio Transcriptions API を使った STT プロバイダ実装。

話者分離に対応した `gpt-4o-transcribe-diarize` を既定モデルとし、
`response_format="diarized_json"` で話者ラベル付きのセグメントを取得する。

API キーは環境変数 `OPENAI_API_KEY` から読み込む
(コードにハードコードせず、`.env` 経由で与える)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openai import AuthenticationError, OpenAI, OpenAIError, RateLimitError

from app.stt.base import Segment, SttError, SttProvider

#: 話者分離に対応した既定モデル。
DEFAULT_MODEL = "gpt-4o-transcribe-diarize"

#: 残高不足を表す OpenAI のエラーコード。リトライでは回復しない。
INSUFFICIENT_QUOTA_CODE = "insufficient_quota"

#: API が受け付けるファイルサイズの上限 (25MB)。
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024

#: API が受け付ける音声フォーマットの拡張子。
SUPPORTED_SUFFIXES = frozenset(
    {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
)


class OpenAiSttProvider(SttProvider):
    """OpenAI による文字起こしプロバイダ。

    受け取った音声ファイルを 1 本まるごと API に渡す。長さや容量の上限に
    合わせた分割・圧縮は呼び出し側（app.audio）で行う。
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client: OpenAI | None = None,
    ) -> None:
        """
        引数:
            model: 使用するモデル名。既定は `gpt-4o-transcribe-diarize`。
            client: 使用する OpenAI クライアント。未指定なら環境変数から生成する。
        """
        self._model = model
        self._client = client if client is not None else OpenAI()

    def transcribe(self, path: Path) -> list[Segment]:
        """音声ファイルを文字起こしし、話者ラベル付きの `Segment` 列を返す。"""
        self._validate(path)

        try:
            with path.open("rb") as audio:
                response = self._client.audio.transcriptions.create(
                    file=audio,
                    model=self._model,
                    response_format="diarized_json",
                    # 30 秒を超える音声では指定が必要。
                    chunking_strategy="auto",
                )
        except AuthenticationError as exc:
            raise SttError(
                "OpenAI APIキーが拒否されました。.env の OPENAI_API_KEY を確認してください。"
            ) from exc
        except RateLimitError as exc:
            # 残高不足はリトライしても回復しないため、レート制限とは分けて伝える。
            if _error_code(exc) == INSUFFICIENT_QUOTA_CODE:
                raise SttError(
                    "OpenAIのクレジット残高が不足しています。"
                    "https://platform.openai.com/settings/organization/billing で確認してください。"
                ) from exc
            raise SttError(
                "OpenAI APIのレート制限に達しました。しばらく待ってから再実行してください。"
            ) from exc
        except OpenAIError as exc:
            # 理由が分からないと対処できないため、APIの説明をそのまま伝える。
            raise SttError(f"OpenAI の文字起こしに失敗しました: {_error_message(exc)}") from exc

        return _to_segments(response)

    def _validate(self, path: Path) -> None:
        """API に渡す前にローカルで検査し、明確なエラーにして落とす。"""
        if not path.is_file():
            raise SttError(f"音声ファイルが見つかりません: {path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise SttError(
                f"対応していない音声フォーマットです: {suffix or '(拡張子なし)'} "
                f"(対応: {supported})"
            )

        size = path.stat().st_size
        if size == 0:
            raise SttError(f"音声ファイルが空です: {path}")
        if size > MAX_FILE_SIZE_BYTES:
            raise SttError(
                f"音声ファイルが上限 {MAX_FILE_SIZE_BYTES} バイトを超えています "
                f"({size} バイト): {path}"
            )


def _error_code(error: OpenAIError) -> str | None:
    """OpenAIのエラー応答からエラーコードを取り出す。取れない場合はNone。"""
    code = _error_detail(error, "code")
    if code is not None:
        return code
    attribute = getattr(error, "code", None)
    return attribute if isinstance(attribute, str) else None


def _error_message(error: OpenAIError) -> str:
    """OpenAIのエラー応答から、利用者に見せる説明を取り出す。"""
    return _error_detail(error, "message") or str(error)


def _error_detail(error: OpenAIError, key: str) -> str | None:
    """エラー応答の本文から指定のフィールドを取り出す。

    ``{"error": {...}}`` で包まれている場合と、直接入っている場合の両方を見る。
    """
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None
    for candidate in (body.get("error"), body):
        if isinstance(candidate, dict) and isinstance(candidate.get(key), str):
            return candidate[key]
    return None


def _to_segments(response: Any) -> list[Segment]:
    """`diarized_json` のレスポンスを `Segment` 列に変換する。"""
    raw_segments = getattr(response, "segments", None)
    if raw_segments is None:
        raise SttError(
            "OpenAI のレスポンスに segments が含まれていません。"
            "話者分離に対応したモデルを指定しているか確認してください。"
        )

    return [
        Segment(
            speaker=getattr(segment, "speaker", None),
            start=getattr(segment, "start", None),
            end=getattr(segment, "end", None),
            text=getattr(segment, "text", ""),
        )
        for segment in raw_segments
    ]

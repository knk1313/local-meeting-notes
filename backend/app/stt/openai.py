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

from app.stt.base import ProgressCallback, Segment, SttError, SttProvider

#: 話者分離に対応した既定モデル。
DEFAULT_MODEL = "gpt-4o-transcribe-diarize"

#: 話者付きの区間が1つ確定するたびに届くストリームのイベント。
SEGMENT_EVENT = "transcript.text.segment"

#: 文字起こしの完了を表すストリームのイベント。
DONE_EVENT = "transcript.text.done"

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

    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
        """音声ファイルを文字起こしし、話者ラベル付きの `Segment` 列を返す。

        結果はストリームで受け取る。区間が確定するたびにその終了時刻を
        ``on_progress`` へ渡すため、長い音声でも進み具合が分かる。
        """
        self._validate(path)

        segments: list[Segment] = []
        done_text = ""
        try:
            with path.open("rb") as audio:
                stream = self._client.audio.transcriptions.create(
                    file=audio,
                    model=self._model,
                    response_format="diarized_json",
                    # 30 秒を超える音声では指定が必要。
                    chunking_strategy="auto",
                    stream=True,
                )
                for event in stream:
                    event_type = getattr(event, "type", None)
                    if event_type == SEGMENT_EVENT:
                        segment = _to_segment(event)
                        segments.append(segment)
                        if on_progress is not None and segment.end is not None:
                            on_progress(segment.end)
                    elif event_type == DONE_EVENT:
                        done_text = getattr(event, "text", "") or ""
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

        # 本文があるのに区間が届かないのは、話者分離に対応しないモデルの場合。
        # 空のまま返すと「発話なし」として録音を破棄してしまうため、失敗として扱う。
        if not segments and done_text.strip():
            raise SttError(
                "OpenAI の応答に話者付きの区間が含まれていません。"
                "話者分離に対応したモデルを指定しているか確認してください。"
            )
        return segments

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


def _to_segment(event: Any) -> Segment:
    """ストリームの区間イベントを `Segment` に変換する。"""
    return Segment(
        speaker=getattr(event, "speaker", None),
        start=getattr(event, "start", None),
        end=getattr(event, "end", None),
        text=getattr(event, "text", ""),
    )

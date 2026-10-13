"""録音プロバイダが実装する共通インターフェース。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class AudioCaptureError(RuntimeError):
    """録音の開始・停止・音声チャンク出力に失敗したことを表す例外。"""


class AudioRecorder(ABC):
    """システム音声とマイク音声を録音するプロバイダ。"""

    @abstractmethod
    def record(self, output_dir: Path, block_seconds: int) -> int:
        """録音を開始し、終了時のプロセス終了コードを返す。"""

    @property
    def last_error(self) -> str | None:
        """録音が失敗した理由。取得できない実装ではNoneを返す。"""
        return None

"""STT プロバイダが共通で実装するインターフェース。

`cli.py` などの上位層は本モジュールの `SttProvider` / `Segment` のみに依存し、
OpenAI や Google といったプロバイダ固有の詳細を意識しない。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


#: 文字起こしが済んだ位置（音声先頭からの秒）を受け取るコールバック。
ProgressCallback = Callable[[float], None]


class SttError(RuntimeError):
    """文字起こしに失敗したことを表す例外。

    プロバイダ固有の例外は本例外に包んで送出し、上位層がプロバイダ固有の
    例外型を import しなくて済むようにする。
    """


@dataclass(frozen=True)
class Segment:
    """話者ラベル付きの文字起こし断片。

    属性:
        speaker: 話者ラベル。プロバイダが返す ID をそのまま保持する
            (OpenAI なら "A" / "B" ...)。表示用の表記への変換は上位層で行う。
            話者分離に対応しないプロバイダ・モデルでは None。
        start: 音声先頭からの開始秒。取得できない場合は None。
        end: 音声先頭からの終了秒。取得できない場合は None。
        text: 当該区間の文字起こしテキスト。
    """

    speaker: str | None
    start: float | None
    end: float | None
    text: str


class SttProvider(ABC):
    """音声ファイルを文字起こしするプロバイダ。"""

    @abstractmethod
    def transcribe(self, path: Path, *, on_progress: ProgressCallback | None = None) -> list[Segment]:
        """音声ファイル 1 本を文字起こしし、時系列順の `Segment` 列を返す。

        引数:
            path: 文字起こし対象の音声ファイル。
            on_progress: 文字起こしが済んだ位置（秒）を随時受け取る。
                途中経過を返せない実装は呼ばなくてよい。

        戻り値:
            開始時刻の昇順に並んだ `Segment` のリスト。

        例外:
            SttError: ファイルが不正、またはプロバイダ呼び出しに失敗した場合。
        """

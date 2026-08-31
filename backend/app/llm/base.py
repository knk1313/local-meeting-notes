"""会議の要約・タスク抽出で共通に使うデータ構造。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LlmError(RuntimeError):
    """LLMによる会議分析に失敗したことを表す例外。"""


@dataclass(frozen=True)
class Task:
    """会議から抽出した実行タスク。"""

    title: str
    assignee: str | None
    due_date: str | None


@dataclass(frozen=True)
class MeetingAnalysis:
    """会議の要約と、そこから抽出した情報。"""

    summary: list[str]
    decisions: list[str]
    open_questions: list[str]
    tasks: list[Task]


class MeetingAnalyzer(ABC):
    """文字起こしを会議分析結果へ変換するインターフェース。"""

    @abstractmethod
    def analyze(self, transcript: str) -> MeetingAnalysis:
        """文字起こし全文を分析し、構造化した会議情報を返す。"""

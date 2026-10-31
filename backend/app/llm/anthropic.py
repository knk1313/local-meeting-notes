"""Claude APIを使った会議の要約・タスク抽出。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from anthropic import APIError, Anthropic, AuthenticationError

from app.llm.base import LlmError, MeetingAnalysis, MeetingAnalyzer, Task
from app.settings import settings


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "meeting_analysis.md"
TOOL_NAME = "submit_meeting_analysis"

#: 残高不足を表す Anthropic のエラーメッセージ断片。リトライでは回復しない。
CREDIT_BALANCE_MESSAGE = "credit balance"

MEETING_ANALYSIS_TOOL = {
    "name": TOOL_NAME,
    "description": "会議の要約とタスク抽出の結果を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "array",
                "items": {"type": "string"},
                "description": "会議の要点。",
            },
            "decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "会議で決定した事項。",
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "会議で未決の事項や確認が必要な事項。",
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "実行する内容。"},
                        "assignee": {
                            "type": ["string", "null"],
                            "description": "担当者。不明な場合は null。",
                        },
                        "due_date": {
                            "type": ["string", "null"],
                            "description": "期限。不明な場合は null。",
                        },
                    },
                    "required": ["title", "assignee", "due_date"],
                    "additionalProperties": False,
                },
                "description": "会議で合意・依頼された実行タスク。",
            },
        },
        "required": ["summary", "decisions", "open_questions", "tasks"],
        "additionalProperties": False,
    },
}


class ClaudeMeetingAnalyzer(MeetingAnalyzer):
    """Claude APIを利用して文字起こしを会議情報へ変換する。"""

    def __init__(
        self,
        *,
        model: str,
        client: Anthropic | None = None,
        workspace_id: str | None = None,
        prompt_path: Path = PROMPT_PATH,
    ) -> None:
        """分析器を初期化する。"""
        if not model.strip():
            raise ValueError("Claudeのモデル名を指定してください。")

        self._model = model
        self._client = client if client is not None else _create_client(workspace_id)
        self._prompt_path = prompt_path

    def analyze(self, transcript: str) -> MeetingAnalysis:
        """文字起こし全文をClaudeへ渡し、構造化した会議情報を返す。"""
        if not transcript.strip():
            raise LlmError("文字起こしが空です。")

        prompt = _load_prompt(self._prompt_path, transcript)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2_048,
                messages=[{"role": "user", "content": prompt}],
                tools=[MEETING_ANALYSIS_TOOL],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except AuthenticationError as exc:
            raise LlmError(
                "Anthropic APIキーが拒否されました。.env の ANTHROPIC_API_KEY を確認してください。"
            ) from exc
        except APIError as exc:
            message = str(exc)
            if "anthropic-workspace-id is required" in message:
                raise LlmError(
                    "このANTHROPIC_API_KEYにはWorkspace IDが必要です。"
                    " .env に ANTHROPIC_WORKSPACE_ID を設定してください。"
                ) from exc
            # 残高不足はリトライしても回復しないため、理由をそのまま伝える。
            if CREDIT_BALANCE_MESSAGE in message.lower():
                raise LlmError(
                    "Anthropicのクレジット残高が不足しています。"
                    "https://console.anthropic.com/settings/billing で確認してください。"
                ) from exc
            # 理由が分からないと対処できないため、APIの説明をそのまま伝える。
            raise LlmError(f"Claudeによる会議分析に失敗しました: {_error_message(exc)}") from exc

        return _to_meeting_analysis(response)


def create_default_analyzer() -> ClaudeMeetingAnalyzer:
    """`.env` の設定を使ったClaude分析器を生成する。"""
    if not settings.anthropic_api_key:
        raise LlmError("ANTHROPIC_API_KEY が設定されていません。")
    if not settings.claude_model:
        raise LlmError("CLAUDE_MODEL が設定されていません。")
    return ClaudeMeetingAnalyzer(
        model=settings.claude_model,
        workspace_id=settings.anthropic_workspace_id,
    )


def _create_client(workspace_id: str | None) -> Anthropic:
    """Workspace IDがある場合だけ、Claude APIの対象Workspaceを指定する。"""
    if not workspace_id:
        return Anthropic()
    return Anthropic(default_headers={"anthropic-workspace-id": workspace_id})


def _error_message(error: APIError) -> str:
    """Anthropicのエラー応答から、利用者に見せる説明を取り出す。

    ``{"error": {"message": ...}}`` の形の本文があればそれを使い、無ければ例外の文字列を使う。
    """
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        detail = body.get("error")
        if isinstance(detail, Mapping) and isinstance(detail.get("message"), str):
            return detail["message"]
    return getattr(error, "message", None) or str(error)


def _load_prompt(path: Path, transcript: str) -> str:
    """プロンプトファイルを読み込み、文字起こしを埋め込む。"""
    try:
        template = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LlmError(f"プロンプトを読み込めません: {path}") from exc

    placeholder = "{{transcript}}"
    if placeholder not in template:
        raise LlmError(f"プロンプトに {placeholder} がありません: {path}")
    return template.replace(placeholder, transcript)


def _to_meeting_analysis(response: Any) -> MeetingAnalysis:
    """Claudeのtool useレスポンスを会議分析結果へ変換する。"""
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != TOOL_NAME:
            continue
        return _analysis_from_payload(getattr(block, "input", None))

    raise LlmError("Claudeのレスポンスに会議分析結果が含まれていません。")


def _analysis_from_payload(payload: Any) -> MeetingAnalysis:
    """tool useの入力値を検証し、会議分析結果を生成する。"""
    if not isinstance(payload, Mapping):
        raise LlmError("Claudeの会議分析結果が不正です。")

    tasks = _tasks_from_payload(payload.get("tasks"))
    return MeetingAnalysis(
        summary=_string_list(payload.get("summary"), "summary"),
        decisions=_string_list(payload.get("decisions"), "decisions"),
        open_questions=_string_list(payload.get("open_questions"), "open_questions"),
        tasks=tasks,
    )


def _string_list(value: Any, field_name: str) -> list[str]:
    """文字列リスト形式の項目を検証する。"""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LlmError(f"Claudeの {field_name} が不正です。")
    return value


def _tasks_from_payload(value: Any) -> list[Task]:
    """タスク一覧を検証し、Taskのリストへ変換する。"""
    if not isinstance(value, list):
        raise LlmError("Claudeの tasks が不正です。")

    tasks: list[Task] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise LlmError("Claudeの tasks に不正な項目があります。")

        title = item.get("title")
        assignee = item.get("assignee")
        due_date = item.get("due_date")
        if not isinstance(title, str) or not title.strip():
            raise LlmError("Claudeのタスク名が不正です。")
        if assignee is not None and not isinstance(assignee, str):
            raise LlmError("Claudeのタスク担当者が不正です。")
        if due_date is not None and not isinstance(due_date, str):
            raise LlmError("Claudeのタスク期限が不正です。")

        tasks.append(Task(title=title, assignee=assignee, due_date=due_date))

    return tasks

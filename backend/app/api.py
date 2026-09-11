"""ローカル会議UI向けのFastAPIアプリケーション。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.audio import MacOsAudioRecorder
from app.cli import run_record
from app.stt import Segment


SessionPhase = Literal["recording", "transcribing", "summarizing", "completed", "failed"]


class StartMeetingRequest(BaseModel):
    """会議開始時にフロントエンドから受け取る情報。"""

    title: str = Field(min_length=1, max_length=120)
    participants: list[str] = Field(default_factory=list, max_length=30)


class TranscriptSegmentResponse(BaseModel):
    """ブラウザへ返す文字起こし断片。"""

    speaker: str | None
    start: float | None
    end: float | None
    text: str


class MeetingResponse(BaseModel):
    """会議セッションの現在状態。"""

    id: str
    title: str
    participants: list[str]
    phase: SessionPhase
    message: str
    transcript: list[TranscriptSegmentResponse]
    note_path: str | None = None
    error: str | None = None


@dataclass
class MeetingSession:
    """録音プロセスと逐次STT結果をまとめて管理する。"""

    id: str
    title: str
    participants: list[str]
    recorder: MacOsAudioRecorder = field(default_factory=MacOsAudioRecorder)
    phase: SessionPhase = "recording"
    message: str = "録音を開始しています…"
    transcript: list[Segment] = field(default_factory=list)
    note_path: str | None = None
    error: str | None = None
    _thread: Thread | None = field(default=None, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def start(self) -> None:
        """録音と逐次STTをバックグラウンドで開始する。"""
        self._thread = Thread(target=self._run, name=f"meeting-{self.id}", daemon=True)
        self._thread.start()

    def request_stop(self) -> None:
        """録音停止を要求する。要約とMarkdown生成はバックグラウンドで続ける。"""
        with self._lock:
            if self.phase not in {"recording", "transcribing"}:
                return
            self.message = "録音を停止しています…"
        self.recorder.request_stop()

    def snapshot(self) -> MeetingResponse:
        """ロック下で、フロント表示用の一貫した状態を返す。"""
        with self._lock:
            return MeetingResponse(
                id=self.id,
                title=self.title,
                participants=list(self.participants),
                phase=self.phase,
                message=self.message,
                transcript=[
                    TranscriptSegmentResponse(
                        speaker=segment.speaker,
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                    )
                    for segment in self.transcript
                ],
                note_path=self.note_path,
                error=self.error,
            )

    def _run(self) -> None:
        args = argparse.Namespace(
            title=self.title,
            participants=self.participants,
            tags=[],
            keep_transcript=False,
        )
        try:
            exit_code = run_record(
                args,
                recorder=self.recorder,
                on_status=self._set_status,
                on_segments=self._append_segments,
            )
        except Exception as exc:  # UIへ失敗理由を返し、サーバープロセスは継続する。
            with self._lock:
                self.phase = "failed"
                self.error = str(exc)
                self.message = "録音処理に失敗しました。"
            return

        with self._lock:
            if exit_code == 0:
                self.phase = "completed"
                self.message = "会議ノートを生成しました。"
            else:
                self.phase = "failed"
                self.error = self.message
                self.message = "録音処理に失敗しました。"

    def _append_segments(self, segments: list[Segment]) -> None:
        with self._lock:
            self.transcript.extend(segments)
            self.phase = "transcribing"

    def _set_status(self, message: str) -> None:
        with self._lock:
            self.message = message
            if message.startswith("要約・タスク") or message.startswith("Markdownを書き出し"):
                self.phase = "summarizing"
            elif message.startswith("文字起こし"):
                self.phase = "transcribing"
            elif message.startswith("会議ノートを保存しました:"):
                self.note_path = message.removeprefix("会議ノートを保存しました:").strip()


class MeetingService:
    """ローカルでは一度に1会議だけを扱うセッション管理。"""

    def __init__(self) -> None:
        self._session: MeetingSession | None = None
        self._lock = Lock()

    def start(self, request: StartMeetingRequest) -> MeetingSession:
        with self._lock:
            if self._session is not None and self._session.snapshot().phase in {"recording", "transcribing", "summarizing"}:
                raise RuntimeError("すでに会議を録音しています。")
            self._session = MeetingSession(
                id=str(uuid4()),
                title=request.title.strip(),
                participants=[participant.strip() for participant in request.participants if participant.strip()],
            )
            self._session.start()
            return self._session

    def current(self) -> MeetingSession:
        with self._lock:
            if self._session is None:
                raise LookupError("進行中または直近の会議がありません。")
            return self._session

    def get(self, session_id: str) -> MeetingSession:
        """指定IDの会議セッションを返す。ローカル版では直近の1件だけを保持する。"""
        session = self.current()
        if session.id != session_id:
            raise LookupError("指定された会議が見つかりません。")
        return session


service = MeetingService()

app = FastAPI(title="Local Meeting Notes API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """ローカルAPIの起動確認を返す。"""
    return {"status": "ok"}


@app.post("/api/meetings", response_model=MeetingResponse, status_code=201)
def start_meeting(request: StartMeetingRequest) -> MeetingResponse:
    """会議の録音・逐次文字起こしを開始する。"""
    try:
        return service.start(request).snapshot()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/meetings/current", response_model=MeetingResponse)
def get_current_meeting() -> MeetingResponse:
    """現在または直近の会議セッションを返す。"""
    try:
        return service.current().snapshot()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/meetings/{session_id}", response_model=MeetingResponse)
def get_meeting(session_id: str) -> MeetingResponse:
    """URLに対応する会議セッションを返す。"""
    try:
        return service.get(session_id).snapshot()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/meetings/current/stop", response_model=MeetingResponse)
def stop_current_meeting() -> MeetingResponse:
    """録音を停止し、要約・Markdown生成へ進める。"""
    try:
        session = service.current()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.request_stop()
    return session.snapshot()


def main() -> None:
    """`python -m app.api` 用のローカルサーバー起動入口。"""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

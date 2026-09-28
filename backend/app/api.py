"""ローカル会議UI向けのFastAPIアプリケーション。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.audio import MacOsAudioRecorder
from app.cli import EXIT_NO_SPEECH, EXIT_SUCCESS, run_record
from app.notes import StoredNote, get_note, list_notes
from app.settings import settings
from app.stt import Segment


SessionPhase = Literal["recording", "transcribing", "summarizing", "completed", "no_speech", "failed"]


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


class NoteSummaryResponse(BaseModel):
    """一覧に表示する保存済み会議ノートの概要。"""

    id: str
    title: str
    date: str
    participants: list[str]
    tags: list[str]
    excerpt: str
    duration_seconds: float | None = None


class NoteDetailResponse(NoteSummaryResponse):
    """Markdown本文まで含む会議ノート。"""

    markdown: str


class MeetingResponse(BaseModel):
    """会議セッションの現在状態。"""

    id: str
    title: str
    participants: list[str]
    phase: SessionPhase
    message: str
    transcript: list[TranscriptSegmentResponse]
    note_path: str | None = None
    warning: str | None = None
    error: str | None = None


@dataclass
class MeetingSession:
    """録音プロセスと、停止後の文字起こし・要約の進行状況をまとめて管理する。"""

    id: str
    title: str
    participants: list[str]
    recorder: MacOsAudioRecorder = field(default_factory=MacOsAudioRecorder)
    phase: SessionPhase = "recording"
    message: str = "録音を開始しています…"
    transcript: list[Segment] = field(default_factory=list)
    note_path: str | None = None
    warning: str | None = None
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
                warning=self.warning,
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
                on_warning=self._set_warning,
                on_stage=self._set_stage,
                on_note=self._set_note_path,
            )
        except Exception as exc:  # UIへ失敗理由を返し、サーバープロセスは継続する。
            with self._lock:
                self.phase = "failed"
                self.error = str(exc)
                self.message = "録音処理に失敗しました。"
            return

        # 終了理由は終了コードで判定し、メッセージ文言には依存させない。
        with self._lock:
            if exit_code == EXIT_SUCCESS:
                self.phase = "completed"
                self.message = "会議ノートを生成しました。"
            elif exit_code == EXIT_NO_SPEECH:
                # 失敗ではないため error は設定せず、理由は message のまま残す。
                self.phase = "no_speech"
            else:
                self.phase = "failed"
                self.error = self.message
                self.message = "録音処理に失敗しました。"

    def _append_segments(self, segments: list[Segment]) -> None:
        with self._lock:
            self.transcript.extend(segments)

    def _set_warning(self, message: str) -> None:
        with self._lock:
            self.warning = message

    def _set_stage(self, stage: str) -> None:
        with self._lock:
            if stage in {"transcribing", "summarizing"}:
                self.phase = stage

    def _set_note_path(self, path: Path) -> None:
        with self._lock:
            self.note_path = str(path)

    def _set_status(self, message: str) -> None:
        with self._lock:
            self.message = message


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


@app.get("/api/health")
def health() -> dict[str, str]:
    """ローカルAPIの起動確認を返す。"""
    return {"status": "ok"}


@app.get("/api/notes", response_model=list[NoteSummaryResponse])
def list_meeting_notes() -> list[NoteSummaryResponse]:
    """NOTES_DIRに保存済みの会議ノートを新しい順に返す。"""
    return [_note_summary(note) for note in list_notes(settings.notes_dir)]


@app.get("/api/notes/{note_id}", response_model=NoteDetailResponse)
def get_meeting_note(note_id: str) -> NoteDetailResponse:
    """ファイル名のstemを指定して、会議ノートのMarkdown本文を返す。"""
    try:
        note = get_note(settings.notes_dir, note_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="会議ノートを読み込めませんでした。") from exc
    return NoteDetailResponse(**_note_summary(note).model_dump(), markdown=note.markdown)


def _note_summary(note: StoredNote) -> NoteSummaryResponse:
    """保存済みノートを一覧用のレスポンスへ変換する。"""
    return NoteSummaryResponse(
        id=note.id,
        title=note.title,
        date=note.date,
        participants=note.participants,
        tags=note.tags,
        excerpt=note.excerpt,
        duration_seconds=note.duration_seconds,
    )


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

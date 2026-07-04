from __future__ import annotations

from pydantic import BaseModel


class AttachedFile(BaseModel):
    name: str
    text: str  # pre-extracted text content


ALLOWED_MODELS = {
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4-8",
    "gemini-3.5-flash",
    "glm-5.2",
}

DEFAULT_MODEL = "claude-sonnet-5"


class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    images: list[str] = []      # base64 data URLs
    files: list[AttachedFile] = []  # pre-extracted file contents
    model: str = DEFAULT_MODEL
    multi_agent: bool = False
    private: bool = False
    history: list[HistoryMessage] = []  # for private mode multi-turn
    continue_message_id: int | None = None  # continue a stopped assistant reply


class SessionInfo(BaseModel):
    session_id: str
    title: str
    message_count: int

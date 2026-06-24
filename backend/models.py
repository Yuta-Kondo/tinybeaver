from __future__ import annotations

from pydantic import BaseModel


class AttachedFile(BaseModel):
    name: str
    text: str  # pre-extracted text content


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    images: list[str] = []      # base64 data URLs
    files: list[AttachedFile] = []  # pre-extracted file contents


class SessionInfo(BaseModel):
    session_id: str
    title: str
    message_count: int

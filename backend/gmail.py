"""Gmail API integration — OAuth2 flow + email fetch helpers."""
from __future__ import annotations

import base64
import email as email_lib
import json
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from .memory import delete_oauth_token, load_oauth_token, save_oauth_token

# Read-only scope is enough for listing + reading emails
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Redirect URI must match what's registered in Google Cloud Console
_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/gmail/callback")

# In-memory store for PKCE code_verifier keyed by OAuth state parameter
_pending: dict[str, str] = {}


def _client_config() -> dict:
    client_id = os.getenv("GMAIL_CLIENT_ID")
    client_secret = os.getenv("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_REDIRECT_URI],
        }
    }


def get_auth_url() -> str:
    flow = Flow.from_client_config(_client_config(), scopes=_SCOPES, redirect_uri=_REDIRECT_URI)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    # Persist the code_verifier so the callback can send it with the token request
    if flow.code_verifier:
        _pending[state] = flow.code_verifier
    return url


def exchange_code(code: str, state: str = "") -> str:
    """Exchange OAuth code for tokens, persist them, return the Gmail address."""
    flow = Flow.from_client_config(_client_config(), scopes=_SCOPES, redirect_uri=_REDIRECT_URI)
    code_verifier = _pending.pop(state, None)
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials
    # Get the user's email address
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    gmail_email = profile.get("emailAddress", "")
    save_oauth_token("gmail", creds.to_json(), gmail_email)
    return gmail_email


def _get_credentials() -> Credentials:
    row = load_oauth_token("gmail")
    if not row:
        raise RuntimeError("Gmail not connected")
    creds = Credentials.from_authorized_user_info(json.loads(row["token_json"]), _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_oauth_token("gmail", creds.to_json(), row["email"])
    return creds


def get_connection_status() -> dict:
    row = load_oauth_token("gmail")
    if not row:
        return {"connected": False}
    return {"connected": True, "email": row["email"]}


def disconnect() -> None:
    delete_oauth_token("gmail")


def list_emails(max_results: int = 20, query: str = "") -> list[dict]:
    """Return a list of email summaries (id, from, subject, date, snippet)."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    params: dict[str, Any] = {"userId": "me", "maxResults": max_results}
    if query:
        params["q"] = query
    resp = service.users().messages().list(**params).execute()
    messages = resp.get("messages", [])

    result = []
    for msg in messages:
        meta = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
        result.append({
            "id": msg["id"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(no subject)"),
            "date": headers.get("Date", ""),
            "snippet": meta.get("snippet", ""),
        })
    return result


def get_email(msg_id: str) -> dict:
    """Return full email content (headers + decoded plain-text body)."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

    payload = msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

    body = _extract_body(payload)
    return {
        "id": msg_id,
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "body": body,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if not data:
            return ""
        raw = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        # Strip HTML tags for plain text
        msg = email_lib.message_from_string(raw)
        return msg.get_payload(decode=True).decode("utf-8", errors="replace") if msg.get_payload() else raw

    # multipart — recurse into parts, prefer plain over html
    parts = payload.get("parts", [])
    plain = next((p for p in parts if p.get("mimeType") == "text/plain"), None)
    if plain:
        return _extract_body(plain)
    for part in parts:
        text = _extract_body(part)
        if text.strip():
            return text
    return ""

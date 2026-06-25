import { useEffect, useRef, useState } from "react";
import {
  type EmailDetail,
  type EmailSummary,
  fetchEmail,
  fetchEmails,
  gmailDisconnect,
  gmailStartAuth,
  gmailStatus,
} from "../lib/api";

interface Props {
  onSendToChat?: (text: string) => void;
}

function formatDate(raw: string): string {
  try {
    return new Date(raw).toLocaleDateString("en-CA", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return raw;
  }
}

function senderName(from: string): string {
  const m = from.match(/^"?([^"<]+)"?\s*</);
  return m ? m[1].trim() : from.replace(/<.*>/, "").trim() || from;
}

export default function GmailPanel({ onSendToChat }: Props) {
  const [status, setStatus] = useState<{ connected: boolean; email?: string } | null>(null);
  const [emails, setEmails] = useState<EmailSummary[]>([]);
  const [selected, setSelected] = useState<EmailDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reload = async () => {
    const s = await gmailStatus();
    setStatus(s);
    if (s.connected) {
      setLoading(true);
      fetchEmails(searchQ, 25)
        .then(setEmails)
        .catch(() => setEmails([]))
        .finally(() => setLoading(false));
    }
  };

  useEffect(() => { reload(); }, []);

  // Check URL param after OAuth redirect
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail") === "connected") {
      window.history.replaceState({}, "", window.location.pathname);
      reload();
    }
  }, []);

  useEffect(() => {
    if (!status?.connected) return;
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => {
      setLoading(true);
      setSelected(null);
      fetchEmails(searchQ, 25)
        .then(setEmails)
        .catch(() => setEmails([]))
        .finally(() => setLoading(false));
    }, 400);
  }, [searchQ]);

  const connect = async () => {
    const url = await gmailStartAuth();
    window.location.href = url;
  };

  const disconnect = async () => {
    await gmailDisconnect();
    setStatus({ connected: false });
    setEmails([]);
    setSelected(null);
  };

  const openEmail = async (id: string) => {
    setLoadingDetail(true);
    setSelected(null);
    try {
      const detail = await fetchEmail(id);
      setSelected(detail);
    } finally {
      setLoadingDetail(false);
    }
  };

  const sendToChat = () => {
    if (!selected || !onSendToChat) return;
    const text = [
      `**Email from:** ${selected.from}`,
      `**Subject:** ${selected.subject}`,
      `**Date:** ${selected.date}`,
      `**To:** ${selected.to}`,
      "",
      selected.body.trim(),
    ].join("\n");
    onSendToChat(text);
  };

  if (!status) return <div className="gmail-loading">Loading…</div>;

  if (!status.connected) {
    return (
      <div className="gmail-connect">
        <div className="gmail-connect-icon">✉</div>
        <p className="gmail-connect-desc">Connect your Gmail account to read and discuss emails with the AI.</p>
        <button className="gmail-connect-btn" onClick={connect}>Connect Gmail</button>
      </div>
    );
  }

  return (
    <div className="gmail-panel">
      <div className="gmail-header">
        <span className="gmail-account">{status.email}</span>
        <button className="gmail-disconnect" onClick={disconnect} title="Disconnect">✕</button>
      </div>

      <div className="gmail-search-wrap">
        <input
          className="gmail-search"
          placeholder="Search emails…"
          value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
        />
      </div>

      {selected ? (
        <div className="gmail-detail">
          <button className="gmail-back" onClick={() => setSelected(null)}>← Back</button>
          <div className="gmail-detail-subject">{selected.subject}</div>
          <div className="gmail-detail-meta">
            <span>{selected.from}</span>
            <span>{formatDate(selected.date)}</span>
          </div>
          <div className="gmail-detail-body">{selected.body || selected.snippet}</div>
        </div>
      ) : (
        <div className="gmail-list">
          {loading && <div className="gmail-loading">Loading…</div>}
          {!loading && emails.length === 0 && (
            <div className="gmail-empty">No emails found</div>
          )}
          {loadingDetail && <div className="gmail-loading">Opening…</div>}
          {emails.map((e) => (
            <div key={e.id} className="gmail-item" onClick={() => openEmail(e.id)}>
              <div className="gmail-item-from">{senderName(e.from)}</div>
              <div className="gmail-item-subject">{e.subject}</div>
              <div className="gmail-item-meta">
                <span className="gmail-item-snippet">{e.snippet}</span>
                <span className="gmail-item-date">{formatDate(e.date)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

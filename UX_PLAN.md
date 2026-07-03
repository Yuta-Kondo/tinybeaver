# tinybeaver — UX Development Plan

Prioritized by **impact ÷ effort**. Grounded in the current codebase (React + FastAPI, SSE streaming, topic memory, MoA, private mode).

---

## Phase 1 — Fix what's broken / high leverage, low effort  ✅ SHIPPED (2026-07-03)

### 1.1 Message actions are invisible on mobile 🐞 ✅
**Problem:** In `MessageBubble.tsx:300`, action buttons render only when `hovered` is true. Touch devices have no hover → **you cannot copy, edit, retry, or delete any message on a phone.**
**Fix:** Show actions on tap (toggle on message click) on touch devices, or always-render a compact action row on mobile. Detect via `matchMedia("(pointer: coarse)")` (already used elsewhere in ChatView).
**Effort:** S

### 1.2 Regenerate an assistant response ✅
**Problem:** Retry (`↺`) only exists on *user* messages (`MessageBubble.tsx:304`). If an answer is bad, you must find the preceding user message to re-run.
**Fix:** Add a "Regenerate" action to assistant messages that re-runs from the prior user turn (reuse the resend/truncate path). Optionally "regenerate with a different model."
**Effort:** S–M

### 1.3 Code block copy + syntax highlighting ✅
**Problem:** Code renders as plain `<pre>` via ReactMarkdown — no per-block copy, no highlighting. Core need for a dev-facing agent.
**Fix:** Custom `code`/`pre` renderer with a copy button + lightweight highlighter (e.g. `shiki` or `highlight.js`). Language label in the corner.
**Effort:** M

### 1.4 Scroll-to-bottom button ✅
**Problem:** `pinnedRef` (`ChatView.tsx:191`) tracks whether the user scrolled up, but there's no visible way to jump back to the latest during a long stream.
**Fix:** Floating "↓ jump to latest" pill that appears when `!pinned`, hidden when at bottom.
**Effort:** S

### 1.5 Draft persistence ✅
**Problem:** Reloading mid-typing loses the draft.
**Fix:** Persist the textarea draft per-session to `localStorage`, restore on mount.
**Effort:** S

---

## Phase 2 — Trust, transparency, polish  ✅ SHIPPED (2026-07-03, except 2.5)

### 2.1 Response feedback (👍 / 👎) wired to memory ✅
**Why:** The backend already has a feedback-memory concept, but there's no UI to capture it. Thumbs up/down on assistant messages is the highest-signal, lowest-friction way to improve future answers.
**Fix:** Feedback buttons in the action row → new endpoint that stores the signal (and optional short note) into the feedback memory. Show a subtle "thanks" confirmation.
**Effort:** M

### 2.2 Better error UX ✅
**Problem:** Errors are injected as `_Error: …_` markdown text (`useChat.ts`), indistinguishable from content, with no retry.
**Fix:** Dedicated error bubble style + a "Retry" button. Distinguish network vs. API vs. quota (e.g. Gemini 429) with a friendly message.
**Effort:** S–M

### 2.3 Session rename + manual titles ✅
**Problem:** Titles are auto-set from the first 60 chars (`main.py:486`); no way to rename.
**Fix:** Inline rename in the sidebar (double-click or a ⋯ menu) → `update_session_title`. Endpoint already exists.
**Effort:** S

### 2.4 Session-switch loading state ✅
**Problem:** Switching sessions blanks the view then pops content in.
**Fix:** Lightweight skeleton / fade while `fetchSessionMessages` resolves.
**Effort:** S

### 2.5 Consistent icon set ✅
**Problem:** Mixed glyphs (`⎘ ↑ ■ ↺ ✎ ✕ ⬆`) look ad-hoc.
**Fix:** Replace with a single inline-SVG icon set for a coherent, polished feel.
**Effort:** M

---

## Phase 3 — Larger UX features  ✅ MOSTLY SHIPPED (2026-07-03)

### 3.1 Streaming stop → keep partial + continue ✅
Preserve partial output on stop (already streamed to DB?) and offer "continue."

### 3.2 Voice input ✅
Web Speech API mic button in the composer for hands-free capture on mobile.

### 3.3 Command palette (⌘K expansion) ✅
`⌘K` currently focuses search. Expand into a palette: jump to session, switch model, toggle private, new chat, open Tasks/Topics/Gmail.

### 3.4 Memory/context inspector ✅
A panel showing *why* the agent answered a certain way — which topics were loaded, what got written back. Turns the topic tags into a browsable trust surface.

### 3.5 Attachment previews — image lightbox + PDF thumbnails ✅
Inline preview for images/PDFs before send, and richer rendering of returned files.

---

## Suggested order

1. **1.1** (mobile actions bug) — ship first, it's a correctness issue.
2. **1.4, 1.5, 2.3, 2.4** — batch of quick wins.
3. **1.2, 1.3** — regenerate + code blocks (core chat quality).
4. **2.1, 2.2** — feedback loop + error handling.
5. **2.5** then Phase 3 as capacity allows.

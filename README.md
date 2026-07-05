# tinybeaver

A personal AI assistant web app — a FastAPI backend and a React (Vite) frontend,
powered by Claude, with a topic-based long-term memory that persists across chats.

Unlike a stateless chatbot, tinybeaver classifies each message, loads the relevant
memory topics into context, and writes new facts back after replying — so it keeps
learning about you over time.

---

## Features

- **Streaming chat** over Server-Sent Events, with Markdown, KaTeX math, tables,
  and syntax-highlighted code blocks (copy per block).
- **Topic memory.** Messages are classified into topics; relevant topics are
  loaded into context and updated after each reply. Browse/edit them in the
  Memory panel; semantic search over topics via embeddings.
- **Model picker** — Claude Haiku / Sonnet / Opus, Gemini Flash, and GLM, per chat.
- **Multi-agent (MoA) mode** — a sequential debate of three Gemini agents
  synthesized by Claude, streamed live per agent.
- **Private mode** — nothing is written to the DB or memory for that conversation.
- **Web search** (Tavily) with cited sources, and inline URL fetching.
- **Attachments** — images (with lightbox), and PDF/CSV/TXT extraction with a
  first-page PDF thumbnail preview.
- **Gmail integration**, **scheduled tasks**, and **web-push notifications**.
- **Command palette** (⌘K), **voice input** (Web Speech API), response feedback
  (👍/👎 fed back into memory), regenerate / edit / stop-and-continue, per-message
  model + cost tags, session rename/search, light/dark themes, and PWA install.

---

## Architecture

```
backend/            FastAPI app
├── main.py         routes, chat streaming, tools (search, gmail, files)
├── llm.py          shared Anthropic client + streaming/JSON helpers
├── providers.py    Gemini / GLM providers (message conversion + streaming)
├── models.py       single-source model registry, pricing, cost calc, pydantic models
├── memory.py       SQLite: sessions, messages, topics (+ migrations)
├── classifier.py   routes a message to relevant/new topics
├── embeddings.py   topic embeddings for semantic search
├── gmail.py        Gmail OAuth + read
├── push.py         web-push (VAPID)
└── scheduler.py    background scheduled tasks

frontend/           React + TypeScript (Vite)
└── src/            components, hooks (useChat), lib/api, lib/models

docker-compose.yml  backend (uvicorn) + nginx (serves SPA, proxies API routes)
nginx.conf          static + SSE proxy config
```

Models, pricing, and cost tags are defined once in `backend/models.py`
(`MODELS` registry) and mirrored in `frontend/src/lib/models.ts`. To add a
model, add one entry to each; the dropdown, command palette, validation,
labels, and cost calculations all read from those registries.

Data lives in SQLite at `data/memory.db` (git-ignored). Auth in production is
handled at the edge by Cloudflare Access.

---

## Setup

Requires **Python 3.11+** and **Node 20+**.

```bash
cp .env.example .env          # fill in your keys (see below)
```

**Backend:**
```bash
python3 -m venv .venv-backend && source .venv-backend/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

**Frontend** (in another terminal):
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies API routes to :8000
```

### Environment (`.env`)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | required — Claude |
| `GOOGLE_API_KEY` | Gemini models / MoA |
| `TAVILY_API_KEY` | web search |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REDIRECT_URI` | Gmail integration |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | web-push notifications |
| `CONTACT_EMAIL` | contact used in request headers + VAPID claims |
| `JINA_API_KEY` | optional — improves URL fetching in chat (r.jina.ai) |
| `SCHEDULER_TZ` | optional — IANA timezone for scheduled tasks (e.g. `America/Toronto`) |

---

## Testing

```bash
# backend
pytest -q

# frontend
cd frontend && npm test
```

---

## Deployment

Production runs via Docker Compose (backend + nginx) on a VPS, behind Cloudflare
Access:

```bash
docker compose build backend
docker compose up -d
```

`nginx` serves the built SPA (`frontend/dist`) and proxies API routes to the
backend with SSE buffering disabled for streaming.

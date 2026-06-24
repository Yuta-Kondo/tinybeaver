---
description: Launch the personal-agent app (FastAPI backend + Vite frontend)
---

# Run: Personal Agent

Two processes: FastAPI backend on :8000, Vite frontend on :5173.

## Node location

Node is NOT in PATH. Use the binary at:
```
/private/tmp/node-v20.19.2-darwin-arm64/bin/node
```

If that path is gone (tmp gets cleared), run:
```bash
find /private/tmp -name "node" -type f -perm +111 2>/dev/null | grep -v node_modules | head -3
```

## Start backend

```bash
cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate
# Kill any stale process first
kill $(lsof -ti :8000) 2>/dev/null || true
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
sleep 3
curl -s http://localhost:8000/health
```

## Start frontend

```bash
kill $(lsof -ti :5173) 2>/dev/null || true
NODE=/private/tmp/node-v20.19.2-darwin-arm64/bin/node
cd "$(git rev-parse --show-toplevel)/frontend"
$NODE node_modules/.bin/vite --port 5173 &
sleep 4
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/
```

## Verify

- Backend health: `curl http://localhost:8000/health` → `{"ok":true,...}`
- Frontend: HTTP 200 on `http://localhost:5173/`
- Topics search: `curl "http://localhost:8000/topics/search?q=phd"` → results array

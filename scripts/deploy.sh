#!/bin/bash
# Deploy to Hetzner VPS
# Usage: ./scripts/deploy.sh <VPS_IP>
# Requires: VPS_IP arg, SSH key configured, .env.production present
set -e

VPS_IP="${1:?Usage: ./scripts/deploy.sh <VPS_IP>}"
SSH="ssh -o StrictHostKeyChecking=accept-new root@$VPS_IP"
REMOTE=/app

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NODE_BIN="$ROOT/node-v20.19.2-darwin-arm64/bin"

echo "==> Building React frontend..."
(cd frontend && PATH="$NODE_BIN:$PATH" npm run build)

echo "==> Transferring app files to $VPS_IP..."
rsync -az --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='data/' \
  --exclude='memory/' \
  --exclude='.env' \
  . root@$VPS_IP:$REMOTE/

# Transfer built frontend separately
rsync -az frontend/dist/ root@$VPS_IP:$REMOTE/frontend/dist/

echo "==> Transferring .env.production..."
scp .env.production root@$VPS_IP:$REMOTE/.env

echo "==> Starting services..."
$SSH "cd $REMOTE && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build"

echo "==> Deploy complete. Check logs: ssh root@$VPS_IP 'docker compose -C /app logs -f'"

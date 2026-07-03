#!/bin/bash
# Securely transfer local data (SQLite DB + memory files) to VPS
# Run ONCE after first deploy, or whenever you want to sync local → cloud
# Usage: ./scripts/migrate-data.sh <VPS_IP>
set -e

VPS_IP="${1:?Usage: ./scripts/migrate-data.sh <VPS_IP>}"
REMOTE=/app

echo "==> Stopping backend on VPS to avoid DB corruption..."
ssh root@$VPS_IP "cd $REMOTE && docker compose stop backend"

echo "==> Transferring memory files..."
rsync -az --delete memory/ root@$VPS_IP:$REMOTE/memory/

echo "==> Transferring SQLite database..."
# data/ uses a Docker named volume — must copy via the container, not host filesystem
scp data/memory.db root@$VPS_IP:/tmp/memory.db
ssh root@$VPS_IP "docker cp /tmp/memory.db app-backend-1:/app/data/memory.db && rm /tmp/memory.db"

echo "==> Restarting backend..."
ssh root@$VPS_IP "cd $REMOTE && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend"

echo "==> Data migration complete."

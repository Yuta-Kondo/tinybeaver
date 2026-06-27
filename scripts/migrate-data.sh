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
# Copy to a temp path first, then move atomically
rsync -az data/memory.db root@$VPS_IP:/tmp/memory.db
ssh root@$VPS_IP "mv /tmp/memory.db $REMOTE/data/memory.db && chown root:root $REMOTE/data/memory.db && chmod 600 $REMOTE/data/memory.db"

echo "==> Restarting backend..."
ssh root@$VPS_IP "cd $REMOTE && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend"

echo "==> Data migration complete."

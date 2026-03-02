#!/usr/bin/env bash
# update.sh — быстрый деплой изменений на сервер
# Использование: ./update.sh
# Делает: git push → git pull на сервере → docker compose up -d --build

set -euo pipefail

SSH_KEY="${HOME}/.ssh/id_ed25519_seva"
SERVER="root@109.172.114.197"
SERVER_PATH="/root/trade_bot"

echo "→ git push..."
git push origin main

echo "→ деплой на сервер..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SERVER" \
  "cd $SERVER_PATH && git pull && docker compose up -d --build"

echo "✓ готово"

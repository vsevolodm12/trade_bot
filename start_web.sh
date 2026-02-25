#!/usr/bin/env bash
# Запуск веб-интерфейса
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate

echo "🌐 Запускаю веб-интерфейс..."
nohup python web_main.py >> logs/web.log 2>&1 &
WEB_PID=$!
echo $WEB_PID > logs/web.pid

PORT="${WEB_PORT:-8080}"
echo "✅ Веб-интерфейс запущен: http://localhost:${PORT} (PID ${WEB_PID})"

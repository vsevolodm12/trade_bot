#!/usr/bin/env bash
# Остановка веб-интерфейса
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/logs/web.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "⛔ Веб-интерфейс остановлен (PID $PID)"
    else
        echo "ℹ️  Процесс $PID уже не запущен"
    fi
    rm -f "$PID_FILE"
else
    echo "ℹ️  PID-файл не найден"
fi

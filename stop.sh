#!/usr/bin/env bash
# Остановка бота
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".bot.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️  Бот не запущен (файл $PID_FILE не найден)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "🛑 Останавливаю бота (PID: $PID)..."
    kill "$PID"

    # Ждём завершения до 10 сек
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  Процесс не завершился. Принудительная остановка..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "✅ Бот остановлен"
else
    echo "⚠️  Процесс $PID не найден. Очищаю PID-файл."
    rm -f "$PID_FILE"
fi

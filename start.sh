#!/usr/bin/env bash
# Запуск бота в фоновом режиме
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".bot.pid"
LOG_FILE="logs/bot.log"

mkdir -p logs

# Проверяем, не запущен ли уже бот
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  Бот уже запущен (PID: $PID)"
        echo "   Используйте ./restart.sh для перезапуска."
        exit 1
    else
        echo "⚠️  Найден устаревший PID-файл. Очищаю..."
        rm "$PID_FILE"
    fi
fi

# Проверяем наличие виртуального окружения
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Проверяем наличие .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден. Создайте его на основе .env.example"
    exit 1
fi

# Проверяем, задан ли токен
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | cut -d'=' -f2 | tr -d '[:space:]')
if [ -z "$TOKEN" ]; then
    echo "❌ TELEGRAM_BOT_TOKEN не задан в .env"
    exit 1
fi

echo "🚀 Запускаю бота..."
nohup python -m bot.main >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

sleep 1
if kill -0 "$BOT_PID" 2>/dev/null; then
    echo "✅ Бот запущен (PID: $BOT_PID)"
    echo "   Логи: $LOG_FILE"
    echo "   Остановка: ./stop.sh"
else
    echo "❌ Бот не смог запуститься. Проверьте логи: $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

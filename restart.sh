#!/usr/bin/env bash
# Перезапуск бота
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔄 Перезапускаю бота..."

"$SCRIPT_DIR/stop.sh" || true
sleep 2
"$SCRIPT_DIR/start.sh"

#!/usr/bin/env bash
# =============================================================================
# deploy.sh — деплой Trade Bot на чистый сервер с нуля
#
# Что делает:
#   1. Проверяет SSH-соединение
#   2. Устанавливает Docker + git на сервере (если не установлены)
#   3. Клонирует репозиторий (или делает git pull если уже есть)
#   4. Копирует .env с токенами
#   5. Собирает Docker-образ и запускает оба сервиса (bot + web)
#
# Требования (локально):
#   • ssh, scp
#   • SSH-ключ добавлен в ~/.ssh/authorized_keys на сервере
#
# Настройка:
#   Добавьте в .env следующие переменные:
#
#   SERVER_USER=ubuntu
#   SERVER_HOST=123.45.67.89
#   SERVER_PATH=/opt/trade_bot
#   GITHUB_REPO=https://github.com/vsevolodm12/trade_bot
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Загружаем переменные из .env ────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден."
    exit 1
fi

_load() { grep -E "^${1}=" .env | head -1 | cut -d'=' -f2- | tr -d '[:space:]' || true; }

SERVER_USER="${SERVER_USER:-$(_load SERVER_USER)}"
SERVER_HOST="${SERVER_HOST:-$(_load SERVER_HOST)}"
SERVER_PATH="${SERVER_PATH:-$(_load SERVER_PATH)}"
GITHUB_REPO="${GITHUB_REPO:-$(_load GITHUB_REPO)}"

SERVER_USER="${SERVER_USER:-ubuntu}"
SERVER_PATH="${SERVER_PATH:-/opt/trade_bot}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/vsevolodm12/trade_bot}"

if [ -z "$SERVER_HOST" ]; then
    echo "❌ SERVER_HOST не задан. Добавьте в .env: SERVER_HOST=ваш.ip"
    exit 1
fi

SSH="ssh -o StrictHostKeyChecking=no"
SSH_TARGET="${SERVER_USER}@${SERVER_HOST}"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║          Trade Bot — Docker-деплой на сервер             ║"
echo "╠══════════════════════════════════════════════════════════╣"
printf "  Сервер : %s\n"  "$SSH_TARGET"
printf "  Путь   : %s\n"  "$SERVER_PATH"
printf "  Репо   : %s\n"  "$GITHUB_REPO"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Шаг 1: SSH-соединение ───────────────────────────────────────────────────
echo "🔗 [1/5] Проверяю SSH-соединение..."
if ! $SSH -o ConnectTimeout=10 -o BatchMode=yes "$SSH_TARGET" "echo ok" &>/dev/null; then
    echo "❌ Нет SSH-доступа к ${SSH_TARGET}"
    echo "   Убедитесь, что ключ добавлен: ssh-copy-id ${SSH_TARGET}"
    exit 1
fi
echo "   ✓ Соединение OK"
echo ""

# ─── Шаг 2: Установка Docker и git ───────────────────────────────────────────
echo "🐳 [2/5] Проверяю Docker и git на сервере..."

$SSH "$SSH_TARGET" bash -s << 'INSTALL'
set -euo pipefail

install_docker() {
    echo "   → Устанавливаю Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "   ✓ Docker установлен. Переподключитесь если нужны права без sudo."
}

install_git() {
    echo "   → Устанавливаю git..."
    sudo apt-get update -qq && sudo apt-get install -y -qq git
}

command -v docker &>/dev/null && echo "   ✓ Docker $(docker --version | cut -d' ' -f3 | tr -d ',')" || install_docker
command -v git    &>/dev/null && echo "   ✓ git $(git --version)"                                    || install_git

# Docker Compose plugin (входит в Docker >= 20.10 как 'docker compose')
docker compose version &>/dev/null && echo "   ✓ docker compose OK" || {
    echo "   → Устанавливаю docker-compose-plugin..."
    sudo apt-get install -y -qq docker-compose-plugin
}
INSTALL
echo ""

# ─── Шаг 3: Клонируем / обновляем репозиторий ────────────────────────────────
echo "📦 [3/5] Синхронизирую код с GitHub..."

$SSH "$SSH_TARGET" bash -s << GITPULL
set -euo pipefail

REPO="${GITHUB_REPO}"
PATH_="${SERVER_PATH}"

sudo mkdir -p "\$PATH_"
sudo chown "\${USER}:\${USER}" "\$PATH_"

if [ -d "\${PATH_}/.git" ]; then
    echo "   → Репо уже есть, делаю git pull..."
    cd "\$PATH_"
    git pull --rebase
else
    echo "   → Клонирую \$REPO → \$PATH_..."
    git clone "\$REPO" "\$PATH_"
    cd "\$PATH_"
fi

echo "   ✓ Код на коммите: \$(git log -1 --oneline)"
GITPULL
echo ""

# ─── Шаг 4: Копируем .env ────────────────────────────────────────────────────
echo "🔐 [4/5] Передаю .env..."
scp -q .env "${SSH_TARGET}:${SERVER_PATH}/.env"
$SSH "$SSH_TARGET" "chmod 600 '${SERVER_PATH}/.env'"
echo "   ✓ .env скопирован (права 600)"
echo ""

# ─── Шаг 5: Сборка и запуск через Docker Compose ─────────────────────────────
echo "🚀 [5/5] Собираю образ и запускаю сервисы..."

$SSH "$SSH_TARGET" bash -s << COMPOSE
set -euo pipefail
cd "${SERVER_PATH}"

echo "   → docker compose build..."
docker compose build --no-cache

echo "   → docker compose up -d..."
docker compose up -d

echo ""
echo "─────────────────────────────────────────────────────────────"
docker compose ps
echo "─────────────────────────────────────────────────────────────"
COMPOSE

# ─── Итог ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                  ✅ Деплой завершён!                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Веб-интерфейс: http://${SERVER_HOST}:$(grep WEB_PORT .env | cut -d= -f2 || echo 8080)"
echo ""
echo "Полезные команды на сервере (ssh ${SSH_TARGET}):"
echo ""
echo "  # Статус сервисов"
echo "  cd ${SERVER_PATH} && docker compose ps"
echo ""
echo "  # Логи бота"
echo "  cd ${SERVER_PATH} && docker compose logs -f bot"
echo ""
echo "  # Логи веб-интерфейса"
echo "  cd ${SERVER_PATH} && docker compose logs -f web"
echo ""
echo "  # Перезапуск"
echo "  cd ${SERVER_PATH} && docker compose restart"
echo ""
echo "  # Обновление (после git push)"
echo "  cd ${SERVER_PATH} && git pull && docker compose up -d --build"

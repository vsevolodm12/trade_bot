"""
Точка запуска веб-интерфейса Trade Alerts.

Запуск:
    python web_main.py

Переменные окружения (.env):
    WEB_PORT       — порт сервера (по умолчанию 8080)
    WEB_SECRET     — PIN для входа в веб-интерфейс
    SESSION_SECRET — секрет для подписи cookie (любая случайная строка)
    DB_PATH        — путь к SQLite базе (по умолчанию bot.db)
    ALLOWED_USER_IDS — Telegram user_id через запятую (первый = уведомления)

Не требует WEB_USER_ID: показывает все алерты из базы,
уведомления идут первому пользователю из ALLOWED_USER_IDS.
"""
import os
import sys
import logging

import uvicorn
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "8080"))

    if os.getenv("WEB_PASSWORD", "changeme") == "changeme":
        logging.warning(
            "⚠️  WEB_PASSWORD не задан — используется 'changeme'. "
            "Установите надёжный пароль в .env"
        )

    allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not allowed:
        logging.warning(
            "⚠️  ALLOWED_USER_IDS не задан — уведомления через Telegram не будут "
            "отправляться для алертов, добавленных через веб"
        )

    logging.info("Веб-интерфейс запускается на http://localhost:%d", port)
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="warning",
    )

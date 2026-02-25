import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TWELVEDATA_API_KEY: str = os.getenv("TWELVEDATA_API_KEY", "")
DB_PATH: str = os.getenv("DB_PATH", "bot.db")

# Опциональный список разрешённых user_id (пусто = все)
_raw_ids = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS: list[int] = (
    [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]
    if _raw_ids.strip()
    else []
)

# Первый пользователь из ALLOWED_USER_IDS — получает уведомления об алертах
# добавленных через веб-интерфейс
PRIMARY_USER_ID: int = ALLOWED_USER_IDS[0] if ALLOWED_USER_IDS else 0

# URL веб-интерфейса (HTTPS, нужен для Telegram Mini App кнопки)
WEB_URL: str = os.getenv("WEB_URL", "")

# Интервалы проверки по умолчанию (в секундах)
DEFAULT_INTERVAL_RU: int = 60    # 1 минута
DEFAULT_INTERVAL_US: int = 180   # 3 минуты

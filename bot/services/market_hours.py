"""
Проверка рабочих часов бирж.

Используется для:
  - Пропуска мониторинга цен когда биржа закрыта (MOEX, US, HK)
  - Пропуска TwelveData батча когда нет смысла обновлять цены

Биржи и часы:
  MOEX  — Пн-Пт 10:00–18:40 МСК (UTC+3)
  NYSE/NASDAQ — Пн-Пт 09:30–16:00 ET
  HKEX  — Пн-Пт 09:30–12:00 и 13:00–16:00 HKT (UTC+8)

Добавляем буфер ±10 мин для захвата открытия/закрытия.
"""
import datetime
from zoneinfo import ZoneInfo

TZ_MOSCOW = ZoneInfo("Europe/Moscow")
TZ_NY     = ZoneInfo("America/New_York")
TZ_HK     = ZoneInfo("Asia/Hong_Kong")

# Группы бирж → таймзона + часы
_EXCHANGE_GROUPS: dict[str, dict] = {
    "MOEX": {
        "tz": TZ_MOSCOW,
        "open":  (10, 0),
        "close": (18, 40),
        "lunch": None,
    },
    "NYSE": {
        "tz": TZ_NY,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": None,
    },
    "NASDAQ": {
        "tz": TZ_NY,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": None,
    },
    "NYSE ARCA": {
        "tz": TZ_NY,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": None,
    },
    "NYSE MKT": {
        "tz": TZ_NY,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": None,
    },
    "CBOE": {
        "tz": TZ_NY,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": None,
    },
    "HKEX": {
        "tz": TZ_HK,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": ((12, 0), (13, 0)),  # перерыв 12:00–13:00
    },
    "HKSE": {
        "tz": TZ_HK,
        "open":  (9, 30),
        "close": (16, 0),
        "lunch": ((12, 0), (13, 0)),
    },
}

# Запас ±N минут: учитывает пред-маркет / после-маркет и погрешность расписания
_BUFFER_MINUTES = 10


def is_market_open(exchange: str) -> bool:
    """
    Проверяет, открыта ли биржа прямо сейчас.

    Неизвестные биржи → True (чтобы не пропустить алерт).
    """
    cfg = _EXCHANGE_GROUPS.get(exchange.upper().strip())
    if cfg is None:
        return True  # неизвестная биржа — предполагаем открыто

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Выходные (0=Пн, 5=Сб, 6=Вс)
    if now_utc.weekday() >= 5:
        return False

    now = now_utc.astimezone(cfg["tz"])
    buf = datetime.timedelta(minutes=_BUFFER_MINUTES)

    open_t  = now.replace(hour=cfg["open"][0],  minute=cfg["open"][1],  second=0, microsecond=0)
    close_t = now.replace(hour=cfg["close"][0], minute=cfg["close"][1], second=0, microsecond=0)

    # Раньше открытия или позже закрытия (с буфером)
    if now < open_t - buf or now > close_t + buf:
        return False

    # Обед (опционально)
    if cfg["lunch"]:
        lunch_start_h, lunch_start_m = cfg["lunch"][0]
        lunch_end_h,   lunch_end_m   = cfg["lunch"][1]
        lunch_start = now.replace(hour=lunch_start_h, minute=lunch_start_m, second=0, microsecond=0)
        lunch_end   = now.replace(hour=lunch_end_h,   minute=lunch_end_m,   second=0, microsecond=0)
        if lunch_start <= now < lunch_end:
            return False

    return True


def any_foreign_market_open() -> bool:
    """True если хотя бы одна иностранная биржа открыта (US или HK)."""
    return is_market_open("NYSE") or is_market_open("HKEX")


def next_market_open_seconds(exchange: str) -> float:
    """
    Через сколько секунд откроется биржа (грубо, без учёта праздников).
    Используется для логирования.
    """
    cfg = _EXCHANGE_GROUPS.get(exchange.upper().strip())
    if cfg is None:
        return 0

    now = datetime.datetime.now(datetime.timezone.utc).astimezone(cfg["tz"])
    today_open = now.replace(
        hour=cfg["open"][0], minute=cfg["open"][1], second=0, microsecond=0
    )

    if now < today_open:
        return (today_open - now).total_seconds()

    # Следующий рабочий день
    days_ahead = 1
    while True:
        candidate = today_open + datetime.timedelta(days=days_ahead)
        if candidate.weekday() < 5:
            return (candidate - now).total_seconds()
        days_ahead += 1

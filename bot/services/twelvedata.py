"""
Twelve Data API — используется ТОЛЬКО для двух задач:

  1. Первичный поиск тикера при добавлении алерта (/quote, 1 кредит)
  2. Периодическая батч-валидация цен во время работы биржи (/price, 1 кредит/тикер)

Лимиты Basic 8 план:
  - 800 кредитов/день
  - 8 запросов/мин (не кредитов — именно HTTP-запросов)

Стратегия батча:
  - 100 тикеров разбиваем на группы по _CHUNK_SIZE (8 по умолчанию)
  - 1 группа = 1 HTTP-запрос = 8 кредитов
  - Между запросами выдерживаем паузу через rate limiter
  - Итого: 100 тикеров → 13 запросов, ~2 минуты на полный цикл
  - Батч запускается только если биржа открыта

Бюджет при 100 US/HK тикерах:
  800 кредитов/день
  - резерв 100 для /quote (добавление новых тикеров)
  - 700 для батча → 700/100 = 7 полных циклов в день
  Батч раз в 3 ч × 8 ч открытой биржи = 2–3 цикла/день → запас большой
"""
import asyncio
import datetime
import logging
import time
from typing import Optional

import aiohttp

from bot.config import TWELVEDATA_API_KEY

logger = logging.getLogger(__name__)

_BASE    = "https://api.twelvedata.com"
_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Тикеров в одном HTTP-запросе (не превышаем кредитный лимит в минуту)
_CHUNK_SIZE: int = 8

# Максимум HTTP-запросов к TD в минуту
_MAX_REQUESTS_PER_MIN: int = 8

# Резерв кредитов на добавление новых тикеров через /quote
TD_RESERVE_CREDITS: int = 100
TD_DAILY_LIMIT:     int = 800

_EXCHANGE_CURRENCY: dict[str, str] = {
    "NASDAQ":    "USD",
    "NYSE":      "USD",
    "NYSE ARCA": "USD",
    "NYSE MKT":  "USD",
    "CBOE":      "USD",
    "HKEX":      "HKD",
    "HKSE":      "HKD",
}

# ─── Rate Limiter (скользящее окно 60 сек) ───────────────────────────────────

_req_timestamps: list[float] = []
_rate_lock = asyncio.Lock()


async def _rate_limit() -> None:
    """
    Ждёт, если за последние 60 сек уже было ≥ _MAX_REQUESTS_PER_MIN запросов.
    Добавляет текущий timestamp в очередь.
    """
    async with _rate_lock:
        now = time.monotonic()
        window = 60.0

        # Очищаем старые записи
        while _req_timestamps and now - _req_timestamps[0] >= window:
            _req_timestamps.pop(0)

        if len(_req_timestamps) >= _MAX_REQUESTS_PER_MIN:
            # Ждём до момента, когда самый старый запрос выйдет за окно
            wait = window - (now - _req_timestamps[0]) + 0.05
            logger.debug("TD rate limit: ждём %.1f сек", wait)
            await asyncio.sleep(wait)
            # Повторно очищаем
            now = time.monotonic()
            while _req_timestamps and now - _req_timestamps[0] >= window:
                _req_timestamps.pop(0)

        _req_timestamps.append(time.monotonic())


# ─── Дневной бюджет ──────────────────────────────────────────────────────────

_budget: dict = {"date": None, "used": 0}


def _budget_remaining() -> int:
    today = datetime.date.today()
    if _budget["date"] != today:
        _budget["date"] = today
        _budget["used"] = 0
    return TD_DAILY_LIMIT - _budget["used"]


def _budget_spend(n: int) -> None:
    today = datetime.date.today()
    if _budget["date"] != today:
        _budget["date"] = today
        _budget["used"] = 0
    _budget["used"] += n
    logger.info(
        "TwelveData: --%d кредитов → использовано %d/%d сегодня",
        n, _budget["used"], TD_DAILY_LIMIT,
    )


def budget_status() -> dict:
    remaining = _budget_remaining()
    return {
        "daily_limit":         TD_DAILY_LIMIT,
        "used":                TD_DAILY_LIMIT - remaining,
        "remaining":           remaining,
        "reserve":             TD_RESERVE_CREDITS,
        "available_for_batch": max(0, remaining - TD_RESERVE_CREDITS),
    }


# ─── Единичный запрос /quote (при добавлении нового тикера) ─────────────────

async def get_stock_price(ticker: str) -> Optional[dict]:
    """
    /quote — полная информация о тикере.
    Стоимость: 1 кредит. Вызывать только при добавлении нового алерта.
    """
    if not TWELVEDATA_API_KEY:
        logger.warning("TWELVEDATA_API_KEY не задан")
        return None

    if _budget_remaining() <= 0:
        logger.warning("TwelveData: дневной лимит исчерпан, /quote пропущен для %s", ticker)
        return None

    ticker = ticker.upper().strip()
    url    = f"{_BASE}/quote"
    params = {"symbol": ticker, "apikey": TWELVEDATA_API_KEY, "format": "JSON"}

    await _rate_limit()

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("TwelveData /quote %s: %s", ticker, exc)
        return None

    if "code" in data or data.get("status") == "error":
        logger.debug("TwelveData ошибка %s: %s", ticker, data.get("message"))
        return None

    close = data.get("close")
    if close is None:
        return None

    _budget_spend(1)

    exchange = data.get("exchange", "")
    currency = data.get("currency") or _EXCHANGE_CURRENCY.get(exchange, "USD")

    return {
        "ticker":       data.get("symbol", ticker),
        "company_name": data.get("name", ticker),
        "price":        float(close),
        "currency":     currency,
        "exchange":     exchange,
    }


# ─── Батч-запрос /price (периодическая валидация) ───────────────────────────

async def _fetch_chunk(tickers: list[str]) -> dict[str, float]:
    """
    Один HTTP-запрос для группы тикеров через /price.
    Возвращает {ticker: price}.
    """
    url    = f"{_BASE}/price"
    params = {
        "symbol": ",".join(tickers),
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
    }

    await _rate_limit()  # соблюдаем 8 запросов/мин

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("TwelveData /price chunk %s: %s", tickers, exc)
        return {}

    if not isinstance(data, dict):
        return {}
    if "code" in data or data.get("status") == "error":
        logger.warning("TwelveData /price ошибка: %s", data.get("message", data))
        return {}

    result: dict[str, float] = {}

    if len(tickers) == 1:
        # Один тикер: {"price": "189.30"}
        raw = data.get("price")
        if raw is not None:
            try:
                price = float(raw)
                if price > 0:
                    result[tickers[0]] = price
            except (ValueError, TypeError):
                pass
    else:
        # Несколько: {"AAPL": {"price": "189.30"}, "MSFT": {"price": "415.50"}, ...}
        for ticker in tickers:
            entry = data.get(ticker)
            if isinstance(entry, dict):
                raw = entry.get("price")
                if raw is not None:
                    try:
                        price = float(raw)
                        if price > 0:
                            result[ticker] = price
                    except (ValueError, TypeError):
                        pass

    return result


async def get_batch_prices(tickers: list[str]) -> dict[str, float]:
    """
    Батч-проверка цен через TwelveData /price.

    Алгоритм:
      1. Фильтруем тикеры которых хватает бюджета
      2. Разбиваем на группы по _CHUNK_SIZE (8)
      3. Шлём по 1 запросу, соблюдая rate limiter (8 req/min)
      4. Итого 100 тикеров → ~13 запросов → ~2 мин
    """
    if not tickers or not TWELVEDATA_API_KEY:
        return {}

    available = _budget_remaining() - TD_RESERVE_CREDITS
    if available <= 0:
        logger.warning(
            "TwelveData batch: бюджет исчерпан (доступно %d кред., резерв %d), пропускаем",
            _budget_remaining(), TD_RESERVE_CREDITS,
        )
        return {}

    # Урезаем список если кредитов не хватит на всех
    if len(tickers) > available:
        logger.warning(
            "TwelveData batch: урезаем с %d до %d тикеров (бюджет)",
            len(tickers), available,
        )
        tickers = tickers[:available]

    # Разбиваем на чанки
    chunks = [tickers[i:i + _CHUNK_SIZE] for i in range(0, len(tickers), _CHUNK_SIZE)]
    logger.info(
        "TwelveData batch: %d тикеров → %d запросов по %d",
        len(tickers), len(chunks), _CHUNK_SIZE,
    )

    result: dict[str, float] = {}
    credits_spent = 0

    for chunk in chunks:
        chunk_result = await _fetch_chunk(chunk)
        result.update(chunk_result)
        credits_spent += len(chunk)

    _budget_spend(credits_spent)
    logger.info(
        "TwelveData batch: получено %d/%d цен, потрачено %d кредитов",
        len(result), len(tickers), credits_spent,
    )
    return result

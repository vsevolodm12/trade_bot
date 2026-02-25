"""
Курсы валют через Yahoo Finance (бесплатно).

Пары:
  USDRUB=X  — сколько рублей за 1 доллар
  HKDUSD=X  — сколько долларов за 1 гонконгский доллар

Кешируются на 1 час. При ошибке возвращается пустой dict — вся логика
конвертации тогда молча пропускает её и показывает родную валюту.
"""
import asyncio
import concurrent.futures
import logging
import time

logger = logging.getLogger(__name__)

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="forex"
)

_cache: dict[str, float] = {}
_cache_ts: float = 0.0
_CACHE_TTL = 3600  # обновляем курсы раз в час

_PAIRS = ["USDRUB=X", "HKDUSD=X"]


def _sync_fetch_rates() -> dict[str, float]:
    import yfinance as yf

    rates: dict[str, float] = {}
    for pair in _PAIRS:
        try:
            t = yf.Ticker(pair)
            p = t.fast_info.last_price
            if p and float(p) > 0:
                rates[pair] = float(p)
                logger.debug("forex %s = %.4f", pair, rates[pair])
        except Exception as exc:
            logger.debug("forex %s: %s", pair, exc)
    return rates


async def get_rates() -> dict[str, float]:
    """Возвращает кешированные курсы. Обновляет раз в час."""
    global _cache, _cache_ts
    if time.time() - _cache_ts < _CACHE_TTL and _cache:
        return _cache
    loop = asyncio.get_event_loop()
    rates = await loop.run_in_executor(_executor, _sync_fetch_rates)
    if rates:
        _cache = rates
        _cache_ts = time.time()
        logger.info(
            "forex: курсы обновлены — USDRUB=%.2f, HKDUSD=%.4f",
            rates.get("USDRUB=X", 0),
            rates.get("HKDUSD=X", 0),
        )
    return _cache


def convert(
    price: float,
    from_currency: str,
    to_currency: str,
    rates: dict[str, float],
) -> tuple[float, str]:
    """
    Конвертирует цену из from_currency в to_currency.
    Возвращает (цена, итоговая_валюта).
    Если конвертация невозможна (нет курса) — возвращает исходные значения.
    """
    if to_currency == "original" or from_currency == to_currency:
        return price, from_currency

    usdrub = rates.get("USDRUB=X", 0.0)
    hkdusd = rates.get("HKDUSD=X", 0.0)

    if not usdrub or not hkdusd:
        return price, from_currency  # курсы недоступны — без конвертации

    # Сначала переводим в USD
    if from_currency == "USD":
        usd = price
    elif from_currency == "RUB":
        usd = price / usdrub
    elif from_currency == "HKD":
        usd = price * hkdusd
    else:
        return price, from_currency

    # Из USD в нужную валюту
    if to_currency == "USD":
        return usd, "USD"
    elif to_currency == "RUB":
        return usd * usdrub, "RUB"
    elif to_currency == "HKD":
        return usd / hkdusd if hkdusd else price, "HKD"

    return price, from_currency

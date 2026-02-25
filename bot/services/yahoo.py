"""
Yahoo Finance (yfinance) — бесплатный источник цен без лимитов.
Используется для постоянного мониторинга US/HK акций вместо TwelveData.
Поддерживает батч-запросы: 100+ тикеров за один вызов.

Стратегия получения цены (single):
  1. fast_info.last_price — мгновенно, работает и когда рынок закрыт
  2. history(period="5d") — надёжный fallback, возвращает последние торги
  3. download(period="1d", interval="5m") — только если рынок открыт

Стратегия batch:
  1. download(period="1d", interval="5m") — быстро когда рынок открыт
  2. download(period="5d", interval="1d") — fallback для закрытого рынка
"""
import asyncio
import concurrent.futures
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="yfinance"
)


def _get_price_from_ticker(t) -> Optional[float]:
    """Получить последнюю цену через fast_info или history."""
    # 1. fast_info.last_price — работает всегда (кеш Yahoo)
    try:
        p = t.fast_info.last_price
        if p and float(p) > 0:
            return float(p)
    except Exception:
        pass

    # 2. history(5d, 1d) — последние дневные свечи
    try:
        hist = t.history(period="5d", interval="1d")
        if not hist.empty:
            p = float(hist["Close"].dropna().iloc[-1])
            if p > 0:
                return p
    except Exception:
        pass

    return None


def _sync_single(ticker: str) -> Optional[dict]:
    """Синхронное получение одного тикера с метаданными (для поиска)."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)

        price = _get_price_from_ticker(t)
        if not price:
            return None

        info     = t.info or {}
        company  = info.get("longName") or info.get("shortName") or ticker
        currency = info.get("currency") or ""
        exchange = info.get("exchange") or ""

        return {
            "ticker":       ticker,
            "company_name": company,
            "price":        price,
            "currency":     currency,
            "exchange":     exchange,
        }
    except Exception as exc:
        logger.debug("yfinance single %s: %s", ticker, exc)
        return None


def _sync_batch(tickers: list[str]) -> dict[str, float]:
    """Синхронный батч-запрос. Запускается в ThreadPoolExecutor."""
    if not tickers:
        return {}
    try:
        import yfinance as yf

        def _download_close(period: str, interval: str) -> "pd.DataFrame | None":
            import pandas as pd
            data = yf.download(
                tickers if len(tickers) > 1 else tickers[0],
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            return None if data.empty else data

        # Попытка 1: 1d/5m (актуально когда рынок открыт)
        data = _download_close("1d", "5m")

        # Попытка 2: 5d/1d (работает всегда, возвращает последние торги)
        if data is None:
            data = _download_close("5d", "1d")

        if data is None:
            return {}

        close = data["Close"] if len(tickers) > 1 else data["Close"]
        result: dict[str, float] = {}

        if len(tickers) == 1:
            try:
                val = float(close.dropna().iloc[-1])
                if val > 0:
                    result[tickers[0]] = val
            except Exception:
                pass
        else:
            for ticker in tickers:
                try:
                    col = close[ticker] if ticker in close.columns else None
                    if col is None:
                        continue
                    val = float(col.dropna().iloc[-1])
                    if val > 0:
                        result[ticker] = val
                except Exception as e:
                    logger.debug("yfinance: нет данных для %s: %s", ticker, e)

        return result

    except Exception as exc:
        logger.warning("yfinance batch failed: %s", exc)
        return {}


async def get_batch_prices(tickers: list[str]) -> dict[str, float]:
    """Асинхронный батч-запрос цен. Один вызов на 100+ тикеров."""
    if not tickers:
        return {}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _sync_batch, tickers)


async def get_stock_price(ticker: str) -> Optional[dict]:
    """Асинхронное получение цены одного тикера с метаданными."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _sync_single, ticker)

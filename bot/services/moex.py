"""
Интеграция с MOEX ISS API (бесплатно, задержка 15 мин).
Документация: https://iss.moex.com/iss/reference/
"""
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

MOEX_BASE = "https://iss.moex.com/iss"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def get_stock_price(ticker: str) -> Optional[dict]:
    """
    Получить данные по акции с MOEX (основной режим торгов, борд TQBR).

    Возвращает словарь:
        ticker, company_name, price, currency ("RUB"), exchange ("MOEX")
    или None, если акция не найдена.
    """
    ticker = ticker.upper().strip()
    url = (
        f"{MOEX_BASE}/engines/stock/markets/shares"
        f"/boards/TQBR/securities/{ticker}.json"
    )
    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": "SECID,SECNAME,SHORTNAME,PREVPRICE",
        "marketdata.columns": "SECID,LAST,CLOSEPRICE,MARKETPRICE2",
        "lang": "ru",
    }

    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug("MOEX вернул статус %s для %s", resp.status, ticker)
                    return None
                data = await resp.json(content_type=None)
    except Exception as exc:
        logger.warning("MOEX запрос для %s не выполнен: %s", ticker, exc)
        return None

    sec_cols = data.get("securities", {}).get("columns", [])
    sec_rows = data.get("securities", {}).get("data", [])
    md_cols  = data.get("marketdata",  {}).get("columns", [])
    md_rows  = data.get("marketdata",  {}).get("data",    [])

    if not sec_rows or not md_rows:
        return None

    sec = dict(zip(sec_cols, sec_rows[0]))
    md  = dict(zip(md_cols,  md_rows[0]))

    # Приоритет: последняя сделка → цена закрытия → цена предыдущего дня
    price = md.get("LAST") or md.get("CLOSEPRICE") or md.get("MARKETPRICE2") or sec.get("PREVPRICE")
    if price is None:
        return None

    company = sec.get("SECNAME") or sec.get("SHORTNAME") or ticker

    return {
        "ticker":       ticker,
        "company_name": company,
        "price":        float(price),
        "currency":     "RUB",
        "exchange":     "MOEX",
    }

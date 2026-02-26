"""
FastAPI веб-приложение — Trade Alerts Interface.

Концепция:
  - Один PIN → доступ ко всем алертам в базе
  - При добавлении алерта через веб — уведомление идёт PRIMARY_USER_ID
    (первый в ALLOWED_USER_IDS из .env)
  - user_id нужен только для роутинга Telegram-уведомлений, не для доступа
"""
import hashlib
import hmac
import json
import os
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, Form, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature

from fastapi import UploadFile, File
from bot.config import PRIMARY_USER_ID, ALLOWED_USER_IDS, TELEGRAM_BOT_TOKEN
from bot.database import Database
from bot.services.moex import get_stock_price as moex_price
from bot.services.twelvedata import get_stock_price as td_price, budget_status
from bot.services.yahoo import get_stock_price as yahoo_price
from bot.services.forex import get_rates, convert as fx_convert

logger = logging.getLogger(__name__)

# ─── Конфигурация ────────────────────────────────────────────────────────────

WEB_LOGIN    = os.getenv("WEB_LOGIN", "")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "changeme")
SESSION_KEY  = os.getenv("SESSION_SECRET", "session-change-me")

signer = URLSafeTimedSerializer(SESSION_KEY)
db     = Database(os.getenv("DB_PATH", "bot.db"))

CURRENCY_SYM    = {"RUB": "₽", "USD": "$", "HKD": "HK$"}
DIRECTION_LABEL = {"above": "▲", "below": "▼"}

DISPLAY_CURRENCIES = {
    "original": "Родная",
    "RUB":      "₽ Рубли",
    "USD":      "$ Доллары",
}

RU_INTERVALS = {60: "1 мин", 120: "2 мин", 300: "5 мин"}
US_INTERVALS = {180: "3 мин", 300: "5 мин", 600: "10 мин"}

# Маппинг кодов бирж Yahoo Finance → наш стандарт
_YAHOO_EXCHANGE: dict[str, str] = {
    "HKG": "HKEX", "HKSE": "HKEX",
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ",
    "NYQ": "NYSE",
    "PCX": "NYSE ARCA",
    "ASE": "NYSE MKT",
    "CBT": "CBOE", "BTS": "CBOE",
}
_YAHOO_CURRENCY: dict[str, str] = {
    "HKEX": "HKD", "HKSE": "HKD",
}


async def _search_stock(ticker: str) -> Optional[dict]:
    """
    Ищет тикер: MOEX → TwelveData → Yahoo Finance.
    Возвращает нормализованный dict или None.
    """
    # 1. MOEX ISS (бесплатно, без кредитов)
    stock = await moex_price(ticker)
    if stock:
        return stock

    # 2. TwelveData /quote (1 кредит)
    stock = await td_price(ticker)
    if stock:
        return stock

    # 3. Yahoo Finance — для HK (.HK), ETF и прочих
    stock = await yahoo_price(ticker)
    if not stock:
        return None

    # Нормализуем биржу из Yahoo-кода
    raw_ex  = stock.get("exchange", "")
    exchange = _YAHOO_EXCHANGE.get(raw_ex, raw_ex) or "NYSE"

    # Валюта: если Yahoo вернул пустую — берём по бирже
    currency = stock.get("currency") or _YAHOO_CURRENCY.get(exchange, "USD")

    return {
        "ticker":       stock["ticker"],
        "company_name": stock["company_name"],
        "price":        stock["price"],
        "currency":     currency,
        "exchange":     exchange,
    }


# ─── Startup ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    yield


app = FastAPI(lifespan=lifespan)

_BASE     = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(_BASE, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(_BASE, "static")), name="static")


# ─── Сессии ──────────────────────────────────────────────────────────────────

def make_session() -> str:
    return signer.dumps({"auth": True})


def is_authenticated(session: Optional[str]) -> bool:
    if not session:
        return False
    try:
        data = signer.loads(session, max_age=86400 * 30)
        return bool(data.get("auth"))
    except (BadSignature, Exception):
        return False


def auth_redirect():
    return RedirectResponse(url="/login", status_code=302)


def _set_session_cookie(response, max_age: int = 86400 * 30) -> None:
    """Выставляет подписанный session cookie на max_age секунд (по умолчанию 30 дней)."""
    response.set_cookie(
        "session",
        make_session(),
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )


# ─── Telegram Mini App validation ────────────────────────────────────────────

def validate_telegram_init_data(init_data: str) -> Optional[dict]:
    """
    Валидация Telegram WebApp initData по официальному алгоритму.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Алгоритм:
      secret_key = HMAC-SHA256("WebAppData", bot_token)
      data_check_string = sorted(key=value пары, кроме hash) через \\n
      signature = HMAC-SHA256(secret_key, data_check_string).hexdigest()
      signature == hash → данные валидны

    Возвращает словарь user из initData или None при ошибке.
    """
    if not TELEGRAM_BOT_TOKEN or not init_data:
        return None

    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = params.pop("hash", None)
    if not received_hash:
        return None

    # Проверяем актуальность данных (не старше 24 часов)
    auth_date = int(params.get("auth_date", 0))
    if time.time() - auth_date > 86400:
        logger.warning("Telegram initData просрочены (auth_date=%d)", auth_date)
        return None

    # Строка для проверки подписи
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )

    # Вычисляем подпись
    secret_key = hmac.new(
        b"WebAppData",
        TELEGRAM_BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    calculated = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        logger.warning("Telegram initData: неверная подпись")
        return None

    # Извлекаем user
    user_str = params.get("user")
    if user_str:
        try:
            return json.loads(user_str)
        except (json.JSONDecodeError, Exception):
            pass

    return {}  # подпись валидна, но нет данных о пользователе


# ─── Утилиты ─────────────────────────────────────────────────────────────────

def _enrich(
    alerts: list[dict],
    display_currency: str = "original",
    rates: dict | None = None,
) -> list[dict]:
    result = []
    rates = rates or {}
    for a in alerts:
        orig_currency = a["currency"]
        current_raw   = a.get("current_price")
        target_raw    = a["target_price"]
        direction     = a["direction"]

        # Конвертация в валюту отображения
        if current_raw and display_currency != "original":
            current_conv, disp_cur = fx_convert(current_raw, orig_currency, display_currency, rates)
        else:
            current_conv, disp_cur = current_raw, orig_currency

        target_conv, _ = fx_convert(target_raw, orig_currency, display_currency, rates) \
            if display_currency != "original" else (target_raw, orig_currency)

        sym = CURRENCY_SYM.get(disp_cur, disp_cur)

        pct = None
        if current_raw and target_raw and target_raw > 0 and current_raw > 0:
            pct = min(100.0, (current_raw / target_raw * 100) if direction == "above"
                      else (target_raw / current_raw * 100))

        dist_pct = None
        if current_raw and target_raw and current_raw > 0:
            dist_pct = abs((target_raw - current_raw) / current_raw * 100)

        if pct is None:
            color = "normal"
        elif direction == "above":
            color = "above-reached" if pct >= 97 else "above-close" if pct >= 88 else "above"
        else:
            color = "below-reached" if pct >= 97 else "below-close" if pct >= 88 else "below"

        result.append({
            **a,
            "sym":            sym,
            "dir_label":      DIRECTION_LABEL.get(direction, ""),
            "current_fmt":    f"{current_conv:.2f} {sym}" if current_conv else "—",
            "target_fmt":     f"{target_conv:.2f} {sym}",
            "progress_pct":   round(pct, 1) if pct is not None else None,
            "dist_pct":       round(dist_pct, 1) if dist_pct is not None else None,
            "progress_color": color,
        })
    return result


def _enrich_one(alert: dict, display_currency: str = "original", rates: dict | None = None) -> dict:
    return _enrich([alert], display_currency, rates)[0]


def _tradingview_url(ticker: str, exchange: str) -> str:
    if exchange == "MOEX":
        return f"https://www.tradingview.com/symbols/MOEX-{ticker}/"
    if exchange in ("HKEX", "HKSE"):
        return f"https://www.tradingview.com/symbols/HKEX-{ticker}/"
    return f"https://www.tradingview.com/symbols/{ticker}/"


async def _all_alerts() -> list[dict]:
    """Все активные алерты из базы (без фильтра по user_id)."""
    return await db.get_all_active_alerts_web()


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/alerts")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Optional[str] = Cookie(None)):
    if is_authenticated(session):
        return RedirectResponse(url="/alerts")
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    login_ok    = (not WEB_LOGIN) or username.strip() == WEB_LOGIN
    password_ok = password.strip() == WEB_PASSWORD
    if not login_ok or not password_ok:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Неверный логин или пароль"}
        )
    resp = RedirectResponse(url="/alerts", status_code=303)
    _set_session_cookie(resp)
    return resp


@app.post("/auth/telegram")
async def auth_telegram(init_data: str = Form(...)):
    """
    Валидация Telegram Mini App initData.
    Вызывается JavaScript на странице /login при обнаружении Telegram WebApp.
    Если подпись верна и user_id в ALLOWED_USER_IDS — выставляет session cookie.
    """
    user = validate_telegram_init_data(init_data)

    if user is None:
        return JSONResponse(
            {"ok": False, "error": "Неверная подпись Telegram. Откройте приложение через бота."},
            status_code=403,
        )

    user_id = user.get("id")

    # Если ALLOWED_USER_IDS задан — проверяем что пользователь в списке
    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        logger.warning("Mini App auth: user_id=%s не в ALLOWED_USER_IDS", user_id)
        return JSONResponse(
            {"ok": False, "error": "Нет доступа. Ваш аккаунт не авторизован."},
            status_code=403,
        )

    first_name = user.get("first_name", "")
    logger.info("Mini App auth: пользователь %s (id=%s) вошёл", first_name, user_id)

    resp = JSONResponse({"ok": True, "user": first_name})
    _set_session_cookie(resp)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("session")
    return resp


# ─── Portfolio ────────────────────────────────────────────────────────────────

_MARKET_FILTERS = {
    "all": lambda a: True,
    "ru":  lambda a: a["exchange"] == "MOEX",
    "us":  lambda a: a["exchange"] not in ("MOEX", "HKEX", "HKSE"),
    "hk":  lambda a: a["exchange"] in ("HKEX", "HKSE"),
}


def _apply_filter(alerts: list[dict], market: str) -> list[dict]:
    fn = _MARKET_FILTERS.get(market, _MARKET_FILTERS["all"])
    return [a for a in alerts if fn(a)]


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, session: Optional[str] = Cookie(None)):
    if not is_authenticated(session):
        return auth_redirect()

    s        = await db.get_user_settings(PRIMARY_USER_ID)
    disp_cur = s.get("display_currency", "original")
    rates    = await get_rates() if disp_cur != "original" else {}
    alerts   = await _all_alerts()
    enriched = _enrich(alerts, disp_cur, rates)

    return templates.TemplateResponse("index.html", {
        "request":        request,
        "alerts":         enriched,
        "total":          len(alerts),
        "active":         "alerts",
        "market":         "all",
        "display_currency": disp_cur,
    })


@app.get("/partials/alerts", response_class=HTMLResponse)
async def alerts_partial(
    request: Request,
    market: str = "all",
    sort:   str = "default",
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse('<div id="alerts-wrap"></div>')

    s        = await db.get_user_settings(PRIMARY_USER_ID)
    disp_cur = s.get("display_currency", "original")
    rates    = await get_rates() if disp_cur != "original" else {}
    alerts   = await _all_alerts()
    enriched = _apply_filter(_enrich(alerts, disp_cur, rates), market)

    if sort == "proximity":
        enriched.sort(key=lambda a: a["dist_pct"] if a["dist_pct"] is not None else 9999)
    elif sort == "newest":
        enriched.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    elif sort == "oldest":
        enriched.sort(key=lambda a: a.get("created_at") or "")

    return templates.TemplateResponse("partials/alert_list.html", {
        "request": request,
        "alerts":  enriched,
        "market":  market,
        "sort":    sort,
    })


# ─── Add Alert ────────────────────────────────────────────────────────────────

@app.get("/partials/add-form", response_class=HTMLResponse)
async def add_form(request: Request, session: Optional[str] = Cookie(None)):
    if not is_authenticated(session):
        return HTMLResponse("")
    return templates.TemplateResponse("partials/add_form.html", {"request": request})


@app.post("/partials/search", response_class=HTMLResponse)
async def search_ticker(
    request: Request,
    ticker: str = Form(...),
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("")

    ticker  = ticker.upper().strip()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    if not ticker or len(ticker) > 20 or not set(ticker).issubset(allowed):
        return templates.TemplateResponse(
            "partials/ticker_error.html",
            {"request": request, "error": "Неверный формат тикера"},
        )

    stock = await _search_stock(ticker)

    if not stock:
        return templates.TemplateResponse(
            "partials/ticker_error.html",
            {"request": request, "error": f"Акция «{ticker}» не найдена. Проверьте тикер."},
        )

    sym   = CURRENCY_SYM.get(stock["currency"], stock["currency"])
    price = stock["price"]
    cur   = stock["currency"]

    # Альтернативные цены для переключателя в карточке
    rates = await get_rates()
    alt_prices: dict[str, str] = {}
    for target_cur, target_sym in CURRENCY_SYM.items():
        if target_cur == cur:
            continue
        converted, _ = fx_convert(price, cur, target_cur, rates)
        if converted != price:  # конвертация удалась
            alt_prices[target_cur] = f"{converted:.2f} {target_sym}"

    return templates.TemplateResponse("partials/ticker_found.html", {
        "request":    request,
        "stock":      stock,
        "sym":        sym,
        "price_fmt":  f"{price:.2f} {sym}",
        "alt_prices": alt_prices,  # {"USD": "3.97 $", "RUB": "304.00 ₽"}
        "tv_url":     _tradingview_url(stock["ticker"], stock["exchange"]),
    })


@app.post("/alerts", response_class=HTMLResponse)
async def add_alert(
    request: Request,
    ticker:        str            = Form(...),
    company_name:  str            = Form(...),
    exchange:      str            = Form(...),
    current_price: float          = Form(...),
    currency:      str            = Form(...),
    target_above:  Optional[float] = Form(None),
    target_below:  Optional[float] = Form(None),
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    if not target_above and not target_below:
        return HTMLResponse(
            '<p style="color:var(--danger);padding:8px">Заполните хотя бы одно поле</p>'
        )

    # Уведомления пойдут PRIMARY_USER_ID (первый из ALLOWED_USER_IDS в .env)
    if target_above and target_above > 0:
        await db.add_alert(
            user_id=PRIMARY_USER_ID,
            ticker=ticker,
            exchange=exchange,
            company_name=company_name,
            target_price=target_above,
            currency=currency,
            direction="above",
            current_price=current_price,
        )

    if target_below and target_below > 0:
        await db.add_alert(
            user_id=PRIMARY_USER_ID,
            ticker=ticker,
            exchange=exchange,
            company_name=company_name,
            target_price=target_below,
            currency=currency,
            direction="below",
            current_price=current_price,
        )

    s        = await db.get_user_settings(PRIMARY_USER_ID)
    disp_cur = s.get("display_currency", "original")
    rates    = await get_rates() if disp_cur != "original" else {}
    alerts   = await _all_alerts()
    enriched = _enrich(alerts, disp_cur, rates)

    resp = templates.TemplateResponse(
        "partials/alert_list.html",
        {"request": request, "alerts": enriched},
    )
    resp.headers["HX-Trigger"] = "alertAdded"
    return resp


# ─── Excel bulk import ───────────────────────────────────────────────────────

@app.post("/upload/excel", response_class=HTMLResponse)
async def upload_excel(
    request: Request,
    file:    UploadFile = File(...),
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    import io
    import openpyxl

    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        ws = wb.active
    except Exception:
        return templates.TemplateResponse(
            "partials/excel_result.html",
            {"request": request, "error": "Не удалось прочитать файл. Убедитесь, что это .xlsx"},
            status_code=400,
        )

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return templates.TemplateResponse(
            "partials/excel_result.html",
            {"request": request, "error": "Файл пустой"},
        )

    # Пропускаем первую строку если это заголовок (не число во второй колонке)
    start = 0
    first_b = rows[0][1] if len(rows[0]) > 1 else None
    if first_b is None or not str(first_b).replace(".", "").replace(",", "").isdigit():
        start = 1

    added, skipped = [], []
    for row in rows[start:]:
        if len(row) < 2:
            continue
        raw_ticker = str(row[0]).strip().upper() if row[0] else ""
        raw_price  = str(row[1]).replace(",", ".").strip() if row[1] else ""

        if not raw_ticker or not raw_price:
            continue
        try:
            target_price = float(raw_price)
        except ValueError:
            skipped.append(f"{raw_ticker} — неверная цена")
            continue

        stock = await _search_stock(raw_ticker)
        if not stock:
            skipped.append(f"{raw_ticker} — не найден")
            continue

        direction = "above" if target_price >= stock["price"] else "below"
        try:
            await db.add_alert(
                user_id=PRIMARY_USER_ID,
                ticker=stock["ticker"],
                exchange=stock["exchange"],
                company_name=stock["company_name"],
                target_price=target_price,
                currency=stock["currency"],
                direction=direction,
                current_price=stock["price"],
            )
            added.append(stock["ticker"])
        except Exception as e:
            skipped.append(f"{raw_ticker} — ошибка БД")
            logger.error("excel import DB error %s: %s", raw_ticker, e)

    # Обновляем список алертов и закрываем шит
    alerts   = await _all_alerts()
    enriched = _enrich(alerts)
    resp = templates.TemplateResponse(
        "partials/excel_result.html",
        {"request": request, "added": added, "skipped": skipped},
    )
    resp.headers["HX-Trigger"] = "alertAdded"
    return resp


# ─── Delete / Edit ───────────────────────────────────────────────────────────

@app.delete("/alerts/{alert_id}", response_class=HTMLResponse)
async def delete_alert(
    alert_id: int,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)
    # Не проверяем user_id — веб-приложение показывает все алерты
    async with __import__("aiosqlite").connect(db.db_path) as conn:
        await conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        await conn.commit()
    return HTMLResponse("")


@app.get("/partials/alerts/{alert_id}", response_class=HTMLResponse)
async def alert_card_partial(
    request: Request,
    alert_id: int,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("")

    alert = await db.get_alert_by_id(alert_id)
    if not alert:
        return HTMLResponse("")

    s        = await db.get_user_settings(PRIMARY_USER_ID)
    disp_cur = s.get("display_currency", "original")
    rates    = await get_rates() if disp_cur != "original" else {}
    enriched = _enrich_one(alert, disp_cur, rates)
    return templates.TemplateResponse("partials/alert_card.html", {
        "request": request,
        "a":       enriched,
        "tv_url":  _tradingview_url(alert["ticker"], alert["exchange"]),
    })


@app.get("/partials/alerts/{alert_id}/edit", response_class=HTMLResponse)
async def alert_card_edit(
    request: Request,
    alert_id: int,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("")

    alert = await db.get_alert_by_id(alert_id)
    if not alert:
        return HTMLResponse("")

    enriched = _enrich_one(alert)
    return templates.TemplateResponse("partials/alert_card_edit.html", {
        "request": request,
        "a":       enriched,
    })


@app.put("/alerts/{alert_id}/target", response_class=HTMLResponse)
async def update_target(
    request: Request,
    alert_id:     int,
    target_price: float = Form(...),
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    alert = await db.get_alert_by_id(alert_id)
    if not alert:
        return HTMLResponse("", status_code=404)

    current   = alert.get("current_price") or alert["target_price"]
    direction = "above" if target_price >= current else "below"

    await db.update_alert_target(
        alert_id, alert["user_id"], target_price, direction, current
    )

    updated  = await db.get_alert_by_id(alert_id)
    s        = await db.get_user_settings(PRIMARY_USER_ID)
    disp_cur = s.get("display_currency", "original")
    rates    = await get_rates() if disp_cur != "original" else {}
    enriched = _enrich_one(updated, disp_cur, rates)

    return templates.TemplateResponse("partials/alert_card.html", {
        "request": request,
        "a":       enriched,
        "tv_url":  _tradingview_url(updated["ticker"], updated["exchange"]),
    })


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: Optional[str] = Cookie(None)):
    if not is_authenticated(session):
        return auth_redirect()

    # Настройки показываем PRIMARY_USER_ID
    s      = await db.get_user_settings(PRIMARY_USER_ID)
    td     = budget_status()

    return templates.TemplateResponse("settings.html", {
        "request":            request,
        "s":                  s,
        "ru_intervals":       RU_INTERVALS,
        "us_intervals":       US_INTERVALS,
        "display_currencies": DISPLAY_CURRENCIES,
        "td":                 td,
        "active":             "settings",
    })


@app.post("/settings/ru/{seconds}", response_class=HTMLResponse)
async def set_ru_interval(
    request: Request,
    seconds: int,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    if seconds not in RU_INTERVALS:
        raise HTTPException(400, "Недопустимый интервал")

    await db.upsert_user_settings(PRIMARY_USER_ID, interval_ru=seconds)
    s  = await db.get_user_settings(PRIMARY_USER_ID)
    td = budget_status()

    return templates.TemplateResponse("partials/settings_intervals.html", {
        "request":            request,
        "s":                  s,
        "ru_intervals":       RU_INTERVALS,
        "us_intervals":       US_INTERVALS,
        "display_currencies": DISPLAY_CURRENCIES,
        "td":                 td,
    })


@app.post("/settings/us/{seconds}", response_class=HTMLResponse)
async def set_us_interval(
    request: Request,
    seconds: int,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    if seconds not in US_INTERVALS:
        raise HTTPException(400, "Недопустимый интервал")

    await db.upsert_user_settings(PRIMARY_USER_ID, interval_us=seconds)
    s  = await db.get_user_settings(PRIMARY_USER_ID)
    td = budget_status()

    return templates.TemplateResponse("partials/settings_intervals.html", {
        "request":            request,
        "s":                  s,
        "ru_intervals":       RU_INTERVALS,
        "us_intervals":       US_INTERVALS,
        "display_currencies": DISPLAY_CURRENCIES,
        "td":                 td,
    })


@app.post("/currency/{code}", response_class=HTMLResponse)
async def switch_currency(
    request: Request,
    code: str,
    market: str = "all",
    session: Optional[str] = Cookie(None),
):
    """Быстрое переключение валюты прямо с главной страницы."""
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    if code not in DISPLAY_CURRENCIES:
        raise HTTPException(400, "Недопустимая валюта")

    await db.upsert_user_settings(PRIMARY_USER_ID, display_currency=code)
    rates    = await get_rates() if code != "original" else {}
    alerts   = await _all_alerts()
    enriched = _apply_filter(_enrich(alerts, code, rates), market)

    resp = templates.TemplateResponse("partials/alert_list.html", {
        "request": request,
        "alerts":  enriched,
    })
    resp.headers["HX-Trigger"] = f"currencyChanged:{code}"
    return resp


@app.post("/settings/currency/{code}", response_class=HTMLResponse)
async def set_display_currency(
    request: Request,
    code: str,
    session: Optional[str] = Cookie(None),
):
    if not is_authenticated(session):
        return HTMLResponse("", status_code=401)

    if code not in DISPLAY_CURRENCIES:
        raise HTTPException(400, "Недопустимая валюта")

    await db.upsert_user_settings(PRIMARY_USER_ID, display_currency=code)
    s  = await db.get_user_settings(PRIMARY_USER_ID)
    td = budget_status()

    return templates.TemplateResponse("partials/settings_intervals.html", {
        "request":            request,
        "s":                  s,
        "ru_intervals":       RU_INTERVALS,
        "us_intervals":       US_INTERVALS,
        "display_currencies": DISPLAY_CURRENCIES,
        "td":                 td,
    })

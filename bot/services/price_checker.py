"""
Фоновые задачи проверки цен.

Два планировщика:

  check_prices_job  — каждые 30 сек (Yahoo + MOEX)
    • Цены обновляются ВСЕГДА (даже когда биржа закрыта — Yahoo кеширует последнюю)
    • Telegram-уведомления только когда биржа открыта
    • MOEX: поштучно через ISS (бесплатно)
    • US/HK: один батч через Yahoo Finance (бесплатно)

  td_batch_job  — каждые ~3 ч (TwelveData, только во время работы биржи)
    • Пропускает если все иностранные биржи закрыты
    • Пропускает тикеры, чья биржа закрыта
    • Разбивает на группы по 8, rate limiter 8 req/мин
    • Проверяет бюджет перед запуском

Экономия TwelveData:
  - 3 ч интервал × рабочее время биржи (~7 ч/день) = 2–3 цикла/день
  - 100 тикеров × 3 цикла = 300 кредитов/день из 800
  - 500 кредитов остаётся в резерве
"""
import logging
import os
import time

from telegram import Bot
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import alert_action_keyboard
from bot.services.moex import get_stock_price as moex_price
from bot.services.yahoo import get_batch_prices as yahoo_batch
from bot.services.twelvedata import get_batch_prices as td_batch
from bot.services.market_hours import is_market_open, any_foreign_market_open

logger = logging.getLogger(__name__)

TD_BATCH_INTERVAL_SEC: int = int(os.getenv("TD_BATCH_INTERVAL_SEC", str(3 * 3600)))

CURRENCY_SYM: dict[str, str] = {"RUB": "₽", "USD": "$", "HKD": "HK$"}


# ─── Yahoo + MOEX: непрерывный мониторинг ────────────────────────────────────

async def check_prices_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    await _run_yahoo_moex(context.bot, db)


async def _run_yahoo_moex(bot: Bot, db: Database) -> None:
    try:
        alerts = await db.get_all_active_alerts()
    except Exception as exc:
        logger.error("Не удалось получить алерты: %s", exc)
        return

    now = time.time()
    moex_due:    list[dict] = []
    foreign_due: list[dict] = []

    for alert in alerts:
        exchange = alert["exchange"]

        interval = (
            alert.get("interval_ru", 60)
            if exchange == "MOEX"
            else alert.get("interval_us", 180)
        )
        last = alert.get("last_checked") or 0
        if now - last >= interval:
            if exchange == "MOEX":
                moex_due.append(alert)
            else:
                foreign_due.append(alert)

    # US/HK: один батч на все тикеры (Yahoo — бесплатно)
    if foreign_due:
        tickers = list({a["ticker"] for a in foreign_due})
        prices  = await yahoo_batch(tickers)
        logger.debug(
            "Yahoo batch: %d тикеров, получено %d цен",
            len(tickers), len(prices),
        )
        for alert in foreign_due:
            price = prices.get(alert["ticker"])
            if price is not None:
                await _process_price(bot, db, alert, price)

    # MOEX: поштучно
    for alert in moex_due:
        try:
            data = await moex_price(alert["ticker"])
            if data:
                await _process_price(bot, db, alert, data["price"])
        except Exception as exc:
            logger.error("MOEX %s: %s", alert["ticker"], exc)


# ─── TwelveData: батч-валидация раз в несколько часов ────────────────────────

async def td_batch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.bot_data["db"]
    await _run_td_batch(context.bot, db)


async def _run_td_batch(bot: Bot, db: Database) -> None:
    # Пропускаем если все иностранные биржи закрыты — не тратим кредиты
    if not any_foreign_market_open():
        logger.info("TwelveData batch: все иностранные биржи закрыты, пропускаем")
        return

    try:
        alerts = await db.get_all_active_alerts()
    except Exception as exc:
        logger.error("td_batch: не удалось получить алерты: %s", exc)
        return

    # Берём только иностранные И чья биржа открыта сейчас
    foreign_open = [
        a for a in alerts
        if a["exchange"] != "MOEX" and is_market_open(a["exchange"])
    ]

    if not foreign_open:
        logger.info("TwelveData batch: нет открытых иностранных бирж")
        return

    tickers = list({a["ticker"] for a in foreign_open})
    logger.info(
        "TwelveData batch: запускаем валидацию %d тикеров "
        "(разбивка по %d в группе, rate limit 8 req/мин)",
        len(tickers), 8,
    )

    prices = await td_batch(tickers)  # внутри: rate limiter + бюджет

    if not prices:
        logger.info("TwelveData batch: нет данных (бюджет или ошибка API)")
        return

    for alert in foreign_open:
        price = prices.get(alert["ticker"])
        if price is not None:
            await _process_price(bot, db, alert, price)

    logger.info(
        "TwelveData batch: обновлено %d/%d алертов",
        sum(1 for a in foreign_open if a["ticker"] in prices),
        len(foreign_open),
    )


# ─── Обработка цены: обновление + проверка таргета ───────────────────────────

async def _process_price(
    bot: Bot, db: Database, alert: dict, current_price: float
) -> None:
    await db.update_alert_check(alert["id"], current_price)

    # Telegram-уведомления только когда рынок открыт
    if not is_market_open(alert["exchange"]):
        return

    direction = alert["direction"]
    triggered = (
        direction == "above" and current_price >= alert["target_price"]
    ) or (
        direction == "below" and current_price <= alert["target_price"]
    )

    if triggered:
        await _send_notification(bot, db, alert, current_price)


async def _send_notification(
    bot: Bot, db: Database, alert: dict, current_price: float
) -> None:
    await db.deactivate_alert(alert["id"])

    sym = CURRENCY_SYM.get(alert["currency"], alert["currency"])

    if alert["direction"] == "above":
        direction_line = "▲ Цена поднялась выше целевого уровня"
    else:
        direction_line = "▼ Цена опустилась ниже целевого уровня"

    text = (
        f"🔔 *{alert['ticker']}* — уведомление сработало\n"
        f"_{alert['company_name']}_\n\n"
        f"🎯 Цель:    `{alert['target_price']:.2f} {sym}`\n"
        f"💰 Сейчас: `{current_price:.2f} {sym}`\n\n"
        f"{direction_line}"
    )

    keyboard = alert_action_keyboard(alert["id"], alert["ticker"], alert["exchange"])

    # Отправляем всем разрешённым пользователям (или только владельцу алерта)
    recipients = ALLOWED_USER_IDS if ALLOWED_USER_IDS else [alert["user_id"]]
    for uid in recipients:
        try:
            await bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            logger.info("Уведомление: %s → user %s", alert["ticker"], uid)
        except Exception as exc:
            logger.error("Не удалось отправить уведомление user %s: %s", uid, exc)

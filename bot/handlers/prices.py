"""
Показать текущие цены по всем тикерам из портфеля пользователя.

Цены берём напрямую из БД — они обновляются каждые 30 сек через Yahoo/MOEX.
Никаких API-вызовов, 0 кредитов TwelveData.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

CURRENCY_SYM: dict[str, str] = {"RUB": "₽", "USD": "$", "HKD": "HK$"}


async def prices_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    db: Database = context.bot_data["db"]
    alerts = await db.get_user_alerts(user_id)

    if not alerts:
        await update.message.reply_text(
            "📈 Портфель пуст. Сначала добавьте акции!",
            reply_markup=main_menu_keyboard(),
        )
        return

    # Уникальные тикеры — берём первый алерт для каждого (там хранится последняя цена)
    seen: dict[tuple, dict] = {}
    for a in alerts:
        key = (a["ticker"], a["exchange"])
        if key not in seen:
            seen[key] = a

    lines = ["📈 *Текущие цены:*\n"]
    for (ticker, exchange), alert in seen.items():
        sym     = CURRENCY_SYM.get(alert["currency"], alert["currency"])
        current = alert.get("current_price")
        if current:
            lines.append(f"• *{ticker}* ({exchange}): `{current:.2f} {sym}`")
        else:
            lines.append(f"• *{ticker}* ({exchange}): нет данных")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

"""
Показать текущие цены по всем тикерам из портфеля пользователя.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import main_menu_keyboard
from bot.services.moex import get_stock_price as moex_price
from bot.services.twelvedata import get_stock_price as td_price

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

    # Уникальные тикеры
    seen: dict[tuple, dict] = {}
    for a in alerts:
        key = (a["ticker"], a["exchange"])
        if key not in seen:
            seen[key] = a

    msg = await update.message.reply_text("⏳ Получаю актуальные цены...")

    lines = ["📈 *Текущие цены:*\n"]
    for (ticker, exchange), alert in seen.items():
        if exchange == "MOEX":
            data = await moex_price(ticker)
        else:
            data = await td_price(ticker)

        sym = CURRENCY_SYM.get(alert["currency"], alert["currency"])
        if data:
            lines.append(
                f"• *{ticker}* ({exchange}): `{data['price']:.2f} {sym}`"
            )
        else:
            lines.append(f"• *{ticker}* ({exchange}): ❌ нет данных")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")

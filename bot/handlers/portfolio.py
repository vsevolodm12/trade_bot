"""
Отображение портфеля (активных алертов) и удаление позиций.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import main_menu_keyboard, portfolio_item_keyboard

logger = logging.getLogger(__name__)

CURRENCY_SYM: dict[str, str] = {"RUB": "₽", "USD": "$", "HKD": "HK$"}
DIRECTION_LABEL: dict[str, str] = {"above": "▲ выше", "below": "▼ ниже"}


async def portfolio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    db: Database = context.bot_data["db"]
    alerts = await db.get_user_alerts(user_id)

    if not alerts:
        await update.message.reply_text(
            "📊 Ваш портфель пуст.\n\nНажмите *➕ Добавить уведомление*, "
            "чтобы начать отслеживание.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.reply_text(
        f"📊 *Мой портфель* — {len(alerts)} активн. алерт(ов):",
        parse_mode="Markdown",
    )

    for alert in alerts:
        sym          = CURRENCY_SYM.get(alert["currency"], alert["currency"])
        dir_label    = DIRECTION_LABEL.get(alert["direction"], "")
        current      = alert.get("current_price")
        current_str  = f"{current:.2f} {sym}" if current else "—"

        text = (
            f"📌 *{alert['ticker']}* | {alert['company_name']}\n"
            f"🎯 Цель: {dir_label} *{alert['target_price']:.2f} {sym}*\n"
            f"💰 Последняя цена: {current_str}\n"
            f"🏦 Биржа: {alert['exchange']}"
        )
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=portfolio_item_keyboard(
                alert["id"], alert["ticker"], alert["exchange"]
            ),
        )


async def delete_alert_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    alert_id = int(query.data.split("_")[-1])
    user_id  = update.effective_user.id
    db: Database = context.bot_data["db"]

    success = await db.delete_alert(alert_id, user_id)
    if success:
        await query.edit_message_text("🗑 Алерт удалён.")
    else:
        await query.answer("❌ Не удалось удалить алерт.", show_alert=True)

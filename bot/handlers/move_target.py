"""
Диалог переноса таргета после срабатывания алерта (ConversationHandler).

Запускается inline-кнопкой «Переставить выше».
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.database import Database
from bot.keyboards import cancel_move_keyboard, main_menu_keyboard
from bot.services.moex import get_stock_price as moex_price
from bot.services.yahoo import get_stock_price as yahoo_price

logger = logging.getLogger(__name__)

WAITING_NEW_TARGET = 1

CURRENCY_SYM: dict[str, str] = {
    "RUB": "₽",
    "USD": "$",
    "HKD": "HK$",
}


# ─── Точка входа (callback_data = "move_target_{id}") ───────────────────────

async def move_target_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    alert_id = int(query.data.split("_")[-1])
    db: Database = context.bot_data["db"]
    alert = await db.get_alert_by_id(alert_id)

    if not alert:
        await query.edit_message_text("❌ Алерт не найден.")
        return ConversationHandler.END

    context.user_data["move_alert_id"] = alert_id
    context.user_data["move_alert"]    = alert

    sym = CURRENCY_SYM.get(alert["currency"], alert["currency"])
    await query.message.reply_text(
        f"📝 Введите новую целевую цену для *{alert['ticker']}*\n"
        f"_(текущий таргет: {alert['target_price']:.2f} {sym})_:",
        parse_mode="Markdown",
        reply_markup=cancel_move_keyboard(alert_id),
    )
    return WAITING_NEW_TARGET


# ─── Получение новой цены ────────────────────────────────────────────────────

async def new_target_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    raw = update.message.text.strip().replace(",", ".")

    try:
        new_target = float(raw)
        if new_target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число:", reply_markup=cancel_move_keyboard(
                context.user_data.get("move_alert_id", 0)
            )
        )
        return WAITING_NEW_TARGET

    alert_id = context.user_data.get("move_alert_id")
    alert    = context.user_data.get("move_alert")
    if not alert_id or not alert:
        await update.message.reply_text("❌ Ошибка сессии. Начните заново.")
        return ConversationHandler.END

    db      = context.bot_data["db"]
    user_id = alert["user_id"]

    # Получаем свежую цену для определения направления
    if alert["exchange"] == "MOEX":
        fresh = await moex_price(alert["ticker"])
    else:
        fresh = await yahoo_price(alert["ticker"])

    current_price = fresh["price"] if fresh else (alert.get("current_price") or 0.0)
    direction     = "above" if new_target >= current_price else "below"

    success = await db.update_alert_target(
        alert_id, user_id, new_target, direction, current_price
    )

    sym = CURRENCY_SYM.get(alert["currency"], alert["currency"])
    if success:
        action = "вырастет до" if direction == "above" else "упадёт до"
        await update.message.reply_text(
            f"✅ Таргет обновлён!\n"
            f"Уведомлю, когда *{alert['ticker']}* {action} *{new_target:.2f} {sym}*.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text("❌ Не удалось обновить таргет.")

    context.user_data.pop("move_alert_id", None)
    context.user_data.pop("move_alert",    None)
    return ConversationHandler.END


# ─── Отмена ──────────────────────────────────────────────────────────────────

async def cancel_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Перенос таргета отменён.")
    context.user_data.pop("move_alert_id", None)
    context.user_data.pop("move_alert",    None)
    return ConversationHandler.END

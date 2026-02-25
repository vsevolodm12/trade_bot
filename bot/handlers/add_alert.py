"""
Диалог добавления нового алерта (ConversationHandler).

Состояния:
    WAITING_TICKER  — ожидаем тикер от пользователя
    WAITING_TARGET  — ожидаем целевую цену
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import cancel_keyboard, main_menu_keyboard
from bot.services.moex import get_stock_price as moex_price
from bot.services.twelvedata import get_stock_price as td_price

logger = logging.getLogger(__name__)

WAITING_TICKER = 1
WAITING_TARGET = 2

CURRENCY_SYM: dict[str, str] = {
    "RUB": "₽",
    "USD": "$",
    "HKD": "HK$",
}


def _check_access(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


# ─── Точка входа ─────────────────────────────────────────────────────────────

async def add_alert_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _check_access(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 Введите тикер акции.\n\n"
        "Примеры: `SBER`, `AAPL`, `NVDA`, `0700.HK`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )
    return WAITING_TICKER


# ─── Получение тикера ────────────────────────────────────────────────────────

async def ticker_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw    = update.message.text.strip()
    ticker = raw.upper()

    # Минимальная валидация
    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    if not ticker or len(ticker) > 20 or not set(ticker).issubset(allowed_chars):
        await update.message.reply_text(
            "❌ Неверный формат тикера. Попробуйте ещё раз:",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TICKER

    await update.message.reply_text(f"🔍 Ищу *{ticker}*...", parse_mode="Markdown")

    # Ищем сначала на MOEX, затем в Twelve Data
    stock = await moex_price(ticker)
    if not stock:
        stock = await td_price(ticker)

    if not stock:
        await update.message.reply_text(
            f"❌ Акция *{ticker}* не найдена.\n"
            "Проверьте тикер и попробуйте ещё раз:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TICKER

    context.user_data["pending_stock"] = stock

    sym = CURRENCY_SYM.get(stock["currency"], stock["currency"])
    text = (
        f"✅ *Найдено: {stock['company_name']} ({stock['exchange']})*\n"
        f"Текущая цена: *{stock['price']:.2f} {sym}*\n\n"
        f"Введите целевую цену (число):"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=cancel_keyboard()
    )
    return WAITING_TARGET


# ─── Получение целевой цены ──────────────────────────────────────────────────

async def target_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip().replace(",", ".")

    try:
        target = float(raw)
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (например: `350` или `150.50`):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TARGET

    stock = context.user_data.get("pending_stock")
    if not stock:
        await update.message.reply_text("❌ Ошибка сессии. Начните заново.")
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    user_id      = update.effective_user.id
    current      = stock["price"]
    direction    = "above" if target >= current else "below"

    await db.add_alert(
        user_id      = user_id,
        ticker       = stock["ticker"],
        exchange     = stock["exchange"],
        company_name = stock["company_name"],
        target_price = target,
        currency     = stock["currency"],
        direction    = direction,
        current_price= current,
    )

    sym    = CURRENCY_SYM.get(stock["currency"], stock["currency"])
    action = "вырастет до" if direction == "above" else "упадёт до"
    text   = (
        f"✅ *Принято!* Маякну, когда *{stock['company_name']}* "
        f"{action} *{target:.2f} {sym}*.\n"
        f"_(Текущая: {current:.2f} {sym})_"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
    )

    context.user_data.pop("pending_stock", None)
    return ConversationHandler.END


# ─── Отмена ──────────────────────────────────────────────────────────────────

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("❌ Добавление отменено.")
    else:
        await update.message.reply_text(
            "❌ Добавление отменено.", reply_markup=main_menu_keyboard()
        )
    context.user_data.pop("pending_stock", None)
    return ConversationHandler.END

"""
Диалог добавления нового алерта (ConversationHandler).

Состояния:
    WAITING_TICKER        — ожидаем тикер от пользователя
    WAITING_DIRECTION     — ожидаем выбор направления (▲/▼/↕️)
    WAITING_TARGET        — ожидаем целевую цену (первую или единственную)
    WAITING_TARGET_SECOND — ожидаем вторую целевую цену (режим "оба направления")
"""
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import cancel_keyboard, main_menu_keyboard
from bot.services.moex import get_stock_price as moex_price
from bot.services.twelvedata import get_stock_price as td_price

logger = logging.getLogger(__name__)

WAITING_TICKER        = 1
WAITING_DIRECTION     = 2
WAITING_TARGET        = 3
WAITING_TARGET_SECOND = 4

CURRENCY_SYM: dict[str, str] = {
    "RUB": "₽",
    "USD": "$",
    "HKD": "HK$",
}


def _check_access(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def _direction_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▲ Только рост",    callback_data="dir_above"),
            InlineKeyboardButton("▼ Только падение", callback_data="dir_below"),
        ],
        [
            InlineKeyboardButton("↕️ Оба направления", callback_data="dir_both"),
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data="cancel"),
        ],
    ])


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

    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
    if not ticker or len(ticker) > 20 or not set(ticker).issubset(allowed_chars):
        await update.message.reply_text(
            "❌ Неверный формат тикера. Попробуйте ещё раз:",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TICKER

    await update.message.reply_text(f"🔍 Ищу *{ticker}*...", parse_mode="Markdown")

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
        f"✅ *{stock['company_name']} ({stock['exchange']})*\n"
        f"Текущая цена: *{stock['price']:.2f} {sym}*\n\n"
        f"Выберите направление уведомления:"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=_direction_keyboard()
    )
    return WAITING_DIRECTION


# ─── Выбор направления ────────────────────────────────────────────────────────

async def direction_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    direction = query.data  # "dir_above" | "dir_below" | "dir_both"
    context.user_data["alert_direction"] = direction

    stock = context.user_data.get("pending_stock")
    if not stock:
        await query.edit_message_text("❌ Ошибка сессии. Начните заново.")
        return ConversationHandler.END

    sym = CURRENCY_SYM.get(stock["currency"], stock["currency"])

    if direction == "dir_above":
        prompt = (
            f"▲ *Уведомление при росте*\n"
            f"Текущая: {stock['price']:.2f} {sym}\n\n"
            f"Введите целевую цену _(выше текущей)_:"
        )
    elif direction == "dir_below":
        prompt = (
            f"▼ *Уведомление при падении*\n"
            f"Текущая: {stock['price']:.2f} {sym}\n\n"
            f"Введите целевую цену _(ниже текущей)_:"
        )
    else:  # dir_both
        prompt = (
            f"↕️ *Два уведомления*\n"
            f"Текущая: {stock['price']:.2f} {sym}\n\n"
            f"Шаг 1/2 — введите цель роста ▲:"
        )

    await query.edit_message_text(
        prompt, parse_mode="Markdown", reply_markup=cancel_keyboard()
    )
    return WAITING_TARGET


# ─── Целевая цена (первая или единственная) ──────────────────────────────────

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

    stock     = context.user_data.get("pending_stock")
    direction = context.user_data.get("alert_direction", "dir_above")

    if not stock:
        await update.message.reply_text("❌ Ошибка сессии. Начните заново.")
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    user_id      = update.effective_user.id
    sym          = CURRENCY_SYM.get(stock["currency"], stock["currency"])

    if direction == "dir_both":
        # Запоминаем первый таргет, просим второй
        context.user_data["target_above"] = target
        await update.message.reply_text(
            f"▲ Цель роста *{target:.2f} {sym}* — принято!\n\n"
            f"Шаг 2/2 — введите цель падения ▼:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TARGET_SECOND

    # Один алерт
    actual_direction = "above" if direction == "dir_above" else "below"
    await db.add_alert(
        user_id      = user_id,
        ticker       = stock["ticker"],
        exchange     = stock["exchange"],
        company_name = stock["company_name"],
        target_price = target,
        currency     = stock["currency"],
        direction    = actual_direction,
        current_price= stock["price"],
    )

    action = "вырастет до" if actual_direction == "above" else "упадёт до"
    await update.message.reply_text(
        f"✅ Маякну, когда *{stock['company_name']}* "
        f"{action} *{target:.2f} {sym}*.\n"
        f"_(Текущая: {stock['price']:.2f} {sym})_",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    context.user_data.pop("pending_stock", None)
    context.user_data.pop("alert_direction", None)
    return ConversationHandler.END


# ─── Вторая целевая цена (режим "оба направления") ───────────────────────────

async def target_second_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    raw = update.message.text.strip().replace(",", ".")

    try:
        target_below = float(raw)
        if target_below <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число:",
            reply_markup=cancel_keyboard(),
        )
        return WAITING_TARGET_SECOND

    stock        = context.user_data.get("pending_stock")
    target_above = context.user_data.get("target_above")

    if not stock or target_above is None:
        await update.message.reply_text("❌ Ошибка сессии. Начните заново.")
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    user_id      = update.effective_user.id
    sym          = CURRENCY_SYM.get(stock["currency"], stock["currency"])

    await db.add_alert(
        user_id      = user_id,
        ticker       = stock["ticker"],
        exchange     = stock["exchange"],
        company_name = stock["company_name"],
        target_price = target_above,
        currency     = stock["currency"],
        direction    = "above",
        current_price= stock["price"],
    )
    await db.add_alert(
        user_id      = user_id,
        ticker       = stock["ticker"],
        exchange     = stock["exchange"],
        company_name = stock["company_name"],
        target_price = target_below,
        currency     = stock["currency"],
        direction    = "below",
        current_price= stock["price"],
    )

    await update.message.reply_text(
        f"✅ *Два уведомления добавлены!*\n"
        f"▲ Рост до *{target_above:.2f} {sym}*\n"
        f"▼ Падение до *{target_below:.2f} {sym}*\n"
        f"_(Текущая: {stock['price']:.2f} {sym})_",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    context.user_data.pop("pending_stock", None)
    context.user_data.pop("alert_direction", None)
    context.user_data.pop("target_above", None)
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
    context.user_data.pop("alert_direction", None)
    context.user_data.pop("target_above", None)
    return ConversationHandler.END

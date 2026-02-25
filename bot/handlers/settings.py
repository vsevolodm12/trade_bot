"""
Управление настройками пользователя (частота проверки цен).
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import (
    settings_keyboard,
    settings_ru_keyboard,
    settings_us_keyboard,
)

logger = logging.getLogger(__name__)


def _settings_text(settings: dict) -> str:
    ru_min = settings["interval_ru"] // 60
    us_min = settings["interval_us"] // 60
    return (
        f"⚙️ *Настройки*\n\n"
        f"🇷🇺 Проверка РФ (MOEX): каждые *{ru_min} мин.*\n"
        f"🇺🇸🇭🇰 Проверка США/Гонконг: каждые *{us_min} мин.*"
    )


async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    db: Database = context.bot_data["db"]
    s = await db.get_user_settings(user_id)
    await update.message.reply_text(
        _settings_text(s), parse_mode="Markdown", reply_markup=settings_keyboard()
    )


# ─── Показ подменю ───────────────────────────────────────────────────────────

async def settings_ru_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🇷🇺 Выберите частоту проверки *российского* рынка (MOEX):",
        parse_mode="Markdown",
        reply_markup=settings_ru_keyboard(),
    )


async def settings_us_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🇺🇸🇭🇰 Выберите частоту проверки *рынков США и Гонконга*:",
        parse_mode="Markdown",
        reply_markup=settings_us_keyboard(),
    )


# ─── Установка интервалов ────────────────────────────────────────────────────

async def set_interval_ru_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query    = update.callback_query
    await query.answer()
    interval = int(query.data.split("_")[-1])  # "set_ru_60" → 60
    user_id  = update.effective_user.id
    db: Database = context.bot_data["db"]

    await db.upsert_user_settings(user_id, interval_ru=interval)
    s = await db.get_user_settings(user_id)
    await query.edit_message_text(
        _settings_text(s), parse_mode="Markdown", reply_markup=settings_keyboard()
    )


async def set_interval_us_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query    = update.callback_query
    await query.answer()
    interval = int(query.data.split("_")[-1])  # "set_us_180" → 180
    user_id  = update.effective_user.id
    db: Database = context.bot_data["db"]

    await db.upsert_user_settings(user_id, interval_us=interval)
    s = await db.get_user_settings(user_id)
    await query.edit_message_text(
        _settings_text(s), parse_mode="Markdown", reply_markup=settings_keyboard()
    )


async def back_to_settings_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query    = update.callback_query
    await query.answer()
    user_id  = update.effective_user.id
    db: Database = context.bot_data["db"]
    s = await db.get_user_settings(user_id)
    await query.edit_message_text(
        _settings_text(s), parse_mode="Markdown", reply_markup=settings_keyboard()
    )

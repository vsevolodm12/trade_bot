import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS, WEB_URL
from bot.keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    # Проверка разрешённых пользователей (если список задан)
    if ALLOWED_USER_IDS and user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        logger.warning("Отказ в доступе: user_id=%s", user.id)
        return

    text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Я помогу отслеживать цены акций и уведомлю, когда цена достигнет "
        "нужного уровня.\n\n"
        "📌 Выберите действие в меню ниже:"
    )

    # Если WEB_URL задан — добавляем кнопку открытия Mini App
    if WEB_URL:
        webapp_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📊 Открыть портфель",
                web_app=WebAppInfo(url=WEB_URL),
            )]
        ])
        await update.message.reply_text(text, reply_markup=webapp_keyboard)
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

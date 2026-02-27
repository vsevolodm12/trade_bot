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

    # Проверка разрешённых пользователей
    if ALLOWED_USER_IDS and user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        logger.warning("Отказ в доступе: user_id=%s", user.id)
        return

    text = (
        f"Привет, {user.first_name}! 👋\n\n"
        "Здесь ты можешь отслеживать цены акций и получать уведомления, "
        "когда цена достигает нужного уровня.\n\n"
        "Открой интерфейс — всё уже там 👇"
    )

    if WEB_URL:
        if WEB_URL.startswith("https://"):
            btn = InlineKeyboardButton("📊 Открыть Trade Alerts", web_app=WebAppInfo(url=WEB_URL))
        else:
            btn = InlineKeyboardButton("📊 Открыть Trade Alerts", url=WEB_URL)

        # Одно сообщение: текст + inline кнопка (как на скриншоте)
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[btn]]),
        )
    else:
        # Без web url — показываем reply keyboard
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

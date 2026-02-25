"""
Точка входа: сборка Application, регистрация хендлеров, запуск.
"""
import logging
import os
import sys
import warnings
from telegram.warnings import PTBUserWarning

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import TELEGRAM_BOT_TOKEN, DB_PATH
from bot.database import Database
from bot.services.price_checker import (
    check_prices_job,
    td_batch_job,
    TD_BATCH_INTERVAL_SEC,
)

from bot.handlers.start import start_handler
from bot.handlers.add_alert import (
    add_alert_entry,
    ticker_received,
    target_received,
    cancel_add,
    WAITING_TICKER,
    WAITING_TARGET,
)
from bot.handlers.move_target import (
    move_target_entry,
    new_target_received,
    cancel_move,
    WAITING_NEW_TARGET,
)
from bot.handlers.portfolio import delete_alert_callback
from bot.handlers.prices import prices_handler
from bot.handlers.closest import closest_handler

# ─── Логирование ─────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

# Заглушаем PTBUserWarning о per_message (поведение корректно для нашей схемы,
# где в states смешаны MessageHandler и CallbackQueryHandler)
warnings.filterwarnings("ignore", category=PTBUserWarning)

# Логируем только в stdout — nohup в start.sh сам перенаправит в файл.
# Так избегаем двойной записи при запуске через start.sh.
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Снизим шум от PTB и aiohttp
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ─── post_init: инициализация БД ─────────────────────────────────────────────

async def post_init(application: Application) -> None:
    db: Database = application.bot_data["db"]
    await db.init()
    logger.info("БД инициализирована")


# ─── Сборка приложения ────────────────────────────────────────────────────────

def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Переменная TELEGRAM_BOT_TOKEN не задана в .env!")
        sys.exit(1)

    db = Database(DB_PATH)

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.bot_data["db"] = db

    # ── ConversationHandler: добавление алерта ──────────────────────────────
    # Только MessageHandler в entry_points → per_message=False безопасен.
    # Кнопка «Отмена» (CallbackQueryHandler) живёт в states, а не в fallbacks,
    # чтобы PTB не выдавал предупреждение.
    add_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(r"^➕ Добавить уведомление$"), add_alert_entry
            )
        ],
        states={
            WAITING_TICKER: [
                CallbackQueryHandler(cancel_add, pattern="^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ticker_received),
            ],
            WAITING_TARGET: [
                CallbackQueryHandler(cancel_add, pattern="^cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, target_received),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_add),
            # Нажатие кнопки главного меню завершает диалог
            MessageHandler(
                filters.Regex(r"^📈 Текущие цены$"),
                cancel_add,
            ),
        ],
    )

    # ── ConversationHandler: перенос таргета ────────────────────────────────
    # Entry point — CallbackQuery, поэтому ставим per_message=True.
    move_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(move_target_entry, pattern=r"^move_target_\d+$")
        ],
        states={
            WAITING_NEW_TARGET: [
                CallbackQueryHandler(cancel_move, pattern=r"^cancel_move_\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_target_received),
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_move),
        ],
        per_message=False,  # ждём текстовый ответ, не callback → False корректен
    )

    # ── Регистрация хендлеров ───────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(add_conv)
    app.add_handler(move_conv)

    # Главное меню
    app.add_handler(
        MessageHandler(filters.Regex(r"^🎯 Близко к цели$"), closest_handler)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^📈 Текущие цены$"), prices_handler)
    )

    # Callback-кнопки (удаление алерта из уведомлений / "Близко к цели")
    app.add_handler(
        CallbackQueryHandler(delete_alert_callback, pattern=r"^delete_alert_\d+$")
    )

    # ── Yahoo/MOEX: непрерывный мониторинг каждые 30 сек ───────────────────
    app.job_queue.run_repeating(check_prices_job, interval=30, first=15)

    # ── TwelveData: батч-валидация раз в несколько часов ───────────────────
    # TD_BATCH_INTERVAL_SEC по умолчанию 10800 (3 ч).
    # 100 тикеров × 8 батчей/день = 800 кредитов/день — точно в лимите.
    app.job_queue.run_repeating(
        td_batch_job,
        interval=TD_BATCH_INTERVAL_SEC,
        first=120,  # первый запуск через 2 мин после старта
    )
    logger.info(
        "TwelveData батч-проверка: каждые %.1f ч",
        TD_BATCH_INTERVAL_SEC / 3600,
    )

    return app


# ─── Запуск ──────────────────────────────────────────────────────────────────

def main() -> None:
    app = build_app()
    logger.info("Бот запускается...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

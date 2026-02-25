"""
Показывает алерты отсортированные по близости к таргету.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.database import Database
from bot.keyboards import main_menu_keyboard, portfolio_item_keyboard

logger = logging.getLogger(__name__)

CURRENCY_SYM    = {"RUB": "₽", "USD": "$", "HKD": "HK$"}
DIRECTION_LABEL = {"above": "▲", "below": "▼"}
BAR_LEN = 12  # длина прогресс-бара


def _progress_bar(pct: float) -> str:
    filled = round(BAR_LEN * pct / 100)
    return "█" * filled + "░" * (BAR_LEN - filled)


def _calc(alert: dict) -> dict:
    """Добавляет pct и dist_pct к алерту."""
    current = alert.get("current_price")
    target  = alert["target_price"]
    direction = alert["direction"]

    pct = None
    dist_pct = None
    if current and target and current > 0 and target > 0:
        pct = min(100.0, (current / target * 100) if direction == "above"
                  else (target / current * 100))
        dist_pct = abs((target - current) / current * 100)

    return {**alert, "pct": pct, "dist_pct": dist_pct}


async def closest_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    db: Database = context.bot_data["db"]
    alerts = await db.get_user_alerts(user_id)

    if not alerts:
        await update.message.reply_text(
            "📊 Портфель пуст.",
            reply_markup=main_menu_keyboard(),
        )
        return

    enriched = [_calc(a) for a in alerts]
    enriched.sort(key=lambda a: a["dist_pct"] if a["dist_pct"] is not None else 9999)

    await update.message.reply_text(
        f"🎯 *Близко к цели* — {len(enriched)} уведомлений\n_Отсортировано по близости к таргету_",
        parse_mode="Markdown",
    )

    for a in enriched:
        sym       = CURRENCY_SYM.get(a["currency"], a["currency"])
        dir_label = DIRECTION_LABEL.get(a["direction"], "")
        current   = a.get("current_price")
        pct       = a["pct"]
        dist_pct  = a["dist_pct"]

        current_str = f"{current:.2f} {sym}" if current else "—"

        if pct is not None:
            bar  = _progress_bar(pct)
            prog = f"\n`{bar}` {pct:.1f}%"
            dist = f"  _{dist_pct:.1f}% до цели_" if dist_pct is not None else ""
        else:
            prog = ""
            dist = ""

        text = (
            f"📌 *{a['ticker']}* | {a['company_name']}\n"
            f"💰 Сейчас: `{current_str}`\n"
            f"🎯 Цель: {dir_label} `{a['target_price']:.2f} {sym}`"
            f"{prog}{dist}"
        )

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=portfolio_item_keyboard(a["id"], a["ticker"], a["exchange"]),
        )

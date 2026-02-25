from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# ─── Главное меню ────────────────────────────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["➕ Добавить уведомление", "📊 Мой портфель"],
            ["🎯 Близко к цели",        "📈 Текущие цены"],
            ["⚙️ Настройки"],
        ],
        resize_keyboard=True,
    )


# ─── Кнопка отмены (inline) ──────────────────────────────────────────────────

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
    )


# ─── Кнопки алерта (после срабатывания) ──────────────────────────────────────

def alert_action_keyboard(
    alert_id: int, ticker: str, exchange: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Удалить алерт", callback_data=f"delete_alert_{alert_id}"
                ),
                InlineKeyboardButton(
                    "⬆️ Переставить выше", callback_data=f"move_target_{alert_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📊 Открыть график", url=_tradingview_url(ticker, exchange)
                )
            ],
        ]
    )


# ─── Кнопки позиции в портфеле ───────────────────────────────────────────────

def portfolio_item_keyboard(
    alert_id: int, ticker: str, exchange: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Удалить", callback_data=f"delete_alert_{alert_id}"
                ),
                InlineKeyboardButton(
                    "📊 График", url=_tradingview_url(ticker, exchange)
                ),
            ]
        ]
    )


# ─── Настройки ───────────────────────────────────────────────────────────────

def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🇷🇺 Частота МБ (Россия)", callback_data="settings_ru")],
            [InlineKeyboardButton("🇺🇸🇭🇰 Частота (США / Гонконг)", callback_data="settings_us")],
        ]
    )


def settings_ru_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("1 мин",  callback_data="set_ru_60"),
                InlineKeyboardButton("2 мин",  callback_data="set_ru_120"),
                InlineKeyboardButton("5 мин",  callback_data="set_ru_300"),
            ],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_to_settings")],
        ]
    )


def settings_us_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("3 мин",  callback_data="set_us_180"),
                InlineKeyboardButton("5 мин",  callback_data="set_us_300"),
                InlineKeyboardButton("10 мин", callback_data="set_us_600"),
            ],
            [InlineKeyboardButton("↩️ Назад", callback_data="back_to_settings")],
        ]
    )


# ─── Кнопка отмены переноса таргета ─────────────────────────────────────────

def cancel_move_keyboard(alert_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_move_{alert_id}")]]
    )


# ─── Вспомогательная функция ─────────────────────────────────────────────────

def _tradingview_url(ticker: str, exchange: str) -> str:
    if exchange == "MOEX":
        return f"https://www.tradingview.com/symbols/MOEX-{ticker}/"
    if exchange in ("HKEX", "HKSE"):
        return f"https://www.tradingview.com/symbols/HKEX-{ticker}/"
    return f"https://www.tradingview.com/symbols/{ticker}/"

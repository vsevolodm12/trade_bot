import time
import logging
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self) -> None:
        """Создать таблицы при первом запуске."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    ticker        TEXT    NOT NULL,
                    exchange      TEXT    NOT NULL,
                    company_name  TEXT    NOT NULL,
                    target_price  REAL    NOT NULL,
                    currency      TEXT    NOT NULL,
                    direction     TEXT    NOT NULL,
                    current_price REAL,
                    last_checked  REAL    DEFAULT 0,
                    is_active     INTEGER NOT NULL DEFAULT 1,
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id          INTEGER PRIMARY KEY,
                    interval_ru      INTEGER NOT NULL DEFAULT 60,
                    interval_us      INTEGER NOT NULL DEFAULT 180,
                    display_currency TEXT    NOT NULL DEFAULT 'original'
                )
            """)
            # Миграция: добавляем колонку если таблица уже существовала без неё
            try:
                await db.execute(
                    "ALTER TABLE user_settings ADD COLUMN display_currency TEXT NOT NULL DEFAULT 'original'"
                )
            except Exception:
                pass  # колонка уже есть
            await db.commit()
        logger.info("База данных инициализирована: %s", self.db_path)

    # ─── Алерты ────────────────────────────────────────────────────────────────

    async def add_alert(
        self,
        user_id: int,
        ticker: str,
        exchange: str,
        company_name: str,
        target_price: float,
        currency: str,
        direction: str,
        current_price: float,
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO alerts
                    (user_id, ticker, exchange, company_name,
                     target_price, currency, direction, current_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, ticker, exchange, company_name,
                 target_price, currency, direction, current_price),
            )
            await db.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    async def get_user_alerts(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM alerts
                WHERE user_id = ? AND is_active = 1
                ORDER BY created_at DESC
                """,
                (user_id,),
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_all_active_alerts_web(self) -> list[dict]:
        """Все активные алерты без фильтра по user_id (для веб-интерфейса)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM alerts
                WHERE is_active = 1
                ORDER BY exchange, ticker
                """
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_all_active_alerts(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT a.*,
                       COALESCE(s.interval_ru, 60)  AS interval_ru,
                       COALESCE(s.interval_us, 180) AS interval_us
                FROM alerts a
                LEFT JOIN user_settings s ON a.user_id = s.user_id
                WHERE a.is_active = 1
                """
            ) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get_alert_by_id(self, alert_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM alerts WHERE id = ?", (alert_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def delete_alert(self, alert_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM alerts WHERE id = ? AND user_id = ?",
                (alert_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def deactivate_alert(self, alert_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE alerts SET is_active = 0 WHERE id = ?", (alert_id,)
            )
            await db.commit()

    async def update_alert_target(
        self,
        alert_id: int,
        user_id: int,
        new_target: float,
        direction: str,
        current_price: float,
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                UPDATE alerts
                SET target_price  = ?,
                    direction     = ?,
                    current_price = ?,
                    is_active     = 1,
                    last_checked  = 0
                WHERE id = ? AND user_id = ?
                """,
                (new_target, direction, current_price, alert_id, user_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def update_alert_check(self, alert_id: int, current_price: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE alerts SET current_price = ?, last_checked = ? WHERE id = ?",
                (current_price, time.time(), alert_id),
            )
            await db.commit()

    # ─── Настройки пользователя ─────────────────────────────────────────────

    async def get_user_settings(self, user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return dict(row)
                return {"user_id": user_id, "interval_ru": 60, "interval_us": 180, "display_currency": "original"}

    async def upsert_user_settings(
        self,
        user_id: int,
        interval_ru: Optional[int] = None,
        interval_us: Optional[int] = None,
        display_currency: Optional[str] = None,
    ) -> None:
        current = await self.get_user_settings(user_id)
        new_ru  = interval_ru       if interval_ru       is not None else current["interval_ru"]
        new_us  = interval_us       if interval_us       is not None else current["interval_us"]
        new_cur = display_currency  if display_currency  is not None else current["display_currency"]

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO user_settings (user_id, interval_ru, interval_us, display_currency)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    interval_ru      = excluded.interval_ru,
                    interval_us      = excluded.interval_us,
                    display_currency = excluded.display_currency
                """,
                (user_id, new_ru, new_us, new_cur),
            )
            await db.commit()

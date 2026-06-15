"""Точка входу: long polling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, TelegramObject

from .config import load_config
from .db import Database
from .handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("splitdaddy")


class RememberUserMiddleware(BaseMiddleware):
    """На кожне повідомлення зберігає автора в known_users.

    Так бот «знайомиться» з людьми (особливо без @username) — потім їх можна
    резолвити у /spent навіть лише за @username чи додавати через @all.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user and not event.from_user.is_bot:
            u = event.from_user
            await self._db.remember_user(
                u.id, u.username, u.full_name or (u.username or str(u.id))
            )
        return await handler(event, data)


async def main() -> None:
    config = load_config()

    db = Database(config.db_path)
    await db.connect()
    logger.info("DB ready at %s", config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["db"] = db          # інжектиться в хендлери за іменем параметра `db`
    dp["config"] = config  # доступний хендлерам як параметр `config`
    dp.message.middleware(RememberUserMiddleware(db))
    dp.include_router(router)

    try:
        logger.info("Starting long polling…")
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

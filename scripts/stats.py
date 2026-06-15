"""Друк глобальної статистики бота в консоль.

Запуск на сервері:  .venv/bin/python -m scripts.stats
"""

from __future__ import annotations

import asyncio

from bot.config import load_config
from bot.db import Database
from bot.formatting import money


async def main() -> None:
    config = load_config()
    db = Database(config.db_path)
    await db.connect()
    try:
        s = await db.get_stats()
    finally:
        await db.close()

    closed = s["parties_total"] - s["parties_open"]
    print("📈 SplitDaddy — статистика")
    print(f"  Користувачів:       {s['users']}")
    print(f"  Вечірок:            {s['parties_total']} "
          f"(відкритих {s['parties_open']}, закритих {closed})")
    print(f"  Чатів із ботом:     {s['chats']}")
    print(f"  Витрат:             {s['expenses']}")
    print(f"  Сумарно проведено:  {money(s['total_cents'])}")


if __name__ == "__main__":
    asyncio.run(main())

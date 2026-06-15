"""Спільні фікстури для тестів."""

import pytest_asyncio

from bot.db import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    """Свіжа БД у тимчасовому файлі на кожен тест."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()

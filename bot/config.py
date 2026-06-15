"""Конфігурація через змінні оточення."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    default_currency: str = "UAH"


def load_config() -> Config:
    """Зчитати конфіг з .env / оточення. Кидає помилку, якщо немає токена."""
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Не задано BOT_TOKEN. Скопіюйте .env.example у .env і впишіть токен."
        )

    db_path = os.getenv("DB_PATH", "splitdaddy.db").strip() or "splitdaddy.db"

    return Config(bot_token=token, db_path=db_path)

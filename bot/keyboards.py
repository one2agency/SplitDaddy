"""Клавіатури: reply (постійні кнопки внизу) та inline (під повідомленнями)."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Підписи кнопок — вони ж приходять як текст повідомлення при натисканні.
BTN_NEW = "🎉 Нова вечірка"
BTN_MEMBERS = "👥 Учасники"
BTN_ADD = "➕ Додати учасників"
BTN_SUMMARY = "📊 Підсумок"
BTN_FINISH = "✅ Завершити"
BTN_HELP = "❓ Допомога"

BUTTON_LABELS = {BTN_NEW, BTN_MEMBERS, BTN_ADD, BTN_SUMMARY, BTN_FINISH, BTN_HELP}


def main_keyboard() -> ReplyKeyboardMarkup:
    # Примітка: KeyboardButtonRequestUsers (нативний пікер) Telegram дозволяє
    # ЛИШЕ в приватних чатах — у групі він валить надсилання клавіатури. Тому
    # «➕ Додати учасників» — звичайна кнопка-підказка, а реально додаємо тегами.
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_SUMMARY)],
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_MEMBERS)],
            [KeyboardButton(text=BTN_FINISH), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Витрата: 350 коктейлі @ira",
    )


def join_keyboard(party_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🙋 Я в ділі", callback_data=f"join:{party_id}")]
        ]
    )


def expense_actions_keyboard(party_id: int, seq: int) -> InlineKeyboardMarkup:
    """Дії над конкретною витратою: редагувати / видалити."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Редагувати", callback_data=f"edit:{party_id}:{seq}"
                ),
                InlineKeyboardButton(
                    text="🗑 Видалити витрату", callback_data=f"del:{party_id}:{seq}"
                ),
            ]
        ]
    )

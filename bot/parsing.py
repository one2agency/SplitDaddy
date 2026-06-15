"""Розбір текстового вводу з опорою на message entities, а не на сирий текст.

Telegram має два типи згадок:
  * mention      — для користувачів з @username (несе лише текст «@username»);
  * text_mention — для користувачів без username (несе об'єкт user з user.id).
Тому учасників збираємо саме з entities, щоб коректно ловити людей без @.

Формати:
  * витрата:      <сума> <опис> [@user...] [-я]
  * додати уч.:   + @user [@user...]
  * прибрати уч.: - @user [@user...]
  * видалити:     видалити BX-3   (або: видалити 3)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from aiogram.types import Message, User

# Перше число: 800, 800.50, 800,50
_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")
# Витрата = повідомлення, що починається з числа.
_STARTS_WITH_NUMBER = re.compile(r"^\s*\d")
# «видалити BX-3», «видалити #BX-3», «видалити 3»
_DELETE_RE = re.compile(
    r"^\s*(?:видалити|delete|del)\s+#?(?:([A-Za-z2-9]{2,4})-)?(\d+)\s*$",
    re.IGNORECASE,
)

_EXCLUDE_SELF = {"-я", "-me", "-i", "-я."}


class ParseError(Exception):
    """Помилка розбору з людиночитабельним повідомленням (українською)."""


@dataclass
class ParsedExpense:
    amount_cents: int
    description: str
    text_mention_users: list[User] = field(default_factory=list)
    mention_usernames: list[str] = field(default_factory=list)
    exclude_self: bool = False

    @property
    def has_tags(self) -> bool:
        return bool(self.text_mention_users or self.mention_usernames)


@dataclass
class ParsedParticipantOp:
    op: str  # '+' або '-'
    text_mention_users: list[User] = field(default_factory=list)
    mention_usernames: list[str] = field(default_factory=list)


def parse_amount_to_cents(raw: str) -> int:
    """'800,50' / '800.50' / '800' -> копійки (int). Кидає ParseError при невдачі."""
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        raise ParseError(f"Не вдалося розпізнати суму: «{raw}»")
    if value <= 0:
        raise ParseError("Сума має бути більшою за нуль.")
    cents = (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def looks_like_expense(text: str) -> bool:
    return bool(_STARTS_WITH_NUMBER.match(text or ""))


def _collect_mentions(message: Message) -> tuple[list[User], list[str], list[str]]:
    """Повертає (text_mention_users, mention_usernames, тексти-згадок для вирізання)."""
    text = message.text or ""
    users: list[User] = []
    usernames: list[str] = []
    mention_texts: list[str] = []
    for ent in message.entities or []:
        if ent.type == "text_mention" and ent.user is not None:
            users.append(ent.user)
            mention_texts.append(ent.extract_from(text))
        elif ent.type == "mention":
            uname = ent.extract_from(text)
            usernames.append(uname)
            mention_texts.append(uname)
    return users, usernames, mention_texts


def parse_expense(message: Message) -> ParsedExpense:
    text = (message.text or "").strip()

    amount_match = _AMOUNT_RE.match(text)
    if amount_match is None:
        raise ParseError(
            "Не бачу суму. Витрата починається з числа: напр. <code>350 коктейлі @ira</code>."
        )
    amount_cents = parse_amount_to_cents(amount_match.group(0))

    users, usernames, mention_texts = _collect_mentions(message)

    tokens = text.split()
    exclude_self = any(t.lower() in _EXCLUDE_SELF for t in tokens)

    # Опис = текст без суми, без згадок, без ключа -я.
    description = text[amount_match.end():]
    for mt in mention_texts:
        description = description.replace(mt, " ", 1)
    desc_tokens = [t for t in description.split() if t.lower() not in _EXCLUDE_SELF]
    description = " ".join(desc_tokens).strip()

    return ParsedExpense(
        amount_cents=amount_cents,
        description=description,
        text_mention_users=users,
        mention_usernames=usernames,
        exclude_self=exclude_self,
    )


def parse_participant_op(message: Message) -> ParsedParticipantOp | None:
    """Розпізнати '+ @user' / '- @user'. Повертає None, якщо це не така команда."""
    text = (message.text or "").lstrip()
    if not text or text[0] not in "+-":
        return None
    if looks_like_expense(text):  # '-я' всередині витрати сюди не потрапляє
        return None
    users, usernames, _ = _collect_mentions(message)
    if not users and not usernames:
        return None
    return ParsedParticipantOp(op=text[0], text_mention_users=users, mention_usernames=usernames)


def parse_delete_text(text: str) -> tuple[str | None, int] | None:
    """'видалити BX-3' -> ('BX', 3); 'видалити 3' -> (None, 3). Інакше None."""
    m = _DELETE_RE.match(text or "")
    if m is None:
        return None
    code = m.group(1).upper() if m.group(1) else None
    return code, int(m.group(2))

"""Тести розбору суми (частина parsing, що не залежить від Telegram-обʼєктів)."""

import pytest
from aiogram.types import Message, MessageEntity, User

from bot.parsing import (
    ParseError,
    looks_like_expense,
    parse_amount_to_cents,
    parse_delete_text,
    parse_expense,
)


def _msg(text, uid=1, entities=None):
    return Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": -100, "type": "group"},
            "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"},
            "text": text,
            "entities": [e.model_dump() for e in (entities or [])],
        }
    )


def test_integer_amount():
    assert parse_amount_to_cents("800") == 80000


def test_dot_decimal():
    assert parse_amount_to_cents("800.50") == 80050


def test_comma_decimal():
    assert parse_amount_to_cents("800,50") == 80050


def test_single_decimal_digit():
    assert parse_amount_to_cents("800.5") == 80050


def test_rounding_half_up():
    assert parse_amount_to_cents("0.005") == 1


def test_zero_rejected():
    with pytest.raises(ParseError):
        parse_amount_to_cents("0")


def test_garbage_rejected():
    with pytest.raises(ParseError):
        parse_amount_to_cents("abc")


def test_looks_like_expense():
    assert looks_like_expense("1200 піца")
    assert looks_like_expense("  350 коктейлі @ira")
    assert not looks_like_expense("+ @oleh")
    assert not looks_like_expense("видалити BX-3")
    assert not looks_like_expense("привіт усім")


def test_parse_delete_with_code():
    assert parse_delete_text("видалити BX-3") == ("BX", 3)
    assert parse_delete_text("видалити #BX-3") == ("BX", 3)
    assert parse_delete_text("видалити k7-12") == ("K7", 12)


def test_parse_delete_without_code():
    assert parse_delete_text("видалити 5") == (None, 5)


def test_parse_delete_non_match():
    assert parse_delete_text("видалити все життя") is None
    assert parse_delete_text("1200 піца") is None


# ---- parse_expense (з message entities) -----------------------------------


def test_expense_no_tags():
    p = parse_expense(_msg("1200 піца"))
    assert p.amount_cents == 120000
    assert p.description == "піца"
    assert not p.has_tags
    assert not p.exclude_self


def test_expense_with_mention():
    text = "350 коктейлі @ira @oleh"
    ents = [
        MessageEntity(type="mention", offset=text.index("@ira"), length=4),
        MessageEntity(type="mention", offset=text.index("@oleh"), length=5),
    ]
    p = parse_expense(_msg(text, entities=ents))
    assert p.amount_cents == 35000
    assert p.description == "коктейлі"
    assert p.mention_usernames == ["@ira", "@oleh"]
    assert p.has_tags


def test_expense_exclude_self():
    text = "800 таксі @ira -я"
    ents = [MessageEntity(type="mention", offset=text.index("@ira"), length=4)]
    p = parse_expense(_msg(text, entities=ents))
    assert p.amount_cents == 80000
    assert p.description == "таксі"
    assert p.exclude_self
    assert p.mention_usernames == ["@ira"]


def test_expense_comma_amount_and_description():
    p = parse_expense(_msg("800,50 таксі додому"))
    assert p.amount_cents == 80050
    assert p.description == "таксі додому"


def test_expense_text_mention_carries_user():
    text = "600 вхід Друг -me"
    ents = [
        MessageEntity(
            type="text_mention",
            offset=text.index("Друг"),
            length=4,
            user=User(id=99, is_bot=False, first_name="Друг"),
        )
    ]
    p = parse_expense(_msg(text, entities=ents))
    assert p.amount_cents == 60000
    assert p.description == "вхід"
    assert [u.id for u in p.text_mention_users] == [99]
    assert p.exclude_self


def test_expense_without_amount_raises():
    with pytest.raises(ParseError):
        parse_expense(_msg("просто балачка"))

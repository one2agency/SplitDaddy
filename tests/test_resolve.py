"""Тести визначення бенефіціарів у хендлерах — серце правил поділу.

Перевіряємо _resolve_beneficiaries напряму (без Telegram), будуючи ParsedExpense:
  • без тегів        → усі учасники;
  • без тегів + -я   → усі, крім платника;
  • з тегами         → відмічені + платник;
  • з тегами + -я    → лише відмічені;
  • нерозпізнаний @  → (None, [username]).
"""

from aiogram.types import User

from bot.handlers import _resolve_beneficiaries
from bot.parsing import ParsedExpense


def _parsed(text_mentions=None, usernames=None, exclude_self=False):
    return ParsedExpense(
        amount_cents=10000,
        description="x",
        text_mention_users=text_mentions or [],
        mention_usernames=usernames or [],
        exclude_self=exclude_self,
    )


async def _party_with(db, payer_id=1, members=(1, 2, 3)):
    party = await db.create_party(-1, organizer_user_id=payer_id)
    for uid in members:
        await db.add_participant(party.id, uid, None, f"U{uid}")
    return party


async def test_no_tags_splits_among_all(db):
    party = await _party_with(db, payer_id=1, members=(1, 2, 3))
    bens, unknown = await _resolve_beneficiaries(db, party, 1, _parsed())
    assert unknown == []
    assert sorted(bens) == [1, 2, 3]


async def test_no_tags_exclude_self(db):
    party = await _party_with(db, payer_id=1, members=(1, 2, 3))
    bens, _ = await _resolve_beneficiaries(db, party, 1, _parsed(exclude_self=True))
    assert sorted(bens) == [2, 3]
    assert 1 not in bens


async def test_tags_include_author(db):
    party = await _party_with(db, payer_id=1, members=(1, 2, 3, 4))
    await db.remember_user(2, "oleh", "Олег")
    bens, unknown = await _resolve_beneficiaries(
        db, party, 1, _parsed(usernames=["@oleh"])
    )
    assert unknown == []
    # відмічений Олег (2) + автор (1)
    assert sorted(bens) == [1, 2]


async def test_tags_exclude_self(db):
    party = await _party_with(db, payer_id=1, members=(1, 2, 3))
    await db.remember_user(3, "ira", "Іра")
    bens, _ = await _resolve_beneficiaries(
        db, party, 1, _parsed(usernames=["@ira"], exclude_self=True)
    )
    assert bens == [3]  # лише відмічена, платника немає


async def test_text_mention_autoadds_participant(db):
    party = await _party_with(db, payer_id=1, members=(1,))
    guest = User(id=77, is_bot=False, first_name="Гість")
    bens, unknown = await _resolve_beneficiaries(
        db, party, 1, _parsed(text_mentions=[guest])
    )
    assert unknown == []
    assert sorted(bens) == [1, 77]
    # text_mention автоматично став учасником
    assert await db.is_participant(party.id, 77) is True


async def test_unknown_username_blocks(db):
    party = await _party_with(db, payer_id=1, members=(1,))
    bens, unknown = await _resolve_beneficiaries(
        db, party, 1, _parsed(usernames=["@ghost"])
    )
    assert bens is None
    assert unknown == ["@ghost"]


async def test_payer_not_member_still_works_with_tags(db):
    # Платник 9 не у списку, але з тегами він додається як бенефіціар.
    party = await _party_with(db, payer_id=1, members=(1, 2))
    await db.remember_user(2, "oleh", "Олег")
    bens, _ = await _resolve_beneficiaries(db, party, 9, _parsed(usernames=["@oleh"]))
    assert sorted(bens) == [2, 9]

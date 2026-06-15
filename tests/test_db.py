"""Інтеграційні тести шару даних (реальний SQLite у тимчасовому файлі)."""

from bot.db import CODE_ALPHABET


async def test_create_party_assigns_valid_code(db):
    party = await db.create_party(chat_id=-100, organizer_user_id=1, title="Тест")
    assert party.status == "open"
    assert party.organizer_user_id == 1
    assert 2 <= len(party.code) <= 4
    assert all(ch in CODE_ALPHABET for ch in party.code)
    # У коді немає схожих символів.
    assert not (set("01OI") & set(party.code))


async def test_codes_are_unique(db):
    codes = set()
    for _ in range(30):
        p = await db.create_party(chat_id=-1, organizer_user_id=1)
        assert p.code not in codes
        codes.add(p.code)


async def test_get_open_party(db):
    assert await db.get_open_party(-100) is None
    p = await db.create_party(-100, organizer_user_id=1)
    got = await db.get_open_party(-100)
    assert got is not None and got.id == p.id
    await db.close_party(p.id)
    assert await db.get_open_party(-100) is None


async def test_add_participant_reports_new(db):
    p = await db.create_party(-1, organizer_user_id=1)
    assert await db.add_participant(p.id, 10, "ann", "Ann") is True   # новий
    assert await db.add_participant(p.id, 10, "ann", "Ann") is False  # вже є
    assert await db.is_participant(p.id, 10) is True
    assert await db.is_participant(p.id, 999) is False


async def test_expense_seq_increments_per_party(db):
    a = await db.create_party(-1, organizer_user_id=1)
    b = await db.create_party(-2, organizer_user_id=1)
    assert await db.add_expense(a.id, 1, 1000, "x", [1]) == 1
    assert await db.add_expense(a.id, 1, 1000, "y", [1]) == 2
    # Інша вечірка має власну нумерацію.
    assert await db.add_expense(b.id, 1, 1000, "z", [1]) == 1


async def test_expense_beneficiaries_preserve_order(db):
    p = await db.create_party(-1, organizer_user_id=1)
    seq = await db.add_expense(p.id, 1, 1000, "x", [3, 1, 2])
    exp = await db.get_expense_by_seq(p.id, seq)
    assert exp.beneficiaries == [3, 1, 2]


async def test_expense_dedup_beneficiaries(db):
    p = await db.create_party(-1, organizer_user_id=1)
    seq = await db.add_expense(p.id, 1, 1000, "x", [1, 1, 2, 2, 3])
    exp = await db.get_expense_by_seq(p.id, seq)
    assert exp.beneficiaries == [1, 2, 3]


async def test_update_expense(db):
    p = await db.create_party(-1, organizer_user_id=1)
    seq = await db.add_expense(p.id, 1, 1000, "старе", [1, 2])
    assert await db.update_expense_by_seq(p.id, seq, 600, "нове", [2, 3]) is True
    exp = await db.get_expense_by_seq(p.id, seq)
    assert exp.seq == seq
    assert exp.amount_cents == 600
    assert exp.description == "нове"
    assert exp.beneficiaries == [2, 3]


async def test_update_missing_expense_returns_false(db):
    p = await db.create_party(-1, organizer_user_id=1)
    assert await db.update_expense_by_seq(p.id, 999, 100, "x", [1]) is False


async def test_delete_expense(db):
    p = await db.create_party(-1, organizer_user_id=1)
    seq = await db.add_expense(p.id, 1, 1000, "x", [1, 2])
    assert await db.delete_expense_by_seq(p.id, seq) is True
    assert await db.get_expense_by_seq(p.id, seq) is None
    assert await db.delete_expense_by_seq(p.id, seq) is False  # повторно


async def test_remove_participant_states(db):
    p = await db.create_party(-1, organizer_user_id=1)
    await db.add_participant(p.id, 1, None, "Org")
    await db.add_participant(p.id, 2, None, "Free")   # без витрат
    await db.add_participant(p.id, 3, None, "Spender")
    await db.add_expense(p.id, 3, 1000, "x", [3])     # 3 — платник
    assert await db.remove_participant(p.id, 2) == "ok"
    assert await db.remove_participant(p.id, 2) == "absent"
    assert await db.remove_participant(p.id, 3) == "has_expenses"
    assert await db.is_participant(p.id, 3) is True


async def test_resolve_username_case_insensitive(db):
    await db.remember_user(42, "Oleh", "Олег")
    assert (await db.resolve_username("@OLEH")).tg_user_id == 42
    assert (await db.resolve_username("oleh")).tg_user_id == 42
    assert await db.resolve_username("@nobody") is None


async def test_get_stats(db):
    empty = await db.get_stats()
    assert empty == {
        "users": 0, "parties_total": 0, "parties_open": 0,
        "chats": 0, "expenses": 0, "total_cents": 0,
    }
    await db.remember_user(1, "a", "A")
    await db.remember_user(2, "b", "B")
    p1 = await db.create_party(-100, organizer_user_id=1)
    p2 = await db.create_party(-200, organizer_user_id=1)
    await db.close_party(p2.id)
    await db.add_expense(p1.id, 1, 50000, "x", [1, 2])
    await db.add_expense(p1.id, 1, 30000, "y", [1])
    s = await db.get_stats()
    assert s["users"] == 2
    assert s["parties_total"] == 2
    assert s["parties_open"] == 1
    assert s["chats"] == 2
    assert s["expenses"] == 2
    assert s["total_cents"] == 80000


async def test_remember_user_upsert(db):
    await db.remember_user(1, "old", "Old Name")
    await db.remember_user(1, "new", "New Name")
    p = await db.resolve_username("new")
    assert p.display_name == "New Name"
    assert await db.resolve_username("old") is None

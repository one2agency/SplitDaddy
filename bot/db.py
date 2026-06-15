"""Шар доступу до даних на aiosqlite.

Записи серіалізуються через asyncio.Lock, а складені вставки (витрата + частки)
виконуються в одній транзакції — щоб одночасні витрати не псували дані.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite

from .splitter import Expense

# Base32-алфавіт без схожих символів (немає 0/O та 1/I).
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

SCHEMA = """
CREATE TABLE IF NOT EXISTS parties (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    code TEXT NOT NULL UNIQUE,             -- короткий код, напр. 'BX'
    title TEXT,
    organizer_user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',   -- open | closed
    currency TEXT NOT NULL DEFAULT 'UAH',
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    party_id INTEGER NOT NULL REFERENCES parties(id),
    tg_user_id INTEGER NOT NULL,
    username TEXT,
    display_name TEXT,
    UNIQUE(party_id, tg_user_id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,                -- глобальний внутрішній ID
    party_id INTEGER NOT NULL REFERENCES parties(id),
    seq INTEGER NOT NULL,                  -- номер у межах вечірки (для code-n)
    payer_user_id INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(party_id, seq)
);

CREATE TABLE IF NOT EXISTS expense_shares (
    expense_id INTEGER NOT NULL REFERENCES expenses(id),
    beneficiary_user_id INTEGER NOT NULL,
    PRIMARY KEY (expense_id, beneficiary_user_id)
);

-- Глобальний довідник користувачів: дозволяє резолвити @username -> user_id
-- навіть поза межами конкретної сесії (кожен пише боту хоч раз).
CREATE TABLE IF NOT EXISTS known_users (
    tg_user_id INTEGER PRIMARY KEY,
    username TEXT,
    display_name TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_parties_chat ON parties(chat_id, status);
CREATE INDEX IF NOT EXISTS idx_expenses_party ON expenses(party_id);
CREATE INDEX IF NOT EXISTS idx_known_username ON known_users(username);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Party:
    id: int
    chat_id: int
    code: str
    title: str | None
    organizer_user_id: int
    status: str
    currency: str


@dataclass(frozen=True)
class Participant:
    tg_user_id: int
    username: str | None
    display_name: str | None


@dataclass(frozen=True)
class ExpenseRow:
    id: int
    seq: int
    payer_user_id: int
    amount_cents: int
    description: str | None
    created_at: str
    beneficiaries: list[int]


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database не ініціалізовано (виклич connect())")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---- known_users ------------------------------------------------------

    async def remember_user(
        self, tg_user_id: int, username: str | None, display_name: str | None
    ) -> None:
        async with self._write_lock:
            await self.conn.execute(
                """
                INSERT INTO known_users (tg_user_id, username, display_name, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at
                """,
                (tg_user_id, username, display_name, _now()),
            )
            await self.conn.commit()

    async def resolve_username(self, username: str) -> Participant | None:
        """Знайти користувача за @username (без урахування регістру)."""
        uname = username.lstrip("@").lower()
        async with self.conn.execute(
            "SELECT tg_user_id, username, display_name FROM known_users "
            "WHERE lower(username) = ?",
            (uname,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return Participant(row["tg_user_id"], row["username"], row["display_name"])

    # ---- parties ----------------------------------------------------------

    async def _generate_code(self) -> str:
        """Унікальний глобально код 2–4 символи (розширюється при колізіях)."""
        for length in (2, 2, 3, 3, 4, 4, 4):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))
            async with self.conn.execute(
                "SELECT 1 FROM parties WHERE code = ?", (code,)
            ) as cur:
                if await cur.fetchone() is None:
                    return code
        raise RuntimeError("Не вдалося згенерувати унікальний код вечірки")

    async def get_open_party(self, chat_id: int) -> Party | None:
        async with self.conn.execute(
            "SELECT * FROM parties WHERE chat_id = ? AND status = 'open' "
            "ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ) as cur:
            row = await cur.fetchone()
        return _party_from_row(row)

    async def create_party(
        self, chat_id: int, organizer_user_id: int, title: str | None = None,
        currency: str = "UAH",
    ) -> Party:
        async with self._write_lock:
            code = await self._generate_code()
            cur = await self.conn.execute(
                "INSERT INTO parties "
                "(chat_id, code, title, organizer_user_id, status, currency, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?, ?)",
                (chat_id, code, title, organizer_user_id, currency, _now()),
            )
            await self.conn.commit()
            party_id = cur.lastrowid
        return Party(
            party_id, chat_id, code, title, organizer_user_id, "open", currency
        )

    async def close_party(self, party_id: int) -> None:
        async with self._write_lock:
            await self.conn.execute(
                "UPDATE parties SET status = 'closed', closed_at = ? WHERE id = ?",
                (_now(), party_id),
            )
            await self.conn.commit()

    # ---- participants -----------------------------------------------------

    async def add_participant(
        self,
        party_id: int,
        tg_user_id: int,
        username: str | None,
        display_name: str | None,
    ) -> bool:
        """Додати/оновити учасника. Повертає True, якщо це новий учасник."""
        async with self._write_lock:
            async with self.conn.execute(
                "SELECT 1 FROM participants WHERE party_id = ? AND tg_user_id = ?",
                (party_id, tg_user_id),
            ) as cur:
                existed = await cur.fetchone() is not None
            await self.conn.execute(
                """
                INSERT INTO participants (party_id, tg_user_id, username, display_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(party_id, tg_user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name
                """,
                (party_id, tg_user_id, username, display_name),
            )
            await self.conn.commit()
            return not existed

    async def remove_participant(self, party_id: int, tg_user_id: int) -> str:
        """Прибрати учасника. Повертає 'ok' | 'absent' | 'has_expenses'."""
        async with self._write_lock:
            async with self.conn.execute(
                "SELECT 1 FROM participants WHERE party_id = ? AND tg_user_id = ?",
                (party_id, tg_user_id),
            ) as cur:
                if await cur.fetchone() is None:
                    return "absent"
            # Не прибираємо, якщо людина платник або бенефіціар якоїсь витрати.
            async with self.conn.execute(
                "SELECT 1 FROM expenses WHERE party_id = ? AND payer_user_id = ? "
                "UNION SELECT 1 FROM expense_shares s "
                "JOIN expenses e ON e.id = s.expense_id "
                "WHERE e.party_id = ? AND s.beneficiary_user_id = ? LIMIT 1",
                (party_id, tg_user_id, party_id, tg_user_id),
            ) as cur:
                if await cur.fetchone() is not None:
                    return "has_expenses"
            await self.conn.execute(
                "DELETE FROM participants WHERE party_id = ? AND tg_user_id = ?",
                (party_id, tg_user_id),
            )
            await self.conn.commit()
            return "ok"

    async def list_participants(self, party_id: int) -> list[Participant]:
        async with self.conn.execute(
            "SELECT tg_user_id, username, display_name FROM participants "
            "WHERE party_id = ? ORDER BY id",
            (party_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Participant(r["tg_user_id"], r["username"], r["display_name"]) for r in rows
        ]

    async def is_participant(self, party_id: int, tg_user_id: int) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM participants WHERE party_id = ? AND tg_user_id = ?",
            (party_id, tg_user_id),
        ) as cur:
            return await cur.fetchone() is not None

    # ---- expenses ---------------------------------------------------------

    async def add_expense(
        self,
        party_id: int,
        payer_user_id: int,
        amount_cents: int,
        description: str | None,
        beneficiaries: list[int],
    ) -> int:
        """Вставити витрату + частки в одній транзакції. Повертає seq (code-n)."""
        async with self._write_lock:
            try:
                await self.conn.execute("BEGIN")
                async with self.conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM expenses "
                    "WHERE party_id = ?",
                    (party_id,),
                ) as cur:
                    seq = (await cur.fetchone())["next"]
                cur = await self.conn.execute(
                    "INSERT INTO expenses "
                    "(party_id, seq, payer_user_id, amount_cents, description, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (party_id, seq, payer_user_id, amount_cents, description, _now()),
                )
                expense_id = cur.lastrowid
                for uid in dict.fromkeys(beneficiaries):  # унікалізація зі збереженням порядку
                    await self.conn.execute(
                        "INSERT INTO expense_shares (expense_id, beneficiary_user_id) "
                        "VALUES (?, ?)",
                        (expense_id, uid),
                    )
                await self.conn.commit()
                return seq
            except Exception:
                await self.conn.rollback()
                raise

    async def _attach_beneficiaries(self, row) -> ExpenseRow:
        async with self.conn.execute(
            "SELECT beneficiary_user_id FROM expense_shares "
            "WHERE expense_id = ? ORDER BY rowid",
            (row["id"],),
        ) as bcur:
            bens = [b["beneficiary_user_id"] for b in await bcur.fetchall()]
        return ExpenseRow(
            id=row["id"],
            seq=row["seq"],
            payer_user_id=row["payer_user_id"],
            amount_cents=row["amount_cents"],
            description=row["description"],
            created_at=row["created_at"],
            beneficiaries=bens,
        )

    async def list_expenses(self, party_id: int) -> list[ExpenseRow]:
        async with self.conn.execute(
            "SELECT * FROM expenses WHERE party_id = ? ORDER BY seq",
            (party_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [await self._attach_beneficiaries(r) for r in rows]

    async def get_expense_by_seq(self, party_id: int, seq: int) -> ExpenseRow | None:
        async with self.conn.execute(
            "SELECT * FROM expenses WHERE party_id = ? AND seq = ?",
            (party_id, seq),
        ) as cur:
            r = await cur.fetchone()
        if r is None:
            return None
        return await self._attach_beneficiaries(r)

    async def update_expense_by_seq(
        self,
        party_id: int,
        seq: int,
        amount_cents: int,
        description: str | None,
        beneficiaries: list[int],
    ) -> bool:
        """Оновити суму/опис/бенефіціарів витрати (seq лишається). В одній транзакції."""
        async with self._write_lock:
            try:
                await self.conn.execute("BEGIN")
                async with self.conn.execute(
                    "SELECT id FROM expenses WHERE party_id = ? AND seq = ?",
                    (party_id, seq),
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    await self.conn.rollback()
                    return False
                expense_id = row["id"]
                await self.conn.execute(
                    "UPDATE expenses SET amount_cents = ?, description = ? WHERE id = ?",
                    (amount_cents, description, expense_id),
                )
                await self.conn.execute(
                    "DELETE FROM expense_shares WHERE expense_id = ?", (expense_id,)
                )
                for uid in dict.fromkeys(beneficiaries):
                    await self.conn.execute(
                        "INSERT INTO expense_shares (expense_id, beneficiary_user_id) "
                        "VALUES (?, ?)",
                        (expense_id, uid),
                    )
                await self.conn.commit()
                return True
            except Exception:
                await self.conn.rollback()
                raise

    async def delete_expense_by_seq(self, party_id: int, seq: int) -> bool:
        async with self._write_lock:
            try:
                await self.conn.execute("BEGIN")
                async with self.conn.execute(
                    "SELECT id FROM expenses WHERE party_id = ? AND seq = ?",
                    (party_id, seq),
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    await self.conn.rollback()
                    return False
                expense_id = row["id"]
                await self.conn.execute(
                    "DELETE FROM expense_shares WHERE expense_id = ?", (expense_id,)
                )
                await self.conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
                await self.conn.commit()
                return True
            except Exception:
                await self.conn.rollback()
                raise

    async def expenses_for_split(self, party_id: int) -> list[Expense]:
        rows = await self.list_expenses(party_id)
        return [
            Expense(r.payer_user_id, r.amount_cents, r.beneficiaries) for r in rows
        ]


def _party_from_row(row) -> Party | None:
    if row is None:
        return None
    return Party(
        id=row["id"],
        chat_id=row["chat_id"],
        code=row["code"],
        title=row["title"],
        organizer_user_id=row["organizer_user_id"],
        status=row["status"],
        currency=row["currency"],
    )

"""Чиста бізнес-логіка поділу витрат: жодних залежностей від Telegram чи БД.

Усі суми — в копійках (int), щоб уникнути похибок з плаваючою комою.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Expense:
    """Одна витрата для підрахунку.

    beneficiaries — впорядкований список user_id. Порядок важливий: залишок
    від ділення (зайві копійки) розподіляється першим бенефіціарам.
    """

    payer_user_id: int
    amount_cents: int
    beneficiaries: list[int]


@dataclass(frozen=True)
class Transfer:
    debtor_user_id: int
    creditor_user_id: int
    amount_cents: int


def split_amount(amount_cents: int, n: int) -> list[int]:
    """Поділити суму на n рівних часток так, щоб їхня сума точно = amount_cents.

    Залишок (по одній копійці) додається першим часткам.
    Приклад: split_amount(1000, 3) -> [334, 333, 333].
    """
    if n <= 0:
        raise ValueError("Кількість бенефіціарів має бути > 0")
    base, remainder = divmod(amount_cents, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def compute_balances(expenses: list[Expense]) -> dict[int, int]:
    """Порахувати чистий баланс кожного учасника: paid - owed (у копійках).

    net > 0 — кредитор (йому винні), net < 0 — боржник (він винен).
    Сума всіх балансів завжди дорівнює 0.
    """
    balances: dict[int, int] = {}

    for exp in expenses:
        if not exp.beneficiaries:
            continue
        # Платник заплатив повну суму.
        balances[exp.payer_user_id] = (
            balances.get(exp.payer_user_id, 0) + exp.amount_cents
        )
        # Кожен бенефіціар винен свою частку.
        shares = split_amount(exp.amount_cents, len(exp.beneficiaries))
        for user_id, share in zip(exp.beneficiaries, shares):
            balances[user_id] = balances.get(user_id, 0) - share

    return balances


def minimize_transfers(balances: dict[int, int]) -> list[Transfer]:
    """Жадібна мінімізація переказів: найбільший боржник -> найбільший кредитор.

    На кожному кроці гаситься максимально можлива сума, тож утворюється
    щонайбільше (k-1) переказів для k ненульових балансів.
    """
    creditors = sorted(
        ((uid, bal) for uid, bal in balances.items() if bal > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    debtors = sorted(
        ((uid, -bal) for uid, bal in balances.items() if bal < 0),
        key=lambda x: x[1],
        reverse=True,
    )

    transfers: list[Transfer] = []
    i = j = 0
    cred = [list(c) for c in creditors]  # [uid, amount_owed_to_them]
    debt = [list(d) for d in debtors]    # [uid, amount_they_owe]

    while i < len(debt) and j < len(cred):
        debtor_id, owe = debt[i]
        creditor_id, due = cred[j]
        pay = min(owe, due)

        if pay > 0:
            transfers.append(Transfer(debtor_id, creditor_id, pay))

        debt[i][1] -= pay
        cred[j][1] -= pay

        if debt[i][1] == 0:
            i += 1
        if cred[j][1] == 0:
            j += 1

    return transfers

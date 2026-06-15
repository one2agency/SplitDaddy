"""Тести чистої логіки поділу — без Telegram і БД."""

from bot.splitter import (
    Expense,
    compute_balances,
    minimize_transfers,
    split_amount,
)


def test_split_amount_even():
    assert split_amount(90000, 3) == [30000, 30000, 30000]


def test_split_amount_remainder_goes_to_first():
    # 1000 копійок на 3 → 334, 333, 333 (зайва копійка першому).
    assert split_amount(1000, 3) == [334, 333, 333]
    assert sum(split_amount(1000, 3)) == 1000


def test_split_amount_one_beneficiary():
    assert split_amount(12345, 1) == [12345]


def _spec_v2_expenses():
    # Приклад зі специфікації (вечірка #BX), 1=Я, 2=Олег, 3=Іра, 4=Макс.
    return [
        Expense(1, 120000, [1, 2, 3, 4]),  # #BX-1 коктейлі на всіх
        Expense(2, 60000, [3]),             # #BX-2 таксі @ira -я (Олег виключив себе)
        Expense(3, 40000, [1, 2, 3, 4]),    # #BX-3 вхід на всіх
    ]


def test_balances_sum_to_zero():
    assert sum(compute_balances(_spec_v2_expenses()).values()) == 0


def test_spec_example_balances():
    balances = compute_balances(_spec_v2_expenses())
    assert balances == {1: 80000, 2: 20000, 3: -60000, 4: -40000}


def test_spec_example_minimal_transfers():
    transfers = minimize_transfers(compute_balances(_spec_v2_expenses()))
    # Очікувано: Іра→Я 600, Макс→Я 200, Макс→Олег 200 — 3 перекази.
    assert len(transfers) == 3
    triples = {(t.debtor_user_id, t.creditor_user_id, t.amount_cents) for t in transfers}
    assert triples == {(3, 1, 60000), (4, 1, 20000), (4, 2, 20000)}


def test_payer_not_beneficiary():
    # Платник 1 заплатив 600 лише за двох друзів (2 і 3), сам не їхав.
    expenses = [Expense(1, 60000, [2, 3])]
    balances = compute_balances(expenses)
    assert balances == {1: 60000, 2: -30000, 3: -30000}


def test_minimize_when_all_settled():
    assert minimize_transfers({1: 0, 2: 0}) == []


def test_minimize_conserves_total():
    expenses = [
        Expense(1, 100000, [1, 2, 3]),
        Expense(2, 50000, [1, 2]),
        Expense(3, 33333, [1, 2, 3, 4]),
    ]
    balances = compute_balances(expenses)
    transfers = minimize_transfers(balances)
    # Сума переказів кожному кредитору = його баланс.
    for uid, bal in balances.items():
        if bal > 0:
            received = sum(t.amount_cents for t in transfers if t.creditor_user_id == uid)
            assert received == bal

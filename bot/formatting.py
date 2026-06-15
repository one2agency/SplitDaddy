"""Рендеринг повідомлень бота (українською). Гроші — з копійок у гривні."""

from __future__ import annotations

import html

from .db import ExpenseRow, Participant, Party
from .splitter import Transfer

CURRENCY_SIGN = {"UAH": "₴", "USD": "$", "EUR": "€"}


def money(cents: int, currency: str = "UAH") -> str:
    """120050 -> '1200.50 ₴', 30000 -> '300 ₴'."""
    sign = CURRENCY_SIGN.get(currency, currency)
    whole, frac = divmod(abs(cents), 100)
    body = f"{whole}" if frac == 0 else f"{whole}.{frac:02d}"
    prefix = "-" if cents < 0 else ""
    return f"{prefix}{body} {sign}"


def display_name(p: Participant) -> str:
    return p.display_name or (f"@{p.username}" if p.username else None) or str(p.tg_user_id)


def name_of(uid: int, by: dict[int, Participant]) -> str:
    p = by.get(uid)
    return display_name(p) if p else str(uid)


def party_title(party: Party) -> str:
    return party.title or f"Вечірка #{party.code}"


def render_welcome() -> str:
    return (
        "🍹 <b>Привіт! Я рахую, хто кому винен після гулянки.</b>\n\n"
        "Жодних слешів і перемикання розкладки — лише кнопки внизу й текст витрат.\n\n"
        "Тисни <b>🎉 Нова вечірка</b>, щоб почати. Потім просто пиши витрати:\n"
        "<code>1200 піца</code> — на всіх\n"
        "<code>350 коктейлі @ira @oleh</code> — на відмічених + тебе\n"
        "<code>800 таксі @ira -я</code> — ти заплатив, але не їхав\n\n"
        "<b>❓ Допомога</b> — повний гайд."
    )


def render_help() -> str:
    return (
        "🆘 <b>Як цим користуватись (це простіше, ніж ділити рахунок у голові о 2:00)</b>\n\n"
        "<b>Кнопки внизу:</b>\n"
        "🎉 <b>Нова вечірка</b> — почати. Хто натиснув — той організатор.\n"
        "➕ <b>Додати учасників</b> — обрати людей зі списку чату.\n"
        "👥 <b>Учасники</b> — хто в ділі + як додати інших.\n"
        "📊 <b>Підсумок</b> — хто кому винен (будь-коли).\n"
        "✅ <b>Завершити</b> — фінальний розрахунок (лише організатор 👑).\n\n"
        "<b>Додати витрату</b> — просто напиши повідомленням:\n"
        "<code>&lt;сума&gt; &lt;опис&gt; [@хто] [-я]</code>\n"
        "• <code>1200 піца</code> — поділ на <b>всіх</b> учасників.\n"
        "• <code>350 коктейлі @ira @oleh</code> — на відмічених <b>+ тебе</b>.\n"
        "• <code>800 таксі @ira -я</code> — <code>-я</code> виключає тебе («я не їхав»).\n"
        "Сума: <code>800</code>, <code>800.50</code> або <code>800,50</code>.\n\n"
        "<b>Учасники:</b> автор витрати додається сам; будь-хто з учасників може "
        "додати інших — <code>+ @user</code>, прибрати — <code>- @user</code>.\n\n"
        "<b>Виправити витрату:</b> кнопка <b>✏️ Редагувати</b> під витратою, або "
        "просто <b>відповідь (reply)</b> на повідомлення витрати новим текстом "
        "(<code>800 таксі @ira -я</code>). Як варіант — видалити й додати заново.\n"
        "<b>Видалити витрату:</b> кнопка <b>🗑 Видалити витрату</b> під нею, або "
        "текст <code>видалити BX-3</code>. Можна автору витрати чи адміну.\n\n"
        "Балачки, меми й фото я ввічливо ігнорую. 😌"
    )


def render_expense_short(exp: ExpenseRow, by: dict[int, Participant], party: Party) -> str:
    bens = ", ".join(name_of(b, by) for b in exp.beneficiaries)
    desc = html.escape(exp.description or "—")
    return (
        f"<b>#{party.code}-{exp.seq}</b> {money(exp.amount_cents, party.currency)} — {desc}\n"
        f"   платник: {html.escape(name_of(exp.payer_user_id, by))} | "
        f"за: {html.escape(bens)} ({len(exp.beneficiaries)})"
    )


def render_expenses(
    expenses: list[ExpenseRow], by: dict[int, Participant], party: Party
) -> str:
    if not expenses:
        return f"У вечірці #{party.code} ще немає витрат. Напиши, напр.: <code>1200 піца</code>"
    lines = [f"<b>🧾 Витрати — {html.escape(party_title(party))}</b>"]
    total = sum(e.amount_cents for e in expenses)
    for exp in expenses:
        lines.append(render_expense_short(exp, by, party))
    lines.append(f"\n<b>Разом:</b> {money(total, party.currency)}")
    return "\n".join(lines)


def render_summary(
    transfers: list[Transfer],
    by: dict[int, Participant],
    party: Party,
    *,
    final: bool = False,
) -> str:
    header = "🏁 <b>Фінальний підсумок</b>" if final else "💰 <b>Підсумок вечірки</b>"
    lines = [f"{header} #{party.code}"]
    if not transfers:
        lines.append("\nВсі в розрахунку — ніхто нікому не винен 🎉")
        return "\n".join(lines)
    lines.append("")
    for t in transfers:
        lines.append(
            f"{html.escape(name_of(t.debtor_user_id, by))} → "
            f"{html.escape(name_of(t.creditor_user_id, by))}: "
            f"<b>{money(t.amount_cents, party.currency)}</b>"
        )
    lines.append(f"\n<i>(переказів: {len(transfers)})</i>")
    return "\n".join(lines)


def render_stats(s: dict, currency: str = "UAH") -> str:
    closed = s["parties_total"] - s["parties_open"]
    return (
        "📈 <b>Статистика SplitDaddy</b>\n\n"
        f"👤 Користувачів: <b>{s['users']}</b>\n"
        f"🎉 Вечірок: <b>{s['parties_total']}</b> "
        f"(відкритих {s['parties_open']}, закритих {closed})\n"
        f"💬 Чатів із ботом: <b>{s['chats']}</b>\n"
        f"🧾 Витрат: <b>{s['expenses']}</b>\n"
        f"💰 Сумарно проведено: <b>{money(s['total_cents'], currency)}</b>"
    )


def render_members(participants: list[Participant], party: Party) -> str:
    title = html.escape(party_title(party))
    if not participants:
        return (
            f"<b>👥 {title}</b>\nПоки нікого. Натисни «🙋 Я в ділі» під вітанням "
            "або додай тегами: <code>+ @user</code>.\nАвтор першої витрати додасться сам."
        )
    lines = [f"<b>👥 Учасники — {title}</b>"]
    for i, p in enumerate(participants, 1):
        organizer = " 👑" if p.tg_user_id == party.organizer_user_id else ""
        uname = f" (@{p.username})" if p.username else ""
        lines.append(f"{i}. {html.escape(display_name(p))}{html.escape(uname)}{organizer}")
    lines.append(
        "\nДодати: кнопка <b>➕ Додати учасників</b> або <code>+ @user</code>. "
        "Прибрати: <code>- @user</code>. Може будь-хто з учасників, або «🙋 Я в ділі»."
    )
    return "\n".join(lines)

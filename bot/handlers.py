"""Обробники aiogram: кнопки + текстовий ввід, без слеш-команд."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    User,
)

from .db import Database, Participant, Party
from .formatting import (
    money,
    name_of,
    party_title,
    render_expenses,
    render_help,
    render_members,
    render_summary,
    render_welcome,
)
from .keyboards import (
    BTN_ADD,
    BTN_FINISH,
    BTN_HELP,
    BTN_MEMBERS,
    BTN_NEW,
    BTN_SUMMARY,
    expense_actions_keyboard,
    join_keyboard,
    main_keyboard,
)
from .parsing import (
    ParseError,
    looks_like_expense,
    parse_delete_text,
    parse_expense,
    parse_participant_op,
)
from .splitter import compute_balances, minimize_transfers

logger = logging.getLogger("splitdaddy.handlers")
router = Router()


# --------------------------------------------------------------------------
# Допоміжні
# --------------------------------------------------------------------------

def _udisplay(user: User) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


async def _index(db: Database, party_id: int) -> dict[int, Participant]:
    return {p.tg_user_id: p for p in await db.list_participants(party_id)}


async def _register(db: Database, party_id: int, user: User) -> bool:
    """Запам'ятати глобально + додати в сесію. True, якщо новий учасник."""
    await db.remember_user(user.id, user.username, _udisplay(user))
    return await db.add_participant(party_id, user.id, user.username, _udisplay(user))


async def _is_admin(message_or_chat, user_id: int) -> bool:
    chat = getattr(message_or_chat, "chat", message_or_chat)
    if chat.type == "private":
        return True
    try:
        member = await chat.get_member(user_id)
    except Exception:  # noqa: BLE001
        return False
    return member.status in ("creator", "administrator")


async def _build_summary(db: Database, party: Party, *, final: bool) -> str:
    expenses = await db.expenses_for_split(party.id)
    transfers = minimize_transfers(compute_balances(expenses))
    by = await _index(db, party.id)
    return render_summary(transfers, by, party, final=final)


# --------------------------------------------------------------------------
# Вхід у групу / приватний старт — показати клавіатуру
# --------------------------------------------------------------------------

@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    new = event.new_chat_member.status
    old = event.old_chat_member.status
    if new in ("member", "administrator") and old in ("left", "kicked"):
        await event.bot.send_message(
            event.chat.id, render_welcome(), reply_markup=main_keyboard()
        )


@router.message(F.text.startswith("/start"))
async def on_start(message: Message) -> None:
    await message.answer(render_welcome(), reply_markup=main_keyboard())


# --------------------------------------------------------------------------
# Кнопки
# --------------------------------------------------------------------------

@router.message(F.text == BTN_HELP)
async def on_help(message: Message) -> None:
    await message.answer(render_help(), reply_markup=main_keyboard())


@router.message(F.text == BTN_NEW)
async def on_new_party(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    existing = await db.get_open_party(message.chat.id)
    if existing is not None:
        await message.answer(
            f"⚠️ Уже є відкрита вечірка <b>#{existing.code}</b>. "
            "Спершу заверши її кнопкою <b>✅ Завершити</b>, тоді почнемо нову."
        )
        return

    party = await db.create_party(message.chat.id, message.from_user.id)
    await _register(db, party.id, message.from_user)
    logger.info("Created party #%s in chat %s by %s",
                party.code, message.chat.id, message.from_user.id)
    # Перше повідомлення оновлює нижню клавіатуру (зокрема «➕ Додати учасників»).
    await message.answer(
        f"🎉 Вечірка <b>#{party.code}</b> почалась! Організатор: "
        f"{_udisplay(message.from_user)} 👑\n\n"
        "<b>Додай учасників</b> одним зі способів:\n"
        "• кнопка <b>➕ Додати учасників</b> внизу — обрати людей зі списку;\n"
        "• теги: <code>+ @user1 @user2</code>;\n"
        "• або хай кожен натисне <b>🙋 Я в ділі</b> нижче.\n\n"
        "Далі просто пишіть витрати: <code>350 коктейлі @ira</code>",
        reply_markup=main_keyboard(),
    )
    await message.answer(
        "🙋 Хто на вечірці — тисніть кнопку:",
        reply_markup=join_keyboard(party.id),
    )


@router.message(F.text == BTN_MEMBERS)
async def on_members(message: Message, db: Database) -> None:
    party = await db.get_open_party(message.chat.id)
    if party is None:
        await message.answer("Немає відкритої вечірки. Тисни «🎉 Нова вечірка».")
        return
    await message.answer(render_members(await db.list_participants(party.id), party))


@router.message(F.text == BTN_ADD)
async def on_add_hint(message: Message, db: Database) -> None:
    party = await db.get_open_party(message.chat.id)
    if party is None:
        await message.answer("Спершу почни вечірку — «🎉 Нова вечірка».")
        return
    await message.answer(
        "<b>Як додати учасників:</b>\n"
        "• Напиши <code>+ </code> і відміть людей: <code>+ @user1 @user2</code>.\n"
        "• Без username? Постав <code>+ </code>, почни вводити ім'я і обери людину "
        "зі списку-автодоповнення — Telegram підставить її як згадку з ID.\n"
        "• Або хай кожен сам натисне <b>🙋 Я в ділі</b> під вітанням.\n"
        "• Автор будь-якої витрати додається автоматично."
    )


@router.message(F.text == BTN_SUMMARY)
async def on_summary(message: Message, db: Database) -> None:
    party = await db.get_open_party(message.chat.id)
    if party is None:
        await message.answer("Немає відкритої вечірки. Тисни «🎉 Нова вечірка».")
        return
    # Підсумок — без кнопок видалення (їх показуємо лише під кожною витратою).
    await message.answer(await _build_summary(db, party, final=False))


@router.message(F.text == BTN_FINISH)
async def on_finish(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    party = await db.get_open_party(message.chat.id)
    if party is None:
        await message.answer("Немає відкритої вечірки для завершення.")
        return
    if message.from_user.id != party.organizer_user_id:
        await message.answer(
            "Завершити вечірку може лише організатор (хто її створив). 👑"
        )
        return
    summary = await _build_summary(db, party, final=True)
    await db.close_party(party.id)
    logger.info("Party #%s closed in chat %s", party.code, message.chat.id)
    await message.answer(
        summary + "\n\n<i>Вечірку закрито. Нова — «🎉 Нова вечірка».</i>"
    )


# --------------------------------------------------------------------------
# Inline-кнопки
# --------------------------------------------------------------------------

@router.callback_query(F.data.startswith("join:"))
async def on_join(query: CallbackQuery, db: Database) -> None:
    party_id = int(query.data.split(":")[1])
    is_new = await _register(db, party_id, query.from_user)
    await query.answer("Ти в ділі! ✅" if is_new else "Ти вже в списку 🙂")
    if is_new:
        logger.info("User %s joined party_id=%s", query.from_user.id, party_id)


@router.callback_query(F.data.startswith("del:"))
async def on_delete_cb(query: CallbackQuery, db: Database) -> None:
    _, party_id_s, seq_s = query.data.split(":")
    party_id, seq = int(party_id_s), int(seq_s)

    # Знаходимо вечірку, щоб мати code/currency для перерендеру.
    party = await db.get_open_party(query.message.chat.id)
    if party is None or party.id != party_id:
        await query.answer("Цю вечірку вже закрито.", show_alert=True)
        return

    exp = await db.get_expense_by_seq(party_id, seq)
    if exp is None:
        await query.answer("Витрату вже видалено.", show_alert=True)
        return

    is_author = exp.payer_user_id == query.from_user.id
    if not is_author and not await _is_admin(query.message, query.from_user.id):
        await query.answer("Видалити може лише автор витрати або адмін.", show_alert=True)
        return

    await db.delete_expense_by_seq(party_id, seq)
    logger.info("Deleted expense #%s-%s by %s", party.code, seq, query.from_user.id)
    await query.answer(f"🗑 #{party.code}-{seq} видалено")

    # Прибрати кнопки й позначити витрату як видалену прямо в повідомленні.
    try:
        await query.message.edit_text(
            f"{query.message.html_text}\n\n🗑 <i>Витрату видалено.</i>",
            reply_markup=None,
        )
    except Exception:  # noqa: BLE001 — текст міг не змінитись
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass


@router.callback_query(F.data.startswith("edit:"))
async def on_edit_cb(query: CallbackQuery) -> None:
    _, _party_id_s, seq_s = query.data.split(":")
    # Редагування без станів: підказуємо відповісти (reply) виправленою витратою.
    await query.answer(
        "Щоб змінити цю витрату — ВІДПОВІДЬ (reply) на це повідомлення новим "
        "текстом, напр.: 800 таксі @ira -я",
        show_alert=True,
    )


# --------------------------------------------------------------------------
# Загальний текстовий роутер: видалити / +-учасник / витрата / ігнор
# --------------------------------------------------------------------------

# Витяг посилання на витрату (#CODE-N) з повідомлення бота, на яке відповіли.
_EXPENSE_REF_RE = re.compile(r"#([A-Z2-9]{2,4})-(\d+)")


def _expense_ref_from_reply(message: Message) -> tuple[str, int] | None:
    r = message.reply_to_message
    if r is None or r.from_user is None or not r.from_user.is_bot:
        return None
    m = _EXPENSE_REF_RE.search(r.text or r.caption or "")
    if m is None:
        return None
    return m.group(1), int(m.group(2))

@router.message(F.text)
async def on_text(message: Message, db: Database) -> None:
    text = message.text or ""
    party = await db.get_open_party(message.chat.id)

    # 1) Видалення: «видалити BX-3»
    delete = parse_delete_text(text)
    if delete is not None:
        if party is None:
            return  # без вечірки — мовчимо (це звичайна переписка)
        await _handle_delete_text(message, db, party, delete)
        return

    # 2) Керування учасниками: «+ @user» / «- @user»
    op = parse_participant_op(message)
    if op is not None:
        if party is None:
            return
        await _handle_participant_op(message, db, party, op)
        return

    # 3) Витрата: повідомлення, що починається з числа
    if looks_like_expense(text):
        if party is None:
            return  # ігноруємо числа, коли вечірки немає (не шумимо в чаті)
        ref = _expense_ref_from_reply(message)
        if ref is not None:
            # Відповідь на повідомлення витрати = редагування саме її.
            await _handle_edit(message, db, party, ref)
        else:
            await _handle_expense(message, db, party)
        return

    # 4) Решта (балачки, меми) — ігноруємо.


async def _handle_delete_text(
    message: Message, db: Database, party: Party, delete: tuple[str | None, int]
) -> None:
    code, seq = delete
    if code is not None and code != party.code:
        await message.reply(
            f"Витрата #{code}-{seq} не з поточної вечірки (#{party.code})."
        )
        return
    exp = await db.get_expense_by_seq(party.id, seq)
    if exp is None:
        await message.reply(f"Витрату #{party.code}-{seq} не знайдено.")
        return
    is_author = exp.payer_user_id == message.from_user.id
    if not is_author and not await _is_admin(message, message.from_user.id):
        await message.reply("Видалити може лише автор витрати або адмін чату.")
        return
    await db.delete_expense_by_seq(party.id, seq)
    logger.info("Deleted expense #%s-%s by %s", party.code, seq, message.from_user.id)
    await message.reply(f"🗑 #{party.code}-{seq} видалено. Дивись «📊 Підсумок».")


async def _handle_participant_op(
    message: Message, db: Database, party: Party, op
) -> None:
    user = message.from_user
    # Керувати списком може будь-який учасник вечірки.
    if not await db.is_participant(party.id, user.id):
        await message.reply(
            "Спершу приєднайся до вечірки — кнопка «🙋 Я в ділі» під вітанням "
            "(або додай будь-яку витрату)."
        )
        return

    # Резолв тегів у користувачів.
    resolved: list[Participant] = []
    unknown: list[str] = []
    for u in op.text_mention_users:
        await db.remember_user(u.id, u.username, _udisplay(u))
        resolved.append(Participant(u.id, u.username, _udisplay(u)))
    for uname in op.mention_usernames:
        found = await db.resolve_username(uname)
        if found is None:
            unknown.append(uname)
        else:
            resolved.append(found)

    done: list[str] = []
    notes: list[str] = []
    for p in resolved:
        if op.op == "+":
            await db.add_participant(party.id, p.tg_user_id, p.username, p.display_name)
            done.append(p.display_name or f"@{p.username}")
        else:
            res = await db.remove_participant(party.id, p.tg_user_id)
            label = p.display_name or f"@{p.username}"
            if res == "ok":
                done.append(label)
            elif res == "absent":
                notes.append(f"{label} — не був у списку")
            elif res == "has_expenses":
                notes.append(f"{label} — має витрати, прибрати не можна")

    verb = "Додано" if op.op == "+" else "Прибрано"
    parts = []
    if done:
        parts.append(f"✅ {verb}: {', '.join(done)}")
    if unknown:
        names = ", ".join(f"@{u.lstrip('@')}" for u in unknown)
        parts.append(
            f"❓ Поки не можу додати: {names}.\n"
            "Telegram не дає боту впізнати людину за @username, доки вона сама щось "
            "не зробить у чаті. Досить, щоб вона написала будь-що або натиснула "
            "<b>🙋 Я в ділі</b> — після цього <code>+ @user</code> спрацює."
        )
    if notes:
        parts.append("⚠️ " + "; ".join(notes))
    await message.reply("\n".join(parts) or "Нічого не змінилось.")


async def _resolve_beneficiaries(
    db: Database, party: Party, payer_id: int, parsed
) -> tuple[list[int] | None, list[str]]:
    """Визначити бенефіціарів за правилами поділу. Повертає (ids|None, unknown).

    Якщо є нерозпізнані @username — повертає (None, [usernames])."""
    tagged_ids: list[int] = []
    unknown: list[str] = []
    for u in parsed.text_mention_users:
        await db.remember_user(u.id, u.username, _udisplay(u))
        await db.add_participant(party.id, u.id, u.username, _udisplay(u))
        tagged_ids.append(u.id)
    for uname in parsed.mention_usernames:
        found = await db.resolve_username(uname)
        if found is None:
            unknown.append(uname)
            continue
        await db.add_participant(
            party.id, found.tg_user_id, found.username, found.display_name
        )
        tagged_ids.append(found.tg_user_id)

    if unknown:
        return None, unknown

    if parsed.has_tags:
        bens = list(tagged_ids)
        if not parsed.exclude_self:
            bens.append(payer_id)
    else:
        bens = [p.tg_user_id for p in await db.list_participants(party.id)]
        if parsed.exclude_self:
            bens = [b for b in bens if b != payer_id]

    return list(dict.fromkeys(bens)), []


def _unknown_reply(unknown: list[str]) -> str:
    names = ", ".join(f"@{u.lstrip('@')}" for u in unknown)
    return (
        f"⚠️ Не впізнав: {names}.\nХай ці люди напишуть у чат хоч щось "
        "(або натиснуть «🙋 Я в ділі») — тоді я запам'ятаю їхній ID."
    )


async def _handle_expense(message: Message, db: Database, party: Party) -> None:
    payer = message.from_user
    await _register(db, party.id, payer)  # автор завжди учасник

    try:
        parsed = parse_expense(message)
    except ParseError as e:
        await message.reply(f"⚠️ {e}")
        return

    beneficiaries, unknown = await _resolve_beneficiaries(db, party, payer.id, parsed)
    if unknown:
        await message.reply(_unknown_reply(unknown))
        return
    if not beneficiaries:
        await message.reply(
            "⚠️ Нема на кого ділити. Відміть когось тегами або не виключай себе через -я."
        )
        return

    seq = await db.add_expense(
        party.id, payer.id, parsed.amount_cents, parsed.description or None, beneficiaries
    )
    logger.info(
        "Party #%s: expense #%s-%s amount=%s payer=%s bens=%s",
        party.code, party.code, seq, parsed.amount_cents, payer.id, beneficiaries,
    )

    by = await _index(db, party.id)
    bens_names = ", ".join(name_of(b, by) for b in beneficiaries)
    desc = parsed.description or "витрата"
    await message.reply(
        f"✅ <b>#{party.code}-{seq}</b>: {money(parsed.amount_cents, party.currency)} "
        f"за «{desc}»\n"
        f"Платник: {_udisplay(payer)} | поділ на {len(beneficiaries)}: {bens_names}",
        reply_markup=expense_actions_keyboard(party.id, seq),
    )


async def _handle_edit(
    message: Message, db: Database, party: Party, ref: tuple[str, int]
) -> None:
    code, seq = ref
    if code != party.code:
        await message.reply(f"Витрата #{code}-{seq} не з поточної вечірки (#{party.code}).")
        return
    exp = await db.get_expense_by_seq(party.id, seq)
    if exp is None:
        await message.reply(f"Витрату #{party.code}-{seq} не знайдено (могла бути видалена).")
        return

    # Змінити може автор витрати або адмін чату.
    editor = message.from_user
    if editor.id != exp.payer_user_id and not await _is_admin(message, editor.id):
        await message.reply("Редагувати витрату може лише її автор або адмін чату.")
        return

    try:
        parsed = parse_expense(message)
    except ParseError as e:
        await message.reply(f"⚠️ {e}")
        return

    # Платник лишається оригінальним; «-я»/поділ-на-всіх рахуються від нього.
    beneficiaries, unknown = await _resolve_beneficiaries(
        db, party, exp.payer_user_id, parsed
    )
    if unknown:
        await message.reply(_unknown_reply(unknown))
        return
    if not beneficiaries:
        await message.reply(
            "⚠️ Нема на кого ділити. Відміть когось тегами або не виключай платника через -я."
        )
        return

    await db.update_expense_by_seq(
        party.id, seq, parsed.amount_cents, parsed.description or None, beneficiaries
    )
    logger.info(
        "Party #%s: edited #%s-%s amount=%s bens=%s by %s",
        party.code, party.code, seq, parsed.amount_cents, beneficiaries, editor.id,
    )

    by = await _index(db, party.id)
    bens_names = ", ".join(name_of(b, by) for b in beneficiaries)
    desc = parsed.description or "витрата"
    await message.reply(
        f"✏️ Оновлено <b>#{party.code}-{seq}</b>: "
        f"{money(parsed.amount_cents, party.currency)} за «{desc}»\n"
        f"Платник: {name_of(exp.payer_user_id, by)} | "
        f"поділ на {len(beneficiaries)}: {bens_names}\nДивись «📊 Підсумок».",
        reply_markup=expense_actions_keyboard(party.id, seq),
    )

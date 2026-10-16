"""Telegram bot for PPR OSS: staff linking, duty lookup and notifications."""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import threading
from datetime import date, timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger("ppr.telegram_bot")
_lock = threading.RLock()
_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None
_dispatcher: Dispatcher | None = None
_running_token: str | None = None
_registration: dict[int, dict] = {}


def _read_token(db=None) -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if db is None:
        try:
            from database import SessionLocal
            db = SessionLocal()
            try:
                return _read_token(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Could not read Telegram token")
            return False, ""
    try:
        from settings_service import get_setting
        enabled = bool(get_setting(db, "integrations.telegram.enabled"))
        configured = get_setting(db, "integrations.telegram.bot_token")
        if configured:
            token = configured
    except Exception:
        logger.exception("Could not load Telegram settings")
        return False, ""
    return enabled and bool(token), token


def _db():
    from database import SessionLocal
    return SessionLocal()


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _commands() -> str:
    return (
        "/help — справка\n"
        "/who — кто дежурит сегодня\n"
        "/week — мои дежурства на этой неделе\n"
        "/schedule — мои ближайшие дежурства\n"
        "/status — дежурю ли я сегодня\n"
        "/whoami — мои данные и статус привязки\n"
        "/register — зарегистрироваться или обновить данные"
    )


def _linked_user(db, chat_id: int):
    from models import User
    return db.query(User).filter(
        User.telegram_chat_id == str(chat_id),
        User.telegram_status == "approved",
        User.is_active.is_(True),
    ).first()


def _duty_rows(db, start: date, end: date, user_id: int | None = None):
    from models import DutySchedule
    from sqlalchemy.orm import joinedload
    q = db.query(DutySchedule).options(
        joinedload(DutySchedule.user), joinedload(DutySchedule.department)
    ).filter(DutySchedule.duty_date >= start, DutySchedule.duty_date <= end)
    if user_id is not None:
        q = q.filter(DutySchedule.user_id == user_id)
    return q.order_by(DutySchedule.duty_date, DutySchedule.department_id, DutySchedule.shift).all()


def _duty_line(duty) -> str:
    name = html.escape((duty.user.full_name or duty.user.username) if duty.user else "Сотрудник")
    shift = {"day": "день", "night": "ночь", "full": "сутки"}.get(duty.shift, duty.shift or "смена")
    department = html.escape(duty.department.name if duty.department else "Все подразделения")
    return f"• {duty.duty_date.strftime('%d.%m.%Y')} — {name}, {shift} ({department})"


async def _poll(token: str):
    global _loop, _dispatcher
    _loop = asyncio.get_running_loop()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    _dispatcher = dp

    async def _send(message: Message, text: str):
        await message.answer(text)

    async def _show_who(message: Message):
        db = _db()
        try:
            today = date.today()
            rows = _duty_rows(db, today, today)
            # One person may have both a global and a local assignment. Display that person once.
            seen = set()
            names = []
            for row in rows:
                if not row.user or row.user_id in seen:
                    continue
                seen.add(row.user_id)
                name = html.escape(row.user.full_name or row.user.username or "Сотрудник")
                names.append(name)
            if not names:
                await _send(message, "Сегодня дежурные не назначены.")
            else:
                await _send(message, "<b>Дежурят сегодня:</b>\n" + "\n".join(f"• {name}" for name in names))
        except Exception:
            logger.exception("Telegram /who failed")
            await _send(message, "Не удалось получить график дежурств. Попробуйте позже.")
        finally:
            db.close()

    async def _show_profile(message: Message, start_registration: bool = False):
        db = _db()
        try:
            user = _linked_user(db, message.chat.id)
            if user:
                dept = html.escape(user.department.name if user.department else "не указано")
                position = html.escape(user.position or "не указана")
                await _send(
                    message,
                    "<b>Ваши данные:</b>\n\n"
                    f"ФИО: {html.escape(user.full_name or user.username or '—')}\n"
                    f"Телефон: {html.escape(user.phone or 'не указан')}\n"
                    f"Должность: {position}\nПодразделение: {dept}\n"
                    f"Роль: {html.escape(user.role or '—')}\n\nСтатус: ✅ Активен\n\n"
                    + _commands(),
                )
                return
            pending = db.query(__import__("models").User).filter(
                __import__("models").User.telegram_chat_id == str(message.chat.id),
                __import__("models").User.telegram_status == "pending",
            ).first()
            if pending:
                await _send(
                    message,
                    "Ваша заявка ожидает одобрения администратора.\n"
                    f"Сотрудник: {html.escape(pending.full_name or pending.username or '—')}\n"
                    f"Телефон: {html.escape(pending.telegram_pending_phone or pending.phone or 'не указан')}",
                )
                return
        except Exception:
            logger.exception("Telegram profile lookup failed")
            await _send(message, "Не удалось проверить привязку. Попробуйте позже.")
            return
        finally:
            db.close()
        if start_registration:
            _registration[message.chat.id] = {"step": "name"}
            await _send(message, "📝 <b>Регистрация сотрудника</b>\n\nВведите ваше ФИО (как в веб-системе):")
        else:
            await _send(message, "Аккаунт не привязан. Используйте /register для подачи заявки.")

    @dp.message(Command("start"))
    async def start(message: Message):
        await _show_profile(message, start_registration=True)

    @dp.message(Command("register"))
    async def register(message: Message):
        db = _db()
        try:
            linked = _linked_user(db, message.chat.id)
            if linked:
                _registration[message.chat.id] = {"step": "phone", "user_id": linked.id}
                await _send(message, "📝 <b>Обновление данных</b>\n\nВведите актуальный номер телефона. После отправки заявка будет повторно направлена администратору.")
                return
            from models import User
            pending = db.query(User).filter(
                User.telegram_chat_id == str(message.chat.id),
                User.telegram_status == "pending",
            ).first()
            if pending:
                await _send(message, "Ваша заявка уже ожидает одобрения администратора. Повторно отправлять её не нужно.")
                return
        finally:
            db.close()
        _registration[message.chat.id] = {"step": "name"}
        await _send(message, "📝 <b>Регистрация сотрудника</b>\n\nВведите ваше ФИО (как в веб-системе):")

    @dp.message(Command("help"))
    async def help_command(message: Message):
        await _send(message, "<b>Команды бота ППР ОСС</b>\n" + _commands())

    @dp.message(Command("id"))
    async def show_id(message: Message):
        await _send(message, f"Chat ID: <code>{message.chat.id}</code>")

    @dp.message(Command("who"))
    async def who(message: Message):
        await _show_who(message)

    @dp.message(Command("whoami"))
    async def whoami(message: Message):
        await _show_profile(message)

    @dp.message(Command("status"))
    async def status(message: Message):
        db = _db()
        try:
            user = _linked_user(db, message.chat.id)
            if not user:
                await _send(message, "Аккаунт не привязан или заявка ещё не одобрена. Используйте /register или обратитесь к администратору.")
                return
            today = date.today()
            rows = [d for d in _duty_rows(db, today, today, user.id)]
            if rows:
                shifts = ", ".join({"day": "день", "night": "ночь", "full": "сутки"}.get(d.shift, d.shift) for d in rows)
                await _send(message, f"✅ Сегодня вы дежурите. Смена: {html.escape(shifts)}.")
            else:
                await _send(message, "❌ Сегодня вы не дежурите.")
        except Exception:
            logger.exception("Telegram /status failed")
            await _send(message, "Не удалось проверить дежурство. Попробуйте позже.")
        finally:
            db.close()

    @dp.message(Command("week"))
    async def week(message: Message):
        await _show_personal_schedule(message, days=7, week_only=True)

    @dp.message(Command("schedule"))
    async def schedule(message: Message):
        await _show_personal_schedule(message, days=30, week_only=False)

    async def _show_personal_schedule(message: Message, days: int, week_only: bool):
        db = _db()
        try:
            user = _linked_user(db, message.chat.id)
            if not user:
                await _send(message, "Аккаунт не привязан или заявка ещё не одобрена. Используйте /register или обратитесь к администратору.")
                return
            today = date.today()
            start = today - timedelta(days=today.weekday()) if week_only else today
            end = start + timedelta(days=6) if week_only else today + timedelta(days=days - 1)
            rows = _duty_rows(db, start, end, user.id)
            deduplicated = []
            seen = set()
            for row in rows:
                key = (row.duty_date, row.shift)
                if key in seen:
                    continue
                seen.add(key)
                deduplicated.append(row)
            if not deduplicated:
                await _send(message, "На этот период у вас нет назначенных дежурств.")
                return
            title = "Ваша дежурная неделя" if week_only else "Ваши ближайшие дежурства"
            await _send(message, "<b>" + title + f" ({start.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}):</b>\n" + "\n".join(_duty_line(d) for d in deduplicated))
        except Exception:
            logger.exception("Telegram personal schedule failed")
            await _send(message, "Не удалось получить график. Попробуйте позже.")
        finally:
            db.close()

    @dp.message()
    async def registration_input(message: Message):
        chat_id = message.chat.id
        state = _registration.get(chat_id)
        if not state:
            return
        text = (message.text or "").strip()
        if not text:
            await _send(message, "Отправьте текстовое сообщение или /cancel для отмены.")
            return
        if text.casefold() in {"/cancel", "отмена"}:
            _registration.pop(chat_id, None)
            await _send(message, "Регистрация отменена.")
            return
        db = _db()
        try:
            from models import User
            if state["step"] == "name":
                matches = db.query(User).filter(User.is_active.is_(True)).all()
                matched = [u for u in matches if _clean(u.full_name) == _clean(text)]
                if len(matched) != 1:
                    if not matched:
                        await _send(message, "Сотрудник с таким ФИО не найден. Проверьте написание или обратитесь к администратору.")
                    else:
                        await _send(message, "Найдено несколько сотрудников с таким ФИО. Обратитесь к администратору для привязки.")
                    return
                user = matched[0]
                if user.telegram_status == "approved" and user.telegram_chat_id and user.telegram_chat_id != str(chat_id):
                    await _send(message, "У этого сотрудника уже привязан другой Telegram. Обратитесь к администратору.")
                    return
                if user.telegram_status == "pending" and user.telegram_chat_id and user.telegram_chat_id != str(chat_id):
                    await _send(message, "Заявка этого сотрудника уже отправлена из другого Telegram.")
                    return
                state.update({"step": "phone", "user_id": user.id})
                _registration[chat_id] = state
                await _send(message, f"👤 Найден сотрудник: <b>{html.escape(user.full_name or user.username or '—')}</b>\n📱 Текущий телефон: {html.escape(user.phone or 'не указан')}\n\nВведите номер телефона (например: +77001234567):")
                return
            if state["step"] == "phone":
                phone = re.sub(r"[\s()\-]", "", text)
                if not re.fullmatch(r"\+?[0-9]{7,15}", phone):
                    await _send(message, "Некорректный номер. Введите номер в международном формате, например +77001234567.")
                    return
                user = db.query(User).filter(User.id == state["user_id"], User.is_active.is_(True)).first()
                if not user:
                    _registration.pop(chat_id, None)
                    await _send(message, "Сотрудник больше не активен. Обратитесь к администратору.")
                    return
                other = db.query(User).filter(
                    User.telegram_chat_id == str(chat_id),
                    User.id != user.id,
                    User.telegram_status.in_(["approved", "pending"]),
                ).first()
                if other:
                    await _send(message, "Этот Telegram уже привязан к другому сотруднику. Обратитесь к администратору.")
                    return
                user.telegram_chat_id = str(chat_id)
                user.telegram_pending_phone = phone
                user.telegram_status = "pending"
                db.commit()
                _registration.pop(chat_id, None)
                dept = html.escape(user.department.name if user.department else "не указано")
                pos = html.escape(user.position or "не указана")
                await _send(
                    message,
                    "✅ Заявка отправлена!\n\n"
                    f"👤 {html.escape(user.full_name or user.username or '—')}\n"
                    f"📱 {html.escape(phone)}\n💼 {pos}\n🏢 {dept}\n\n"
                    "⏳ Ожидайте одобрения администратором. После одобрения станут доступны персональные команды и уведомления.",
                )
                return
        except Exception:
            db.rollback()
            logger.exception("Telegram registration failed")
            await _send(message, "❌ Ошибка при сохранении заявки. Попробуйте позже или обратитесь к администратору.")
        finally:
            db.close()

    try:
        logger.info("Starting aiogram polling")
        await dp.start_polling(bot, close_bot_session=False, handle_signals=False)
    finally:
        await bot.session.close()
        _dispatcher = None
        _loop = None


def _thread_main(token: str):
    try:
        asyncio.run(_poll(token))
    except Exception:
        logger.exception("Telegram polling stopped")



def send_telegram_to_chat(chat_id: str | int, text: str) -> bool:
    """Send a one-off private message using the currently configured bot token."""
    enabled, token = _read_token()
    if not enabled or not token or not chat_id:
        return False

    async def _send():
        client = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            await client.send_message(chat_id=str(chat_id), text=text)
            return True
        finally:
            await client.session.close()

    try:
        return asyncio.run(_send())
    except Exception:
        logger.exception("Could not send Telegram private message")
        return False


def stop_telegram_bot():
    global _thread, _running_token
    with _lock:
        loop, dp, thread = _loop, _dispatcher, _thread
        if loop and dp and thread and thread.is_alive():
            try:
                asyncio.run_coroutine_threadsafe(dp.stop_polling(), loop).result(timeout=5)
            except Exception:
                logger.exception("Could not stop Telegram polling cleanly")
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        _thread = None
        _running_token = None


def start_telegram_bot(db=None):
    global _thread, _running_token
    enabled, token = _read_token(db)
    if not enabled or not token:
        logger.info("Telegram polling not started: integration disabled or token missing")
        stop_telegram_bot()
        return False
    with _lock:
        if _thread and _thread.is_alive() and _running_token == token:
            return True
        stop_telegram_bot()
        _running_token = token
        _thread = threading.Thread(
            target=_thread_main,
            args=(token,),
            name="ppr-telegram-aiogram",
            daemon=True,
        )
        _thread.start()
        return True


def restart_telegram_bot(db=None):
    stop_telegram_bot()
    return start_telegram_bot(db)

"""Telegram long-polling bot built with aiogram 3."""
from __future__ import annotations

import asyncio
import logging
import os
import threading

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


def _read_token(db=None) -> tuple[bool, str]:
    enabled = True
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


async def _poll(token: str):
    global _loop, _dispatcher
    _loop = asyncio.get_running_loop()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    _dispatcher = dp

    @dp.message(Command("start"))
    async def start(message: Message):
        chat_id = message.chat.id
        username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "не указан"
        await message.answer(
            "Бот уведомлений ППР ОСС активен.\n"
            f"Chat ID: <code>{chat_id}</code>\n"
            f"Пользователь: {username}\n\n"
            "Скопируйте Chat ID в веб-интерфейс: Настройки системы → Интеграции."
        )

    @dp.message(Command("id"))
    async def show_id(message: Message):
        await message.answer(f"Chat ID: <code>{message.chat.id}</code>")

    @dp.message(Command("help"))
    async def help_command(message: Message):
        await message.answer(
            "<b>Команды бота ППР ОСС</b>\n"
            "/start — подключение и показ Chat ID\n"
            "/id — повторно показать Chat ID\n"
            "/help — список команд"
        )

    try:
        logger.info("Starting aiogram polling")
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        await bot.session.close()
        _dispatcher = None
        _loop = None


def _thread_main(token: str):
    try:
        asyncio.run(_poll(token))
    except Exception:
        logger.exception("Telegram polling stopped")


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

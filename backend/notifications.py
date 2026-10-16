"""Уведомления: журнал + отправка сообщений через aiogram."""
import asyncio
import logging
from datetime import date, datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logger = logging.getLogger("ppr.notifications")


def _telegram_config(db=None):
    """Настройки из БД приоритетнее переменных окружения."""
    import os
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = True
    if db is not None:
        try:
            from settings_service import get_setting
            enabled = bool(get_setting(db, "integrations.telegram.enabled"))
            configured_token = get_setting(db, "integrations.telegram.bot_token")
            configured_chat = get_setting(db, "integrations.telegram.chat_id")
            if configured_token:
                token = configured_token
            if configured_chat:
                chat_id = configured_chat
        except Exception:
            logger.exception("failed to read Telegram settings")
            return False, "", ""
    return enabled, token, chat_id


async def _send_message_async(token: str, chat_id: str, text: str) -> bool:
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception:
        logger.exception("Telegram sendMessage failed")
        return False
    finally:
        await bot.session.close()


def _send_telegram(text: str, db=None) -> bool:
    enabled, token, chat_id = _telegram_config(db)
    if not enabled or not token or not chat_id:
        logger.info("Telegram notification skipped: integration disabled or token/chat ID missing")
        return False
    try:
        return asyncio.run(_send_message_async(token, chat_id, text))
    except Exception:
        logger.exception("Telegram notification failed")
        return False


def _log(db, kind: str, message: str, meta: dict | None = None):
    from models import NotificationLog
    import json
    row = NotificationLog(
        kind=kind,
        message=message,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    return row


def notify_message(db, kind: str, message: str, meta: dict | None = None):
    _log(db, kind, message, meta)
    return _send_telegram(f"<b>ППР ОСС</b>\n{message}", db=db)


def notify_overdue(db, count: int):
    msg = f"Просроченных задач ППР: {count} (на {date.today().isoformat()})"
    notify_message(db, "overdue", msg, {"count": count})


def notify_today_duties(db):
    from models import DutySchedule
    from sqlalchemy.orm import joinedload
    today = date.today()
    duties = (
        db.query(DutySchedule)
        .options(joinedload(DutySchedule.user))
        .filter(DutySchedule.duty_date == today)
        .all()
    )
    if not duties:
        return
    # Same employee can have a global duty and a department-specific duty on one date.
    unique = {}
    for duty in duties:
        if duty.user:
            unique.setdefault(duty.user_id, duty.user.full_name or duty.user.username)
    names = ", ".join(dict.fromkeys(unique.values()))
    if names:
        notify_message(db, "duty", f"Сегодня дежурят: {names}", {"date": today.isoformat(), "user_ids": list(unique)})

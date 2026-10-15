"""Уведомления: журнал + опционально Telegram webhook."""
import os
import json
import logging
from datetime import date, datetime
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("ppr.notifications")

# TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID — из переменных окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def _send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("telegram failed: %s", e)
        return False


def _log(db, kind: str, message: str, meta: dict | None = None):
    from models import NotificationLog
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
    _send_telegram(f"<b>ППР ОСС</b>\n{message}")


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
    names = ", ".join((d.user.full_name or d.user.username) for d in duties if d.user)
    notify_message(db, "duty", f"Сегодня дежурит: {names}", {"date": today.isoformat()})

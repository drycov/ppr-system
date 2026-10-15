"""Фоновые задачи: просрочки, автоплан, напоминания."""
from datetime import date, datetime
from calendar import monthrange
import threading
import time
import logging

logger = logging.getLogger("ppr.scheduler")

_stop = threading.Event()
_thread = None


def _run_daily_jobs():
    """Ежедневные задачи (раз в сутки по локальному времени)."""
    from database import SessionLocal
    from planning import mark_overdue, generate_plans_for_period
    from notifications import notify_overdue, notify_today_duties

    db = SessionLocal()
    try:
        n = mark_overdue(db)
        logger.info("mark_overdue: %s", n)
        if n and get_setting(db, 'notifications.overdue_enabled'):
            notify_overdue(db, n)

        # 1-е число месяца — автогенерация плана
        today = date.today()
        if today.day == 1 and get_setting(db, 'planning.auto_generate'):
            result = generate_plans_for_period(db, today.year, today.month)
            logger.info("auto generate plans: %s", result)
            from notifications import notify_message
            if get_setting(db, "notifications.auto_plan_enabled"):
                notify_message(db, "auto_plan", result.get("message", "План на месяц создан"))

        if get_setting(db, 'notifications.duty_enabled'):
            notify_today_duties(db)
    except Exception as e:
        logger.exception("daily jobs failed: %s", e)
    finally:
        db.close()


def _loop(interval_sec: int = 3600):
    """Проверка раз в час; daily-jobs не чаще раза в сутки."""
    last_daily_key = None
    while not _stop.is_set():
        try:
            key = date.today().isoformat()
            if key != last_daily_key:
                _run_daily_jobs()
                last_daily_key = key
        except Exception as e:
            logger.exception("scheduler tick: %s", e)
        _stop.wait(interval_sec)


def start_scheduler(interval_sec: int | None = None):
    global _thread
    if interval_sec is None:
        try:
            from database import SessionLocal
            from settings_service import get_setting
            db = SessionLocal()
            try:
                interval_sec = int(get_setting(db, 'scheduler.interval_seconds') or 3600)
            finally:
                db.close()
        except Exception:
            interval_sec = 3600
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval_sec,), daemon=True, name="ppr-scheduler")
    _thread.start()
    logger.info("scheduler started (interval=%ss)", interval_sec)


def stop_scheduler():
    _stop.set()

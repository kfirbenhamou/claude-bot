"""
services/scheduler.py
"""

import os
import logging
import pytz
from datetime import datetime, timedelta, date
from dateutil.rrule import rrulestr
from telegram import Bot
from dotenv import load_dotenv

from db.queries import get_all_active_events, is_occurrence_skipped
from services.reminder import send_reminder

load_dotenv()
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Jerusalem"))
LATE_DELIVERY_WINDOW = timedelta(hours=int(os.getenv("LATE_DELIVERY_HOURS", "4")))
logger = logging.getLogger(__name__)


async def check_and_send_reminders(bot: Bot):
    now = datetime.now(TZ)  # always timezone-aware
    logger.info(f"[scheduler] בודק תזכורות — {now.strftime('%H:%M')}")
    events = get_all_active_events()
    logger.info(f"[scheduler] נמצאו {len(events)} אירועים")

    for event in events:
        try:
            remind_before = timedelta(minutes=event["remind_before_minutes"])

            if event["is_recurring"]:
                occurrences = _get_upcoming_occurrences(event, now)
                for occ_dt in occurrences:
                    occ_dt = _ensure_aware(occ_dt)
                    reminder_time = occ_dt - remind_before
                    if _is_due(reminder_time, now, late_window_seconds=int(LATE_DELIVERY_WINDOW.total_seconds())):
                        date_str = occ_dt.strftime("%Y-%m-%d")
                        if is_occurrence_skipped(event["id"], date_str):
                            continue
                        logger.info(f"[scheduler] שולח תזכורת: {event['title']}")
                        await send_reminder(bot, dict(event), occ_dt)
            else:
                if not event["event_datetime"]:
                    continue
                event_dt = _ensure_aware(datetime.fromisoformat(event["event_datetime"]))
                reminder_time = event_dt - remind_before
                if _is_due(reminder_time, now, late_window_seconds=int(LATE_DELIVERY_WINDOW.total_seconds())):
                    logger.info(f"[scheduler] שולח תזכורת: {event['title']}")
                    await send_reminder(bot, dict(event), event_dt)

        except Exception as e:
            logger.error(f"[scheduler] שגיאה באירוע {event['id']} ({event['title']}): {e}")


def _ensure_aware(dt: datetime) -> datetime:
    """Guarantees a datetime has timezone info. If naive, assumes TZ."""
    if dt.tzinfo is None:
        return TZ.localize(dt)
    return dt


def _get_upcoming_occurrences(event, now: datetime) -> list:
    if not event["rrule"] or not event["rrule_start"]:
        return []

    try:
        remind_before = timedelta(minutes=event["remind_before_minutes"])
        
        # rrule_start is stored as DATE in DB (YYYY-MM-DD), convert to datetime
        rrule_start_str = event["rrule_start"]
        if isinstance(rrule_start_str, str):
            # If it's just a date string "2026-04-10", add midnight time.
            # Using 00:00 ensures occurrences earlier that day (e.g. 08:00) aren't skipped.
            if len(rrule_start_str) == 10 and rrule_start_str[4] == '-':
                rrule_start_str = rrule_start_str + " 00:00:00"
        
        dtstart = _ensure_aware(datetime.fromisoformat(rrule_start_str))
        
        # Ensure dtstart is in local timezone
        if dtstart.tzinfo != TZ:
            dtstart = dtstart.astimezone(TZ)
        
        # IMPORTANT: Don't embed DTSTART as a naive value in the RRULE text.
        # Passing an aware `dtstart` avoids mixing naive/aware datetimes inside dateutil.
        rrule_str = f"RRULE:{event['rrule']}"

        # Parse rrule with proper timezone handling
        rule = rrulestr(rrule_str, ignoretz=False, dtstart=dtstart)

        end_dt = now + timedelta(hours=24)
        if event["rrule_end"]:
            rrule_end_str = event["rrule_end"]
            if isinstance(rrule_end_str, str):
                if len(rrule_end_str) == 10 and rrule_end_str[4] == '-':
                    rrule_end_str = rrule_end_str + " 23:59:59"  # End of day
            
            rrule_end = _ensure_aware(datetime.fromisoformat(rrule_end_str))
            if rrule_end.tzinfo != TZ:
                rrule_end = rrule_end.astimezone(TZ)
            end_dt = min(end_dt, rrule_end)

        # Only search occurrences whose *reminder time* could be due:
        # reminder_time = occurrence - remind_before
        # due window is: now - LATE_DELIVERY_WINDOW <= reminder_time <= now + early_tolerance
        now_aware = _ensure_aware(now)
        early_tolerance = timedelta(seconds=60)
        start_boundary = _ensure_aware(now_aware - LATE_DELIVERY_WINDOW + remind_before)
        end_boundary = _ensure_aware(min(end_dt, now_aware + early_tolerance + remind_before))
        
        occurrences = rule.between(start_boundary, end_boundary, inc=True)

        due = []
        
        for occ in occurrences:
            # rrulestr might return naive datetimes, so ensure awareness
            if isinstance(occ, datetime):
                occ = _ensure_aware(occ)
            else:
                # If it's just a date, convert to datetime
                if isinstance(occ, date):
                    occ = datetime.combine(occ, datetime.min.time())
                    occ = _ensure_aware(occ)
            
            # Convert to local timezone if needed
            if occ.tzinfo is not None and occ.tzinfo != TZ:
                occ = occ.astimezone(TZ)
            
            # Calculate reminder time and ensure both are aware for comparison
            reminder_time = occ - remind_before
            now_comparison = _ensure_aware(now)
            
            if _is_due(
                reminder_time,
                now_comparison,
                early_tolerance_seconds=60,
                late_window_seconds=int(LATE_DELIVERY_WINDOW.total_seconds()),
            ):
                due.append(occ)
        
        return due
        
    except Exception as e:
        logger.error(f"[scheduler] שגיאה בעיבוד rrule עבור אירוע {event['id']}: {e}")
        import traceback
        logger.error(f"[scheduler] traceback: {traceback.format_exc()}")
        return []


def _is_due(
    reminder_time: datetime,
    now: datetime,
    early_tolerance_seconds: int = 60,
    late_window_seconds: int = 0,
) -> bool:
    reminder_time = _ensure_aware(reminder_time)
    now = _ensure_aware(now)

    if now < reminder_time:
        return (reminder_time - now).total_seconds() <= early_tolerance_seconds
    return (now - reminder_time).total_seconds() <= late_window_seconds
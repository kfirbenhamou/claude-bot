"""
services/gcal.py
Google Calendar integration — create, update, and delete events.

All calls are fire-and-forget; callers should wrap in try/except so a
Google Calendar failure never breaks the Telegram bot.

Setup (one-time):
  1. Run scripts/gcal_auth.py once on any machine with a browser.
  2. Set GCAL_TOKEN_PATH, GCAL_CREDENTIALS_PATH, GCAL_CALENDAR_ID in .env.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, date

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

GCAL_TOKEN_PATH = os.getenv("GCAL_TOKEN_PATH", "token.json")
GCAL_CREDENTIALS_PATH = os.getenv("GCAL_CREDENTIALS_PATH", "credentials.json")
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _load_credentials():
    """Load (and refresh if needed) OAuth2 credentials from token.json."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not os.path.exists(GCAL_TOKEN_PATH):
        raise FileNotFoundError(
            f"Google Calendar token not found at '{GCAL_TOKEN_PATH}'. "
            "Run scripts/gcal_auth.py first."
        )

    creds = Credentials.from_authorized_user_file(GCAL_TOKEN_PATH, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds)
        else:
            raise RuntimeError(
                "Google Calendar credentials are invalid and cannot be refreshed. "
                "Run scripts/gcal_auth.py again."
            )

    return creds


def _save_credentials(creds) -> None:
    with open(GCAL_TOKEN_PATH, "w") as fh:
        fh.write(creds.to_json())


def _build_service():
    from googleapiclient.discovery import build

    creds = _load_credentials()
    return build("calendar", "v3", credentials=creds)


# ── rrule conversion ───────────────────────────────────────────────────────────

def _rrule_to_gcal(rrule: str) -> str:
    """
    Convert our internal rrule string to a Google Calendar RRULE: prefixed string.

    Our format:  FREQ=WEEKLY;BYDAY=TU;BYHOUR=17;BYMINUTE=30
    GCal format: RRULE:FREQ=WEEKLY;BYDAY=TU
    (BYHOUR/BYMINUTE go into the event start time, not the RRULE itself.)
    """
    cleaned = re.sub(r";?BYHOUR=\d+", "", rrule)
    cleaned = re.sub(r";?BYMINUTE=\d+", "", cleaned)
    cleaned = cleaned.strip(";")
    return f"RRULE:{cleaned}"


# ── Event body builder ────────────────────────────────────────────────────────

def _build_gcal_body(event, persona_name: str) -> dict:
    """
    Build the Google Calendar event resource dict from a DB event row.
    Works for both single and recurring events.
    """
    title = f"{persona_name} — {event['title']}"
    description_parts = []
    if event["location"]:
        description_parts.append(f"📍 {event['location']}")
    if event["notes"]:
        description_parts.append(f"📝 {event['notes']}")
    description = "\n".join(description_parts)

    body: dict = {
        "summary": title,
        "description": description,
    }

    if event["is_recurring"] and event["rrule"]:
        rrule_str = event["rrule"]
        # Extract start time from BYHOUR/BYMINUTE in the rrule
        hour_match = re.search(r"BYHOUR=(\d+)", rrule_str)
        minute_match = re.search(r"BYMINUTE=(\d+)", rrule_str)
        hour = int(hour_match.group(1)) if hour_match else 0
        minute = int(minute_match.group(1)) if minute_match else 0

        # Use rrule_start as base date; fall back to today
        base_date_str = event["rrule_start"] or date.today().isoformat()
        base_date = date.fromisoformat(base_date_str)
        start_dt = datetime(base_date.year, base_date.month, base_date.day, hour, minute)

        end_dt = start_dt + timedelta(hours=1)

        body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": os.getenv("TIMEZONE", "Asia/Jerusalem"),
        }
        body["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": os.getenv("TIMEZONE", "Asia/Jerusalem"),
        }
        body["recurrence"] = [_rrule_to_gcal(rrule_str)]

    elif event["event_datetime"]:
        start_dt = datetime.fromisoformat(str(event["event_datetime"]))
        end_dt = start_dt + timedelta(hours=1)

        body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": os.getenv("TIMEZONE", "Asia/Jerusalem"),
        }
        body["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": os.getenv("TIMEZONE", "Asia/Jerusalem"),
        }
    else:
        # No time information — create an all-day event for today
        today = date.today().isoformat()
        body["start"] = {"date": today}
        body["end"] = {"date": today}

    return body


# ── Public API ────────────────────────────────────────────────────────────────

def create_gcal_event(event, persona_name: str) -> str | None:
    """
    Creates a Google Calendar event. Returns the gcal event ID, or None on failure.
    """
    if not os.path.exists(GCAL_TOKEN_PATH):
        return None
    try:
        service = _build_service()
        body = _build_gcal_body(event, persona_name)
        result = (
            service.events()
            .insert(calendarId=GCAL_CALENDAR_ID, body=body)
            .execute()
        )
        gcal_id = result.get("id")
        logger.info(f"[gcal] created event '{body['summary']}' → {gcal_id}")
        return gcal_id
    except Exception as exc:
        logger.warning(f"[gcal] create_gcal_event failed: {exc}")
        return None


def update_gcal_event(gcal_event_id: str, event, persona_name: str) -> None:
    """
    Updates an existing Google Calendar event. Silently skips if gcal_event_id is None.
    """
    if not gcal_event_id or not os.path.exists(GCAL_TOKEN_PATH):
        return
    try:
        service = _build_service()
        body = _build_gcal_body(event, persona_name)
        service.events().update(
            calendarId=GCAL_CALENDAR_ID,
            eventId=gcal_event_id,
            body=body,
        ).execute()
        logger.info(f"[gcal] updated event {gcal_event_id} → '{body['summary']}'")
    except Exception as exc:
        logger.warning(f"[gcal] update_gcal_event failed ({gcal_event_id}): {exc}")


def delete_gcal_event(gcal_event_id: str) -> None:
    """
    Deletes a Google Calendar event. Silently skips if gcal_event_id is None.
    """
    if not gcal_event_id or not os.path.exists(GCAL_TOKEN_PATH):
        return
    try:
        service = _build_service()
        service.events().delete(
            calendarId=GCAL_CALENDAR_ID,
            eventId=gcal_event_id,
        ).execute()
        logger.info(f"[gcal] deleted event {gcal_event_id}")
    except Exception as exc:
        logger.warning(f"[gcal] delete_gcal_event failed ({gcal_event_id}): {exc}")

"""
db/queries.py
All database access in one place.
"""

import sqlite3
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)
DB_PATH = os.getenv("DB_PATH", "family_bot.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # access columns by name
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply lightweight schema migrations for columns added after initial setup."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(events)").fetchall()
    }
    if "gcal_event_id" not in existing:
        conn.execute("ALTER TABLE events ADD COLUMN gcal_event_id TEXT")
        conn.commit()


def _ensure_agent_state_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_pending (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       TEXT NOT NULL,
            user_id       INTEGER NOT NULL,
            kind          TEXT NOT NULL,
            field         TEXT NOT NULL,
            parsed_json   TEXT NOT NULL,
            original_text TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_pending_chat_user ON agent_pending(chat_id, user_id)"
    )
    conn.commit()


# ── Personas ──────────────────────────────────────────────────────────────────

def get_all_personas():
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM personas WHERE active = 1"
        ).fetchall()


def get_persona_by_username(username: str):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM personas WHERE telegram_username = ?", (username,)
        ).fetchone()


def get_persona_by_chat_id(chat_id: str):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM personas WHERE private_chat_id = ?", (chat_id,)
        ).fetchone()


def get_persona_by_id(persona_id: int):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM personas WHERE id = ?", (persona_id,)
        ).fetchone()


def save_private_chat_id(telegram_username: str, chat_id: str):
    """Called when a persona /starts the bot privately."""
    with _conn() as conn:
        conn.execute(
            "UPDATE personas SET private_chat_id = ? WHERE telegram_username = ?",
            (chat_id, telegram_username)
        )
        conn.commit()


def update_persona_username(persona_id: int, username: str):
    """Called when adding Alma or Arbel to Telegram later."""
    with _conn() as conn:
        conn.execute(
            "UPDATE personas SET telegram_username = ? WHERE id = ?",
            (username, persona_id)
        )
        conn.commit()


def get_parents():
    """Returns personas who manage others (i.e., parents)."""
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM personas WHERE manages_for != '' AND active = 1"
        ).fetchall()


# ── Events ────────────────────────────────────────────────────────────────────

def add_event(title, persona_id, location=None, notes=None,
              event_datetime=None, rrule=None, rrule_start=None,
              rrule_end=None, remind_before_minutes=60, send_to="both"):
    """
    Add a single or recurring event.
    Single:    pass event_datetime
    Recurring: pass rrule + rrule_start (and optionally rrule_end)
    """
    is_recurring = rrule is not None
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO events
               (title, persona_id, location, notes, is_recurring,
                event_datetime, rrule, rrule_start, rrule_end,
                remind_before_minutes, send_to)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (title, persona_id, location, notes, is_recurring,
             event_datetime, rrule, rrule_start, rrule_end,
             remind_before_minutes, send_to)
        )
        conn.commit()
        return cur.lastrowid


def get_all_active_events():
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE active = 1"
        ).fetchall()


def get_event_by_id(event_id: int):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()


def find_events(persona_id: int | None = None, title_query: str | None = None):
    """
    Finds active events by optional persona_id and/or partial title match.
    Returns list[Row].
    """
    where = ["active = 1"]
    params: list = []
    if persona_id is not None:
        where.append("persona_id = ?")
        params.append(persona_id)
    if title_query:
        where.append("title LIKE ?")
        params.append(f"%{title_query}%")

    sql = "SELECT * FROM events WHERE " + " AND ".join(where) + " ORDER BY id DESC"
    with _conn() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def update_event(event_id: int, **fields) -> None:
    """
    Updates an event row with provided fields.
    Allowed keys: title, location, notes, event_datetime, rrule, rrule_start, rrule_end,
                  remind_before_minutes, send_to, active, is_recurring
    """
    allowed = {
        "title",
        "location",
        "notes",
        "event_datetime",
        "rrule",
        "rrule_start",
        "rrule_end",
        "remind_before_minutes",
        "send_to",
        "active",
        "is_recurring",
        "persona_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return

    sets = ", ".join([f"{k} = ?" for k in updates.keys()])
    params = list(updates.values()) + [event_id]
    with _conn() as conn:
        conn.execute(f"UPDATE events SET {sets} WHERE id = ?", tuple(params))
        conn.commit()


def set_agent_pending(chat_id: str, user_id: int, kind: str, field: str, parsed: dict, original_text: str | None = None) -> None:
    with _conn() as conn:
        _ensure_agent_state_tables(conn)
        conn.execute("DELETE FROM agent_pending WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.execute(
            """INSERT INTO agent_pending (chat_id, user_id, kind, field, parsed_json, original_text)
               VALUES (?,?,?,?,?,?)""",
            (chat_id, user_id, kind, field, json.dumps(parsed, ensure_ascii=False), original_text),
        )
        conn.commit()


def get_agent_pending(chat_id: str, user_id: int):
    with _conn() as conn:
        _ensure_agent_state_tables(conn)
        row = conn.execute(
            """SELECT kind, field, parsed_json, original_text
               FROM agent_pending
               WHERE chat_id = ? AND user_id = ?
               ORDER BY id DESC
               LIMIT 1""",
            (chat_id, user_id),
        ).fetchone()
        if not row:
            return None
        try:
            parsed = json.loads(row["parsed_json"])
        except Exception:
            parsed = {}
        return {
            "kind": row["kind"],
            "field": row["field"],
            "parsed": parsed,
            "original_text": row["original_text"] or "",
        }


def clear_agent_pending(chat_id: str, user_id: int) -> None:
    with _conn() as conn:
        _ensure_agent_state_tables(conn)
        conn.execute("DELETE FROM agent_pending WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()


def clear_all_agent_pending() -> int:
    """
    Clears all pending agent state (all chats/users). Returns deleted row count.
    """
    with _conn() as conn:
        _ensure_agent_state_tables(conn)
        cur = conn.execute("DELETE FROM agent_pending")
        conn.commit()
        return cur.rowcount

def get_gcal_event_id(event_id: int) -> str | None:
    """Returns the Google Calendar event ID stored for this event, or None."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT gcal_event_id FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if row:
            return row["gcal_event_id"]
        return None


def set_gcal_event_id(event_id: int, gcal_event_id: str) -> None:
    """Stores the Google Calendar event ID after a successful sync."""
    with _conn() as conn:
        conn.execute(
            "UPDATE events SET gcal_event_id = ? WHERE id = ?",
            (gcal_event_id, event_id),
        )
        conn.commit()


def delete_event(event_id: int) -> None:
    """
    Deletes an event and related data so it stops appearing immediately.
    """
    with _conn() as conn:
        conn.execute("DELETE FROM reminder_log WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM event_exceptions WHERE event_id = ?", (event_id,))
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()


def get_events_for_persona(persona_id: int):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE persona_id = ? AND active = 1",
            (persona_id,)
        ).fetchall()


# ── Exceptions ────────────────────────────────────────────────────────────────

def add_exception(event_id, original_date, action,
                  new_datetime=None, note=None, created_by=None):
    with _conn() as conn:
        conn.execute(
            """INSERT INTO event_exceptions
               (event_id, original_date, action, new_datetime, note, created_by)
               VALUES (?,?,?,?,?,?)""",
            (event_id, original_date, action, new_datetime, note, created_by)
        )
        conn.commit()


def get_exceptions_for_event(event_id: int):
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM event_exceptions WHERE event_id = ?", (event_id,)
        ).fetchall()


def is_occurrence_skipped(event_id: int, date_str: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM event_exceptions
               WHERE event_id = ? AND original_date = ? AND action = 'skip'""",
            (event_id, date_str)
        ).fetchone()
        return row is not None


# ── Reminder log ──────────────────────────────────────────────────────────────

def log_reminder(event_id, occurrence_date, channel, status: str = "sent"):
    with _conn() as conn:
        conn.execute(
            """INSERT INTO reminder_log (event_id, occurrence_date, channel, status)
               VALUES (?,?,?,?)""",
            (event_id, occurrence_date, channel, status)
        )
        conn.commit()


def was_reminder_sent(event_id, occurrence_date, channel) -> bool:
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM reminder_log
               WHERE event_id = ? AND occurrence_date = ? AND channel = ?""",
            (event_id, occurrence_date, channel)
        ).fetchone()
        return row is not None


def was_reminder_sent_recently(
    event_id,
    occurrence_date,
    channel,
    within_minutes: int = 30,
) -> bool:
    """
    Returns True if a reminder was sent in the last `within_minutes`.
    Uses SQLite time functions; `sent_at` is stored as CURRENT_TIMESTAMP.
    """
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM reminder_log
               WHERE event_id = ?
                 AND occurrence_date = ?
                 AND channel = ?
                 AND status = 'sent'
                 AND sent_at >= datetime('now', ?)""",
            (event_id, occurrence_date, channel, f"-{int(within_minutes)} minutes"),
        ).fetchone()
        return row is not None


def mark_occurrence_handled(event_id, occurrence_date, handled_by: str | None = None) -> None:
    """
    Marks an occurrence as handled so the scheduler can stop repeating reminders.
    """
    with _conn() as conn:
        conn.execute(
            """INSERT INTO reminder_log (event_id, occurrence_date, channel, status)
               VALUES (?,?,?,?)""",
            (event_id, occurrence_date, f"handled_by:{handled_by or ''}", "handled"),
        )
        conn.commit()


def is_occurrence_handled(event_id, occurrence_date) -> bool:
    with _conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM reminder_log
               WHERE event_id = ? AND occurrence_date = ? AND status = 'handled'
               LIMIT 1""",
            (event_id, occurrence_date),
        ).fetchone()
        return row is not None

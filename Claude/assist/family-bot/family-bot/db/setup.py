"""
db/setup.py
Run once: python db/setup.py
Creates all tables and seeds Kfir, Moran, Alma, Arbel.
"""

import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "family_bot.db")


def setup():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Personas ──────────────────────────────────────────────────────────────
    # telegram_username: without the @, set when they join Telegram
    # private_chat_id:   filled automatically when they /start the bot privately
    # receives_group:    should their reminders appear in the family group?
    # receives_private:  should they also get a private message?
    # manages_for:       comma-separated persona IDs this person receives
    #                    reminders on behalf of (used for Alma & Arbel)
    c.executescript("""
        CREATE TABLE IF NOT EXISTS personas (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT NOT NULL,
            role                TEXT NOT NULL,
            telegram_username   TEXT,
            private_chat_id     TEXT,
            receives_group      BOOLEAN DEFAULT TRUE,
            receives_private    BOOLEAN DEFAULT TRUE,
            manages_for         TEXT DEFAULT '',
            active              BOOLEAN DEFAULT TRUE,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Events ────────────────────────────────────────────────────────────
        -- Single event:    fill event_datetime, leave rrule* columns NULL
        -- Recurring event: fill rrule, rrule_start; leave event_datetime NULL
        CREATE TABLE IF NOT EXISTS events (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            title                   TEXT NOT NULL,
            location                TEXT,
            notes                   TEXT,
            persona_id              INTEGER NOT NULL REFERENCES personas(id),
            is_recurring            BOOLEAN DEFAULT FALSE,

            -- Single events
            event_datetime          DATETIME,

            -- Recurring events (iCal RRULE format)
            rrule                   TEXT,
            rrule_start             DATE,
            rrule_end               DATE,

            -- How many minutes before the event to send the reminder
            remind_before_minutes   INTEGER DEFAULT 60,

            -- 'group', 'private', 'both'
            send_to                 TEXT DEFAULT 'both',

            -- Google Calendar event ID (null until synced)
            gcal_event_id           TEXT,

            active                  BOOLEAN DEFAULT TRUE,
            created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Event exceptions ──────────────────────────────────────────────────
        -- Used when a family member skips or reschedules one occurrence
        -- of a recurring event, without affecting the whole series.
        CREATE TABLE IF NOT EXISTS event_exceptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        INTEGER NOT NULL REFERENCES events(id),
            original_date   DATE NOT NULL,
            action          TEXT NOT NULL CHECK(action IN ('skip','reschedule','modify')),
            new_datetime    DATETIME,
            note            TEXT,
            created_by      TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── Reminder log ──────────────────────────────────────────────────────
        -- Tracks every reminder sent so we never double-send.
        CREATE TABLE IF NOT EXISTS reminder_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        INTEGER REFERENCES events(id),
            occurrence_date DATE,
            sent_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
            channel         TEXT,
            status          TEXT DEFAULT 'sent'
        );

        -- ── Global config ─────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS config (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );
    """)

    # ── Seed personas ─────────────────────────────────────────────────────────
    # Alma (id=3) and Arbel (id=4) have no Telegram yet.
    # manages_for on Kfir and Moran means they both get notified about
    # Alma's and Arbel's events privately.
    existing = c.execute("SELECT COUNT(*) FROM personas").fetchone()[0]
    if existing == 0:
        c.executemany(
            """INSERT INTO personas
               (name, role, telegram_username, private_chat_id,
                receives_group, receives_private, manages_for)
               VALUES (?,?,?,?,?,?,?)""",
            [
                # name    role        username  chat_id  group  private  manages_for
                ("כפיר", "dad",       None,     None,    True,  True,   "3,4"),
                ("מורן", "mom",       None,     None,    True,  True,   "3,4"),
                ("עלמה", "daughter",  None,     None,    True,  False,  ""),
                ("ארבל", "son",       None,     None,    True,  False,  ""),
            ]
        )
        print("✅ Seeded 4 personas: כפיר, מורן, עלמה, ארבל")
    else:
        print("ℹ️  Personas already exist, skipping seed.")

    conn.commit()
    conn.close()
    print(f"✅ Database ready at: {DB_PATH}")
    print()
    print("Next steps:")
    print("  1. Fill in .env with your bot token and OpenAI key")
    print("  2. Add the bot to your family Telegram group")
    print("  3. Run: python main.py")
    print()
    print("After Kfir and Moran each /start the bot privately,")
    print("their private_chat_id will be saved automatically.")


if __name__ == "__main__":
    setup()

"""
add_events_example.py
Run this to populate your first events.
Edit to match your real family schedule.

Run with: python add_events_example.py
"""

from db.setup import setup
from db.queries import add_event

# Make sure DB exists
setup()

# ── Persona IDs (as seeded in setup.py) ──────────────────────────────────────
KFIR  = 1
MORAN = 2
ALMA  = 3
ARBEL = 4

# ── Recurring events ──────────────────────────────────────────────────────────

# עלמה — שחייה כל שלישי וחמישי בשעה 16:00
add_event(
    title="שחייה",
    persona_id=ALMA,
    location="בריכת ספורטק",
    rrule="FREQ=WEEKLY;BYDAY=TU,TH;BYHOUR=16;BYMINUTE=0",
    rrule_start="2025-09-01",
    rrule_end="2026-06-30",
    remind_before_minutes=60,
    send_to="both",
)

# ארבל — כדורגל כל יום שני בשעה 17:00
add_event(
    title="כדורגל",
    persona_id=ARBEL,
    location="מגרש השכונה",
    rrule="FREQ=WEEKLY;BYDAY=MO;BYHOUR=17;BYMINUTE=0",
    rrule_start="2025-09-01",
    rrule_end="2026-06-30",
    remind_before_minutes=60,
    send_to="both",
)

# כפיר — חדר כושר כל ראשון, שלישי, חמישי בשעה 7:00
add_event(
    title="חדר כושר",
    persona_id=KFIR,
    location="מכבי כושר",
    rrule="FREQ=WEEKLY;BYDAY=SU,TU,TH;BYHOUR=7;BYMINUTE=0",
    rrule_start="2025-09-01",
    remind_before_minutes=30,
    send_to="private",  # Personal — only Kfir gets this privately
)

# מורן — יוגה כל רביעי בשעה 19:00
add_event(
    title="יוגה",
    persona_id=MORAN,
    location="סטודיו שמש",
    rrule="FREQ=WEEKLY;BYDAY=WE;BYHOUR=19;BYMINUTE=0",
    rrule_start="2025-09-01",
    remind_before_minutes=45,
    send_to="private",
)

# ── Single events ─────────────────────────────────────────────────────────────

# פגישת הורים — עלמה
add_event(
    title="פגישת הורים — עלמה",
    persona_id=MORAN,
    location="בית הספר",
    event_datetime="2025-10-20 18:00:00",
    remind_before_minutes=120,
    send_to="both",
)

# רופא שיניים — ארבל
add_event(
    title="רופא שיניים — ארבל",
    persona_id=ARBEL,
    location="קליניקת הסמל",
    event_datetime="2025-10-22 10:00:00",
    remind_before_minutes=60,
    send_to="both",
)

print("✅ Events added successfully!")
print()
print("Events added:")
print("  🏊 עלמה — שחייה (כל שלישי וחמישי, 16:00)")
print("  ⚽ ארבל — כדורגל (כל שני, 17:00)")
print("  🏋️ כפיר — חדר כושר (כל ראשון/שלישי/חמישי, 07:00) [פרטי]")
print("  🧘 מורן — יוגה (כל רביעי, 19:00) [פרטי]")
print("  📚 פגישת הורים — עלמה (20/10 18:00)")
print("  🦷 רופא שיניים — ארבל (22/10 10:00)")

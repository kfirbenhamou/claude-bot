"""
handlers/add_event_wizard.py

Conversational flow for adding events via Telegram.
Triggered by: "הוסף אירוע" / "add event" / "/add"

The wizard asks step by step:
  1. For whom? (shows persona buttons)
  2. What activity?
  3. Where? (optional)
  4. Recurring or one-time?
  5a. If one-time: when? (date + time)
  5b. If recurring: which days + time, start date, end date
  6. How many minutes before to remind?
  7. Group, private, or both?
  → Confirms and saves.

Uses Telegram ConversationHandler so each user's state is tracked separately.
"""

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from datetime import datetime, date
import pytz
import re
import os
from dotenv import load_dotenv

from db.queries import get_all_personas, add_event

load_dotenv(override=True)
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Jerusalem"))

# ── Conversation states ───────────────────────────────────────────────────────
(
    ASK_PERSONA,
    ASK_TITLE,
    ASK_LOCATION,
    ASK_RECURRING,
    ASK_DATETIME,          # single event
    ASK_DAYS,              # recurring
    ASK_TIME,              # recurring
    ASK_REMIND_BEFORE,
    ASK_SEND_TO,
    CONFIRM,
) = range(10)

# Hebrew day name → rrule weekday code
DAYS_MAP = {
    "ראשון": "SU",
    "שני": "MO",
    "שלישי": "TU",
    "רביעי": "WE",
    "חמישי": "TH",
    "שישי": "FR",
    "שבת": "SA",
}

CANCEL_WORDS = {"ביטול", "cancel", "/cancel"}


# ── Entry point ───────────────────────────────────────────────────────────────

async def start_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by /add or a message containing 'הוסף אירוע'."""
    context.user_data.clear()
    personas = get_all_personas()

    if not personas:
        await update.message.reply_text("לא נמצאו פרסונות. הריצו python db/setup.py תחילה.")
        return ConversationHandler.END

    # Build keyboard with persona names
    buttons = [[p["name"] for p in personas]]
    await update.message.reply_text(
        "➕ *הוספת אירוע חדש*\n\nעבור מי האירוע?\n\n"
        "_ניתן לבחור מספר אנשים בפסיקים: עלמה, ארבל_",
        reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="Markdown",
    )
    # Store personas for later lookup
    context.user_data["personas"] = {p["name"]: p["id"] for p in personas}
    return ASK_PERSONA


# ── Step 1: Persona ───────────────────────────────────────────────────────────

async def received_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    personas = context.user_data.get("personas", {})
    
    # Parse comma-separated names for multiple personas
    names = [n.strip() for n in re.split(r"[,،]", text)]
    selected_personas = {}
    unknown = []
    
    for name in names:
        if name in personas:
            selected_personas[name] = personas[name]
        else:
            unknown.append(name)
    
    if not selected_personas:
        await update.message.reply_text(
            f"לא מכיר את {names}. נסה שוב.\n\n"
            f"ניתן לבחור מס״פ אנשים בפסיקים, למשל: עלמה, ארבל"
        )
        return ASK_PERSONA
    
    if unknown:
        await update.message.reply_text(
            f"⚠️ לא מכיר: {', '.join(unknown)}\n"
            f"נמשיכים עם: {', '.join(selected_personas.keys())}"
        )
    
    context.user_data["selected_personas"] = selected_personas
    names_str = ", ".join(selected_personas.keys())
    
    await update.message.reply_text(
        f"מצוין! אירוע עבור *{names_str}*.\n\nמה שם הפעילות?",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )
    return ASK_TITLE


# ── Step 2: Title ─────────────────────────────────────────────────────────────

async def received_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if title in CANCEL_WORDS:
        return await cancel(update, context)

    context.user_data["title"] = title

    await update.message.reply_text(
        f"📍 איפה מתקיימת הפעילות?\n_(שלחו 'דלג' אם אין מיקום)_",
        parse_mode="Markdown",
    )
    return ASK_LOCATION


# ── Step 3: Location ──────────────────────────────────────────────────────────

async def received_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    context.user_data["location"] = None if text in ("דלג", "skip", "-") else text

    await update.message.reply_text(
        "האירוע מתרחש *פעם אחת* או *חוזר על עצמו*?",
        reply_markup=ReplyKeyboardMarkup(
            [["פעם אחת", "חוזר על עצמו"]],
            one_time_keyboard=True, resize_keyboard=True
        ),
        parse_mode="Markdown",
    )
    return ASK_RECURRING


# ── Step 4: Recurring? ────────────────────────────────────────────────────────

async def received_recurring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    if "חוזר" in text or "recurring" in text.lower():
        context.user_data["is_recurring"] = True
        await update.message.reply_text(
            "באילו ימים? (ניתן לבחור מספר ימים, הפרידו בפסיקים)\n\n"
            "לדוגמה: *שני, רביעי, שישי*",
            reply_markup=ReplyKeyboardMarkup(
                [["ראשון", "שני", "שלישי", "רביעי"],
                 ["חמישי", "שישי", "שבת"]],
                one_time_keyboard=True, resize_keyboard=True
            ),
            parse_mode="Markdown",
        )
        return ASK_DAYS
    else:
        context.user_data["is_recurring"] = False
        await update.message.reply_text(
            "📅 מתי האירוע? כתבו תאריך ושעה.\n\n"
            "לדוגמה: *20/10/2025 16:00*",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
        return ASK_DATETIME


# ── Step 5a: Single event datetime ────────────────────────────────────────────

async def received_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    dt = _parse_datetime(text)
    if not dt:
        await update.message.reply_text(
            "לא הצלחתי להבין את התאריך. נסה שוב בפורמט: *20/10/2025 16:00*",
            parse_mode="Markdown",
        )
        return ASK_DATETIME

    context.user_data["event_datetime"] = dt.isoformat()
    return await ask_remind_before(update, context)


# ── Step 5b: Recurring — which days ──────────────────────────────────────────

async def received_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    # Parse comma-separated days
    parts = [d.strip() for d in re.split(r"[,،,]", text)]
    rrule_days = []
    unknown = []
    for part in parts:
        code = DAYS_MAP.get(part)
        if code:
            rrule_days.append(code)
        else:
            unknown.append(part)

    if not rrule_days:
        await update.message.reply_text(
            "לא הכרתי את הימים. נסה שוב — לדוגמה: שני, רביעי"
        )
        return ASK_DAYS

    context.user_data["rrule_days"] = rrule_days
    days_display = ", ".join(parts[:len(rrule_days)])

    await update.message.reply_text(
        f"ימים: *{days_display}*\n\nבאיזו שעה? (לדוגמה: *16:00*)",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )
    return ASK_TIME


# ── Step 5c: Recurring — time ─────────────────────────────────────────────────

async def received_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        await update.message.reply_text("פורמט שעה לא תקין. נסה שוב: *16:00*", parse_mode="Markdown")
        return ASK_TIME

    context.user_data["rrule_hour"] = int(match.group(1))
    context.user_data["rrule_minute"] = int(match.group(2))
    
    # Auto-set start date to today and no end date
    context.user_data["rrule_start"] = date.today().isoformat()
    context.user_data["rrule_end"] = None

    return await ask_remind_before(update, context)




# ── Step 6: Remind before ─────────────────────────────────────────────────────

async def ask_remind_before(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⏰ כמה זמן לפני לשלוח תזכורת?",
        reply_markup=ReplyKeyboardMarkup(
            [["30 דקות", "60 דקות", "120 דקות"]],
            one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ASK_REMIND_BEFORE


async def received_remind_before(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    # Extract the number from "30 דקות" or plain "45"
    match = re.search(r"\d+", text)
    minutes = int(match.group()) if match else 60
    context.user_data["remind_before"] = minutes

    await update.message.reply_text(
        "📨 לאן לשלוח את התזכורת?",
        reply_markup=ReplyKeyboardMarkup(
            [["קבוצה בלבד", "פרטי בלבד", "שניהם"]],
            one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ASK_SEND_TO


# ── Step 7: Send to ───────────────────────────────────────────────────────────

async def received_send_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in CANCEL_WORDS:
        return await cancel(update, context)

    mapping = {"קבוצה בלבד": "group", "פרטי בלבד": "private", "שניהם": "both"}
    send_to = mapping.get(text, "both")
    context.user_data["send_to"] = send_to

    return await show_confirmation(update, context)


# ── Confirmation ──────────────────────────────────────────────────────────────

async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data
    selected_personas = d.get("selected_personas", {})
    personas_str = ", ".join(selected_personas.keys())
    
    lines = [
        "✅ *סיכום האירוע — הכל נראה טוב?*\n",
        f"👤 עבור: *{personas_str}*",
        f"📌 פעילות: *{d['title']}*",
    ]
    if d.get("location"):
        lines.append(f"📍 מיקום: {d['location']}")

    if d.get("is_recurring"):
        days_heb = {v: k for k, v in DAYS_MAP.items()}
        day_names = ", ".join(days_heb.get(c, c) for c in d.get("rrule_days", []))
        lines.append(f"🔁 חוזר: {day_names} בשעה {d['rrule_hour']:02d}:{d['rrule_minute']:02d}")
        lines.append(f"📅 החל מ: {d['rrule_start']}")
    else:
        lines.append(f"📅 מועד: {d.get('event_datetime', '')}")

    lines.append(f"⏰ תזכורת: {d['remind_before']} דקות לפני")
    send_labels = {"group": "קבוצה בלבד", "private": "פרטי בלבד", "both": "שניהם"}
    lines.append(f"📨 שליחה: {send_labels.get(d['send_to'], d['send_to'])}")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=ReplyKeyboardMarkup(
            [["שמור ✅", "ביטול ❌"]],
            one_time_keyboard=True, resize_keyboard=True
        ),
        parse_mode="Markdown",
    )
    return CONFIRM


async def received_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "ביטול" in text or "❌" in text:
        return await cancel(update, context)

    d = context.user_data
    selected_personas = d.get("selected_personas", {})

    # Build rrule string if recurring
    rrule = None
    if d.get("is_recurring"):
        byday = ",".join(d["rrule_days"])
        rrule = f"FREQ=WEEKLY;BYDAY={byday};BYHOUR={d['rrule_hour']};BYMINUTE={d['rrule_minute']}"

    # Create event for each selected persona
    event_ids = []
    for persona_name, persona_id in selected_personas.items():
        event_id = add_event(
            title=d["title"],
            persona_id=persona_id,
            location=d.get("location"),
            event_datetime=d.get("event_datetime") if not d.get("is_recurring") else None,
            rrule=rrule,
            rrule_start=d.get("rrule_start"),
            rrule_end=d.get("rrule_end"),
            remind_before_minutes=d["remind_before"],
            send_to=d["send_to"],
        )
        event_ids.append(event_id)

    personas_count = len(selected_personas)
    await update.message.reply_text(
        f"✅ {personas_count} אירוע{'ים' if personas_count != 1 else ''} נשמר{'ו' if personas_count != 1 else ''}!\n\n"
        f"תזכורת תישלח {d['remind_before']} דקות לפני הפעילות.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "בוטל. תמיד ניתן להתחיל מחדש עם /add",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_datetime(text: str):
    """Parses '20/10/2025 16:00' or '20-10-2025 16:00'."""
    formats = ["%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M"]
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return TZ.localize(dt)
        except ValueError:
            continue
    return None


def _parse_date(text: str):
    """Parses '01/09/2025' or '01-09-2025'."""
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── ConversationHandler (import this into main.py) ───────────────────────────

def build_add_event_handler() -> ConversationHandler:
    """
    Returns the ConversationHandler to register in main.py.

    Usage in main.py:
        from handlers.add_event_wizard import build_add_event_handler
        app.add_handler(build_add_event_handler())
    """
    trigger = filters.Regex(r"(?i)(הוסף אירוע|add event|/add)")

    return ConversationHandler(
        entry_points=[
            CommandHandler("add", start_wizard),
            MessageHandler(trigger, start_wizard),
        ],
        states={
            ASK_PERSONA:       [MessageHandler(filters.TEXT & ~filters.COMMAND, received_persona)],
            ASK_TITLE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, received_title)],
            ASK_LOCATION:      [MessageHandler(filters.TEXT & ~filters.COMMAND, received_location)],
            ASK_RECURRING:     [MessageHandler(filters.TEXT & ~filters.COMMAND, received_recurring)],
            ASK_DATETIME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, received_datetime)],
            ASK_DAYS:          [MessageHandler(filters.TEXT & ~filters.COMMAND, received_days)],
            ASK_TIME:          [MessageHandler(filters.TEXT & ~filters.COMMAND, received_time)],
            ASK_REMIND_BEFORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_remind_before)],
            ASK_SEND_TO:       [MessageHandler(filters.TEXT & ~filters.COMMAND, received_send_to)],
            CONFIRM:           [MessageHandler(filters.TEXT & ~filters.COMMAND, received_confirmation)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex(r"(?i)ביטול|cancel"), cancel),
        ],
        allow_reentry=True,
    )

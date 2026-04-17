from __future__ import annotations
"""
utils/formatting.py
Hebrew message templates and @tag helpers.
"""

from datetime import datetime
import pytz

TZ = pytz.timezone("Asia/Jerusalem")

# Event type emoji
ACTIVITY_EMOJI = {
    "שחייה": "🏊",
    "כדורגל": "⚽",
    "ציור": "🎨",
    "מוזיקה": "🎵",
    "רפואה": "🏥",
    "בית ספר": "📚",
    "ספורט": "🏃",
    "default": "📅",
}


def get_emoji(title: str) -> str:
    for keyword, emoji in ACTIVITY_EMOJI.items():
        if keyword in title:
            return emoji
    return ACTIVITY_EMOJI["default"]


def mention(persona) -> str:
    """Returns @username if set, otherwise the Hebrew name."""
    if persona["telegram_username"]:
        return f"@{persona['telegram_username']}"
    return persona["name"]


def format_datetime_hebrew(dt: datetime) -> str:
    """e.g. 'יום שלישי, 15 באוקטובר בשעה 16:00'"""
    days_heb = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    months_heb = [
        "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
        "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"
    ]
    local = dt.astimezone(TZ)
    day_name = days_heb[local.weekday()]
    return f"יום {day_name}, {local.day} ב{months_heb[local.month]} בשעה {local.strftime('%H:%M')}"


def reminder_message(persona, event, occurrence_dt: datetime,
                     is_group: bool = True) -> str:
    """
    Builds a Hebrew reminder message.
    Group version: tags the persona by @username.
    Private version: uses their first name.
    """
    emoji = get_emoji(event["title"])
    tag = mention(persona) if is_group else persona["name"]
    time_str = format_datetime_hebrew(occurrence_dt)
    location = f"\n📍 {event['location']}" if event["location"] else ""
    notes = f"\n💬 {event['notes']}" if event["notes"] else ""

    msg = (
        f"{emoji} {tag} — {event['title']}\n"
        f"🕐 {time_str}"
        f"{location}"
        f"{notes}"
    )
    return msg


def parents_reminder_message(persona, event, occurrence_dt: datetime) -> str:
    """
    Private message to a parent about their child's upcoming event.
    Used when Alma or Arbel don't have Telegram yet.
    """
    emoji = get_emoji(event["title"])
    time_str = format_datetime_hebrew(occurrence_dt)
    location = f"\n📍 {event['location']}" if event["location"] else ""

    msg = (
        f"{emoji} תזכורת עבור {persona['name']}\n"
        f"פעילות: {event['title']}\n"
        f"🕐 {time_str}"
        f"{location}"
    )
    return msg


def confirmation_message(action: str, persona_name: str,
                          event_title: str) -> str:
    messages = {
        "confirm":    f"✅ מצוין! {event_title} מאושר.",
        "skip":       f"⏭ הבנתי, דילוג על {event_title} הפעם.",
        "snooze":     f"⏰ מקבל! אזכיר שוב בעוד 30 דקות.",
        "reschedule": f"📅 אעדכן את {event_title}. מתי חדש?",
        "question":   f"❓ שלחו את השאלה ואשתדל לעזור.",
        "unknown":    f"לא הבנתי, אפשר לנסות שוב? (סיום / דלג / דחה / שאלה)",
    }
    return messages.get(action, messages["unknown"])

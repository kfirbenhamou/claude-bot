from __future__ import annotations
"""
handlers/incoming.py
Handles all incoming Telegram messages.
"""

import logging
import os
from datetime import datetime, date, time, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv
from dateutil.rrule import rrulestr

from db.queries import (
    get_persona_by_username,
    get_persona_by_chat_id,
    get_all_personas,
    get_all_active_events,
    get_events_for_persona,
    save_private_chat_id,
    add_exception,
    mark_occurrence_handled,
    get_event_by_id,
    get_persona_by_id,
    get_gcal_event_id,
    set_gcal_event_id,
)
from handlers.intent import detect_intent
from handlers.qa import answer_event_question
from utils.formatting import confirmation_message, format_datetime_hebrew, get_emoji

load_dotenv()
GROUP_CHAT_ID = int(os.getenv("FAMILY_GROUP_CHAT_ID", "0"))
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Jerusalem"))

logger = logging.getLogger(__name__)


def _sync_event_to_gcal(event_id: int) -> None:
    """
    Fire-and-forget Google Calendar sync for a single event.
    Creates a new GCal event if none exists yet; updates if one does.
    Silently skips if token.json is not configured.
    """
    try:
        from services.gcal import create_gcal_event, update_gcal_event
        event = get_event_by_id(event_id)
        if not event:
            return
        persona = get_persona_by_id(event["persona_id"])
        persona_name = persona["name"] if persona else "משפחה"
        gcal_id = get_gcal_event_id(event_id)
        if gcal_id:
            update_gcal_event(gcal_id, event, persona_name)
        else:
            new_gcal_id = create_gcal_event(event, persona_name)
            if new_gcal_id:
                set_gcal_event_id(event_id, new_gcal_id)
    except Exception as exc:
        logger.warning(f"[gcal] _sync_event_to_gcal({event_id}) failed: {exc}")


def _delete_gcal_event_for(event_id: int) -> None:
    """Fire-and-forget Google Calendar deletion for a single event."""
    try:
        from services.gcal import delete_gcal_event
        gcal_id = get_gcal_event_id(event_id)
        if gcal_id:
            delete_gcal_event(gcal_id)
    except Exception as exc:
        logger.warning(f"[gcal] _delete_gcal_event_for({event_id}) failed: {exc}")


# ── /start ────────────────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    persona = get_persona_by_username(user.username)
    if persona:
        save_private_chat_id(user.username, chat_id)
        await update.message.reply_text(
            f"👋 שלום {persona['name']}!\n\n"
            f"רשמתי אותך. מעכשיו תקבל תזכורות גם בפרטי.\n\n"
            f"שלחו 'עזרה' כדי לראות את האפשרויות הזמינות."
        )
    else:
        await update.message.reply_text(
            "👋 שלום! ברוכים הבאים לבוט משפחה!\n\n"
            "לא מצאתי אותך ברשימת המשפחה.\n"
            "בקש מהמנהל להוסיף את שם המשתמש שלך."
        )


# ── Help menu with inline buttons ──────────────────────────────────────────────

async def show_help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display help menu with clickable buttons for each persona."""
    personas = get_all_personas()
    
    keyboard = []
    for persona in personas:
        keyboard.append(
            [InlineKeyboardButton(f"הצג {persona['name']}", callback_data=f"show_{persona['name']}")]
        )
    keyboard.append(
        [InlineKeyboardButton("הצג היום", callback_data="show_היום"),
         InlineKeyboardButton("הצג מחר", callback_data="show_מחר")]
    )
    keyboard.append(
        [InlineKeyboardButton("הצג הכל", callback_data="show_all")]
    )
    keyboard.append(
        [InlineKeyboardButton("📅 סיכום יום", callback_data="daily_summary")]
    )
    keyboard.append(
        [InlineKeyboardButton("הוסף אירוע", callback_data="add_event")]
    )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎯 בחרו אפשרות:\nניתן גם לכתוב יומי לסיכום היום (טקסט + קול).",
        reply_markup=reply_markup
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy support for /help command."""
    await show_help_menu(update, context)


# ── Show/Display handlers ───────────────────────────────────────────────────────

async def handle_daily_summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help menu: 📅 סיכום יום — same text + voice as the 8:00 morning summary."""
    query = update.callback_query
    await query.answer()
    from services.scheduler import send_daily_summary_to_chat

    await send_daily_summary_to_chat(context.bot, query.message.chat_id)


async def handle_show_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks for show commands."""
    query = update.callback_query
    await query.answer()
    
    command = query.data
    
    if command == "show_היום":
        await _show_today_callback(query)
    elif command == "show_מחר":
        await _show_tomorrow_callback(query)
    elif command == "show_all":
        await _show_all_callback(query)
    elif command == "add_event":
        await query.edit_message_text("🎉 בואו נוסיף אירוע חדש!")
    elif command.startswith("show_"):
        persona_name = command.replace("show_", "")
        await _show_persona_callback(query, persona_name)


async def handle_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy support - kept for compatibility."""
    # Parse argument — could come from /show or free text like "הצג כפיר"
    text = update.message.text.strip()
    args = context.args  # words after /show

    # Detect mode
    arg = " ".join(args).strip() if args else ""

    # Also support free-text triggers like "הצג היום" or "show today"
    if not arg:
        for word in ["היום", "today"]:
            if word in text:
                arg = "היום"
                break

    if arg in ("היום", "today"):
        await _show_today(update)
    elif arg:
        await _show_persona(update, arg)
    else:
        await _show_all(update)


def _build_event_message(event: dict, persona_name: str) -> str:
    """Builds a formatted event message."""
    title = event["title"]
    location = f"\n📍 {event['location']}" if event["location"] else ""
    notes = f"\n📝 {event['notes']}" if event["notes"] else ""
    
    if event["is_recurring"]:
        rrule_info = f"\n🔁 חוזר: {event['rrule']}"
    else:
        rrule_info = ""
    
    if event["event_datetime"]:
        try:
            dt = datetime.fromisoformat(event["event_datetime"])
            time_info = f"\n⏰ {dt.strftime('%d/%m/%Y %H:%M')}"
        except:
            time_info = ""
    else:
        time_info = ""
    
    reminder_mins = event["remind_before_minutes"]
    reminder_info = f"\n🔔 תזכורת {reminder_mins} דקות לפני"
    
    return f"👤 {persona_name}\n🎯 {title}{location}{notes}{time_info}{rrule_info}{reminder_info}"


def _build_event_keyboard(event_id: int) -> InlineKeyboardMarkup:
    """Builds keyboard with edit, remove, add reminder, and TTS listen buttons."""
    keyboard = [
        [
            InlineKeyboardButton("✏️ עריכה", callback_data=f"evt_edit:{event_id}"),
            InlineKeyboardButton("🗑️ הסרה", callback_data=f"evt_remove:{event_id}"),
            InlineKeyboardButton("🔔 הוסף תזכורת", callback_data=f"evt_reminder:{event_id}"),
        ],
        [
            InlineKeyboardButton("🔊 האזן", callback_data=f"evt_tts:{event_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _send_event_with_buttons(chat_id: int, event: dict, persona_name: str, update: Update) -> None:
    """Sends a single event message with action buttons."""
    text = _build_event_message(event, persona_name)
    keyboard = _build_event_keyboard(event["id"])
    await update.message._bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )


async def _show_all(update: Update):
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    if not events:
        await update.message.reply_text("אין אירועים רשומים עדיין.")
        return
    
    await update.message.reply_text(f"📅 *כל האירועים* ({len(events)} סה״כ)")
    for e in events:
        await _send_event_with_buttons(
            update.message.chat_id, 
            e, 
            personas.get(e["persona_id"], "?"),
            update
        )


async def _show_all_callback(query):
    """Show all events via callback query."""
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    if not events:
        await query.edit_message_text("אין אירועים רשומים עדיין.")
        return
    
    await query.edit_message_text(f"📅 *כל האירועים* ({len(events)} סה״כ)", parse_mode="Markdown")
    for e in events:
        await query.message._bot.send_message(
            chat_id=query.message.chat_id,
            text=_build_event_message(e, personas.get(e["persona_id"], "?")),
            reply_markup=_build_event_keyboard(e["id"]),
            parse_mode="Markdown"
        )


async def _show_persona(update: Update, name: str):
    personas = get_all_personas()
    persona = next((p for p in personas if p["name"] == name), None)
    if not persona:
        await update.message.reply_text(
            f"לא מצאתי פרסונה בשם '{name}'.\n"
            f"שמות זמינים: {', '.join(p['name'] for p in personas)}"
        )
        return
    events = get_events_for_persona(persona["id"])
    if not events:
        await update.message.reply_text(f"אין אירועים עבור {name}.")
        return
    
    await update.message.reply_text(f"📅 *אירועים עבור {name}* ({len(events)} סה״כ)", parse_mode="Markdown")
    for e in events:
        await _send_event_with_buttons(
            update.message.chat_id,
            e,
            name,
            update
        )


async def _show_persona_callback(query, name: str):
    """Show persona's events via callback query."""
    personas = get_all_personas()
    persona = next((p for p in personas if p["name"] == name), None)
    if not persona:
        await query.edit_message_text(
            f"לא מצאתי פרסונה בשם '{name}'.\n"
            f"שמות זמינים: {', '.join(p['name'] for p in personas)}"
        )
        return
    events = get_events_for_persona(persona["id"])
    if not events:
        await query.edit_message_text(f"אין אירועים עבור {name}.")
        return
    
    await query.edit_message_text(f"📅 *אירועים עבור {name}* ({len(events)} סה״כ)", parse_mode="Markdown")
    for e in events:
        await query.message._bot.send_message(
            chat_id=query.message.chat_id,
            text=_build_event_message(e, name),
            reply_markup=_build_event_keyboard(e["id"]),
            parse_mode="Markdown"
        )


async def _show_today(update: Update):
    from dateutil.rrule import rrulestr
    today = date.today()
    now = datetime.now(TZ)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    
    today_events = []
    
    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                rrule_start_str = e["rrule_start"]
                # Handle date-only strings (YYYY-MM-DD)
                if isinstance(rrule_start_str, str):
                    if len(rrule_start_str) == 10 and rrule_start_str[4] == '-':
                        rrule_start_str = rrule_start_str + " 00:00:00"
                
                dtstart = datetime.fromisoformat(rrule_start_str)
                if dtstart.tzinfo is None:
                    dtstart = TZ.localize(dtstart)
                elif dtstart.tzinfo != TZ:
                    dtstart = dtstart.astimezone(TZ)
                
                rrule_str = f"RRULE:{e['rrule']}"
                rule = rrulestr(rrule_str, ignoretz=False, dtstart=dtstart)
                
                day_start = TZ.localize(datetime.combine(today, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(today, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    today_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception as ex:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == today:
                    today_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception:
                pass

    if not today_events:
        await update.message.reply_text(f"אין אירועים להיום {today.strftime('%d/%m/%Y')} 🎉")
        return
    
    await update.message.reply_text(f"📅 *אירועים להיום — {today.strftime('%d/%m/%Y')}* ({len(today_events)} סה״כ)", parse_mode="Markdown")
    for e, name in today_events:
        await _send_event_with_buttons(update.message.chat_id, e, name, update)


async def _show_today_callback(query):
    """Show today's events via callback query."""
    from dateutil.rrule import rrulestr
    today = date.today()
    now = datetime.now(TZ)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    
    today_events = []
    
    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                rrule_start_str = e["rrule_start"]
                # Handle date-only strings (YYYY-MM-DD)
                if isinstance(rrule_start_str, str):
                    if len(rrule_start_str) == 10 and rrule_start_str[4] == '-':
                        rrule_start_str = rrule_start_str + " 00:00:00"
                
                dtstart = datetime.fromisoformat(rrule_start_str)
                if dtstart.tzinfo is None:
                    dtstart = TZ.localize(dtstart)
                elif dtstart.tzinfo != TZ:
                    dtstart = dtstart.astimezone(TZ)
                
                rrule_str = f"RRULE:{e['rrule']}"
                rule = rrulestr(rrule_str, ignoretz=False, dtstart=dtstart)
                
                day_start = TZ.localize(datetime.combine(today, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(today, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    today_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception as ex:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == today:
                    today_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception:
                pass

    if not today_events:
        await query.edit_message_text(f"אין אירועים להיום {today.strftime('%d/%m/%Y')} 🎉")
        return
    
    await query.edit_message_text(f"📅 *אירועים להיום — {today.strftime('%d/%m/%Y')}* ({len(today_events)} סה״כ)", parse_mode="Markdown")
    for e, name in today_events:
        await query.message._bot.send_message(
            chat_id=query.message.chat_id,
            text=_build_event_message(e, name),
            reply_markup=_build_event_keyboard(e["id"]),
            parse_mode="HTML"
        )


async def _show_tomorrow(update: Update):
    from dateutil.rrule import rrulestr
    tomorrow = date.today() + timedelta(days=1)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    
    tomorrow_events = []
    
    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                rrule_start_str = e["rrule_start"]
                # Handle date-only strings (YYYY-MM-DD)
                if isinstance(rrule_start_str, str):
                    if len(rrule_start_str) == 10 and rrule_start_str[4] == '-':
                        rrule_start_str = rrule_start_str + " 00:00:00"
                
                dtstart = datetime.fromisoformat(rrule_start_str)
                if dtstart.tzinfo is None:
                    dtstart = TZ.localize(dtstart)
                elif dtstart.tzinfo != TZ:
                    dtstart = dtstart.astimezone(TZ)
                
                rrule_str = f"RRULE:{e['rrule']}"
                rule = rrulestr(rrule_str, ignoretz=False, dtstart=dtstart)
                
                day_start = TZ.localize(datetime.combine(tomorrow, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(tomorrow, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    tomorrow_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception as ex:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == tomorrow:
                    tomorrow_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception:
                pass

    if not tomorrow_events:
        await update.message.reply_text(f"אין אירועים למחר {tomorrow.strftime('%d/%m/%Y')} 🎉")
        return
    
    await update.message.reply_text(f"📅 *אירועים למחר — {tomorrow.strftime('%d/%m/%Y')}* ({len(tomorrow_events)} סה״כ)", parse_mode="Markdown")
    for e, name in tomorrow_events:
        await _send_event_with_buttons(update.message.chat_id, e, name, update)


async def _show_tomorrow_callback(query):
    """Show tomorrow's events via callback query."""
    from dateutil.rrule import rrulestr
    tomorrow = date.today() + timedelta(days=1)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    
    tomorrow_events = []
    
    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                rrule_start_str = e["rrule_start"]
                # Handle date-only strings (YYYY-MM-DD)
                if isinstance(rrule_start_str, str):
                    if len(rrule_start_str) == 10 and rrule_start_str[4] == '-':
                        rrule_start_str = rrule_start_str + " 00:00:00"
                
                dtstart = datetime.fromisoformat(rrule_start_str)
                if dtstart.tzinfo is None:
                    dtstart = TZ.localize(dtstart)
                elif dtstart.tzinfo != TZ:
                    dtstart = dtstart.astimezone(TZ)
                
                rrule_str = f"RRULE:{e['rrule']}"
                rule = rrulestr(rrule_str, ignoretz=False, dtstart=dtstart)
                
                day_start = TZ.localize(datetime.combine(tomorrow, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(tomorrow, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    tomorrow_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception as ex:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == tomorrow:
                    tomorrow_events.append((e, personas.get(e["persona_id"], "?")))
            except Exception:
                pass

    if not tomorrow_events:
        await query.edit_message_text(f"אין אירועים למחר {tomorrow.strftime('%d/%m/%Y')} 🎉")
        return
    
    await query.edit_message_text(f"📅 *אירועים למחר — {tomorrow.strftime('%d/%m/%Y')}* ({len(tomorrow_events)} סה״כ)", parse_mode="Markdown")
    for e, name in tomorrow_events:
        await query.message._bot.send_message(
            chat_id=query.message.chat_id,
            text=_build_event_message(e, name),
            reply_markup=_build_event_keyboard(e["id"]),
            parse_mode="HTML"
        )


def _format_event_line(event, persona_name: str, dt=None) -> str:
    """Formats a single event as a text line."""
    title = event["title"]
    location = f" — {event['location']}" if event["location"] else ""

    if dt:
        time_str = dt.strftime("%H:%M")
        return f"• {persona_name} | {title}{location} בשעה {time_str}"
    elif event["is_recurring"]:
        return f"• {persona_name} | {title}{location} 🔁"
    elif event["event_datetime"]:
        try:
            d = datetime.fromisoformat(event["event_datetime"])
            return f"• {persona_name} | {title}{location} — {d.strftime('%d/%m %H:%M')}"
        except Exception:
            return f"• {persona_name} | {title}{location}"
    return f"• {persona_name} | {title}{location}"


def _try_handle_show_request(text: str, update: Update) -> str:
    """
    Attempts to detect and handle show/display requests in Hebrew or English.
    Patterns:
    - "הצג ארועים עבור [name]" → show events for persona
    - "הצג [name]" → show events for persona
    - "show [name]" → show events for persona (English)
    - "[name]" → just the name alone (show events for persona)
    - "הצג היום" / "show today" → show today's events
    - "הצג מחר" / "show tomorrow" → show tomorrow's events
    - "הצג הכל" / "show all" → show all events
    
    Returns the persona name to show if matched, "ALL", "TODAY", "TOMORROW", or None.
    """
    import re
    
    text_lower = text.lower()
    text_clean = text.strip()
    
    # Check for "show all"
    if "הצג הכל" in text or "show all" in text_lower:
        return "ALL"
    
    # Check for "show today"
    if "הצג היום" in text or "show today" in text_lower:
        return "TODAY"
    
    # Check for "show tomorrow"
    if "הצג מחר" in text or "show tomorrow" in text_lower:
        return "TOMORROW"
    
    # Check for "הצג ארועים עבור [name]" or "הצג [name]" patterns
    personas = get_all_personas()
    persona_names = {p["name"]: p for p in personas}
    
    for persona_name in persona_names.keys():
        # Pattern: "הצג ארועים עבור [name]"
        if f"הצג ארועים עבור {persona_name}" in text or f"הצג אירועים עבור {persona_name}" in text:
            return persona_name
        
        # Pattern: "הצג [name]" (Hebrew verb "show")
        if f"הצג {persona_name}" in text:
            return persona_name
        
        # Pattern: "show [name]" (English)
        if f"show {persona_name}" in text_lower:
            return persona_name
        
        # Pattern: just the name itself (exact match)
        if text_clean == persona_name:
            return persona_name
    
    return None


_DAILY_SUMMARY_TRIGGERS = frozenset({"יומי", "סיכום יומי", "תכנית היום"})


def _normalize_daily_summary_trigger(text: str) -> str:
    """Strip whitespace and stray Hebrew/ASCII quotes (e.g. יומי״ → יומי)."""
    s = (text or "").strip()
    while s and s[0] in "\"'״׳":
        s = s[1:].lstrip()
    while s and s[-1] in "\"'״׳":
        s = s[:-1].rstrip()
    return s.strip()


def _is_daily_summary_command(text: str) -> bool:
    return _normalize_daily_summary_trigger(text) in _DAILY_SUMMARY_TRIGGERS


# ── Incoming reply handler ────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    text = msg.text.strip() if msg.text else ""

    # ── Multi-turn Q&A conversation mode ───────────────────────────────────────
    in_qa_mode = context.user_data.get("qa_mode")
    if in_qa_mode and text:
        if text.lower() in ["done", "סיום", "דלג"]:
            # Exit Q&A mode
            context.user_data.pop("qa_mode", None)
            context.user_data.pop("qa_conversation", None)
            context.user_data.pop("qa_event_context", None)
            await msg.reply_text("✓ סיימנו את השיחה. חזרנו לתפריט הראשי.")
            return
        
        # Continue conversation
        from handlers.qa import answer_event_question_multiturn
        
        event_ctx = context.user_data.get("qa_event_context", {})
        history = context.user_data.get("qa_conversation", [])
        
        # Add user message to history
        history.append({"role": "user", "content": text})
        
        # Get AI answer with full history
        answer = answer_event_question_multiturn(text, event_ctx, history)
        
        # Add assistant message to history
        history.append({"role": "assistant", "content": answer})
        context.user_data["qa_conversation"] = history
        
        # Show exit button
        keyboard = [
            [InlineKeyboardButton("סיום שיחה", callback_data="qa_exit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.reply_text(f"🤖 {answer}", reply_markup=reply_markup)
        return

    # If user is in "ask a question about an event" mode, handle it first.
    pending = context.user_data.get("pending_event_question")
    if pending and text:
        from handlers.qa import answer_event_question_multiturn
        
        event_ctx = pending.get("event_context") or {}
        answer = answer_event_question_multiturn(text, event_ctx, [])
        
        # Initialize multi-turn conversation
        context.user_data.pop("pending_event_question", None)
        context.user_data["qa_mode"] = True
        context.user_data["qa_event_context"] = event_ctx
        context.user_data["qa_conversation"] = [
            {"role": "user", "content": text},
            {"role": "assistant", "content": answer}
        ]
        
        # Show exit button
        keyboard = [
            [InlineKeyboardButton("סיום שיחה", callback_data="qa_exit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.reply_text(f"🤖 {answer}", reply_markup=reply_markup)
        return

    # Hebrew text command shortcuts (שפה עברית בלבד)
    if text == "עזרה" or text == "הסבר":
        return await show_help_menu(update, context)
    if text == "הוסף אירוע":
        # User can continue to add event through wizard
        return
    if text == "ביטול":
        context.user_data.clear()
        await msg.reply_text("ביטלתי את הפעולה הנוכחית. ✓")
        return

    if _is_daily_summary_command(text):
        from services.scheduler import send_daily_summary_to_chat

        await send_daily_summary_to_chat(context.bot, msg.chat_id)
        return

    # ── Edit event field input ─────────────────────────────────────────────────
    edit_state = context.user_data.get("edit_event_state")
    if edit_state and edit_state.get("step") == "awaiting_input" and text:
        await _handle_edit_field_input(update, context, text)
        return

    # ── Free-text show/display requests ────────────────────────────────────────
    # Support patterns like "הצג ארועים עבור עלמה", "הצג עלמה", "show alma", etc.
    show_request = _try_handle_show_request(text, update)
    if show_request:
        if show_request == "ALL":
            await _show_all(update)
        elif show_request == "TODAY":
            await _show_today(update)
        elif show_request == "TOMORROW":
            await _show_tomorrow(update)
        else:
            await _show_persona(update, show_request)
        return

    # Only handle replies to the bot's own messages from here on
    if not msg.reply_to_message:
        return
    if msg.reply_to_message.from_user.id != context.bot.id:
        return

    user = msg.from_user
    persona = get_persona_by_username(user.username)
    if not persona:
        persona = get_persona_by_chat_id(str(msg.chat_id))
    if not persona:
        await msg.reply_text("לא הצלחתי לזהות אותך. פנה לכפיר או מורן.")
        return

    original_text = msg.reply_to_message.text or ""
    event_context = _parse_event_context(original_text)
    result = detect_intent(text, event_context)
    intent = result["intent"]

    reply = confirmation_message(intent, persona["name"],
                                 event_context.get("title", "הפעילות"))

    if intent == "skip" and event_context.get("event_id"):
        add_exception(
            event_id=event_context["event_id"],
            original_date=event_context.get("date"),
            action="skip",
            created_by=persona["name"],
        )
    elif intent == "snooze":
        minutes = result.get("snooze_minutes") or 30
        context.job_queue.run_once(
            _snooze_callback,
            when=minutes * 60,
            data={
                "chat_id": msg.chat_id,
                "original_text": original_text,
                "persona_name": persona["name"],
            },
        )
        reply = f"⏰ אזכיר שוב בעוד {minutes} דקות."

    await msg.reply_text(reply)


async def _snooze_callback(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=f"⏰ תזכורת חוזרת עבור {data['persona_name']}:\n\n{data['original_text']}"
    )


# ── Voice message handler ──────────────────────────────────────────────────────

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Listen to all voice messages in any chat.
    Transcribe with Whisper, then parse for event intent.
    If a create_event or update_event action is detected — execute it.
    If action is 'none' (casual chat) — stay completely silent.
    """
    msg = update.message
    if not msg or not msg.voice:
        return

    from services.transcription import transcribe_voice
    from handlers.agent_actions import parse_agent_action, build_rrule, today_date_str
    from db.queries import add_event, update_event, find_events, get_persona_by_id as _get_persona

    # Download the voice file
    try:
        voice_file = await context.bot.get_file(msg.voice.file_id)
        file_bytes = await voice_file.download_as_bytearray()
    except Exception as exc:
        logger.warning(f"[voice] failed to download voice file: {exc}")
        return

    # Transcribe
    text = await transcribe_voice(bytes(file_bytes))
    if not text:
        return  # blank audio or transcription error — stay silent

    logger.info(f"[voice] transcribed text: {text!r}")

    # Parse intent
    personas = get_all_personas()
    persona_names = [p["name"] for p in personas]
    action_data = parse_agent_action(text, persona_names)
    action = action_data.get("action", "none")

    if action == "none":
        return  # casual chat — stay silent

    # ── Create event ──────────────────────────────────────────────────────────
    if action == "create_event":
        event = action_data.get("event") or {}
        names = event.get("persona_names") or (
            [event["persona_name"]] if event.get("persona_name") else []
        )
        if not names:
            await msg.reply_text("לא הצלחתי לזהות לעבור מי האירוע. נסה שוב.")
            return

        title = event.get("title", "אירוע")
        location = event.get("location")
        notes = event.get("notes")
        remind = int(event.get("remind_before_minutes") or 60)
        send_to = event.get("send_to") or "group"

        is_recurring = bool(event.get("days_of_week"))
        rrule = None
        event_datetime = None
        rrule_start = None

        if is_recurring:
            rrule = build_rrule(event["days_of_week"], event.get("start_time"))
            rrule_start = today_date_str()
        else:
            event_datetime = event.get("event_datetime")

        created_names = []
        for name in names:
            persona = next((p for p in personas if p["name"] == name), None)
            if not persona:
                continue
            event_id = add_event(
                title=title,
                persona_id=persona["id"],
                location=location,
                notes=notes,
                event_datetime=event_datetime,
                rrule=rrule,
                rrule_start=rrule_start,
                remind_before_minutes=remind,
                send_to=send_to,
            )
            _sync_event_to_gcal(event_id)
            created_names.append(name)

        if created_names:
            names_str = ", ".join(created_names)
            time_str = event_datetime or (f"חוזר: {rrule}" if rrule else "")
            await msg.reply_text(
                f"✅ נוסף אירוע:\n"
                f"👤 {names_str}\n"
                f"🎯 {title}\n"
                f"⏰ {time_str}"
            )
        else:
            await msg.reply_text("לא הצלחתי למצוא את שם האדם. נסה שוב.")

    # ── Update event ──────────────────────────────────────────────────────────
    elif action == "update_event":
        match = action_data.get("match") or {}
        updates = action_data.get("updates") or {}

        event_id = match.get("event_id")
        if not event_id:
            persona_name = match.get("persona_name")
            title_query = match.get("title_query")
            persona_obj = next((p for p in personas if p["name"] == persona_name), None) if persona_name else None
            results = find_events(
                persona_id=persona_obj["id"] if persona_obj else None,
                title_query=title_query,
            )
            if not results:
                await msg.reply_text("לא מצאתי אירוע תואם. נסה לציין את שמו המדויק.")
                return
            event_id = results[0]["id"]

        db_updates = {k: v for k, v in updates.items() if v is not None and k in {
            "title", "location", "notes", "remind_before_minutes", "send_to",
            "event_datetime", "rrule", "rrule_start", "rrule_end", "is_recurring"
        }}
        if db_updates:
            update_event(event_id, **db_updates)
            _sync_event_to_gcal(event_id)
            await msg.reply_text(f"✅ האירוע עודכן.")
        else:
            await msg.reply_text("לא הצלחתי להבין מה לעדכן. נסה שוב.")


async def handle_qa_exit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle exiting Q&A conversation."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("qa_mode", None)
    context.user_data.pop("qa_conversation", None)
    context.user_data.pop("qa_event_context", None)
    
    await query.edit_message_text("✓ סיימנו את השיחה.")


def _parse_event_context(bot_message_text: str) -> dict:
    lines = bot_message_text.strip().split("\n")
    title = ""
    if lines:
        parts = lines[0].split("—")
        if len(parts) > 1:
            title = parts[-1].strip()
    return {"title": title}


# ── Reminder inline buttons ────────────────────────────────────────────────────

async def handle_event_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles reminder inline keyboard actions.
    callback_data format: evt:<event_id>:<YYYY-MM-DD>:<HHMM>:<action>
    """
    query = update.callback_query
    await query.answer()

    try:
        parts = (query.data or "").split(":")
        if len(parts) != 5 or parts[0] != "evt":
            return
        _, event_id_str, date_str, hhmm, action = parts
    except Exception:
        return

    event_id = int(event_id_str)
    user = query.from_user
    persona = get_persona_by_username(user.username)
    if not persona:
        persona = get_persona_by_chat_id(str(query.message.chat_id))

    if action == "skip":
        add_exception(
            event_id=event_id,
            original_date=date_str,
            action="skip",
            created_by=(persona["name"] if persona else (user.full_name or "unknown")),
        )
        await query.message.reply_text("⏭ דילגתי על ההתרחשות הזאת.")
        return

    if action == "snooze30":
        context.job_queue.run_once(
            _snooze_inline_callback,
            when=30 * 60,
            data={
                "chat_id": query.message.chat_id,
                "text": query.message.text or "",
                "reply_markup": query.message.reply_markup,
            },
        )
        await query.message.reply_text("⏰ סבבה — אזכיר שוב בעוד 30 דקות.")
        return

    if action == "question":
        # Keep minimal context; answer will be generated when user types next message.
        context.user_data["pending_event_question"] = {
            "event_context": {
                "persona_name": (persona["name"] if persona else ""),
                "title": "",
                "when": f"{date_str} {hhmm[:2]}:{hhmm[2:]}",
                "location": "",
                "event_id": event_id,
            }
        }
        await query.message.reply_text("❓ כתבו את השאלה שלכם על האירוע הזה.")
        return

    if action == "confirm":
        event = get_event_by_id(event_id)
        mark_occurrence_handled(
            event_id=event_id,
            occurrence_date=date_str,
            handled_by=(persona["name"] if persona else (user.full_name or "unknown")),
        )
        # Visually disable buttons on that message
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        # Notify the group that it's handled (and optionally when next cycle is).
        try:
            occ_dt = TZ.localize(
                datetime.fromisoformat(f"{date_str}T{hhmm[:2]}:{hhmm[2:]}:00")
            )
        except Exception:
            occ_dt = None

        handled_by_name = (persona["name"] if persona else (user.full_name or "מישהו"))
        if event:
            event_persona = get_persona_by_id(event["persona_id"])
            who = event_persona["name"] if event_persona else ""
            title = event["title"]
            emoji = get_emoji(title or "")
            when_str = format_datetime_hebrew(occ_dt) if occ_dt else f"{date_str} {hhmm[:2]}:{hhmm[2:]}"

            if event["is_recurring"] and event["rrule"] and event["rrule_start"] and occ_dt:
                # Compute next occurrence after this one.
                rrule_start_str = event["rrule_start"]
                if isinstance(rrule_start_str, str) and len(rrule_start_str) == 10 and rrule_start_str[4] == "-":
                    rrule_start_str = rrule_start_str + " 00:00:00"
                dtstart = datetime.fromisoformat(rrule_start_str)
                if dtstart.tzinfo is None:
                    dtstart = TZ.localize(dtstart)

                rule = rrulestr(f"RRULE:{event['rrule']}", ignoretz=False, dtstart=dtstart)
                next_dt = rule.after(occ_dt, inc=False)
                if next_dt and next_dt.tzinfo is None:
                    next_dt = TZ.localize(next_dt)

                # Respect rrule_end if present
                if next_dt and event["rrule_end"]:
                    end_str = event["rrule_end"]
                    if isinstance(end_str, str) and len(end_str) == 10 and end_str[4] == "-":
                        end_str = end_str + " 23:59:59"
                    end_dt = datetime.fromisoformat(end_str)
                    if end_dt.tzinfo is None:
                        end_dt = TZ.localize(end_dt)
                    if next_dt > end_dt:
                        next_dt = None

                if next_dt:
                    next_str = format_datetime_hebrew(next_dt)
                    text = (
                        f"✅ {emoji} {who} — {title}\n"
                        f"סומן כבוצע על ידי {handled_by_name}.\n"
                        f"({when_str})\n\n"
                        f"🔁 המחזור הבא הוא: {next_str}"
                    )
                else:
                    text = (
                        f"✅ {emoji} {who} — {title}\n"
                        f"סומן כבוצע על ידי {handled_by_name}.\n"
                        f"({when_str})"
                    )
            else:
                text = (
                    f"✅ {emoji} {who} — {title}\n"
                    f"סומן כבוצע על ידי {handled_by_name}.\n"
                    f"({when_str})\n\n"
                    f"זה אירוע חד־פעמי ולא יופיע שוב."
                )

            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=text)

        await query.message.reply_text("✅ סומן כבוצע — לא אזכיר שוב.")
        return


async def _snooze_inline_callback(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=f"⏰ תזכורת חוזרת:\n\n{data['text']}",
        reply_markup=data.get("reply_markup"),
    )


# ── Event Management Callbacks (Edit, Remove, Add Reminder) ──────────────────

def _build_edit_menu(event_id: int, note: str = "") -> tuple:
    """Returns (text, InlineKeyboardMarkup) for the edit field selection menu."""
    event = get_event_by_id(event_id)
    title = event["title"] if event else str(event_id)
    keyboard = [
        [InlineKeyboardButton("📝 כותרת", callback_data=f"edit_field:title:{event_id}")],
        [InlineKeyboardButton("📍 מיקום", callback_data=f"edit_field:location:{event_id}")],
        [InlineKeyboardButton("⏰ זמן", callback_data=f"edit_field:datetime:{event_id}")],
        [InlineKeyboardButton("🔁 חוזר", callback_data=f"edit_field:recurring:{event_id}")],
        [InlineKeyboardButton("🔔 זמן תזכורת", callback_data=f"edit_field:reminder:{event_id}")],
        [InlineKeyboardButton("✅ סיום עריכה", callback_data="cancel_edit")],
    ]
    prefix = f"✔️ {note}\n\n" if note else ""
    text = f"{prefix}✏️ עריכת {title}\n\nבחרו שדה לעריכה:"
    return text, InlineKeyboardMarkup(keyboard)


async def handle_event_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle edit button click for an event."""
    query = update.callback_query
    await query.answer()
    
    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אולם אירוע זה לא נמצא.")
        return
    
    context.user_data["edit_event_state"] = {
        "event_id": event_id,
        "step": "choose_field",
    }
    
    text, reply_markup = _build_edit_menu(event_id)
    await query.edit_message_text(text, reply_markup=reply_markup)


async def handle_event_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle remove button click for an event."""
    query = update.callback_query
    await query.answer()
    
    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע זה לא נמצא.")
        return
    
    # Confirm removal
    keyboard = [
        [
            InlineKeyboardButton("✅ כן, הסר", callback_data=f"confirm_remove:{event_id}"),
            InlineKeyboardButton("❌ לא, בטל", callback_data="cancel_remove"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"⚠️ האם למחוק את \"{event['title']}\"?\n\nפעולה זו לא ניתן לשחזור.",
        reply_markup=reply_markup
    )


async def handle_event_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle add reminder button click for an event."""
    query = update.callback_query
    await query.answer()
    
    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע זה לא נמצא.")
        return
    
    # Initialize reminder flow state
    context.user_data["add_reminder_state"] = {
        "event_id": event_id,
        "step": "select_timing",
        "reminders": [],
    }
    
    # Show preset reminder options
    keyboard = [
        [InlineKeyboardButton("15 דקות לפני", callback_data=f"add_reminder:15:{event_id}")],
        [InlineKeyboardButton("30 דקות לפני", callback_data=f"add_reminder:30:{event_id}")],
        [InlineKeyboardButton("1 שעה לפני", callback_data=f"add_reminder:60:{event_id}")],
        [InlineKeyboardButton("2 שעות לפני", callback_data=f"add_reminder:120:{event_id}")],
        [InlineKeyboardButton("1 יום לפני", callback_data=f"add_reminder:1440:{event_id}")],
        [InlineKeyboardButton("הוסף עוד", callback_data="add_another_reminder")],
        [InlineKeyboardButton("סיום", callback_data=f"finish_reminders:{event_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔔 הוסף תזכורות ל\"{event['title']}\"\n\nבחרו כמה דקות לפני האירוע:",
        reply_markup=reply_markup
    )


async def handle_event_tts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 🔊 האזן button — sends a spoken audio summary of the event."""
    query = update.callback_query
    await query.answer("🔊 מייצר אודיו...")

    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except Exception:
        return

    event = get_event_by_id(event_id)
    if not event:
        await query.message.reply_text("אירוע לא נמצא.")
        return

    persona = get_persona_by_id(event["persona_id"])
    persona_name = persona["name"] if persona else "?"

    from services.tts import generate_event_audio
    import io

    audio_bytes = generate_event_audio(dict(event), persona_name)
    if not audio_bytes:
        await query.message.reply_text("❌ לא הצלחתי לייצר אודיו כרגע. נסו שוב.")
        return

    # Reply under the event card, no caption — audio is the event briefing only.
    await query.message._bot.send_voice(
        chat_id=query.message.chat_id,
        voice=InputFile(io.BytesIO(audio_bytes), filename="event.ogg"),
        reply_to_message_id=query.message.message_id,
    )


async def handle_confirm_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation to remove an event."""
    query = update.callback_query
    await query.answer()
    
    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except:
        return
    
    from db.queries import update_event
    event = get_event_by_id(event_id)
    
    if event:
        _delete_gcal_event_for(event_id)
        update_event(event_id, active=False)
        await query.edit_message_text(f"✅ \"{ event['title']}\" הסר בהצלחה.")
    else:
        await query.edit_message_text("אירוע לא נמצא.")


async def handle_add_reminder_timing_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reminder timing selection."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        _, minutes_str, event_id_str = parts
        minutes = int(minutes_str)
        event_id = int(event_id_str)
    except:
        return
    
    # Add reminder to the list
    if "add_reminder_state" not in context.user_data:
        context.user_data["add_reminder_state"] = {"event_id": event_id, "reminders": []}
    
    context.user_data["add_reminder_state"]["reminders"].append(minutes)
    
    reminders_text = "\n".join([f"  • {m} דקות לפני" for m in context.user_data["add_reminder_state"]["reminders"]])
    
    # Show option to add more or finish
    keyboard = [
        [InlineKeyboardButton("15 דקות לפני", callback_data=f"add_reminder:15:{event_id}")],
        [InlineKeyboardButton("30 דקות לפני", callback_data=f"add_reminder:30:{event_id}")],
        [InlineKeyboardButton("1 שעה לפני", callback_data=f"add_reminder:60:{event_id}")],
        [InlineKeyboardButton("2 שעות לפני", callback_data=f"add_reminder:120:{event_id}")],
        [InlineKeyboardButton("1 יום לפני", callback_data=f"add_reminder:1440:{event_id}")],
        [InlineKeyboardButton("סיום", callback_data=f"finish_reminders:{event_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔔 תזכורות שנוספו:\n{reminders_text}\n\nהוסף עוד או בחר סיום:",
        reply_markup=reply_markup
    )


async def handle_finish_reminders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle finishing the reminder addition flow."""
    query = update.callback_query
    await query.answer()
    
    try:
        _, event_id_str = query.data.split(":")
        event_id = int(event_id_str)
    except:
        return
    
    state = context.user_data.get("add_reminder_state", {})
    reminders = state.get("reminders", [])
    
    if reminders:
        from db.queries import update_event
        event = get_event_by_id(event_id)
        
        # For now, update the main remind_before_minutes to the first reminder
        # In a more advanced system, you'd store multiple reminders
        if event:
            update_event(event_id, remind_before_minutes=reminders[0])
            reminders_text = "\n".join([f"  • {m} דקות לפני האירוע" for m in reminders])
            await query.edit_message_text(
                f"✅ התזכורות לאירוע \"{event['title']}\" עודכנו:\n{reminders_text}"
            )
    else:
        await query.edit_message_text("לא נוספו תזכורות.")
    
    # Clean up state
    context.user_data.pop("add_reminder_state", None)


async def handle_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle field selection in edit flow."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        _, field, event_id_str = parts[0], parts[1], parts[2]
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע לא נמצא.")
        return
    
    # Initialize edit state for this specific field
    if field == "datetime":
        # New day-of-week based flow
        context.user_data["edit_event_state"] = {
            "event_id": event_id,
            "field": field,
            "step": "awaiting_day_name",
            "temp_data": {},
        }
        
        keyboard = [
            [InlineKeyboardButton("ראשון", callback_data=f"day_select:sunday:{event_id}")],
            [InlineKeyboardButton("שני", callback_data=f"day_select:monday:{event_id}")],
            [InlineKeyboardButton("שלישי", callback_data=f"day_select:tuesday:{event_id}")],
            [InlineKeyboardButton("רביעי", callback_data=f"day_select:wednesday:{event_id}")],
            [InlineKeyboardButton("חמישי", callback_data=f"day_select:thursday:{event_id}")],
            [InlineKeyboardButton("שישי", callback_data=f"day_select:friday:{event_id}")],
            [InlineKeyboardButton("שבת", callback_data=f"day_select:saturday:{event_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📅 בחרו את יום השבוע:", reply_markup=reply_markup)
    elif field == "recurring":
        # Recurring status toggle flow
        context.user_data["edit_event_state"] = {
            "event_id": event_id,
            "field": field,
            "step": "awaiting_recurring_choice",
        }
        
        keyboard = [
            [InlineKeyboardButton("כן, חוזר", callback_data=f"edit_recurring:yes:{event_id}")],
            [InlineKeyboardButton("לא, חד-פעמי", callback_data=f"edit_recurring:no:{event_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        current_status = "חוזר" if event["is_recurring"] else "חד-פעמי"
        await query.edit_message_text(
            f"🔁 סטטוס נוכחי: {current_status}\n\nבחרו סטטוס חדש:",
            reply_markup=reply_markup
        )
    else:
        # Simple field edit
        context.user_data["edit_event_state"] = {
            "event_id": event_id,
            "field": field,
            "step": "awaiting_input",
        }
        
        field_prompts = {
            "title": "📝 שלחו את הכותרת החדשה:",
            "location": "📍 שלחו את המיקום החדש:",
            "reminder": "🔔 שלחו את מספר הדקות לתזכורת:",
        }
        
        prompt = field_prompts.get(field, "שנו את הערך:")
        await query.edit_message_text(prompt)


async def handle_cancel_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cancel edit button."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.pop("edit_event_state", None)
    await query.edit_message_text("✅ העריכה הושלמה. השינויים נשמרו.")


async def handle_cancel_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cancel remove button."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("✓ ביטלתי את ההסרה.")


async def _handle_edit_field_input(update: Update, context: ContextTypes.DEFAULT_TYPE, new_value: str) -> None:
    """Handle user input for editing an event field."""
    msg = update.message
    edit_state = context.user_data.get("edit_event_state", {})
    event_id = edit_state.get("event_id")
    field = edit_state.get("field")
    
    if not event_id or not field:
        await msg.reply_text("❌ שגיאה: לא הצלחתי לזהות איזה שדה לערוך.")
        return
    
    from db.queries import update_event
    event = get_event_by_id(event_id)
    
    if not event:
        await msg.reply_text("❌ האירוע לא נמצא.")
        context.user_data.pop("edit_event_state", None)
        return
    
    try:
        # ── Regular field edits ────────────────────────────────────────────────
        if field == "title":
            update_event(event_id, title=new_value)
            _sync_event_to_gcal(event_id)
            note = f"כותרת עודכנה ל: {new_value}"
        
        elif field == "location":
            update_event(event_id, location=new_value)
            _sync_event_to_gcal(event_id)
            note = f"מיקום עודכן ל: {new_value}"
        
        elif field == "reminder":
            try:
                minutes = int(new_value)
                if minutes < 0:
                    raise ValueError("חייב להיות מספר חיובי")
                update_event(event_id, remind_before_minutes=minutes)
                note = f"תזכורת עודכנה ל: {minutes} דקות לפני"
            except ValueError:
                await msg.reply_text("❌ זמן תזכורת חייב להיות מספר חיובי (בדקות).")
                return
        
        else:
            await msg.reply_text("❌ שדה לא חוקי.")
            return
        
        # Keep state alive and return to edit menu
        context.user_data["edit_event_state"] = {"event_id": event_id, "step": "choose_field"}
        text, reply_markup = _build_edit_menu(event_id, note=note)
        await msg.reply_text(text, reply_markup=reply_markup)
        
    except Exception as e:
        await msg.reply_text(f"❌ שגיאה בעדכון: {str(e)}")
        context.user_data.pop("edit_event_state", None)


async def handle_day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle day-of-week selection in datetime edit flow."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        day_name, event_id_str = parts[1], parts[2]
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע לא נמצא.")
        context.user_data.pop("edit_event_state", None)
        return
    
    # Store day name and move to next step
    edit_state = context.user_data.get("edit_event_state", {})
    temp_data = edit_state.get("temp_data", {})
    temp_data["day_name"] = day_name
    
    context.user_data["edit_event_state"]["temp_data"] = temp_data
    context.user_data["edit_event_state"]["step"] = "awaiting_start_hour"
    
    day_hebrew = {
        "sunday": "ראשון",
        "monday": "שני",
        "tuesday": "שלישי",
        "wednesday": "רביעי",
        "thursday": "חמישי",
        "friday": "שישי",
        "saturday": "שבת",
    }
    
    # Show hour picker for start time
    keyboard = []
    for hour in range(0, 24, 4):
        row = []
        for h in range(hour, min(hour + 4, 24)):
            row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"hour_sel:start:{h}:{event_id}"))
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"🕐 {day_hebrew.get(day_name, day_name)}\n\nבחרו שעת התחלה:",
        reply_markup=reply_markup
    )


async def handle_hour_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle hour selection for start/end time."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        time_type, hour_str, event_id_str = parts[1], parts[2], parts[3]
        hour = int(hour_str)
        event_id = int(event_id_str)
    except:
        return
    
    edit_state = context.user_data.get("edit_event_state", {})
    temp_data = edit_state.get("temp_data", {})
    
    # Show minute picker
    keyboard = []
    for minute in range(0, 60, 15):
        row = []
        for m in range(minute, min(minute + 15, 60), 5):
            row.append(InlineKeyboardButton(f"{m:02d}", callback_data=f"min_sel:{time_type}:{hour}:{m}:{event_id}"))
        keyboard.append(row)
    
    time_label = "התחלה" if time_type == "start" else "סיום"
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"בחרו דקות ל{time_label} ({hour:02d}:??):", reply_markup=reply_markup)


async def handle_minute_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle minute selection and store the time."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        time_type, hour_str, minute_str, event_id_str = parts[1], parts[2], parts[3], parts[4]
        hour = int(hour_str)
        minute = int(minute_str)
        event_id = int(event_id_str)
    except:
        return
    
    edit_state = context.user_data.get("edit_event_state", {})
    temp_data = edit_state.get("temp_data", {})
    
    time_str = f"{hour:02d}:{minute:02d}"
    
    if time_type == "start":
        temp_data["start_time"] = time_str
        context.user_data["edit_event_state"]["temp_data"] = temp_data
        context.user_data["edit_event_state"]["step"] = "awaiting_end_hour"
        
        # Show hour picker for end time
        keyboard = []
        for h in range(0, 24, 4):
            row = []
            for end_h in range(h, min(h + 4, 24)):
                row.append(InlineKeyboardButton(f"{end_h:02d}", callback_data=f"hour_sel:end:{end_h}:{event_id}"))
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"🕑 התחלה: {time_str}\n\nעכשיו בחרו שעת סיום:", reply_markup=reply_markup)
    
    else:  # end time
        temp_data["end_time"] = time_str
        context.user_data["edit_event_state"]["temp_data"] = temp_data
        context.user_data["edit_event_state"]["step"] = "awaiting_recurring"
        
        keyboard = [
            [InlineKeyboardButton("כן, חוזר", callback_data=f"dt_recurring_yes:{event_id}")],
            [InlineKeyboardButton("לא, חד-פעמי", callback_data=f"dt_recurring_no:{event_id}")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⏰ סיכום:\n• התחלה: {temp_data.get('start_time')}\n• סיום: {time_str}\n\n🔁 האם זה אירוע חוזר?",
            reply_markup=reply_markup
        )


async def handle_datetime_recurring_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle recurring selection in datetime edit flow."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        # Format: dt_recurring_yes:123 or dt_recurring_no:123
        action_part = parts[0]  # "dt_recurring_yes" or "dt_recurring_no"
        event_id_str = parts[1]
        recurring_str = action_part.split("_")[-1]  # Extract "yes" or "no"
        is_recurring = recurring_str == "yes"
        event_id = int(event_id_str)
    except:
        return
    
    edit_state = context.user_data.get("edit_event_state", {})
    temp_data = edit_state.get("temp_data", {})
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע לא נמצא.")
        context.user_data.pop("edit_event_state", None)
        return
    
    from db.queries import update_event
    
    try:
        day_name = temp_data.get("day_name")
        start_time = temp_data.get("start_time")
        end_time = temp_data.get("end_time")
        
        # Map day names to rrule day codes
        day_to_rrule = {
            "sunday": "SU",
            "monday": "MO",
            "tuesday": "TU",
            "wednesday": "WE",
            "thursday": "TH",
            "friday": "FR",
            "saturday": "SA",
        }
        
        if is_recurring:
            # Create recurring event with this day of week
            rrule_day = day_to_rrule.get(day_name, "MO")
            rrule_str = f"FREQ=WEEKLY;BYDAY={rrule_day};BYHOUR={start_time.split(':')[0]};BYMINUTE={start_time.split(':')[1]}"
            
            # Use today's date as rrule_start
            today = date.today().isoformat()
            
            update_event(
                event_id,
                is_recurring=True,
                rrule=rrule_str,
                rrule_start=today,
                event_datetime=None
            )
            _sync_event_to_gcal(event_id)
            text, reply_markup = _build_edit_menu(event_id, note=f"זמן עודכן כחוזר: {day_name} {start_time}-{end_time}")
            await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            # Single event - need to pick a specific date
            # For now, use next occurrence of this day
            today = date.today()
            day_to_num = {
                "sunday": 6,
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
            }
            
            target_day = day_to_num.get(day_name, 0)
            days_ahead = target_day - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            
            event_date = today + timedelta(days=days_ahead)
            full_datetime = f"{event_date.isoformat()} {start_time}"
            
            update_event(event_id, event_datetime=full_datetime, is_recurring=False, rrule=None, rrule_start=None)
            _sync_event_to_gcal(event_id)
            text, reply_markup = _build_edit_menu(event_id, note=f"זמן עודכן: {event_date.strftime('%d/%m/%Y')} {start_time}-{end_time}")
            await query.edit_message_text(text, reply_markup=reply_markup)
        
        context.user_data["edit_event_state"] = {"event_id": event_id, "step": "choose_field"}
    
    except Exception as e:
        await query.edit_message_text(f"❌ שגיאה בעדכון: {str(e)}")
        context.user_data.pop("edit_event_state", None)


async def handle_rrule_preset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle preset recurrence rule selection."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        rrule_type, event_id_str = parts[1], parts[2]
        event_id = int(event_id_str)
    except:
        return
    
    edit_state = context.user_data.get("edit_event_state", {})
    temp_data = edit_state.get("temp_data", {})
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע לא נמצא.")
        context.user_data.pop("edit_event_state", None)
        return
    
    from db.queries import update_event
    
    # Map preset types to rrule strings
    rrule_map = {
        "daily": "FREQ=DAILY",
        "weekly": "FREQ=WEEKLY",
        "weekdays": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    }
    
    rrule_str = rrule_map.get(rrule_type)
    if not rrule_str:
        await query.edit_message_text("❌ סוג חזרה לא ידוע.")
        return
    
    try:
        day = temp_data.get("day")
        
        update_event(
            event_id,
            is_recurring=True,
            rrule=rrule_str,
            rrule_start=day,
            event_datetime=None
        )
        _sync_event_to_gcal(event_id)
        context.user_data["edit_event_state"] = {"event_id": event_id, "step": "choose_field"}
        text, reply_markup = _build_edit_menu(event_id, note=f"חזרה עודכנה: {rrule_type}")
        await query.edit_message_text(text, reply_markup=reply_markup)
    
    except Exception as e:
        await query.edit_message_text(f"❌ שגיאה בעדכון: {str(e)}")
        context.user_data.pop("edit_event_state", None)


async def handle_edit_recurring_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle recurring status selection in edit flow."""
    query = update.callback_query
    await query.answer()
    
    try:
        parts = query.data.split(":")
        recurring_choice, event_id_str = parts[1], parts[2]
        is_recurring = recurring_choice == "yes"
        event_id = int(event_id_str)
    except:
        return
    
    event = get_event_by_id(event_id)
    if not event:
        await query.edit_message_text("אירוע לא נמצא.")
        context.user_data.pop("edit_event_state", None)
        return
    
    from db.queries import update_event
    
    try:
        if is_recurring:
            # If switching to recurring, need to set up rrule
            # For now, use a simple weekly recurrence on the current day
            if event.get("event_datetime"):
                event_dt = datetime.fromisoformat(event["event_datetime"])
                day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                day_name = day_names[event_dt.weekday()]
                
                day_to_rrule = {
                    "sunday": "SU",
                    "monday": "MO",
                    "tuesday": "TU",
                    "wednesday": "WE",
                    "thursday": "TH",
                    "friday": "FR",
                    "saturday": "SA",
                }
                
                rrule_day = day_to_rrule.get(day_name, "MO")
                hour = event_dt.hour
                minute = event_dt.minute
                rrule_str = f"FREQ=WEEKLY;BYDAY={rrule_day};BYHOUR={hour:02d};BYMINUTE={minute:02d}"
                start_date = date.today().isoformat()
                
                update_event(
                    event_id,
                    is_recurring=True,
                    rrule=rrule_str,
                    rrule_start=start_date,
                    event_datetime=None
                )
                _sync_event_to_gcal(event_id)
                context.user_data["edit_event_state"] = {"event_id": event_id, "step": "choose_field"}
                text, reply_markup = _build_edit_menu(event_id, note=f"עודכן לחוזר: {day_name} {hour:02d}:{minute:02d}")
                await query.edit_message_text(text, reply_markup=reply_markup)
            else:
                text, reply_markup = _build_edit_menu(event_id, note="אירוע זה כבר חוזר")
                await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            # Switch to one-time event
            update_event(
                event_id,
                is_recurring=False,
                rrule=None,
                rrule_start=None,
                event_datetime=event.get("event_datetime")
            )
            _sync_event_to_gcal(event_id)
            context.user_data["edit_event_state"] = {"event_id": event_id, "step": "choose_field"}
            text, reply_markup = _build_edit_menu(event_id, note="עודכן לאירוע חד-פעמי")
            await query.edit_message_text(text, reply_markup=reply_markup)
        
        context.user_data.pop("edit_event_state", None)
    
    except Exception as e:
        await query.edit_message_text(f"❌ שגיאה בעדכון: {str(e)}")
        context.user_data.pop("edit_event_state", None)
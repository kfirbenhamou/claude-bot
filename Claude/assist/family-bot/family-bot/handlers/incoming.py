"""
handlers/incoming.py
Handles all incoming Telegram messages.
"""

import os
from datetime import datetime, date
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
)
from handlers.intent import detect_intent
from handlers.qa import answer_event_question
from utils.formatting import confirmation_message, format_datetime_hebrew, get_emoji

load_dotenv()
GROUP_CHAT_ID = int(os.getenv("FAMILY_GROUP_CHAT_ID", "0"))
TZ = pytz.timezone(os.getenv("TIMEZONE", "Asia/Jerusalem"))


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
        [InlineKeyboardButton("הצג היום", callback_data="show_היום")]
    )
    keyboard.append(
        [InlineKeyboardButton("הצג הכל", callback_data="show_all")]
    )
    keyboard.append(
        [InlineKeyboardButton("הוסף אירוע", callback_data="add_event")]
    )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎯 בחרו אפשרות:",
        reply_markup=reply_markup
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy support for /help command."""
    await show_help_menu(update, context)


# ── Show/Display handlers ───────────────────────────────────────────────────────

async def handle_show_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button clicks for show commands."""
    query = update.callback_query
    await query.answer()
    
    command = query.data
    
    if command == "show_היום":
        await _show_today_callback(query)
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


async def _show_all(update: Update):
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    if not events:
        await update.message.reply_text("אין אירועים רשומים עדיין.")
        return
    lines = ["📅 *כל האירועים*\n"]
    for e in events:
        lines.append(_format_event_line(e, personas.get(e["persona_id"], "?")))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _show_all_callback(query):
    """Show all events via callback query."""
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    if not events:
        await query.edit_message_text("אין אירועים רשומים עדיין.")
        return
    lines = ["📅 *כל האירועים*"]
    for e in events:
        lines.append(_format_event_line(e, personas.get(e["persona_id"], "?")))
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


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
    lines = [f"📅 *אירועים עבור {name}*\n"]
    for e in events:
        lines.append(_format_event_line(e, name))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
    lines = [f"📅 *אירועים עבור {name}*"]
    for e in events:
        lines.append(_format_event_line(e, name))
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


async def _show_today(update: Update):
    from dateutil.rrule import rrulestr
    today = date.today()
    now = datetime.now(TZ)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    lines = [f"📅 *אירועים להיום — {today.strftime('%d/%m/%Y')}*\n"]
    found = False

    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                dtstart = datetime.fromisoformat(e["rrule_start"]).replace(tzinfo=TZ)
                rule = rrulestr(
                    f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{e['rrule']}",
                    ignoretz=False
                )
                day_start = TZ.localize(datetime.combine(today, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(today, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    name = personas.get(e["persona_id"], "?")
                    lines.append(_format_event_line(e, name, occ))
                    found = True
            except Exception:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == today:
                    name = personas.get(e["persona_id"], "?")
                    lines.append(_format_event_line(e, name, dt))
                    found = True
            except Exception:
                pass

    if not found:
        lines.append("אין אירועים להיום 🎉")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _show_today_callback(query):
    """Show today's events via callback query."""
    from dateutil.rrule import rrulestr
    today = date.today()
    now = datetime.now(TZ)
    personas = {p["id"]: p["name"] for p in get_all_personas()}
    events = get_all_active_events()
    lines = [f"📅 *אירועים להיום — {today.strftime('%d/%m/%Y')}*"]
    found = False

    for e in events:
        if e["is_recurring"] and e["rrule"] and e["rrule_start"]:
            try:
                dtstart = datetime.fromisoformat(e["rrule_start"]).replace(tzinfo=TZ)
                rule = rrulestr(
                    f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}\nRRULE:{e['rrule']}",
                    ignoretz=False
                )
                day_start = TZ.localize(datetime.combine(today, datetime.min.time()))
                day_end   = TZ.localize(datetime.combine(today, datetime.max.time()))
                occs = rule.between(day_start, day_end, inc=True)
                for occ in occs:
                    name = personas.get(e["persona_id"], "?")
                    lines.append(_format_event_line(e, name, occ))
                    found = True
            except Exception:
                pass
        elif e["event_datetime"]:
            try:
                dt = datetime.fromisoformat(e["event_datetime"])
                if dt.tzinfo is None:
                    dt = TZ.localize(dt)
                if dt.date() == today:
                    name = personas.get(e["persona_id"], "?")
                    lines.append(_format_event_line(e, name, dt))
                    found = True
            except Exception:
                pass

    if not found:
        lines.append("אין אירועים להיום 🎉")
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")


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
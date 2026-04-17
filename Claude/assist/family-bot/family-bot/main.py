from __future__ import annotations
"""
main.py
Entry point. Starts the Telegram bot and the scheduler.

Run with: python main.py
"""

import os
import logging
from dotenv import load_dotenv

from telegram import Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from handlers.incoming import (
    handle_start,
    handle_message,
    handle_voice_message,
    handle_help,
    handle_show,
    handle_show_callback,
    handle_daily_summary_callback,
    handle_event_action_callback,
    handle_qa_exit_callback,
    handle_event_edit_callback,
    handle_event_remove_callback,
    handle_event_reminder_callback,
    handle_event_tts_callback,
    handle_confirm_remove_callback,
    handle_add_reminder_timing_callback,
    handle_finish_reminders_callback,
    handle_edit_field_callback,
    handle_edit_recurring_callback,
    handle_cancel_edit_callback,
    handle_cancel_remove_callback,
    handle_day_select_callback,
    handle_hour_select_callback,
    handle_minute_select_callback,
    handle_datetime_recurring_callback,
    handle_rrule_preset_callback,
)
from handlers.add_event_wizard import build_add_event_handler
from services.scheduler import check_and_send_reminders, send_daily_summary

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def scheduler_job(bot: Bot):
    try:
        await check_and_send_reminders(bot)
    except Exception as e:
        logger.error(f"Scheduler error: {e}")


async def daily_summary_job(bot: Bot):
    try:
        await send_daily_summary(bot)
    except Exception as e:
        logger.error(f"Daily summary job error: {e}")


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    
    # Reminder inline actions (✅/⏭/⏰/❓)
    app.add_handler(CallbackQueryHandler(handle_event_action_callback, pattern="^evt:"))
    
    # Event management callbacks (Edit, Remove, Add Reminder)
    app.add_handler(CallbackQueryHandler(handle_event_edit_callback, pattern="^evt_edit:"))
    app.add_handler(CallbackQueryHandler(handle_edit_field_callback, pattern="^edit_field:"))
    app.add_handler(CallbackQueryHandler(handle_edit_recurring_callback, pattern="^edit_recurring:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_edit_callback, pattern="^cancel_edit$"))
    app.add_handler(CallbackQueryHandler(handle_day_select_callback, pattern="^day_select:"))
    app.add_handler(CallbackQueryHandler(handle_hour_select_callback, pattern="^hour_sel:"))
    app.add_handler(CallbackQueryHandler(handle_minute_select_callback, pattern="^min_sel:"))
    app.add_handler(CallbackQueryHandler(handle_datetime_recurring_callback, pattern="^dt_recurring_"))
    app.add_handler(CallbackQueryHandler(handle_rrule_preset_callback, pattern="^rrule_"))
    app.add_handler(CallbackQueryHandler(handle_event_remove_callback, pattern="^evt_remove:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_remove_callback, pattern="^cancel_remove$"))
    app.add_handler(CallbackQueryHandler(handle_confirm_remove_callback, pattern="^confirm_remove:"))
    app.add_handler(CallbackQueryHandler(handle_event_reminder_callback, pattern="^evt_reminder:"))
    app.add_handler(CallbackQueryHandler(handle_event_tts_callback, pattern="^evt_tts:"))
    app.add_handler(CallbackQueryHandler(handle_add_reminder_timing_callback, pattern="^add_reminder:"))
    app.add_handler(CallbackQueryHandler(handle_finish_reminders_callback, pattern="^finish_reminders:"))
    
    # Q&A conversation exit
    app.add_handler(CallbackQueryHandler(handle_qa_exit_callback, pattern="^qa_exit$"))
    
    # Help/show menu callbacks
    app.add_handler(CallbackQueryHandler(handle_daily_summary_callback, pattern="^daily_summary$"))
    app.add_handler(CallbackQueryHandler(handle_show_callback))
    app.add_handler(build_add_event_handler())
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))
    app.add_handler(MessageHandler(
        filters.VOICE,
        handle_voice_message
    ))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduler_job,
        "interval",
        minutes=1,
        args=[app.bot],
        id="reminder_check",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_summary_job,
        "cron",
        hour=8,
        minute=0,
        args=[app.bot],
        id="daily_summary",
        replace_existing=True,
    )

    # post_init runs after the event loop is already up — safe to start scheduler here
    async def post_init(application: Application) -> None:
        scheduler.start()
        logger.info("⏰ Scheduler started")

    app.post_init = post_init

    logger.info("🤖 Family bot starting...")
    logger.info("👨‍👩‍👧‍👦 Personas: כפיר, מורן, עלמה, ארבל")
    logger.info("💬 Commands: /start, עזרה, יומי, הוסף אירוע, ביטול")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
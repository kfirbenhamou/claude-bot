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
    handle_help,
    handle_show,
    handle_show_callback,
    handle_event_action_callback,
    handle_qa_exit_callback,
)
from handlers.add_event_wizard import build_add_event_handler
from services.scheduler import check_and_send_reminders

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


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    # Reminder inline actions (✅/⏭/⏰/❓)
    app.add_handler(CallbackQueryHandler(handle_event_action_callback, pattern="^evt:"))
    # Q&A conversation exit
    app.add_handler(CallbackQueryHandler(handle_qa_exit_callback, pattern="^qa_exit$"))
    # Help/show menu callbacks
    app.add_handler(CallbackQueryHandler(handle_show_callback))
    app.add_handler(build_add_event_handler())
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
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

    # post_init runs after the event loop is already up — safe to start scheduler here
    async def post_init(application: Application) -> None:
        scheduler.start()
        logger.info("⏰ Scheduler started")

    app.post_init = post_init

    logger.info("🤖 Family bot starting...")
    logger.info("👨‍👩‍👧‍👦 Personas: כפיר, מורן, עלמה, ארבל")
    logger.info("💬 Commands: /start, עזרה, הוסף אירוע, ביטול")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
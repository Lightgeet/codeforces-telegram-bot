from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from codeforces import ContestMonitor
from database import Database, UserPreference

load_dotenv(Path(__file__).with_name(".env"))

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DIVISIONS = {
    "div1": "Div. 1",
    "div2": "Div. 2",
    "div3": "Div. 3",
    "div4": "Div. 4",
    "all": "All Divisions",
}

DIVISION_QUESTION = (
    "Which Codeforces division do you want to receive contest notifications for?"
)


def _database(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return cast(Database, context.application.bot_data["database"])


def _division_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(label, callback_data=f"division:{key}")
        for key, label in DIVISIONS.items()
    ]
    return InlineKeyboardMarkup([[button] for button in buttons])


def _format_preference(preference: UserPreference) -> str:
    notification_state = (
        "enabled" if preference.notifications_enabled else "disabled"
    )
    return (
        f"Your selected division: {preference.selected_division}\n"
        f"Notifications are {notification_state}."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    preference = await asyncio.to_thread(_database(context).get_user, user.id)
    if preference is None or preference.selected_division is None:
        await message.reply_text(DIVISION_QUESTION, reply_markup=_division_keyboard())
        return

    await message.reply_text(
        f"Welcome back!\n{_format_preference(preference)}\n"
        "Use /change to choose a different division or /resume to enable notifications."
    )


async def change_division(
    update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(DIVISION_QUESTION, reply_markup=_division_keyboard())


async def select_division(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        return

    await query.answer()
    callback_data = query.data or ""
    key = callback_data.removeprefix("division:")
    selected_division = DIVISIONS.get(key)
    if selected_division is None:
        await query.edit_message_text("That division selection is no longer valid. Use /change to try again.")
        return

    await asyncio.to_thread(
        _database(context).save_preference, user.id, selected_division
    )
    if selected_division == "All Divisions":
        confirmation = "I will notify you about every new official Codeforces contest."
    else:
        confirmation = (
            f"I will notify you whenever a new {selected_division} "
            "Codeforces contest is announced."
        )

    await query.edit_message_text(
        f"Your division preference has been saved: {selected_division}.\n\n"
        f"{confirmation}\n\n"
        "Use /change to change your division."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    preference = await asyncio.to_thread(_database(context).get_user, user.id)
    if preference is None or preference.selected_division is None:
        await message.reply_text("No division is saved yet. Use /start to choose one.")
        return
    await message.reply_text(_format_preference(preference))


async def stop_notifications(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    changed = await asyncio.to_thread(
        _database(context).set_notifications_enabled, user.id, False
    )
    if changed:
        await message.reply_text(
            "Notifications are disabled. Your saved division has not been deleted. "
            "Use /resume to enable notifications again."
        )
    else:
        await message.reply_text("No division is saved yet. Use /start to choose one.")


async def resume_notifications(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    changed = await asyncio.to_thread(
        _database(context).set_notifications_enabled, user.id, True
    )
    if changed:
        preference = await asyncio.to_thread(_database(context).get_user, user.id)
        if preference is not None:
            await message.reply_text(
                f"Notifications are enabled for {preference.selected_division}."
            )
    else:
        await message.reply_text("No division is saved yet. Use /start to choose one.")


async def help_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            "Available commands:\n"
            "/start - Start the bot or view your saved settings\n"
            "/change - Change your Codeforces division\n"
            "/status - View your division and notification status\n"
            "/stop - Disable notifications without deleting your division\n"
            "/resume - Resume notifications for your saved division\n"
            "/help - Show this help message"
        )


async def echo(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is not None and message.text is not None:
        await message.reply_text(f"You said: {message.text}")


async def post_init(application: Application) -> None:
    database = cast(Database, application.bot_data["database"])
    await asyncio.to_thread(database.initialize)

    monitor = ContestMonitor(database, application.bot)
    application.bot_data["contest_monitor"] = monitor
    await monitor.poll_once()
    application.bot_data["contest_monitor_task"] = asyncio.create_task(
        monitor.run(), name="codeforces-contest-monitor"
    )


async def post_shutdown(application: Application) -> None:
    task = application.bot_data.get("contest_monitor_task")
    if isinstance(task, asyncio.Task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    monitor = application.bot_data.get("contest_monitor")
    if isinstance(monitor, ContestMonitor):
        await monitor.close()


def build_application(token: str, database: Database) -> Application:
    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["database"] = database

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("change", change_division))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("stop", stop_notifications))
    application.add_handler(CommandHandler("resume", resume_notifications))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(select_division, pattern=r"^division:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    return application


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to the .env file or environment."
        )

    database_path = Path(
        os.environ.get("BOT_DATABASE_PATH", Path(__file__).with_name("bot.db"))
    )
    application = build_application(token, Database(database_path))
    logger.info("Starting the Codeforces contest notification bot.")
    application.run_polling()


if __name__ == "__main__":
    main()

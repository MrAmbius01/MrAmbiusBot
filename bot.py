import logging
import sqlite3
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.error import TelegramError, NetworkError, Conflict
import schedule
import time
import asyncio
import random
import logging.handlers

# Set up logging with RotatingFileHandler
log_file = "bot.log"
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.handlers.RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN not found in .env")
    raise ValueError("BOT_TOKEN not found in .env")
logger.info("Loaded BOT_TOKEN from environment variables")

# Initialize SQLite database
def init_db():
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            referred_by INTEGER
        )''')
        conn.commit()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        conn.close()

init_db()

# Get all user IDs for broadcasting
def get_all_user_ids():
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        user_ids = [row[0] for row in c.fetchall()]
        conn.close()
        logger.info(f"Retrieved {len(user_ids)} user IDs for broadcast")
        return user_ids
    except sqlite3.Error as e:
        logger.error(f"Error retrieving user IDs: {e}")
        return []

# Register or update user
def register_user(user_id: int, username: str, referred_by: int = None):
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (user_id, username, balance, referred_by) VALUES (?, ?, ?, ?)",
                  (user_id, username, 0.0, referred_by))
        conn.commit()
        logger.info(f"Registered user {user_id} ({username}), referred by {referred_by}")
    except sqlite3.Error as e:
        logger.error(f"Register user error: {e}")
    finally:
        conn.close()

# Add referral earnings
def add_referral(user_id: int):
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if result and result[0]:
            referred_by = result[0]
            c.execute("UPDATE users SET balance = balance + 10.0 WHERE user_id = ?", (referred_by,))
            conn.commit()
            logger.info(f"Added $10 to user {referred_by} for referring {user_id}")
    except sqlite3.Error as e:
        logger.error(f"Add referral error: {e}")
    finally:
        conn.close()

# Get user balance
def get_balance(user_id: int) -> float:
    try:
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        return result[0] if result else 0.0
    except sqlite3.Error as e:
        logger.error(f"Get balance error: {e}")
        return 0.0
    finally:
        conn.close()

# Main menu keyboard
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("FREE BETS", callback_data='free_bets')],
        [InlineKeyboardButton("EARN MONEY FOR FREE", callback_data='earn_money')],
        [InlineKeyboardButton("Official Channel", callback_data='official_channel')],
        [InlineKeyboardButton("How To Use This Bot ?", callback_data='how_to_use')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Sample betting tips for broadcast
def get_daily_betting_tip():
    tips = [
        "⚽ Over 2.5 goals in Manchester United vs. Arsenal (Odds: 2.10)",
        "🏀 Lakers to win against Celtics (Odds: 1.85)",
        "🎾 Nadal to win in straight sets (Odds: 3.50)",
        "⚽ Both teams to score in Liverpool vs. Chelsea (Odds: 1.75)",
        "🏈 Chiefs to cover the spread (-6.5) vs. Raiders (Odds: 2.00)"
    ]
    return random.choice(tips)

# Broadcast message to all users
async def broadcast_message(context: ContextTypes.DEFAULT_TYPE):
    try:
        user_ids = get_all_user_ids()
        if not user_ids:
            logger.info("No users to broadcast to")
            return

        message = (
            "🌟 MR AMBIUS PREDICTIONS Daily Update! 🌟\n\n"
            f"Today's Betting Tip: {get_daily_betting_tip()}\n\n"
            "Earn $10 per friend invited! Use /balance to check your earnings.\n"
            "Join our channel for more tips: https://t.me/+tJ5HBX3pXA5MWVk\n"
            "Contact @Honorable_Hunter_5G for questions."
        )
        success_count = 0
        for user_id in user_ids:
            for attempt in range(3):  # Retry up to 3 times
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        reply_markup=get_main_menu()
                    )
                    success_count += 1
                    logger.info(f"Sent broadcast to user {user_id}")
                    await asyncio.sleep(0.1)  # Respect rate limits
                    break
                except NetworkError as e:
                    logger.warning(f"Network error for user {user_id}, attempt {attempt + 1}: {e}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                except TelegramError as e:
                    logger.error(f"Failed to send broadcast to user {user_id}: {e}")
                    break
        logger.info(f"Broadcast completed: {success_count}/{len(user_ids)} users")
    except Exception as e:
        logger.error(f"Broadcast error: {e}")

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user = update.effective_user
        user_id = user.id
        username = user.username or user.first_name or "User"
        logger.info(f"Processing /start for user {user_id} ({username})")

        # Register user
        referred_by = None
        if context.args:
            try:
                referred_by = int(context.args[0])
                if referred_by != user_id:
                    register_user(user_id, username, referred_by)
                    add_referral(user_id)
                else:
                    logger.warning(f"User {user_id} tried to self-refer")
                    register_user(user_id, username)
            except ValueError:
                logger.warning(f"Invalid referral code from {user_id}: {context.args[0]}")
                register_user(user_id, username)
        else:
            register_user(user_id, username)

        # Send welcome message
        await update.message.reply_text(
            f"Welcome, {username}!\n\n"
            "Join MR AMBIUS PREDICTIONS for betting tips (odds 10 to 100+) and passive income.\n\n"
            f"Earn $10 per friend invited! Your referral link: t.me/{context.bot.username}?start={user_id}\n\n"
            f"Join our channel: https://t.me/+tJ5HBX3pXA5MWVk\n"
            "Contact @Honorable_Hunter_5G for questions.\n\n"
            "Choose an option below ✨",
            reply_markup=get_main_menu()
        )
        logger.info(f"User {user_id} started the bot")
    except NetworkError as e:
        logger.error(f"Network error in start handler: {e}")
        await update.message.reply_text("Network issue. Please try again later.")
    except TelegramError as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text("Sorry, an error occurred. Please try again later.")

# Help command handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        logger.info(f"Processing /help for user {user_id}")
        await update.message.reply_text(
            "How to use MR AMBIUS PREDICTIONS bot:\n"
            "- /start: Show the main menu\n"
            "- /help: See this help message\n"
            "- /balance: Check your referral earnings\n"
            "- Use buttons to explore features\n"
            "- Share your referral link to earn $10 per friend!\n"
            "Contact @Honorable_Hunter_5G for questions.",
            reply_markup=get_main_menu()
        )
        logger.info(f"User {user_id} used /help")
    except NetworkError as e:
        logger.error(f"Network error in help handler: {e}")
        await update.message.reply_text("Network issue. Please try again later.")
    except TelegramError as e:
        logger.error(f"Error in help handler: {e}")
        await update.message.reply_text("Sorry, an error occurred. Please try again.")

# Balance command handler
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        logger.info(f"Processing /balance for user {user_id}")
        balance = get_balance(user_id)
        await update.message.reply_text(
            f"Your current balance: ${balance:.2f}\n"
            "Earn more by sharing your referral link!\n"
            "Contact @Honorable_Hunter_5G for questions.",
            reply_markup=get_main_menu()
        )
        logger.info(f"User {user_id} checked balance: ${balance:.2f}")
    except NetworkError as e:
        logger.error(f"Network error in balance handler: {e}")
        await update.message.reply_text("Network issue. Please try again later.")
    except TelegramError as e:
        logger.error(f"Error in balance handler: {e}")
        await update.message.reply_text("Sorry, an error occurred. Please try again.")

# Button callback handler
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()
        logger.info(f"Processing button {query.data} for user {user_id}")

        responses = {
            'free_bets': "Free bets with high odds (10 to 100+) coming soon! Check our channel: https://t.me/+tJ5HBX3pXA5MWVk",
            'earn_money': (
                f"Earn $10 per friend you invite!\n"
                f"Your referral link: t.me/{context.bot.username}?start={user_id}\n"
                "Share it with friends to start earning!"
            ),
            'official_channel': "Join our official channel: https://t.me/+tJ5HBX3pXA5MWVk",
            'how_to_use': (
                "How to use this bot:\n"
                "- Click buttons to explore features\n"
                "- Use /start to return to the main menu\n"
                "- Use /balance to check your earnings\n"
                "- Share your referral link to earn $10 per friend!\n"
                "Contact @Honorable_Hunter_5G for questions."
            )
        }

        keyboard = [[InlineKeyboardButton("Back to Menu", callback_data='main_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query.data == 'main_menu':
            await query.edit_message_text(
                "Welcome back to the main menu! Choose an option:",
                reply_markup=get_main_menu()
            )
        else:
            await query.edit_message_text(
                text=responses.get(query.data, "Invalid option selected"),
                reply_markup=reply_markup
            )
        logger.info(f"User {user_id} clicked button: {query.data}")
    except NetworkError as e:
        logger.error(f"Network error in button handler: {e}")
        await query.message.reply_text("Network issue. Please try again later.")
    except TelegramError as e:
        logger.error(f"Error in button handler: {e}")
        await query.message.reply_text("Sorry, an error occurred. Please try again.")

# Handle unknown commands
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user_id = update.effective_user.id
        logger.info(f"Processing unknown command {update.message.text} for user {user_id}")
        await update.message.reply_text(
            "Sorry, I didn't understand that command. Use /help for available commands.",
            reply_markup=get_main_menu()
        )
        logger.info(f"User {user_id} sent unknown command: {update.message.text}")
    except NetworkError as e:
        logger.error(f"Network error in unknown handler: {e}")
        await update.message.reply_text("Network issue. Please try again later.")
    except TelegramError as e:
        logger.error(f"Error in unknown handler: {e}")
        await update.message.reply_text("Sorry, an error occurred. Please try again.")

# Schedule daily broadcast
def schedule_broadcast(app: Application):
    schedule.every().day.at("09:00").do(lambda: asyncio.run_coroutine_threadsafe(broadcast_message(app), app.loop))
    logger.info("Scheduled daily broadcast at 09:00")
    while True:
        schedule.run_pending()
        time.sleep(60)

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error: {context.error}")
    if isinstance(context.error, NetworkError):
        logger.error(f"Network error: {context.error}. Retrying may help.")
        if update and update.message:
            await update.message.reply_text("Network issue. Please try again later.")
    elif isinstance(context.error, Conflict):
        logger.error("Conflict error: Another instance of the bot is running. Please stop other instances.")
        if update and update.message:
            await update.message.reply_text("Bot is already running elsewhere. Please try again later or contact @Honorable_Hunter_5G.")
    else:
        if update and update.message:
            await update.message.reply_text("An error occurred. Please try again or contact @Honorable_Hunter_5G.")

def main() -> None:
    try:
        logger.info("Starting bot application")
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("balance", balance))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.COMMAND, unknown))
        application.add_error_handler(error_handler)
        logger.info("Handlers registered: start, help, balance, button, unknown, error")

        # Start the broadcast scheduler in a separate thread
        import threading
        threading.Thread(target=schedule_broadcast, args=(application,), daemon=True).start()

        application.run_polling(allowed_updates=Update.ALL_TYPES, timeout=30)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == '__main__':
    main()
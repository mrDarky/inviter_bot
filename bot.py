import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatMemberUpdated
from dotenv import load_dotenv
from database import Database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/bot.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it in .env file.")

# Initialize bot and dispatcher
bot = None
dp = None
db = Database(DATABASE_PATH)

# Scheduler for scheduled messages
scheduler = AsyncIOScheduler()


def init_bot():
    """Initialize bot and dispatcher"""
    global bot, dp
    if bot is None:
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    user = message.from_user
    
    # Add user to database
    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    # Log action
    await db.log_action(user.id, "start", "User started the bot")
    
    await message.answer(
        f"👋 Welcome, {user.first_name}!\n\n"
        "I'm an inviter bot. I can help you manage channel members and send messages."
    )


@dp.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def on_user_join(event: ChatMemberUpdated):
    """Handle user joining a channel"""
    user = event.new_chat_member.user
    
    # Add user to database
    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    # Log action
    await db.log_action(user.id, "join_channel", f"Joined channel: {event.chat.title}")
    
    logger.info(f"User {user.id} ({user.username}) joined channel {event.chat.title}")
    
    # Send welcome message to user if possible
    try:
        await bot.send_message(
            user.id,
            f"👋 Welcome to {event.chat.title}!\n\n"
            "Thank you for joining!"
        )
    except Exception as e:
        logger.warning(f"Could not send welcome message to user {user.id}: {e}")


@dp.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated):
    """Handle user leaving a channel"""
    user = event.old_chat_member.user
    
    # Log action
    await db.log_action(user.id, "leave_channel", f"Left channel: {event.chat.title}")
    
    logger.info(f"User {user.id} ({user.username}) left channel {event.chat.title}")


async def send_message_to_users(user_ids: list, text: str, parse_mode: str = None):
    """Send message to multiple users"""
    success_count = 0
    fail_count = 0
    
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text, parse_mode=parse_mode)
            success_count += 1
            await db.log_action(user_id, "received_message", "Message sent via admin panel")
            await asyncio.sleep(0.05)  # Rate limiting
        except Exception as e:
            logger.warning(f"Could not send message to user {user_id}: {e}")
            fail_count += 1
    
    logger.info(f"Message sent to {success_count} users, failed for {fail_count} users")
    return success_count, fail_count


async def check_scheduled_messages():
    """Check and send scheduled messages"""
    try:
        messages = await db.get_pending_scheduled_messages()
        
        for msg in messages:
            # Get all active users
            users = await db.get_users()
            user_ids = [user['user_id'] for user in users if not user['is_banned']]
            
            # Send message
            text = msg['html_text'] if msg['html_text'] else msg['text']
            parse_mode = "HTML" if msg['html_text'] else None
            
            await send_message_to_users(user_ids, text, parse_mode)
            
            # Mark as sent
            await db.mark_scheduled_message_sent(msg['id'])
            
            logger.info(f"Scheduled message {msg['id']} sent")
    except Exception as e:
        logger.error(f"Error checking scheduled messages: {e}")


async def send_static_messages():
    """Send static messages to users based on their join day"""
    try:
        users = await db.get_users()
        static_messages = await db.get_static_messages()
        
        for user in users:
            if user['is_banned']:
                continue
            
            # Calculate days since join
            join_date = datetime.fromisoformat(user['join_date'])
            days_since_join = (datetime.now() - join_date).days
            
            # Find matching static message
            for msg in static_messages:
                if msg['is_active'] and msg['day_number'] == days_since_join:
                    text = msg['html_text'] if msg['html_text'] else msg['text']
                    parse_mode = "HTML" if msg['html_text'] else None
                    
                    try:
                        await bot.send_message(user['user_id'], text, parse_mode=parse_mode)
                        await db.log_action(user['user_id'], "received_static_message", f"Day {days_since_join} message")
                        logger.info(f"Static message sent to user {user['user_id']} for day {days_since_join}")
                    except Exception as e:
                        logger.warning(f"Could not send static message to user {user['user_id']}: {e}")
    except Exception as e:
        logger.error(f"Error sending static messages: {e}")


async def main():
    """Main function"""
    # Initialize bot
    init_bot()
    
    # Initialize database
    await db.init_db()
    logger.info("Database initialized")
    
    # Setup scheduler
    scheduler.add_job(check_scheduled_messages, 'interval', minutes=1)
    scheduler.add_job(send_static_messages, 'cron', hour=9, minute=0)  # Daily at 9 AM
    scheduler.start()
    logger.info("Scheduler started")
    
    # Start bot
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

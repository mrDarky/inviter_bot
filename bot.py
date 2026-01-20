import asyncio
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatMemberUpdated, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from database import Database
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import json

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = None
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/bot.db")

# Initialize bot and dispatcher
bot = None
dp = Dispatcher()  # Create dispatcher at module level
db = Database(DATABASE_PATH)

# Scheduler for scheduled messages
scheduler = AsyncIOScheduler()


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler to save logs to database"""
    def emit(self, record):
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.async_emit(record))
        except Exception:
            pass
    
    async def async_emit(self, record):
        try:
            await db.add_log(
                level=record.levelname,
                source="bot",
                message=record.getMessage(),
                details=str(record.__dict__)
            )
        except Exception:
            pass


# Add database handler to logger
db_handler = DatabaseLogHandler()
db_handler.setLevel(logging.INFO)
logger.addHandler(db_handler)


async def get_bot_token():
    """Get bot token from DB or environment"""
    token = await db.get_setting('bot_token')
    if not token:
        token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN not found in database or environment variables")
    return token


def init_bot():
    """Initialize bot instance only (dispatcher already created at module level).
    
    Returns:
        bool: True if bot was initialized successfully with env token,
              False if bot token needs to be retrieved from database.
              Caller should handle database token retrieval in async context.
    """
    global bot, BOT_TOKEN
    if bot is None:
        # Try to get token from env for sync initialization
        BOT_TOKEN = os.getenv("BOT_TOKEN")
        
        if not BOT_TOKEN:
            # If no env token, we need async context to get from DB
            # This will be handled by the caller
            return False
        
        bot = Bot(token=BOT_TOKEN)
        return True
    return True


async def build_main_menu():
    """Build main menu from database"""
    try:
        menu_items = await db.get_bot_menu()
        if not menu_items:
            return None
        
        buttons = []
        for item in menu_items:
            button = KeyboardButton(text=item['button_name'])
            buttons.append([button])
        
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    except Exception as e:
        logger.error(f"Error building main menu: {e}")
        return None


async def handle_menu_action(message: types.Message, menu_item: dict):
    """Handle menu item action"""
    try:
        if menu_item['button_type'] == 'link':
            await message.answer(f"Open: {menu_item['action_value']}")
        elif menu_item['button_type'] == 'text':
            await message.answer(menu_item['action_value'])
        elif menu_item['button_type'] == 'inline':
            # Parse inline buttons from JSON with validation
            try:
                inline_buttons_data = json.loads(menu_item['inline_buttons'])
                if not isinstance(inline_buttons_data, list):
                    raise ValueError("inline_buttons must be a list")
                
                buttons = []
                for btn_data in inline_buttons_data:
                    if not isinstance(btn_data, dict):
                        continue
                    if 'text' not in btn_data or 'url' not in btn_data:
                        continue
                    
                    button = InlineKeyboardButton(
                        text=str(btn_data['text'])[:100],  # Limit text length
                        url=str(btn_data['url'])[:500]  # Limit URL length
                    )
                    buttons.append([button])
                
                if buttons:
                    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                    await message.answer("Choose an option:", reply_markup=keyboard)
                else:
                    await message.answer("Invalid menu configuration")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error parsing inline buttons: {e}")
                await message.answer("Error loading menu options")
    except Exception as e:
        logger.error(f"Error handling menu action: {e}")
        await message.answer("Error processing menu action")


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
    logger.info(f"User {user.id} started the bot")
    
    # Build main menu
    menu = await build_main_menu()
    
    await message.answer(
        f"👋 Welcome, {user.first_name}!\n\n"
        "I'm an inviter bot. I can help you manage channel members and send messages.",
        reply_markup=menu
    )


@dp.message(F.text)
async def handle_menu_message(message: types.Message):
    """Handle menu button clicks"""
    try:
        menu_items = await db.get_bot_menu()
        for item in menu_items:
            if item['button_name'] == message.text:
                await handle_menu_action(message, item)
                return
    except Exception as e:
        logger.error(f"Error handling menu message: {e}")


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


async def parse_buttons_config(buttons_config: str):
    """Parse button configuration string into InlineKeyboardMarkup
    Format: 
    some text 1 | url1, some text2 | url2
    some text 3 | url3
    (1 row per line, separated by commas for columns)
    """
    if not buttons_config or not buttons_config.strip():
        return None
    
    try:
        rows = []
        for line in buttons_config.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Split by comma for multiple buttons in one row
            buttons_in_row = []
            for button_str in line.split(','):
                button_str = button_str.strip()
                if '|' in button_str:
                    parts = button_str.split('|', 1)
                    text = parts[0].strip()
                    url = parts[1].strip()
                    if text and url:
                        buttons_in_row.append(InlineKeyboardButton(text=text, url=url))
            
            if buttons_in_row:
                rows.append(buttons_in_row)
        
        if rows:
            return InlineKeyboardMarkup(inline_keyboard=rows)
        return None
    except Exception as e:
        logger.error(f"Error parsing buttons config: {e}")
        return None


async def send_static_messages():
    """Send static messages to users based on their join day and time"""
    try:
        users = await db.get_users()
        static_messages = await db.get_static_messages()
        current_time = datetime.now()
        
        for user in users:
            if user['is_banned']:
                continue
            
            # Calculate days since join
            join_date = datetime.fromisoformat(user['join_date'])
            days_since_join = (current_time - join_date).days
            
            # Find matching static messages for this day
            for msg in static_messages:
                if not msg['is_active'] or msg['day_number'] != days_since_join:
                    continue
                
                # Check if message was already sent to this user
                already_sent = await db.is_static_message_sent(user['user_id'], msg['id'])
                if already_sent:
                    continue
                
                # Get time configuration
                send_time = msg.get('send_time')
                additional_minutes = msg.get('additional_minutes', 0) or 0
                
                # Determine if it's time to send the message
                should_send = False
                
                if days_since_join == 0:
                    # Day 0: Send based on join time + additional minutes
                    time_to_send = join_date + timedelta(minutes=additional_minutes)
                    should_send = current_time >= time_to_send
                else:
                    # Day 1+: Send at specific time (or default 09:00) + additional minutes
                    if not send_time:
                        send_time = "09:00"  # Default send time
                    
                    # Parse send_time (HH:MM format)
                    try:
                        hour, minute = map(int, send_time.split(':'))
                        target_date = join_date.date() + timedelta(days=days_since_join)
                        time_to_send = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
                        time_to_send += timedelta(minutes=additional_minutes)
                        
                        # Check if current time is within sending window (current time >= target time and < target time + 5 minutes)
                        should_send = time_to_send <= current_time < time_to_send + timedelta(minutes=5)
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"Invalid send_time format for message {msg['id']}: {send_time}, error: {e}")
                        continue
                
                if not should_send:
                    continue
                
                # Prepare message content
                text = msg['html_text'] if msg['html_text'] else msg['text']
                parse_mode = "HTML" if msg['html_text'] else None
                media_type = msg.get('media_type', 'text')
                media_file_id = msg.get('media_file_id')
                buttons_config = msg.get('buttons_config')
                
                # Parse buttons if configured
                reply_markup = await parse_buttons_config(buttons_config) if buttons_config else None
                
                try:
                    # Send based on media type
                    if media_type == 'text' or not media_file_id:
                        await bot.send_message(
                            user['user_id'], 
                            text, 
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'photo':
                        await bot.send_photo(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'video':
                        await bot.send_video(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'video_note':
                        # Video notes don't support captions or buttons, send text separately
                        await bot.send_video_note(user['user_id'], media_file_id)
                        if text:
                            await bot.send_message(
                                user['user_id'],
                                text,
                                parse_mode=parse_mode,
                                reply_markup=reply_markup
                            )
                    elif media_type == 'animation':
                        await bot.send_animation(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'document':
                        await bot.send_document(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'audio':
                        await bot.send_audio(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'voice':
                        # Voice messages don't support captions, send text separately
                        await bot.send_voice(user['user_id'], media_file_id)
                        if text:
                            await bot.send_message(
                                user['user_id'],
                                text,
                                parse_mode=parse_mode,
                                reply_markup=reply_markup
                            )
                    else:
                        # Fallback to text
                        await bot.send_message(
                            user['user_id'],
                            text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    
                    # Mark message as sent
                    await db.mark_static_message_sent(user['user_id'], msg['id'])
                    await db.log_action(user['user_id'], "received_static_message", f"Day {days_since_join} message (ID: {msg['id']})")
                    logger.info(f"Static message {msg['id']} sent to user {user['user_id']} for day {days_since_join}")
                except Exception as e:
                    logger.warning(f"Could not send static message to user {user['user_id']}: {e}")
    except Exception as e:
        logger.error(f"Error sending static messages: {e}")


async def main():
    """Main function"""
    global bot, BOT_TOKEN
    
    # Initialize database first
    await db.init_db()
    logger.info("Database initialized")
    
    # Get bot token from DB or env
    try:
        BOT_TOKEN = await get_bot_token()
        logger.info("Bot token retrieved")
    except Exception as e:
        logger.error(f"Failed to get bot token: {e}")
        raise
    
    # Initialize bot with token
    bot = Bot(token=BOT_TOKEN)
    
    # Handlers are already registered via decorators at module level
    
    # Setup scheduler
    scheduler.add_job(check_scheduled_messages, 'interval', minutes=1)
    scheduler.add_job(send_static_messages, 'interval', minutes=1)  # Check every minute for time-based messages
    scheduler.start()
    logger.info("Scheduler started")
    
    # Start bot
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

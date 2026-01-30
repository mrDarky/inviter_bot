import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatMemberUpdated, ChatJoinRequest, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from database import Database
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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


def normalize_media_type(media_type):
    """
    Normalize media type value to string format.
    Handles legacy numeric media type values:
    0 or '0' -> 'text'
    1 or '1' -> 'photo'
    2 or '2' -> 'video'
    3 or '3' -> 'document'
    """
    if media_type is None:
        return 'text'
    
    # Convert to string if it's a number
    media_type_str = str(media_type)
    
    # Map numeric values to media type strings
    numeric_mapping = {
        '0': 'text',
        '1': 'photo',
        '2': 'video',
        '3': 'document',
        '4': 'animation',
        '5': 'audio',
        '6': 'voice',
        '7': 'video_note'
    }
    
    # If it's a numeric value, convert it
    if media_type_str in numeric_mapping:
        return numeric_mapping[media_type_str]
    
    # Otherwise return as-is (already a proper string)
    return media_type_str


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
    
    # Extract invite code from deep link if present
    # Format: /start CODE or /start (no code)
    invite_code = None
    if message.text and len(message.text.split()) > 1:
        invite_code = message.text.split()[1]
        # Validate invite code exists and is active
        invite_link = await db.get_invite_link_by_code(invite_code)
        if not invite_link or not invite_link.get('is_active'):
            logger.warning(f"User {user.id} tried to use invalid or inactive invite code: {invite_code}")
            invite_code = None
    
    # Add user to database
    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        invite_code=invite_code
    )
    
    # Log action
    action_data = f"Invite code: {invite_code}" if invite_code else "No invite code"
    await db.log_action(user.id, "start", action_data)
    logger.info(f"User {user.id} started the bot with invite code: {invite_code}")
    
    # Check if onboarding questions are configured
    questions = await db.get_user_questions(active_only=True)
    auto_approve_mode = await db.get_setting('auto_approve_mode')
    
    # Only start onboarding if mode is 'after_messages' and questions exist
    if questions and auto_approve_mode == 'after_messages':
        # Start onboarding process
        await message.answer("Welcome! Please answer a few questions to get started.")
        await start_user_onboarding(user.id)
    else:
        # Build main menu
        menu = await build_main_menu()
        
        await message.answer(
            "Use the menu below to interact with the bot.",
            reply_markup=menu
        )


@dp.message(F.text)
async def handle_text_message(message: types.Message):
    """Handle text messages - both menu clicks and question answers"""
    try:
        user_id = message.from_user.id
        
        # Check if user is in onboarding state waiting for text answer
        onboarding_state = await db.get_user_onboarding_state(user_id)
        
        if onboarding_state and onboarding_state['current_question_id']:
            question_id = onboarding_state['current_question_id']
            question = await db.get_user_question(question_id)
            
            if question and question['question_type'] == 'text':
                # Store the answer
                await db.add_user_answer(user_id, question_id, message.text)
                await db.log_action(user_id, "answered_question", f"Question ID: {question_id}")
                
                await message.answer("✓ Answer recorded")
                
                # Send next question or complete onboarding
                await send_next_question(user_id, question_id)
                return
        
        # If not in onboarding, check for menu items
        menu_items = await db.get_bot_menu()
        for item in menu_items:
            if item['button_name'] == message.text:
                await handle_menu_action(message, item)
                return
                
    except Exception as e:
        logger.error(f"Error handling text message: {e}")


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


@dp.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def on_user_leave(event: ChatMemberUpdated):
    """Handle user leaving a channel"""
    user = event.old_chat_member.user
    
    # Log action
    await db.log_action(user.id, "leave_channel", f"Left channel: {event.chat.title}")
    
    logger.info(f"User {user.id} ({user.username}) left channel {event.chat.title}")


@dp.chat_join_request()
async def on_join_request(update: ChatJoinRequest):
    """Handle join request to a channel"""
    user = update.from_user
    chat = update.chat
    
    # Store join request in database
    await db.add_join_request(
        user_id=user.id,
        chat_id=chat.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    # Log action
    await db.log_action(user.id, "join_request", f"Join request for channel: {chat.title}")
    
    logger.info(f"User {user.id} ({user.username}) requested to join channel {chat.title}")
    
    # Check auto-approve mode
    auto_approve_mode = await db.get_setting('auto_approve_mode')
    
    if auto_approve_mode == 'immediate':
        # Auto-approve immediately
        try:
            await bot.approve_chat_join_request(chat.id, user.id)
            # Get the join request we just created
            join_requests = await db.get_join_requests_by_user(user.id)
            pending_req = next((req for req in join_requests if int(req['chat_id']) == chat.id and req['status'] == 'pending'), None)
            if pending_req:
                await db.approve_join_request(pending_req['id'])
            await db.log_action(user.id, "auto_approved", "Immediate approval")
            logger.info(f"User {user.id} auto-approved immediately")
        except Exception as e:
            logger.warning(f"Could not auto-approve user {user.id} immediately: {e}")
    elif auto_approve_mode == 'after_messages':
        # Auto-approve will happen after onboarding is complete
        # Send initial message to user
        try:
            await bot.send_message(
                user.id,
                "Thank you for your interest! Please complete the questions below to proceed."
            )
            # Start onboarding if questions exist
            questions = await db.get_user_questions(active_only=True)
            if questions:
                await start_user_onboarding(user.id)
        except Exception as e:
            logger.warning(f"Could not send onboarding message to user {user.id}: {e}")


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
        current_time = datetime.utcnow()  # Use UTC time explicitly
        
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
                        from datetime import time as dt_time
                        time_to_send = datetime.combine(target_date, dt_time(hour, minute))
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
                media_type = normalize_media_type(msg.get('media_type', 'text'))
                media_file_id = msg.get('media_file_id')
                buttons_config = msg.get('buttons_config')
                
                # Create markup with buttons and viewed button
                reply_markup = await create_message_markup(msg['id'], buttons_config)
                
                try:
                    # Send based on media type
                    if media_type == 'text':
                        await bot.send_message(
                            user['user_id'], 
                            text, 
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'photo' and media_file_id:
                        await bot.send_photo(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'video' and media_file_id:
                        await bot.send_video(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'video_note' and media_file_id:
                        # Video notes don't support captions or buttons, send text separately
                        await bot.send_video_note(user['user_id'], media_file_id)
                        if text:
                            await bot.send_message(
                                user['user_id'],
                                text,
                                parse_mode=parse_mode,
                                reply_markup=reply_markup
                            )
                    elif media_type == 'animation' and media_file_id:
                        await bot.send_animation(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'document' and media_file_id:
                        await bot.send_document(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'audio' and media_file_id:
                        await bot.send_audio(
                            user['user_id'],
                            media_file_id,
                            caption=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup
                        )
                    elif media_type == 'voice' and media_file_id:
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
                        # Fallback to text if media type is not recognized or media file is missing
                        if media_type != 'text' and not media_file_id:
                            logger.warning(f"Media type '{media_type}' specified but no media_file_id provided for message {msg['id']} to user {user['user_id']}. Falling back to text only.")
                        elif media_type not in ['text', 'photo', 'video', 'video_note', 'animation', 'document', 'audio', 'voice']:
                            logger.warning(f"Unrecognized media type '{media_type}' for message {msg['id']} to user {user['user_id']}. Falling back to text only.")
                        
                        if text:
                            await bot.send_message(
                                user['user_id'],
                                text,
                                parse_mode=parse_mode,
                                reply_markup=reply_markup
                            )
                        else:
                            logger.error(f"Cannot send message {msg['id']} to user {user['user_id']}: no text content and media_file_id missing")
                    
                    # Mark message as sent
                    await db.mark_static_message_sent(user['user_id'], msg['id'])
                    await db.log_action(user['user_id'], "received_static_message", f"Day {days_since_join} message (ID: {msg['id']})")
                    logger.info(f"Static message {msg['id']} sent to user {user['user_id']} for day {days_since_join}")
                except Exception as e:
                    logger.warning(f"Could not send static message to user {user['user_id']}: {e}")
    except Exception as e:
        logger.error(f"Error sending static messages: {e}")


@dp.callback_query(F.data.startswith("viewed_"))
async def handle_viewed_button(callback: types.CallbackQuery):
    """Handle 'viewed' button callback"""
    try:
        # Extract static message ID from callback data
        msg_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        # Log the action
        await db.log_action(user_id, "viewed_message", f"Static message ID: {msg_id}")
        
        # Update button to show it was viewed
        await callback.answer("Message marked as viewed ✓")
        
        # Edit the message to update button text
        new_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✓ Viewed", callback_data=f"already_viewed_{msg_id}")]
        ])
        await callback.message.edit_reply_markup(reply_markup=new_markup)
        
        # Check if there's a next message to send
        await send_next_message_if_available(user_id, msg_id)
        
    except Exception as e:
        logger.error(f"Error handling viewed button: {e}")
        await callback.answer("Error processing request")


@dp.callback_query(F.data.startswith("answer_"))
async def handle_answer_button(callback: types.CallbackQuery):
    """Handle answer button callback for questions"""
    try:
        # Extract question ID and answer from callback data
        # Format: answer_<question_id>_<answer_value>
        parts = callback.data.split("_", 2)
        question_id = int(parts[1])
        answer_value = parts[2] if len(parts) > 2 else ""
        user_id = callback.from_user.id
        
        # Store the answer
        await db.add_user_answer(user_id, question_id, answer_value)
        await db.log_action(user_id, "answered_question", f"Question ID: {question_id}, Answer: {answer_value}")
        
        # Update button to show answer was recorded
        await callback.answer(f"Answer recorded: {answer_value} ✓")
        
        # Send next question or complete onboarding
        await send_next_question(user_id, question_id)
        
    except Exception as e:
        logger.error(f"Error handling answer button: {e}")
        await callback.answer("Error processing answer")


async def send_next_message_if_available(user_id: int, current_msg_id: int):
    """Send next static message if available after current one is viewed"""
    try:
        # Get current message info
        static_messages = await db.get_static_messages()
        current_msg = next((msg for msg in static_messages if msg['id'] == current_msg_id), None)
        
        if not current_msg:
            return
        
        # Find next message in sequence (same day or next day)
        next_msg = None
        for msg in static_messages:
            if msg['is_active'] and msg['day_number'] == current_msg['day_number']:
                # Check if there's another message on same day
                already_sent = await db.is_static_message_sent(user_id, msg['id'])
                if not already_sent and msg['id'] > current_msg_id:
                    next_msg = msg
                    break
        
        if next_msg:
            # Send the next message immediately
            text = next_msg['html_text'] if next_msg['html_text'] else next_msg['text']
            parse_mode = "HTML" if next_msg['html_text'] else None
            buttons_config = next_msg.get('buttons_config')
            
            # Add viewed button
            reply_markup = await create_message_markup(next_msg['id'], buttons_config)
            
            await bot.send_message(user_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
            await db.mark_static_message_sent(user_id, next_msg['id'])
            await db.log_action(user_id, "received_static_message", f"Message ID: {next_msg['id']}")
            
    except Exception as e:
        logger.error(f"Error sending next message: {e}")


async def create_message_markup(msg_id: int, buttons_config: str = None):
    """Create inline keyboard markup with buttons and viewed button"""
    rows = []
    
    # Add configured buttons if any
    if buttons_config:
        markup = await parse_buttons_config(buttons_config)
        if markup:
            rows.extend(markup.inline_keyboard)
    
    # Add viewed button
    rows.append([InlineKeyboardButton(text="👁 Mark as Viewed", callback_data=f"viewed_{msg_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_next_question(user_id: int, current_question_id: int):
    """Send next question in the onboarding sequence"""
    try:
        questions = await db.get_user_questions(active_only=True)
        
        # Find next question
        current_index = next((i for i, q in enumerate(questions) if q['id'] == current_question_id), -1)
        
        if current_index >= 0 and current_index < len(questions) - 1:
            # Send next question
            next_question = questions[current_index + 1]
            await send_question(user_id, next_question)
        else:
            # All questions answered, complete onboarding
            await db.complete_user_onboarding(user_id)
            await db.set_user_onboarding_state(user_id, current_question_id=None)
            
            # Check if auto-approve is enabled and approve user
            auto_approve_mode = await db.get_setting('auto_approve_mode')
            if auto_approve_mode == 'after_messages':
                # Check if user has pending join requests
                join_requests = await db.get_join_requests_by_user(user_id)
                pending_requests = [req for req in join_requests if req['status'] == 'pending']
                
                for req in pending_requests:
                    try:
                        await bot.approve_chat_join_request(int(req['chat_id']), int(user_id))
                        await db.approve_join_request(req['id'])
                        await db.log_action(user_id, "auto_approved", f"After onboarding completion")
                    except Exception as e:
                        logger.warning(f"Could not auto-approve join request for user {user_id}: {e}")
            
            await bot.send_message(user_id, "✅ Thank you for completing the onboarding! Welcome to our community.")
            
    except Exception as e:
        logger.error(f"Error sending next question: {e}")


async def send_question(user_id: int, question: dict):
    """Send a question to user"""
    try:
        question_text = question['question_text']
        question_type = question['question_type']
        question_id = question['id']
        
        # Update user state
        await db.set_user_onboarding_state(user_id, current_question_id=question_id)
        
        if question_type == 'buttons':
            # Parse options and create inline keyboard
            options = question.get('options', '')
            if options:
                try:
                    options_list = json.loads(options) if options.startswith('[') else options.split(',')
                except (json.JSONDecodeError, ValueError):
                    options_list = options.split(',')
                
                buttons = []
                for i, option in enumerate(options_list):
                    option = option.strip()
                    if option:
                        button = InlineKeyboardButton(
                            text=option,
                            callback_data=f"answer_{question_id}_{option}"
                        )
                        buttons.append([button])
                
                markup = InlineKeyboardMarkup(inline_keyboard=buttons)
                await bot.send_message(user_id, question_text, reply_markup=markup)
            else:
                await bot.send_message(user_id, question_text)
        else:
            # Text input question
            await bot.send_message(user_id, f"{question_text}\n\nPlease type your answer:")
            
    except Exception as e:
        logger.error(f"Error sending question: {e}")


async def start_user_onboarding(user_id: int):
    """Start user onboarding with questions"""
    try:
        questions = await db.get_user_questions(active_only=True)
        
        if questions:
            # Initialize onboarding state
            await db.set_user_onboarding_state(user_id, current_question_id=0)
            
            # Send first question
            await send_question(user_id, questions[0])
            return True
        return False
    except Exception as e:
        logger.error(f"Error starting onboarding: {e}")
        return False


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

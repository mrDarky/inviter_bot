import os
import secrets
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Union
from dotenv import load_dotenv
from database import Database
from passlib.context import CryptContext
import asyncio
import logging
import json
import shutil
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired,
    PasswordHashInvalid, FloodWait, BadRequest, ChannelInvalid, 
    ChannelPrivate, PeerIdInvalid, UsernameInvalid, UsernameNotOccupied
)
from pyrogram.enums import ChatMemberStatus

# Load environment variables
load_dotenv()

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/bot.db")
SESSIONS_DIR = os.getenv("SESSIONS_DIR", "./data/sessions")

# Regex pattern for invite link code validation
INVITE_CODE_PATTERN = r'^[a-zA-Z0-9_-]+$'

# Database instance
db = Database(DATABASE_PATH)

# Create sessions directory
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Store active Pyrogram clients and their metadata
pyrogram_clients = {}
pyrogram_sessions_metadata = {}


def normalize_channel_id(channel_id: str) -> Union[int, str]:
    """
    Normalize channel ID to proper format.
    Telegram channel IDs can be provided in different formats:
    - Numeric ID: -1001234567890 (negative integers) - returns as int
    - Username: @channelname or channelname (alphanumeric with underscores) - returns as str
    
    This function normalizes numeric IDs to integer format (required by Pyrogram)
    and preserves usernames as strings.
    Note: Both normalized and original IDs should be tried when making API calls.
    """
    # If it's empty, return as-is
    if not channel_id:
        return channel_id
    
    # If it's a username (starts with @ or contains non-numeric/non-hyphen characters), return as-is
    # Usernames can contain letters, digits, and underscores
    if channel_id.startswith('@') or not all(c.isdigit() or c == '-' for c in channel_id):
        return channel_id
    
    # If it's a numeric ID, convert to integer (required by Pyrogram's get_chat)
    try:
        channel_id_int = int(channel_id)
        return channel_id_int
    except ValueError:
        # Not a valid numeric ID, return as-is (likely a username)
        return channel_id


class DatabaseLogHandler(logging.Handler):
    """Custom logging handler to save logs to database"""
    def emit(self, record):
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.async_emit(record))
            else:
                loop.run_until_complete(self.async_emit(record))
        except Exception:
            pass
    
    async def async_emit(self, record):
        try:
            await db.add_log(
                level=record.levelname,
                source="admin_panel",
                message=record.getMessage(),
                details=str(record.__dict__)
            )
        except Exception:
            pass


# Add database handler to logger
db_handler = DatabaseLogHandler()
db_handler.setLevel(logging.INFO)
logger.addHandler(db_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup"""
    await db.init_db()
    yield


# Initialize FastAPI app
app = FastAPI(title="Inviter Bot Admin Panel", lifespan=lifespan)

# Templates
templates = Jinja2Templates(directory="templates")

# Static files (will be created later)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# Pydantic models
class LoginRequest(BaseModel):
    username: str
    password: str


class MessageRequest(BaseModel):
    text: str
    html_text: Optional[str] = None
    user_ids: List[int]


class PyrogramSendCodeRequest(BaseModel):
    session_name: str
    api_id: int
    api_hash: str
    phone_number: str


class PyrogramVerifyCodeRequest(BaseModel):
    session_name: str
    phone_code: str
    phone_code_hash: str


class PyrogramVerifyPasswordRequest(BaseModel):
    session_name: str
    password: str


class PyrogramCheckSessionRequest(BaseModel):
    session_name: str


class PyrogramLoadRequestsRequest(BaseModel):
    session_name: str
    channel_id: str


class PyrogramDeleteSessionRequest(BaseModel):
    session_name: str


class PyrogramBotSessionRequest(BaseModel):
    session_name: str
    api_id: int
    api_hash: str
    bot_token: str


class PyrogramCheckAccessRequest(BaseModel):
    session_name: str
    channel_id: str


class ScheduleMessageRequest(BaseModel):
    text: str
    html_text: Optional[str] = None
    scheduled_time: str


class StaticMessageRequest(BaseModel):
    day_number: int
    text: Optional[str] = None
    html_text: Optional[str] = None
    media_type: Optional[str] = 'text'
    media_file_id: Optional[str] = None
    buttons_config: Optional[str] = None
    send_time: Optional[str] = None
    additional_minutes: Optional[int] = 0


class SettingRequest(BaseModel):
    key: str
    value: str


# Session management - persistent storage in database
SESSION_EXPIRY_HOURS = 24


def create_session(username: str) -> str:
    """Generate a secure session token. Token must be stored in database separately."""
    token = secrets.token_urlsafe(32)
    return token


async def cleanup_sessions():
    """Remove expired sessions"""
    await db.cleanup_expired_sessions(SESSION_EXPIRY_HOURS)


async def verify_session(request: Request) -> bool:
    """Verify session from cookie"""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return False
    
    # Get session from database
    session_data = await db.get_session(session_token)
    if not session_data:
        return False
    
    # Check if session is expired
    try:
        # SQLite CURRENT_TIMESTAMP format is compatible with ISO format
        created_at = datetime.fromisoformat(session_data["created_at"])
    except (ValueError, KeyError):
        # If parsing fails, consider session invalid
        await db.delete_session(session_token)
        return False
    
    if datetime.now() - created_at > timedelta(hours=SESSION_EXPIRY_HOURS):
        await db.delete_session(session_token)
        return False
    return True


async def require_auth(request: Request):
    """Dependency to require authentication"""
    if not await verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


# Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root redirect to login or dashboard"""
    if await verify_session(request):
        return RedirectResponse(url="/admin/users")
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login"""
    logger.info(f"Login attempt for user: {username}")
    
    # First check if credentials exist in database
    db_creds = await db.get_admin_credentials(username)
    
    is_valid = False
    if db_creds:
        # Verify against database password
        is_valid = pwd_context.verify(password, db_creds['password_hash'])
    else:
        # Fallback to environment variables
        is_valid = username == ADMIN_USERNAME and password == ADMIN_PASSWORD
    
    if is_valid:
        session_token = create_session(username)
        # Store session in database
        await db.create_session(session_token, username)
        # Clean up old sessions
        await cleanup_sessions()
        
        response = RedirectResponse(url="/admin/users", status_code=303)
        response.set_cookie(key="session_token", value=session_token, httponly=True)
        logger.info(f"Successful login for user: {username}")
        return response
    
    logger.warning(f"Failed login attempt for user: {username}")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid credentials"
    })


@app.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.delete_session(session_token)
    response = RedirectResponse(url="/login")
    response.delete_cookie("session_token")
    return response


@app.get("/admin/users", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def users_page(request: Request, search: str = None, is_banned: int = None, page: int = 1):
    """Users management page"""
    limit = 20
    offset = (page - 1) * limit
    
    users = await db.get_users(search=search, is_banned=is_banned, limit=limit, offset=offset)
    total = await db.get_user_count(search=search, is_banned=is_banned)
    total_pages = (total + limit - 1) // limit
    
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "page": page,
        "total_pages": total_pages,
        "search": search or "",
        "is_banned": is_banned
    })


@app.get("/admin/statistics", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def statistics_page(request: Request):
    """Statistics page"""
    stats = await db.get_statistics()
    return templates.TemplateResponse("statistics.html", {
        "request": request,
        "stats": stats
    })


@app.get("/admin/scheduling", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def scheduling_page(request: Request):
    """Scheduling page"""
    messages = await db.get_scheduled_messages()
    return templates.TemplateResponse("scheduling.html", {
        "request": request,
        "messages": messages
    })


@app.get("/admin/static-messages", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def static_messages_page(request: Request):
    """Static messages page"""
    messages = await db.get_static_messages()
    return templates.TemplateResponse("static_messages.html", {
        "request": request,
        "messages": messages
    })


@app.get("/admin/settings", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def settings_page(request: Request):
    """Settings page"""
    settings = await db.get_all_settings()
    # Get bot token from DB if exists, otherwise from env
    bot_token = settings.get('bot_token') or os.getenv('BOT_TOKEN', '')
    if bot_token:
        # Mask the token for display
        settings['bot_token_masked'] = bot_token[:10] + '...' + bot_token[-10:] if len(bot_token) > 20 else '***'
    else:
        settings['bot_token_masked'] = ''
    
    # Parse bot info if available
    bot_info_str = settings.get('bot_info')
    if bot_info_str:
        try:
            settings['bot_info'] = json.loads(bot_info_str)
        except (json.JSONDecodeError, TypeError):
            settings['bot_info'] = None
    else:
        settings['bot_info'] = None
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings
    })


@app.get("/api/settings")
async def get_settings_api(_: None = Depends(require_auth)):
    """Get settings via API"""
    settings = await db.get_all_settings()
    # Get bot token from DB if exists, otherwise from env
    bot_token = settings.get('bot_token') or os.getenv('BOT_TOKEN', '')
    settings['bot_token'] = bot_token
    return settings


@app.get("/admin/logs", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def logs_page(request: Request):
    """Logs page with 4 tabs"""
    return templates.TemplateResponse("logs.html", {
        "request": request
    })


@app.get("/admin/menu-constructor", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def menu_constructor_page(request: Request):
    """Menu constructor page"""
    menu_items = await db.get_all_bot_menu()
    return templates.TemplateResponse("menu_constructor.html", {
        "request": request,
        "menu_items": menu_items
    })


@app.get("/admin/invite-requests", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def invite_requests_page(request: Request, status: str = 'pending', page: int = 1):
    """Invite requests page"""
    limit = 20
    offset = (page - 1) * limit
    
    requests = await db.get_join_requests(status=status, limit=limit, offset=offset)
    total = await db.get_join_request_count(status=status)
    total_pages = (total + limit - 1) // limit
    
    return templates.TemplateResponse("invite_requests.html", {
        "request": request,
        "requests": requests,
        "page": page,
        "total_pages": total_pages,
        "status": status
    })


@app.get("/admin/session-manager", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def session_manager_page(request: Request):
    """Session manager page for Pyrogram sessions"""
    sessions = await db.get_pyrogram_sessions()
    settings = await db.get_all_settings()
    return templates.TemplateResponse("session_manager.html", {
        "request": request,
        "sessions": sessions,
        "settings": settings
    })


@app.get("/admin/invite-links", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def invite_links_page(request: Request):
    """Invite links management page"""
    invite_links = await db.get_invite_links()
    
    # Get bot username to construct full invite links
    bot_username = await db.get_setting('bot_username')
    if not bot_username:
        # Try to get bot info
        try:
            from bot import bot
            if bot:
                bot_info = await bot.get_me()
                bot_username = bot_info.username
                await db.save_setting('bot_username', bot_username)
        except:
            bot_username = "YourBot"
    
    return templates.TemplateResponse("invite_links.html", {
        "request": request,
        "invite_links": invite_links,
        "bot_username": bot_username
    })


# API endpoints
@app.post("/api/users/ban")
async def ban_users(user_ids: List[int], _: None = Depends(require_auth)):
    """Ban selected users"""
    for user_id in user_ids:
        await db.ban_user(user_id)
    return {"status": "success", "message": f"Banned {len(user_ids)} users"}


@app.post("/api/users/unban")
async def unban_users(user_ids: List[int], _: None = Depends(require_auth)):
    """Unban selected users"""
    for user_id in user_ids:
        await db.unban_user(user_id)
    return {"status": "success", "message": f"Unbanned {len(user_ids)} users"}


@app.post("/api/users/delete")
async def delete_users(user_ids: List[int], _: None = Depends(require_auth)):
    """Delete selected users"""
    for user_id in user_ids:
        await db.delete_user(user_id)
    return {"status": "success", "message": f"Deleted {len(user_ids)} users"}


@app.post("/api/users/send-message")
async def send_message(request: MessageRequest, _: None = Depends(require_auth)):
    """Send message to selected users"""
    try:
        # Import bot and get token
        from aiogram import Bot
        
        # Get bot token from DB or env
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        text = request.html_text if request.html_text else request.text
        parse_mode = "HTML" if request.html_text else None
        
        success_count = 0
        fail_count = 0
        
        for user_id in request.user_ids:
            try:
                await bot_instance.send_message(user_id, text, parse_mode=parse_mode)
                success_count += 1
                await db.log_action(user_id, "received_message", "Message sent via admin panel")
                await asyncio.sleep(0.05)  # Rate limiting
            except Exception as e:
                fail_count += 1
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "message": f"Sent to {success_count} users, failed for {fail_count} users",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/schedule/add")
async def add_scheduled_message(request: ScheduleMessageRequest, _: None = Depends(require_auth)):
    """Add scheduled message"""
    await db.add_scheduled_message(request.text, request.html_text, request.scheduled_time)
    return {"status": "success", "message": "Scheduled message added"}


@app.delete("/api/schedule/{message_id}")
async def delete_scheduled_message(message_id: int, _: None = Depends(require_auth)):
    """Delete scheduled message"""
    await db.delete_scheduled_message(message_id)
    return {"status": "success", "message": "Scheduled message deleted"}


@app.post("/api/static-messages/add")
async def add_static_message(request: StaticMessageRequest, _: None = Depends(require_auth)):
    """Add static message"""
    # Use html_text as fallback if text is not provided
    text_value = request.text if request.text else request.html_text
    if not text_value:
        raise HTTPException(status_code=400, detail="Either text or html_text must be provided")
    
    await db.add_static_message(
        request.day_number, 
        text_value, 
        request.html_text, 
        request.media_type, 
        request.media_file_id, 
        request.buttons_config,
        request.send_time,
        request.additional_minutes
    )
    return {"status": "success", "message": "Static message added"}


@app.put("/api/static-messages/{message_id}")
async def update_static_message(message_id: int, request: StaticMessageRequest, _: None = Depends(require_auth)):
    """Update static message"""
    # Use html_text as fallback if text is not provided
    text_value = request.text if request.text else request.html_text
    if not text_value:
        raise HTTPException(status_code=400, detail="Either text or html_text must be provided")
    
    await db.update_static_message(
        message_id, 
        request.day_number, 
        text_value, 
        request.html_text, 
        request.media_type, 
        request.media_file_id, 
        request.buttons_config,
        request.send_time,
        request.additional_minutes
    )
    return {"status": "success", "message": "Static message updated"}


@app.delete("/api/static-messages/{message_id}")
async def delete_static_message(message_id: int, _: None = Depends(require_auth)):
    """Delete static message"""
    await db.delete_static_message(message_id)
    return {"status": "success", "message": "Static message deleted"}


@app.post("/api/static-messages/{message_id}/toggle")
async def toggle_static_message(message_id: int, _: None = Depends(require_auth)):
    """Toggle static message active status"""
    await db.toggle_static_message(message_id)
    return {"status": "success", "message": "Static message toggled"}


@app.post("/api/static-messages/upload-media")
async def upload_media(
    file: UploadFile = File(...),
    media_type: str = Form(...),
    _: None = Depends(require_auth)
):
    """Upload media file to Telegram and return file_id"""
    try:
        from aiogram import Bot
        from aiogram.types import FSInputFile, BufferedInputFile
        
        # Get bot token
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        # Read file content
        file_content = await file.read()
        
        # Create a buffered input file
        input_file = BufferedInputFile(file_content, filename=file.filename)
        
        # Get admin user ID to send the file to (for storage)
        # We'll use a dummy chat - in production, you might want a specific storage chat
        admin_chat_id_str = os.getenv('ADMIN_CHAT_ID')
        if not admin_chat_id_str:
            # If no admin chat is configured, we can't upload
            raise HTTPException(
                status_code=400, 
                detail="ADMIN_CHAT_ID not configured. Please add your Telegram user ID to .env"
            )
        
        try:
            admin_chat_id = int(admin_chat_id_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="ADMIN_CHAT_ID must be a valid integer"
            )
        
        # Send file to get file_id
        file_id = None
        if media_type == 'photo':
            message = await bot_instance.send_photo(admin_chat_id, input_file)
            file_id = message.photo[-1].file_id  # Get largest photo
        elif media_type == 'video':
            message = await bot_instance.send_video(admin_chat_id, input_file)
            file_id = message.video.file_id
        elif media_type == 'video_note':
            message = await bot_instance.send_video_note(admin_chat_id, input_file)
            file_id = message.video_note.file_id
        elif media_type == 'document':
            message = await bot_instance.send_document(admin_chat_id, input_file)
            file_id = message.document.file_id
        elif media_type == 'animation':
            message = await bot_instance.send_animation(admin_chat_id, input_file)
            file_id = message.animation.file_id
        elif media_type == 'audio':
            message = await bot_instance.send_audio(admin_chat_id, input_file)
            file_id = message.audio.file_id
        elif media_type == 'voice':
            message = await bot_instance.send_voice(admin_chat_id, input_file)
            file_id = message.voice.file_id
        else:
            raise HTTPException(status_code=400, detail="Invalid media type")
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "file_id": file_id,
            "message": "File uploaded successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading media: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/settings")
async def save_settings(settings: dict, _: None = Depends(require_auth)):
    """Save settings"""
    logger.info(f"Updating settings: {list(settings.keys())}")
    for key, value in settings.items():
        await db.set_setting(key, value)
    return {"status": "success", "message": "Settings saved"}


@app.post("/api/settings/change-password")
async def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    _: None = Depends(require_auth)
):
    """Change admin password"""
    username = ADMIN_USERNAME
    logger.info(f"Password change request for user: {username}")
    
    # Verify old password
    db_creds = await db.get_admin_credentials(username)
    
    is_valid = False
    if db_creds:
        is_valid = pwd_context.verify(old_password, db_creds['password_hash'])
    else:
        # If no DB creds, check against env password
        is_valid = old_password == ADMIN_PASSWORD
    
    if not is_valid:
        logger.warning(f"Invalid old password provided for user: {username}")
        raise HTTPException(status_code=400, detail="Invalid old password")
    
    # Hash and store new password
    password_hash = pwd_context.hash(new_password)
    await db.update_admin_password(username, password_hash)
    logger.info(f"Password successfully changed for user: {username}")
    
    return {"status": "success", "message": "Password changed successfully"}


@app.post("/api/settings/bot-token")
async def update_bot_token(bot_token: str = Form(...), _: None = Depends(require_auth)):
    """Update bot token"""
    logger.info("Updating bot token")
    await db.set_setting('bot_token', bot_token)
    return {"status": "success", "message": "Bot token updated successfully"}


@app.post("/api/settings/check-bot")
async def check_bot_token(bot_token: str = Form(None), _: None = Depends(require_auth)):
    """Check bot token and retrieve bot information"""
    logger.info("Checking bot token")
    
    # Get token from form or from database
    if not bot_token:
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv("BOT_TOKEN")
    
    if not bot_token:
        raise HTTPException(status_code=400, detail="No bot token provided")
    
    temp_bot = None
    try:
        # Import Bot from aiogram
        from aiogram import Bot
        
        # Create temporary bot instance
        temp_bot = Bot(token=bot_token)
        
        # Get bot information
        bot_info = await temp_bot.get_me()
        
        # Prepare bot info dictionary
        bot_data = {
            "bot_id": bot_info.id,
            "bot_username": bot_info.username,
            "bot_first_name": bot_info.first_name,
            "bot_last_name": bot_info.last_name or "",
            "can_join_groups": bot_info.can_join_groups,
            "can_read_all_group_messages": bot_info.can_read_all_group_messages,
            "supports_inline_queries": bot_info.supports_inline_queries
        }
        
        # Save bot info to database settings
        await db.set_setting('bot_info', json.dumps(bot_data))
        
        logger.info(f"Bot info retrieved: @{bot_info.username}")
        
        return {
            "status": "success",
            "message": "Bot verified successfully",
            "bot_info": bot_data
        }
    except Exception as e:
        logger.error(f"Error checking bot token: {e}")
        raise HTTPException(status_code=400, detail="Invalid bot token or connection error")
    finally:
        # Ensure bot session is always closed
        if temp_bot:
            try:
                await temp_bot.session.close()
            except Exception:
                pass


# Logs API endpoints
@app.get("/api/logs")
async def get_logs(
    source: str = None,
    level: str = None,
    offset: int = 0,
    limit: int = 1000,
    _: None = Depends(require_auth)
):
    """Get logs with filters"""
    logs = await db.get_logs(source=source, level=level, limit=limit, offset=offset)
    total = await db.get_logs_count(source=source, level=level)
    return {
        "logs": logs,
        "total": total,
        "has_more": offset + limit < total
    }


# Menu constructor API endpoints
class MenuItemRequest(BaseModel):
    button_name: str
    button_order: int
    button_type: str
    action_value: Optional[str] = None
    inline_buttons: Optional[str] = None


@app.get("/api/menu")
async def get_menu(_: None = Depends(require_auth)):
    """Get all menu items"""
    menu_items = await db.get_all_bot_menu()
    return {"menu_items": menu_items}


@app.post("/api/menu")
async def add_menu_item(request: MenuItemRequest, _: None = Depends(require_auth)):
    """Add menu item"""
    logger.info(f"Adding menu item: {request.button_name}")
    await db.add_bot_menu_item(
        request.button_name,
        request.button_order,
        request.button_type,
        request.action_value,
        request.inline_buttons
    )
    return {"status": "success", "message": "Menu item added"}


@app.put("/api/menu/{menu_id}")
async def update_menu_item(menu_id: int, request: MenuItemRequest, _: None = Depends(require_auth)):
    """Update menu item"""
    logger.info(f"Updating menu item: {menu_id}")
    await db.update_bot_menu_item(
        menu_id,
        request.button_name,
        request.button_order,
        request.button_type,
        request.action_value,
        request.inline_buttons
    )
    return {"status": "success", "message": "Menu item updated"}


@app.delete("/api/menu/{menu_id}")
async def delete_menu_item(menu_id: int, _: None = Depends(require_auth)):
    """Delete menu item"""
    logger.info(f"Deleting menu item: {menu_id}")
    await db.delete_bot_menu_item(menu_id)
    return {"status": "success", "message": "Menu item deleted"}


@app.post("/api/menu/{menu_id}/toggle")
async def toggle_menu_item(menu_id: int, _: None = Depends(require_auth)):
    """Toggle menu item active status"""
    logger.info(f"Toggling menu item: {menu_id}")
    await db.toggle_bot_menu_item(menu_id)
    return {"status": "success", "message": "Menu item toggled"}


# Invite requests API endpoints
@app.post("/api/invite-requests/approve")
async def approve_join_requests(request_ids: List[int], _: None = Depends(require_auth)):
    """Approve selected join requests"""
    try:
        from aiogram import Bot
        
        # Get bot token
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        success_count = 0
        fail_count = 0
        
        for request_id in request_ids:
            try:
                # Get request details
                join_request = await db.get_join_request_by_id(request_id)
                if not join_request or join_request['status'] != 'pending':
                    fail_count += 1
                    continue
                
                # Approve the join request
                await bot_instance.approve_chat_join_request(
                    chat_id=join_request['chat_id'],
                    user_id=join_request['user_id']
                )
                
                # Update database
                await db.approve_join_request(request_id)
                await db.log_action(join_request['user_id'], "join_request_approved", f"Chat ID: {join_request['chat_id']}")
                success_count += 1
            except Exception as e:
                logger.error(f"Error approving join request {request_id}: {e}")
                fail_count += 1
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "message": f"Approved {success_count} requests, failed for {fail_count} requests",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving join requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/invite-requests/deny")
async def deny_join_requests(request_ids: List[int], _: None = Depends(require_auth)):
    """Deny selected join requests"""
    try:
        from aiogram import Bot
        
        # Get bot token
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        success_count = 0
        fail_count = 0
        
        for request_id in request_ids:
            try:
                # Get request details
                join_request = await db.get_join_request_by_id(request_id)
                if not join_request or join_request['status'] != 'pending':
                    fail_count += 1
                    continue
                
                # Deny the join request
                await bot_instance.decline_chat_join_request(
                    chat_id=join_request['chat_id'],
                    user_id=join_request['user_id']
                )
                
                # Update database
                await db.deny_join_request(request_id)
                await db.log_action(join_request['user_id'], "join_request_denied", f"Chat ID: {join_request['chat_id']}")
                success_count += 1
            except Exception as e:
                logger.error(f"Error denying join request {request_id}: {e}")
                fail_count += 1
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "message": f"Denied {success_count} requests, failed for {fail_count} requests",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error denying join requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/invite-requests/approve-all")
async def approve_all_join_requests(_: None = Depends(require_auth)):
    """Approve all pending join requests"""
    try:
        from aiogram import Bot
        
        # Get bot token
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        # Get all pending requests with batching
        success_count = 0
        fail_count = 0
        batch_size = 100
        offset = 0
        
        while True:
            pending_requests = await db.get_join_requests(status='pending', limit=batch_size, offset=offset)
            if not pending_requests:
                break
            
            for join_request in pending_requests:
                try:
                    # Approve the join request
                    await bot_instance.approve_chat_join_request(
                        chat_id=join_request['chat_id'],
                        user_id=join_request['user_id']
                    )
                    
                    # Update database
                    await db.approve_join_request(join_request['id'])
                    await db.log_action(join_request['user_id'], "join_request_approved", f"Chat ID: {join_request['chat_id']}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error approving join request {join_request['id']}: {e}")
                    fail_count += 1
            
            # Move to next batch
            offset += batch_size
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "message": f"Approved {success_count} requests, failed for {fail_count} requests",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving all join requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/invite-requests/deny-all")
async def deny_all_join_requests(_: None = Depends(require_auth)):
    """Deny all pending join requests"""
    try:
        from aiogram import Bot
        
        # Get bot token
        bot_token = await db.get_setting('bot_token')
        if not bot_token:
            bot_token = os.getenv('BOT_TOKEN')
        
        if not bot_token:
            raise HTTPException(status_code=400, detail="Bot token not configured")
        
        bot_instance = Bot(token=bot_token)
        
        # Get all pending requests with batching
        success_count = 0
        fail_count = 0
        batch_size = 100
        offset = 0
        
        while True:
            pending_requests = await db.get_join_requests(status='pending', limit=batch_size, offset=offset)
            if not pending_requests:
                break
            
            for join_request in pending_requests:
                try:
                    # Deny the join request
                    await bot_instance.decline_chat_join_request(
                        chat_id=join_request['chat_id'],
                        user_id=join_request['user_id']
                    )
                    
                    # Update database
                    await db.deny_join_request(join_request['id'])
                    await db.log_action(join_request['user_id'], "join_request_denied", f"Chat ID: {join_request['chat_id']}")
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error denying join request {join_request['id']}: {e}")
                    fail_count += 1
            
            # Move to next batch
            offset += batch_size
        
        await bot_instance.session.close()
        
        return {
            "status": "success",
            "message": f"Denied {success_count} requests, failed for {fail_count} requests",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error denying all join requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Pyrogram Session Management API Endpoints
@app.post("/api/pyrogram/send-code")
async def pyrogram_send_code(
    request: PyrogramSendCodeRequest,
    _: None = Depends(require_auth)
):
    """Send verification code to phone number"""
    try:
        session_path = os.path.join(SESSIONS_DIR, request.session_name)
        
        # Create Pyrogram client
        client = Client(
            name=session_path,
            api_id=request.api_id,
            api_hash=request.api_hash
        )
        
        # Connect and send code
        await client.connect()
        sent_code = await client.send_code(request.phone_number)
        
        # Store client and metadata temporarily
        pyrogram_clients[request.session_name] = client
        pyrogram_sessions_metadata[request.session_name] = {
            'phone_number': request.phone_number,
            'api_id': request.api_id,
            'api_hash': request.api_hash
        }
        
        return {
            "status": "success",
            "phone_code_hash": sent_code.phone_code_hash,
            "message": "Verification code sent"
        }
    except FloodWait as e:
        return {"status": "error", "message": f"Flood wait: please wait {e.value} seconds"}
    except Exception as e:
        logger.error(f"Error sending code: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/verify-code")
async def pyrogram_verify_code(
    request: PyrogramVerifyCodeRequest,
    _: None = Depends(require_auth)
):
    """Verify phone code and sign in"""
    try:
        client = pyrogram_clients.get(request.session_name)
        metadata = pyrogram_sessions_metadata.get(request.session_name)
        
        if not client or not metadata:
            return {"status": "error", "message": "Session not found. Please start over."}
        
        try:
            # Sign in with code
            await client.sign_in(
                phone_number=metadata['phone_number'],
                phone_code_hash=request.phone_code_hash,
                phone_code=request.phone_code
            )
            
            # Get user info
            me = await client.get_me()
            user_info = json.dumps({
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone_number": me.phone_number
            })
            
            # Save to database (use upsert pattern)
            session_data = await db.get_pyrogram_session(request.session_name)
            if not session_data:
                try:
                    await db.add_pyrogram_session(
                        session_name=request.session_name,
                        phone_number=metadata['phone_number'],
                        api_id=metadata['api_id'],
                        api_hash=metadata['api_hash'],
                        user_info=user_info
                    )
                except Exception as e:
                    # If race condition occurred, update instead
                    logger.warning(f"Session might already exist, updating: {e}")
                    await db.update_pyrogram_session(request.session_name, user_info=user_info, is_active=1)
            else:
                await db.update_pyrogram_session(request.session_name, user_info=user_info, is_active=1)
            
            # Disconnect client and cleanup
            await client.disconnect()
            del pyrogram_clients[request.session_name]
            del pyrogram_sessions_metadata[request.session_name]
            
            return {
                "status": "success",
                "requires_password": False,
                "user_info": user_info,
                "message": "Successfully authenticated"
            }
        except SessionPasswordNeeded:
            # 2FA is enabled, keep client connected
            return {
                "status": "success",
                "requires_password": True,
                "message": "Two-factor authentication required"
            }
        except PhoneCodeInvalid:
            return {"status": "error", "message": "Invalid verification code"}
        except PhoneCodeExpired:
            return {"status": "error", "message": "Verification code expired. Please start over."}
    except Exception as e:
        logger.error(f"Error verifying code: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/verify-password")
async def pyrogram_verify_password(
    request: PyrogramVerifyPasswordRequest,
    _: None = Depends(require_auth)
):
    """Verify 2FA password"""
    try:
        client = pyrogram_clients.get(request.session_name)
        metadata = pyrogram_sessions_metadata.get(request.session_name)
        
        if not client or not metadata:
            return {"status": "error", "message": "Session not found. Please start over."}
        
        try:
            # Check password
            await client.check_password(request.password)
            
            # Get user info
            me = await client.get_me()
            user_info = json.dumps({
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone_number": me.phone_number
            })
            
            # Save to database (use upsert pattern)
            session_data = await db.get_pyrogram_session(request.session_name)
            if not session_data:
                try:
                    await db.add_pyrogram_session(
                        session_name=request.session_name,
                        phone_number=metadata['phone_number'],
                        api_id=metadata['api_id'],
                        api_hash=metadata['api_hash'],
                        user_info=user_info
                    )
                except Exception as e:
                    # If race condition occurred, update instead
                    logger.warning(f"Session might already exist, updating: {e}")
                    await db.update_pyrogram_session(request.session_name, user_info=user_info, is_active=1)
            else:
                await db.update_pyrogram_session(request.session_name, user_info=user_info, is_active=1)
            
            # Disconnect client and cleanup
            await client.disconnect()
            del pyrogram_clients[request.session_name]
            del pyrogram_sessions_metadata[request.session_name]
            
            return {
                "status": "success",
                "user_info": user_info,
                "message": "Successfully authenticated"
            }
        except PasswordHashInvalid:
            return {"status": "error", "message": "Invalid 2FA password"}
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/import-session")
async def pyrogram_import_session(
    session_name: str = Form(...),
    api_id: int = Form(...),
    api_hash: str = Form(...),
    phone_number: str = Form(...),
    session_file: UploadFile = File(...),
    _: None = Depends(require_auth)
):
    """Import existing session file"""
    try:
        session_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
        
        # Save uploaded file
        with open(session_path, "wb") as f:
            shutil.copyfileobj(session_file.file, f)
        
        # Verify session by connecting
        client = Client(
            name=os.path.join(SESSIONS_DIR, session_name),
            api_id=api_id,
            api_hash=api_hash
        )
        
        try:
            await client.start()
            me = await client.get_me()
            
            user_info = json.dumps({
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "phone_number": me.phone_number
            })
            
            # Save to database
            await db.add_pyrogram_session(
                session_name=session_name,
                phone_number=phone_number,
                api_id=api_id,
                api_hash=api_hash,
                user_info=user_info
            )
            
            await client.stop()
            
            return {
                "status": "success",
                "message": "Session imported successfully",
                "user_info": user_info
            }
        except Exception as e:
            # Remove invalid session file
            if os.path.exists(session_path):
                os.remove(session_path)
            raise e
    except Exception as e:
        logger.error(f"Error importing session: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/check-session")
async def pyrogram_check_session(
    request: PyrogramCheckSessionRequest,
    _: None = Depends(require_auth)
):
    """Check if session is valid and get user info"""
    try:
        session_data = await db.get_pyrogram_session(request.session_name)
        if not session_data:
            return {"status": "error", "message": "Session not found in database"}
        
        session_path = os.path.join(SESSIONS_DIR, request.session_name)
        
        # Create client - handle both user and bot sessions
        if session_data.get('session_type') == 'bot' and session_data.get('bot_token'):
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash'],
                bot_token=session_data['bot_token']
            )
        else:
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash']
            )
        
        try:
            await client.start()
            me = await client.get_me()
            
            user_info = json.dumps({
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": getattr(me, 'last_name', None),
                "phone_number": getattr(me, 'phone_number', None),
                "is_bot": getattr(me, 'is_bot', False)
            })
            
            # Update database
            await db.update_pyrogram_session(request.session_name, user_info=user_info, is_active=1)
            
            await client.stop()
            
            return {
                "status": "success",
                "user_info": user_info,
                "message": "Session is active"
            }
        except Exception as e:
            await db.update_pyrogram_session(request.session_name, is_active=0)
            return {"status": "error", "message": f"Session is invalid: {str(e)}"}
    except Exception as e:
        logger.error(f"Error checking session: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/load-requests")
async def pyrogram_load_requests(
    request: PyrogramLoadRequestsRequest,
    _: None = Depends(require_auth)
):
    """Load join requests from a channel"""
    try:
        session_data = await db.get_pyrogram_session(request.session_name)
        if not session_data:
            return {"status": "error", "message": "Session not found"}
        
        session_path = os.path.join(SESSIONS_DIR, request.session_name)
        
        # Create client - handle both user and bot sessions
        if session_data.get('session_type') == 'bot' and session_data.get('bot_token'):
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash'],
                bot_token=session_data['bot_token']
            )
        else:
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash']
            )
        
        try:
            await client.start()
            
            # Normalize channel ID
            normalized_channel_id = normalize_channel_id(request.channel_id)
            
            # Get chat - try with normalized ID first, then original if it fails
            chat = None
            last_error = None
            
            # Try normalized ID
            try:
                chat = await client.get_chat(normalized_channel_id)
            except (BadRequest, ChannelInvalid, PeerIdInvalid) as e:
                last_error = e
                # If normalized ID fails and it's different from original, try original
                # Compare string representations to handle int vs str comparison
                if str(normalized_channel_id) != request.channel_id:
                    try:
                        chat = await client.get_chat(request.channel_id)
                        last_error = None
                    except (BadRequest, ChannelInvalid, PeerIdInvalid) as e2:
                        last_error = e2
            
            if chat is None:
                await client.stop()
                error_msg = "Invalid channel ID or username. Please verify that: 1) The channel ID is correct (format: -1001234567890 for numeric IDs or @username for usernames), 2) The channel exists, 3) You have access to this channel."
                return {"status": "error", "message": error_msg}
            
            # Check if user has permission
            try:
                member = await client.get_chat_member(chat.id, "me")
                if not member.privileges or not member.privileges.can_invite_users:
                    await client.stop()
                    return {"status": "error", "message": "You don't have permission to view join requests in this channel"}
            except Exception as e:
                await client.stop()
                return {"status": "error", "message": f"Cannot check permissions: {str(e)}"}
            
            # Get join requests with batch processing
            # Remove limit to load all join requests in batches
            count = 0
            skipped = 0
            total = 0
            batch_size = 100
            batch = []
            
            async for req in client.get_chat_join_requests(chat.id):
                try:
                    total += 1
                    batch.append({
                        'user_id': req.user.id,
                        'chat_id': chat.id,
                        'username': req.user.username,
                        'first_name': req.user.first_name,
                        'last_name': req.user.last_name
                    })
                    
                    # Process in batches
                    if len(batch) >= batch_size:
                        for item in batch:
                            is_new = await db.add_join_request(**item)
                            if is_new:
                                count += 1
                            else:
                                skipped += 1
                        batch = []
                except Exception as e:
                    logger.debug(f"Skipping request: {e}")
                    continue
            
            # Process remaining items
            for item in batch:
                is_new = await db.add_join_request(**item)
                if is_new:
                    count += 1
                else:
                    skipped += 1
            
            await client.stop()
            
            message = f"Loaded {count} new join requests"
            if skipped > 0:
                message += f" ({skipped} already existed, {total} total found)"
            
            return {
                "status": "success",
                "count": count,
                "skipped": skipped,
                "total": total,
                "message": message
            }
        except FloodWait as e:
            await client.stop()
            return {"status": "error", "message": f"Flood wait: please wait {e.value} seconds"}
        except Exception as e:
            await client.stop()
            raise e
    except Exception as e:
        logger.error(f"Error loading requests: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/check-access")
async def pyrogram_check_access(
    request: PyrogramCheckAccessRequest,
    _: None = Depends(require_auth)
):
    """Check if session has access to a channel"""
    try:
        session_data = await db.get_pyrogram_session(request.session_name)
        if not session_data:
            return {"status": "error", "message": "Session not found"}
        
        session_path = os.path.join(SESSIONS_DIR, request.session_name)
        
        # Create client - handle both user and bot sessions
        if session_data.get('session_type') == 'bot' and session_data.get('bot_token'):
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash'],
                bot_token=session_data['bot_token']
            )
        else:
            client = Client(
                name=session_path,
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash']
            )
        
        try:
            await client.start()
            
            # Normalize channel ID
            normalized_channel_id = normalize_channel_id(request.channel_id)
            
            # Get chat - try with normalized ID first, then original if it fails
            chat = None
            last_error = None
            
            # Try normalized ID
            try:
                chat = await client.get_chat(normalized_channel_id)
            except (BadRequest, ChannelInvalid, ChannelPrivate, PeerIdInvalid) as e:
                last_error = e
                # If normalized ID fails and it's different from original, try original
                # Compare string representations to handle int vs str comparison
                if str(normalized_channel_id) != request.channel_id:
                    try:
                        chat = await client.get_chat(request.channel_id)
                        last_error = None
                    except (BadRequest, ChannelInvalid, ChannelPrivate, PeerIdInvalid) as e2:
                        last_error = e2
            
            if chat is None:
                await client.stop()
                # Provide more specific error message based on the exception type
                if last_error and isinstance(last_error, ChannelPrivate):
                    error_msg = "Access denied: This is a private channel and you don't have permission to access it."
                elif last_error and isinstance(last_error, (ChannelInvalid, PeerIdInvalid)):
                    error_msg = "Invalid channel: The channel ID or username is incorrect or the channel doesn't exist."
                else:
                    error_msg = "Unable to access channel: Please verify the channel ID/username and ensure you have access to it."
                return {"status": "error", "message": error_msg}
            
            # Check if user/bot has access and get permissions
            try:
                member = await client.get_chat_member(chat.id, "me")
                
                # Build permissions info
                permissions_info = {
                    "status": member.status.name if member.status else "UNKNOWN",
                    "can_be_edited": member.can_be_edited if hasattr(member, 'can_be_edited') else False,
                }
                
                # Add privileges if available (for admin/owner)
                if member.privileges:
                    permissions_info.update({
                        "can_manage_chat": member.privileges.can_manage_chat,
                        "can_delete_messages": member.privileges.can_delete_messages,
                        "can_manage_video_chats": member.privileges.can_manage_video_chats,
                        "can_restrict_members": member.privileges.can_restrict_members,
                        "can_promote_members": member.privileges.can_promote_members,
                        "can_change_info": member.privileges.can_change_info,
                        "can_invite_users": member.privileges.can_invite_users,
                        "can_post_messages": member.privileges.can_post_messages,
                        "can_edit_messages": member.privileges.can_edit_messages,
                        "can_pin_messages": member.privileges.can_pin_messages,
                    })
                
                await client.stop()
                
                return {
                    "status": "success",
                    "message": f"Access confirmed to {chat.title or 'Unknown Channel'}",
                    "chat_info": {
                        "id": chat.id,
                        "title": chat.title or "Unknown Channel",
                        "type": chat.type.name if chat.type else "UNKNOWN",
                        "username": f"@{chat.username}" if chat.username else None,
                        "members_count": chat.members_count if hasattr(chat, 'members_count') else None,
                    },
                    "permissions": permissions_info
                }
            except Exception as e:
                await client.stop()
                return {
                    "status": "error", 
                    "message": f"You have access to the channel but cannot check permissions: {str(e)}"
                }
            
        except FloodWait as e:
            await client.stop()
            return {"status": "error", "message": f"Flood wait: please wait {e.value} seconds"}
        except Exception as e:
            await client.stop()
            raise e
    except Exception as e:
        logger.error(f"Error checking access: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/delete-session")
async def pyrogram_delete_session(
    request: PyrogramDeleteSessionRequest,
    _: None = Depends(require_auth)
):
    """Delete a Pyrogram session"""
    try:
        # Delete from database
        await db.delete_pyrogram_session(request.session_name)
        
        # Delete session file
        session_path = os.path.join(SESSIONS_DIR, f"{request.session_name}.session")
        if os.path.exists(session_path):
            os.remove(session_path)
        
        return {"status": "success", "message": "Session deleted"}
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/pyrogram/create-bot-session")
async def pyrogram_create_bot_session(
    request: PyrogramBotSessionRequest,
    _: None = Depends(require_auth)
):
    """Create a bot session using bot token"""
    try:
        session_path = os.path.join(SESSIONS_DIR, request.session_name)
        
        # Create Pyrogram bot client
        client = Client(
            name=session_path,
            api_id=request.api_id,
            api_hash=request.api_hash,
            bot_token=request.bot_token
        )
        
        # Start the client and get bot info
        await client.start()
        me = await client.get_me()
        
        # Create user_info JSON with null checks
        username = me.username or f"bot_{me.id}"
        user_info = json.dumps({
            "id": me.id,
            "username": username,
            "first_name": me.first_name or "Bot",
            "is_bot": True
        })
        
        # Save to database
        await db.add_pyrogram_session(
            session_name=request.session_name,
            phone_number=f"bot_{username}",
            api_id=request.api_id,
            api_hash=request.api_hash,
            user_info=user_info,
            session_type='bot',
            bot_token=request.bot_token
        )
        
        # Stop the client
        await client.stop()
        
        return {
            "status": "success",
            "user_info": user_info,
            "message": "Bot session created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating bot session: {e}")
        # Clean up session file if it was created
        session_path_file = os.path.join(SESSIONS_DIR, f"{request.session_name}.session")
        if os.path.exists(session_path_file):
            try:
                os.remove(session_path_file)
            except:
                pass
        return {"status": "error", "message": str(e)}


# Invite Links API endpoints
@app.post("/api/invite-links/create")
async def create_invite_link(code: str = Form(...), name: str = Form(...), _: None = Depends(require_auth)):
    """Create a new invite link"""
    try:
        # Validate code format (alphanumeric and underscores only)
        import re
        if not re.match(INVITE_CODE_PATTERN, code):
            return {"status": "error", "message": "Code can only contain letters, numbers, hyphens, and underscores"}
        
        # Check if code already exists
        existing = await db.get_invite_link_by_code(code)
        if existing:
            return {"status": "error", "message": "This code already exists"}
        
        await db.create_invite_link(code, name)
        return {"status": "success", "message": f"Invite link '{name}' created successfully"}
    except Exception as e:
        logger.error(f"Error creating invite link: {e}")
        return {"status": "error", "message": str(e)}


@app.delete("/api/invite-links/{link_id}")
async def delete_invite_link(link_id: int, _: None = Depends(require_auth)):
    """Delete an invite link"""
    try:
        await db.delete_invite_link(link_id)
        return {"status": "success", "message": "Invite link deleted"}
    except Exception as e:
        logger.error(f"Error deleting invite link: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/invite-links/{link_id}/toggle")
async def toggle_invite_link(link_id: int, _: None = Depends(require_auth)):
    """Toggle invite link active status"""
    try:
        await db.toggle_invite_link(link_id)
        return {"status": "success", "message": "Invite link status toggled"}
    except Exception as e:
        logger.error(f"Error toggling invite link: {e}")
        return {"status": "error", "message": str(e)}


# Channel invite links routes (Telegram channel invite links)
@app.get("/admin/channel-invite-links", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def channel_invite_links_page(request: Request):
    """Channel invite links management page"""
    links = await db.get_channel_invite_links()
    sessions = await db.get_pyrogram_sessions()
    
    # Filter only active sessions
    active_sessions = [s for s in sessions if s['is_active']]
    
    return templates.TemplateResponse("channel_invite_links.html", {
        "request": request,
        "links": links,
        "sessions": active_sessions
    })


@app.post("/api/channel-invite-links/get-channels")
async def get_user_channels(session_name: str = Form(...), _: None = Depends(require_auth)):
    """Get list of channels/groups for a Pyrogram session"""
    try:
        # Get session data from database
        session_data = await db.get_pyrogram_session(session_name)
        if not session_data:
            return {"status": "error", "message": "Session not found"}
        
        if not session_data['is_active']:
            return {"status": "error", "message": "Session is not active"}
        
        # Check if it's a bot session
        if session_data.get('session_type') == 'bot':
            return {"status": "error", "message": "Bot sessions cannot list channels. This feature is only available for user sessions. Please use a user session or enter the channel ID manually."}
        
        # Create Pyrogram client
        client = Client(
            name=os.path.join(SESSIONS_DIR, session_name),
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Get all dialogs (chats)
            channels = []
            async for dialog in client.get_dialogs():
                chat = dialog.chat
                # Only include channels and supergroups where user is admin
                if chat.type in ["channel", "supergroup"]:
                    try:
                        # Check if user has rights to create invite links
                        member = await client.get_chat_member(chat.id, "me")
                        if member.privileges and (member.privileges.can_invite_users or member.status == ChatMemberStatus.OWNER):
                            channels.append({
                                "id": chat.id,
                                "title": chat.title,
                                "username": chat.username,
                                "type": chat.type
                            })
                    except Exception:
                        # Skip channels where we can't get member info
                        pass
            
            await client.stop()
            
            return {"status": "success", "channels": channels}
        except Exception as e:
            try:
                await client.stop()
            except:
                pass
            logger.error(f"Error getting channels: {e}")
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error in get_user_channels: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/channel-invite-links/create")
async def create_channel_invite_link(
    session_name: str = Form(...),
    channel_id: str = Form(...),
    name: str = Form(...),
    expire_date: Optional[int] = Form(None),
    member_limit: Optional[int] = Form(None),
    creates_join_request: bool = Form(False),
    _: None = Depends(require_auth)
):
    """Create a new channel invite link via Pyrogram"""
    try:
        # Get session data
        session_data = await db.get_pyrogram_session(session_name)
        if not session_data or not session_data['is_active']:
            return {"status": "error", "message": "Session not found or inactive"}
        
        # Normalize channel ID
        normalized_channel_id = normalize_channel_id(channel_id)
        
        # Create Pyrogram client
        client = Client(
            name=os.path.join(SESSIONS_DIR, session_name),
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Get channel info - this will validate access
            # Try normalized ID first, then original if different
            chat = None
            last_error = None
            
            try:
                chat = await client.get_chat(normalized_channel_id)
            except (UsernameInvalid, UsernameNotOccupied) as e:
                last_error = e
                # Compare string representations to handle int vs str comparison
                if str(normalized_channel_id) != channel_id:
                    try:
                        chat = await client.get_chat(channel_id)
                        last_error = None
                    except (UsernameInvalid, UsernameNotOccupied) as e2:
                        last_error = e2
                
                if last_error:
                    await client.stop()
                    return {
                        "status": "error", 
                        "message": "Invalid username. Please check the username format (e.g., @channelname) and ensure it exists."
                    }
            except (ChannelInvalid, PeerIdInvalid, BadRequest) as e:
                last_error = e
                # Compare string representations to handle int vs str comparison
                if str(normalized_channel_id) != channel_id:
                    try:
                        chat = await client.get_chat(channel_id)
                        last_error = None
                    except (ChannelInvalid, PeerIdInvalid, BadRequest) as e2:
                        last_error = e2
                
                if last_error:
                    await client.stop()
                    return {
                        "status": "error", 
                        "message": "Invalid channel ID. Please use a valid numeric channel ID (e.g., -1001234567890) or username (e.g., @channelname)."
                    }
            except ChannelPrivate:
                await client.stop()
                return {
                    "status": "error", 
                    "message": "Cannot access this channel. The channel is private or the session doesn't have access to it."
                }
            
            if chat is None:
                await client.stop()
                return {
                    "status": "error",
                    "message": "Unable to access channel. Please verify the channel ID and your access permissions."
                }
            
            # Create invite link - use chat.id for consistency
            invite_link = await client.create_chat_invite_link(
                chat_id=chat.id,
                name=name,
                expire_date=expire_date,
                member_limit=member_limit,
                creates_join_request=creates_join_request
            )
            
            # Save to database - use chat.id for the numeric ID
            await db.create_channel_invite_link(
                session_name=session_name,
                channel_id=chat.id,
                channel_title=chat.title,
                channel_username=chat.username,
                invite_link=invite_link.invite_link,
                name=name,
                expire_date=expire_date,
                member_limit=member_limit,
                creates_join_request=1 if creates_join_request else 0,
                is_primary=0
            )
            
            await client.stop()
            
            return {
                "status": "success",
                "message": f"Invite link '{name}' created successfully",
                "invite_link": invite_link.invite_link
            }
        except Exception as e:
            try:
                await client.stop()
            except:
                pass
            logger.error(f"Error creating channel invite link: {e}")
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error in create_channel_invite_link: {e}")
        return {"status": "error", "message": str(e)}


@app.put("/api/channel-invite-links/{link_id}/edit")
async def edit_channel_invite_link(
    link_id: int,
    name: str = Form(...),
    expire_date: Optional[int] = Form(None),
    member_limit: Optional[int] = Form(None),
    creates_join_request: bool = Form(False),
    _: None = Depends(require_auth)
):
    """Edit a channel invite link via Pyrogram"""
    try:
        # Get link data
        link_data = await db.get_channel_invite_link_by_id(link_id)
        if not link_data:
            return {"status": "error", "message": "Link not found"}
        
        if link_data['is_revoked']:
            return {"status": "error", "message": "Cannot edit revoked link"}
        
        # Get session data
        session_data = await db.get_pyrogram_session(link_data['session_name'])
        if not session_data or not session_data['is_active']:
            return {"status": "error", "message": "Session not found or inactive"}
        
        # Create Pyrogram client
        client = Client(
            name=os.path.join(SESSIONS_DIR, link_data['session_name']),
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Edit invite link
            updated_link = await client.edit_chat_invite_link(
                chat_id=link_data['channel_id'],
                invite_link=link_data['invite_link'],
                name=name,
                expire_date=expire_date,
                member_limit=member_limit,
                creates_join_request=creates_join_request
            )
            
            # Update in database
            await db.update_channel_invite_link(
                link_id=link_id,
                name=name,
                expire_date=expire_date,
                member_limit=member_limit,
                creates_join_request=1 if creates_join_request else 0
            )
            
            await client.stop()
            
            return {
                "status": "success",
                "message": f"Invite link '{name}' updated successfully"
            }
        except Exception as e:
            try:
                await client.stop()
            except:
                pass
            logger.error(f"Error editing channel invite link: {e}")
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error in edit_channel_invite_link: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/channel-invite-links/{link_id}/export")
async def export_channel_invite_link(link_id: int, _: None = Depends(require_auth)):
    """Export (get) a channel invite link via Pyrogram"""
    try:
        # Get link data
        link_data = await db.get_channel_invite_link_by_id(link_id)
        if not link_data:
            return {"status": "error", "message": "Link not found"}
        
        # Get session data
        session_data = await db.get_pyrogram_session(link_data['session_name'])
        if not session_data or not session_data['is_active']:
            return {"status": "error", "message": "Session not found or inactive"}
        
        # Create Pyrogram client
        client = Client(
            name=os.path.join(SESSIONS_DIR, link_data['session_name']),
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Export chat invite link (get primary link)
            invite_link = await client.export_chat_invite_link(link_data['channel_id'])
            
            await client.stop()
            
            return {
                "status": "success",
                "message": "Primary invite link exported",
                "invite_link": invite_link
            }
        except Exception as e:
            try:
                await client.stop()
            except:
                pass
            logger.error(f"Error exporting channel invite link: {e}")
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error in export_channel_invite_link: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/channel-invite-links/{link_id}/revoke")
async def revoke_channel_invite_link(link_id: int, _: None = Depends(require_auth)):
    """Revoke a channel invite link via Pyrogram"""
    try:
        # Get link data
        link_data = await db.get_channel_invite_link_by_id(link_id)
        if not link_data:
            return {"status": "error", "message": "Link not found"}
        
        if link_data['is_revoked']:
            return {"status": "error", "message": "Link is already revoked"}
        
        # Get session data
        session_data = await db.get_pyrogram_session(link_data['session_name'])
        if not session_data or not session_data['is_active']:
            return {"status": "error", "message": "Session not found or inactive"}
        
        # Create Pyrogram client
        client = Client(
            name=os.path.join(SESSIONS_DIR, link_data['session_name']),
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Revoke invite link
            await client.revoke_chat_invite_link(
                chat_id=link_data['channel_id'],
                invite_link=link_data['invite_link']
            )
            
            # Mark as revoked in database
            await db.update_channel_invite_link(link_id=link_id, is_revoked=1)
            
            await client.stop()
            
            return {
                "status": "success",
                "message": "Invite link revoked successfully"
            }
        except Exception as e:
            try:
                await client.stop()
            except:
                pass
            logger.error(f"Error revoking channel invite link: {e}")
            return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"Error in revoke_channel_invite_link: {e}")
        return {"status": "error", "message": str(e)}


@app.delete("/api/channel-invite-links/{link_id}")
async def delete_channel_invite_link_route(link_id: int, _: None = Depends(require_auth)):
    """Delete a channel invite link via Pyrogram and from database"""
    try:
        # Get link data
        link_data = await db.get_channel_invite_link_by_id(link_id)
        if not link_data:
            return {"status": "error", "message": "Link not found"}
        
        # Get session data
        session_data = await db.get_pyrogram_session(link_data['session_name'])
        if session_data and session_data['is_active']:
            # Try to delete from Telegram
            client = Client(
                name=os.path.join(SESSIONS_DIR, link_data['session_name']),
                api_id=session_data['api_id'],
                api_hash=session_data['api_hash']
            )
            
            try:
                await client.start()
                
                # Delete invite link from Telegram
                await client.delete_chat_invite_link(
                    chat_id=link_data['channel_id'],
                    invite_link=link_data['invite_link']
                )
                
                await client.stop()
            except Exception as e:
                try:
                    await client.stop()
                except:
                    pass
                logger.warning(f"Could not delete link from Telegram: {e}")
                # Continue to delete from database anyway
        
        # Delete from database
        await db.delete_channel_invite_link(link_id)
        
        return {
            "status": "success",
            "message": "Invite link deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error in delete_channel_invite_link: {e}")
        return {"status": "error", "message": str(e)}


# User Questions Page and API
@app.get("/admin/questions", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def questions_page(request: Request):
    """Questions management page"""
    questions = await db.get_user_questions(active_only=False)
    return templates.TemplateResponse("questions.html", {
        "request": request,
        "questions": questions
    })


class QuestionRequest(BaseModel):
    question_text: str
    question_type: str  # text or buttons
    options: Optional[str] = None
    order_number: int = 0
    is_required: int = 1


@app.post("/api/questions/add")
async def add_question(request: QuestionRequest, _: None = Depends(require_auth)):
    """Add a new question"""
    await db.add_user_question(
        question_text=request.question_text,
        question_type=request.question_type,
        options=request.options,
        is_required=request.is_required,
        order_number=request.order_number
    )
    return {"status": "success", "message": "Question added successfully"}


@app.get("/api/questions/{question_id}")
async def get_question(question_id: int, _: None = Depends(require_auth)):
    """Get a specific question"""
    question = await db.get_user_question(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


@app.put("/api/questions/{question_id}")
async def update_question(question_id: int, request: QuestionRequest, _: None = Depends(require_auth)):
    """Update a question"""
    await db.update_user_question(
        question_id=question_id,
        question_text=request.question_text,
        question_type=request.question_type,
        options=request.options,
        is_required=request.is_required,
        order_number=request.order_number
    )
    return {"status": "success", "message": "Question updated successfully"}


@app.delete("/api/questions/{question_id}")
async def delete_question(question_id: int, _: None = Depends(require_auth)):
    """Delete a question"""
    await db.delete_user_question(question_id)
    return {"status": "success", "message": "Question deleted successfully"}


@app.post("/api/questions/{question_id}/toggle")
async def toggle_question(question_id: int, _: None = Depends(require_auth)):
    """Toggle question active status"""
    await db.toggle_user_question(question_id)
    return {"status": "success", "message": "Question status toggled"}


@app.get("/api/users/{user_id}/answers")
async def get_user_answers(user_id: int, _: None = Depends(require_auth)):
    """Get answers for a specific user"""
    answers = await db.get_user_answers(user_id)
    return {"answers": answers}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host=host, port=port)

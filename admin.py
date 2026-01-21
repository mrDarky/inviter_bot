import os
import secrets
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
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
    PasswordHashInvalid, FloodWait, BadRequest
)

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

# Database instance
db = Database(DATABASE_PATH)

# Create sessions directory
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Store active Pyrogram clients and their metadata
pyrogram_clients = {}
pyrogram_sessions_metadata = {}


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
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings
    })


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
        
        # Create client and check
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
                "last_name": me.last_name,
                "phone_number": me.phone_number
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
        
        # Create client
        client = Client(
            name=session_path,
            api_id=session_data['api_id'],
            api_hash=session_data['api_hash']
        )
        
        try:
            await client.start()
            
            # Get chat
            try:
                chat = await client.get_chat(request.channel_id)
            except BadRequest:
                await client.stop()
                return {"status": "error", "message": "Invalid channel ID or username"}
            
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
            count = 0
            batch_size = 100
            batch = []
            
            async for req in client.get_chat_join_requests(chat.id, limit=1000):  # Limit to 1000 total
                try:
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
                            try:
                                await db.add_join_request(**item)
                                count += 1
                            except Exception:
                                # Skip if already exists
                                pass
                        batch = []
                except Exception as e:
                    logger.debug(f"Skipping request: {e}")
                    continue
            
            # Process remaining items
            for item in batch:
                try:
                    await db.add_join_request(**item)
                    count += 1
                except Exception:
                    # Skip if already exists
                    pass
            
            await client.stop()
            
            return {
                "status": "success",
                "count": count,
                "message": f"Loaded {count} join requests"
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


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host=host, port=port)

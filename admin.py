import os
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, HTTPException, Depends
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

# Database instance
db = Database(DATABASE_PATH)


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


class ScheduleMessageRequest(BaseModel):
    text: str
    html_text: Optional[str] = None
    scheduled_time: str


class StaticMessageRequest(BaseModel):
    day_number: int
    text: str
    html_text: Optional[str] = None


class SettingRequest(BaseModel):
    key: str
    value: str


# Session management - persistent storage in database
SESSION_EXPIRY_HOURS = 24


def create_session(username: str) -> str:
    """Create a session token - caller must store it in database before use"""
    import secrets
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
    from datetime import timedelta
    created_at = datetime.fromisoformat(session_data["created_at"])
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
    await db.add_static_message(request.day_number, request.text, request.html_text)
    return {"status": "success", "message": "Static message added"}


@app.put("/api/static-messages/{message_id}")
async def update_static_message(message_id: int, request: StaticMessageRequest, _: None = Depends(require_auth)):
    """Update static message"""
    await db.update_static_message(message_id, request.day_number, request.text, request.html_text)
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


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host=host, port=port)

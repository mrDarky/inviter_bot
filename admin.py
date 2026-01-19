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
import asyncio

# Load environment variables
load_dotenv()

# Configuration
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/bot.db")

# Database instance
db = Database(DATABASE_PATH)


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


# Simple session management
sessions = {}
SESSION_EXPIRY_HOURS = 24


def create_session(username: str) -> str:
    """Create a session token"""
    import secrets
    token = secrets.token_urlsafe(32)
    sessions[token] = {"username": username, "created_at": datetime.now()}
    # Clean up old sessions
    cleanup_sessions()
    return token


def cleanup_sessions():
    """Remove expired sessions"""
    from datetime import timedelta
    expiry_time = datetime.now() - timedelta(hours=SESSION_EXPIRY_HOURS)
    expired = [token for token, data in sessions.items() if data["created_at"] < expiry_time]
    for token in expired:
        del sessions[token]


def verify_session(request: Request) -> bool:
    """Verify session from cookie"""
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in sessions:
        return False
    # Check if session is expired
    session_data = sessions[session_token]
    from datetime import timedelta
    if datetime.now() - session_data["created_at"] > timedelta(hours=SESSION_EXPIRY_HOURS):
        del sessions[session_token]
        return False
    return True


async def require_auth(request: Request):
    """Dependency to require authentication"""
    if not verify_session(request):
        raise HTTPException(status_code=401, detail="Not authenticated")


# Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root redirect to login or dashboard"""
    if verify_session(request):
        return RedirectResponse(url="/admin/users")
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """Handle login"""
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session_token = create_session(username)
        response = RedirectResponse(url="/admin/users", status_code=303)
        response.set_cookie(key="session_token", value=session_token, httponly=True)
        return response
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Invalid credentials"
    })


@app.get("/logout")
async def logout(request: Request):
    """Handle logout"""
    session_token = request.cookies.get("session_token")
    if session_token in sessions:
        del sessions[session_token]
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
    return templates.TemplateResponse("settings.html", {
        "request": request,
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
        # Import bot only when needed
        from bot import bot, init_bot
        init_bot()
        
        text = request.html_text if request.html_text else request.text
        parse_mode = "HTML" if request.html_text else None
        
        success_count = 0
        fail_count = 0
        
        for user_id in request.user_ids:
            try:
                await bot.send_message(user_id, text, parse_mode=parse_mode)
                success_count += 1
                await db.log_action(user_id, "received_message", "Message sent via admin panel")
                await asyncio.sleep(0.05)  # Rate limiting
            except Exception as e:
                fail_count += 1
        
        return {
            "status": "success",
            "message": f"Sent to {success_count} users, failed for {fail_count} users",
            "success_count": success_count,
            "fail_count": fail_count
        }
    except Exception as e:
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
    for key, value in settings.items():
        await db.set_setting(key, value)
    return {"status": "success", "message": "Settings saved"}


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(app, host=host, port=port)

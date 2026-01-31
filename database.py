import aiosqlite
import os
from datetime import datetime


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    async def init_db(self):
        """Initialize database tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_banned INTEGER DEFAULT 0,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Messages table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    html_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Scheduled messages table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    html_text TEXT,
                    scheduled_time TIMESTAMP NOT NULL,
                    is_sent INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Static messages table (messages for first N days)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS static_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    html_text TEXT,
                    media_type TEXT DEFAULT 'text',
                    media_file_id TEXT,
                    buttons_config TEXT,
                    send_time TEXT,
                    additional_minutes INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # User actions/statistics table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    action_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # Static message sent tracking table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS static_messages_sent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    static_message_id INTEGER NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (static_message_id) REFERENCES static_messages(id),
                    UNIQUE(user_id, static_message_id)
                )
            """)
            
            # Settings table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Logs table for both bot and admin panel
            await db.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Admin credentials table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admin_credentials (
                    id INTEGER PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Bot menu structure table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_menu (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    button_name TEXT NOT NULL,
                    button_order INTEGER NOT NULL,
                    button_type TEXT NOT NULL,
                    action_value TEXT,
                    inline_buttons TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sessions table for persistent login
            await db.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Join requests table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS join_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    status TEXT DEFAULT 'pending',
                    request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_date TIMESTAMP,
                    UNIQUE(user_id, chat_id)
                )
            """)
            
            # Create index on status column for better query performance
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_join_requests_status 
                ON join_requests(status)
            """)
            
            # Pyrogram sessions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pyrogram_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_name TEXT UNIQUE NOT NULL,
                    phone_number TEXT NOT NULL,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    last_check TIMESTAMP,
                    user_info TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Invite links table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invite_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Channel invite links table (Telegram channel invite links)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channel_invite_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    session_name TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_title TEXT,
                    channel_username TEXT,
                    invite_link TEXT NOT NULL,
                    name TEXT NOT NULL,
                    expire_date INTEGER,
                    member_limit INTEGER,
                    creates_join_request INTEGER DEFAULT 0,
                    is_primary INTEGER DEFAULT 0,
                    is_revoked INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES pyrogram_sessions(id)
                )
            """)
            
            # Migration: Add new columns to static_messages if they don't exist
            try:
                # Check if columns exist
                async with db.execute("PRAGMA table_info(static_messages)") as cursor:
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    if 'media_type' not in column_names:
                        await db.execute("ALTER TABLE static_messages ADD COLUMN media_type TEXT DEFAULT 'text'")
                    if 'media_file_id' not in column_names:
                        await db.execute("ALTER TABLE static_messages ADD COLUMN media_file_id TEXT")
                    if 'buttons_config' not in column_names:
                        await db.execute("ALTER TABLE static_messages ADD COLUMN buttons_config TEXT")
                    if 'send_time' not in column_names:
                        await db.execute("ALTER TABLE static_messages ADD COLUMN send_time TEXT")
                    if 'additional_minutes' not in column_names:
                        await db.execute("ALTER TABLE static_messages ADD COLUMN additional_minutes INTEGER DEFAULT 0")
            except Exception as e:
                # Log migration errors for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Migration warning (may be expected if columns already exist): {e}")
            
            # Migration: Add invite_code column to users table if it doesn't exist
            try:
                async with db.execute("PRAGMA table_info(users)") as cursor:
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    if 'invite_code' not in column_names:
                        await db.execute("ALTER TABLE users ADD COLUMN invite_code TEXT")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Migration warning for users table: {e}")
            
            # Migration: Add session_type and bot_token columns to pyrogram_sessions table if they don't exist
            try:
                async with db.execute("PRAGMA table_info(pyrogram_sessions)") as cursor:
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    if 'session_type' not in column_names:
                        await db.execute("ALTER TABLE pyrogram_sessions ADD COLUMN session_type TEXT DEFAULT 'user'")
                    if 'bot_token' not in column_names:
                        await db.execute("ALTER TABLE pyrogram_sessions ADD COLUMN bot_token TEXT")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Migration warning for pyrogram_sessions table: {e}")
            
            # Questions table for user onboarding questions
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_text TEXT NOT NULL,
                    question_type TEXT NOT NULL,
                    options TEXT,
                    is_required INTEGER DEFAULT 1,
                    order_number INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # User answers table to store responses
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_answers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    answer_text TEXT NOT NULL,
                    answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (question_id) REFERENCES user_questions(id)
                )
            """)
            
            # User onboarding state table to track progress
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_onboarding_state (
                    user_id INTEGER PRIMARY KEY,
                    current_question_id INTEGER,
                    static_messages_completed INTEGER DEFAULT 0,
                    onboarding_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    onboarding_completed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            await db.commit()
    
    # User operations
    async def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None, invite_code: str = None):
        """Add or update user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, invite_code)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_activity = CURRENT_TIMESTAMP
            """, (user_id, username, first_name, last_name, invite_code))
            await db.commit()
    
    async def get_users(self, search: str = None, is_banned: int = None, limit: int = 100, offset: int = 0):
        """Get users with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM users WHERE 1=1"
            params = []
            
            if search:
                query += " AND (username LIKE ? OR first_name LIKE ? OR last_name LIKE ?)"
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param])
            
            if is_banned is not None:
                query += " AND is_banned = ?"
                params.append(is_banned)
            
            query += " ORDER BY join_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_user_count(self, search: str = None, is_banned: int = None):
        """Get total user count with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT COUNT(*) FROM users WHERE 1=1"
            params = []
            
            if search:
                query += " AND (username LIKE ? OR first_name LIKE ? OR last_name LIKE ?)"
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param])
            
            if is_banned is not None:
                query += " AND is_banned = ?"
                params.append(is_banned)
            
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchone()
                return result[0]
    
    async def ban_user(self, user_id: int):
        """Ban a user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    
    async def unban_user(self, user_id: int):
        """Unban a user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
    
    async def delete_user(self, user_id: int):
        """Delete a user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            await db.commit()
    
    # User actions/statistics
    async def log_action(self, user_id: int, action_type: str, action_data: str = None):
        """Log user action"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_actions (user_id, action_type, action_data)
                VALUES (?, ?, ?)
            """, (user_id, action_type, action_data))
            await db.commit()
    
    async def get_statistics(self):
        """Get statistics"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Total users
            async with db.execute("SELECT COUNT(*) as total FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            
            # Banned users
            async with db.execute("SELECT COUNT(*) as total FROM users WHERE is_banned = 1") as cursor:
                banned_users = (await cursor.fetchone())[0]
            
            # Active users (activity in last 7 days)
            async with db.execute("""
                SELECT COUNT(*) as total FROM users 
                WHERE last_activity >= datetime('now', '-7 days')
            """) as cursor:
                active_users = (await cursor.fetchone())[0]
            
            # Recent actions
            async with db.execute("""
                SELECT ua.*, u.username, u.first_name 
                FROM user_actions ua
                LEFT JOIN users u ON ua.user_id = u.user_id
                ORDER BY ua.created_at DESC
                LIMIT 100
            """) as cursor:
                rows = await cursor.fetchall()
                recent_actions = [dict(row) for row in rows]
            
            return {
                "total_users": total_users,
                "banned_users": banned_users,
                "active_users": active_users,
                "recent_actions": recent_actions
            }
    
    # Scheduled messages
    async def add_scheduled_message(self, text: str, html_text: str, scheduled_time: str):
        """Add scheduled message"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO scheduled_messages (text, html_text, scheduled_time)
                VALUES (?, ?, ?)
            """, (text, html_text, scheduled_time))
            await db.commit()
    
    async def get_scheduled_messages(self):
        """Get all scheduled messages"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM scheduled_messages 
                ORDER BY scheduled_time ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_pending_scheduled_messages(self):
        """Get pending scheduled messages"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM scheduled_messages 
                WHERE is_sent = 0 AND scheduled_time <= datetime('now')
                ORDER BY scheduled_time ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def mark_scheduled_message_sent(self, message_id: int):
        """Mark scheduled message as sent"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE scheduled_messages SET is_sent = 1 WHERE id = ?
            """, (message_id,))
            await db.commit()
    
    async def delete_scheduled_message(self, message_id: int):
        """Delete scheduled message"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM scheduled_messages WHERE id = ?", (message_id,))
            await db.commit()
    
    # Static messages
    async def add_static_message(self, day_number: int, text: str, html_text: str, media_type: str = 'text', media_file_id: str = None, buttons_config: str = None, send_time: str = None, additional_minutes: int = 0):
        """Add static message"""
        # Normalize file_id: strip whitespace and convert empty strings to None
        if media_file_id is not None and isinstance(media_file_id, str):
            media_file_id = media_file_id.strip()
            if not media_file_id:
                media_file_id = None
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO static_messages (day_number, text, html_text, media_type, media_file_id, buttons_config, send_time, additional_minutes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (day_number, text, html_text, media_type, media_file_id, buttons_config, send_time, additional_minutes))
            await db.commit()
    
    async def get_static_messages(self):
        """Get all static messages"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM static_messages 
                ORDER BY day_number ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def update_static_message(self, message_id: int, day_number: int, text: str, html_text: str, media_type: str = 'text', media_file_id: str = None, buttons_config: str = None, send_time: str = None, additional_minutes: int = 0):
        """Update static message"""
        # Normalize file_id: strip whitespace and convert empty strings to None
        if media_file_id is not None and isinstance(media_file_id, str):
            media_file_id = media_file_id.strip()
            if not media_file_id:
                media_file_id = None
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE static_messages SET day_number = ?, text = ?, html_text = ?, media_type = ?, media_file_id = ?, buttons_config = ?, send_time = ?, additional_minutes = ? WHERE id = ?
            """, (day_number, text, html_text, media_type, media_file_id, buttons_config, send_time, additional_minutes, message_id))
            await db.commit()
    
    async def delete_static_message(self, message_id: int):
        """Delete static message"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM static_messages WHERE id = ?", (message_id,))
            await db.commit()
    
    async def toggle_static_message(self, message_id: int):
        """Toggle static message active status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE static_messages 
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """, (message_id,))
            await db.commit()
    
    async def mark_static_message_sent(self, user_id: int, static_message_id: int):
        """Mark static message as sent to a user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO static_messages_sent (user_id, static_message_id)
                VALUES (?, ?)
            """, (user_id, static_message_id))
            await db.commit()
    
    async def is_static_message_sent(self, user_id: int, static_message_id: int):
        """Check if static message was already sent to a user"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT COUNT(*) FROM static_messages_sent 
                WHERE user_id = ? AND static_message_id = ?
            """, (user_id, static_message_id)) as cursor:
                result = await cursor.fetchone()
                return result[0] > 0
    
    # Settings
    async def get_setting(self, key: str):
        """Get setting value"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                result = await cursor.fetchone()
                return result[0] if result else None
    
    async def set_setting(self, key: str, value: str):
        """Set setting value"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """, (key, value))
            await db.commit()
    
    async def get_all_settings(self):
        """Get all settings"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM settings") as cursor:
                rows = await cursor.fetchall()
                return {row['key']: row['value'] for row in rows}
    
    # Logs operations
    async def add_log(self, level: str, source: str, message: str, details: str = None):
        """Add log entry"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO logs (level, source, message, details)
                VALUES (?, ?, ?, ?)
            """, (level, source, message, details))
            await db.commit()
    
    async def get_logs(self, source: str = None, level: str = None, limit: int = 1000, offset: int = 0):
        """Get logs with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM logs WHERE 1=1"
            params = []
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            if level:
                query += " AND level = ?"
                params.append(level)
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_logs_count(self, source: str = None, level: str = None):
        """Get total logs count with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT COUNT(*) FROM logs WHERE 1=1"
            params = []
            
            if source:
                query += " AND source = ?"
                params.append(source)
            
            if level:
                query += " AND level = ?"
                params.append(level)
            
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchone()
                return result[0]
    
    # Admin credentials operations
    async def get_admin_credentials(self, username: str):
        """Get admin credentials"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM admin_credentials WHERE username = ?", (username,)) as cursor:
                result = await cursor.fetchone()
                return dict(result) if result else None
    
    async def update_admin_password(self, username: str, password_hash: str):
        """Update admin password"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO admin_credentials (username, password_hash)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, updated_at = CURRENT_TIMESTAMP
            """, (username, password_hash))
            await db.commit()
    
    # Bot menu operations
    async def get_bot_menu(self):
        """Get all bot menu items"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM bot_menu 
                WHERE is_active = 1
                ORDER BY button_order ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_bot_menu(self):
        """Get all bot menu items including inactive"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM bot_menu 
                ORDER BY button_order ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def add_bot_menu_item(self, button_name: str, button_order: int, button_type: str, action_value: str = None, inline_buttons: str = None):
        """Add bot menu item"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO bot_menu (button_name, button_order, button_type, action_value, inline_buttons)
                VALUES (?, ?, ?, ?, ?)
            """, (button_name, button_order, button_type, action_value, inline_buttons))
            await db.commit()
    
    async def update_bot_menu_item(self, menu_id: int, button_name: str, button_order: int, button_type: str, action_value: str = None, inline_buttons: str = None):
        """Update bot menu item"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE bot_menu 
                SET button_name = ?, button_order = ?, button_type = ?, action_value = ?, inline_buttons = ?
                WHERE id = ?
            """, (button_name, button_order, button_type, action_value, inline_buttons, menu_id))
            await db.commit()
    
    async def delete_bot_menu_item(self, menu_id: int):
        """Delete bot menu item"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM bot_menu WHERE id = ?", (menu_id,))
            await db.commit()
    
    async def toggle_bot_menu_item(self, menu_id: int):
        """Toggle bot menu item active status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE bot_menu 
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """, (menu_id,))
            await db.commit()
    
    # Session operations
    async def create_session(self, session_token: str, username: str):
        """Create a new session"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO sessions (session_token, username)
                VALUES (?, ?)
            """, (session_token, username))
            await db.commit()
    
    async def get_session(self, session_token: str):
        """Get session by token"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,)) as cursor:
                result = await cursor.fetchone()
                return dict(result) if result else None
    
    async def delete_session(self, session_token: str):
        """Delete a session"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM sessions WHERE session_token = ?", (session_token,))
            await db.commit()
    
    async def cleanup_expired_sessions(self, hours: int):
        """Remove sessions older than specified hours"""
        # Ensure hours is an integer for safety
        hours = int(hours)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM sessions 
                WHERE created_at < datetime('now', '-' || ? || ' hours')
            """, (hours,))
            await db.commit()
    
    # Join requests operations
    async def add_join_request(self, user_id: int, chat_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Add or update join request. Returns True if new record was inserted, False if updated."""
        async with aiosqlite.connect(self.db_path) as db:
            # First check if exists to determine if it's new or update
            async with db.execute(
                "SELECT id FROM join_requests WHERE user_id = ? AND chat_id = ?",
                (user_id, chat_id)
            ) as cursor:
                exists = await cursor.fetchone() is not None
            
            await db.execute("""
                INSERT INTO join_requests (user_id, chat_id, username, first_name, last_name, status)
                VALUES (?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(user_id, chat_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    status = 'pending',
                    request_date = CURRENT_TIMESTAMP,
                    processed_date = NULL
            """, (user_id, chat_id, username, first_name, last_name))
            await db.commit()
            return not exists  # Return True if it was a new insert
    
    async def get_join_requests(self, status: str = 'pending', limit: int = 100, offset: int = 0, 
                                chat_id: int = None, date_from: str = None, date_to: str = None, 
                                older_than_count: int = None):
        """Get join requests with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM join_requests WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if chat_id:
                query += " AND chat_id = ?"
                params.append(chat_id)
            
            if date_from:
                query += " AND request_date >= ?"
                params.append(date_from)
            
            if date_to:
                # Add one day to include the entire end date
                query += " AND request_date < datetime(?, '+1 day')"
                params.append(date_to)
            
            query += " ORDER BY request_date DESC"
            
            # Apply older_than_count filter if specified (skip the first N oldest results)
            final_offset = offset
            if older_than_count:
                final_offset += older_than_count
            
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, final_offset])
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_join_request_count(self, status: str = 'pending', chat_id: int = None, 
                                     date_from: str = None, date_to: str = None, 
                                     older_than_count: int = None):
        """Get total join request count with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT COUNT(*) FROM join_requests WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if chat_id:
                query += " AND chat_id = ?"
                params.append(chat_id)
            
            if date_from:
                query += " AND request_date >= ?"
                params.append(date_from)
            
            if date_to:
                # Add one day to include the entire end date
                query += " AND request_date < datetime(?, '+1 day')"
                params.append(date_to)
            
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchone()
                count = result[0]
            
            # Apply older_than_count filter if specified
            if older_than_count and count > older_than_count:
                return count - older_than_count
            
            return count
    
    async def approve_join_request(self, request_id: int):
        """Approve a join request"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE join_requests 
                SET status = 'approved', processed_date = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (request_id,))
            await db.commit()
    
    async def deny_join_request(self, request_id: int):
        """Deny a join request"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE join_requests 
                SET status = 'denied', processed_date = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (request_id,))
            await db.commit()
    
    async def approve_all_join_requests(self):
        """Approve all pending join requests"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE join_requests 
                SET status = 'approved', processed_date = CURRENT_TIMESTAMP 
                WHERE status = 'pending'
            """)
            await db.commit()
    
    async def deny_all_join_requests(self):
        """Deny all pending join requests"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE join_requests 
                SET status = 'denied', processed_date = CURRENT_TIMESTAMP 
                WHERE status = 'pending'
            """)
            await db.commit()
    
    async def get_join_request_by_id(self, request_id: int):
        """Get join request by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM join_requests WHERE id = ?", (request_id,)) as cursor:
                result = await cursor.fetchone()
                return dict(result) if result else None
    
    async def get_join_requests_by_user(self, user_id: int):
        """Get all join requests for a specific user"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM join_requests WHERE user_id = ? ORDER BY request_date DESC",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_distinct_chat_ids(self):
        """Get distinct chat_ids from join requests with basic info"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT chat_id, 
                       COUNT(*) as request_count
                FROM join_requests 
                GROUP BY chat_id 
                ORDER BY request_count DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    # Pyrogram sessions methods
    async def add_pyrogram_session(self, session_name: str, phone_number: str, api_id: int, api_hash: str, user_info: str = None, session_type: str = 'user', bot_token: str = None):
        """Add a new Pyrogram session"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO pyrogram_sessions (session_name, phone_number, api_id, api_hash, user_info, last_check, session_type, bot_token)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            """, (session_name, phone_number, api_id, api_hash, user_info, session_type, bot_token))
            await db.commit()
    
    async def get_pyrogram_sessions(self):
        """Get all Pyrogram sessions"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pyrogram_sessions ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_pyrogram_session(self, session_name: str):
        """Get a specific Pyrogram session"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM pyrogram_sessions WHERE session_name = ?", (session_name,)) as cursor:
                result = await cursor.fetchone()
                return dict(result) if result else None
    
    async def update_pyrogram_session(self, session_name: str, user_info: str = None, is_active: int = None):
        """Update a Pyrogram session"""
        async with aiosqlite.connect(self.db_path) as db:
            if user_info is not None:
                await db.execute("""
                    UPDATE pyrogram_sessions 
                    SET user_info = ?, last_check = CURRENT_TIMESTAMP
                    WHERE session_name = ?
                """, (user_info, session_name))
            if is_active is not None:
                await db.execute("""
                    UPDATE pyrogram_sessions 
                    SET is_active = ?, last_check = CURRENT_TIMESTAMP
                    WHERE session_name = ?
                """, (is_active, session_name))
            await db.commit()
    
    async def delete_pyrogram_session(self, session_name: str):
        """Delete a Pyrogram session"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pyrogram_sessions WHERE session_name = ?", (session_name,))
            await db.commit()
    
    # Invite links operations
    async def create_invite_link(self, code: str, name: str):
        """Create a new invite link"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO invite_links (code, name, is_active)
                VALUES (?, ?, 1)
            """, (code, name))
            await db.commit()
    
    async def get_invite_links(self):
        """Get all invite links with usage statistics"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT 
                    il.id,
                    il.code,
                    il.name,
                    il.is_active,
                    il.created_at,
                    COUNT(u.id) as user_count
                FROM invite_links il
                LEFT JOIN users u ON u.invite_code = il.code
                GROUP BY il.id
                ORDER BY il.created_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_invite_link_by_code(self, code: str):
        """Get invite link by code"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM invite_links WHERE code = ?
            """, (code,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def delete_invite_link(self, link_id: int):
        """Delete an invite link"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM invite_links WHERE id = ?", (link_id,))
            await db.commit()
    
    async def toggle_invite_link(self, link_id: int):
        """Toggle invite link active status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE invite_links 
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """, (link_id,))
            await db.commit()
    
    # Channel invite links methods (Telegram channel invite links)
    async def create_channel_invite_link(
        self,
        session_name: str,
        channel_id: int,
        channel_title: str,
        channel_username: str,
        invite_link: str,
        name: str,
        expire_date: int = None,
        member_limit: int = None,
        creates_join_request: int = 0,
        is_primary: int = 0
    ):
        """Create a new channel invite link record"""
        async with aiosqlite.connect(self.db_path) as db:
            # Get session_id from session_name
            async with db.execute(
                "SELECT id FROM pyrogram_sessions WHERE session_name = ?",
                (session_name,)
            ) as cursor:
                session_row = await cursor.fetchone()
                if not session_row:
                    raise ValueError(f"Session '{session_name}' not found")
                session_id = session_row[0]
            
            await db.execute("""
                INSERT INTO channel_invite_links (
                    session_id, session_name, channel_id, channel_title, channel_username,
                    invite_link, name, expire_date, member_limit, 
                    creates_join_request, is_primary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, session_name, channel_id, channel_title, channel_username,
                invite_link, name, expire_date, member_limit,
                creates_join_request, is_primary
            ))
            await db.commit()
    
    async def get_channel_invite_links(self, session_name: str = None, channel_id: int = None):
        """Get all channel invite links with optional filters"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM channel_invite_links WHERE 1=1"
            params = []
            
            if session_name:
                query += " AND session_name = ?"
                params.append(session_name)
            
            if channel_id:
                query += " AND channel_id = ?"
                params.append(channel_id)
            
            query += " ORDER BY created_at DESC"
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_channel_invite_link_by_id(self, link_id: int):
        """Get a specific channel invite link by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM channel_invite_links WHERE id = ?",
                (link_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_channel_invite_link(
        self,
        link_id: int,
        invite_link: str = None,
        name: str = None,
        expire_date: int = None,
        member_limit: int = None,
        creates_join_request: int = None,
        is_revoked: int = None
    ):
        """Update a channel invite link"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            
            if invite_link is not None:
                updates.append("invite_link = ?")
                params.append(invite_link)
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if expire_date is not None:
                updates.append("expire_date = ?")
                params.append(expire_date)
            if member_limit is not None:
                updates.append("member_limit = ?")
                params.append(member_limit)
            if creates_join_request is not None:
                updates.append("creates_join_request = ?")
                params.append(creates_join_request)
            if is_revoked is not None:
                updates.append("is_revoked = ?")
                params.append(is_revoked)
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(link_id)
                query = f"UPDATE channel_invite_links SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, params)
                await db.commit()
    
    async def delete_channel_invite_link(self, link_id: int):
        """Delete a channel invite link"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM channel_invite_links WHERE id = ?", (link_id,))
            await db.commit()
    
    # User questions methods
    async def add_user_question(self, question_text: str, question_type: str, options: str = None, 
                                is_required: int = 1, order_number: int = 0):
        """Add a new user question"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_questions (question_text, question_type, options, is_required, order_number)
                VALUES (?, ?, ?, ?, ?)
            """, (question_text, question_type, options, is_required, order_number))
            await db.commit()
    
    async def get_user_questions(self, active_only: bool = True):
        """Get all user questions"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM user_questions"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY order_number ASC"
            
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_user_question(self, question_id: int):
        """Get a specific user question"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM user_questions WHERE id = ?",
                (question_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_user_question(self, question_id: int, question_text: str = None, 
                                   question_type: str = None, options: str = None,
                                   is_required: int = None, order_number: int = None):
        """Update a user question"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            
            if question_text is not None:
                updates.append("question_text = ?")
                params.append(question_text)
            if question_type is not None:
                updates.append("question_type = ?")
                params.append(question_type)
            if options is not None:
                updates.append("options = ?")
                params.append(options)
            if is_required is not None:
                updates.append("is_required = ?")
                params.append(is_required)
            if order_number is not None:
                updates.append("order_number = ?")
                params.append(order_number)
            
            if updates:
                params.append(question_id)
                query = f"UPDATE user_questions SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, params)
                await db.commit()
    
    async def toggle_user_question(self, question_id: int):
        """Toggle user question active status"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE user_questions 
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
                WHERE id = ?
            """, (question_id,))
            await db.commit()
    
    async def delete_user_question(self, question_id: int):
        """Delete a user question"""
        async with aiosqlite.connect(self.db_path) as db:
            # Delete associated answers first
            await db.execute("DELETE FROM user_answers WHERE question_id = ?", (question_id,))
            await db.execute("DELETE FROM user_questions WHERE id = ?", (question_id,))
            await db.commit()
    
    # User answers methods
    async def add_user_answer(self, user_id: int, question_id: int, answer_text: str):
        """Add or update a user answer"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if answer already exists
            async with db.execute("""
                SELECT id FROM user_answers WHERE user_id = ? AND question_id = ?
            """, (user_id, question_id)) as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                # Update existing answer
                await db.execute("""
                    UPDATE user_answers SET answer_text = ?, answered_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND question_id = ?
                """, (answer_text, user_id, question_id))
            else:
                # Insert new answer
                await db.execute("""
                    INSERT INTO user_answers (user_id, question_id, answer_text)
                    VALUES (?, ?, ?)
                """, (user_id, question_id, answer_text))
            await db.commit()
    
    async def get_user_answers(self, user_id: int):
        """Get all answers for a specific user"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT ua.*, uq.question_text, uq.question_type
                FROM user_answers ua
                JOIN user_questions uq ON ua.question_id = uq.id
                WHERE ua.user_id = ?
                ORDER BY uq.order_number ASC
            """, (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_user_answer(self, user_id: int, question_id: int):
        """Get a specific user answer"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM user_answers WHERE user_id = ? AND question_id = ?
            """, (user_id, question_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    # User onboarding state methods
    async def set_user_onboarding_state(self, user_id: int, current_question_id: int = None, 
                                        static_messages_completed: int = None):
        """Set or update user onboarding state"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if state exists
            async with db.execute("""
                SELECT user_id FROM user_onboarding_state WHERE user_id = ?
            """, (user_id,)) as cursor:
                existing = await cursor.fetchone()
            
            if existing:
                # Update existing state
                updates = []
                params = []
                if current_question_id is not None:
                    updates.append("current_question_id = ?")
                    params.append(current_question_id)
                if static_messages_completed is not None:
                    updates.append("static_messages_completed = ?")
                    params.append(static_messages_completed)
                
                if updates:
                    params.append(user_id)
                    query = f"UPDATE user_onboarding_state SET {', '.join(updates)} WHERE user_id = ?"
                    await db.execute(query, params)
            else:
                # Insert new state
                await db.execute("""
                    INSERT INTO user_onboarding_state (user_id, current_question_id, static_messages_completed)
                    VALUES (?, ?, ?)
                """, (user_id, current_question_id or 0, static_messages_completed or 0))
            await db.commit()
    
    async def get_user_onboarding_state(self, user_id: int):
        """Get user onboarding state"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM user_onboarding_state WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def complete_user_onboarding(self, user_id: int):
        """Mark user onboarding as completed"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE user_onboarding_state 
                SET onboarding_completed_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))
            await db.commit()

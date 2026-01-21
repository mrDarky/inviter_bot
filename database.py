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
            
            await db.commit()
    
    # User operations
    async def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Add or update user"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    last_activity = CURRENT_TIMESTAMP
            """, (user_id, username, first_name, last_name))
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
        """Add or update join request"""
        async with aiosqlite.connect(self.db_path) as db:
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
    
    async def get_join_requests(self, status: str = 'pending', limit: int = 100, offset: int = 0):
        """Get join requests with optional status filter"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = "SELECT * FROM join_requests WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            query += " ORDER BY request_date DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_join_request_count(self, status: str = 'pending'):
        """Get total join request count with optional status filter"""
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT COUNT(*) FROM join_requests WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            async with db.execute(query, params) as cursor:
                result = await cursor.fetchone()
                return result[0]
    
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

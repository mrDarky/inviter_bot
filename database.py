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
            
            # Settings table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
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
    async def add_static_message(self, day_number: int, text: str, html_text: str):
        """Add static message"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO static_messages (day_number, text, html_text)
                VALUES (?, ?, ?)
            """, (day_number, text, html_text))
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
    
    async def update_static_message(self, message_id: int, text: str, html_text: str):
        """Update static message"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE static_messages SET text = ?, html_text = ? WHERE id = ?
            """, (text, html_text, message_id))
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

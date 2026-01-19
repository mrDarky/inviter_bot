# Inviter Bot - Telegram Bot with Admin Panel

A powerful Telegram bot with a comprehensive admin panel for managing channel members and sending automated messages.

## Features

### Telegram Bot (aiogram)
- 🤖 Accept and track invite members in channels
- 📨 Send messages to members
- 📊 Track user activities and statistics
- 🔔 Automated static messages for first N days
- ⏰ Scheduled message delivery

### Admin Panel (FastAPI + Bootstrap 5)
- 👥 **Users Management Page**
  - View all users in a responsive table
  - Search and filter users (active, banned, etc.)
  - Multi-select actions (ban, unban, delete)
  - Send custom messages to selected users with HTML support
  - Real-time preview of messages
  
- 📊 **Statistics Page**
  - Total users, active users, banned users
  - Recent user actions log
  - Activity monitoring
  
- 📅 **Scheduling Page**
  - Interactive calendar view (FullCalendar)
  - Schedule messages for future delivery
  - View and manage scheduled messages
  
- 📧 **Static Messages Page**
  - Create messages for specific days after user joins
  - Toggle active/inactive status
  - Edit and delete messages
  
- ⚙️ **Settings Page**
  - Configure bot behavior
  - Welcome message settings
  - Auto-ban options
  - Message timing configuration

## Technology Stack

- **Python 3.8+**
- **aiogram 3.3** - Telegram Bot Framework
- **FastAPI 0.109** - Web Framework for Admin Panel
- **SQLite** - Database (aiosqlite for async operations)
- **Bootstrap 5** - Frontend UI Framework
- **FullCalendar** - Calendar component for scheduling
- **APScheduler** - Task scheduling

## Installation

1. Clone the repository:
```bash
git clone https://github.com/mrDarky/inviter_bot.git
cd inviter_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
```

4. Edit `.env` and add your Telegram Bot Token:
```env
BOT_TOKEN=your_bot_token_here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
API_HOST=0.0.0.0
API_PORT=8000
DATABASE_PATH=./data/bot.db
```

## Getting a Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` command
3. Follow the instructions to create your bot
4. Copy the token and paste it in your `.env` file

## Usage

### Run Everything (Bot + Admin Panel)
```bash
python run.py
```

This will start both:
- Telegram Bot (background process)
- Admin Panel at http://localhost:8000

### Run Components Separately

**Run Bot Only:**
```bash
python bot.py
```

**Run Admin Panel Only:**
```bash
python admin.py
```

Or with uvicorn:
```bash
uvicorn admin:app --host 0.0.0.0 --port 8000
```

## Admin Panel Access

- **URL:** http://localhost:8000
- **Default Username:** admin
- **Default Password:** admin123

⚠️ **Security Note:** Change the default credentials in `.env` before deploying to production!

## Database Structure

The bot uses SQLite with the following tables:
- `users` - Store user information
- `messages` - Message history
- `scheduled_messages` - Messages scheduled for future delivery
- `static_messages` - Automated messages for first N days
- `user_actions` - Activity log for statistics
- `settings` - Bot configuration

## Features in Detail

### User Management
- View all users with pagination
- Search by username, first name, or last name
- Filter by banned/active status
- Select multiple users for bulk actions
- Ban/unban users
- Delete users
- Send custom messages with HTML formatting

### Message Sending
- Send plain text or HTML formatted messages
- Live preview of HTML messages
- Send to selected users or all users
- Track message delivery status

### Scheduling
- Visual calendar interface
- Schedule messages for specific date/time
- Automatic delivery when time arrives
- View scheduled and sent messages

### Static Messages
- Configure messages for Day 0, 1, 2, etc.
- Automatically sent based on user join date
- Enable/disable individual messages
- Edit message content

### Statistics
- Real-time user counts
- Active users (last 7 days)
- Banned users count
- Recent activity log with action types
- Auto-refresh every 30 seconds

## Project Structure

```
inviter_bot/
├── bot.py              # Telegram bot main file
├── admin.py            # FastAPI admin panel
├── database.py         # Database operations
├── run.py              # Main runner script
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .gitignore          # Git ignore file
├── templates/          # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── users.html
│   ├── statistics.html
│   ├── scheduling.html
│   ├── static_messages.html
│   └── settings.html
├── static/             # Static files (created automatically)
└── data/               # Database storage (created automatically)
    └── bot.db
```

## Bot Commands

- `/start` - Start the bot and register user

## Channel Setup

To use the bot for channel member management:

1. Add your bot to the channel as an administrator
2. Give it permission to:
   - Add new members
   - Post messages
   - View member list

## Development

### Adding New Features

The codebase is organized for easy extension:

- **Database operations:** Add methods to `database.py`
- **Bot handlers:** Add handlers to `bot.py`
- **API endpoints:** Add routes to `admin.py`
- **Frontend pages:** Add templates to `templates/`

### API Endpoints

All API endpoints are prefixed with `/api/`:

- `POST /api/users/ban` - Ban users
- `POST /api/users/unban` - Unban users
- `POST /api/users/delete` - Delete users
- `POST /api/users/send-message` - Send message to users
- `POST /api/schedule/add` - Add scheduled message
- `DELETE /api/schedule/{id}` - Delete scheduled message
- `POST /api/static-messages/add` - Add static message
- `PUT /api/static-messages/{id}` - Update static message
- `DELETE /api/static-messages/{id}` - Delete static message
- `POST /api/static-messages/{id}/toggle` - Toggle message status
- `POST /api/settings` - Save settings

## Troubleshooting

### Database Issues
If you encounter database errors, delete the database file and restart:
```bash
rm -rf data/
python run.py
```

### Bot Not Responding
1. Check if BOT_TOKEN is correct in `.env`
2. Verify bot is running: `ps aux | grep bot.py`
3. Check bot logs for errors

### Admin Panel Not Loading
1. Check if port 8000 is available
2. Try accessing via http://127.0.0.1:8000
3. Check admin panel logs for errors

## Security Considerations

- Change default admin credentials
- Use HTTPS in production
- Keep BOT_TOKEN secret
- Regularly backup database
- Implement rate limiting for API endpoints
- Use environment variables for sensitive data

## License

This project is open source and available under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions:
- Open an issue on GitHub
- Check existing issues for solutions

## Roadmap

- [ ] User authentication with JWT tokens
- [ ] Multiple admin users support
- [ ] Export/import user data
- [ ] Advanced analytics dashboard
- [ ] Webhook support for real-time updates
- [ ] Multi-language support
- [ ] Rate limiting per user
- [ ] Message templates
- [ ] File attachment support
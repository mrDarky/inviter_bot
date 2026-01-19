# Quick Start Guide

## 1. Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
```

## 2. Configure

Edit `.env` file and add your bot token:
```
BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
```

Get your token from [@BotFather](https://t.me/BotFather) on Telegram.

## 3. Run

```bash
python run.py
```

## 4. Access Admin Panel

Open browser: http://localhost:8000
- Username: `admin`
- Password: `admin123`

## 5. Setup Your Channel

1. Add your bot to your Telegram channel as administrator
2. Grant permissions: Add members, Post messages, View members
3. Users who join will be automatically tracked

## Done! 🎉

Your bot is now running and tracking channel members!

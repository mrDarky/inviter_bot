#!/usr/bin/env python3
"""
Main runner script for Inviter Bot
Runs both the Telegram bot and admin panel
"""
import asyncio
import subprocess
import sys
import os
from pathlib import Path

def main():
    """Run bot and admin panel"""
    # Check if .env exists
    if not Path('.env').exists():
        print("⚠️  .env file not found!")
        print("Please copy .env.example to .env and configure your settings:")
        print("  cp .env.example .env")
        print("\nThen edit .env and add your BOT_TOKEN")
        sys.exit(1)
    
    print("🚀 Starting Inviter Bot System...")
    print("=" * 50)
    
    # Start bot in background
    print("📱 Starting Telegram Bot...")
    bot_process = subprocess.Popen(
        [sys.executable, "bot.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    # Start admin panel
    print("🌐 Starting Admin Panel...")
    print("=" * 50)
    print("\n✅ System started successfully!")
    print(f"📊 Admin Panel: http://localhost:{os.getenv('API_PORT', '8000')}")
    print("👤 Default credentials: admin / admin123")
    print("\nPress Ctrl+C to stop\n")
    
    try:
        admin_process = subprocess.run(
            [sys.executable, "admin.py"],
            check=True
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        bot_process.terminate()
        bot_process.wait()
        print("✅ Stopped successfully")

if __name__ == "__main__":
    main()

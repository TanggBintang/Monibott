import os
import json
from dotenv import load_dotenv
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, ContextTypes
import asyncio
import logging

load_dotenv()

# Import bot class
from bot import TelegramBot

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

app = Flask(__name__)

# Global variables
telegram_bot = None
bot_application = None

def initialize_bot():
    """Initialize the telegram bot"""
    global telegram_bot, bot_application
    
    # Konfigurasi
    BOT_TOKEN = os.getenv('BOT_TOKEN', "8284891962:AAHbRY1FB23MIh4TZ8qeSh6CXQ35XKH_XjQ")
    SPREADSHEET_ID = os.getenv('SPREADSHEET_ID', "1bs_6iDuxgTX4QF_FTra3YDYVsRFatwRXLQ0tiQfNZyI")
    
    if not BOT_TOKEN or not SPREADSHEET_ID:
        raise Exception("BOT_TOKEN and SPREADSHEET_ID must be set!")
    
    # Create bot instance
    telegram_bot = TelegramBot(BOT_TOKEN, SPREADSHEET_ID)
    
    # Create application for webhook
    bot_application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers from TelegramBot class
    telegram_bot.setup_handlers(bot_application)
    
    print("🤖 Bot initialized successfully!")
    return telegram_bot, bot_application

@app.route('/')
def index():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "Telegram Bot Webhook Server is running",
        "bot": "Report Bot"
    }

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook from Telegram"""
    try:
        # Get JSON data from request
        json_data = request.get_json()
        
        if not json_data:
            return {"status": "error", "message": "No JSON data received"}, 400
        
        # Create Update object
        update = Update.de_json(json_data, bot_application.bot)
        
        # Process update asynchronously
        asyncio.run(bot_application.process_update(update))
        
        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}, 500

@app.route('/set-webhook', methods=['POST'])
def set_webhook():
    """Set webhook URL for Telegram bot"""
    try:
        webhook_url = request.json.get('webhook_url')
        if not webhook_url:
            return {"status": "error", "message": "webhook_url is required"}, 400
        
        # Set webhook
        result = asyncio.run(bot_application.bot.set_webhook(url=webhook_url + '/webhook'))
        
        if result:
            return {"status": "ok", "message": f"Webhook set to {webhook_url}/webhook"}
        else:
            return {"status": "error", "message": "Failed to set webhook"}, 500
            
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route('/webhook-info', methods=['GET'])
def webhook_info():
    """Get current webhook info"""
    try:
        info = asyncio.run(bot_application.bot.get_webhook_info())
        return {
            "status": "ok",
            "webhook_info": {
                "url": info.url,
                "has_custom_certificate": info.has_custom_certificate,
                "pending_update_count": info.pending_update_count,
                "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
                "last_error_message": info.last_error_message,
                "max_connections": info.max_connections,
                "allowed_updates": info.allowed_updates
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

if __name__ == '__main__':
    try:
        # Initialize bot
        initialize_bot()
        
        # Get port from environment variable (Railway uses PORT)
        port = int(os.getenv('PORT', 5000))
        
        print(f"🚀 Starting webhook server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        exit(1)
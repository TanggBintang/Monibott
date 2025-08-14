import os
import json
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, ContextTypes
import asyncio
import logging
import traceback
from datetime import datetime

load_dotenv()

# Import bot class
from bot import TelegramBot

# Setup logging dengan format yang lebih detail
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global variables
telegram_bot = None
bot_application = None

async def initialize_bot():
    """Initialize the telegram bot"""
    global telegram_bot, bot_application
    
    try:
        # Konfigurasi
        BOT_TOKEN = os.getenv('BOT_TOKEN')
        SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
        
        if not BOT_TOKEN:
            raise Exception("BOT_TOKEN environment variable is required!")
        if not SPREADSHEET_ID:
            raise Exception("SPREADSHEET_ID environment variable is required!")
        
        logger.info("Initializing Telegram Bot...")
        logger.info(f"Bot Token: {'*' * (len(BOT_TOKEN) - 10)}{BOT_TOKEN[-10:]}")
        logger.info(f"Spreadsheet ID: {SPREADSHEET_ID}")
        
        # Create bot instance
        telegram_bot = TelegramBot(BOT_TOKEN, SPREADSHEET_ID)
        logger.info("✅ TelegramBot instance created")
        
        # Create application for webhook
        bot_application = Application.builder().token(BOT_TOKEN).build()
        logger.info("✅ Application instance created")
        
        # IMPORTANT: Initialize the application properly
        await bot_application.initialize()
        logger.info("✅ Application initialized")
        
        await bot_application.start()
        logger.info("✅ Application started")
        
        # Add handlers from TelegramBot class
        telegram_bot.setup_handlers(bot_application)
        logger.info("✅ Handlers setup complete")
        
        logger.info("🤖 Bot initialized and started successfully!")
        return telegram_bot, bot_application
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize bot: {e}")
        logger.error(traceback.format_exc())
        raise

@app.route('/')
def index():
    """Health check endpoint"""
    try:
        return jsonify({
            "status": "ok",
            "message": "Telegram Bot Webhook Server is running",
            "bot": "Report Bot",
            "timestamp": datetime.now().isoformat(),
            "bot_initialized": telegram_bot is not None,
            "application_initialized": bot_application is not None
        })
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook from Telegram"""
    try:
        # Check if bot is initialized
        if not bot_application:
            logger.error("Bot application is not initialized")
            return jsonify({
                "status": "error", 
                "message": "Bot application is not initialized"
            }), 500
        
        # Get JSON data from request
        json_data = request.get_json(force=True)
        
        if not json_data:
            logger.warning("No JSON data received")
            return jsonify({
                "status": "error", 
                "message": "No JSON data received"
            }), 400
        
        # Log incoming update (but not the full data for privacy)
        if 'message' in json_data:
            user_id = json_data.get('message', {}).get('from', {}).get('id', 'unknown')
            message_type = 'text' if json_data.get('message', {}).get('text') else 'other'
            logger.info(f"Received {message_type} message from user {user_id}")
        else:
            logger.info(f"Received update: {list(json_data.keys())}")
        
        try:
            # Create Update object
            update = Update.de_json(json_data, bot_application.bot)
            
            if not update:
                logger.warning("Failed to create Update object from JSON")
                return jsonify({
                    "status": "error", 
                    "message": "Invalid update data"
                }), 400
            
            # Process update asynchronously
            asyncio.run(bot_application.process_update(update))
            
            return jsonify({"status": "ok"})
            
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            logger.error(traceback.format_exc())
            
            # Return 200 to prevent Telegram from retrying
            return jsonify({
                "status": "error", 
                "message": "Internal processing error"
            })
        
    except Exception as e:
        logger.error(f"Critical error in webhook: {e}")
        logger.error(traceback.format_exc())
        
        # Return 500 for critical errors
        return jsonify({
            "status": "error", 
            "message": "Critical server error"
        }), 500

@app.route('/set-webhook', methods=['POST'])
def set_webhook():
    """Set webhook URL for Telegram bot"""
    try:
        if not bot_application:
            return jsonify({
                "status": "error", 
                "message": "Bot application is not initialized"
            }), 500
        
        # Get JSON data
        json_data = request.get_json()
        if not json_data:
            return jsonify({
                "status": "error", 
                "message": "JSON data with webhook_url is required"
            }), 400
            
        webhook_url = json_data.get('webhook_url')
        if not webhook_url:
            return jsonify({
                "status": "error", 
                "message": "webhook_url field is required"
            }), 400
        
        # Ensure webhook_url ends with the correct path
        if not webhook_url.endswith('/webhook'):
            webhook_url = webhook_url.rstrip('/') + '/webhook'
        
        logger.info(f"Setting webhook to: {webhook_url}")
        
        # Set webhook
        result = asyncio.run(bot_application.bot.set_webhook(url=webhook_url))
        
        if result:
            logger.info(f"✅ Webhook successfully set to {webhook_url}")
            return jsonify({
                "status": "ok", 
                "message": f"Webhook set to {webhook_url}",
                "timestamp": datetime.now().isoformat()
            })
        else:
            logger.error("Failed to set webhook")
            return jsonify({
                "status": "error", 
                "message": "Failed to set webhook"
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error", 
            "message": f"Error setting webhook: {str(e)}"
        }), 500

@app.route('/webhook-info', methods=['GET'])
def webhook_info():
    """Get current webhook info"""
    try:
        if not bot_application:
            return jsonify({
                "status": "error", 
                "message": "Bot application is not initialized"
            }), 500
        
        info = asyncio.run(bot_application.bot.get_webhook_info())
        
        return jsonify({
            "status": "ok",
            "webhook_info": {
                "url": info.url,
                "has_custom_certificate": info.has_custom_certificate,
                "pending_update_count": info.pending_update_count,
                "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
                "last_error_message": info.last_error_message,
                "max_connections": info.max_connections,
                "allowed_updates": info.allowed_updates
            },
            "timestamp": datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error getting webhook info: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error", 
            "message": f"Error getting webhook info: {str(e)}"
        }), 500

@app.route('/delete-webhook', methods=['POST'])
def delete_webhook():
    """Delete current webhook"""
    try:
        if not bot_application:
            return jsonify({
                "status": "error", 
                "message": "Bot application is not initialized"
            }), 500
        
        result = asyncio.run(bot_application.bot.delete_webhook())
        
        if result:
            logger.info("✅ Webhook deleted successfully")
            return jsonify({
                "status": "ok", 
                "message": "Webhook deleted successfully",
                "timestamp": datetime.now().isoformat()
            })
        else:
            logger.error("Failed to delete webhook")
            return jsonify({
                "status": "error", 
                "message": "Failed to delete webhook"
            }), 500
            
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error", 
            "message": f"Error deleting webhook: {str(e)}"
        }), 500

@app.route('/test', methods=['GET'])
def test():
    """Test endpoint for debugging"""
    try:
        return jsonify({
            "status": "ok",
            "message": "Test endpoint working",
            "bot_initialized": telegram_bot is not None,
            "application_initialized": bot_application is not None,
            "bot_token_set": bool(os.getenv('BOT_TOKEN')),
            "spreadsheet_id_set": bool(os.getenv('SPREADSHEET_ID')),
            "google_credentials_set": bool(os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')),
            "environment_variables": {
                "PORT": os.getenv('PORT'),
                "BOT_TOKEN": "***" + (os.getenv('BOT_TOKEN', '')[-10:] if os.getenv('BOT_TOKEN') else 'Not Set'),
                "SPREADSHEET_ID": os.getenv('SPREADSHEET_ID', 'Not Set'),
            },
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error in test endpoint: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "status": "error",
        "message": "Endpoint not found",
        "timestamp": datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({
        "status": "error",
        "message": "Internal server error",
        "timestamp": datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    try:
        logger.info("🚀 Starting Telegram Bot Webhook Server...")
        
        # Initialize bot dengan async
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(initialize_bot())
        
        # Get port from environment variable (Railway uses PORT)
        port = int(os.getenv('PORT', 5000))
        host = os.getenv('HOST', '0.0.0.0')
        
        logger.info(f"🚀 Starting Flask server on {host}:{port}")
        logger.info("✅ Server ready to receive webhooks")
        
        # Run Flask app
        app.run(host=host, port=port, debug=False, threaded=True)
        
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        logger.error(traceback.format_exc())
        exit(1)

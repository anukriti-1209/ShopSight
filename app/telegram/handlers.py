import logging
from app.models import TelegramUpdate
from app.telegram.client import telegram_client
from app.pipeline import process_order

logger = logging.getLogger(__name__)

async def handle_incoming_message(update: TelegramUpdate) -> None:
    """Handle incoming Telegram updates and route them appropriately."""
    try:
        # Ignore updates that don't contain a message
        if not update.message:
            return

        chat_id = update.message.chat.id
        # Use from_user if available
        if update.message.from_user:
            username = update.message.from_user.username
            first_name = update.message.from_user.first_name
        else:
            username = update.message.chat.username
            first_name = update.message.chat.first_name
            
        message_id = update.message.message_id
        
        # Check for /start command
        if update.message.text and update.message.text.startswith('/start'):
            welcome_text = (
                "Welcome to ShopSight! 👓\n\n"
                "You can submit orders by sending me a text description, a voice note, or a photo of a prescription.\n"
                "I will process it automatically."
            )
            await telegram_client.send_message(chat_id, welcome_text)
            return

        # Handle text
        if update.message.text:
            await telegram_client.send_message(
                chat_id, 
                "📋 Got it! Processing your order...", 
                reply_to_message_id=message_id
            )
            raw_input = update.message.text
            
            await process_order(chat_id, username, first_name, raw_input, "text")
            return

        # Handle voice note
        if update.message.voice:
            await telegram_client.send_message(
                chat_id, 
                "🎙️ Got your voice note! Processing...", 
                reply_to_message_id=message_id
            )
            file_id = update.message.voice.file_id
            media_bytes = await telegram_client.download_file_by_id(file_id)
            raw_input = "Voice Note"
            
            await process_order(chat_id, username, first_name, raw_input, "voice", media_bytes=media_bytes)
            return

        # Handle photo
        if update.message.photo:
            await telegram_client.send_message(
                chat_id, 
                "📷 Got your photo! Processing...", 
                reply_to_message_id=message_id
            )
            # The last element in the photo array is the highest resolution
            highest_res_photo = update.message.photo[-1]
            file_id = highest_res_photo.file_id
            media_bytes = await telegram_client.download_file_by_id(file_id)
            raw_input = "Photo"
            caption = update.message.caption
            
            await process_order(chat_id, username, first_name, raw_input, "photo", media_bytes=media_bytes, caption=caption)
            return

        # Handle unsupported types
        await telegram_client.send_message(
            chat_id,
            "❓ I can only process text, voice notes, and photos.",
            reply_to_message_id=message_id
        )

    except Exception as e:
        logger.exception(f"Unhandled exception in handle_incoming_message: {e}")
        # We catch everything so the background task never crashes completely

import logging
import httpx
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

class TelegramClient:
    """Async Telegram client using httpx."""
    
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.file_base = f"https://api.telegram.org/file/bot{self.token}"
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Create the underlying httpx client."""
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=30.0)
            logger.info("Telegram HTTP client started.")

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None
            logger.info("Telegram HTTP client closed.")

    async def set_webhook(self, url: str, secret_token: str, drop_pending: bool = True) -> bool:
        """Set the Telegram webhook."""
        if not self.client:
            await self.start()
        
        try:
            payload = {
                "url": url,
                "secret_token": secret_token,
                "drop_pending_updates": drop_pending
            }
            response = await self.client.post(f"{self.api_base}/setWebhook", json=payload)
            response.raise_for_status()
            logger.info("Webhook set successfully.")
            return response.json().get("ok", False)
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            return False

    async def send_message(self, chat_id: int, text: str, parse_mode: str = 'HTML', reply_to_message_id: Optional[int] = None) -> Optional[dict]:
        """Send a text message."""
        if not self.client:
            await self.start()
            
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
            
        try:
            response = await self.client.post(f"{self.api_base}/sendMessage", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
            return None

    async def get_file_path(self, file_id: str) -> Optional[str]:
        """Call getFile to retrieve the file_path."""
        if not self.client:
            await self.start()
            
        try:
            response = await self.client.get(f"{self.api_base}/getFile", params={"file_id": file_id})
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                return data["result"]["file_path"]
            logger.error(f"getFile returned not ok: {data}")
            return None
        except Exception as e:
            logger.error(f"Failed to get file path for {file_id}: {e}")
            return None

    async def download_file_bytes(self, file_path: str) -> Optional[bytes]:
        """Download a file by its file_path."""
        if not self.client:
            await self.start()
            
        try:
            url = f"{self.file_base}/{file_path}"
            response = await self.client.get(url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            logger.error(f"Failed to download file {file_path}: {e}")
            return None

    async def download_file_by_id(self, file_id: str) -> Optional[bytes]:
        """Combine get_file_path and download_file_bytes."""
        file_path = await self.get_file_path(file_id)
        if not file_path:
            return None
        return await self.download_file_bytes(file_path)

# Module-level instance
telegram_client = TelegramClient()

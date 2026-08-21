import asyncio
import logging
from typing import Optional
import httpx
from app.config import settings
from app.models import TelegramUpdate
from app.telegram.handlers import handle_incoming_message

logger = logging.getLogger(__name__)

class TelegramPoller:
    """Background polling worker for local development when a public webhook URL is not active."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_offset = 0

    async def start(self):
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("No TELEGRAM_BOT_TOKEN configured, poller disabled.")
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram background poller started (listening for live messages)... 🤖")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram background poller stopped.")

    async def _poll_loop(self):
        api_base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            while self._running:
                try:
                    url = f"{api_base}/getUpdates"
                    params = {"timeout": 10}
                    if self._last_offset > 0:
                        params["offset"] = self._last_offset + 1

                    res = await client.get(url, params=params)
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("ok") and data.get("result"):
                            for update_dict in data["result"]:
                                update_id = update_dict.get("update_id", 0)
                                if update_id > self._last_offset:
                                    self._last_offset = update_id

                                try:
                                    update = TelegramUpdate.model_validate(update_dict)
                                    # Process in background task
                                    asyncio.create_task(handle_incoming_message(update))
                                except Exception as parse_err:
                                    logger.error(f"Error parsing Telegram update: {parse_err}")

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Poller connection notice: {e}")
                    await asyncio.sleep(2)

                await asyncio.sleep(0.5)

telegram_poller = TelegramPoller()

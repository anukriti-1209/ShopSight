from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from typing import Optional
from app.config import settings
from app.models import TelegramUpdate
from app.dedup import deduplicator
from app.telegram.handlers import handle_incoming_message
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/telegram/webhook")
async def telegram_webhook(
    update: TelegramUpdate,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    # 1. Validate secret token
    if settings.TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret token")
    
    # 2. Dedup check
    if deduplicator.is_duplicate(update.update_id):
        return {"ok": True, "status": "duplicate_skipped"}
    
    # 3. Offload to background and return 200 immediately
    background_tasks.add_task(handle_incoming_message, update)
    
    return {"ok": True}

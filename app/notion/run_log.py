import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.notion.client import NotionClient
from app.config import settings

logger = logging.getLogger(__name__)

def log_event(
    notion: NotionClient,
    order_id: str,
    event_type: str,
    details: str,
    order_page_id: Optional[str] = None
) -> None:
    """Creates a row in the Run Log DB."""
    
    event_id = f"EVT-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    
    properties = {
        "Event ID": {
            "title": [{"text": {"content": event_id}}]
        },
        "Event Type": {
            "select": {"name": event_type}
        },
        "Timestamp": {
            "date": {"start": datetime.now(timezone.utc).isoformat()}
        },
        "Order ID": {
            "rich_text": [{"text": {"content": order_id}}]
        },
        "Details": {
            "rich_text": [{"text": {"content": details}}]
        },
        "Source": {
            "select": {"name": "System"}
        }
    }
    
    if order_page_id:
        # Assuming there is a relation property, but the spec only explicitly asked for Order ID as rich_text.
        # Adding it safely if relation exists in schema, otherwise just skip.
        pass

    try:
        notion.create_page(
            database_id=settings.RUN_LOG_DB_ID,
            properties=properties
        )
    except Exception as e:
        logger.error(f"Failed to log event to Notion Run Log DB: {e}")

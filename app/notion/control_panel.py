import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from app.notion.client import NotionClient
from app.config import settings

logger = logging.getLogger(__name__)

def _find_callout_block(notion: NotionClient, page_id: str, prefix: str) -> str:
    """Finds a callout block with a specific prefix text on the given page."""
    blocks = notion.get_block_children(page_id)
    for block in blocks:
        if block.get("type") == "callout":
            rich_text = block["callout"].get("rich_text", [])
            if rich_text:
                content = rich_text[0].get("plain_text", "")
                if content.startswith(prefix):
                    return block["id"]
    return None

def update_heartbeat(notion: NotionClient, control_panel_page_id: str) -> None:
    """Finds or creates a callout block with heartbeat status, updates it with current timestamp."""
    try:
        current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text_content = f"Heartbeat: 🟢 System Running (Last checked: {current_time})"
        
        block_data = {
            "callout": {
                "rich_text": [{"text": {"content": text_content}}],
                "icon": {"type": "emoji", "emoji": "🟢"}
            }
        }
        
        existing_block_id = _find_callout_block(notion, control_panel_page_id, "Heartbeat:")
        
        if existing_block_id:
            notion.update_block(existing_block_id, block_data)
        else:
            notion.append_block_children(
                control_panel_page_id,
                [{"type": "callout", **block_data}]
            )
    except Exception as e:
        logger.error(f"Failed to update heartbeat in control panel: {e}")


def update_daily_counts(notion: NotionClient, control_panel_page_id: str) -> None:
    """Queries Orders DB for today's counts and updates a callout block."""
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        filter_conditions = {
            "property": "Created At",
            "date": {
                "on_or_after": today_start
            }
        }
        
        orders = notion.query_all_pages(database_id=settings.ORDERS_DB_ID, filter_conditions=filter_conditions)
        
        counts = {
            "received": len(orders),
            "auto-approved": 0,
            "pending": 0,
            "ready": 0
        }
        
        for order in orders:
            props = order.get("properties", {})
            status_prop = props.get("Status", {}).get("select")
            if status_prop:
                status = status_prop.get("name")
                if status == "Auto-Approved":
                    counts["auto-approved"] += 1
                elif status in ("Pending Review", "Needs Approval"):
                    counts["pending"] += 1
                elif status == "Ready":
                    counts["ready"] += 1
                    
        text_content = (
            f"Daily Counts: "
            f"Received: {counts['received']} | "
            f"Auto-Approved: {counts['auto-approved']} | "
            f"Pending: {counts['pending']} | "
            f"Ready: {counts['ready']}"
        )
        
        block_data = {
            "callout": {
                "rich_text": [{"text": {"content": text_content}}],
                "icon": {"type": "emoji", "emoji": "📊"}
            }
        }
        
        existing_block_id = _find_callout_block(notion, control_panel_page_id, "Daily Counts:")
        
        if existing_block_id:
            notion.update_block(existing_block_id, block_data)
        else:
            notion.append_block_children(
                control_panel_page_id,
                [{"type": "callout", **block_data}]
            )
    except Exception as e:
        logger.error(f"Failed to update daily counts in control panel: {e}")

async def update_heartbeat_job() -> None:
    """Scheduled job to update the Notion control panel heartbeat and daily counts."""
    try:
        from app.notion.client import NotionClient
        from app.config import settings
        if not settings.CONTROL_PANEL_PAGE_ID:
            logger.warning("No CONTROL_PANEL_PAGE_ID set, skipping heartbeat update.")
            return
            
        client = NotionClient()
        update_heartbeat(client, settings.CONTROL_PANEL_PAGE_ID)
        update_daily_counts(client, settings.CONTROL_PANEL_PAGE_ID)
        if hasattr(client, 'close'):
            client.close()
    except Exception as e:
        logger.error(f"Error in update_heartbeat_job: {e}")

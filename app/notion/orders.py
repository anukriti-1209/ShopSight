import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from app.notion.client import NotionClient
from app.models import OrderData
from app.config import settings
from app.blueprints.base import BlueprintConfig
from app.blueprints.loader import get_active_blueprint

logger = logging.getLogger(__name__)


def _rich_text(content: Optional[str]) -> Dict[str, Any]:
    """Build a Notion rich_text property value."""
    if not content:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": str(content)[:2000]}}]}


def _number(value: Optional[float | int]) -> Dict[str, Any]:
    """Build a Notion number property value."""
    if value is None:
        return {"number": None}
    return {"number": float(value)}


def _select(name: Optional[str]) -> Dict[str, Any]:
    """Build a Notion select property value."""
    if not name:
        return {"select": None}
    return {"select": {"name": str(name)}}


def _date(iso_date_str: str) -> Dict[str, Any]:
    """Build a Notion date property value."""
    return {"date": {"start": iso_date_str}}


def create_order(order_data: OrderData, notion: NotionClient, blueprint: Optional[BlueprintConfig] = None) -> str:
    """Creates a row in the Orders DB and returns the Notion page ID dynamically based on blueprint."""
    bp = blueprint or get_active_blueprint()
    ext = order_data.extraction

    properties: Dict[str, Any] = {
        "Order ID": {"title": [{"text": {"content": order_data.order_id}}]},
        "Raw Input": _rich_text(order_data.raw_input),
        "Customer Name": _rich_text(ext.customer_name or order_data.telegram_first_name),
        "Customer Phone": _rich_text(ext.customer_phone),
        "Telegram Chat ID": _number(order_data.telegram_chat_id),
        "Telegram Username": _rich_text(order_data.telegram_username),
        "Confidence": _number(ext.confidence),
        "AI Explanation": _rich_text(ext.explanation),
        "Status": _select(order_data.status),
        "Urgency": _select(ext.urgency or "Normal"),
        "Estimated Value": _number(ext.estimated_value),
        "Input Type": _select(order_data.input_type.capitalize()),
        "Created At": _date(order_data.created_at),
    }

    # Add dynamic blueprint fields if present
    for field in bp.fields:
        val = ext.get_field_value(field.name)
        if field.notion_type == "select":
            properties[field.label] = _select(val)
        elif field.notion_type == "number":
            properties[field.label] = _number(val)
        else:
            properties[field.label] = _rich_text(val)

    # Add mismatch flags if verification was run
    if order_data.verification and order_data.verification.has_mismatches:
        mismatch_text = "; ".join(order_data.verification.mismatch_details)
        properties["Mismatch Flags"] = _rich_text(mismatch_text)
    else:
        properties["Mismatch Flags"] = _rich_text(None)

    response = notion.create_page(
        database_id=settings.ORDERS_DB_ID,
        properties=properties,
    )
    page_id = response["id"]
    logger.info(f"Created order {order_data.order_id} in Notion: {page_id}")
    return page_id


def query_pending_orders(notion: NotionClient) -> List[Dict[str, Any]]:
    """Query orders with status 'Needs Approval'."""
    return notion.query_all_pages(
        database_id=settings.ORDERS_DB_ID,
        filter_conditions={"property": "Status", "select": {"equals": "Needs Approval"}},
    )


def query_stale_orders(notion: NotionClient, threshold_minutes: int) -> List[Dict[str, Any]]:
    """Query orders with status 'Needs Approval' AND created_at older than threshold."""
    threshold_time = (datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)).isoformat()
    return notion.query_all_pages(
        database_id=settings.ORDERS_DB_ID,
        filter_conditions={
            "and": [
                {"property": "Status", "select": {"equals": "Needs Approval"}},
                {"property": "Created At", "date": {"before": threshold_time}},
            ]
        },
    )


def query_orders_by_status(notion: NotionClient, status: str) -> List[Dict[str, Any]]:
    """Query orders by a specific status."""
    return notion.query_all_pages(
        database_id=settings.ORDERS_DB_ID,
        filter_conditions={"property": "Status", "select": {"equals": status}},
    )


def update_order_status(notion: NotionClient, page_id: str, new_status: str) -> None:
    """Update the status of an order."""
    notion.update_page(page_id, {"Status": _select(new_status)})


def update_order_urgency(notion: NotionClient, page_id: str, urgency: str) -> None:
    """Update the urgency of an order."""
    notion.update_page(page_id, {"Urgency": _select(urgency)})


def extract_property_value(page: Dict[str, Any], property_name: str, prop_type: Optional[str] = None) -> Any:
    """Safely extract a value from a Notion page property."""
    props = page.get("properties", {})
    prop = props.get(property_name, {})
    detected_type = prop.get("type") or prop_type

    if not detected_type:
        return None

    if detected_type in ("rich_text", "title"):
        text_arr = prop.get(detected_type, [])
        return "".join(t.get("plain_text", "") for t in text_arr) or None
    elif detected_type == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    elif detected_type == "number":
        return prop.get("number")
    elif detected_type == "date":
        date_obj = prop.get("date")
        return date_obj.get("start") if date_obj else None
    elif detected_type == "checkbox":
        return prop.get("checkbox")

    return None

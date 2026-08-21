import sys
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.notion.client import NotionClient
from app.config import settings
from app.blueprints.loader import get_blueprint, list_available_blueprints

def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a Notion workspace for any ShopSight Industry Blueprint.")
    parser.add_argument("--blueprint", default=getattr(settings, "ACTIVE_BLUEPRINT", "optical"), help="Blueprint ID (optical, dental, auto_repair, custom_tailoring)")
    args = parser.parse_args()

    bp = get_blueprint(args.blueprint)
    if not bp:
        print(f"Error: Blueprint '{args.blueprint}' not found.")
        print("Available blueprints:", [b["id"] for b in list_available_blueprints()])
        sys.exit(1)

    if not settings.NOTION_TOKEN or not settings.NOTION_PARENT_PAGE_ID:
        print("Error: NOTION_TOKEN and NOTION_PARENT_PAGE_ID must be set in .env")
        sys.exit(1)

    print(f"Initializing Notion Client for blueprint: {bp.display_name} ({bp.id})...")
    client = NotionClient(settings.NOTION_TOKEN)
    parent_page_id = settings.NOTION_PARENT_PAGE_ID

    # Build core base properties
    orders_db_properties = {
        "Order ID": {"title": {}},
        "Raw Input": {"rich_text": {}},
        "Customer Name": {"rich_text": {}},
        "Customer Phone": {"rich_text": {}},
        "Telegram Chat ID": {"number": {"format": "number"}},
        "Telegram Username": {"rich_text": {}},
        "Confidence": {"number": {"format": "percent"}},
        "Mismatch Flags": {"rich_text": {}},
        "AI Explanation": {"rich_text": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Pending Review", "color": "default"},
                    {"name": "Needs Approval", "color": "yellow"},
                    {"name": "Auto-Approved", "color": "green"},
                    {"name": "Approved", "color": "green"},
                    {"name": "Approved ✓", "color": "green"},
                    {"name": "Rejected", "color": "red"},
                    {"name": "Ready", "color": "blue"},
                    {"name": "Ready ✓", "color": "blue"},
                    {"name": "Needs Human", "color": "red"},
                ]
            }
        },
        "Urgency": {
            "select": {
                "options": [
                    {"name": "Normal", "color": "default"},
                    {"name": "High", "color": "red"},
                ]
            }
        },
        "Estimated Value": {"number": {"format": "number"}},
        "Input Type": {
            "select": {
                "options": [
                    {"name": "Text", "color": "default"},
                    {"name": "Voice", "color": "purple"},
                    {"name": "Photo", "color": "blue"},
                ]
            }
        },
        "Created At": {"date": {}},
    }

    # Add dynamic blueprint fields
    for field in bp.fields:
        if field.notion_type == "select" and field.options:
            orders_db_properties[field.label] = {
                "select": {
                    "options": [{"name": opt.name, "color": opt.color} for opt in field.options]
                }
            }
        elif field.notion_type == "number":
            orders_db_properties[field.label] = {"number": {"format": "number"}}
        else:
            orders_db_properties[field.label] = {"rich_text": {}}

    print(f"Creating {bp.display_name} Orders Database...")
    try:
        orders_db = client.create_database(
            parent_page_id=parent_page_id,
            title=f"{bp.display_name} Orders Database",
            properties=orders_db_properties,
            icon_emoji="📦"
        )
        orders_db_id = orders_db["id"]
        print(f"[OK] Created Orders Database: {orders_db_id}")
    except Exception as e:
        print(f"[ERROR] Failed to create Orders DB: {e}")
        return

    print("Creating Automation Run Log Database...")
    run_log_db_properties = {
        "Event ID": {"title": {}},
        "Order ID": {"rich_text": {}},
        "Event Type": {
            "select": {
                "options": [
                    {"name": "received", "color": "blue"},
                    {"name": "transcribed", "color": "purple"},
                    {"name": "extracted", "color": "blue"},
                    {"name": "verification_run", "color": "orange"},
                    {"name": "flagged", "color": "yellow"},
                    {"name": "auto_approved", "color": "green"},
                    {"name": "needs_approval", "color": "yellow"},
                    {"name": "approved", "color": "green"},
                    {"name": "rejected", "color": "red"},
                    {"name": "reminder_sent", "color": "orange"},
                    {"name": "vendor_order_sent", "color": "blue"},
                    {"name": "customer_notified", "color": "green"},
                    {"name": "ready_for_pickup", "color": "green"},
                    {"name": "error", "color": "red"},
                    {"name": "needs_human", "color": "red"},
                ]
            }
        },
        "Details": {"rich_text": {}},
        "Timestamp": {"date": {}},
        "Source": {
            "select": {
                "options": [
                    {"name": "System", "color": "blue"},
                    {"name": "Admin", "color": "purple"},
                ]
            }
        },
    }

    try:
        run_log_db = client.create_database(
            parent_page_id=parent_page_id,
            title=f"{bp.display_name} Run Log",
            properties=run_log_db_properties,
            icon_emoji="📜"
        )
        run_log_db_id = run_log_db["id"]
        print(f"[OK] Created Run Log Database: {run_log_db_id}")
    except Exception as e:
        print(f"[ERROR] Failed to create Run Log DB: {e}")
        return

    clean_orders_id = orders_db_id.replace("-", "")
    clean_run_log_id = run_log_db_id.replace("-", "")
    orders_url = f"https://www.notion.so/{clean_orders_id}"
    run_log_url = f"https://www.notion.so/{clean_run_log_id}"

    print(f"Creating Control Panel for {bp.display_name}...")
    children = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": f"Welcome to ShopSight — {bp.display_name} automated intake and dispatch system."}}],
                "icon": {"type": "emoji", "emoji": "⚡"}
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔔 Needs Your Approval"}}]}
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [
                {"type": "text", "text": {"content": "👉 Open "}},
                {"type": "text", "text": {"content": f"{bp.display_name} Orders (Needs Approval View)", "link": {"url": orders_url}}}
            ]}
        },
        {
            "object": "block",
            "type": "divider",
            "divider": {}
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "⚡ System Status"}}]}
        },
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "🟢 System Running — Heartbeat active"}}],
                "icon": {"type": "emoji", "emoji": "⚡"}
            }
        },
        {
            "object": "block",
            "type": "divider",
            "divider": {}
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📜 Automation Run Log"}}]}
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [
                {"type": "text", "text": {"content": "👉 Open "}},
                {"type": "text", "text": {"content": "Code-Written Run Log Database", "link": {"url": run_log_url}}}
            ]}
        }
    ]

    try:
        control_panel = client.create_standalone_page(
            parent_page_id=parent_page_id,
            title=f"ShopSight - {bp.display_name} Control Panel",
            icon_emoji="🎛️",
            children=children
        )
        control_panel_id = control_panel["id"]
        print(f"[OK] Created Control Panel Page: {control_panel_id}")
    except Exception as e:
        print(f"[ERROR] Failed to create Control Panel page: {e}")
        return

    print("\n🎉 Provisioning complete for blueprint:", bp.id)
    print(f"ORDERS_DB_ID={orders_db_id}")
    print(f"RUN_LOG_DB_ID={run_log_db_id}")
    print(f"CONTROL_PANEL_PAGE_ID={control_panel_id}")

if __name__ == "__main__":
    main()

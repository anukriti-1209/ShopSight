import logging
from datetime import datetime, timezone, timedelta
from app.config import settings

logger = logging.getLogger(__name__)


def _is_shop_hours() -> bool:
    """Check if current time (IST) is within shop hours."""
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    return settings.SHOP_HOURS_START <= now.hour < settings.SHOP_HOURS_END


async def check_sla_escalation():
    """Periodic job: check for orders stuck in 'Needs Approval' past the SLA threshold.
    
    Also polls for status changes made by the admin in Notion (Approved / Ready).
    """
    from app.notion.client import NotionClient
    from app.notion.orders import (
        query_stale_orders, update_order_urgency,
        query_orders_by_status, update_order_status,
        extract_property_value,
    )
    from app.notion.run_log import log_event
    from app.telegram.client import telegram_client
    
    logger.info("Running SLA escalation check...")
    notion = NotionClient()
    
    try:
        # === Part 1: SLA Escalation ===
        if _is_shop_hours():
            stale_orders = query_stale_orders(notion, settings.SLA_THRESHOLD_MINUTES)
            for order in stale_orders:
                page_id = order["id"]
                order_id = extract_property_value(order, "Order ID", "title")
                urgency = extract_property_value(order, "Urgency", "select")
                
                if urgency == "High":
                    continue  # Already escalated
                
                logger.warning(f"Escalating order {order_id} — past SLA threshold")
                
                # Update urgency in Notion
                update_order_urgency(notion, page_id, "High")
                
                # Send Telegram alert to admin
                try:
                    await telegram_client.send_message(
                        chat_id=settings.ADMIN_CHAT_ID,
                        text=f"⚠️ <b>Order {order_id}</b> has been waiting for your approval for over {settings.SLA_THRESHOLD_MINUTES} minutes.\n\nPlease review it in Notion.",
                    )
                except Exception as e:
                    logger.error(f"Failed to send escalation alert: {e}")
                
                # Log the escalation
                log_event(notion, order_id or "unknown", "reminder_sent",
                         f"SLA escalation — order pending > {settings.SLA_THRESHOLD_MINUTES} min",
                         order_page_id=page_id)
        
        # === Part 2: Poll for Admin Actions (Approved / Ready) ===
        await _poll_approval_changes(notion)
        
    except Exception as e:
        logger.error(f"SLA escalation check failed: {e}", exc_info=True)
    finally:
        notion.close()


async def _poll_approval_changes(notion):
    """Check for orders the admin has approved or marked as ready in Notion."""
    from app.notion.orders import query_orders_by_status, update_order_status, extract_property_value
    from app.notion.run_log import log_event
    from app.telegram.client import telegram_client
    from app.vendor.pdf import generate_lab_order_pdf
    from app.vendor.email_sender import send_lab_order_email
    
    # Check for newly approved orders
    approved_orders = query_orders_by_status(notion, "Approved")
    for order in approved_orders:
        page_id = order["id"]
        order_id = extract_property_value(order, "Order ID", "title") or "unknown"
        chat_id = extract_property_value(order, "Telegram Chat ID", "number")
        customer_name = extract_property_value(order, "Customer Name", "rich_text") or "Customer"
        
        logger.info(f"Processing approved order {order_id}")
        
        try:
            # Generate vendor PDF
            order_data = _build_order_dict_from_page(order)
            pdf_bytes = generate_lab_order_pdf(order_data)
            
            # Email PDF to vendor
            email_sent = send_lab_order_email(
                to_email=settings.VENDOR_EMAIL,
                order_id=order_id,
                pdf_bytes=pdf_bytes,
            )
            
            if email_sent:
                log_event(notion, order_id, "vendor_order_sent",
                         f"Lab order PDF emailed to {settings.VENDOR_EMAIL}",
                         order_page_id=page_id)
            
            # Notify customer
            if chat_id:
                try:
                    await telegram_client.send_message(
                        chat_id=int(chat_id),
                        text=f"✅ <b>Order Confirmed!</b>\n\nHi {customer_name}, your order <b>{order_id}</b> has been approved and sent to our lab.\n\n📅 <b>Estimated ready:</b> 2-3 business days\n\nWe'll notify you when it's ready for pickup! 👓",
                    )
                    log_event(notion, order_id, "customer_notified",
                             "Customer sent approval confirmation with ETA",
                             order_page_id=page_id)
                except Exception as e:
                    logger.error(f"Failed to notify customer for {order_id}: {e}")
            
            # Update status to prevent re-processing
            update_order_status(notion, page_id, "Approved ✓")
            log_event(notion, order_id, "approved",
                     "Order approved by admin, vendor PDF sent, customer notified",
                     order_page_id=page_id)
            
        except Exception as e:
            logger.error(f"Error processing approved order {order_id}: {e}", exc_info=True)
            log_event(notion, order_id, "error", f"Error processing approval: {str(e)}",
                     order_page_id=page_id)
    
    # Check for orders marked as Ready
    ready_orders = query_orders_by_status(notion, "Ready")
    for order in ready_orders:
        page_id = order["id"]
        order_id = extract_property_value(order, "Order ID", "title") or "unknown"
        chat_id = extract_property_value(order, "Telegram Chat ID", "number")
        customer_name = extract_property_value(order, "Customer Name", "rich_text") or "Customer"
        
        if chat_id:
            try:
                await telegram_client.send_message(
                    chat_id=int(chat_id),
                    text=f"🎉 <b>Ready for Pickup!</b>\n\nHi {customer_name}, great news! Your order <b>{order_id}</b> is ready.\n\n📍 Pick it up at the shop at your convenience.\n\nThank you for choosing us! 👓",
                )
                log_event(notion, order_id, "ready_for_pickup",
                         "Customer notified — order ready for pickup",
                         order_page_id=page_id)
            except Exception as e:
                logger.error(f"Failed to send ready notification for {order_id}: {e}")
        
        # Update status to prevent re-processing
        update_order_status(notion, page_id, "Ready ✓")


def _build_order_dict_from_page(page: dict) -> dict:
    """Build order dict from Notion page for PDF generation."""
    from app.notion.orders import extract_property_value
    from datetime import datetime
    
    return {
        "order_id": extract_property_value(page, "Order ID", "title") or "N/A",
        "customer_name": extract_property_value(page, "Customer Name", "rich_text") or "N/A",
        "order_date": datetime.now().strftime("%Y-%m-%d"),
        "frame_info": extract_property_value(page, "Frame Info", "rich_text") or "Not specified",
        "lens_type": extract_property_value(page, "Lens Type", "select") or "Single Vision",
        "od_sph": extract_property_value(page, "OD SPH", "rich_text") or "—",
        "od_cyl": extract_property_value(page, "OD CYL", "rich_text") or "—",
        "od_axis": extract_property_value(page, "OD AXIS", "rich_text") or "—",
        "od_add": extract_property_value(page, "OD ADD", "rich_text") or "—",
        "od_pd": extract_property_value(page, "PD", "rich_text") or "—",
        "os_sph": extract_property_value(page, "OS SPH", "rich_text") or "—",
        "os_cyl": extract_property_value(page, "OS CYL", "rich_text") or "—",
        "os_axis": extract_property_value(page, "OS AXIS", "rich_text") or "—",
        "os_add": extract_property_value(page, "OS ADD", "rich_text") or "—",
        "os_pd": extract_property_value(page, "PD", "rich_text") or "—",
        "notes": extract_property_value(page, "AI Explanation", "rich_text") or "Standard order",
    }

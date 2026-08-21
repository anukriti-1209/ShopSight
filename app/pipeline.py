import logging
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional

from app.config import settings
from app.models import OrderData, PrescriptionExtraction, VerificationResult
from app.blueprints.loader import get_active_blueprint

logger = logging.getLogger(__name__)


async def process_order(
    chat_id: int,
    username: Optional[str],
    first_name: Optional[str],
    raw_input: str,
    input_type: str,
    media_bytes: Optional[bytes] = None,
    caption: Optional[str] = None,
) -> None:
    """Universal order processing pipeline across all industry blueprints."""
    from app.approval.engine import determine_approval_status
    from app.notion.client import NotionClient
    from app.notion.orders import create_order
    from app.notion.run_log import log_event
    from app.telegram.client import telegram_client
    
    bp = get_active_blueprint()
    order_id = f"ORD-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:4]}"
    notion = NotionClient()
    
    try:
        # === Step 1: AI Extraction (Groq or Gemini) ===
        logger.info(f"[{order_id}] Starting extraction ({bp.id}) for {input_type} from chat {chat_id}")
        
        extraction: Optional[PrescriptionExtraction] = None
        
        # Check DEV_MODE cache first
        from app.gemini.cache import gemini_cache
        cache_key = media_bytes if media_bytes else raw_input
        if gemini_cache and gemini_cache.enabled:
            cached = gemini_cache.get(cache_key)
            if cached:
                extraction = PrescriptionExtraction.model_validate_json(cached)
                logger.info(f"[{order_id}] Using cached extraction")
        
        if extraction is None:
            # Check for Groq API first
            if settings.GROQ_API_KEY:
                try:
                    from app.groq_service import GroqService
                    groq_svc = GroqService(settings.GROQ_API_KEY)
                    
                    if input_type == "voice" and media_bytes:
                        extraction = groq_svc.extract_from_voice(media_bytes, blueprint=bp)
                    elif input_type == "photo" and media_bytes:
                        extraction = groq_svc.extract_from_photo(media_bytes, caption, blueprint=bp)
                    else:
                        extraction = groq_svc.extract_from_text(raw_input, blueprint=bp)
                    logger.info(f"[{order_id}] Groq extraction succeeded: confidence={extraction.confidence}")
                except Exception as e:
                    logger.error(f"[{order_id}] Groq extraction error: {e}", exc_info=True)
            
            # Fallback to Gemini if extraction still None
            if extraction is None:
                from app.gemini.client import gemini_client
                from app.gemini.extraction import extract_from_text, extract_from_voice, extract_from_photo
                if gemini_client is not None:
                    try:
                        if input_type == "voice" and media_bytes:
                            extraction = await extract_from_voice(gemini_client, media_bytes)
                        elif input_type == "photo" and media_bytes:
                            extraction = await extract_from_photo(gemini_client, media_bytes, caption)
                        else:
                            extraction = await extract_from_text(gemini_client, raw_input)
                    except Exception as e:
                        logger.error(f"[{order_id}] Gemini extraction failed: {e}")
            
            # If both failed or not configured
            if extraction is None:
                extraction = PrescriptionExtraction(
                    confidence=0.0,
                    explanation="AI extraction service unavailable (neither Groq nor Gemini key configured)",
                    raw_input_type=input_type,
                )
            elif gemini_cache and gemini_cache.enabled:
                gemini_cache.put(cache_key, extraction.model_dump_json())
        
        # Use transcription as raw_input for voice/photo if available
        if extraction.transcription and input_type in ("voice", "photo"):
            raw_input = extraction.transcription
        
        # === Step 2: Conditional Verification ===
        from app.gemini.verification import should_verify
        verification: Optional[VerificationResult] = None
        
        if should_verify(extraction):
            logger.info(f"[{order_id}] Running verification pass")
            try:
                if settings.GROQ_API_KEY:
                    from app.groq_service import GroqService
                    groq_svc = GroqService(settings.GROQ_API_KEY)
                    verification = groq_svc.verify_extraction(raw_input, extraction)
                else:
                    from app.gemini.client import gemini_client
                    from app.gemini.verification import verify_extraction
                    if gemini_client:
                        verification = await verify_extraction(gemini_client, raw_input, extraction)
                        
                if verification and verification.has_mismatches:
                    logger.warning(f"[{order_id}] Verification found mismatches: {verification.mismatch_details}")
            except Exception as e:
                logger.error(f"[{order_id}] Verification failed: {e}")
        
        # === Step 3: Determine Approval Status ===
        status, explanation = determine_approval_status(extraction, verification, blueprint=bp)
        extraction.explanation = explanation  # Update with full explanation
        logger.info(f"[{order_id}] Status: {status}")
        
        # === Step 4: Create Order in Notion ===
        order_data = OrderData(
            order_id=order_id,
            telegram_chat_id=chat_id,
            telegram_username=username,
            telegram_first_name=first_name,
            raw_input=raw_input[:2000],
            input_type=input_type,
            extraction=extraction,
            verification=verification,
            status=status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        
        try:
            page_id = create_order(order_data, notion, blueprint=bp)
            order_data.notion_page_id = page_id
        except Exception as e:
            logger.error(f"[{order_id}] Failed to create order in Notion: {e}")
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ We received your order but encountered an issue saving it. Our team has been notified.",
            )
            return
        
        # === Step 5: Log Events ===
        try:
            log_event(notion, order_id, "received",
                     f"Order received via {input_type} from Telegram user {username or chat_id}",
                     order_page_id=page_id)
            log_event(notion, order_id, "extracted",
                     f"Extraction complete ({bp.id}) — confidence: {extraction.confidence:.2f}",
                     order_page_id=page_id)
            if verification:
                log_event(notion, order_id, "verification_run",
                         f"Verification: {'mismatches found' if verification.has_mismatches else 'no issues'}",
                         order_page_id=page_id)
        except Exception as e:
            logger.error(f"[{order_id}] Failed to log events: {e}")
        
        # === Step 6: Handle based on status ===
        if status == "Auto-Approved":
            await _handle_auto_approved(order_id, order_data, page_id, notion, blueprint=bp)
        elif status == "Needs Approval":
            log_event(notion, order_id, "needs_approval",
                     f"Order queued for manual review: {explanation}",
                     order_page_id=page_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text=f"📋 Your order <b>{order_id}</b> has been received and is queued for verification.\n\nWe'll notify you once confirmed!",
            )
        elif status == "Needs Human":
            log_event(notion, order_id, "needs_human",
                     f"Order could not be automatically processed: {explanation}",
                     order_page_id=page_id)
            await telegram_client.send_message(
                chat_id=chat_id,
                text="📋 We received your message but couldn't fully understand the order details. Our team will review it manually and follow up soon!",
            )
        
    except Exception as e:
        logger.exception(f"[{order_id}] Pipeline failed: {e}")
        try:
            await telegram_client.send_message(
                chat_id=chat_id,
                text="⚠️ Something went wrong processing your order. Our team has been notified and will follow up shortly.",
            )
        except Exception:
            pass
    finally:
        notion.close()


async def _handle_auto_approved(
    order_id: str,
    order_data: OrderData,
    page_id: str,
    notion,
    blueprint=None,
) -> None:
    """Handle auto-approved orders: generate PDF, email vendor, notify customer."""
    from app.notion.run_log import log_event
    from app.telegram.client import telegram_client
    from app.vendor.pdf import generate_lab_order_pdf
    from app.vendor.email_sender import send_lab_order_email
    from app.notion.orders import update_order_status
    
    bp = blueprint or get_active_blueprint()
    ext = order_data.extraction
    
    log_event(notion, order_id, "auto_approved",
             f"Auto-approved: high confidence ({ext.confidence:.2f})",
             order_page_id=page_id)
    
    # Build complete dictionary for PDF
    try:
        pdf_data = ext.model_dump()
        pdf_data["order_id"] = order_id
        pdf_data["customer_name"] = ext.customer_name or order_data.telegram_first_name or "Client"
        pdf_data["order_date"] = datetime.now().strftime("%Y-%m-%d")
        pdf_data["notes"] = ext.explanation or "Standard job dispatch"
        
        pdf_bytes = generate_lab_order_pdf(pdf_data, blueprint=bp)
        
        # Email to vendor / supplier if configured
        if settings.VENDOR_EMAIL and "example.com" not in settings.VENDOR_EMAIL:
            email_sent = send_lab_order_email(
                to_email=settings.VENDOR_EMAIL,
                order_id=order_id,
                pdf_bytes=pdf_bytes,
            )
            if email_sent:
                log_event(notion, order_id, "vendor_order_sent",
                         f"Lab order PDF dispatched to {settings.VENDOR_EMAIL}",
                         order_page_id=page_id)
    except Exception as e:
        logger.error(f"[{order_id}] PDF generation/dispatch notice: {e}")
    
    # Notify customer
    customer_name = ext.customer_name or order_data.telegram_first_name or "there"
    try:
        await telegram_client.send_message(
            chat_id=order_data.telegram_chat_id,
            text=f"✅ <b>Order Confirmed!</b>\n\nHi {customer_name}, your order <b>{order_id}</b> has been verified and sent for processing!\n\n📅 <b>Estimated ready:</b> 2-3 business days\n\nWe'll notify you as soon as it's ready for pickup!",
        )
        log_event(notion, order_id, "customer_notified",
                 "Customer sent confirmation with estimated turnaround",
                 order_page_id=page_id)
    except Exception as e:
        logger.error(f"[{order_id}] Failed to notify customer: {e}")
    
    # Update status to mark as processed
    try:
        update_order_status(notion, page_id, "Auto-Approved ✓")
    except Exception as e:
        logger.error(f"[{order_id}] Failed to update status: {e}")

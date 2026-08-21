import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.telegram.client import telegram_client
from app.telegram.webhook import router as webhook_router
from app.blueprints.loader import get_active_blueprint, list_available_blueprints, get_blueprint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Scheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # === STARTUP ===
    bp = get_active_blueprint()
    logger.info(f"Starting ShopSight with active blueprint: {bp.display_name} ({bp.id})...")
    
    # 1. Initialize Telegram client and set webhook (or start local poller)
    await telegram_client.start()
    webhook_url = settings.TELEGRAM_WEBHOOK_URL
    if webhook_url and "your-render-app" not in webhook_url and "localhost" not in webhook_url:
        try:
            result = await telegram_client.set_webhook(
                url=webhook_url,
                secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
            )
            logger.info(f"Telegram webhook set: {result}")
        except Exception as e:
            logger.error(f"Failed to set Telegram webhook: {e}")
    else:
        from app.telegram.poller import telegram_poller
        await telegram_poller.start()
    
    # 2. Initialize Gemini client (if key present)
    if settings.GEMINI_API_KEYS:
        try:
            from app.gemini.client import GeminiClient
            import app.gemini.client as gemini_module
            gemini_module.gemini_client = GeminiClient()
            logger.info("Gemini client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
    
    # 3. Initialize Gemini cache (DEV_MODE only)
    try:
        from app.gemini.cache import GeminiCache
        import app.gemini.cache as cache_module
        cache_module.gemini_cache = GeminiCache(enabled=settings.DEV_MODE)
    except Exception as e:
        logger.error(f"Failed to initialize Gemini cache: {e}")
    
    # 4. Start APScheduler for periodic jobs
    try:
        from app.approval.escalation import check_sla_escalation
        from app.notion.control_panel import update_heartbeat_job
        
        scheduler.add_job(
            check_sla_escalation,
            trigger=IntervalTrigger(minutes=15),
            id="sla_escalation_check",
            name="SLA Escalation & Approval Polling",
            replace_existing=True,
            next_run_time=datetime.now(),
        )
        
        scheduler.add_job(
            update_heartbeat_job,
            trigger=IntervalTrigger(minutes=5),
            id="heartbeat_update",
            name="Control Panel Heartbeat",
            replace_existing=True,
            next_run_time=datetime.now(),
        )
        
        scheduler.start()
        logger.info("APScheduler started with SLA escalation and heartbeat jobs")
    except Exception as e:
        logger.error(f"Failed to start APScheduler: {e}")
    
    logger.info("ShopSight started successfully! 🟢")
    
    yield
    
    # === SHUTDOWN ===
    logger.info("Shutting down ShopSight...")
    
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    
    try:
        from app.telegram.poller import telegram_poller
        await telegram_poller.stop()
    except Exception:
        pass

    await telegram_client.close()
    logger.info("ShopSight shut down. 🔴")


# Create FastAPI app
app = FastAPI(
    title="ShopSight Universal OS",
    description="Universal Conversational Intake & Approval Ecosystem",
    version="2.0.0",
    lifespan=lifespan,
)

# Include webhook router
app.include_router(webhook_router)


# === Web Dashboard Routes ===

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the clean Operations Hub Web Dashboard."""
    template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>ShopSight Operations Hub</h1><p>Dashboard loading...</p>")


@app.get("/api/blueprints")
async def get_blueprints():
    """List all available industry blueprints."""
    return {
        "active": get_active_blueprint().model_dump(),
        "available": list_available_blueprints()
    }


@app.post("/api/blueprints/switch")
async def switch_blueprint(blueprint_id: str):
    """Switch active blueprint dynamically at runtime."""
    bp = get_blueprint(blueprint_id)
    if not bp:
        raise HTTPException(status_code=404, detail=f"Blueprint '{blueprint_id}' not found")

    settings.ACTIVE_BLUEPRINT = blueprint_id
    
    # Persist in .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            content = env_path.read_text(encoding="utf-8")
            if "ACTIVE_BLUEPRINT=" in content:
                import re
                content = re.sub(r"ACTIVE_BLUEPRINT=.*", f"ACTIVE_BLUEPRINT={blueprint_id}", content)
            else:
                content += f"\nACTIVE_BLUEPRINT={blueprint_id}\n"
            env_path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not persist ACTIVE_BLUEPRINT in .env: {e}")

    logger.info(f"Switched active blueprint to: {bp.display_name} ({bp.id})")
    return {
        "status": "success",
        "active_blueprint": bp.model_dump()
    }


@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """API endpoint providing real-time metrics, orders, and run logs directly from Notion."""
    from app.notion.client import NotionClient
    from app.notion.orders import extract_property_value

    bp = get_active_blueprint()
    notion = NotionClient()
    try:
        orders_raw = notion.query_all_pages(settings.ORDERS_DB_ID)
        run_logs_raw = notion.query_all_pages(settings.RUN_LOG_DB_ID)

        counts = {
            "total": len(orders_raw),
            "auto_approved": 0,
            "needs_approval": 0,
            "ready": 0,
        }

        orders_list = []
        for o in orders_raw:
            page_id = o.get("id")
            status = extract_property_value(o, "Status", "select") or "Pending"
            if "Auto-Approved" in status or status == "Approved":
                counts["auto_approved"] += 1
            elif "Needs Approval" in status:
                counts["needs_approval"] += 1
            elif "Ready" in status:
                counts["ready"] += 1

            order_item = {
                "page_id": page_id,
                "order_id": extract_property_value(o, "Order ID", "title") or "N/A",
                "customer_name": extract_property_value(o, "Customer Name", "rich_text") or "Patient",
                "status": status,
                "estimated_value": extract_property_value(o, "Estimated Value", "number"),
                "ai_explanation": extract_property_value(o, "AI Explanation", "rich_text") or "",
                "created_at": extract_property_value(o, "Created At", "date") or "",
                "urgency": extract_property_value(o, "Urgency", "select") or "Normal",
                "input_type": extract_property_value(o, "Input Type", "select") or "Text",
            }

            # Extract fields dynamically based on blueprint
            for field in bp.fields:
                order_item[field.name] = extract_property_value(o, field.label, field.notion_type)

            orders_list.append(order_item)

        run_logs_list = []
        for l in run_logs_raw[:25]:
            run_logs_list.append({
                "event_id": extract_property_value(l, "Event ID", "title") or "N/A",
                "event_type": extract_property_value(l, "Event Type", "select") or "event",
                "details": extract_property_value(l, "Details", "rich_text") or "",
                "timestamp": extract_property_value(l, "Timestamp", "date") or "",
            })

        return {
            "status": "online",
            "blueprint": {
                "id": bp.id,
                "display_name": bp.display_name,
                "industry": bp.industry,
                "currency_symbol": bp.currency_symbol,
                "pdf_title": bp.pdf_title,
                "fields": [f.model_dump() for f in bp.fields]
            },
            "available_blueprints": list_available_blueprints(),
            "counts": counts,
            "orders": orders_list,
            "run_logs": run_logs_list,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to fetch dashboard stats from Notion: {e}")
        return {
            "status": "error",
            "error": str(e),
            "blueprint": {"id": bp.id, "display_name": bp.display_name, "industry": bp.industry},
            "counts": {"total": 0, "auto_approved": 0, "needs_approval": 0, "ready": 0},
            "orders": [],
            "run_logs": [],
        }
    finally:
        notion.close()


class TestOrderRequest(BaseModel):
    text: str
    input_type: Optional[str] = "text"
    customer_name: Optional[str] = "Demo Customer"


@app.post("/api/test/order")
async def trigger_test_order(payload: TestOrderRequest):
    """Trigger a live order simulation through the AI + Notion pipeline."""
    from app.pipeline import process_order

    await process_order(
        chat_id=settings.ADMIN_CHAT_ID,
        username="DemoUser",
        first_name=payload.customer_name,
        raw_input=payload.text,
        input_type=payload.input_type or "text",
    )
    return {
        "status": "success",
        "message": "Order processed through AI pipeline and written to Notion!",
    }


@app.get("/api/order/{order_id}/pdf")
async def download_order_pdf(order_id: str):
    """Generate and return the vendor dispatch PDF on the fly for any order."""
    from app.notion.client import NotionClient
    from app.notion.orders import extract_property_value
    from app.vendor.pdf import generate_lab_order_pdf

    bp = get_active_blueprint()
    notion = NotionClient()
    try:
        filter_conditions = {
            "property": "Order ID",
            "title": {"equals": order_id}
        }
        res = notion.query_database(settings.ORDERS_DB_ID, filter_conditions=filter_conditions)
        pages = res.get("results", [])
        
        order_data: Dict[str, Any] = {
            "order_id": order_id,
            "customer_name": "Client",
            "order_date": datetime.now().strftime("%Y-%m-%d"),
            "notes": "Generated from ShopSight Job Dispatch System",
        }

        if pages:
            page = pages[0]
            order_data["customer_name"] = extract_property_value(page, "Customer Name", "rich_text") or "Client"
            order_data["notes"] = extract_property_value(page, "AI Explanation", "rich_text") or "Standard Job"
            for field in bp.fields:
                order_data[field.name] = extract_property_value(page, field.label, field.notion_type)

        pdf_bytes = generate_lab_order_pdf(order_data, blueprint=bp)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="Job_Order_{order_id}.pdf"'},
        )
    finally:
        notion.close()


@app.post("/api/order/{page_id}/action")
async def perform_order_action(page_id: str, action: str):
    """Approve or mark order as ready directly from the web dashboard."""
    from app.notion.client import NotionClient
    from app.notion.orders import update_order_status
    from app.approval.escalation import _poll_approval_changes

    notion = NotionClient()
    try:
        if action == "approve":
            update_order_status(notion, page_id, "Approved")
        elif action == "ready":
            update_order_status(notion, page_id, "Ready")
        else:
            raise HTTPException(status_code=400, detail="Invalid action")

        await _poll_approval_changes(notion)
        return {"status": "success", "action": action}
    finally:
        notion.close()


@app.get("/health")
async def health_check():
    """Health check endpoint for Render keep-alive pings."""
    return {
        "status": "healthy",
        "service": "shopsight",
        "blueprint": get_active_blueprint().id,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def system_status():
    """Detailed system status for debugging."""
    bp = get_active_blueprint()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    
    return {
        "service": "shopsight",
        "status": "running",
        "blueprint": {
            "id": bp.id,
            "display_name": bp.display_name,
            "industry": bp.industry,
        },
        "components": {
            "telegram": "connected" if telegram_client._client else "disconnected",
            "ai_engine": "Groq Llama 3.3 70B & Whisper",
            "scheduler_jobs": jobs,
        },
        "config": {
            "active_blueprint": bp.id,
            "dev_mode": settings.DEV_MODE,
            "shop_name": settings.SHOP_NAME,
            "auto_approve_confidence": settings.AUTO_APPROVE_CONFIDENCE,
            "sla_threshold_minutes": settings.SLA_THRESHOLD_MINUTES,
        },
    }

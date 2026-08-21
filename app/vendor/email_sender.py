import logging
import smtplib
from email.message import EmailMessage
from app.config import settings

logger = logging.getLogger(__name__)


def send_lab_order_email(
    to_email: str,
    order_id: str,
    pdf_bytes: bytes,
) -> bool:
    """Send a lab order PDF via Gmail SMTP. Returns True on success."""
    if not settings.GMAIL_USER or not settings.GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not configured — skipping email send")
        return False
    
    msg = EmailMessage()
    msg["Subject"] = f"Lab Order - #{order_id} - {settings.SHOP_NAME}"
    msg["From"] = settings.GMAIL_USER
    msg["To"] = to_email
    
    msg.set_content(f"Please find attached the lab order #{order_id} from {settings.SHOP_NAME}.")
    msg.add_alternative(f"""
    <html>
    <body>
        <h2 style="color: #1E3A8A;">Lab Order #{order_id}</h2>
        <p>Please find attached the prescription specifications for processing.</p>
        <p>Shop: <strong>{settings.SHOP_NAME}</strong></p>
        <p>Contact: {settings.SHOP_PHONE}</p>
        <br/>
        <p>Thank you,<br/><strong>{settings.SHOP_NAME}</strong></p>
    </body>
    </html>
    """, subtype="html")
    
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"Lab_Order_{order_id}.pdf",
    )
    
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Lab order email sent to {to_email} for order {order_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email for order {order_id}: {e}")
        return False

import logging
from datetime import datetime
from typing import Dict, Any, Optional
from fpdf import FPDF
from app.config import settings
from app.blueprints.base import BlueprintConfig
from app.blueprints.loader import get_active_blueprint

logger = logging.getLogger(__name__)

def _clean_str(val) -> str:
    """Sanitize string for standard Helvetica font in PDF."""
    if val is None:
        return "-"
    s = str(val)
    replacements = {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "₹": "Rs.",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s.encode('latin-1', 'replace').decode('latin-1')

class UniversalJobPDF(FPDF):
    def __init__(self, order_id: str, title: str = "JOB ORDER SLIP", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_id = _clean_str(order_id)
        self.doc_title = _clean_str(title)
        
    def header(self):
        # Header - Business Name
        self.set_font("helvetica", "B", 16)
        shop_name = _clean_str(getattr(settings, 'SHOP_NAME', 'ShopSight Practice'))
        self.cell(0, 10, shop_name, new_x="LMARGIN", new_y="NEXT", align="C")
        
        # Header - Contact
        self.set_font("helvetica", "", 10)
        if hasattr(settings, 'SHOP_ADDRESS') and settings.SHOP_ADDRESS:
            self.cell(0, 5, _clean_str(settings.SHOP_ADDRESS), new_x="LMARGIN", new_y="NEXT", align="C")
        if hasattr(settings, 'SHOP_PHONE') and settings.SHOP_PHONE:
            self.cell(0, 5, f"Phone: {_clean_str(settings.SHOP_PHONE)}", new_x="LMARGIN", new_y="NEXT", align="C")
            
        self.ln(4)
        # Title Banner
        self.set_font("helvetica", "B", 11)
        self.cell(0, 9, f"{self.doc_title} - #{self.order_id}", border=1, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(4)

    def footer(self):
        self.set_y(-25)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 5, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", new_x="LMARGIN", new_y="NEXT")
        
        self.set_y(-20)
        self.set_font("helvetica", "", 9)
        self.cell(0, 10, "Authorized Lab Tech / Manager Signature: _______________________", align="L")
        
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def generate_lab_order_pdf(order_data: dict, blueprint: Optional[BlueprintConfig] = None) -> bytes:
    """Generate a job/dispatch order PDF dynamically based on the active blueprint."""
    bp = blueprint or get_active_blueprint()
    
    pdf = UniversalJobPDF(
        order_id=order_data.get("order_id", "N/A"),
        title=bp.pdf_title
    )
    pdf.add_page()
    
    # Customer / Patient Info Section
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 7, "Client / Patient Information", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 5, f"Name: {_clean_str(order_data.get('customer_name', 'N/A'))}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Order Date: {_clean_str(order_data.get('order_date', datetime.now().strftime('%Y-%m-%d')))}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    
    # Dynamic Job Parameters Table
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 7, f"{bp.display_name} Specifications", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    
    if bp.id == "optical":
        # Structured Optical Table
        with pdf.table() as table:
            header = table.row()
            for col_name in ["Eye", "SPH", "CYL", "AXIS", "ADD", "PD"]:
                header.cell(col_name)
                
            row_od = table.row()
            row_od.cell("OD (Right)")
            row_od.cell(_clean_str(order_data.get("od_sph", "-")))
            row_od.cell(_clean_str(order_data.get("od_cyl", "-")))
            row_od.cell(_clean_str(order_data.get("od_axis", "-")))
            row_od.cell(_clean_str(order_data.get("od_add", "-")))
            row_od.cell(_clean_str(order_data.get("od_pd", "-")))
            
            row_os = table.row()
            row_os.cell("OS (Left)")
            row_os.cell(_clean_str(order_data.get("os_sph", "-")))
            row_os.cell(_clean_str(order_data.get("os_cyl", "-")))
            row_os.cell(_clean_str(order_data.get("os_axis", "-")))
            row_os.cell(_clean_str(order_data.get("os_add", "-")))
            row_os.cell(_clean_str(order_data.get("os_pd", "-")))
        
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 5, f"Lens Type: {_clean_str(order_data.get('lens_type', 'Single Vision'))}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Frame Info: {_clean_str(order_data.get('frame_info', 'Standard'))}", new_x="LMARGIN", new_y="NEXT")

    else:
        # Dynamic Key-Value Specifications Table for any other blueprint
        with pdf.table() as table:
            header = table.row()
            header.cell("Parameter Specification")
            header.cell("Extracted Value")
            
            for field in bp.fields:
                val = order_data.get(field.name)
                if val:
                    row = table.row()
                    row.cell(_clean_str(field.label))
                    row.cell(_clean_str(val))

    pdf.ln(6)
    
    # Notes & Special Instructions Section
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 7, "Special Instructions / AI Triage Notes", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9)
    notes_text = order_data.get("notes") or order_data.get("ai_explanation") or "Standard Order"
    pdf.multi_cell(0, 5, _clean_str(notes_text), border=1, new_x="LMARGIN", new_y="NEXT")
    
    return bytes(pdf.output())

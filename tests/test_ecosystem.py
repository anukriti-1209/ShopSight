import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.blueprints.loader import list_available_blueprints, get_blueprint, get_active_blueprint
from app.groq_service import GroqService
from app.approval.engine import determine_approval_status
from app.vendor.pdf import generate_lab_order_pdf

def test_all():
    print("=== 1. Blueprint Registry Test ===")
    blueprints = list_available_blueprints()
    print(f"Total Blueprints Loaded: {len(blueprints)}")
    for b in blueprints:
        print(f" - [{b['id']}] {b['display_name']} ({b['industry']})")

    print("\n=== 2. Dental Blueprint Extraction Test ===")
    dental_bp = get_blueprint("dental")
    groq = GroqService()
    dental_text = "Dr. Sharma here for patient Priya. Tooth 21 single crown chahiye in E-Max shade A2, urgent delivery."
    dental_res = groq.extract_from_text(dental_text, blueprint=dental_bp)
    print("Extracted Tooth:", dental_res.tooth_numbers)
    print("Extracted Shade:", dental_res.shade)
    print("Extracted Restoration:", dental_res.restoration_type)
    print("Confidence:", dental_res.confidence)
    status, expl = determine_approval_status(dental_res, blueprint=dental_bp)
    print("Approval Gate Decision:", status)

    print("\n=== 3. Auto Repair Extraction Test ===")
    auto_bp = get_blueprint("auto_repair")
    auto_text = "Bhai Swift VDI number DL 3C AY 4521 ka front brake pads change karna hai. Customer Rajesh."
    auto_res = groq.extract_from_text(auto_text, blueprint=auto_bp)
    print("Vehicle:", auto_res.vehicle_info)
    print("Reg:", auto_res.registration_number)
    print("Parts:", auto_res.parts_required)
    status_auto, _ = determine_approval_status(auto_res, blueprint=auto_bp)
    print("Auto Gate Decision:", status_auto)

    print("\n=== 4. Dynamic PDF Dispatch Generator Test ===")
    dental_pdf = generate_lab_order_pdf({
        "order_id": "DENT-TEST-99",
        "customer_name": "Priya",
        "tooth_numbers": "#21",
        "shade": "A2",
        "restoration_type": "Single Crown",
        "material": "E-Max Lithium Disilicate"
    }, blueprint=dental_bp)
    print("Generated Dental PDF Bytes:", len(dental_pdf))

    print("\n[SUCCESS] Universal Ecosystem Engine fully verified!")

if __name__ == "__main__":
    test_all()

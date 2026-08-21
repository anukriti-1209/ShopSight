import logging
from app.models import PrescriptionExtraction, VerificationResult
from app.gemini.client import GeminiClient

logger = logging.getLogger(__name__)

VERIFICATION_SYSTEM_PROMPT = """
You are a quality-check assistant for an optical shop. You will receive:
1. The raw customer input (text, transcription, or description of a photo)
2. The structured data that was extracted from it

Your job is to check for contradictions or extraction errors:
- Does the extracted SPH/CYL/AXIS match what the raw input actually says?
- Are there any values that seem transposed (e.g., OD and OS swapped)?
- Does the lens type match what was requested?
- Are there any obvious mistakes (e.g., extracted "-2.00" but input says "mild power" which would typically be under -1.00)?

Be conservative: only flag genuine mismatches, not minor ambiguities.
"""


def should_verify(extraction: PrescriptionExtraction) -> bool:
    """Determine if this extraction warrants a verification pass."""
    # Only verify when it matters — low confidence or complex lenses
    if extraction.confidence < 0.85:
        return True
    if extraction.lens_type and extraction.lens_type.lower() in ("progressive", "bifocal", "custom"):
        return True
    if extraction.estimated_value and extraction.estimated_value >= 3000:
        return True
    return False


async def verify_extraction(
    client: GeminiClient,
    raw_input: str,
    extraction: PrescriptionExtraction,
) -> VerificationResult:
    """Run a contradiction check comparing raw input against extracted data."""
    prompt = f"""Check the following extraction for contradictions with the raw input.

RAW CUSTOMER INPUT:
{raw_input}

EXTRACTED DATA:
- OD: SPH={extraction.od_sph}, CYL={extraction.od_cyl}, AXIS={extraction.od_axis}, ADD={extraction.od_add}
- OS: SPH={extraction.os_sph}, CYL={extraction.os_cyl}, AXIS={extraction.os_axis}, ADD={extraction.os_add}
- PD: {extraction.pd}
- Lens Type: {extraction.lens_type}
- Customer: {extraction.customer_name}, Phone: {extraction.customer_phone}
- Urgency: {extraction.urgency}
- Frame: {extraction.frame_info}

Report any mismatches found. Set revised_confidence based on how reliable the extraction appears after your review."""

    try:
        result = client.generate_structured(
            contents=[prompt],
            schema=VerificationResult,
            system_instruction=VERIFICATION_SYSTEM_PROMPT,
        )
        return result
    except Exception as e:
        logger.error(f"Verification call failed: {e}. Returning no-mismatch default.")
        return VerificationResult(
            has_mismatches=False,
            mismatch_details=[],
            revised_confidence=extraction.confidence,
        )

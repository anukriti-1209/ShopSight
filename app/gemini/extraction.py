import logging
from typing import Optional
from app.models import PrescriptionExtraction
from app.gemini.client import GeminiClient

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """
You are an expert optometrist's assistant at an Indian optical shop. Your job is to extract structured prescription and order data from customer messages.

The input may be:
- A text message in English, Hindi (Devanagari), romanized Hindi (Hinglish), or a mix of all three
- A transcription of a voice note (which you will transcribe first if audio is provided)
- A photo of a handwritten prescription, an old glasses sticker, or a lab order slip

IMPORTANT LANGUAGE HANDLING:
- Customers frequently mix Hindi and English mid-sentence (Hinglish)
- Romanized Hindi examples: "minus do point five", "dono aankhon mein", "progressive wala lens", "thoda zyada power hai"
- Devanagari may appear alongside English optometry terms
- Always try to understand the intent regardless of language mixing

EXTRACTION RULES:
- Extract all prescription values you can find (OD/OS SPH, CYL, AXIS, ADD, PD)
- Identify lens type: single_vision (default if unclear), bifocal, progressive, or custom
- Estimate order value in INR if possible (single vision ~₹500-2000, bifocal ~₹1500-4000, progressive ~₹3000-8000+)
- Set confidence 0.0-1.0 based on how complete and clear the extraction is
- Write a brief plain-language explanation suitable for the shop owner to read in Notion
- If the input is garbage/unreadable, set confidence to 0.0 and explain why

FEW-SHOT EXAMPLES:

<examples>
<example>
<input>Mere liye ek chasma banana hai, minus 2.5 dono aankhon mein, single vision, koi bhi accha frame de dena</input>
<output>{"transcription": null, "customer_name": null, "customer_phone": null, "od_sph": "-2.50", "od_cyl": null, "od_axis": null, "od_add": null, "os_sph": "-2.50", "os_cyl": null, "os_axis": null, "os_add": null, "pd": null, "lens_type": "single_vision", "frame_info": "Any good frame (customer's choice)", "urgency": "normal", "estimated_value": 1200.0, "confidence": 0.75, "explanation": "Standard single-vision order, both eyes -2.50 SPH. No cylinder or axis specified. Frame left to shop choice. Moderate confidence — clear power but no CYL/AXIS values.", "raw_input_type": "text"}</output>
</example>

<example>
<input>मेरा पावर: OD -1.50 / -0.75 x 180, OS -2.00 / -0.50 x 170, progressive lens chahiye, Titan frame model T1234</input>
<output>{"transcription": null, "customer_name": null, "customer_phone": null, "od_sph": "-1.50", "od_cyl": "-0.75", "od_axis": "180", "od_add": null, "os_sph": "-2.00", "os_cyl": "-0.50", "os_axis": "170", "os_add": null, "pd": null, "lens_type": "progressive", "frame_info": "Titan T1234", "urgency": "normal", "estimated_value": 5000.0, "confidence": 0.88, "explanation": "Progressive lens order with complete SPH/CYL/AXIS for both eyes. ADD power not specified (needed for progressive). Specific Titan frame requested. High confidence on extraction, but missing ADD value.", "raw_input_type": "text"}</output>
</example>

<example>
<input>My name is Ramesh, phone 9876543210. Uska power thoda zyada hai, minus do point five right eye mein aur minus teen left mein. Cylinder bhi hai thoda, minus zero point seven five dono mein. Progressive lens chahiye with blue cut coating. Jaldi chahiye, kal tak.</input>
<output>{"transcription": null, "customer_name": "Ramesh", "customer_phone": "9876543210", "od_sph": "-2.50", "od_cyl": "-0.75", "od_axis": null, "od_add": null, "os_sph": "-3.00", "os_cyl": "-0.75", "os_axis": null, "os_add": null, "pd": null, "lens_type": "progressive", "frame_info": null, "urgency": "urgent", "estimated_value": 5500.0, "confidence": 0.72, "explanation": "Urgent progressive lens order for Ramesh. SPH and CYL extracted from Hinglish. AXIS and ADD values missing (both critical for progressive). Blue cut coating requested. Customer needs it by tomorrow.", "raw_input_type": "text"}</output>
</example>
</examples>
"""


async def extract_from_text(client: GeminiClient, text: str) -> PrescriptionExtraction:
    """Extract prescription data from a text message."""
    prompt = f"Extract prescription and order data from this customer message:\n\n{text}"
    result = client.generate_structured(
        contents=[prompt],
        schema=PrescriptionExtraction,
        system_instruction=EXTRACTION_SYSTEM_PROMPT,
    )
    result.raw_input_type = "text"
    return result


async def extract_from_voice(client: GeminiClient, audio_bytes: bytes) -> PrescriptionExtraction:
    """Transcribe voice note and extract prescription data in one call."""
    prompt = "Listen to this voice note from a customer at an Indian optical shop. First transcribe it word-for-word, then extract all prescription and order data."
    result = client.generate_multimodal(
        media_bytes=audio_bytes,
        mime_type="audio/ogg",
        prompt=prompt,
        schema=PrescriptionExtraction,
        system_instruction=EXTRACTION_SYSTEM_PROMPT,
    )
    result.raw_input_type = "voice"
    return result


async def extract_from_photo(client: GeminiClient, image_bytes: bytes, caption: Optional[str] = None) -> PrescriptionExtraction:
    """Extract prescription data from a photo (prescription slip, glasses sticker, etc.)."""
    prompt = "Analyze this photo from a customer at an Indian optical shop. It may be a handwritten prescription, an old glasses sticker, or a lab order slip. Extract all prescription and order data you can see."
    if caption:
        prompt += f"\n\nThe customer also sent this caption with the photo: {caption}"
    result = client.generate_multimodal(
        media_bytes=image_bytes,
        mime_type="image/jpeg",
        prompt=prompt,
        schema=PrescriptionExtraction,
        system_instruction=EXTRACTION_SYSTEM_PROMPT,
    )
    result.raw_input_type = "photo"
    return result

import io
import json
import base64
import logging
from typing import Optional
from groq import Groq
from app.config import settings
from app.models import PrescriptionExtraction, VerificationResult
from app.blueprints.base import BlueprintConfig
from app.blueprints.loader import get_active_blueprint

logger = logging.getLogger(__name__)

def build_extraction_system_prompt(blueprint: Optional[BlueprintConfig] = None) -> str:
    bp = blueprint or get_active_blueprint()
    
    fields_schema_desc = []
    for f in bp.fields:
        fields_schema_desc.append(f'  "{f.name}": null or string (Description: {f.description})')
    
    schema_fields_str = ",\n".join(fields_schema_desc)
    
    few_shot_str = ""
    if bp.few_shot_examples:
        few_shot_str = "\nFEW-SHOT EXAMPLES:\n"
        for ex in bp.few_shot_examples:
            few_shot_str += f"Input: {ex.get('input')}\nOutput: {json.dumps(ex.get('output'))}\n\n"

    return f"""
You are an expert AI assistant powering {bp.display_name} for the {bp.industry} industry.
Your job is to extract structured, actionable order and job parameters from customer messages.

{bp.system_instruction_addendum}

IMPORTANT LANGUAGE HANDLING:
- Customers frequently mix Hindi and English mid-sentence (Hinglish), or conversational dialect.
- Always infer the correct technical values regardless of conversational phrasing.

EXTRACTION RULES:
- Extract all domain parameters accurately.
- Estimate order/job value in {bp.currency} if possible.
- Set confidence 0.0 to 1.0 based on clarity and completeness.
- Write a clear, concise AI explanation line for the manager to review in Notion.
- If input is unparseable / gibberish, set confidence to 0.0 with explanation.

You MUST respond strictly with a valid JSON object conforming to this exact schema:
{{
  "transcription": null or string,
  "customer_name": null or string,
  "customer_phone": null or string,
  "urgency": "normal" | "urgent",
  "estimated_value": number or null,
  "confidence": number (0.0 to 1.0),
  "explanation": "string describing the extracted order and any review notes",
  "raw_input_type": "text" | "voice" | "photo",
{schema_fields_str}
}}
{few_shot_str}
"""

VERIFICATION_SYSTEM_PROMPT = """
You are a quality-check assistant. You will receive the raw customer input and the extracted data.
Check for contradictions, swapped parameters, or invalid inferences.
Respond strictly in JSON format:
{
  "has_mismatches": true or false,
  "mismatch_details": ["list of strings describing issues found"],
  "revised_confidence": number between 0.0 and 1.0
}
"""

class GroqService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not configured")
        self.client = Groq(api_key=self.api_key)

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
        """Transcribe voice note using Groq Whisper."""
        try:
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename
            
            transcription = self.client.audio.transcriptions.create(
                file=(filename, audio_file.read()),
                model="whisper-large-v3-turbo",
                response_format="json",
                language="hi",
                temperature=0.0
            )
            return transcription.text
        except Exception as e:
            logger.error(f"Groq Whisper transcription notice: {e}")
            try:
                audio_file = io.BytesIO(audio_bytes)
                audio_file.name = filename
                transcription = self.client.audio.transcriptions.create(
                    file=(filename, audio_file.read()),
                    model="whisper-large-v3-turbo",
                    response_format="json"
                )
                return transcription.text
            except Exception as e2:
                logger.error(f"Groq Whisper fallback failed: {e2}")
                raise e2

    def extract_from_text(self, text: str, blueprint: Optional[BlueprintConfig] = None) -> PrescriptionExtraction:
        """Extract structured data using Groq with dynamic blueprint schema."""
        system_prompt = build_extraction_system_prompt(blueprint)
        
        chat_completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract order and job data from this customer message:\n\n{text}"}
            ],
            model="openai/gpt-oss-120b",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_json = chat_completion.choices[0].message.content
        data = json.loads(raw_json)
        data["raw_input_type"] = "text"
        return PrescriptionExtraction.model_validate(data)

    def extract_from_voice(self, audio_bytes: bytes, blueprint: Optional[BlueprintConfig] = None) -> PrescriptionExtraction:
        """Transcribe voice note with Whisper then extract structured parameters."""
        transcription_text = self.transcribe_audio(audio_bytes)
        logger.info(f"Transcribed voice note: {transcription_text}")
        
        extraction = self.extract_from_text(transcription_text, blueprint)
        extraction.transcription = transcription_text
        extraction.raw_input_type = "voice"
        return extraction

    def extract_from_photo(self, image_bytes: bytes, caption: Optional[str] = None, blueprint: Optional[BlueprintConfig] = None) -> PrescriptionExtraction:
        """Extract domain parameters from photo using Llama 3.2 Vision."""
        system_prompt = build_extraction_system_prompt(blueprint)
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        user_content = [
            {
                "type": "text",
                "text": "Analyze this photo of a handwritten slip, requisition note, or work item. Extract all parameters strictly conforming to the required JSON schema." + (f" Customer caption: {caption}" if caption else "")
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                }
            }
        ]
        
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                model="llama-3.2-11b-vision-preview",
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            raw_json = chat_completion.choices[0].message.content
            data = json.loads(raw_json)
            data["raw_input_type"] = "photo"
            return PrescriptionExtraction.model_validate(data)
        except Exception as e:
            logger.error(f"Groq Vision extraction notice: {e}")
            return PrescriptionExtraction(
                confidence=0.0,
                explanation=f"Vision extraction note: {str(e)}",
                raw_input_type="photo"
            )

    def verify_extraction(self, raw_input: str, extraction: PrescriptionExtraction) -> VerificationResult:
        """Verify extraction against raw input."""
        prompt = f"RAW INPUT:\n{raw_input}\n\nEXTRACTED DATA:\n{extraction.model_dump_json()}"
        chat_completion = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            model="openai/gpt-oss-120b",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_json = chat_completion.choices[0].message.content
        data = json.loads(raw_json)
        return VerificationResult.model_validate(data)

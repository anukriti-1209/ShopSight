import logging
import os
from typing import Type, TypeVar, Optional
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel
from tenacity import (
    retry, stop_after_attempt, wait_random_exponential,
    retry_if_exception, before_sleep_log
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _is_retryable(exception: BaseException) -> bool:
    if isinstance(exception, APIError):
        if exception.code in (429, 500, 503, 504):
            if "daily" in str(exception).lower():
                logger.error("Daily quota exhausted — retry won't help until reset.")
                return False
            return True
    return False


class GeminiClient:
    """Gemini 2.0 Flash client with multi-key rotation and retry."""

    def __init__(self, api_keys: Optional[list[str]] = None):
        from app.config import settings
        self._keys = api_keys or settings.gemini_api_key_list
        if not self._keys:
            raise ValueError("No Gemini API keys configured")
        self._current_key_index = 0
        self._client = genai.Client(api_key=self._keys[0])
        logger.info(f"GeminiClient initialized with {len(self._keys)} API key(s)")

    def _rotate_key(self):
        """Switch to next API key on daily quota exhaustion."""
        if len(self._keys) <= 1:
            return False
        self._current_key_index = (self._current_key_index + 1) % len(self._keys)
        self._client = genai.Client(api_key=self._keys[self._current_key_index])
        logger.warning(f"Rotated to Gemini API key index {self._current_key_index}")
        return True

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_random_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def generate_structured(
        self,
        contents: list,
        schema: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> T:
        """Generate structured JSON output conforming to a Pydantic schema."""
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            )
            if system_instruction:
                config.system_instruction = system_instruction

            response = self._client.models.generate_content(
                model="gemini-2.0-flash",
                contents=contents,
                config=config,
            )
            return schema.model_validate_json(response.text)
        except APIError as e:
            if "daily" in str(e).lower() and self._rotate_key():
                # Retry with new key
                return self.generate_structured(contents, schema, system_instruction, temperature)
            raise

    def generate_multimodal(
        self,
        media_bytes: bytes,
        mime_type: str,
        prompt: str,
        schema: Type[T],
        system_instruction: Optional[str] = None,
        temperature: float = 0.1,
    ) -> T:
        """Generate structured output from media (audio/image) + text prompt."""
        contents = [
            types.Part.from_bytes(data=media_bytes, mime_type=mime_type),
            prompt,
        ]
        return self.generate_structured(contents, schema, system_instruction, temperature)

# Module-level singleton
gemini_client: Optional[GeminiClient] = None

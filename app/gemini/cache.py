import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_FILE = Path(".cache/gemini_cache.json")


class GeminiCache:
    """DEV_MODE only: caches Gemini responses by input hash to save API quota."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._cache: dict = {}
        if enabled:
            self._load()
            logger.info(f"Gemini cache enabled with {len(self._cache)} cached entries")

    def _load(self):
        try:
            if CACHE_FILE.exists():
                self._cache = json.loads(CACHE_FILE.read_text())
        except Exception as e:
            logger.warning(f"Failed to load Gemini cache: {e}")
            self._cache = {}

    def _save(self):
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(self._cache, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save Gemini cache: {e}")

    @staticmethod
    def _hash_input(content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode()
        return hashlib.sha256(content).hexdigest()

    def get(self, input_content: str | bytes) -> Optional[str]:
        if not self.enabled:
            return None
        key = self._hash_input(input_content)
        result = self._cache.get(key)
        if result:
            logger.debug(f"Gemini cache HIT for {key[:12]}...")
        return result

    def put(self, input_content: str | bytes, response_json: str):
        if not self.enabled:
            return
        key = self._hash_input(input_content)
        self._cache[key] = response_json
        self._save()
        logger.debug(f"Gemini cache STORE for {key[:12]}...")


# Module-level singleton, initialized in main.py
gemini_cache: Optional[GeminiCache] = None

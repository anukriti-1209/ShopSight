import time
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class UpdateDeduplicator:
    """In-memory deduplication set for Telegram update_ids with TTL eviction.
    
    Known tradeoff: state is lost on process restart. Worst case is one
    duplicate order if Telegram retries during a ~30s cold start window.
    This is documented and accepted for a single-shop hackathon project.
    """
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 10000):
        self._seen: Dict[int, float] = {}  # update_id -> timestamp
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._insert_count = 0
    
    def is_duplicate(self, update_id: int) -> bool:
        if update_id in self._seen:
            logger.debug(f"Duplicate update_id detected: {update_id}")
            return True
        self._seen[update_id] = time.time()
        self._insert_count += 1
        if self._insert_count % 100 == 0:
            self._evict_expired()
        if len(self._seen) > self._max_size:
            logger.warning(f"Dedup cache exceeded max size ({self._max_size}), purging")
            self._seen.clear()
        return False
    
    def _evict_expired(self):
        now = time.time()
        expired = [uid for uid, ts in self._seen.items() if now - ts > self._ttl]
        for uid in expired:
            del self._seen[uid]
        if expired:
            logger.debug(f"Evicted {len(expired)} expired update_ids")

# Module-level singleton
deduplicator = UpdateDeduplicator()

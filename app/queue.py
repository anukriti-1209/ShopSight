import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


class GeminiRequestQueue:
    """Async queue that enforces minimum spacing between Gemini API calls.
    
    At 5s spacing = max 12 calls/min, safely under the 15 RPM free tier limit.
    """
    
    def __init__(self, min_spacing_seconds: float = 5.0):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._min_spacing = min_spacing_seconds
        self._last_call_time: float = 0
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the background worker."""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info(f"Gemini request queue started (min spacing: {self._min_spacing}s)")
    
    async def stop(self):
        """Stop the background worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Gemini request queue stopped")
    
    async def enqueue(self, coro_func: Callable[..., Coroutine], *args, **kwargs) -> asyncio.Future:
        """Enqueue a coroutine to be executed with rate limiting."""
        future = asyncio.get_event_loop().create_future()
        await self._queue.put((coro_func, args, kwargs, future))
        return future
    
    async def _worker(self):
        """Background worker that processes queued requests with spacing."""
        while self._running:
            try:
                coro_func, args, kwargs, future = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            
            # Enforce spacing
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self._min_spacing:
                wait_time = self._min_spacing - elapsed
                logger.debug(f"Queue spacing: waiting {wait_time:.1f}s before next Gemini call")
                await asyncio.sleep(wait_time)
            
            # Execute
            try:
                result = await coro_func(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self._last_call_time = time.monotonic()
                self._queue.task_done()


# Module-level singleton
gemini_queue: Optional[GeminiRequestQueue] = None

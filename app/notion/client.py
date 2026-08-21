import os
import time
import random
import logging
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


class NotionClient:
    """Synchronous Notion API client with automatic 429 Retry-After handling."""

    def __init__(self, auth_token: Optional[str] = None, max_retries: int = 5, timeout: float = 30.0):
        from app.config import settings
        self.auth_token = auth_token or settings.NOTION_TOKEN
        self.max_retries = max_retries
        self.client = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.auth_token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def _request(self, method: str, endpoint: str, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute HTTP request with automatic retry on 429 and transient errors."""
        retries = 0
        while True:
            try:
                response = self.client.request(method, endpoint.lstrip("/"), json=json)
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 1.0))
                    jitter = random.uniform(0.1, 0.5)
                    retries += 1
                    if retries > self.max_retries:
                        response.raise_for_status()
                    logger.warning(f"Notion 429 rate limit. Waiting {retry_after + jitter:.1f}s (retry {retries}/{self.max_retries})")
                    time.sleep(retry_after + jitter)
                    continue
                if response.status_code in (502, 503, 529):
                    retries += 1
                    if retries > self.max_retries:
                        response.raise_for_status()
                    backoff = (2 ** retries) + random.uniform(0.1, 1.0)
                    logger.warning(f"Notion {response.status_code} error. Backoff {backoff:.1f}s")
                    time.sleep(backoff)
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                retries += 1
                if retries > self.max_retries:
                    raise
                backoff = (2 ** retries) + random.uniform(0.1, 1.0)
                logger.warning(f"Notion connection error: {exc}. Backoff {backoff:.1f}s")
                time.sleep(backoff)

    def close(self):
        self.client.close()

    def create_database(self, parent_page_id: str, title: str, properties: Dict, is_inline: bool = True, icon_emoji: Optional[str] = None) -> Dict:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "is_inline": is_inline,
            "properties": properties,
        }
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        return self._request("POST", "/databases", json=payload)

    def create_page(self, database_id: str, properties: Dict, icon_emoji: Optional[str] = None, children: Optional[List] = None) -> Dict:
        payload = {"parent": {"database_id": database_id}, "properties": properties}
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if children:
            payload["children"] = children
        return self._request("POST", "/pages", json=payload)

    def create_standalone_page(self, parent_page_id: str, title: str, icon_emoji: Optional[str] = None, cover_url: Optional[str] = None, children: Optional[List] = None) -> Dict:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {"title": [{"type": "text", "text": {"content": title}}]},
        }
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if cover_url:
            payload["cover"] = {"type": "external", "external": {"url": cover_url}}
        if children:
            payload["children"] = children
        return self._request("POST", "/pages", json=payload)

    def query_database(self, database_id: str, filter_conditions: Optional[Dict] = None, sorts: Optional[List] = None, page_size: int = 100) -> Dict:
        payload: Dict[str, Any] = {"page_size": min(page_size, 100)}
        if filter_conditions:
            payload["filter"] = filter_conditions
        if sorts:
            payload["sorts"] = sorts
        return self._request("POST", f"/databases/{database_id}/query", json=payload)

    def query_all_pages(self, database_id: str, filter_conditions: Optional[Dict] = None, sorts: Optional[List] = None) -> List[Dict]:
        results = []
        has_more = True
        next_cursor = None
        while has_more:
            payload: Dict[str, Any] = {"page_size": 100}
            if filter_conditions:
                payload["filter"] = filter_conditions
            if sorts:
                payload["sorts"] = sorts
            if next_cursor:
                payload["start_cursor"] = next_cursor
            res = self._request("POST", f"/databases/{database_id}/query", json=payload)
            results.extend(res.get("results", []))
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
        return results

    def update_page(self, page_id: str, properties: Dict) -> Dict:
        return self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})

    def get_page(self, page_id: str) -> Dict:
        return self._request("GET", f"/pages/{page_id}")

    def append_block_children(self, block_id: str, children: List[Dict]) -> Dict:
        return self._request("PATCH", f"/blocks/{block_id}/children", json={"children": children})

    def get_block_children(self, block_id: str) -> List[Dict]:
        results = []
        has_more = True
        next_cursor = None
        while has_more:
            endpoint = f"/blocks/{block_id}/children?page_size=100"
            if next_cursor:
                endpoint += f"&start_cursor={next_cursor}"
            res = self._request("GET", endpoint)
            results.extend(res.get("results", []))
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
        return results

    def update_block(self, block_id: str, block_data: Dict) -> Dict:
        return self._request("PATCH", f"/blocks/{block_id}", json=block_data)

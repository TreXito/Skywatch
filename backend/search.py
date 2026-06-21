"""Web search enrichment via a SearXNG instance (JSON API).

Used by the AI digest to pull context about the most interesting aircraft. Fully
optional and best-effort: if SearXNG isn't configured/reachable, callers get [].
The instance must have the JSON output format enabled.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from . import constants

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(self, settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": constants.USER_AGENT},
            follow_redirects=True,
        )
        self._img_cache: dict[str, Optional[str]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.searxng_url)

    async def search(self, query: str, n: int = 10) -> list[dict]:
        if not self.enabled or not query.strip():
            return []
        base = self.settings.searxng_url.rstrip("/")
        try:
            resp = await self._client.get(
                f"{base}/search",
                params={"q": query, "format": "json", "safesearch": 0},
            )
            resp.raise_for_status()
            results = (resp.json() or {}).get("results") or []
            out = []
            for r in results[:n]:
                out.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": (r.get("content") or "")[:300],
                })
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearXNG search failed (%s): %s", base, exc)
            return []

    async def image(self, query: str) -> Optional[str]:
        """First image result from SearXNG image search (for the MSFS aircraft type)."""
        if not self.enabled or not query.strip():
            return None
        if query in self._img_cache:
            return self._img_cache[query]
        base = self.settings.searxng_url.rstrip("/")
        try:
            resp = await self._client.get(
                f"{base}/search",
                params={"q": query, "categories": "images", "format": "json",
                        "safesearch": 1},
            )
            resp.raise_for_status()
            url = None
            for r in (resp.json() or {}).get("results", [])[:5]:
                url = r.get("img_src") or r.get("thumbnail_src")
                if url:
                    if url.startswith("//"):
                        url = "https:" + url
                    break
            if len(self._img_cache) > 200:
                self._img_cache.clear()
            self._img_cache[query] = url
            return url
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearXNG image search failed: %s", exc)
            return None

    async def about_aircraft(self, insight: dict, n: int = 10) -> list[dict]:
        """Build a query from an insight dict and return the top web results."""
        parts = [
            insight.get("callsign"),
            insight.get("typecode"),
            insight.get("operator"),
        ]
        query = " ".join(p for p in parts if p).strip() or insight.get("reason", "")
        query = f"{query} aircraft"
        return await self.search(query, n=n)

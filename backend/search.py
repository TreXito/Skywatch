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

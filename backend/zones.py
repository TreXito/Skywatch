"""Conflict / hazard zone overlay.

Pulls headlines from configurable news RSS/Atom feeds, keeps the ones that look
conflict/hazard related, geocodes them against a bundled region gazetteer, and
aggregates them into map regions. Also merges any static zones from config.

This is intentionally dependency-free (stdlib XML parsing) and deterministic: a
self-hosted instance gets predictable behavior without external geocoding keys.
"""
from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from html import unescape
from typing import Optional

import httpx

from . import constants

logger = logging.getLogger(__name__)


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_feed(xml_text: str) -> list[dict]:
    """Return [{title, link, source}] from an RSS or Atom document."""
    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # Feed title (source name).
    source = ""
    for child in root.iter():
        if _strip_ns(child.tag) == "title" and child.text:
            source = child.text.strip()
            break

    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag not in ("item", "entry"):
            continue
        title = ""
        link = ""
        for c in el:
            ct = _strip_ns(c.tag)
            if ct == "title" and c.text:
                title = unescape(c.text.strip())
            elif ct == "link":
                link = (c.get("href") or c.text or "").strip()
        if title:
            items.append({"title": title, "link": link, "source": source})
    return items


class ZoneService:
    def __init__(self, settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=20.0, follow_redirects=True,
            headers={"User-Agent": constants.USER_AGENT},
        )
        self._cache: list[dict] = []
        self._last_refresh = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    def _feeds(self) -> list[str]:
        if self.settings.news_feeds_replace and self.settings.news_feeds:
            return self.settings.news_feeds
        return constants.DEFAULT_NEWS_FEEDS + list(self.settings.news_feeds)

    def _static_zones(self) -> list[dict]:
        out = []
        for z in self.settings.conflict_zones:
            if "lat" in z and "lon" in z:
                out.append({
                    "name": z.get("name", "Zone"),
                    "lat": float(z["lat"]),
                    "lon": float(z["lon"]),
                    "radius_km": float(z.get("radius_km", 100)),
                    "severity": z.get("severity", "high"),
                    "mentions": 0,
                    "static": True,
                    "headlines": [],
                    "note": z.get("note", "User-defined zone"),
                })
        return out

    async def get_zones(self, force: bool = False) -> list[dict]:
        if not self.settings.zones_enabled:
            return self._static_zones()
        now = time.time()
        if not force and self._cache and \
                now - self._last_refresh < self.settings.zones_refresh_minutes * 60:
            return self._cache
        await self.refresh()
        return self._cache

    async def refresh(self) -> None:
        if not self.settings.zones_enabled:
            self._cache = self._static_zones()
            return
        feeds = self._feeds()
        results = await asyncio.gather(
            *(self._fetch(u) for u in feeds), return_exceptions=True
        )
        headlines: list[dict] = []
        for r in results:
            if isinstance(r, list):
                headlines.extend(r)

        regions = self._aggregate(headlines)
        zones = self._static_zones() + regions
        self._cache = zones
        self._last_refresh = time.time()
        logger.info("Zones refreshed: %d headlines → %d conflict regions (+%d static)",
                    len(headlines), len(regions), len(zones) - len(regions))

    async def _fetch(self, url: str) -> list[dict]:
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return _parse_feed(resp.text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Feed fetch failed (%s): %s", url, exc)
            return []

    def _aggregate(self, headlines: list[dict]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for h in headlines:
            title_l = h["title"].lower()
            if not any(kw in title_l for kw in constants.CONFLICT_KEYWORDS):
                continue
            region = self._match_region(title_l)
            if not region:
                continue
            name, (lat, lon, radius, _aliases) = region
            b = buckets.setdefault(name, {
                "name": name, "lat": lat, "lon": lon, "radius_km": radius,
                "mentions": 0, "static": False, "headlines": [],
            })
            b["mentions"] += 1
            if len(b["headlines"]) < 8:
                b["headlines"].append(h)

        out = []
        for b in buckets.values():
            if b["mentions"] < self.settings.zones_min_mentions:
                continue
            b["severity"] = ("high" if b["mentions"] >= 5
                             else "medium" if b["mentions"] >= 2 else "low")
            out.append(b)
        out.sort(key=lambda z: z["mentions"], reverse=True)
        return out

    @staticmethod
    def _match_region(title_l: str) -> Optional[tuple]:
        for name, data in constants.GAZETTEER.items():
            aliases = data[3]
            for alias in aliases:
                if alias in title_l:
                    return name, data
        return None

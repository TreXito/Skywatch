"""Aircraft photos via the Planespotters.net public API (keyless, by icao24 hex).

Results are cached in memory (including negative results) to be a good API
citizen and keep popups snappy.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from . import constants

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400  # photos rarely change


class PhotoService:
    def __init__(self, settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": constants.USER_AGENT}
        )
        self._cache: dict[str, tuple[float, Optional[dict]]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, icao24: str) -> Optional[dict]:
        if not self.settings.photos_enabled or not icao24:
            return None
        icao24 = icao24.lower()
        now = time.time()
        cached = self._cache.get(icao24)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            resp = await self._client.get(
                constants.PLANESPOTTERS_HEX_URL.format(hex=icao24)
            )
            resp.raise_for_status()
            data = resp.json()
            photos = data.get("photos") or []
            result = None
            if photos:
                p = photos[0]
                result = {
                    "thumbnail": (p.get("thumbnail_large") or p.get("thumbnail") or {}).get("src"),
                    "link": p.get("link"),
                    "photographer": p.get("photographer"),
                }
            self._cache[icao24] = (now, result)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("Photo fetch for %s failed: %s", icao24, exc)
            self._cache[icao24] = (now, None)
            return None

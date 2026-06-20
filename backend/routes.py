"""Flight route lookup (origin → destination) via the keyless adsbdb.com API.

Resolves a callsign to its scheduled origin/destination airports (with coordinates,
so the frontend can draw the route) plus the operating airline. Cached in memory,
including negative results.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from . import constants

logger = logging.getLogger(__name__)

_ADSBDB_CALLSIGN_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
_CACHE_TTL = 3600


class RouteService:
    def __init__(self, settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": constants.USER_AGENT}
        )
        self._cache: dict[str, tuple[float, Optional[dict]]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _airport(node: dict) -> Optional[dict]:
        if not node:
            return None
        return {
            "iata": node.get("iata_code"),
            "icao": node.get("icao_code"),
            "name": node.get("name"),
            "city": node.get("municipality"),
            "country": node.get("country_name"),
            "lat": node.get("latitude"),
            "lon": node.get("longitude"),
        }

    async def get(self, callsign: str) -> Optional[dict]:
        if not self.settings.routes_enabled or not callsign:
            return None
        callsign = callsign.strip().upper()
        if not callsign:
            return None
        now = time.time()
        cached = self._cache.get(callsign)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            resp = await self._client.get(_ADSBDB_CALLSIGN_URL.format(callsign=callsign))
            result = None
            if resp.status_code == 200:
                fr = (resp.json().get("response") or {}).get("flightroute") or {}
                origin = self._airport(fr.get("origin"))
                destination = self._airport(fr.get("destination"))
                if origin or destination:
                    result = {
                        "callsign": callsign,
                        "airline": (fr.get("airline") or {}).get("name"),
                        "origin": origin,
                        "destination": destination,
                    }
            self._cache[callsign] = (now, result)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.debug("Route lookup for %s failed: %s", callsign, exc)
            self._cache[callsign] = (now, None)
            return None

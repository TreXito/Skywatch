"""METAR weather via the Aviation Weather Center API (aviationweather.gov).

Fetches decoded METARs for a bounding box (for the weather panel) and for
individual stations (for airport popups), with a short in-memory cache.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from . import constants
from .utils import bounding_box

logger = logging.getLogger(__name__)

_CACHE_TTL = 300  # seconds


class WeatherService:
    def __init__(self, settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=20.0, headers={"User-Agent": constants.USER_AGENT}
        )
        self._bbox_cache: tuple[float, list] | None = None
        self._station_cache: dict[str, tuple[float, dict]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _simplify(m: dict) -> dict:
        return {
            "station": m.get("icaoId"),
            "name": m.get("name"),
            "lat": m.get("lat"),
            "lon": m.get("lon"),
            "temp_c": m.get("temp"),
            "dewp_c": m.get("dewp"),
            "wind_dir": m.get("wdir"),
            "wind_kt": m.get("wspd"),
            "wind_gust_kt": m.get("wgst"),
            "visibility": m.get("visib"),
            "altimeter": m.get("altim"),
            "flight_category": m.get("fltCat"),
            "raw": m.get("rawOb"),
            "observed": m.get("obsTime"),
        }

    async def metars_in_radius(self) -> list[dict]:
        if not self.settings.metar_enabled:
            return []
        now = time.time()
        if self._bbox_cache and now - self._bbox_cache[0] < _CACHE_TTL:
            return self._bbox_cache[1]

        s = self.settings
        lat_min, lat_max, lon_min, lon_max = bounding_box(
            s.latitude, s.longitude, max(s.radius_km, 120)
        )
        try:
            resp = await self._client.get(
                constants.METAR_API_URL,
                params={
                    "bbox": f"{lat_min:.3f},{lon_min:.3f},{lat_max:.3f},{lon_max:.3f}",
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            out = [self._simplify(m) for m in data if m.get("icaoId")]
            self._bbox_cache = (now, out)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("METAR bbox fetch failed: %s", exc)
            return self._bbox_cache[1] if self._bbox_cache else []

    async def metar_for(self, station: str) -> Optional[dict]:
        if not self.settings.metar_enabled or not station:
            return None
        station = station.upper()
        now = time.time()
        cached = self._station_cache.get(station)
        if cached and now - cached[0] < _CACHE_TTL:
            return cached[1]
        try:
            resp = await self._client.get(
                constants.METAR_API_URL,
                params={"ids": station, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            out = self._simplify(data[0])
            self._station_cache[station] = (now, out)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("METAR fetch for %s failed: %s", station, exc)
            return None

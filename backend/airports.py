"""Airports overlay backed by the OurAirports public dataset.

Downloads airports.csv once, caches it in SQLite, and serves airports within the
configured radius. Refreshed on the same schedule as aircraft metadata.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time

import httpx

from . import constants
from .database import Database
from .utils import bounding_box, haversine_km

logger = logging.getLogger(__name__)

_META_KEY = "airports_last_update"

# OurAirports `type` values, smallest → largest meaningful.
_TYPE_ORDER = ["small_airport", "medium_airport", "large_airport"]
_MIN_TYPE_MAP = {
    "small": ["small_airport", "medium_airport", "large_airport"],
    "medium": ["medium_airport", "large_airport"],
    "large": ["large_airport"],
}


class AirportService:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings

    async def ensure_database(self) -> None:
        if not self.settings.airports_enabled:
            return
        count = await self.db.airports_count()
        last = await self.db.get_meta_info(_META_KEY)
        stale = True
        if last:
            stale = (time.time() - float(last)) / 86400 >= self.settings.metadata_update_days
        if count == 0 or stale:
            try:
                await self._download()
            except Exception as exc:  # noqa: BLE001
                logger.error("Airport download failed (continuing without it): %s", exc)
        else:
            logger.info("Airports up to date (%d rows)", count)

    async def _download(self) -> None:
        logger.info("Downloading airports database…")
        async with httpx.AsyncClient(
            timeout=120.0, follow_redirects=True,
            headers={"User-Agent": constants.USER_AGENT},
        ) as client:
            resp = await client.get(constants.OURAIRPORTS_CSV_URL)
            resp.raise_for_status()
            text = resp.text
        rows = await asyncio.get_event_loop().run_in_executor(None, self._parse, text)
        if not rows:
            logger.warning("Airports CSV parsed to 0 rows")
            return
        batch = []
        for r in rows:
            batch.append(r)
            if len(batch) >= 5000:
                await self.db.bulk_upsert_airports(batch)
                batch = []
        if batch:
            await self.db.bulk_upsert_airports(batch)
        await self.db.set_meta_info(_META_KEY, str(time.time()))
        logger.info("Loaded %d airports", len(rows))

    @staticmethod
    def _parse(text: str) -> list[tuple]:
        if text and text[0] == "﻿":
            text = text[1:]
        reader = csv.DictReader(io.StringIO(text))
        out = []
        keep = {"small_airport", "medium_airport", "large_airport"}
        for rec in reader:
            if rec.get("type") not in keep:
                continue
            try:
                lat = float(rec["latitude_deg"])
                lon = float(rec["longitude_deg"])
            except (TypeError, ValueError, KeyError):
                continue
            out.append((
                rec.get("ident"),
                rec.get("type"),
                rec.get("name"),
                lat, lon,
                rec.get("iso_country"),
                rec.get("icao_code") or rec.get("gps_code") or rec.get("ident"),
                rec.get("iata_code"),
                rec.get("municipality"),
            ))
        return out

    async def in_radius(self) -> list[dict]:
        if not self.settings.airports_enabled:
            return []
        s = self.settings
        lat_min, lat_max, lon_min, lon_max = bounding_box(
            s.latitude, s.longitude, s.radius_km
        )
        types = _MIN_TYPE_MAP.get(s.airports_min_type, _MIN_TYPE_MAP["medium"])
        rows = await self.db.airports_in_box(
            lat_min, lat_max, lon_min, lon_max, types, limit=s.airports_max * 3
        )
        for r in rows:
            r["distance_km"] = round(
                haversine_km(s.latitude, s.longitude, r["latitude"], r["longitude"]), 1
            )
        rows = [r for r in rows if r["distance_km"] <= s.radius_km]
        rows.sort(key=lambda r: r["distance_km"])
        return rows[: s.airports_max]

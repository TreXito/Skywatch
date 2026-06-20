"""Aircraft metadata enrichment.

Downloads the OpenSky aircraft database (CSV), loads it into SQLite for fast
icao24 → registration/type/operator lookups, and refreshes it periodically.
Also derives a marker category and detects helicopters from typecode/category.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from typing import Optional

import httpx

from . import constants
from .constants import OPENSKY_METADATA_DB_URL
from .database import Database
from .models import Aircraft

logger = logging.getLogger(__name__)

_META_KEY_LAST_UPDATE = "metadata_last_update"

# Candidate CSV column names → our field. OpenSky has changed headers over time,
# so we match flexibly.
_COLUMN_ALIASES = {
    "icao24": ["icao24"],
    "registration": ["registration", "reg"],
    "typecode": ["typecode", "icaoaircrafttype", "model_code"],
    "manufacturer": ["manufacturername", "manufacturer", "manufacturericao"],
    "model": ["model"],
    "operator": ["operator", "operatorcallsign", "owner"],
    "owner": ["owner", "operator"],
}


class Enricher:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings
        self._cache: dict[str, Optional[dict]] = {}

    # ----------------------------------------------------------- lookups

    async def enrich(self, aircraft: Aircraft) -> Aircraft:
        meta = await self._lookup(aircraft.icao24)
        if meta:
            aircraft.registration = meta.get("registration") or None
            aircraft.typecode = meta.get("typecode") or None
            aircraft.manufacturer = meta.get("manufacturer") or None
            aircraft.model = meta.get("model") or None
            aircraft.operator = meta.get("operator") or None
            aircraft.owner = meta.get("owner") or None
        aircraft.marker_category = self._categorize(aircraft)
        return aircraft

    async def _lookup(self, icao24: str) -> Optional[dict]:
        if icao24 in self._cache:
            return self._cache[icao24]
        meta = await self.db.lookup_metadata(icao24)
        # Bound the in-memory cache so it can't grow unbounded.
        if len(self._cache) > 50_000:
            self._cache.clear()
        self._cache[icao24] = meta
        return meta

    def _categorize(self, a: Aircraft) -> str:
        """Best-effort marker category for frontend coloring (non-alert)."""
        if a.squawk in constants.EMERGENCY_SQUAWKS:
            return constants.CATEGORY_EMERGENCY
        if a.category in constants.GROUND_VEHICLE_CATEGORIES:
            return constants.CATEGORY_GROUND
        if a.category == constants.BALLOON_CATEGORY:
            return constants.CATEGORY_BALLOON
        tc = (a.typecode or "").upper()
        if a.category == constants.HELICOPTER_CATEGORY or tc in constants.HELICOPTER_TYPECODES:
            return constants.CATEGORY_HELICOPTER
        return constants.CATEGORY_NORMAL  # alert engine may upgrade this

    # ----------------------------------------------------------- DB refresh

    async def ensure_database(self) -> None:
        """Download metadata DB if empty or stale (runs at startup)."""
        if not self.settings.metadata_auto_download:
            count = await self.db.metadata_count()
            logger.info("Metadata auto-download disabled (%d rows cached)", count)
            return

        count = await self.db.metadata_count()
        last = await self.db.get_meta_info(_META_KEY_LAST_UPDATE)
        stale = True
        if last:
            age_days = (time.time() - float(last)) / 86400
            stale = age_days >= self.settings.metadata_update_days

        if count == 0 or stale:
            logger.info("Refreshing aircraft metadata database (count=%d, stale=%s)",
                        count, stale)
            try:
                await self.download_metadata()
            except Exception as exc:  # noqa: BLE001
                logger.error("Metadata download failed (continuing without it): %s", exc)
        else:
            logger.info("Aircraft metadata up to date (%d rows)", count)

    async def download_metadata(self) -> None:
        """Stream the CSV, parse it, and bulk-load into SQLite."""
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(OPENSKY_METADATA_DB_URL)
            resp.raise_for_status()
            text = resp.text

        rows = await asyncio.get_event_loop().run_in_executor(
            None, self._parse_csv, text
        )
        if not rows:
            logger.warning("Metadata CSV parsed to 0 rows; skipping load")
            return

        # Insert in batches to keep memory/commit sizes reasonable.
        batch = []
        for row in rows:
            batch.append(row)
            if len(batch) >= 5000:
                await self.db.bulk_upsert_metadata(batch)
                batch = []
        if batch:
            await self.db.bulk_upsert_metadata(batch)

        await self.db.set_meta_info(_META_KEY_LAST_UPDATE, str(time.time()))
        self._cache.clear()
        logger.info("Loaded %d aircraft metadata rows", len(rows))

    @staticmethod
    def _parse_csv(text: str) -> list[tuple]:
        # Strip a UTF-8 BOM if present (OpenSky's CSV ships one).
        if text and text[0] == "﻿":
            text = text[1:]
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            return []
        norm_header = [
            h.strip().strip('"').strip("'").lstrip("﻿").lower().replace(" ", "")
            for h in header
        ]

        def col(field: str) -> Optional[int]:
            for alias in _COLUMN_ALIASES[field]:
                if alias in norm_header:
                    return norm_header.index(alias)
            return None

        idx = {f: col(f) for f in _COLUMN_ALIASES}
        if idx["icao24"] is None:
            logger.warning("Metadata CSV has no icao24 column; header=%s", norm_header)
            return []

        out: list[tuple] = []
        for rec in reader:
            def g(field):
                i = idx[field]
                if i is None or i >= len(rec):
                    return None
                v = rec[i].strip().strip("'").strip('"')
                return v or None

            icao = g("icao24")
            if not icao:
                continue
            out.append((
                icao.lower(),
                g("registration"),
                g("typecode"),
                g("manufacturer"),
                g("model"),
                g("operator"),
                g("owner"),
            ))
        return out

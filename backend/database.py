"""Async SQLite layer: aircraft metadata cache, sighting history, alert log.

Uses aiosqlite. A single connection is shared (SQLite handles serialized access);
WAL mode is enabled for better concurrent read/write behavior.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterable, Optional

import aiosqlite

from .models import AlertRecord

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._create_tables()
        logger.info("Database ready at %s", self.path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        assert self._db
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                icao24        TEXT PRIMARY KEY,
                registration  TEXT,
                typecode      TEXT,
                manufacturer  TEXT,
                model         TEXT,
                operator      TEXT,
                owner         TEXT
            );

            CREATE TABLE IF NOT EXISTS sightings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24        TEXT NOT NULL,
                callsign      TEXT,
                typecode      TEXT,
                registration  TEXT,
                latitude      REAL,
                longitude     REAL,
                altitude_m    REAL,
                speed_ms      REAL,
                track         REAL,
                distance_km   REAL,
                ts            REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sightings_icao_ts
                ON sightings (icao24, ts);
            CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings (ts);

            CREATE TABLE IF NOT EXISTS alerts (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24        TEXT NOT NULL,
                alert_type    TEXT NOT NULL,
                title         TEXT,
                label         TEXT,
                callsign      TEXT,
                typecode      TEXT,
                registration  TEXT,
                operator      TEXT,
                squawk        TEXT,
                altitude_m    REAL,
                speed_ms      REAL,
                distance_km   REAL,
                latitude      REAL,
                longitude     REAL,
                color         INTEGER,
                ts            REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts (ts);

            CREATE TABLE IF NOT EXISTS meta_info (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        await self._db.commit()

    # ----------------------------------------------------------- metadata DB

    async def metadata_count(self) -> int:
        assert self._db
        async with self._db.execute("SELECT COUNT(*) AS c FROM metadata") as cur:
            row = await cur.fetchone()
            return row["c"] if row else 0

    async def lookup_metadata(self, icao24: str) -> Optional[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT * FROM metadata WHERE icao24 = ?", (icao24.lower(),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def bulk_upsert_metadata(self, rows: Iterable[tuple]) -> None:
        """rows: (icao24, registration, typecode, manufacturer, model, operator, owner)."""
        assert self._db
        await self._db.executemany(
            """
            INSERT INTO metadata
                (icao24, registration, typecode, manufacturer, model, operator, owner)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(icao24) DO UPDATE SET
                registration=excluded.registration,
                typecode=excluded.typecode,
                manufacturer=excluded.manufacturer,
                model=excluded.model,
                operator=excluded.operator,
                owner=excluded.owner
            """,
            rows,
        )
        await self._db.commit()

    async def get_meta_info(self, key: str) -> Optional[str]:
        assert self._db
        async with self._db.execute(
            "SELECT value FROM meta_info WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None

    async def set_meta_info(self, key: str, value: str) -> None:
        assert self._db
        await self._db.execute(
            "INSERT INTO meta_info (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self._db.commit()

    # ----------------------------------------------------------- sightings

    async def record_sightings(self, aircraft_list) -> None:
        assert self._db
        now = time.time()
        rows = [
            (
                a.icao24, a.callsign, a.typecode, a.registration,
                a.latitude, a.longitude, a.baro_altitude or a.geo_altitude,
                a.velocity, a.true_track, a.distance_km, now,
            )
            for a in aircraft_list
            if a.latitude is not None and a.longitude is not None
        ]
        if not rows:
            return
        await self._db.executemany(
            """
            INSERT INTO sightings
                (icao24, callsign, typecode, registration, latitude, longitude,
                 altitude_m, speed_ms, track, distance_km, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self._db.commit()

    async def recent_track(self, icao24: str, since_s: float) -> list[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT latitude, longitude, altitude_m, track, ts FROM sightings "
            "WHERE icao24 = ? AND ts >= ? ORDER BY ts ASC",
            (icao24.lower(), since_s),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def recent_sightings(self, limit: int = 200) -> list[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT icao24, callsign, typecode, registration, latitude, longitude, "
            "altitude_m, speed_ms, distance_km, MAX(ts) AS ts FROM sightings "
            "GROUP BY icao24 ORDER BY ts DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ----------------------------------------------------------- alerts

    async def record_alert(self, alert: AlertRecord) -> None:
        assert self._db
        await self._db.execute(
            """
            INSERT INTO alerts
                (icao24, alert_type, title, label, callsign, typecode, registration,
                 operator, squawk, altitude_m, speed_ms, distance_km, latitude,
                 longitude, color, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.icao24, alert.alert_type, alert.title, alert.label,
                alert.callsign, alert.typecode, alert.registration, alert.operator,
                alert.squawk, alert.altitude_m, alert.speed_ms, alert.distance_km,
                alert.latitude, alert.longitude, alert.color, alert.timestamp,
            ),
        )
        await self._db.commit()

    async def last_alert_time(self, icao24: str, alert_type: str) -> Optional[float]:
        assert self._db
        async with self._db.execute(
            "SELECT MAX(ts) AS ts FROM alerts WHERE icao24 = ? AND alert_type = ?",
            (icao24.lower(), alert_type),
        ) as cur:
            row = await cur.fetchone()
            return row["ts"] if row and row["ts"] is not None else None

    async def recent_alerts(self, limit: int = 100) -> list[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ----------------------------------------------------------- maintenance

    async def prune(self, retention_hours: int) -> None:
        assert self._db
        cutoff = time.time() - retention_hours * 3600
        await self._db.execute("DELETE FROM sightings WHERE ts < ?", (cutoff,))
        await self._db.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,))
        await self._db.commit()

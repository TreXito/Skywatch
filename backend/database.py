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

            CREATE TABLE IF NOT EXISTS airports (
                ident       TEXT PRIMARY KEY,
                type        TEXT,
                name        TEXT,
                latitude    REAL,
                longitude   REAL,
                iso_country TEXT,
                icao        TEXT,
                iata        TEXT,
                municipality TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_airports_bbox
                ON airports (latitude, longitude);

            CREATE TABLE IF NOT EXISTS flights (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24      TEXT NOT NULL,
                callsign    TEXT,
                typecode    TEXT,
                registration TEXT,
                origin      TEXT,
                destination TEXT,
                start_ts    REAL NOT NULL,
                end_ts      REAL NOT NULL,
                max_alt_m   REAL,
                min_alt_m   REAL,
                points      INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_flights_icao
                ON flights (icao24, end_ts);

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

    async def bulk_lookup_metadata(self, icaos: list[str]) -> dict:
        """Look up many icao24s at once (for the global scan). Returns {icao: row}."""
        assert self._db
        out: dict[str, dict] = {}
        icaos = [i.lower() for i in icaos if i]
        for start in range(0, len(icaos), 900):  # stay under SQLite's param limit
            chunk = icaos[start:start + 900]
            ph = ",".join("?" for _ in chunk)
            async with self._db.execute(
                f"SELECT * FROM metadata WHERE icao24 IN ({ph})", chunk
            ) as cur:
                for row in await cur.fetchall():
                    out[row["icao24"]] = dict(row)
        return out

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

    # ----------------------------------------------------------- airports

    async def airports_count(self) -> int:
        assert self._db
        async with self._db.execute("SELECT COUNT(*) AS c FROM airports") as cur:
            row = await cur.fetchone()
            return row["c"] if row else 0

    async def bulk_upsert_airports(self, rows) -> None:
        """rows: (ident,type,name,lat,lon,iso_country,icao,iata,municipality)."""
        assert self._db
        await self._db.executemany(
            """
            INSERT INTO airports
                (ident, type, name, latitude, longitude, iso_country, icao, iata, municipality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ident) DO UPDATE SET
                type=excluded.type, name=excluded.name,
                latitude=excluded.latitude, longitude=excluded.longitude,
                iso_country=excluded.iso_country, icao=excluded.icao,
                iata=excluded.iata, municipality=excluded.municipality
            """,
            rows,
        )
        await self._db.commit()

    async def airports_in_box(self, lat_min, lat_max, lon_min, lon_max,
                              types: list[str], limit: int = 400) -> list[dict]:
        assert self._db
        placeholders = ",".join("?" for _ in types) or "''"
        sql = (
            "SELECT ident, type, name, latitude, longitude, iso_country, icao, iata, "
            "municipality FROM airports WHERE latitude BETWEEN ? AND ? "
            "AND longitude BETWEEN ? AND ? "
            f"AND type IN ({placeholders}) LIMIT ?"
        )
        params = [lat_min, lat_max, lon_min, lon_max, *types, limit]
        async with self._db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

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

    # ----------------------------------------------------------- flights

    async def update_flights(self, aircraft_list, gap_s: float = 1800) -> None:
        """Attribute observed positions to per-aircraft flight sessions.

        A new flight is started when an aircraft reappears after `gap_s` of no
        contact or with a different callsign; otherwise the current flight is
        extended. Gives a FlightRadar24-like per-aircraft flight log.
        """
        assert self._db
        now = time.time()
        for a in aircraft_list:
            if a.latitude is None or a.longitude is None:
                continue
            alt = a.baro_altitude or a.geo_altitude
            callsign = (a.callsign or "").strip() or None
            async with self._db.execute(
                "SELECT id, callsign, end_ts, max_alt_m, min_alt_m, points "
                "FROM flights WHERE icao24 = ? ORDER BY end_ts DESC LIMIT 1",
                (a.icao24,),
            ) as cur:
                row = await cur.fetchone()

            new_flight = (
                row is None
                or (now - row["end_ts"]) > gap_s
                or (callsign and row["callsign"] and callsign != row["callsign"])
            )
            if new_flight:
                await self._db.execute(
                    "INSERT INTO flights (icao24, callsign, typecode, registration, "
                    "start_ts, end_ts, max_alt_m, min_alt_m, points) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (a.icao24, callsign, a.typecode, a.registration,
                     now, now, alt, alt),
                )
            else:
                mx = max(row["max_alt_m"] or 0, alt or 0) if alt is not None else row["max_alt_m"]
                mn = (min(row["min_alt_m"], alt) if (row["min_alt_m"] is not None and alt is not None)
                      else (alt if row["min_alt_m"] is None else row["min_alt_m"]))
                await self._db.execute(
                    "UPDATE flights SET end_ts=?, points=points+1, max_alt_m=?, "
                    "min_alt_m=?, callsign=COALESCE(callsign, ?) WHERE id=?",
                    (now, mx, mn, callsign, row["id"]),
                )
        await self._db.commit()

    async def set_flight_route(self, icao24: str, callsign: str,
                               origin: str, destination: str) -> None:
        assert self._db
        await self._db.execute(
            "UPDATE flights SET origin=COALESCE(origin, ?), "
            "destination=COALESCE(destination, ?) WHERE icao24=? AND callsign=? "
            "AND end_ts = (SELECT MAX(end_ts) FROM flights WHERE icao24=?)",
            (origin, destination, icao24.lower(), callsign, icao24.lower()),
        )
        await self._db.commit()

    async def recent_flights(self, icao24: str, limit: int = 25) -> list[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT * FROM flights WHERE icao24 = ? ORDER BY end_ts DESC LIMIT ?",
            (icao24.lower(), limit),
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

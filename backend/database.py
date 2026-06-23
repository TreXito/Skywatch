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
        # In-memory open-flight sessions keyed by icao24, so archiving every flight
        # worldwide doesn't need a per-aircraft SELECT each scan (~15k aircraft).
        self._sessions: dict[str, dict] = {}

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

            CREATE TABLE IF NOT EXISTS msfs_flights (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                aircraft     TEXT,
                start_ts     REAL NOT NULL,
                end_ts       REAL NOT NULL,
                duration_s   REAL,
                max_alt_ft   REAL,
                max_speed_kts REAL,
                points       INTEGER DEFAULT 0,
                track_geojson TEXT,
                distance_km  REAL,
                dep_lat REAL, dep_lon REAL, arr_lat REAL, arr_lon REAL,
                dep_airport TEXT, arr_airport TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msfs_flights_ts ON msfs_flights (end_ts);

            CREATE TABLE IF NOT EXISTS meta_info (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS records (
                key       TEXT PRIMARY KEY,   -- e.g. 'fastest:today', 'highest:alltime'
                value     REAL NOT NULL,
                icao24    TEXT,
                callsign  TEXT,
                typecode  TEXT,
                label     TEXT,
                day       TEXT,               -- UTC date for ':today' records
                ts        REAL
            );
            """
        )
        # Migrate older msfs_flights tables (add columns if missing).
        for col, decl in [
            ("distance_km", "REAL"), ("dep_lat", "REAL"), ("dep_lon", "REAL"),
            ("arr_lat", "REAL"), ("arr_lon", "REAL"),
            ("dep_airport", "TEXT"), ("arr_airport", "TEXT"),
        ]:
            try:
                await self._db.execute(f"ALTER TABLE msfs_flights ADD COLUMN {col} {decl}")
            except Exception:  # noqa: BLE001 – column already exists
                pass
        await self._db.commit()

    async def nearest_airport(self, lat: float, lon: float, max_km: float = 12.0):
        """Closest airport (name + codes) to a point, or None. Uses a bbox prefilter."""
        assert self._db
        d = max_km / 111.0
        async with self._db.execute(
            "SELECT name, icao, iata, latitude, longitude FROM airports "
            "WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
            (lat - d, lat + d, lon - d * 2, lon + d * 2),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        best, best_d = None, max_km
        for r in rows:
            from .utils import haversine_km
            dist = haversine_km(lat, lon, r["latitude"], r["longitude"])
            if dist < best_d:
                best, best_d = r, dist
        if not best:
            return None
        code = best.get("iata") or best.get("icao")
        return f"{best['name']}" + (f" ({code})" if code else "")

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

        Open sessions are cached in memory so archiving every flight worldwide
        (~15k aircraft per scan) batches its writes instead of doing a SELECT +
        UPDATE per aircraft. On a cache miss the last open flight is loaded from
        the DB once, so a restart resumes flights instead of fragmenting them.
        """
        assert self._db
        now = time.time()
        updates: list[tuple] = []
        for a in aircraft_list:
            if a.latitude is None or a.longitude is None:
                continue
            alt = a.baro_altitude or a.geo_altitude
            callsign = (a.callsign or "").strip() or None
            s = self._sessions.get(a.icao24)
            if s is None:                       # warm the cache from the DB (restart)
                async with self._db.execute(
                    "SELECT id, callsign, end_ts, max_alt_m, min_alt_m "
                    "FROM flights WHERE icao24 = ? ORDER BY end_ts DESC LIMIT 1",
                    (a.icao24,),
                ) as cur:
                    row = await cur.fetchone()
                if row is not None:
                    s = {"id": row["id"], "callsign": row["callsign"],
                         "end_ts": row["end_ts"], "max": row["max_alt_m"],
                         "min": row["min_alt_m"]}
                    self._sessions[a.icao24] = s

            new_flight = (
                s is None
                or (now - s["end_ts"]) > gap_s
                or (callsign and s["callsign"] and callsign != s["callsign"])
            )
            if new_flight:
                cur = await self._db.execute(
                    "INSERT INTO flights (icao24, callsign, typecode, registration, "
                    "start_ts, end_ts, max_alt_m, min_alt_m, points) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (a.icao24, callsign, a.typecode, a.registration,
                     now, now, alt, alt),
                )
                self._sessions[a.icao24] = {
                    "id": cur.lastrowid, "callsign": callsign,
                    "end_ts": now, "max": alt, "min": alt}
            else:
                if alt is not None:
                    s["max"] = max(s["max"] or alt, alt)
                    s["min"] = alt if s["min"] is None else min(s["min"], alt)
                s["end_ts"] = now
                if callsign and not s["callsign"]:
                    s["callsign"] = callsign
                updates.append((now, s["max"], s["min"], s["callsign"], s["id"]))

        if updates:
            await self._db.executemany(
                "UPDATE flights SET end_ts=?, points=points+1, max_alt_m=?, "
                "min_alt_m=?, callsign=COALESCE(callsign, ?) WHERE id=?",
                updates,
            )
        await self._db.commit()
        # Bound the cache: drop sessions idle past the gap (they'll re-seed if seen).
        if len(self._sessions) > 60_000:
            stale = now - gap_s
            for icao in [k for k, v in self._sessions.items() if v["end_ts"] < stale]:
                self._sessions.pop(icao, None)

    async def recent_flights_all(self, limit: int = 60, search: str = "",
                                 min_points: int = 1) -> list[dict]:
        """Most recent flights across ALL aircraft (the worldwide archive browser).
        Optional search matches callsign / typecode / registration / icao24."""
        assert self._db
        sql = ("SELECT * FROM flights WHERE points >= ?")
        params: list = [min_points]
        if search:
            like = f"%{search.upper()}%"
            sql += (" AND (UPPER(callsign) LIKE ? OR UPPER(typecode) LIKE ? "
                    "OR UPPER(registration) LIKE ? OR UPPER(icao24) LIKE ?)")
            params += [like, like, like, like]
        sql += " ORDER BY end_ts DESC LIMIT ?"
        params.append(min(limit, 300))
        async with self._db.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def archive_counts(self) -> dict:
        """Totals for the archive panel: how many flights/positions we've kept."""
        assert self._db
        out = {}
        for key, q in (("flights", "SELECT COUNT(*) AS c FROM flights"),
                       ("positions", "SELECT COUNT(*) AS c FROM sightings"),
                       ("aircraft", "SELECT COUNT(DISTINCT icao24) AS c FROM flights")):
            async with self._db.execute(q) as cur:
                row = await cur.fetchone()
                out[key] = row["c"] if row else 0
        return out

    # ----------------------------------------------------------- records
    async def update_record(self, key: str, value: float, day: str, info: dict) -> bool:
        """Upsert a record (e.g. fastest/highest). Returns True if it was beaten.
        ':today' keys also reset when the UTC day rolls over."""
        assert self._db
        async with self._db.execute(
            "SELECT value, day FROM records WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        is_today = key.endswith(":today")
        beat = (row is None or value > row["value"]
                or (is_today and row["day"] != day))
        if not beat:
            return False
        await self._db.execute(
            "INSERT INTO records (key, value, icao24, callsign, typecode, label, day, ts) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, icao24=excluded.icao24, "
            "callsign=excluded.callsign, typecode=excluded.typecode, "
            "label=excluded.label, day=excluded.day, ts=excluded.ts",
            (key, value, info.get("icao24"), info.get("callsign"),
             info.get("typecode"), info.get("label"), day, time.time()))
        await self._db.commit()
        return True

    async def get_records(self) -> dict:
        assert self._db
        async with self._db.execute(
            "SELECT key, value, icao24, callsign, typecode, label, day, ts "
            "FROM records") as cur:
            return {r["key"]: dict(r) for r in await cur.fetchall()}

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

    # ----------------------------------------------------------- MSFS flights

    async def save_msfs_flight(self, **f) -> int:
        assert self._db
        cur = await self._db.execute(
            "INSERT INTO msfs_flights (aircraft, start_ts, end_ts, duration_s, "
            "max_alt_ft, max_speed_kts, points, track_geojson, distance_km, "
            "dep_lat, dep_lon, arr_lat, arr_lon, dep_airport, arr_airport) "
            "VALUES (:aircraft, :start_ts, :end_ts, :duration_s, :max_alt_ft, "
            ":max_speed_kts, :points, :track_geojson, :distance_km, :dep_lat, "
            ":dep_lon, :arr_lat, :arr_lon, :dep_airport, :arr_airport)",
            f,
        )
        await self._db.commit()
        return cur.lastrowid

    async def recent_msfs_flights(self, limit: int = 200) -> list[dict]:
        assert self._db
        async with self._db.execute(
            "SELECT id, aircraft, start_ts, end_ts, duration_s, max_alt_ft, "
            "max_speed_kts, points, distance_km, dep_airport, arr_airport "
            "FROM msfs_flights ORDER BY end_ts DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def msfs_flight_track(self, flight_id: int) -> Optional[str]:
        assert self._db
        async with self._db.execute(
            "SELECT track_geojson FROM msfs_flights WHERE id = ?", (flight_id,)
        ) as cur:
            row = await cur.fetchone()
            return row["track_geojson"] if row else None

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

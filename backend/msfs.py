"""MSFS2024 own-aircraft state + automatic flight logging.

Holds the latest position pushed by the SimConnect bridge, and logs each flight
(takeoff → landing) to SQLite with the track as GeoJSON for later replay.
Takeoff/landing are detected from airspeed (airborne when > airborne_speed_kts).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from .database import Database
from .models import MsfsPosition

logger = logging.getLogger(__name__)

AIRBORNE_SPEED_KTS = 50.0
LANDING_CONFIRM_S = 20.0     # stay slow/on-ground this long before ending a flight
MIN_FLIGHT_S = 60.0          # ignore taxi blips


class MsfsLogger:
    def __init__(self, db: Database, search=None):
        self.db = db
        self.search = search
        self._airborne = False
        self._slow_since: Optional[float] = None
        self._flight: Optional[dict] = None     # {start_ts, aircraft, max_alt, ...}
        self._track: list[list] = []            # [lon, lat, alt_ft, ts]
        self._last_point_ts = 0.0

    async def update(self, pos: MsfsPosition) -> None:
        now = pos.server_time or time.time()
        speed = pos.true_airspeed_kts or 0.0
        airborne = (not pos.on_ground) and speed > AIRBORNE_SPEED_KTS

        if airborne and not self._airborne:
            self._start_flight(pos, now)
        self._airborne = self._airborne or airborne

        if self._flight is not None:
            # Downsample the track to ~1 point / 3 s.
            if now - self._last_point_ts >= 3.0:
                self._track.append([round(pos.longitude, 5), round(pos.latitude, 5),
                                    round(pos.altitude_ft or 0), round(now)])
                self._last_point_ts = now
            self._flight["max_alt"] = max(self._flight["max_alt"], pos.altitude_ft or 0)
            self._flight["max_spd"] = max(self._flight["max_spd"], speed)

            # Landing detection: slow/on-ground sustained for LANDING_CONFIRM_S.
            slow = pos.on_ground or speed < AIRBORNE_SPEED_KTS
            if slow:
                if self._slow_since is None:
                    self._slow_since = now
                elif now - self._slow_since >= LANDING_CONFIRM_S:
                    await self._end_flight(now)
            else:
                self._slow_since = None

    def _start_flight(self, pos: MsfsPosition, now: float) -> None:
        self._flight = {"start_ts": now, "aircraft": pos.aircraft or "Unknown",
                        "max_alt": pos.altitude_ft or 0, "max_spd": pos.true_airspeed_kts or 0}
        self._track = []
        self._slow_since = None
        self._last_point_ts = 0.0
        logger.info("MSFS flight started (%s)", pos.aircraft)

    async def _end_flight(self, now: float) -> None:
        f = self._flight
        self._flight = None
        self._airborne = False
        self._slow_since = None
        if not f or now - f["start_ts"] < MIN_FLIGHT_S or len(self._track) < 2:
            return
        from .utils import haversine_km
        coords = [[p[0], p[1]] for p in self._track]
        dist = sum(haversine_km(coords[i][1], coords[i][0], coords[i + 1][1],
                                coords[i + 1][0]) for i in range(len(coords) - 1))
        dep, arr = self._track[0], self._track[-1]
        # Prefer human place names (town), fall back to nearest airport.
        dep_ap = arr_ap = None
        if self.search:
            dep_ap = await self.search.reverse_geocode(dep[1], dep[0])
            arr_ap = await self.search.reverse_geocode(arr[1], arr[0])
        dep_ap = dep_ap or await self.db.nearest_airport(dep[1], dep[0])
        arr_ap = arr_ap or await self.db.nearest_airport(arr[1], arr[0])
        geojson = json.dumps({
            "type": "Feature",
            "properties": {"aircraft": f["aircraft"], "start_ts": f["start_ts"],
                           "end_ts": now, "departure": dep_ap, "arrival": arr_ap,
                           "distance_km": round(dist, 1)},
            "geometry": {"type": "LineString", "coordinates": coords},
        })
        fid = await self.db.save_msfs_flight(
            aircraft=f["aircraft"], start_ts=f["start_ts"], end_ts=now,
            duration_s=now - f["start_ts"], max_alt_ft=f["max_alt"],
            max_speed_kts=f["max_spd"], points=len(self._track),
            track_geojson=geojson, distance_km=round(dist, 1),
            dep_lat=dep[1], dep_lon=dep[0], arr_lat=arr[1], arr_lon=arr[0],
            dep_airport=dep_ap, arr_airport=arr_ap)
        logger.info("MSFS flight #%s saved (%s, %s→%s, %.0f km, %d pts)",
                    fid, f["aircraft"], dep_ap, arr_ap, dist, len(self._track))

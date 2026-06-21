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
    def __init__(self, db: Database):
        self.db = db
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
        geojson = json.dumps({
            "type": "Feature",
            "properties": {"aircraft": f["aircraft"], "start_ts": f["start_ts"],
                           "end_ts": now},
            "geometry": {"type": "LineString",
                         "coordinates": [[p[0], p[1]] for p in self._track]},
        })
        fid = await self.db.save_msfs_flight(
            f["aircraft"], f["start_ts"], now, f["max_alt"], f["max_spd"],
            len(self._track), geojson)
        logger.info("MSFS flight #%s saved (%s, %d pts, %.0f min)",
                    fid, f["aircraft"], len(self._track), (now - f["start_ts"]) / 60)

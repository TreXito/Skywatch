"""Alert engine: emergency squawk, military, rare, watchlist, holding detection.

Each poll cycle, `evaluate(aircraft_list)` is called. It classifies aircraft,
upgrades their marker_category for the map, and returns AlertRecords that are not
on cooldown. Cooldown is enforced via the database (per icao24 + alert_type).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Optional

from . import constants
from .config import Settings
from .database import Database
from .models import Aircraft, AlertRecord
from .utils import haversine_km

logger = logging.getLogger(__name__)


class _TrackPoint:
    __slots__ = ("lat", "lon", "track", "ts")

    def __init__(self, lat, lon, track, ts):
        self.lat = lat
        self.lon = lon
        self.track = track
        self.ts = ts


class AlertEngine:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

        # Merge built-in detection sets with user extensions.
        self.military_typecodes = {tc.upper() for tc in constants.MILITARY_TYPECODES}
        self.military_typecodes.update(tc.upper() for tc in settings.military_typecodes)

        self.rare_typecodes = dict(constants.RARE_TYPECODES)
        for tc in settings.rare_typecodes:
            self.rare_typecodes.setdefault(tc.upper(), tc.upper())

        self.military_keywords = list(constants.MILITARY_KEYWORDS)
        self.military_keywords += [k.lower() for k in settings.military_keywords]

        self.watchlist = {e.icao24: e.label for e in settings.watchlist}

        self.special_typecodes = {k.upper(): v for k, v in constants.SPECIAL_TYPECODES.items()}
        self.special_callsigns = dict(constants.SPECIAL_CALLSIGNS)

        # In-memory rolling position history for holding detection.
        self._tracks: dict[str, deque[_TrackPoint]] = defaultdict(
            lambda: deque(maxlen=120)
        )
        # Presence tracking for "one alert per appearance" dedup.
        self._present: dict[str, float] = {}            # icao -> last seen ts
        self._alerted: dict[tuple[str, str], float] = {}  # (icao, type) -> alerted ts

    # --------------------------------------------------------------- main

    async def evaluate(self, aircraft_list: list[Aircraft]) -> list[AlertRecord]:
        alerts: list[AlertRecord] = []
        now = time.time()
        gap = self.settings.alert_reappear_minutes * 60
        for a in aircraft_list:
            # Re-arm an aircraft that has been gone (not seen) for >= gap, so it
            # alerts again on a genuine re-entry but only once per appearance.
            if now - self._present.get(a.icao24, 0) >= gap:
                for k in [k for k in self._alerted if k[0] == a.icao24]:
                    del self._alerted[k]
            self._present[a.icao24] = now
            self._track(a, now)
            for alert in self._classify(a, now):
                if self._passes_dedup(alert, now):
                    alerts.append(alert)
        self._prune(now)
        return alerts

    def _passes_dedup(self, alert: AlertRecord, now: float) -> bool:
        """One alert per (aircraft, type) per appearance session."""
        key = (alert.icao24, alert.alert_type)
        if key in self._alerted:
            return False
        self._alerted[key] = now
        return True

    async def passes_cooldown(self, alert: AlertRecord, now: float = 0.0) -> bool:
        """Public wrapper used by the region watcher (same presence dedup)."""
        return self._passes_dedup(alert, now or time.time())

    def _prune(self, now: float) -> None:
        cutoff = now - 24 * 3600
        for icao, ts in list(self._present.items()):
            if ts < cutoff:
                self._present.pop(icao, None)
        for key, ts in list(self._alerted.items()):
            if ts < cutoff:
                self._alerted.pop(key, None)

    def colorize(self, a: Aircraft) -> str:
        """Set marker_category for display only (no alerts, no cooldown).

        Used for viewport/global aircraft that fall outside the home radius but
        should still be color-coded on the map.
        """
        if a.squawk in constants.EMERGENCY_SQUAWKS:
            a.marker_category = constants.CATEGORY_EMERGENCY
        elif a.icao24 in self.watchlist:
            a.watchlist_label = self.watchlist[a.icao24]
            a.marker_category = constants.CATEGORY_WATCHLIST
        elif self._is_military(a):
            a.marker_category = constants.CATEGORY_MILITARY
        elif self._rare_label(a) and a.marker_category == constants.CATEGORY_NORMAL:
            a.marker_category = constants.CATEGORY_RARE
        return a.marker_category

    def _classify(self, a: Aircraft, now: float) -> list[AlertRecord]:
        """Return all alert types that fire for this aircraft, and set marker color."""
        out: list[AlertRecord] = []
        s = self.settings

        # 1. Emergency squawk (highest priority).
        if s.alert_emergency and a.squawk in constants.EMERGENCY_SQUAWKS:
            label = constants.EMERGENCY_SQUAWKS[a.squawk]
            a.marker_category = constants.CATEGORY_EMERGENCY
            out.append(self._build(a, "emergency",
                                   f"🚨 EMERGENCY ({a.squawk} – {label})",
                                   constants.COLOR_EMERGENCY, label=label, now=now))

        # 2. Watchlist.
        if s.alert_watchlist and a.icao24 in self.watchlist:
            label = self.watchlist[a.icao24]
            a.watchlist_label = label
            if a.marker_category == constants.CATEGORY_NORMAL:
                a.marker_category = constants.CATEGORY_WATCHLIST
            out.append(self._build(a, "watchlist",
                                   f"⭐ Watchlist: {label}",
                                   constants.COLOR_WATCHLIST, label=label, now=now))

        # 3. Military (use the rich special description when we have one).
        is_mil = self._is_military(a)
        special = self.special_label(a)
        if s.alert_military and is_mil:
            if a.marker_category in (constants.CATEGORY_NORMAL,
                                     constants.CATEGORY_HELICOPTER):
                a.marker_category = constants.CATEGORY_MILITARY
            title = f"🛰️ {special}" if special else "🪖 Military aircraft"
            out.append(self._build(a, "military", title,
                                   constants.COLOR_MILITARY, label=special, now=now))

        # 4. Rare / interesting / special (skip if already flagged military).
        rare_label = self._rare_label(a)
        if s.alert_rare and rare_label and not (s.alert_military and is_mil):
            if a.marker_category == constants.CATEGORY_NORMAL:
                a.marker_category = constants.CATEGORY_RARE
            icon = "🛰️" if special else "✈️"
            out.append(self._build(a, "rare",
                                   f"{icon} {rare_label}",
                                   constants.COLOR_RARE, label=rare_label, now=now))

        # 5. Holding pattern.
        if s.alert_holding and self._is_holding(a):
            out.append(self._build(a, "holding",
                                   "🔄 Possible holding pattern detected",
                                   constants.COLOR_HOLDING, now=now))

        return out

    # --------------------------------------------------------------- detectors

    def _is_military(self, a: Aircraft) -> bool:
        tc = (a.typecode or "").upper()
        if tc and tc in self.military_typecodes:
            return True
        haystack = " ".join(
            filter(None, [a.operator, a.owner, a.manufacturer])
        ).lower()
        if any(kw in haystack for kw in self.military_keywords):
            return True
        cs = (a.callsign or "").upper().strip()
        if cs:
            for prefix in constants.MILITARY_CALLSIGN_PREFIXES:
                if cs.startswith(prefix):
                    return True
        return False

    def special_label(self, a: Aircraft) -> Optional[str]:
        """Rich description if this is a curated 'special' aircraft (warbird,
        outsize cargo, spyplane, command post, VIP callsign)."""
        tc = (a.typecode or "").upper()
        if tc and tc in self.special_typecodes:
            return self.special_typecodes[tc]
        cs = (a.callsign or "").upper().strip()
        if cs:
            for prefix, desc in self.special_callsigns.items():
                if cs.startswith(prefix):
                    return desc
        return None

    def is_special(self, a: Aircraft) -> bool:
        return self.special_label(a) is not None

    def is_ping_worthy(self, a: Aircraft) -> bool:
        """Only the most extreme aircraft (NOT a DC-3 / common warbird)."""
        tc = (a.typecode or "").upper()
        if tc in constants.PING_TYPECODES:
            return True
        cs = (a.callsign or "").upper().strip()
        return any(cs.startswith(p) for p in constants.PING_CALLSIGNS)

    def _rare_label(self, a: Aircraft) -> Optional[str]:
        tc = (a.typecode or "").upper()
        sp = self.special_label(a)
        if sp:
            return sp
        if tc and tc in self.rare_typecodes:
            return self.rare_typecodes[tc]
        if self.settings.alert_ground_vehicles and \
                a.category in constants.GROUND_VEHICLE_CATEGORIES:
            return "Ground vehicle"
        if a.category == constants.BALLOON_CATEGORY:
            return "Balloon / lighter-than-air"
        return None

    def _track(self, a: Aircraft, now: float) -> None:
        if a.latitude is None or a.longitude is None or a.true_track is None:
            return
        dq = self._tracks[a.icao24]
        dq.append(_TrackPoint(a.latitude, a.longitude, a.true_track, now))
        # Drop points older than 10 minutes from the left.
        cutoff = now - 600
        while dq and dq[0].ts < cutoff:
            dq.popleft()

    def _is_holding(self, a: Aircraft) -> bool:
        """Detect circular/racetrack holding: enough cumulative turn in a tight area."""
        dq = self._tracks.get(a.icao24)
        if not dq or len(dq) < 6:
            return False

        first, last = dq[0], dq[-1]
        duration = last.ts - first.ts
        if duration < self.settings.holding_min_duration_s:
            return False

        # Confine to a small area: max pairwise distance from centroid.
        clat = sum(p.lat for p in dq) / len(dq)
        clon = sum(p.lon for p in dq) / len(dq)
        max_r = max(haversine_km(clat, clon, p.lat, p.lon) for p in dq)
        if max_r > self.settings.holding_max_radius_km:
            return False

        # Sum signed heading deltas; >= loops * 360 means it's been circling.
        total_turn = 0.0
        prev = None
        for p in dq:
            if prev is not None:
                delta = (p.track - prev) % 360
                if delta > 180:
                    delta -= 360
                total_turn += delta
            prev = p.track
        return abs(total_turn) >= 360 * self.settings.holding_min_loops

    # --------------------------------------------------------------- helpers

    # Public wrapper used by the region watcher in main.py.
    def build_alert(self, a: Aircraft, alert_type: str, title: str, color: int,
                    label: Optional[str] = None, now: float = 0.0) -> AlertRecord:
        return self._build(a, alert_type, title, color, label=label, now=now)

    def _build(self, a: Aircraft, alert_type: str, title: str, color: int,
               label: Optional[str] = None, now: float = 0.0) -> AlertRecord:
        return AlertRecord(
            icao24=a.icao24,
            alert_type=alert_type,
            title=title,
            label=label,
            callsign=a.callsign,
            typecode=a.typecode,
            registration=a.registration,
            operator=a.operator or a.owner,
            model=a.model,
            manufacturer=a.manufacturer,
            squawk=a.squawk,
            altitude_m=a.baro_altitude or a.geo_altitude,
            speed_ms=a.velocity,
            distance_km=a.distance_km,
            latitude=a.latitude,
            longitude=a.longitude,
            color=color,
            timestamp=now or time.time(),
        )

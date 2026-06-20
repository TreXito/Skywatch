"""Pydantic data models for aircraft state, enrichment, and alerts."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class Aircraft(BaseModel):
    """A single aircraft state, enriched with metadata and derived fields."""

    icao24: str
    callsign: Optional[str] = None
    origin_country: Optional[str] = None
    time_position: Optional[int] = None
    last_contact: Optional[int] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    baro_altitude: Optional[float] = None      # meters
    geo_altitude: Optional[float] = None        # meters
    on_ground: bool = False
    velocity: Optional[float] = None            # m/s
    true_track: Optional[float] = None          # degrees, 0 = north
    vertical_rate: Optional[float] = None       # m/s
    squawk: Optional[str] = None
    spi: bool = False
    category: int = 0

    # --- enrichment (filled from metadata DB) ---
    registration: Optional[str] = None
    typecode: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    operator: Optional[str] = None
    owner: Optional[str] = None

    # --- derived ---
    distance_km: Optional[float] = None         # from configured base
    marker_category: str = "normal"             # used for frontend coloring
    watchlist_label: Optional[str] = None

    @staticmethod
    def from_state_vector(sv: list) -> "Aircraft":
        """Build an Aircraft from an OpenSky `/states/all` state vector array.

        Index reference (OpenSky API):
        0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
        5 longitude, 6 latitude, 7 baro_altitude, 8 on_ground, 9 velocity,
        10 true_track, 11 vertical_rate, 12 sensors, 13 geo_altitude, 14 squawk,
        15 spi, 16 position_source, 17 category
        """
        def idx(i):
            return sv[i] if i < len(sv) else None

        callsign = idx(1)
        if callsign:
            callsign = callsign.strip() or None

        return Aircraft(
            icao24=(idx(0) or "").lower(),
            callsign=callsign,
            origin_country=idx(2),
            time_position=idx(3),
            last_contact=idx(4),
            longitude=idx(5),
            latitude=idx(6),
            baro_altitude=idx(7),
            on_ground=bool(idx(8)),
            velocity=idx(9),
            true_track=idx(10),
            vertical_rate=idx(11),
            geo_altitude=idx(13),
            squawk=idx(14),
            spi=bool(idx(15)),
            category=int(idx(17) or 0),
        )


class AlertRecord(BaseModel):
    """A triggered alert, stored in history and sent to Discord."""

    icao24: str
    alert_type: str            # emergency | military | rare | watchlist | holding
    title: str
    label: Optional[str] = None
    callsign: Optional[str] = None
    typecode: Optional[str] = None
    registration: Optional[str] = None
    operator: Optional[str] = None
    squawk: Optional[str] = None
    altitude_m: Optional[float] = None
    speed_ms: Optional[float] = None
    distance_km: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    color: int = 0x95A5A6
    timestamp: float = 0.0

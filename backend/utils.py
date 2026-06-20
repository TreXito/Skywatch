"""Helpers: haversine distance, bounding box, formatting, logging setup."""
from __future__ import annotations

import logging
import math
from logging.handlers import RotatingFileHandler
from pathlib import Path

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometers."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2):
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(rlat2)
    x = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return math.atan2(y, x)


def cross_track_km(lat, lon, lat1, lon1, lat2, lon2) -> float:
    """Distance of point (lat,lon) from the great circle through (1)→(2), in km.

    Used to sanity-check flight routes: an aircraft physically far from the
    great-circle corridor between its claimed origin and destination almost
    certainly has a wrong (reused-callsign) route.
    """
    d13 = haversine_km(lat1, lon1, lat, lon) / EARTH_RADIUS_KM   # angular
    theta13 = _bearing(lat1, lon1, lat, lon)
    theta12 = _bearing(lat1, lon1, lat2, lon2)
    return abs(math.asin(math.sin(d13) * math.sin(theta13 - theta12)) * EARTH_RADIUS_KM)


def bounding_box(lat: float, lon: float, radius_km: float):
    """Return (lat_min, lat_max, lon_min, lon_max) enclosing a radius.

    Adds a small margin so aircraft just outside the radius are still polled.
    """
    radius_km = radius_km * 1.1  # margin
    lat_delta = radius_km / 111.0
    # Clamp cos to avoid blow-up near the poles.
    lon_delta = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    return (
        lat - lat_delta,
        lat + lat_delta,
        lon - lon_delta,
        lon + lon_delta,
    )


def zoom_for_radius(radius_km: float) -> int:
    """Pick a reasonable Leaflet zoom level so the radius circle fits nicely."""
    if radius_km <= 10:
        return 11
    if radius_km <= 25:
        return 10
    if radius_km <= 50:
        return 9
    if radius_km <= 100:
        return 8
    if radius_km <= 250:
        return 7
    return 6


def setup_logging(log_path: Path, level: str = "INFO", max_bytes: int = 5_000_000,
                  backups: int = 3) -> logging.Logger:
    """Configure root logging with console + rotating file handlers."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    # Avoid duplicate handlers on reload.
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet noisy libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return root


def fmt_altitude(meters: float | None) -> str:
    if meters is None:
        return "—"
    feet = meters * 3.28084
    return f"{meters:,.0f} m ({feet:,.0f} ft)"


def fmt_speed(ms: float | None) -> str:
    if ms is None:
        return "—"
    kmh = ms * 3.6
    knots = ms * 1.94384
    return f"{kmh:,.0f} km/h ({knots:,.0f} kt)"

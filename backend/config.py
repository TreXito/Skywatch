"""Configuration loader: flat config.yaml → validated settings with smart defaults.

Design principle: only `latitude` + `longitude` are required. Every other key is
optional and falls back to a sensible default, so the user-facing config stays tiny.
Power users can add any advanced key to the same flat file.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WatchlistEntry(BaseModel):
    icao24: str
    label: str = "Watchlist aircraft"

    def normalized(self) -> "WatchlistEntry":
        return WatchlistEntry(icao24=self.icao24.lower().strip(), label=self.label)


class Settings(BaseModel):
    """All Sky Watch settings. Defaults make the app runnable with just lat/lon."""

    # --- required ---
    latitude: float
    longitude: float

    # --- OpenSky ---
    opensky_username: str = ""
    opensky_password: str = ""
    opensky_client_id: str = ""       # OAuth2 (new API access model)
    opensky_client_secret: str = ""

    # --- Discord ---
    discord_webhook: str = ""
    # Optional dedicated webhooks per alert type; falls back to discord_webhook.
    discord_webhook_emergency: str = ""
    discord_webhook_military: str = ""

    # --- watchlist ---
    watchlist: List[WatchlistEntry] = Field(default_factory=list)

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8080

    # --- auth (presence of `password` enables basic auth) ---
    auth_mode: str = "auto"           # auto | none | basic | token
    username: str = "admin"
    password: str = ""
    api_token: str = ""

    # --- polling / radius ---
    radius_km: float = 50.0
    poll_interval: Optional[float] = None   # auto if None
    default_zoom: Optional[int] = None       # auto from radius if None

    # --- display coverage ---
    # radius   = only show aircraft within radius_km (alerts area)
    # viewport = show every aircraft in the current map view, worldwide (default)
    # global   = poll the whole world at once (heavy; high OpenSky credit use)
    tracking_mode: str = "viewport"
    max_aircraft: int = 800                  # cap markers for browser performance
    routes_enabled: bool = True              # origin/destination lookup (adsbdb)

    # --- map / UI ---
    dark_mode: bool = True
    # Basemap preset: dark-en | dark | german | light | satellite
    map_style: str = "dark-en"
    tile_url: str = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
    tile_url_light: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = '&copy; OpenStreetMap contributors &copy; CARTO'
    public_url: str = ""              # used in Discord "View on Sky Watch" links

    # --- Discord extras ---
    discord_photos: bool = True       # include aircraft photo in alert embeds

    # --- region-entry alerts (e.g. "anyone flying into Ukraine") ---
    region_alerts_enabled: bool = True
    watch_regions: List[dict] = Field(default_factory=list)
    region_poll_interval: Optional[float] = None   # default = poll_interval

    # --- local Ollama AI analysis ---
    ollama_enabled: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_analyze_alerts: bool = True   # analyse each alert and add to webhook
    ollama_digest_minutes: int = 0       # 0 = off; periodic situation digest

    # --- flight trails / history (FlightRadar24-like) ---
    flight_history_enabled: bool = True
    trail_minutes: int = 180             # how far back the selected trail goes

    # --- alert toggles ---
    alert_emergency: bool = True
    alert_military: bool = True
    alert_rare: bool = True
    alert_watchlist: bool = True
    alert_holding: bool = True
    alert_ground_vehicles: bool = False
    alert_cooldown_minutes: int = 30

    # --- holding detection ---
    holding_min_loops: int = 2
    holding_max_radius_km: float = 12.0
    holding_min_duration_s: int = 180

    # --- user-extensible detection lists ---
    military_typecodes: List[str] = Field(default_factory=list)
    rare_typecodes: List[str] = Field(default_factory=list)
    military_keywords: List[str] = Field(default_factory=list)

    # --- map layers / extra features ---
    weather_enabled: bool = True          # RainViewer precipitation radar overlay
    metar_enabled: bool = True            # METAR weather for airports
    airports_enabled: bool = True         # airports overlay
    airports_max: int = 400               # cap airports returned in radius
    airports_min_type: str = "medium"     # small | medium | large (smallest to show)
    photos_enabled: bool = True           # Planespotters aircraft photos
    daynight_enabled: bool = True         # day/night terminator overlay
    stats_enabled: bool = True

    # --- conflict / hazard zones overlay ---
    zones_enabled: bool = True
    news_feeds: List[str] = Field(default_factory=list)   # extends defaults; [] = use defaults
    news_feeds_replace: bool = False                       # True = use only these feeds
    zones_refresh_minutes: int = 30
    zones_min_mentions: int = 1            # headlines needed to draw a region
    conflict_zones: List[dict] = Field(default_factory=list)  # static user zones

    # --- history / enrichment ---
    history_retention_hours: int = 48
    metadata_update_days: int = 7
    metadata_auto_download: bool = True

    # --- logging ---
    log_level: str = "INFO"
    log_max_bytes: int = 5_000_000
    log_backups: int = 3

    # --- paths ---
    data_dir: str = "data"
    log_dir: str = "logs"

    # ---------------------------------------------------------------- helpers

    @property
    def is_configured(self) -> bool:
        """True once the user has set a real (non-zero) location."""
        return not (self.latitude == 0.0 and self.longitude == 0.0)

    @property
    def has_opensky_auth(self) -> bool:
        return bool(
            (self.opensky_username and self.opensky_password)
            or (self.opensky_client_id and self.opensky_client_secret)
        )

    @property
    def effective_poll_interval(self) -> float:
        if self.poll_interval is not None:
            return max(1.0, float(self.poll_interval))
        return 5.0 if self.has_opensky_auth else 10.0

    @property
    def effective_auth_mode(self) -> str:
        if self.auth_mode != "auto":
            return self.auth_mode
        if self.api_token:
            return "token"
        if self.password:
            return "basic"
        return "none"

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def log_path(self) -> Path:
        return Path(self.log_dir)

    def webhook_for(self, alert_type: str) -> str:
        if alert_type == "emergency" and self.discord_webhook_emergency:
            return self.discord_webhook_emergency
        if alert_type == "military" and self.discord_webhook_military:
            return self.discord_webhook_military
        return self.discord_webhook

    def resolved_watch_regions(self) -> list[dict]:
        """Expand watch_regions: entries may name a built-in gazetteer region or
        give explicit lat/lon/radius_km. Returns normalized dicts."""
        from .constants import GAZETTEER
        out = []
        for r in self.watch_regions:
            name = r.get("name") or r.get("region")
            lat, lon, radius = r.get("lat"), r.get("lon"), r.get("radius_km")
            if (lat is None or lon is None) and name and name in GAZETTEER:
                g = GAZETTEER[name]
                lat, lon, radius = g[0], g[1], radius or g[2]
            if lat is None or lon is None:
                continue
            out.append({
                "name": name or "Region",
                "lat": float(lat),
                "lon": float(lon),
                "radius_km": float(radius or 200),
                "label": r.get("label") or f"entered {name or 'region'}",
            })
        return out


def load_config(path: str | Path = "config.yaml") -> Settings:
    """Load settings from YAML. Missing file or missing location → safe defaults.

    Returns a Settings instance even when unconfigured (lat/lon default to 0,0) so
    the app can boot and show a "please configure your location" message.
    """
    path = Path(path)
    raw: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            logger.warning("config.yaml is not a mapping; ignoring contents")
            raw = {}
    else:
        logger.warning("config.yaml not found at %s; using defaults", path)

    # Provide a bootable default location so the app can run unconfigured.
    raw.setdefault("latitude", 0.0)
    raw.setdefault("longitude", 0.0)

    # Normalize watchlist entries (accept missing labels gracefully).
    if "watchlist" in raw and raw["watchlist"]:
        norm = []
        for entry in raw["watchlist"]:
            if isinstance(entry, dict) and entry.get("icao24"):
                norm.append(
                    WatchlistEntry(
                        icao24=str(entry["icao24"]),
                        label=str(entry.get("label", "Watchlist aircraft")),
                    ).normalized()
                )
        raw["watchlist"] = norm

    settings = Settings(**raw)
    return settings

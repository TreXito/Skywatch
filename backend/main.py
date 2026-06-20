"""Sky Watch FastAPI application entry point.

Boots the web server, serves the frontend, exposes REST + WebSocket APIs, and runs
the OpenSky poller as a background task that enriches state vectors, evaluates
alerts, pushes live updates over WebSocket, and dispatches Discord notifications.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .airports import AirportService
from .alerts import AlertEngine
from .auth import AuthManager
from .config import Settings, load_config
from .database import Database
from .discord_notifier import DiscordNotifier
from .enrichment import Enricher
from .models import Aircraft
from .opensky import OpenSkyClient
from .photos import PhotoService
from .routes import RouteService
from .utils import bounding_box, haversine_km, setup_logging, zoom_for_radius
from .weather import WeatherService
from .websocket import WebSocketManager
from .zones import ZoneService

logger = logging.getLogger("skywatch")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
CONFIG_PATH = Path("config.yaml")


class AppState:
    """Mutable container for shared runtime objects and the latest snapshot."""

    def __init__(self):
        self.settings: Settings
        self.db: Database
        self.opensky: OpenSkyClient
        self.enricher: Enricher
        self.alerts: AlertEngine
        self.discord: DiscordNotifier
        self.auth: AuthManager
        self.weather: WeatherService
        self.airports: AirportService
        self.photos: PhotoService
        self.zones: ZoneService
        self.routes: RouteService
        self.ws = WebSocketManager()
        self.current: list[Aircraft] = []
        self.poller_task: asyncio.Task | None = None
        self.maintenance_task: asyncio.Task | None = None


state = AppState()


# ----------------------------------------------------------------- lifecycle

async def _startup() -> None:
    settings = load_config(CONFIG_PATH)
    setup_logging(
        settings.log_path / "skywatch.log",
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backups=settings.log_backups,
    )
    settings.data_path.mkdir(parents=True, exist_ok=True)

    logger.info("Sky Watch v%s starting", __version__)
    if not settings.is_configured:
        logger.warning("No location configured – set latitude/longitude in config.yaml")

    db = Database(settings.data_path / "skywatch.db")
    await db.connect()

    state.settings = settings
    state.db = db
    state.opensky = OpenSkyClient(settings)
    state.enricher = Enricher(db, settings)
    state.alerts = AlertEngine(settings, db)
    state.discord = DiscordNotifier(settings)
    state.auth = AuthManager(settings)
    state.weather = WeatherService(settings)
    state.airports = AirportService(db, settings)
    state.photos = PhotoService(settings)
    state.zones = ZoneService(settings)
    state.routes = RouteService(settings)

    # Load metadata + airports DBs (non-blocking failure tolerated) in the
    # background so the web UI is responsive immediately.
    asyncio.create_task(state.enricher.ensure_database())
    asyncio.create_task(state.airports.ensure_database())
    if settings.zones_enabled:
        asyncio.create_task(state.zones.refresh())

    state.poller_task = asyncio.create_task(_poller_loop())
    state.maintenance_task = asyncio.create_task(_maintenance_loop())


async def _shutdown() -> None:
    for task in (state.poller_task, state.maintenance_task):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    for closer in (state.opensky, state.discord, state.weather,
                   state.photos, state.zones, state.routes):
        with contextlib.suppress(Exception):
            await closer.close()
    with contextlib.suppress(Exception):
        await state.db.close()
    logger.info("Sky Watch stopped")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    try:
        yield
    finally:
        await _shutdown()


# ----------------------------------------------------------------- poller

async def _poller_loop() -> None:
    """Continuously poll OpenSky, enrich, alert, broadcast."""
    await asyncio.sleep(1)  # let startup settle
    while True:
        try:
            if not state.settings.is_configured:
                await _broadcast_snapshot([])
                await asyncio.sleep(5)
                continue

            aircraft = await state.opensky.fetch_states()
            if aircraft is not None:
                await _process(aircraft)
            else:
                # Error/rate-limit: re-broadcast status so UI footer updates.
                await _broadcast_snapshot(state.current)

            await asyncio.sleep(max(1.0, state.opensky.next_delay))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Poller loop error: %s", exc)
            await asyncio.sleep(5)


async def _process(aircraft: list[Aircraft]) -> None:
    s = state.settings
    enriched: list[Aircraft] = []
    for a in aircraft:
        if a.latitude is None or a.longitude is None:
            continue
        a.distance_km = haversine_km(s.latitude, s.longitude, a.latitude, a.longitude)
        if a.distance_km > s.radius_km:
            continue
        await state.enricher.enrich(a)
        enriched.append(a)

    state.current = enriched
    await state.db.record_sightings(enriched)

    # Alerts.
    alerts = await state.alerts.evaluate(enriched)
    for alert in alerts:
        await state.db.record_alert(alert)
        logger.info("ALERT [%s] %s (%s)", alert.alert_type, alert.title, alert.icao24)
        if state.discord.enabled:
            await state.discord.send(alert)

    await _broadcast_snapshot(enriched, new_alerts=alerts)


async def _broadcast_snapshot(aircraft: list[Aircraft], new_alerts=None) -> None:
    payload = {
        "type": "update",
        "aircraft": [a.model_dump() for a in aircraft],
        "status": state.opensky.status.as_dict() if hasattr(state, "opensky") else {},
        "server_time": time.time(),
        "new_alerts": [al.model_dump() for al in (new_alerts or [])],
    }
    await state.ws.broadcast(payload)


async def _maintenance_loop() -> None:
    while True:
        try:
            await asyncio.sleep(3600)
            await state.db.prune(state.settings.history_retention_hours)
            await state.enricher.ensure_database()
            await state.airports.ensure_database()
            if state.settings.zones_enabled:
                await state.zones.refresh()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Maintenance error: %s", exc)


# ----------------------------------------------------------------- app

app = FastAPI(title="Sky Watch", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Static assets and API share the same wall; health is always open.
    if hasattr(state, "auth") and not state.auth.is_authorized(request):
        return state.auth.challenge()
    return await call_next(request)


# --- REST API ---

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__,
            "configured": getattr(state, "settings", None) and state.settings.is_configured}


@app.get("/api/config")
async def get_config():
    s = state.settings
    return {
        "latitude": s.latitude,
        "longitude": s.longitude,
        "radius_km": s.radius_km,
        "zoom": s.default_zoom or zoom_for_radius(s.radius_km),
        "dark_mode": s.dark_mode,
        "tile_url": s.tile_url if s.dark_mode else s.tile_url_light,
        "tile_url_dark": s.tile_url,
        "tile_url_light": s.tile_url_light,
        "tile_attribution": s.tile_attribution,
        "configured": s.is_configured,
        "discord_enabled": state.discord.enabled,
        "version": __version__,
        "tracking_mode": s.tracking_mode,
        "max_aircraft": s.max_aircraft,
        "poll_interval": s.effective_poll_interval,
        "features": {
            "weather": s.weather_enabled,
            "metar": s.metar_enabled,
            "airports": s.airports_enabled,
            "photos": s.photos_enabled,
            "daynight": s.daynight_enabled,
            "zones": s.zones_enabled,
            "stats": s.stats_enabled,
            "routes": s.routes_enabled,
        },
    }


@app.get("/api/aircraft")
async def get_aircraft():
    return {
        "aircraft": [a.model_dump() for a in state.current],
        "status": state.opensky.status.as_dict(),
        "server_time": time.time(),
    }


@app.get("/api/states")
async def get_states(lamin: float = None, lamax: float = None,
                     lomin: float = None, lomax: float = None):
    """Aircraft for an arbitrary map viewport (worldwide), enriched and capped.

    Used by the frontend for viewport/global display. With no bbox params, falls
    back to the home radius (or global if tracking_mode == 'global').
    """
    s = state.settings
    if None not in (lamin, lamax, lomin, lomax):
        bbox = (lamin, lamax, lomin, lomax)
    elif s.tracking_mode == "global":
        bbox = None
    else:
        bbox = bounding_box(s.latitude, s.longitude, s.radius_km)

    aircraft = await state.opensky.fetch_viewport(bbox)
    if aircraft is None:
        return {"aircraft": [], "status": state.opensky.status.as_dict(),
                "server_time": time.time()}

    out = []
    for a in aircraft:
        if a.latitude is None or a.longitude is None:
            continue
        a.distance_km = haversine_km(s.latitude, s.longitude, a.latitude, a.longitude)
        await state.enricher.enrich(a)
        # Let the alert engine's classification color the marker (military/rare/etc.)
        state.alerts.colorize(a)
        out.append(a)

    # Cap for browser performance: keep the closest to the viewport centre.
    if len(out) > s.max_aircraft:
        if bbox is not None:
            clat = (bbox[0] + bbox[1]) / 2
            clon = (bbox[2] + bbox[3]) / 2
        else:
            clat, clon = s.latitude, s.longitude
        out.sort(key=lambda a: haversine_km(clat, clon, a.latitude, a.longitude))
        out = out[: s.max_aircraft]

    return {
        "aircraft": [a.model_dump() for a in out],
        "status": state.opensky.status.as_dict(),
        "count_total": len(aircraft),
        "server_time": time.time(),
    }


@app.get("/api/route/{callsign}")
async def get_route(callsign: str):
    return {"route": await state.routes.get(callsign)}


@app.get("/api/track/{icao24}")
async def get_track(icao24: str):
    since = time.time() - 1800  # last 30 minutes
    points = await state.db.recent_track(icao24, since)
    return {"icao24": icao24.lower(), "track": points}


@app.get("/api/history")
async def get_history(limit: int = 200):
    return {"sightings": await state.db.recent_sightings(min(limit, 1000))}


@app.get("/api/alerts")
async def get_alerts(limit: int = 100):
    return {"alerts": await state.db.recent_alerts(min(limit, 500))}


@app.get("/api/status")
async def get_status():
    return {
        "status": state.opensky.status.as_dict(),
        "aircraft_count": len(state.current),
        "ws_clients": state.ws.count,
        "metadata_rows": await state.db.metadata_count(),
        "poll_interval": state.settings.effective_poll_interval,
        "server_time": time.time(),
    }


@app.get("/api/airports")
async def get_airports():
    return {"airports": await state.airports.in_radius()}


@app.get("/api/weather/metars")
async def get_metars():
    return {"metars": await state.weather.metars_in_radius()}


@app.get("/api/weather/metar/{station}")
async def get_metar(station: str):
    return {"metar": await state.weather.metar_for(station)}


@app.get("/api/zones")
async def get_zones():
    return {"zones": await state.zones.get_zones()}


@app.get("/api/photo/{icao24}")
async def get_photo(icao24: str):
    return {"photo": await state.photos.get(icao24)}


@app.get("/api/stats")
async def get_stats():
    """Live breakdown of current traffic + recent activity."""
    by_category: dict[str, int] = {}
    by_country: dict[str, int] = {}
    by_type: dict[str, int] = {}
    on_ground = 0
    alt_sum = 0.0
    alt_n = 0
    for a in state.current:
        by_category[a.marker_category] = by_category.get(a.marker_category, 0) + 1
        if a.origin_country:
            by_country[a.origin_country] = by_country.get(a.origin_country, 0) + 1
        if a.typecode:
            by_type[a.typecode] = by_type.get(a.typecode, 0) + 1
        if a.on_ground:
            on_ground += 1
        alt = a.baro_altitude or a.geo_altitude
        if alt is not None:
            alt_sum += alt
            alt_n += 1

    def top(d, n=8):
        return sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]

    recent_alerts = await state.db.recent_alerts(limit=500)
    alert_types: dict[str, int] = {}
    for al in recent_alerts:
        alert_types[al["alert_type"]] = alert_types.get(al["alert_type"], 0) + 1

    return {
        "total": len(state.current),
        "on_ground": on_ground,
        "airborne": len(state.current) - on_ground,
        "avg_altitude_m": round(alt_sum / alt_n) if alt_n else None,
        "by_category": by_category,
        "top_countries": top(by_country),
        "top_types": top(by_type),
        "alerts_24h": len(recent_alerts),
        "alerts_by_type": alert_types,
        "server_time": time.time(),
    }


def _csv_response(headers: list[str], rows: list[dict], filename: str) -> Response:
    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/history.csv")
async def export_history():
    rows = await state.db.recent_sightings(limit=1000)
    return _csv_response(
        ["icao24", "callsign", "typecode", "registration", "latitude",
         "longitude", "altitude_m", "speed_ms", "distance_km", "ts"],
        rows, "skywatch-history.csv",
    )


@app.get("/api/export/alerts.csv")
async def export_alerts():
    rows = await state.db.recent_alerts(limit=500)
    return _csv_response(
        ["ts", "alert_type", "title", "icao24", "callsign", "typecode",
         "registration", "operator", "squawk", "distance_km", "latitude", "longitude"],
        rows, "skywatch-alerts.csv",
    )


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    token = ws.query_params.get("token")
    auth_header = ws.headers.get("authorization")
    if not state.auth.authorize_ws_token(token, auth_header):
        await ws.close(code=1008)
        return
    await state.ws.connect(ws)
    try:
        while True:
            # We don't expect client messages; keep the connection alive.
            await ws.receive_text()
    except WebSocketDisconnect:
        await state.ws.disconnect(ws)
    except Exception:  # noqa: BLE001
        await state.ws.disconnect(ws)


# --- Static frontend ---

@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon():
    icon = FRONTEND_DIR / "assets" / "favicon.svg"
    if icon.exists():
        return FileResponse(icon)
    return Response(status_code=204)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def main() -> None:
    import uvicorn
    settings = load_config(CONFIG_PATH)
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()

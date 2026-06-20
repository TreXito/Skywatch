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
from .alerts import AlertEngine
from .auth import AuthManager
from .config import Settings, load_config
from .database import Database
from .discord_notifier import DiscordNotifier
from .enrichment import Enricher
from .models import Aircraft
from .opensky import OpenSkyClient
from .utils import haversine_km, setup_logging, zoom_for_radius
from .websocket import WebSocketManager

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

    # Load metadata DB (non-blocking failure tolerated) in the background so the
    # web UI is responsive immediately.
    asyncio.create_task(state.enricher.ensure_database())

    state.poller_task = asyncio.create_task(_poller_loop())
    state.maintenance_task = asyncio.create_task(_maintenance_loop())


async def _shutdown() -> None:
    for task in (state.poller_task, state.maintenance_task):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    with contextlib.suppress(Exception):
        await state.opensky.close()
    with contextlib.suppress(Exception):
        await state.discord.close()
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
    }


@app.get("/api/aircraft")
async def get_aircraft():
    return {
        "aircraft": [a.model_dump() for a in state.current],
        "status": state.opensky.status.as_dict(),
        "server_time": time.time(),
    }


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

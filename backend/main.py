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

from . import __version__, constants
from .airports import AirportService
from .alerts import AlertEngine
from .auth import AuthManager
from .config import Settings, load_config
from .database import Database
from .discord_notifier import DiscordNotifier
from .enrichment import Enricher
from .models import Aircraft
from .opensky import OpenSkyClient
from .ollama_ai import OllamaService
from .photos import PhotoService
from .routes import RouteService
from .utils import (bounding_box, cross_track_km, haversine_km, setup_logging,
                    zoom_for_radius)
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
        self.ollama: OllamaService
        self.ws = WebSocketManager()
        self.current: list[Aircraft] = []
        self.region_seen: dict[str, set] = {}
        self.ai_insights: list[dict] = []
        self.ai_insights_ts: float = 0.0
        self.poller_task: asyncio.Task | None = None
        self.maintenance_task: asyncio.Task | None = None
        self.region_task: asyncio.Task | None = None
        self.ai_task: asyncio.Task | None = None


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
    state.ollama = OllamaService(settings)

    # Load metadata + airports DBs (non-blocking failure tolerated) in the
    # background so the web UI is responsive immediately.
    asyncio.create_task(state.enricher.ensure_database())
    asyncio.create_task(state.airports.ensure_database())
    if settings.zones_enabled:
        asyncio.create_task(state.zones.refresh())

    state.poller_task = asyncio.create_task(_poller_loop())
    state.maintenance_task = asyncio.create_task(_maintenance_loop())
    if settings.region_alerts_enabled and settings.resolved_watch_regions():
        state.region_task = asyncio.create_task(_region_loop())
    if settings.ollama_enabled and settings.ollama_insights:
        state.ai_task = asyncio.create_task(_ai_loop())


async def _shutdown() -> None:
    for task in (state.poller_task, state.maintenance_task, state.region_task,
                 state.ai_task):
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    for closer in (state.opensky, state.discord, state.weather,
                   state.photos, state.zones, state.routes, state.ollama):
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
    if state.settings.flight_history_enabled:
        await state.db.update_flights(enriched)

    # Alerts.
    by_icao = {a.icao24: a for a in enriched}
    alerts = await state.alerts.evaluate(enriched)
    for alert in alerts:
        await _dispatch_alert(alert, by_icao.get(alert.icao24))

    await _broadcast_snapshot(enriched, new_alerts=alerts)


async def _dispatch_alert(alert, aircraft) -> None:
    """Record, log, and send an alert to Discord with photo + optional AI note."""
    await state.db.record_alert(alert)
    logger.info("ALERT [%s] %s (%s)", alert.alert_type, alert.title, alert.icao24)
    if not state.discord.enabled:
        return

    photo_url = None
    if state.settings.discord_photos:
        photo = await state.photos.get(alert.icao24)
        photo_url = photo.get("thumbnail") if photo else None

    route = None
    callsign = (aircraft.callsign if aircraft else alert.callsign) or ""
    if callsign and state.settings.routes_enabled:
        route = await state.routes.get(callsign)

    ai_text = None
    try:
        ai_text = await state.ollama.analyze_alert(alert, route)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Ollama analysis failed: %s", exc)

    await state.discord.send(alert, photo_url=photo_url, ai_text=ai_text)

    # The coolest cases also go to the dedicated highlights channel (photo + link).
    if (alert.alert_type in ("emergency", "holding", "rare", "region")
            and state.settings.discord_webhook_highlights):
        hl = alert.model_copy(update={"alert_type": "highlight"})
        await state.discord.send(hl, photo_url=photo_url, ai_text=ai_text)


async def _ai_loop() -> None:
    """Every minute, ask the local LLM which current aircraft are most interesting;
    store the picks for the UI and push the top ones to the highlights channel."""
    await asyncio.sleep(20)
    while True:
        try:
            interval = max(30, state.settings.ollama_insights_interval)
            picks = await state.ollama.pick_interesting(state.current)
            by_icao = {a.icao24: a for a in state.current}
            insights = []
            for p in picks:
                a = by_icao.get(p["icao24"])
                if not a:
                    continue
                insights.append({
                    "icao24": a.icao24,
                    "callsign": (a.callsign or "").strip(),
                    "typecode": a.typecode,
                    "operator": a.operator or a.owner,
                    "marker_category": a.marker_category,
                    "reason": p.get("reason", ""),
                })
            if insights:
                state.ai_insights = insights
                state.ai_insights_ts = time.time()
                await _broadcast_ai(insights)
                await _push_highlights(insights, by_icao)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("AI loop error: %s", exc)
            await asyncio.sleep(60)


async def _push_highlights(insights: list[dict], by_icao: dict) -> None:
    if not state.settings.discord_webhook_highlights:
        return
    for ins in insights[:3]:
        a = by_icao.get(ins["icao24"])
        if not a:
            continue
        alert = state.alerts.build_alert(
            a, "highlight", f"✨ AI pick: {ins['reason'] or 'interesting aircraft'}",
            constants.COLOR_HOLDING, label=ins["reason"], now=time.time(),
        )
        # Light cooldown so the same jet isn't re-posted every minute.
        if not await state.alerts.passes_cooldown(alert):
            continue
        photo = await state.photos.get(a.icao24)
        await state.discord.send(alert, photo_url=(photo or {}).get("thumbnail"),
                                 ai_text=ins["reason"])


async def _broadcast_ai(insights: list[dict]) -> None:
    await state.ws.broadcast({
        "type": "ai_insights", "insights": insights, "server_time": time.time(),
    })


async def _region_loop() -> None:
    """Poll each watch region and alert when a new aircraft enters it."""
    await asyncio.sleep(3)
    regions = state.settings.resolved_watch_regions()
    for r in regions:
        state.region_seen[r["name"]] = set()
    first_scan = {r["name"]: True for r in regions}
    interval = state.settings.region_poll_interval or state.settings.effective_poll_interval

    while True:
        try:
            for r in regions:
                bbox = bounding_box(r["lat"], r["lon"], r["radius_km"])
                aircraft = await state.opensky.fetch_viewport(bbox)
                if aircraft is None:
                    continue
                current: set[str] = set()
                entrants = []
                for a in aircraft:
                    if a.latitude is None or a.longitude is None:
                        continue
                    if haversine_km(r["lat"], r["lon"], a.latitude, a.longitude) > r["radius_km"]:
                        continue
                    current.add(a.icao24)
                    if a.icao24 not in state.region_seen[r["name"]]:
                        entrants.append(a)

                # Don't alert on the first scan (everyone already inside).
                if not first_scan[r["name"]]:
                    for a in entrants:
                        await _handle_region_entry(a, r)
                state.region_seen[r["name"]] = current
                first_scan[r["name"]] = False
                await asyncio.sleep(2)  # stagger region calls
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Region loop error: %s", exc)
            await asyncio.sleep(10)


async def _handle_region_entry(a: Aircraft, region: dict) -> None:
    await state.enricher.enrich(a)
    state.alerts.colorize(a)
    import time as _t
    alert = state.alerts.build_alert(
        a, "region", f"🌍 {region['label']}", constants.COLOR_RARE,
        label=region["name"], now=_t.time(),
    )
    if not await state.alerts.passes_cooldown(alert):
        return
    await _dispatch_alert(alert, a)
    # Push a live alert to connected clients too.
    await state.ws.broadcast({
        "type": "update", "aircraft": [x.model_dump() for x in state.current],
        "status": state.opensky.status.as_dict(), "server_time": _t.time(),
        "new_alerts": [alert.model_dump()],
    })


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
        "map_style": s.map_style,
        "trail_minutes": s.trail_minutes,
        "watch_regions": s.resolved_watch_regions(),
        "features": {
            "weather": s.weather_enabled,
            "metar": s.metar_enabled,
            "airports": s.airports_enabled,
            "photos": s.photos_enabled,
            "daynight": s.daynight_enabled,
            "zones": s.zones_enabled,
            "stats": s.stats_enabled,
            "routes": s.routes_enabled,
            "flights": s.flight_history_enabled,
            "ollama": s.ollama_enabled,
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


@app.get("/api/ai/insights")
async def ai_insights():
    return {"insights": state.ai_insights, "updated": state.ai_insights_ts,
            "enabled": state.settings.ollama_enabled and state.settings.ollama_insights}


@app.get("/api/ollama/models")
async def ollama_models(url: str = None):
    return {"models": await state.ollama.list_models(url)}


# Fields the web settings UI can edit. (group, key, type, label)
SETTINGS_SCHEMA = [
    ("Location", "latitude", "number", "Latitude"),
    ("Location", "longitude", "number", "Longitude"),
    ("Location", "radius_km", "number", "Alert radius (km)"),
    ("Map", "map_style", "select:dark-en,dark,german,light,satellite", "Map style"),
    ("Map", "tracking_mode", "select:viewport,radius,global", "Tracking mode"),
    ("Map", "max_aircraft", "number", "Max aircraft shown"),
    ("Map", "public_url", "text", "Public URL (for Discord links)"),
    ("OpenSky", "opensky_client_id", "text", "OAuth2 client id"),
    ("OpenSky", "opensky_client_secret", "password", "OAuth2 client secret"),
    ("OpenSky", "poll_interval", "number", "Poll interval (s, blank=auto)"),
    ("Discord", "discord_webhook", "text", "Webhook URL"),
    ("Discord", "discord_webhook_highlights", "text", "Highlights webhook URL"),
    ("Discord", "discord_photos", "bool", "Attach aircraft photos"),
    ("Alerts", "alert_emergency", "bool", "Emergency squawks"),
    ("Alerts", "alert_military", "bool", "Military"),
    ("Alerts", "alert_rare", "bool", "Rare types"),
    ("Alerts", "alert_holding", "bool", "Holding patterns"),
    ("Alerts", "alert_cooldown_minutes", "number", "Cooldown (min)"),
    ("Alerts", "region_alerts_enabled", "bool", "Region-entry alerts"),
    ("Alerts", "watch_regions_text", "textarea", "Watch regions (one name per line)"),
    ("Layers", "weather_enabled", "bool", "Weather radar"),
    ("Layers", "airports_enabled", "bool", "Airports"),
    ("Layers", "zones_enabled", "bool", "Conflict zones"),
    ("Layers", "flight_history_enabled", "bool", "Flight history"),
    ("Layers", "trail_minutes", "number", "Trail length (min)"),
    ("Ollama AI", "ollama_enabled", "bool", "Enable Ollama"),
    ("Ollama AI", "ollama_url", "text", "Ollama URL (e.g. http://server:11434)"),
    ("Ollama AI", "ollama_model", "text", "Model"),
    ("Ollama AI", "ollama_insights", "bool", "Minute analysis of all flights"),
    ("Ollama AI", "ollama_insights_interval", "number", "Analysis interval (s)"),
]
_RESTART_KEYS = {"opensky_client_id", "opensky_client_secret", "watch_regions_text",
                 "region_alerts_enabled", "tracking_mode"}


@app.get("/api/settings")
async def get_settings():
    s = state.settings
    values = {}
    for _g, key, _t, _l in SETTINGS_SCHEMA:
        if key == "watch_regions_text":
            values[key] = "\n".join(r.get("name", "") for r in s.watch_regions)
        else:
            values[key] = getattr(s, key, None)
    return {"schema": [{"group": g, "key": k, "type": t, "label": l}
                       for g, k, t, l in SETTINGS_SCHEMA], "values": values}


@app.post("/api/settings")
async def post_settings(request: Request):
    body = await request.json()
    allowed = {k for _g, k, _t, _l in SETTINGS_SCHEMA}
    updates: dict = {}
    for key, val in body.items():
        if key not in allowed:
            continue
        if key == "watch_regions_text":
            names = [ln.strip() for ln in str(val).splitlines() if ln.strip()]
            updates["watch_regions"] = [{"name": n} for n in names]
            continue
        updates[key] = val

    from .config import save_overrides
    save_overrides(updates, CONFIG_PATH)

    # Apply live by mutating the shared settings object in place.
    new = load_config(CONFIG_PATH)
    for field in type(new).model_fields:
        setattr(state.settings, field, getattr(new, field))

    restart = bool(set(body.keys()) & _RESTART_KEYS)
    return {"ok": True, "restart_recommended": restart}


@app.get("/api/route/{callsign}")
async def get_route(callsign: str, icao24: str = None,
                    lat: float = None, lon: float = None):
    route = await state.routes.get(callsign)
    if not route:
        return {"route": None}

    # Plausibility: if we know the aircraft position, make sure it's actually on
    # the corridor between origin and destination. Reused callsigns otherwise
    # produce nonsense (e.g. a Singapore→Hong Kong route over Europe).
    plausible = True
    if lat is not None and lon is not None:
        o, d = route.get("origin"), route.get("destination")
        if o and d and o.get("lat") is not None and d.get("lat") is not None:
            xtk = cross_track_km(lat, lon, o["lat"], o["lon"], d["lat"], d["lon"])
            near_o = haversine_km(lat, lon, o["lat"], o["lon"]) < 200
            near_d = haversine_km(lat, lon, d["lat"], d["lon"]) < 200
            plausible = xtk < 350 or near_o or near_d
    route["plausible"] = plausible

    # Only persist plausible routes to the flight log.
    if plausible and icao24 and state.settings.flight_history_enabled:
        o = (route.get("origin") or {}).get("iata") or (route.get("origin") or {}).get("icao")
        d = (route.get("destination") or {}).get("iata") or (route.get("destination") or {}).get("icao")
        if o or d:
            await state.db.set_flight_route(icao24, callsign.strip().upper(), o, d)
    return {"route": route}


@app.get("/api/track/{icao24}")
async def get_track(icao24: str):
    since = time.time() - state.settings.trail_minutes * 60
    points = await state.db.recent_track(icao24, since)
    return {"icao24": icao24.lower(), "track": points}


@app.get("/api/flights/{icao24}")
async def get_flights(icao24: str):
    return {"icao24": icao24.lower(),
            "flights": await state.db.recent_flights(icao24, limit=40)}


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

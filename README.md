# 🛫 Sky Watch

**Self-hostable live flight tracker with Discord alerts.** Sky Watch shows live air
traffic around your location on an interactive map and pings a Discord channel when
something interesting flies by — military aircraft, emergencies, rare types, or
anything on your personal watchlist.

Powered by the [OpenSky Network](https://opensky-network.org) API, Leaflet, and
FastAPI. No build tools, no database server, no bot tokens — just one config file.

![screenshot placeholder](docs/screenshot.png)

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOU/skywatch.git && cd skywatch

# 2. Run the launcher (first run auto-installs everything and creates config)
./start.sh          # Linux / macOS
start.cmd           # Windows

# 3. Edit config.yaml with your location (and optionally Discord webhook), run again
./start.sh
```

Open **http://localhost:8080** — done. 🛫

The only required setting is your `latitude` / `longitude`. Everything else has a
smart default. No OpenSky account? It still works (just polls a little slower). No
Discord webhook? It still works (map-only, no notifications).

---

## Docker

```bash
cp config.example.yaml config.yaml   # edit your location
docker-compose up -d
```

The app is now on **http://localhost:8080**. Data and logs persist in named volumes.

### Run the prebuilt image

```bash
docker run -d --name skywatch -p 8080:8080 \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v skywatch-data:/app/data \
  ghcr.io/YOU/skywatch:latest
```

---

## TrueNAS Scale

Add Sky Watch as a **custom app**:

- **Image**: `ghcr.io/YOU/skywatch:latest` (or build from this repo)
- **Port**: map container `8080` → a host port of your choice
- **Mount** a host file → `/app/config.yaml` (read-only) for your config
- **Mount** host paths → `/app/data` and `/app/logs` for persistence
- Set env `TZ` to your timezone (e.g. `Europe/Vienna`) and start the app

---

## Features

- 🗺️ Live Leaflet map, aircraft icons rotated by heading, color-coded by category
- 🎨 Categories: military (red), emergency (orange), watchlist (yellow), helicopter
  (green), normal (blue), rare (purple), ground vehicle (cyan), balloon (white)
- 🔔 Discord alerts for emergency squawks (7500/7600/7700), military aircraft, rare
  types, watchlist hits, and holding-pattern detection
- 🛩️ Aircraft enrichment (registration, type, operator) from the OpenSky metadata DB
- 📡 WebSocket live updates (markers move smoothly, no page reloads)
- 🔍 Filter panel + search by callsign / type / icao24 / registration
- 🌗 Dark & light mode, mobile responsive
- 🔒 Optional auth (none / basic / token)
- 📜 History of recent sightings and alerts

### Map layers & extras

- 🌧️ **Animated weather radar** (RainViewer) with a play/pause timeline
- 🛬 **Airports overlay** with live **METAR** weather in each popup (aviationweather.gov)
- ⚠️ **Conflict / hazard zones** built from live news feeds + a built-in region
  gazetteer — drawn on the map with the headlines that triggered them. Add your own
  RSS feeds or static zones (e.g. a military operating area) in config.
- 🌓 **Day / night terminator** overlay
- 📷 **Aircraft photos** in the detail card (Planespotters)
- 📊 **Live statistics** panel (counts by category / country / type, alert breakdown)
- 🧰 **Tools**: find-my-location, distance measure, fullscreen, altitude filter,
  sound alerts, and **CSV export** of history & alerts

> All layers use free, keyless data sources and can be toggled off in config.

---

## Setting up a Discord Webhook

1. In Discord, open **Server Settings → Integrations → Webhooks**
2. Click **New Webhook**, pick a channel, and **Copy Webhook URL**
3. Paste it into `config.yaml` as `discord_webhook: "https://discord.com/api/webhooks/…"`
4. Restart Sky Watch — alerts now post to that channel

---

## Building a Watchlist

Watchlist entries are matched by **icao24** (the aircraft's 24-bit hex address). To
find one:

- Look up the aircraft on [ADS-B Exchange](https://globe.adsbexchange.com) — the
  `icao` value in the URL/sidebar is the hex code
- Or find it on [FlightRadar24](https://www.flightradar24.com) under aircraft details
  (the "Mode S" code)

```yaml
watchlist:
  - icao24: "440b41"
    label: "RotorSky R22 (OE-XIW)"
  - icao24: "3c6444"
    label: "Antonov An-124"
```

---

## OpenSky API notes

OpenSky has migrated toward an OAuth2 API-client access model on top of the older
basic-auth accounts. Sky Watch supports **all three**:

| Mode        | Config keys                              | Poll interval |
|-------------|------------------------------------------|---------------|
| Anonymous   | _(none)_                                 | ~10 s         |
| Basic auth  | `opensky_username`, `opensky_password`   | ~5 s          |
| OAuth2      | `opensky_client_id`, `opensky_client_secret` | ~5 s     |

Sky Watch tracks rate limits and backs off automatically (exponential backoff on
errors, honoring `X-Rate-Limit-Retry-After`). See the live status in the footer.

---

## Advanced Configuration

All keys below are **optional** — add them to the same flat `config.yaml` only if you
need them.

| Key | Default | Description |
|-----|---------|-------------|
| `port` | `8080` | HTTP port |
| `host` | `0.0.0.0` | Bind address |
| `radius_km` | `50` | Alert/poll radius around your location |
| `poll_interval` | auto | Seconds between OpenSky polls (auto: 5 auth / 10 anon) |
| `default_zoom` | auto | Initial map zoom (auto from radius) |
| `password` | — | Set to enable **HTTP Basic** auth on the web UI |
| `username` | `admin` | Username for basic auth |
| `api_token` | — | Set to enable **token** auth (Bearer / `?token=`) |
| `auth_mode` | `auto` | `auto` \| `none` \| `basic` \| `token` |
| `dark_mode` | `true` | Dark UI + dark map tiles |
| `tile_url` | CARTO dark | Dark tile URL template |
| `tile_url_light` | OSM | Light tile URL template |
| `tile_attribution` | OSM/CARTO | Map attribution text |
| `public_url` | — | Public base URL used in Discord "View on Sky Watch" links |
| `discord_webhook_emergency` | — | Dedicated webhook for emergency alerts |
| `discord_webhook_military` | — | Dedicated webhook for military alerts |
| `alert_emergency` | `true` | Toggle emergency-squawk alerts |
| `alert_military` | `true` | Toggle military detection |
| `alert_rare` | `true` | Toggle rare-type alerts |
| `alert_watchlist` | `true` | Toggle watchlist alerts |
| `alert_holding` | `true` | Toggle holding-pattern detection |
| `alert_ground_vehicles` | `false` | Alert on ground vehicles |
| `alert_cooldown_minutes` | `30` | Per-aircraft per-type alert cooldown |
| `holding_min_loops` | `2` | Loops required to flag a holding pattern |
| `holding_max_radius_km` | `12` | Max area radius for holding detection |
| `holding_min_duration_s` | `180` | Min duration for holding detection |
| `military_typecodes` | `[]` | Extra military typecodes (extends built-ins) |
| `rare_typecodes` | `[]` | Extra rare typecodes (extends built-ins) |
| `military_keywords` | `[]` | Extra operator keywords for military detection |
| `weather_enabled` | `true` | RainViewer precipitation radar overlay |
| `metar_enabled` | `true` | METAR weather for airport popups |
| `airports_enabled` | `true` | Airports overlay |
| `airports_min_type` | `medium` | Smallest airport size to show (`small`/`medium`/`large`) |
| `airports_max` | `400` | Max airports drawn within radius |
| `photos_enabled` | `true` | Planespotters aircraft photos |
| `daynight_enabled` | `true` | Day/night terminator overlay |
| `stats_enabled` | `true` | Live statistics panel |
| `zones_enabled` | `true` | Conflict/hazard zone overlay |
| `news_feeds` | `[]` | Extra news RSS/Atom feeds (extends built-in defaults) |
| `news_feeds_replace` | `false` | `true` = use only `news_feeds`, ignore defaults |
| `zones_refresh_minutes` | `30` | How often to re-scan news feeds |
| `zones_min_mentions` | `1` | Headlines needed before a region is drawn |
| `conflict_zones` | `[]` | Static user-defined zones (`name`/`lat`/`lon`/`radius_km`/`note`) |
| `history_retention_hours` | `48` | How long to keep sightings/alerts |
| `metadata_update_days` | `7` | Metadata DB refresh interval |
| `metadata_auto_download` | `true` | Auto-download the OpenSky metadata DB |
| `log_level` | `INFO` | Logging level |
| `log_max_bytes` | `5000000` | Log rotation size |
| `log_backups` | `3` | Rotated log files to keep |
| `data_dir` | `data` | Data directory |
| `log_dir` | `logs` | Log directory |

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Health check (always open) |
| `GET /api/config` | Frontend bootstrap config |
| `GET /api/aircraft` | Current aircraft snapshot |
| `GET /api/track/{icao24}` | Recent track points for an aircraft |
| `GET /api/history` | Recent sightings |
| `GET /api/alerts` | Recent alerts |
| `GET /api/status` | API + server status |
| `GET /api/airports` | Airports within radius |
| `GET /api/weather/metars` | METARs in the area |
| `GET /api/weather/metar/{station}` | METAR for one station |
| `GET /api/zones` | Conflict/hazard zones (news + static) |
| `GET /api/photo/{icao24}` | Aircraft photo (Planespotters) |
| `GET /api/stats` | Live traffic statistics |
| `GET /api/export/history.csv` | Download sightings as CSV |
| `GET /api/export/alerts.csv` | Download alerts as CSV |
| `WS  /ws` | Live update stream |

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q                 # run tests
python -m backend.main    # run the server
```

---

## License

MIT — see [LICENSE](LICENSE).

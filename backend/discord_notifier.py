"""Discord webhook notifier: rich embeds with links, per-type webhooks."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from .config import Settings
from .models import AlertRecord
from .utils import fmt_altitude, fmt_speed

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.discord_webhook
                    or self.settings.discord_webhook_emergency
                    or self.settings.discord_webhook_military)

    async def send(self, alert: AlertRecord, photo_url: str | None = None,
                   ai_text: str | None = None) -> bool:
        webhook = self.settings.webhook_for(alert.alert_type)
        if not webhook:
            return False
        try:
            embed = self._embed(alert)
            if photo_url and self.settings.discord_photos:
                embed["image"] = {"url": photo_url}
            if ai_text:
                embed["description"] = f"🧠 **AI analysis**\n{ai_text[:1800]}"
            resp = await self._client.post(webhook, json={"embeds": [embed]})
            if resp.status_code in (200, 204):
                return True
            logger.warning("Discord webhook returned %s: %s",
                           resp.status_code, resp.text[:200])
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Discord webhook failed: %s", exc)
            return False

    def _embed(self, a: AlertRecord) -> dict:
        type_line = a.typecode or ""
        if a.label and a.alert_type in ("rare", "watchlist"):
            type_line = a.label if not a.typecode else f"{a.label} ({a.typecode})"

        fields = []
        if a.callsign:
            fields.append({"name": "Callsign", "value": a.callsign.strip(), "inline": True})
        if type_line:
            fields.append({"name": "Type", "value": type_line, "inline": True})
        if a.registration:
            fields.append({"name": "Registration", "value": a.registration, "inline": True})
        if a.operator:
            fields.append({"name": "Operator", "value": a.operator, "inline": True})
        if a.altitude_m is not None:
            fields.append({"name": "Altitude", "value": fmt_altitude(a.altitude_m), "inline": True})
        if a.speed_ms is not None:
            fields.append({"name": "Speed", "value": fmt_speed(a.speed_ms), "inline": True})
        if a.squawk:
            warn = " ⚠️" if a.alert_type == "emergency" else ""
            fields.append({"name": "Squawk", "value": f"{a.squawk}{warn}", "inline": True})
        if a.distance_km is not None:
            fields.append({"name": "Distance",
                           "value": f"{a.distance_km:.1f} km from base", "inline": True})

        links = []
        callsign = (a.callsign or "").strip()
        if callsign:
            links.append(f"📍 [FlightRadar24](https://www.flightradar24.com/{callsign})")
        links.append(
            f"📡 [ADS-B Exchange](https://globe.adsbexchange.com/?icao={a.icao24})"
        )
        if self.settings.public_url:
            base = self.settings.public_url.rstrip("/")
            links.append(f"🗺️ [Sky Watch]({base}/?focus={a.icao24})")
        if links:
            fields.append({"name": "Links", "value": "\n".join(links), "inline": False})

        embed = {
            "title": a.title,
            "color": a.color,
            "fields": fields,
            "footer": {"text": f"Sky Watch • icao24 {a.icao24}"},
            "timestamp": datetime.fromtimestamp(
                a.timestamp or datetime.now().timestamp(), tz=timezone.utc
            ).isoformat(),
        }
        # Optional static map thumbnail.
        if a.latitude is not None and a.longitude is not None:
            embed["thumbnail"] = {
                "url": (
                    "https://staticmap.openstreetmap.de/staticmap.php?center="
                    f"{a.latitude},{a.longitude}&zoom=9&size=300x200&markers="
                    f"{a.latitude},{a.longitude},red-pushpin"
                )
            }
        return embed

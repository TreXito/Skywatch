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
                   ai_text: str | None = None, ping_user: str | None = None,
                   webhook: str | None = None) -> bool:
        webhook = webhook or self.settings.webhook_for(alert.alert_type)
        if not webhook:
            return False
        try:
            embed = self._embed(alert)
            # Big image = map position (set in _embed); aircraft photo = thumbnail.
            if photo_url and self.settings.discord_photos:
                embed["thumbnail"] = {"url": photo_url}
            if ai_text:
                embed["description"] = f"🧠 **AI analysis**\n{ai_text[:1800]}"
            payload: dict = {"embeds": [embed]}
            if ping_user:
                payload["content"] = f"<@{ping_user}>"
                payload["allowed_mentions"] = {"users": [str(ping_user)]}
            return await self._post(webhook, payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Discord webhook failed: %s", exc)
            return False

    async def send_digest(self, title: str, items: list[dict]) -> bool:
        """Post a single 'top aircraft right now' digest embed (no ping)."""
        webhook = self.settings.webhook_for("highlight")
        if not webhook or not items:
            return False
        lines = []
        for i in items:
            cs = (i.get("callsign") or i.get("icao24") or "").strip()
            base = i.get("public_url") or self.settings.public_url
            link = f"{base.rstrip('/')}/?focus={i['icao24']}" if base else None
            loc = i.get("origin_country") or ""
            head = f"**{cs}** ({i.get('typecode') or '?'})"
            head = f"[{head}]({link})" if link else head
            text = i.get("analysis") or i.get("reason") or i.get("marker_category", "")
            block = f"{head}{(' · ' + loc) if loc else ''}\n{text}"
            srcs = i.get("sources") or []
            if srcs:
                block += "\n" + " · ".join(f"[src{n+1}]({u})" for n, u in enumerate(srcs[:3]))
            lines.append(block)
        embed = {
            "title": title,
            "description": "\n\n".join(lines)[:3900],
            "color": 0x9B59B6,
            "footer": {"text": "Sky Watch • AI top picks"},
        }
        try:
            return await self._post(webhook, {"embeds": [embed]})
        except Exception as exc:  # noqa: BLE001
            logger.error("Discord digest failed: %s", exc)
            return False

    async def _post(self, webhook: str, payload: dict) -> bool:
        resp = await self._client.post(webhook, json=payload)
        if resp.status_code in (200, 204):
            return True
        logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text[:200])
        return False

    def _embed(self, a: AlertRecord) -> dict:
        # Readable aircraft model, e.g. "Boeing 747-8 (B748)" instead of just "B748".
        full_model = " ".join(filter(None, [a.manufacturer, a.model])).strip()
        if full_model and a.typecode:
            type_line = f"{full_model} ({a.typecode})"
        elif full_model:
            type_line = full_model
        else:
            type_line = a.typecode or "Unknown type"

        fields = []
        if a.callsign:
            fields.append({"name": "Callsign", "value": a.callsign.strip(), "inline": True})
        fields.append({"name": "Aircraft", "value": type_line, "inline": True})
        if a.label and a.label != a.model:
            fields.append({"name": "Why", "value": a.label, "inline": False})
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
        # Where it is, not distance-from-base (which is useless for worldwide finds).
        if a.latitude is not None and a.longitude is not None:
            fields.append({"name": "Position",
                           "value": f"{a.latitude:.3f}, {a.longitude:.3f}", "inline": True})

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
        # Big static map showing exactly where the aircraft is (Yandex – keyless
        # and reliable; note ll/pt take lon,lat order).
        if a.latitude is not None and a.longitude is not None:
            embed["image"] = {
                "url": (
                    "https://static-maps.yandex.ru/1.x/?l=map&z=6&size=600,300"
                    f"&ll={a.longitude},{a.latitude}"
                    f"&pt={a.longitude},{a.latitude},pm2rdm"
                )
            }
        return embed

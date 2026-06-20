"""Local Ollama integration for on-the-fly AI analysis of alerts and traffic.

Talks to a local Ollama server (default http://localhost:11434). Fully optional and
best-effort: if Ollama is unreachable or slow, callers get None and the app carries
on. Used to enrich Discord alerts with a short analysis and to build periodic digests.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from .models import AlertRecord
from .utils import fmt_altitude, fmt_speed

logger = logging.getLogger(__name__)


class OllamaService:
    def __init__(self, settings):
        self.settings = settings
        # Generous timeout – local models can be slow on first token.
        self._client = httpx.AsyncClient(timeout=45.0)
        self._available: Optional[bool] = None

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def enabled(self) -> bool:
        return self.settings.ollama_enabled

    async def available(self) -> bool:
        """Cheap reachability check (cached)."""
        if not self.enabled:
            return False
        if self._available is not None:
            return self._available
        try:
            resp = await self._client.get(
                f"{self.settings.ollama_url.rstrip('/')}/api/tags", timeout=5.0
            )
            self._available = resp.status_code == 200
        except Exception:  # noqa: BLE001
            self._available = False
        if not self._available:
            logger.warning("Ollama not reachable at %s", self.settings.ollama_url)
        return self._available

    async def _generate(self, prompt: str, system: str = "") -> Optional[str]:
        if not await self.available():
            return None
        try:
            resp = await self._client.post(
                f"{self.settings.ollama_url.rstrip('/')}/api/generate",
                json={
                    "model": self.settings.ollama_model,
                    "prompt": prompt,
                    "system": system or _SYSTEM_PROMPT,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_predict": 220},
                },
            )
            resp.raise_for_status()
            text = (resp.json().get("response") or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama generate failed: %s", exc)
            self._available = None  # re-check next time
            return None

    async def analyze_alert(self, alert: AlertRecord, route: Optional[dict] = None) -> Optional[str]:
        if not (self.enabled and self.settings.ollama_analyze_alerts):
            return None
        lines = [
            f"Alert type: {alert.alert_type}",
            f"Title: {alert.title}",
            f"Callsign: {alert.callsign or 'unknown'}",
            f"Type: {alert.typecode or 'unknown'}",
            f"Registration: {alert.registration or 'unknown'}",
            f"Operator: {alert.operator or 'unknown'}",
            f"Squawk: {alert.squawk or 'n/a'}",
            f"Altitude: {fmt_altitude(alert.altitude_m)}",
            f"Speed: {fmt_speed(alert.speed_ms)}",
            f"Distance from base: {alert.distance_km:.0f} km" if alert.distance_km is not None else "",
        ]
        if route:
            o = (route.get("origin") or {})
            d = (route.get("destination") or {})
            lines.append(f"Route: {o.get('city') or o.get('iata') or '?'} -> "
                         f"{d.get('city') or d.get('iata') or '?'}")
        prompt = (
            "An aircraft just triggered an alert in a flight-tracking system. "
            "In 2-3 short sentences, explain what is notable about it and why it "
            "might be interesting (aircraft role, operator, possible mission, or "
            "anything unusual). Be concise and factual; avoid speculation presented "
            "as fact.\n\n" + "\n".join(filter(None, lines))
        )
        return await self._generate(prompt)

    async def digest(self, aircraft_list) -> Optional[str]:
        if not self.enabled or self.settings.ollama_digest_minutes <= 0:
            return None
        sample = []
        for a in aircraft_list[:40]:
            sample.append(
                f"{(a.callsign or a.icao24).strip()} {a.typecode or ''} "
                f"{a.marker_category} {a.origin_country or ''}".strip()
            )
        prompt = (
            f"Here are {len(aircraft_list)} aircraft currently near the monitoring "
            "location. Write a short 2-4 sentence situational summary: how busy it "
            "is, any military/rare/interesting traffic, and notable patterns.\n\n"
            + "\n".join(sample)
        )
        return await self._generate(prompt)


_SYSTEM_PROMPT = (
    "You are an aviation analyst assistant embedded in a live flight tracker. "
    "You write brief, sharp, factual notes for an enthusiast audience. Never invent "
    "specific facts you cannot infer; keep it to a few sentences."
)

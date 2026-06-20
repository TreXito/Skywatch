"""Async OpenSky Network API client.

Supports both authentication models OpenSky has used:
  * Legacy HTTP Basic auth (username/password from a free account)
  * New OAuth2 client-credentials flow (client_id/client_secret) – OpenSky migrated
    to Keycloak-issued bearer tokens; see
    https://openskynetwork.github.io/opensky-api/

Anonymous access also works (heavily rate limited). The client tracks request
status, applies a minimum interval between polls, and backs off on errors / 429s.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .constants import OPENSKY_STATES_URL, OPENSKY_TOKEN_URL
from .models import Aircraft
from .utils import bounding_box

logger = logging.getLogger(__name__)


@dataclass
class ApiStatus:
    last_update: float = 0.0
    next_update: float = 0.0
    last_error: Optional[str] = None
    last_count: int = 0
    auth_mode: str = "anonymous"   # anonymous | basic | oauth2
    rate_limited: bool = False
    consecutive_errors: int = 0

    def as_dict(self) -> dict:
        return {
            "last_update": self.last_update,
            "next_update": self.next_update,
            "last_error": self.last_error,
            "last_count": self.last_count,
            "auth_mode": self.auth_mode,
            "rate_limited": self.rate_limited,
        }


class OpenSkyClient:
    def __init__(self, settings):
        self.settings = settings
        self.status = ApiStatus()
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

        if settings.opensky_client_id and settings.opensky_client_secret:
            self.status.auth_mode = "oauth2"
        elif settings.opensky_username and settings.opensky_password:
            self.status.auth_mode = "basic"
        else:
            self.status.auth_mode = "anonymous"

    async def close(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------- OAuth2

    async def _get_token(self) -> Optional[str]:
        """Fetch / refresh an OAuth2 bearer token (client-credentials grant)."""
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        try:
            resp = await self._client.post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.opensky_client_id,
                    "client_secret": self.settings.opensky_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            payload = resp.json()
            self._token = payload["access_token"]
            self._token_expiry = time.time() + float(payload.get("expires_in", 1800))
            logger.info("Obtained OpenSky OAuth2 token")
            return self._token
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to obtain OpenSky OAuth2 token: %s", exc)
            self.status.last_error = f"OAuth2 token error: {exc}"
            return None

    # ----------------------------------------------------------- polling

    async def fetch_states(self) -> Optional[list[Aircraft]]:
        """Fetch state vectors within the configured bounding box.

        Returns a list of Aircraft, or None on error (caller keeps previous data).
        """
        s = self.settings
        lat_min, lat_max, lon_min, lon_max = bounding_box(
            s.latitude, s.longitude, s.radius_km
        )
        params = {
            "lamin": lat_min, "lamax": lat_max,
            "lomin": lon_min, "lomax": lon_max,
        }

        headers = {}
        auth = None
        if self.status.auth_mode == "oauth2":
            token = await self._get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.status.auth_mode == "basic":
            auth = (s.opensky_username, s.opensky_password)

        try:
            resp = await self._client.get(
                OPENSKY_STATES_URL, params=params, headers=headers, auth=auth
            )
            if resp.status_code == 429:
                self.status.rate_limited = True
                self.status.consecutive_errors += 1
                retry_after = resp.headers.get("X-Rate-Limit-Retry-After-Seconds")
                self.status.last_error = "Rate limited by OpenSky (429)"
                logger.warning(
                    "OpenSky rate limited; retry after %s s", retry_after or "?"
                )
                self._schedule_next(backoff=True, retry_after=retry_after)
                return None

            resp.raise_for_status()
            data = resp.json()
            states = data.get("states") or []
            aircraft = [
                Aircraft.from_state_vector(sv)
                for sv in states
                if sv and sv[0]
            ]
            self.status.rate_limited = False
            self.status.consecutive_errors = 0
            self.status.last_error = None
            self.status.last_count = len(aircraft)
            self.status.last_update = time.time()
            self._schedule_next()
            return aircraft

        except httpx.HTTPStatusError as exc:
            self.status.consecutive_errors += 1
            self.status.last_error = f"HTTP {exc.response.status_code}"
            logger.error("OpenSky HTTP error: %s", exc)
            self._schedule_next(backoff=True)
            return None
        except Exception as exc:  # noqa: BLE001
            self.status.consecutive_errors += 1
            self.status.last_error = str(exc)
            logger.error("OpenSky request failed: %s", exc)
            self._schedule_next(backoff=True)
            return None

    def _schedule_next(self, backoff: bool = False, retry_after=None) -> None:
        interval = self.settings.effective_poll_interval
        if retry_after:
            try:
                interval = max(interval, float(retry_after))
            except (TypeError, ValueError):
                pass
        elif backoff:
            # Exponential backoff capped at 5 minutes.
            interval = min(300.0, interval * (2 ** min(self.status.consecutive_errors, 5)))
        self.status.next_update = time.time() + interval

    @property
    def next_delay(self) -> float:
        """Seconds to wait before the next poll (>= 0)."""
        return max(0.0, self.status.next_update - time.time())

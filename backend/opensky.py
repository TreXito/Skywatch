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
from datetime import datetime, timezone
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
    credits_used: int = 0          # estimated OpenSky credits used today
    credit_budget: int = 0
    budget_reached: bool = False

    def as_dict(self) -> dict:
        return {
            "last_update": self.last_update,
            "next_update": self.next_update,
            "last_error": self.last_error,
            "last_count": self.last_count,
            "auth_mode": self.auth_mode,
            "rate_limited": self.rate_limited,
            "credits_used": self.credits_used,
            "credit_budget": self.credit_budget,
            "budget_reached": self.budget_reached,
        }


class OpenSkyClient:
    def __init__(self, settings):
        self.settings = settings
        self.status = ApiStatus()
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._last_call_ts: float = 0.0
        self._last_viewport_call: float = 0.0
        # bbox key -> (timestamp, aircraft)
        self._viewport_cache: dict = {}
        self._credit_day = None
        self._credits_used = 0

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

    # ----------------------------------------------------------- credits

    @staticmethod
    def _estimate_credits(bbox: Optional[tuple]) -> int:
        """OpenSky bills by query area: 1/2/3/4 credits, 4 for the whole world."""
        if bbox is None:
            return 4
        area = abs(bbox[1] - bbox[0]) * abs(bbox[3] - bbox[2])
        if area <= 25:
            return 1
        if area <= 100:
            return 2
        if area <= 400:
            return 3
        return 4

    def _account(self, bbox: Optional[tuple]) -> None:
        today = datetime.now(timezone.utc).date()
        if self._credit_day != today:
            self._credit_day = today
            self._credits_used = 0
            self.status.budget_reached = False
        self._credits_used += self._estimate_credits(bbox)
        self.status.credits_used = self._credits_used
        self.status.credit_budget = self.settings.daily_credit_budget

    @property
    def credits_remaining(self) -> int:
        return max(0, self.settings.daily_credit_budget - self._credits_used)

    # ----------------------------------------------------------- polling

    class RateLimited(Exception):
        pass

    async def _request(self, bbox: Optional[tuple]) -> list[Aircraft]:
        """Low-level OpenSky states request. `bbox` = (lamin,lamax,lomin,lomax)
        or None for the whole world. Raises on error / rate limit."""
        s = self.settings
        params = {}
        if bbox is not None:
            params = {
                "lamin": bbox[0], "lamax": bbox[1],
                "lomin": bbox[2], "lomax": bbox[3],
            }
        headers = {}
        auth = None
        if self.status.auth_mode == "oauth2":
            token = await self._get_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif self.status.auth_mode == "basic":
            auth = (s.opensky_username, s.opensky_password)

        resp = await self._client.get(
            OPENSKY_STATES_URL, params=params, headers=headers, auth=auth
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("X-Rate-Limit-Retry-After-Seconds")
            raise OpenSkyClient.RateLimited(retry_after or "")
        resp.raise_for_status()
        states = (resp.json() or {}).get("states") or []
        self._last_call_ts = time.time()
        self._account(bbox)
        return [Aircraft.from_state_vector(sv) for sv in states if sv and sv[0]]

    def _over_budget(self, background: bool) -> bool:
        """True if a request should be skipped to stay within the daily budget.

        Interactive (browser) fetches stop earlier so a chunk is always reserved
        for the essential background scans; background scans use the full budget.
        The whole point: max out the budget without ever exceeding it.
        """
        budget = self.settings.daily_credit_budget
        threshold = budget if background else int(budget * 0.85)
        return self._credits_used >= threshold

    async def fetch_states(self) -> Optional[list[Aircraft]]:
        """Home-radius poll used for alerts/history. Updates status + schedule."""
        s = self.settings
        bbox = bounding_box(s.latitude, s.longitude, s.radius_km)
        if self._over_budget(background=True):
            self.status.budget_reached = True
            self._schedule_next()
            return None
        try:
            aircraft = await self._request(bbox)
            self.status.rate_limited = False
            self.status.consecutive_errors = 0
            self.status.last_error = None
            self.status.last_count = len(aircraft)
            self.status.last_update = time.time()
            self._schedule_next()
            return aircraft
        except OpenSkyClient.RateLimited as exc:
            self.status.rate_limited = True
            self.status.consecutive_errors += 1
            self.status.last_error = "Rate limited by OpenSky (429)"
            logger.warning("OpenSky rate limited; retry after %s s", exc or "?")
            self._schedule_next(backoff=True, retry_after=str(exc) or None)
            return None
        except Exception as exc:  # noqa: BLE001
            self.status.consecutive_errors += 1
            self.status.last_error = str(exc)
            logger.error("OpenSky request failed: %s", exc)
            self._schedule_next(backoff=True)
            return None

    async def fetch_viewport(self, bbox: Optional[tuple],
                             background: bool = False) -> Optional[list[Aircraft]]:
        """Fetch aircraft for an arbitrary bbox (map viewport) or None=global.

        Cached per rounded bbox for one poll interval, with a global minimum gap
        between real calls so map panning can't hammer OpenSky.

        `background=True` marks essential scans (home/region/global) that always
        run. Interactive (browser) calls are skipped once the daily credit budget
        is reached, so the app keeps running a full day without a hard rate-limit.
        """
        key = "global" if bbox is None else tuple(round(v, 1) for v in bbox)
        now = time.time()
        cached = self._viewport_cache.get(key)
        ttl = self.settings.effective_poll_interval
        if cached and now - cached[0] < ttl:
            return cached[1]

        # Credit budget guard: background scans use the full budget, interactive
        # map fetches reserve a margin so the scans always have credits left.
        if self._over_budget(background):
            self.status.budget_reached = True
            return cached[1] if cached else None

        # Global politeness gap between any two viewport calls.
        if now - self._last_viewport_call < max(1.5, ttl / 2) and cached:
            return cached[1]
        self._last_viewport_call = now

        try:
            aircraft = await self._request(bbox)
            # Bound the cache size.
            if len(self._viewport_cache) > 64:
                self._viewport_cache.clear()
            self._viewport_cache[key] = (now, aircraft)
            return aircraft
        except OpenSkyClient.RateLimited:
            self.status.rate_limited = True
            return cached[1] if cached else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Viewport fetch failed: %s", exc)
            return cached[1] if cached else None

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

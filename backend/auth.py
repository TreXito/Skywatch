"""Configurable authentication for web routes and WebSocket connections.

Modes (resolved from Settings.effective_auth_mode):
  * none  – open access (trusted networks)
  * basic – HTTP Basic auth (username/password); presence of `password` enables it
  * token – Bearer token / `?token=` query param (api_token)
"""
from __future__ import annotations

import base64
import logging
import secrets
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response

logger = logging.getLogger(__name__)

# Paths that never require auth (health checks, login assets, the LAN-only MSFS
# position push from the SimConnect bridge).
_OPEN_PATHS = {"/api/health", "/favicon.ico", "/api/msfs_position",
               "/api/nearest_airport"}


class AuthManager:
    def __init__(self, settings):
        self.settings = settings
        self.mode = settings.effective_auth_mode
        logger.info("Auth mode: %s", self.mode)

    # ----------------------------------------------------------- checks

    def _check_basic(self, header: Optional[str]) -> bool:
        if not header or not header.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            user, _, pw = decoded.partition(":")
        except Exception:  # noqa: BLE001
            return False
        return (
            secrets.compare_digest(user, self.settings.username)
            and secrets.compare_digest(pw, self.settings.password)
        )

    def _check_token(self, request: Request) -> bool:
        token = self.settings.api_token
        if not token:
            return False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            if secrets.compare_digest(header.split(" ", 1)[1], token):
                return True
        q = request.query_params.get("token")
        if q and secrets.compare_digest(q, token):
            return True
        # Allow cookie set by the login flow.
        cookie = request.cookies.get("skywatch_token")
        if cookie and secrets.compare_digest(cookie, token):
            return True
        return False

    def is_authorized(self, request: Request) -> bool:
        if self.mode == "none":
            return True
        if request.url.path in _OPEN_PATHS:
            return True
        if self.mode == "basic":
            return self._check_basic(request.headers.get("authorization"))
        if self.mode == "token":
            return self._check_token(request)
        return True

    def authorize_ws_token(self, token: Optional[str], auth_header: Optional[str]) -> bool:
        """WebSocket auth (query token or Authorization header)."""
        if self.mode == "none":
            return True
        if self.mode == "token":
            if token and secrets.compare_digest(token, self.settings.api_token):
                return True
            if auth_header and auth_header.lower().startswith("bearer "):
                return secrets.compare_digest(
                    auth_header.split(" ", 1)[1], self.settings.api_token
                )
            return False
        if self.mode == "basic":
            return self._check_basic(auth_header)
        return True

    # ----------------------------------------------------------- responses

    def challenge(self) -> Response:
        if self.mode == "basic":
            return Response(
                content="Authentication required",
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": 'Basic realm="Sky Watch"'},
            )
        return HTMLResponse(_TOKEN_LOGIN_PAGE, status_code=status.HTTP_401_UNAUTHORIZED)


_TOKEN_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Sky Watch – Login</title>
<style>
  body{font-family:system-ui,sans-serif;background:#10141a;color:#e6e6e6;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  .card{background:#1a2029;padding:2rem;border-radius:12px;width:320px;
        box-shadow:0 8px 30px rgba(0,0,0,.4)}
  h1{font-size:1.3rem;margin:0 0 1rem} input{width:100%;padding:.6rem;margin:.4rem 0;
     border-radius:8px;border:1px solid #333;background:#0d1117;color:#fff;box-sizing:border-box}
  button{width:100%;padding:.6rem;margin-top:.6rem;border:0;border-radius:8px;
         background:#3498db;color:#fff;font-weight:600;cursor:pointer}
</style></head><body>
<form class="card" onsubmit="event.preventDefault();
  document.cookie='skywatch_token='+encodeURIComponent(t.value)+';path=/;max-age=31536000';
  location.reload();">
  <h1>🛫 Sky Watch</h1>
  <p>Enter the password:</p>
  <input id="t" type="password" placeholder="Password" autofocus>
  <button type="submit">Enter</button>
</form></body></html>"""

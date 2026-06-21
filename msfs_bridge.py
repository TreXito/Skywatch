#!/usr/bin/env python3
"""Sky Watch – MSFS2024 SimConnect bridge (runs on the Windows gaming PC).

Connects to a running MSFS2024 via SimConnect, reads the own-aircraft position a
few times a second, and POSTs it to the Sky Watch server on your LAN. It needs no
configuration inside MSFS – SimConnect attaches automatically when the sim runs.

Usage:
    pip install SimConnect requests PyYAML
    python msfs_bridge.py                 # run the bridge
    python msfs_bridge.py --install-autostart   # start automatically at logon
    python msfs_bridge.py --uninstall-autostart

Config: msfs_bridge.yaml next to this script (see msfs_bridge.example.yaml).
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

try:
    import requests
    import yaml
except ImportError:
    print("Missing deps. Run:  pip install SimConnect requests PyYAML")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "msfs_bridge.yaml")


def load_config(path: str) -> dict:
    cfg = {
        "server_url": "http://192.168.0.250:15000/api/msfs_position",
        "poll_interval_seconds": 2,
        "api_token": "",          # Sky Watch web password / token, if auth is on
        # Optional: live "now flying" status on Discord (everyone can follow along).
        # Rich Presence shows it under YOUR name ("Playing …") like a game status.
        "discord_rpc_client_id": "",      # a Discord app Client ID (see README)
        # (Optional, separate) channel webhook post – usually you want RPC, not this.
        "discord_webhook": "",
        "discord_name": "A pilot",
        "discord_update_seconds": 60,
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg.update(data.get("msfs_bridge", data))
    else:
        print(f"[!] No config at {path} – using defaults. Copy "
              f"msfs_bridge.example.yaml -> msfs_bridge.yaml and edit it.")
    return cfg


def _bcd_squawk(value) -> str | None:
    """SimConnect TRANSPONDER_CODE is BCD16 (0x1200 == squawk 1200)."""
    try:
        return f"{int(value):04X}"
    except (TypeError, ValueError):
        return None


def read_position(aq) -> dict | None:
    """Read the own-aircraft state via the SimConnect AircraftRequests helper."""
    lat = aq.get("PLANE_LATITUDE")
    lon = aq.get("PLANE_LONGITUDE")
    if lat is None or lon is None:
        return None

    heading_rad = aq.get("PLANE_HEADING_DEGREES_TRUE")  # wrapper returns radians
    heading = (math.degrees(heading_rad) % 360) if heading_rad is not None else None
    try:
        aircraft = aq.get("TITLE")
        if isinstance(aircraft, bytes):
            aircraft = aircraft.decode(errors="ignore")
    except Exception:  # noqa: BLE001
        aircraft = None

    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "altitude_ft": _f(aq.get("PLANE_ALTITUDE")),
        "true_airspeed_kts": _f(aq.get("AIRSPEED_TRUE")),
        "heading": heading,
        "vertical_speed_fpm": _f(aq.get("VERTICAL_SPEED")),
        "aircraft": str(aircraft).strip() if aircraft else None,
        "squawk": _bcd_squawk(aq.get("TRANSPONDER_CODE:1")),
        "on_ground": bool(aq.get("SIM_ON_GROUND")),
    }


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_COMPASS = ["North", "North-East", "East", "South-East",
            "South", "South-West", "West", "North-West"]


def _compass(deg) -> str:
    try:
        return _COMPASS[round(float(deg) / 45) % 8]
    except (TypeError, ValueError):
        return "—"


class DiscordReporter:
    """Posts a friendly, plain-English 'now flying' status to Discord and keeps it
    updated, so anyone can follow along (not just aviation nerds)."""

    AIRBORNE_KTS = 50

    def __init__(self, cfg: dict, session: requests.Session, server_base: str):
        self.webhook = cfg.get("discord_webhook", "")
        self.name = cfg.get("discord_name", "A pilot")
        self.every = max(20, int(cfg.get("discord_update_seconds", 60)))
        self.session = session
        self.base = server_base
        self.flying = False
        self.msg_id = None
        self.departure = "somewhere"
        self.start = 0.0
        self.last_edit = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.webhook)

    def _nearest(self, lat, lon) -> str:
        try:
            r = self.session.get(f"{self.base}/api/nearest_airport",
                                  params={"lat": lat, "lon": lon}, timeout=4)
            return (r.json().get("airport") or "an unknown spot")
        except Exception:  # noqa: BLE001
            return "an unknown spot"

    def update(self, pos: dict) -> None:
        if not self.enabled:
            return
        speed = pos.get("true_airspeed_kts") or 0
        airborne = (not pos.get("on_ground")) and speed > self.AIRBORNE_KTS
        now = time.time()
        if airborne and not self.flying:
            self.flying = True
            self.start = now
            self.departure = self._nearest(pos["latitude"], pos["longitude"])
            self._post_takeoff(pos)
        elif self.flying and airborne and now - self.last_edit >= self.every:
            self._edit_inflight(pos)
        elif self.flying and pos.get("on_ground") and speed < self.AIRBORNE_KTS:
            self._post_landing(pos)
            self.flying = False
            self.msg_id = None

    @staticmethod
    def _speeds(kts):
        kmh = round((kts or 0) * 1.852)
        mph = round((kts or 0) * 1.151)
        return f"{kmh} km/h ({mph} mph)"

    @staticmethod
    def _alts(ft):
        m = round((ft or 0) * 0.3048)
        return f"{m:,} m ({round(ft or 0):,} ft) high"

    def _embed(self, pos, title, desc, color):
        return {"title": title, "description": desc, "color": color, "fields": [
            {"name": "Aircraft", "value": pos.get("aircraft") or "Unknown", "inline": True},
            {"name": "Speed", "value": self._speeds(pos.get("true_airspeed_kts")), "inline": True},
            {"name": "Altitude", "value": self._alts(pos.get("altitude_ft")), "inline": True},
            {"name": "Heading", "value": f"{_compass(pos.get('heading'))}", "inline": True},
        ], "footer": {"text": "Live from Microsoft Flight Simulator · Sky Watch"}}

    def _post_takeoff(self, pos):
        e = self._embed(pos, f"✈️ {self.name} just took off!",
                        f"**{self.name}** is now flying a **{pos.get('aircraft') or 'plane'}**, "
                        f"departing from **{self.departure}**. Follow along below!", 0x00B3FF)
        try:
            r = self.session.post(self.webhook + "?wait=true", json={"embeds": [e]}, timeout=6)
            self.msg_id = (r.json() or {}).get("id")
            self.last_edit = time.time()
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Discord takeoff post failed: {exc}")

    def _edit_inflight(self, pos):
        near = self._nearest(pos["latitude"], pos["longitude"])
        mins = round((time.time() - self.start) / 60)
        e = self._embed(pos, f"✈️ {self.name} is flying",
                        f"**{self.name}** is flying a **{pos.get('aircraft') or 'plane'}**, "
                        f"now near **{near}** — {mins} min since takeoff from **{self.departure}**.",
                        0x00B3FF)
        try:
            if self.msg_id:
                self.session.patch(f"{self.webhook}/messages/{self.msg_id}",
                                   json={"embeds": [e]}, timeout=6)
            self.last_edit = time.time()
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Discord update failed: {exc}")

    def _post_landing(self, pos):
        arr = self._nearest(pos["latitude"], pos["longitude"])
        mins = round((time.time() - self.start) / 60)
        e = {"title": f"🛬 {self.name} has landed!",
             "description": f"**{self.name}** landed at **{arr}** after a "
                            f"{mins}-minute flight from **{self.departure}** in a "
                            f"**{pos.get('aircraft') or 'plane'}**. Nice one!",
             "color": 0x2ECC71,
             "footer": {"text": "Live from Microsoft Flight Simulator · Sky Watch"}}
        try:
            if self.msg_id:
                self.session.patch(f"{self.webhook}/messages/{self.msg_id}",
                                   json={"embeds": [e]}, timeout=6)
            else:
                self.session.post(self.webhook, json={"embeds": [e]}, timeout=6)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] Discord landing post failed: {exc}")


class DiscordPresence:
    """Discord Rich Presence – shows the flight as YOUR status ('Playing …'), like a
    game. Plain English so anyone gets it. Needs the local Discord client running
    and a Discord app Client ID (pip install pypresence)."""

    AIRBORNE_KTS = 50

    def __init__(self, cfg: dict, session: requests.Session, server_base: str):
        self.client_id = str(cfg.get("discord_rpc_client_id", "")).strip()
        self.session = session
        self.base = server_base
        self.rpc = None
        self.flying = False
        self.start = 0.0
        self.departure = ""
        self.last = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id)

    def _connect(self) -> bool:
        if self.rpc:
            return True
        try:
            from pypresence import Presence
            self.rpc = Presence(self.client_id)
            self.rpc.connect()
            print("[+] Discord Rich Presence connected.")
            return True
        except Exception as exc:  # noqa: BLE001 – Discord not running / no lib
            self.rpc = None
            return False

    def _nearest(self, lat, lon) -> str:
        try:
            r = self.session.get(f"{self.base}/api/nearest_airport",
                                 params={"lat": lat, "lon": lon}, timeout=4)
            return r.json().get("airport") or ""
        except Exception:  # noqa: BLE001
            return ""

    def update(self, pos: dict) -> None:
        if not self.enabled or not self._connect():
            return
        speed = pos.get("true_airspeed_kts") or 0
        airborne = (not pos.get("on_ground")) and speed > self.AIRBORNE_KTS
        now = time.time()
        if airborne and not self.flying:
            self.flying = True
            self.start = now
            self.departure = self._nearest(pos["latitude"], pos["longitude"])
        if not airborne and self.flying and pos.get("on_ground"):
            self.flying = False
        if now - self.last < 15:
            return
        self.last = now

        aircraft = pos.get("aircraft") or "a plane"
        try:
            if self.flying:
                kmh = round(speed * 1.852)
                m = round((pos.get("altitude_ft") or 0) * 0.3048)
                near = self._nearest(pos["latitude"], pos["longitude"])
                route = f"{self.departure or '?'} → {near}" if near else (self.departure or "")
                details = f"Flying a {aircraft}"[:128]
                state = f"{route} · {kmh} km/h · {m} m high".strip(" ·")[:128]
                self.rpc.update(details=details, state=state, start=int(self.start),
                                large_text="Microsoft Flight Simulator 2024")
            else:
                self.rpc.update(details="On the ground", state=aircraft[:128],
                                large_text="Microsoft Flight Simulator 2024")
        except Exception:  # noqa: BLE001 – Discord closed
            self.rpc = None

    def close(self) -> None:
        try:
            if self.rpc:
                self.rpc.clear()
                self.rpc.close()
        except Exception:  # noqa: BLE001
            pass


def run(cfg: dict) -> None:
    from SimConnect import SimConnect, AircraftRequests  # imported lazily

    url = cfg["server_url"]
    interval = max(0.5, float(cfg.get("poll_interval_seconds", 2)))
    headers = {}
    if cfg.get("api_token"):
        headers["Authorization"] = f"Bearer {cfg['api_token']}"
    session = requests.Session()
    server_base = url.split("/api/")[0]
    discord = DiscordReporter(cfg, session, server_base)   # optional channel webhook
    presence = DiscordPresence(cfg, session, server_base)  # Discord status (RPC)

    extras = ("  +RPC" if presence.enabled else "") + ("  +webhook" if discord.enabled else "")
    print(f"[*] Sky Watch MSFS bridge → {url} (every {interval}s){extras}")
    sm = None
    aq = None
    while True:
        try:
            if sm is None:
                print("[*] Waiting for MSFS… (SimConnect)")
                sm = SimConnect()           # raises until the sim is running
                aq = AircraftRequests(sm, _time=0)
                print("[+] Connected to MSFS.")

            pos = read_position(aq)
            if pos:
                try:
                    session.post(url, json=pos, headers=headers, timeout=5)
                except requests.RequestException as exc:
                    print(f"[!] POST failed: {exc}")
                for reporter in (discord, presence):
                    try:
                        reporter.update(pos)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[!] Discord error: {exc}")
            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[*] Bye.")
            return
        except Exception as exc:  # noqa: BLE001 – sim closed / connection lost
            print(f"[!] Lost SimConnect ({exc}); retrying in 5s…")
            try:
                if sm:
                    sm.exit()
            except Exception:  # noqa: BLE001
                pass
            sm, aq = None, None
            time.sleep(5)


# --------------------------------------------------------------- autostart

def _startup_vbs_path() -> str:
    startup = os.path.join(os.environ.get("APPDATA", ""),
                           r"Microsoft\Windows\Start Menu\Programs\Startup")
    return os.path.join(startup, "skywatch_msfs_bridge.vbs")


def install_autostart() -> None:
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    script = os.path.abspath(__file__)
    vbs = _startup_vbs_path()
    os.makedirs(os.path.dirname(vbs), exist_ok=True)
    # Launch hidden (no console window) at every logon.
    with open(vbs, "w", encoding="utf-8") as f:
        f.write(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{script}""", 0, False\n')
    print(f"[+] Autostart installed: {vbs}")
    print("    It now starts hidden at every Windows logon.")


def uninstall_autostart() -> None:
    vbs = _startup_vbs_path()
    if os.path.exists(vbs):
        os.remove(vbs)
        print(f"[+] Autostart removed: {vbs}")
    else:
        print("[*] No autostart entry found.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Sky Watch MSFS2024 SimConnect bridge")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--install-autostart", action="store_true")
    ap.add_argument("--uninstall-autostart", action="store_true")
    args = ap.parse_args()

    if args.install_autostart:
        install_autostart()
        return
    if args.uninstall_autostart:
        uninstall_autostart()
        return
    run(load_config(args.config))


if __name__ == "__main__":
    main()

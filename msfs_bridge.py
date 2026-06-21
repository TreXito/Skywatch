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


def run(cfg: dict) -> None:
    from SimConnect import SimConnect, AircraftRequests  # imported lazily

    url = cfg["server_url"]
    interval = max(0.5, float(cfg.get("poll_interval_seconds", 2)))
    headers = {}
    if cfg.get("api_token"):
        headers["Authorization"] = f"Bearer {cfg['api_token']}"
    session = requests.Session()

    print(f"[*] Sky Watch MSFS bridge → {url} (every {interval}s)")
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

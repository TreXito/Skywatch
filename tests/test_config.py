import textwrap

from backend.config import load_config, Settings, save_overrides


def test_defaults_with_only_location(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("latitude: 48.3\nlongitude: 14.2\n", encoding="utf-8")
    s = load_config(cfg)
    assert s.latitude == 48.3
    assert s.longitude == 14.2
    assert s.port == 8080
    assert s.radius_km == 50.0
    assert s.is_configured
    # No credentials → anonymous → 10s poll interval.
    assert s.effective_poll_interval == 10.0
    assert s.effective_auth_mode == "none"


def test_missing_file_is_unconfigured(tmp_path):
    s = load_config(tmp_path / "nope.yaml")
    assert not s.is_configured
    assert s.latitude == 0.0


def test_auth_enabled_by_password():
    s = Settings(latitude=1, longitude=1, password="secret")
    assert s.effective_auth_mode == "basic"


def test_token_auth_takes_priority():
    s = Settings(latitude=1, longitude=1, password="x", api_token="tok")
    assert s.effective_auth_mode == "token"


def test_authenticated_poll_interval():
    s = Settings(latitude=1, longitude=1,
                 opensky_username="u", opensky_password="p")
    assert s.has_opensky_auth
    assert s.effective_poll_interval == 5.0


def test_watchlist_normalized(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        latitude: 1
        longitude: 1
        watchlist:
          - icao24: "AABBCC"
            label: "Test"
          - icao24: "ddeeff"
    """), encoding="utf-8")
    s = load_config(cfg)
    assert s.watchlist[0].icao24 == "aabbcc"
    assert s.watchlist[0].label == "Test"
    assert s.watchlist[1].label == "Watchlist aircraft"


def test_webhook_routing():
    s = Settings(latitude=1, longitude=1, discord_webhook="default",
                 discord_webhook_emergency="emer")
    assert s.webhook_for("emergency") == "emer"
    assert s.webhook_for("military") == "default"


def test_highlight_webhook_routing():
    s = Settings(latitude=1, longitude=1, discord_webhook="d",
                 discord_webhook_highlights="hl")
    assert s.webhook_for("highlight") == "hl"
    s2 = Settings(latitude=1, longitude=1, discord_webhook="d")
    assert s2.webhook_for("highlight") == "d"  # falls back


def test_settings_overrides_merge(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"latitude: 1\nlongitude: 2\ndata_dir: {tmp_path.as_posix()}\n",
                   encoding="utf-8")
    # Before overrides: defaults.
    assert load_config(cfg).map_style == "dark-en"
    save_overrides({"map_style": "german", "max_aircraft": 1234}, cfg)
    s = load_config(cfg)
    assert s.map_style == "german"
    assert s.max_aircraft == 1234
    # Original config.yaml is untouched (no map_style written into it).
    assert "map_style" not in cfg.read_text(encoding="utf-8")

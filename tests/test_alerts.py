import time

from backend.config import Settings, WatchlistEntry
from backend.alerts import AlertEngine
from backend.models import Aircraft
from backend import constants


def make_engine(**overrides):
    settings = Settings(latitude=48.3, longitude=14.2, **overrides)
    # db is only used by async cooldown path; sync detectors don't touch it.
    return AlertEngine(settings, db=None)


def test_emergency_squawk_detection():
    eng = make_engine()
    ac = Aircraft(icao24="abc", squawk="7700", latitude=48.3, longitude=14.2)
    alerts = eng._classify(ac, time.time())
    types = {a.alert_type for a in alerts}
    assert "emergency" in types
    assert ac.marker_category == constants.CATEGORY_EMERGENCY


def test_all_emergency_codes():
    eng = make_engine()
    for code in ("7500", "7600", "7700"):
        ac = Aircraft(icao24="x", squawk=code)
        assert any(a.alert_type == "emergency" for a in eng._classify(ac, 0))


def test_non_emergency_squawk():
    eng = make_engine()
    ac = Aircraft(icao24="x", squawk="1000")
    assert not any(a.alert_type == "emergency" for a in eng._classify(ac, 0))


def test_military_typecode():
    eng = make_engine()
    ac = Aircraft(icao24="x", typecode="C130")
    assert eng._is_military(ac)


def test_military_keyword_in_operator():
    eng = make_engine()
    ac = Aircraft(icao24="x", operator="United States Air Force")
    assert eng._is_military(ac)


def test_military_callsign_prefix():
    eng = make_engine()
    ac = Aircraft(icao24="x", callsign="RCH123")
    assert eng._is_military(ac)


def test_civilian_not_military():
    eng = make_engine()
    ac = Aircraft(icao24="x", typecode="B738", operator="Ryanair", callsign="RYR9UD")
    assert not eng._is_military(ac)


def test_rare_typecode():
    eng = make_engine()
    ac = Aircraft(icao24="x", typecode="A124")
    assert eng._rare_label(ac) == "Antonov An-124 Ruslan"


def test_watchlist_match():
    eng = make_engine(watchlist=[WatchlistEntry(icao24="abc123", label="My Plane")])
    ac = Aircraft(icao24="abc123")
    alerts = eng._classify(ac, 0)
    assert any(a.alert_type == "watchlist" and a.label == "My Plane" for a in alerts)


def test_user_extended_military_typecode():
    eng = make_engine(military_typecodes=["ZZZZ"])
    assert eng._is_military(Aircraft(icao24="x", typecode="ZZZZ"))


def test_holding_pattern_detection():
    eng = make_engine(holding_min_loops=1, holding_min_duration_s=60,
                      holding_max_radius_km=20)
    now = time.time()
    # Simulate a circle: heading sweeps 0..360 over points in a tight area.
    for i in range(0, 13):
        track = (i * 30) % 360
        ac = Aircraft(icao24="loop1", latitude=48.30 + 0.001,
                      longitude=14.20 + 0.001, true_track=track)
        # Backdate timestamps so duration is satisfied.
        eng._track(ac, now - (12 - i) * 10)
    ac = Aircraft(icao24="loop1", latitude=48.30, longitude=14.20, true_track=0)
    assert eng._is_holding(ac)


def test_no_holding_for_straight_flight():
    eng = make_engine(holding_min_loops=2)
    now = time.time()
    for i in range(10):
        ac = Aircraft(icao24="str8", latitude=48.0 + i * 0.1,
                      longitude=14.0, true_track=0)
        eng._track(ac, now - (10 - i))
    assert not eng._is_holding(Aircraft(icao24="str8", latitude=49.0,
                                        longitude=14.0, true_track=0))

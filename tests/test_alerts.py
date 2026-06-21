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
    assert "An-124" in eng._rare_label(ac)


def test_common_widebody_not_rare():
    # The 747-400 / 757 / 767 / A330 are everyday types – must NOT be flagged rare.
    eng = make_engine()
    for tc in ("B744", "B752", "B763", "A332", "A343"):
        assert eng._rare_label(Aircraft(icao24="x", typecode=tc)) is None, tc


def test_genuinely_rare_still_flagged():
    eng = make_engine()
    for tc in ("A388", "B748", "CONC", "IL76", "MD11"):
        assert eng._rare_label(Aircraft(icao24="x", typecode=tc)), tc


def test_special_typecode_label():
    eng = make_engine()
    assert "Superfortress" in (eng.special_label(Aircraft(icao24="x", typecode="B29")) or "")
    assert eng.is_special(Aircraft(icao24="x", typecode="B29"))
    assert "Lancaster" in (eng._rare_label(Aircraft(icao24="x", typecode="LANC")) or "")


def test_ping_only_for_brutal_aircraft():
    eng = make_engine()
    assert eng.is_ping_worthy(Aircraft(icao24="x", typecode="E4"))      # Doomsday
    assert eng.is_ping_worthy(Aircraft(icao24="x", typecode="A124"))    # An-124
    assert eng.is_ping_worthy(Aircraft(icao24="x", callsign="NIGHTWATCH01"))
    # A DC-3 / common warbird is special but NOT ping-worthy.
    assert not eng.is_ping_worthy(Aircraft(icao24="x", typecode="DC3"))
    assert not eng.is_ping_worthy(Aircraft(icao24="x", typecode="L39"))
    assert eng.is_special(Aircraft(icao24="x", typecode="DC3"))         # still special


def test_special_callsign_label():
    eng = make_engine()
    assert "VIP" in (eng.special_label(Aircraft(icao24="x", callsign="SPAR19")) or "")
    assert "Nightwatch" in (eng.special_label(Aircraft(icao24="x", callsign="NIGHTWATCH01")) or "")


def test_alert_once_per_appearance():
    import asyncio, time
    eng = make_engine(alert_reappear_minutes=10)
    ac = Aircraft(icao24="abcd", typecode="C130", latitude=48, longitude=14, true_track=0)
    first = asyncio.run(eng.evaluate([ac]))
    second = asyncio.run(eng.evaluate([ac]))
    assert any(a.alert_type == "military" for a in first)
    assert second == []                      # still present → no repeat
    # Simulate it disappearing for a while, then re-entering → re-arms.
    eng._present[ac.icao24] = time.time() - 999
    third = asyncio.run(eng.evaluate([ac]))
    assert any(a.alert_type == "military" for a in third)


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

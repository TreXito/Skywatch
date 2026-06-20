from backend.config import Settings
from backend.routes import RouteService


def test_airport_mapping():
    node = {
        "iata_code": "LHR", "icao_code": "EGLL", "name": "Heathrow",
        "municipality": "London", "country_name": "United Kingdom",
        "latitude": 51.47, "longitude": -0.46,
    }
    ap = RouteService._airport(node)
    assert ap["iata"] == "LHR"
    assert ap["icao"] == "EGLL"
    assert ap["city"] == "London"
    assert ap["lat"] == 51.47 and ap["lon"] == -0.46


def test_airport_none():
    assert RouteService._airport(None) is None
    assert RouteService._airport({}) is None  # empty/missing node → None


def test_tracking_defaults():
    s = Settings(latitude=48, longitude=14)
    assert s.tracking_mode == "viewport"
    assert s.max_aircraft == 800
    assert s.routes_enabled is True
    assert s.map_style == "dark-en"
    assert s.discord_photos is True


def test_resolved_watch_regions_gazetteer():
    s = Settings(latitude=48, longitude=14,
                 watch_regions=[{"name": "Ukraine"}])
    regions = s.resolved_watch_regions()
    assert len(regions) == 1
    assert regions[0]["name"] == "Ukraine"
    assert regions[0]["lat"] != 0 and regions[0]["radius_km"] > 0
    assert "entered Ukraine" in regions[0]["label"]


def test_resolved_watch_regions_explicit_and_invalid():
    s = Settings(latitude=48, longitude=14, watch_regions=[
        {"name": "Custom", "lat": 50.0, "lon": 30.0, "radius_km": 120},
        {"name": "Nowhere"},  # not in gazetteer, no coords → dropped
    ])
    regions = s.resolved_watch_regions()
    assert len(regions) == 1
    assert regions[0]["lat"] == 50.0 and regions[0]["radius_km"] == 120.0

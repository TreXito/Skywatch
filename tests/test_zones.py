from backend.config import Settings
from backend.zones import ZoneService, _parse_feed


RSS_SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test News</title>
  <item><title>Missile strike reported near Kyiv overnight</title>
        <link>https://news.example/1</link></item>
  <item><title>Stock markets rally on earnings</title>
        <link>https://news.example/2</link></item>
  <item><title>Airstrike hits Gaza as ceasefire talks stall</title>
        <link>https://news.example/3</link></item>
</channel></rss>"""

ATOM_SAMPLE = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom News</title>
  <entry><title>Drone strike on border region</title>
         <link href="https://a.example/x"/></entry>
</feed>"""


def make_service(**ov):
    return ZoneService(Settings(latitude=48, longitude=14, **ov))


def test_parse_rss():
    items = _parse_feed(RSS_SAMPLE)
    assert len(items) == 3
    assert items[0]["title"].startswith("Missile strike")
    assert items[0]["link"] == "https://news.example/1"
    assert items[0]["source"] == "Test News"


def test_parse_atom_link_href():
    items = _parse_feed(ATOM_SAMPLE)
    assert len(items) == 1
    assert items[0]["link"] == "https://a.example/x"


def test_parse_garbage_returns_empty():
    assert _parse_feed("not xml at all <<<") == []


def test_match_region_alias():
    svc = make_service()
    assert svc._match_region("missile strike near kyiv overnight")[0] == "Ukraine"
    assert svc._match_region("airstrike hits gaza")[0] == "Gaza"
    assert svc._match_region("a quiet day in the park") is None


def test_aggregate_filters_non_conflict_and_geocodes():
    svc = make_service(zones_min_mentions=1)
    items = _parse_feed(RSS_SAMPLE)
    zones = svc._aggregate(items)
    names = {z["name"] for z in zones}
    # Kyiv->Ukraine and Gaza match; the stock-market headline is dropped.
    assert "Ukraine" in names
    assert "Gaza" in names
    assert all(z["mentions"] >= 1 for z in zones)
    for z in zones:
        assert "lat" in z and "lon" in z and "severity" in z


def test_min_mentions_threshold():
    svc = make_service(zones_min_mentions=2)
    zones = svc._aggregate(_parse_feed(RSS_SAMPLE))
    # Each region only has one mention → filtered out.
    assert zones == []


def test_static_zones_included():
    svc = make_service(conflict_zones=[
        {"name": "Test Range", "lat": 48.5, "lon": 14.5, "radius_km": 20, "note": "MOA"}
    ])
    zones = svc._static_zones()
    assert len(zones) == 1
    assert zones[0]["static"] is True
    assert zones[0]["name"] == "Test Range"

import math

from backend.utils import haversine_km, bounding_box, zoom_for_radius, cross_track_km
from backend.models import Aircraft


def test_cross_track_on_path_is_small():
    # Point on the great circle between (0,0) and (0,20) is ~0 off-track.
    assert cross_track_km(0.0, 10.0, 0.0, 0.0, 0.0, 20.0) < 1.0


def test_cross_track_off_path_is_large():
    # An aircraft far from the corridor (the wrong-route case) is far off-track.
    d = cross_track_km(48.0, 14.0, 1.35, 103.99, 22.31, 113.91)  # SIN->HKG line
    assert d > 2000


def test_haversine_known_distance():
    # Linz to Vienna is ~155 km.
    d = haversine_km(48.3064, 14.2858, 48.2082, 16.3738)
    assert 150 < d < 165


def test_haversine_zero():
    assert haversine_km(48.0, 14.0, 48.0, 14.0) == 0.0


def test_bounding_box_contains_center():
    lat, lon = 48.3, 14.2
    lat_min, lat_max, lon_min, lon_max = bounding_box(lat, lon, 50)
    assert lat_min < lat < lat_max
    assert lon_min < lon < lon_max
    # Box should be larger than the raw radius (has margin).
    assert (lat_max - lat) * 111 > 50


def test_zoom_decreases_with_radius():
    assert zoom_for_radius(10) > zoom_for_radius(100)
    assert zoom_for_radius(50) == 9


def test_state_vector_parsing():
    sv = ["abc123", "DLH123 ", "Germany", 1700000000, 1700000000,
          14.2, 48.3, 11000.0, False, 250.0, 90.0, 0.0, None, 11200.0,
          "1000", False, 0, 4]
    ac = Aircraft.from_state_vector(sv)
    assert ac.icao24 == "abc123"
    assert ac.callsign == "DLH123"
    assert ac.latitude == 48.3
    assert ac.category == 4
    assert ac.squawk == "1000"

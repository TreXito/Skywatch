import asyncio

from backend.database import Database
from backend.models import Aircraft


def _ac(icao, lat=48.0, lon=14.0, alt=10000.0, vel=200.0, cs="AUA1", tc="A320"):
    return Aircraft(icao24=icao, latitude=lat, longitude=lon, callsign=cs,
                    typecode=tc, baro_altitude=alt, velocity=vel)


def test_update_flights_sessions_and_archive(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        # Two aircraft seen across several scans → one flight each, points grow.
        for _ in range(3):
            await db.update_flights([_ac("aaa111"), _ac("bbb222")])
        flights = await db.recent_flights_all(limit=10)
        counts = await db.archive_counts()
        await db.close()
        return flights, counts

    flights, counts = asyncio.run(run())
    assert len(flights) == 2                     # one session per aircraft
    assert all(f["points"] == 3 for f in flights)
    assert counts["flights"] == 2
    assert counts["aircraft"] == 2


def test_new_flight_after_gap(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        await db.update_flights([_ac("aaa111")], gap_s=1)
        # Force the session to look stale, then a re-sighting starts a new flight.
        db._sessions["aaa111"]["end_ts"] -= 10
        await db.update_flights([_ac("aaa111")], gap_s=1)
        flights = await db.recent_flights_all(limit=10, min_points=1)
        await db.close()
        return flights

    flights = asyncio.run(run())
    assert len(flights) == 2                      # the gap split it into two flights


def test_search_filter(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        await db.update_flights([_ac("aaa111", cs="DLH9", tc="B748"),
                                 _ac("bbb222", cs="AUA1", tc="A320")])
        hits = await db.recent_flights_all(limit=10, search="b748", min_points=1)
        await db.close()
        return hits

    hits = asyncio.run(run())
    assert len(hits) == 1
    assert hits[0]["typecode"] == "B748"


def test_records_upsert(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        beat1 = await db.update_record("fastest:alltime", 250.0, "2026-06-23",
                                       {"icao24": "aaa", "label": "AUA1 · A320"})
        beat2 = await db.update_record("fastest:alltime", 200.0, "2026-06-23",
                                       {"icao24": "bbb", "label": "slow"})
        beat3 = await db.update_record("fastest:alltime", 300.0, "2026-06-23",
                                       {"icao24": "ccc", "label": "fast"})
        recs = await db.get_records()
        await db.close()
        return beat1, beat2, beat3, recs

    beat1, beat2, beat3, recs = asyncio.run(run())
    assert beat1 and not beat2 and beat3          # only strictly-faster values win
    assert recs["fastest:alltime"]["value"] == 300.0
    assert recs["fastest:alltime"]["label"] == "fast"

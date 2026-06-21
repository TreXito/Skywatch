import asyncio

from backend.database import Database
from backend.msfs import MsfsLogger
from backend.models import MsfsPosition


def test_msfs_flight_logged_on_takeoff_and_landing(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        log = MsfsLogger(db)
        t = 1000.0
        # On the ground, stationary → no flight yet.
        await log.update(MsfsPosition(latitude=48, longitude=14, true_airspeed_kts=0,
                                      on_ground=True, server_time=t))
        # Take off + climb out.
        for i in range(22):
            t += 3
            await log.update(MsfsPosition(latitude=48 + i * 0.01, longitude=14,
                                          altitude_ft=1000 + i * 200, true_airspeed_kts=140,
                                          on_ground=False, server_time=t))
        # Land + slow down, sustained > landing-confirm window.
        for _ in range(8):
            t += 5
            await log.update(MsfsPosition(latitude=49, longitude=14, true_airspeed_kts=0,
                                          on_ground=True, server_time=t))
        flights = await db.recent_msfs_flights()
        track = await db.msfs_flight_track(flights[0]["id"]) if flights else None
        await db.close()
        return flights, track

    flights, track = asyncio.run(run())
    assert len(flights) == 1
    assert flights[0]["points"] >= 2
    assert track and '"LineString"' in track


def test_taxi_blip_not_logged(tmp_path):
    async def run():
        db = Database(tmp_path / "t.db")
        await db.connect()
        log = MsfsLogger(db)
        t = 0.0
        # Briefly above airborne speed but only for a few seconds → ignored.
        for _ in range(3):
            t += 3
            await log.update(MsfsPosition(latitude=48, longitude=14,
                                          true_airspeed_kts=60, on_ground=False, server_time=t))
        for _ in range(6):
            t += 5
            await log.update(MsfsPosition(latitude=48, longitude=14,
                                          true_airspeed_kts=0, on_ground=True, server_time=t))
        flights = await db.recent_msfs_flights()
        await db.close()
        return flights

    assert asyncio.run(run()) == []

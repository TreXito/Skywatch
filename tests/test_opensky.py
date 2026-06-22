from backend.opensky import OpenSkyClient
from backend.config import Settings


def test_credit_estimation_by_area():
    est = OpenSkyClient._estimate_credits
    assert est(None) == 4                       # whole world
    assert est((48.0, 49.0, 14.0, 15.0)) == 1   # 1 deg^2 -> small
    assert est((40.0, 46.0, 10.0, 16.0)) == 2   # 36 deg^2
    assert est((30.0, 45.0, 0.0, 15.0)) == 3    # 225 deg^2
    assert est((20.0, 45.0, 0.0, 25.0)) == 4    # 625 deg^2 -> large


def test_default_credit_budget():
    s = Settings(latitude=48, longitude=14)
    assert s.daily_credit_budget == 4000


def test_credit_pacing_caps_usage():
    s = Settings(latitude=1, longitude=1, daily_credit_budget=4000)
    c = OpenSkyClient(s)
    # Fresh bucket allows a global (4-credit) call.
    assert c._over_budget(True, None) is False
    # Drain the bucket fast (time barely advances) → further calls are paced off.
    for _ in range(300):
        c._account(None)
    assert c._over_budget(True, None) is True
    # Interactive is throttled at least as hard as background.
    assert c._over_budget(False, None) is True

"""Shared setup. Every test runs without a Gemini key and uses no quota.

    pip install -r requirements-dev.txt
    pytest

What is where:
- test_core.py         cities, truck types, trip costs, fair prices, matching (pure Python)
- test_marketplace.py  the website's API end to end: accounts, loads, vehicles, offers, booking, permissions
- test_ai_tools.py     the AI's tools: drafts only, the guards (date, price, weight), each user sees only their own
- test_engine.py       the Gemini loop with a fake Gemini: time limits, offline answers
- test_paperwork.py    the paperwork agent's Python checks against the answer keys (carried over from logimind-ai)
- test_server.py       health, demo documents, a demo document checked end to end with no Gemini call

Each test gets its own empty database (the `fresh_db` fixture is on for every test).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for folder in (ROOT, ROOT / "evals"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    import db
    import marketplace
    monkeypatch.setenv("KARGONAUT_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("KARGONAUT_DEMO_SEED", "0")
    db.init_db()
    marketplace.DRAFTS.clear()
    yield


@pytest.fixture
def people():
    """A shipper in Tbilisi and a driver with a Dry van in Tbilisi, plus an open load Tbilisi -> Batumi."""
    from datetime import date, timedelta

    import marketplace as mp
    shipper = mp.register("shipper", "ნინო", "555000001", "password1", "Tbilisi", "entrepreneur",
                          business={"id_code": "00000000001", "legal_address": "თბილისი, საცდელი ქ. 1"})
    other = mp.register("shipper", "გიორგი", "555000002", "password1", "Kutaisi")
    driver = mp.register("driver", "ლევანი", "555000003", "password1", "Tbilisi",
                         vehicle={"truck_type": "dry_van", "capacity_kg": 18000, "city": "Tbilisi", "plate": "TB-100-AA"})
    vehicle = mp.vehicles_of(driver["id"])[0]
    load = mp.create_load(shipper["id"], {"origin_city": "Tbilisi", "destination_city": "Batumi",
                                          "truck_type": "dry_van", "weight_kg": 12000, "price_gel": 960,
                                          "pickup_date": (date.today() + timedelta(days=2)).isoformat()})
    full = {u["id"]: mp.get_user(u["id"]) for u in (shipper, other, driver)}
    return {"shipper": full[shipper["id"]], "other": full[other["id"]], "driver": full[driver["id"]],
            "vehicle": vehicle, "load": load}

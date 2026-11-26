"""A load with a delivery deadline (deliver_by): Python checks each offer's truck against the trips it's already
booked for, and recommends the cheapest driver who can make it, not simply the cheapest (core/matching.py)."""
from datetime import date, timedelta

from core.matching import DRIVING_HOURS_PER_DAY, deadline_check
from test_marketplace import client_for, truck

DAY = (date.today() + timedelta(days=2)).isoformat()


def test_no_deadline_no_check():
    load = {"id": 1, "origin_city": "Tbilisi", "destination_city": "Poti", "pickup_date": DAY, "deliver_by": None}
    assert deadline_check(load, "Rustavi", []) is None


def test_a_truck_already_booked_that_day_cant_also_make_a_same_day_delivery():
    load = {"id": 2, "origin_city": "Tbilisi", "destination_city": "Poti", "pickup_date": DAY, "deliver_by": DAY}
    free = deadline_check(load, "Rustavi", [])
    busy = deadline_check(load, "Zestafoni", [{"id": 9, "origin_city": "Zestafoni", "destination_city": "Batumi",
                                                "pickup_date": DAY}])
    assert free["on_time"] and free["hours_needed"] <= DRIVING_HOURS_PER_DAY
    assert not busy["on_time"] and busy["busy_with"][0]["load_id"] == 9 and busy["hours_needed"] > free["hours_needed"]
    two_days = deadline_check({**load, "deliver_by": (date.fromisoformat(DAY) + timedelta(days=1)).isoformat()},
                              "Zestafoni", [{"id": 9, "origin_city": "Zestafoni", "destination_city": "Batumi",
                                             "pickup_date": DAY}])
    assert two_days["on_time"] and two_days["hours_available"] == 2 * DRIVING_HOURS_PER_DAY   # a day more: fits


def test_the_cheaper_offer_that_cant_make_the_deadline_is_not_recommended():
    shipper = client_for("shipper", "555000001")
    cheap = client_for("driver", "555000002", "იაფი", vehicle=truck(city="Zestafoni", plate="ZS-100-AA"))
    on_time = client_for("driver", "555000003", "დროული", vehicle=truck(city="Rustavi", plate="RS-100-AA"))
    other = client_for("shipper", "555000004")
    body = {"origin_city": "Zestafoni", "destination_city": "Batumi", "truck_type": "dry_van", "weight_kg": 8000,
            "pickup_date": DAY, "price_gel": 450}
    clash = other.post("/api/loads", json=body).json()                         # the cheap driver's other trip
    offer = cheap.post(f"/api/loads/{clash['id']}/offers", json={}).json()
    assert other.post(f"/api/offers/{offer['id']}/accept", json={}).status_code == 200

    load = shipper.post("/api/loads", json={**body, "origin_city": "Tbilisi", "destination_city": "Poti",
                                           "price_gel": 870, "deliver_by": DAY}).json()
    assert load["deliver_by"] == DAY
    cheap.post(f"/api/loads/{load['id']}/offers", json={"price_gel": 800})
    on_time.post(f"/api/loads/{load['id']}/offers", json={"price_gel": 900})
    r = shipper.get(f"/api/loads/{load['id']}/offers").json()
    first, second = r["offers"]
    assert first["driver_name"] == "დროული" and r["recommended_offer_id"] == first["id"]     # 900 ₾, on time
    assert second["price_gel"] == 800 and second["deadline"]["on_time"] is False
    assert second["deadline"]["busy_with"][0]["load_id"] == clash["id"]


def test_a_deadline_before_the_pickup_is_refused():
    shipper = client_for("shipper", "555000001")
    r = shipper.post("/api/loads", json={"origin_city": "Tbilisi", "destination_city": "Poti", "truck_type": "dry_van",
                                         "weight_kg": 8000, "pickup_date": DAY, "price_gel": 870,
                                         "deliver_by": date.today().isoformat()})
    assert r.status_code == 400 and "ვადა" in r.json()["detail"]

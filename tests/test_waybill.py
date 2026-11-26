"""„ავიღე ტვირთი“ with the goods waybill (სასაქონლო ზედნადები): the paperwork agent reads it, Python compares it with
the booked load (truck plate, cities, weight). Uses the simulated demo waybill, whose reading ships with the app, so
no Gemini call is made (demo_documents/ge/ge-07, generate_demo_waybill.py)."""
from datetime import date, timedelta

import marketplace as mp
from conftest import ROOT
from test_marketplace import client_for, truck

WAYBILL = ROOT / "demo_documents" / "ge" / "ge-07" / "waybill.pdf"   # Gori -> Rustavi, 900 kg, truck DM-001-KG
DAY = (date.today() + timedelta(days=1)).isoformat()


def booked(plate="DM-001-KG", origin="Gori", destination="Rustavi", weight=900):
    """A shipper's load booked on a driver's truck; returns (shipper, driver, load id)."""
    shipper = client_for("shipper", "555000001")
    driver = client_for("driver", "555000002", vehicle=truck(city="Gori", plate=plate))
    load = shipper.post("/api/loads", json={"origin_city": origin, "destination_city": destination, "truck_type": "dry_van",
                                           "weight_kg": weight, "pickup_date": DAY, "price_gel": 310}).json()
    offer = driver.post(f"/api/loads/{load['id']}/offers", json={}).json()
    assert shipper.post(f"/api/offers/{offer['id']}/accept", json={}).status_code == 200
    return shipper, driver, load["id"]


def pick_up(driver, load_id, path=WAYBILL):
    return driver.post(f"/api/jobs/{load_id}/pickup", files={"file": (path.name, path.read_bytes(), "application/pdf")})


def test_the_right_waybill_matches_the_load_and_both_sides_see_it():
    shipper, driver, load_id = booked()
    r = pick_up(driver, load_id)
    assert r.status_code == 200, r.text
    w = r.json()["waybill"]
    assert r.json()["status"] == "in_transit" and w["problems"] == []
    assert w["plate"] == "DM-001-KG" and w["number"] == "0412378915"            # DM001KG on the paper
    seen = next(x for x in shipper.get("/api/loads/mine").json() if x["id"] == load_id)
    assert seen["waybill"]["file_name"] == "waybill.pdf"                         # the shipper sees it too
    assert shipper.get(f"/api/loads/{load_id}/waybill/file").status_code == 200
    stranger = client_for("shipper", "555000009")
    assert stranger.get(f"/api/loads/{load_id}/waybill/file").status_code == 404


def test_a_waybill_for_another_truck_is_flagged_but_doesnt_block_the_pickup():
    _, driver, load_id = booked(plate="TB-100-AA")
    r = pick_up(driver, load_id).json()
    assert r["status"] == "in_transit"
    assert [p["check"] for p in r["waybill"]["problems"]] == ["waybill_plate_mismatch"]


def test_a_waybill_for_another_route_or_weight_is_flagged():
    _, driver, load_id = booked(origin="Tbilisi", destination="Batumi", weight=5000)
    checks = {p["check"] for p in pick_up(driver, load_id).json()["waybill"]["problems"]}
    assert checks == {"waybill_pickup_city_mismatch", "waybill_delivery_city_mismatch", "waybill_weight_mismatch"}


def test_no_waybill_issued_is_allowed_and_said():
    _, driver, load_id = booked()
    r = driver.post(f"/api/jobs/{load_id}/pickup", data={"none_issued": "true"})
    assert r.status_code == 200 and r.json()["waybill"]["none_issued"] is True


def test_pickup_needs_the_waybill_or_the_none_issued_box():
    _, driver, load_id = booked()
    r = driver.post(f"/api/jobs/{load_id}/pickup")
    assert r.status_code == 400 and "ზედნადებ" in r.json()["detail"]
    assert mp.get_load(load_id)["status"] == "booked"


def test_only_the_booked_driver_picks_up_once():
    _, driver, load_id = booked()
    other = client_for("driver", "555000003", vehicle=truck(plate="RS-300-AA"))
    assert pick_up(other, load_id).status_code == 400
    assert pick_up(driver, load_id).status_code == 200
    assert pick_up(driver, load_id).status_code == 400                           # already on the road

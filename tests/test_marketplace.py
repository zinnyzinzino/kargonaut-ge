"""The website's API end to end, as a browser would use it (cookies included)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

import server

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def client_for(role, phone, name="ტესტი", city="Tbilisi"):
    c = TestClient(server.app)
    r = c.post("/api/register", json={"role": role, "name": name, "phone": phone, "password": "password1",
                                      "city": city, "legal_status": "entrepreneur"})
    assert r.status_code == 200, r.text
    return c


def load_body(**change):
    return {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van", "weight_kg": 12000,
            "pickup_date": TOMORROW, "price_gel": 960, "cargo": "ავეჯი", **change}


def test_registration_rules():
    c = TestClient(server.app)
    ok = {"role": "shipper", "name": "ნინო", "phone": "+995 555 12 34 56", "password": "password1"}
    assert c.post("/api/register", json=ok).json()["phone"] == "555123456"
    assert c.post("/api/register", json=ok).status_code == 400                     # the number is taken
    assert c.post("/api/register", json={**ok, "phone": "123"}).status_code == 400  # not a Georgian mobile
    assert c.post("/api/register", json={**ok, "phone": "555000999", "password": "short"}).status_code == 400
    assert c.post("/api/login", json={"phone": "555123456", "password": "wrong-one"}).status_code == 401
    assert c.post("/api/login", json={"phone": "555 12 34 56", "password": "password1"}).status_code == 200


def test_not_signed_in():
    assert TestClient(server.app).get("/api/loads/mine").status_code == 401


def test_the_whole_deal():
    shipper = client_for("shipper", "555000001", "ნინო")
    driver = client_for("driver", "555000002", "ლევანი")

    load = shipper.post("/api/loads", json=load_body()).json()
    assert load["status"] == "open" and load["origin_label"] == "თბილისი"

    # no vehicle yet: the driver is told to add one
    assert driver.get("/api/loads/open").status_code == 400
    v = driver.post("/api/vehicles", json={"truck_type": "Dry van", "capacity_kg": 18000, "city": "Gori"}).json()
    found = driver.get("/api/loads/open").json()
    row = found["loads"][0]
    assert row["load"]["id"] == load["id"] and row["earnings"]["empty_km"] == 85.8
    assert row["earnings"]["driver_keeps_gel"] == 960 - row["earnings"]["trip_costs_gel"]
    assert "shipper" not in row["load"]                              # no contacts before a booking

    offer = driver.post(f"/api/loads/{load['id']}/offers", json={"price_gel": 920, "message": "ხვალ შემიძლია"}).json()
    offers = shipper.get(f"/api/loads/{load['id']}/offers").json()
    assert offers["recommended_offer_id"] == offer["id"] and offers["offers"][0]["price_gel"] == 920

    booked = shipper.post(f"/api/offers/{offer['id']}/accept").json()
    assert booked["status"] == "booked" and booked["agreed_price_gel"] == 920
    assert booked["driver"]["phone"] == "555000002"                  # contacts shared after the booking
    job = driver.get("/api/jobs").json()["jobs"][0]
    assert job["shipper"]["phone"] == "555000001"

    assert driver.post(f"/api/jobs/{load['id']}/advance").json()["status"] == "in_transit"
    assert driver.post(f"/api/jobs/{load['id']}/advance").json()["status"] == "delivered"
    assert driver.get("/api/vehicles/mine").json()[0]["city"] == "Batumi"   # the truck is where it delivered
    assert v["id"] == job["vehicle_id"]


def test_each_side_can_only_do_its_own_things():
    shipper = client_for("shipper", "555000001")
    other = client_for("shipper", "555000003")
    driver = client_for("driver", "555000002")
    driver.post("/api/vehicles", json={"truck_type": "dry_van", "capacity_kg": 18000, "city": "Tbilisi"})
    load = shipper.post("/api/loads", json=load_body()).json()
    offer = driver.post(f"/api/loads/{load['id']}/offers", json={}).json()
    assert offer["price_gel"] == 960                                  # no price: the shipper's own

    assert driver.post("/api/loads", json=load_body()).status_code == 403     # drivers don't post loads
    assert shipper.post("/api/vehicles", json={}).status_code == 403          # shippers don't add vehicles
    assert other.get(f"/api/loads/{load['id']}/offers").status_code == 404    # not their load
    assert other.post(f"/api/offers/{offer['id']}/accept").status_code == 400
    assert other.post(f"/api/loads/{load['id']}/cancel").status_code == 400
    assert driver.post(f"/api/jobs/{load['id']}/advance").status_code == 400  # not booked yet


def test_a_load_must_make_sense():
    shipper = client_for("shipper", "555000001")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for change in ({"pickup_date": yesterday}, {"destination_city": "Tbilisi"}, {"origin_city": "Moscow"},
                   {"price_gel": 0}, {"truck_type": "helicopter"}, {"pickup_date": "next week"}):
        r = shipper.post("/api/loads", json=load_body(**change))
        assert r.status_code == 400, change
        assert any("ა" <= ch <= "ჿ" for ch in r.json()["detail"])     # the message is Georgian


def test_a_vehicle_that_cannot_carry_it_cannot_offer():
    shipper = client_for("shipper", "555000001")
    driver = client_for("driver", "555000002")
    driver.post("/api/vehicles", json={"truck_type": "sprinter_van", "capacity_kg": 1500, "city": "Tbilisi"})
    load = shipper.post("/api/loads", json=load_body()).json()
    assert driver.get("/api/loads/open").json()["loads"] == []
    assert driver.post(f"/api/loads/{load['id']}/offers", json={}).status_code == 400


def test_public_price_calculator():
    c = TestClient(server.app)
    r = c.get("/api/price?origin=Tbilisi&destination=Batumi&kind=dry_van&weight_kg=12000&price_gel=960").json()
    assert r["verdict"] == "fair" and r["verdict_label"] == "სამართლიანი ფასია"
    assert c.get("/api/price?origin=Tbilisi&destination=Tbilisi").status_code == 400

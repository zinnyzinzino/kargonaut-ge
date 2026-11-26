"""The website's API end to end, as a browser would use it (cookies included)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

import server
from conftest import ROOT

TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def truck(**change):
    return {"truck_type": "dry_van", "capacity_kg": 18000, "city": "Tbilisi", "plate": "TB-100-AA", **change}


def client_for(role, phone, name="ტესტი", city="Tbilisi", vehicle=None):
    """A signed-in browser. A driver registers with a truck (a Dry van in Tbilisi unless `vehicle` says otherwise)."""
    c = TestClient(server.app)
    r = c.post("/api/register", json={"role": role, "name": name, "phone": phone, "password": "password1",
                                      "city": city, "legal_status": "entrepreneur",
                                      "vehicle": (vehicle or truck()) if role == "driver" else {}})
    assert r.status_code == 200, r.text
    return c


DEMO_POD = ROOT / "demo_documents" / "ge" / "ge-06" / "pod.pdf"   # simulated; its reading ships with the app


def deliver(driver, load_id, path=DEMO_POD):
    """„მივიტანე“ with the proof of delivery (no Gemini call: the demo POD's reading is shipped)."""
    return driver.post(f"/api/jobs/{load_id}/deliver", files=[("file", (path.name, path.read_bytes(), "application/pdf"))])


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


def test_a_driver_registers_with_a_truck_or_not_at_all():
    c = TestClient(server.app)
    driver = {"role": "driver", "name": "ლევანი", "phone": "555000002", "password": "password1"}
    no_truck = c.post("/api/register", json=driver)
    assert no_truck.status_code == 400 and "მანქანა" in no_truck.json()["detail"]
    no_plate = c.post("/api/register", json={**driver, "vehicle": truck(plate="")})
    assert no_plate.status_code == 400 and "ნომერი" in no_plate.json()["detail"]
    assert c.post("/api/login", json={"phone": "555000002", "password": "password1"}).status_code == 401  # no account
    ok = c.post("/api/register", json={**driver, "vehicle": truck(plate="tb 100 aa", fuel_l_per_100km=27)})
    assert ok.status_code == 200
    v = c.get("/api/vehicles/mine").json()[0]
    assert v["plate"] == "TB-100-AA" and v["fuel_l_per_100km"] == 27            # the driver's own fuel use is kept
    other = c.post("/api/register", json={**driver, "phone": "555000003", "vehicle": truck()})
    assert other.status_code == 400 and "უკვე" in other.json()["detail"]        # one plate, one truck


def test_a_truck_can_have_its_body_size_and_a_wrong_size_is_refused():
    c = client_for("driver", "555000002", vehicle=truck(length_m=13.6, width_m=2.45))   # no height: optional
    v = c.get("/api/vehicles/mine").json()[0]
    assert (v["length_m"], v["width_m"], v["height_m"]) == (13.6, 2.45, None)
    too_long = c.post("/api/vehicles", json=truck(plate="TB-200-AA", length_m=136))   # centimetres typed as metres
    assert too_long.status_code == 400 and "სიგრძე" in too_long.json()["detail"]


def test_shippers_see_free_trucks_with_the_drivers_phone():
    shipper = client_for("shipper", "555000001")
    driver = client_for("driver", "555000002", "ლევანი", vehicle=truck(length_m=13.6))
    driver.post("/api/vehicles", json=truck(plate="TB-300-AA", city="Batumi"))
    free = shipper.get("/api/vehicles/free").json()
    assert len(free) == 2 and {t["driver_phone"] for t in free} == {"555000002"}
    assert "password_hash" not in free[0] and free[0]["driver_name"] == "ლევანი"
    busy = driver.get("/api/vehicles/mine").json()[0]
    driver.post(f"/api/vehicles/{busy['id']}", json={"available": False})   # the driver marks it taken
    assert [t["id"] for t in shipper.get("/api/vehicles/free").json()] != [busy["id"]]
    assert len(shipper.get("/api/vehicles/free").json()) == 1
    assert driver.get("/api/vehicles/free").status_code == 403              # for shippers only


def test_not_signed_in():
    assert TestClient(server.app).get("/api/loads/mine").status_code == 401


def test_the_whole_deal():
    shipper = client_for("shipper", "555000001", "ნინო")
    driver = client_for("driver", "555000002", "ლევანი", vehicle=truck(truck_type="Dry van", city="Gori"))
    v = driver.get("/api/vehicles/mine").json()[0]

    load = shipper.post("/api/loads", json=load_body()).json()
    assert load["status"] == "open" and load["origin_label"] == "თბილისი"

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
    assert driver.post(f"/api/jobs/{load['id']}/advance").status_code == 400      # delivered needs the paper
    assert deliver(driver, load["id"]).json()["status"] == "delivered"
    assert driver.get("/api/vehicles/mine").json()[0]["city"] == "Batumi"   # the truck is where it delivered
    assert v["id"] == job["vehicle_id"]


def test_each_side_can_only_do_its_own_things():
    shipper = client_for("shipper", "555000001")
    other = client_for("shipper", "555000003")
    driver = client_for("driver", "555000002")
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
    driver = client_for("driver", "555000002", vehicle=truck(truck_type="sprinter_van", capacity_kg=1500))
    load = shipper.post("/api/loads", json=load_body()).json()
    assert driver.get("/api/loads/open").json()["loads"] == []
    assert driver.post(f"/api/loads/{load['id']}/offers", json={}).status_code == 400


def test_public_price_calculator():
    c = TestClient(server.app)
    r = c.get("/api/price?origin=Tbilisi&destination=Batumi&kind=dry_van&weight_kg=12000&price_gel=960").json()
    assert r["verdict"] == "fair" and r["verdict_label"] == "სამართლიანი ფასია"
    assert c.get("/api/price?origin=Tbilisi&destination=Tbilisi").status_code == 400


def test_ratings_after_delivery_once_per_side():
    shipper = client_for("shipper", "555000001", "ნინო")
    other = client_for("shipper", "555000003")
    driver = client_for("driver", "555000002", "ლევანი")
    load = shipper.post("/api/loads", json=load_body()).json()
    offer = driver.post(f"/api/loads/{load['id']}/offers", json={"price_gel": 900}).json()
    # a driver with no ratings yet is "new": no average
    assert shipper.get(f"/api/loads/{load['id']}/offers").json()["offers"][0]["driver_rating"] == {"average": None, "count": 0}
    shipper.post(f"/api/offers/{offer['id']}/accept")
    assert shipper.post(f"/api/loads/{load['id']}/rate", json={"stars": 5}).status_code == 400   # not delivered yet
    driver.post(f"/api/jobs/{load['id']}/advance")
    deliver(driver, load["id"])                                                                   # delivered

    row = next(l for l in shipper.get("/api/loads/mine").json() if l["id"] == load["id"])
    assert row["can_rate"] is True and row["my_rating"] is None
    assert other.post(f"/api/loads/{load['id']}/rate", json={"stars": 1}).status_code == 400      # not their trip
    assert shipper.post(f"/api/loads/{load['id']}/rate", json={"stars": 6}).status_code == 400    # 1-5 only
    r = shipper.post(f"/api/loads/{load['id']}/rate", json={"stars": 4, "comment": "კარგი მძღოლი"})
    assert r.status_code == 200 and r.json()["rated_user"] == {"average": 4.0, "count": 1}
    assert shipper.post(f"/api/loads/{load['id']}/rate", json={"stars": 5}).status_code == 400    # only once
    assert driver.post(f"/api/loads/{load['id']}/rate", json={"stars": 5}).status_code == 200     # the other side

    row = next(l for l in shipper.get("/api/loads/mine").json() if l["id"] == load["id"])
    assert row["can_rate"] is False and row["my_rating"]["stars"] == 4
    assert row["driver"]["rating"] == {"average": 4.0, "count": 1}
    assert shipper.get("/api/me").json()["rating"] == {"average": 5.0, "count": 1}


def test_delivery_needs_the_signed_paper_and_it_is_checked():
    """The demo POD (Gori -> Rustavi): signed with a scribble and no printed name. Delivered to the right city it shows
    only that problem; on a load that went elsewhere, Python also flags the city."""
    shipper = client_for("shipper", "555000001")
    driver = client_for("driver", "555000002")
    rustavi = shipper.post("/api/loads", json=load_body(destination_city="Rustavi", weight_kg=900)).json()
    batumi = shipper.post("/api/loads", json=load_body()).json()
    for load in (rustavi, batumi):
        offer = driver.post(f"/api/loads/{load['id']}/offers", json={}).json()
        shipper.post(f"/api/offers/{offer['id']}/accept")
    assert deliver(driver, rustavi["id"]).status_code == 400          # not picked up yet
    for load in (rustavi, batumi):
        driver.post(f"/api/jobs/{load['id']}/advance")

    pod = deliver(driver, rustavi["id"]).json()["pod"]
    assert pod["read"] and pod["receiver_signed"] is True and pod["receiver_name"] is None   # a scribble isn't a name
    assert [p["check"] for p in pod["problems"]] == ["pod_receiver_unnamed"]
    wrong = deliver(driver, batumi["id"]).json()["pod"]
    assert "pod_city_mismatch" in [p["check"] for p in wrong["problems"]]

    # both sides see it, and only they can open the photo
    row = next(l for l in shipper.get("/api/loads/mine").json() if l["id"] == rustavi["id"])
    assert row["status"] == "delivered" and row["pod"]["file_name"] == "pod.pdf"
    assert shipper.get(f"/api/loads/{rustavi['id']}/pod/file").status_code == 200
    assert client_for("shipper", "555000009").get(f"/api/loads/{rustavi['id']}/pod/file").status_code == 404


def test_transport_order_pdf_for_both_sides_once_booked():
    """გადაზიდვის შეკვეთა: Georgian freight has no standard rate confirmation, so the site writes the order itself."""
    import io

    from pypdf import PdfReader
    shipper = client_for("shipper", "555000001", "ნინო ბერიძე")
    driver = client_for("driver", "555000002", "ლევან გელაშვილი", vehicle=truck(plate="TB-777-AA"))
    stranger = client_for("shipper", "555000003")
    load = shipper.post("/api/loads", json=load_body()).json()
    assert shipper.get(f"/api/loads/{load['id']}/order.pdf").status_code == 400    # no driver booked yet
    offer = driver.post(f"/api/loads/{load['id']}/offers", json={"price_gel": 905}).json()
    shipper.post(f"/api/offers/{offer['id']}/accept")

    for side in (shipper, driver):
        r = side.get(f"/api/loads/{load['id']}/order.pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    text = PdfReader(io.BytesIO(r.content)).pages[0].extract_text()
    for wanted in ("გადაზიდვის შეკვეთა", f"KG-{load['id']:06d}", "ნინო ბერიძე", "ლევან გელაშვილი", "TB-777-AA", "905",
                   "თბილისი", "ბათუმი"):
        assert wanted in text, wanted
    assert len(PdfReader(io.BytesIO(r.content)).pages) == 1
    assert stranger.get(f"/api/loads/{load['id']}/order.pdf").status_code == 404

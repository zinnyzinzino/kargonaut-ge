"""Registering as a person, an entrepreneur or a company (their registry details go on the transport order), and the
trip's transport order: Kargonaut's PDF or the shipper's own document, read by the paperwork agent and checked by
Python against the booking. The own order uses the simulated demo RC ge-06 (Gori -> Rustavi, 900 kg, 310 GEL), whose
reading ships with the app, so no Gemini call is made."""
import io
from datetime import date, timedelta

from fastapi.testclient import TestClient
from pypdf import PdfReader

import marketplace as mp
import server
from conftest import ROOT
from test_marketplace import client_for, truck

RC = ROOT / "demo_documents" / "ge" / "ge-06" / "rc.pdf"   # simulated: Gori -> Rustavi, 900 kg, 310 GEL
DAY = (date.today() + timedelta(days=1)).isoformat()
IBAN = "GE29NB0000000101904917"   # the standard example IBAN for Georgia (well-formed, check digits right)
COMPANY = {"role": "shipper", "name": "შპს „საცდელი“", "phone": "555000005", "password": "password1",
           "legal_status": "company", "id_code": "400000001", "legal_address": "ქუთაისი, საცდელი ქ. 2",
           "contact_person": "ნინო ბერიძე"}


def test_a_company_registers_with_its_registry_details():
    c = TestClient(server.app)
    for change, word in (({"id_code": ""}, "საიდენტიფიკაციო"), ({"id_code": "12345"}, "9 ციფრი"),
                         ({"legal_address": ""}, "მისამართი"), ({"contact_person": ""}, "საკონტაქტო"),
                         ({"bank_account": "GE29NB0000000101904918"}, "IBAN")):   # one digit off: the check fails
        r = c.post("/api/register", json={**COMPANY, **change})
        assert r.status_code == 400 and word in r.json()["detail"], change
    r = c.post("/api/register", json={**COMPANY, "bank_account": "ge29 nb00 0000 0101 9049 17"})
    assert r.status_code == 200, r.text
    me = c.get("/api/me").json()
    assert (me["id_code"], me["bank_account"], me["contact_person"]) == ("400000001", IBAN, "ნინო ბერიძე")
    assert me["order_preference"] == "kargonaut"
    entrepreneur = c.post("/api/register", json={**COMPANY, "phone": "555000006", "legal_status": "entrepreneur",
                                                 "id_code": "400000001"})
    assert entrepreneur.status_code == 400 and "11 ციფრი" in entrepreneur.json()["detail"]


def test_a_private_person_gives_no_registry_details_and_none_are_kept():
    c = TestClient(server.app)
    r = c.post("/api/register", json={**COMPANY, "legal_status": "person", "id_code": "01001012345"})
    assert r.status_code == 200
    assert c.get("/api/me").json()["id_code"] is None            # a personal number is never stored


def test_the_profile_changes_details_and_the_default_order():
    c = TestClient(server.app)
    c.post("/api/register", json=COMPANY)
    assert c.put("/api/me", json={**COMPANY, "bank_account": "123"}).status_code == 400
    me = c.put("/api/me", json={**COMPANY, "bank_account": IBAN, "order_preference": "own"}).json()
    assert me["bank_account"] == IBAN and me["order_preference"] == "own"


def test_demo_accounts_need_no_registry_details():
    made = mp.register("shipper", "შპს „დემო“", "599000001", "password1", "Gori", "company", is_demo=True)
    assert "error" not in made


def book(order_source=None, price=310, shipper=None):
    """A Gori -> Rustavi load (like the demo RC) booked on a driver's truck; returns (shipper, driver, load id)."""
    shipper = shipper or client_for("shipper", "555000001", "ნინო ბერიძე")
    driver = client_for("driver", "555000002", "ლევან გელაშვილი", vehicle=truck(city="Gori", plate="TB-777-AA"))
    load = shipper.post("/api/loads", json={"origin_city": "Gori", "destination_city": "Rustavi", "truck_type": "dry_van",
                                           "weight_kg": 900, "pickup_date": DAY, "price_gel": price}).json()
    offer = driver.post(f"/api/loads/{load['id']}/offers", json={}).json()
    body = {"order_source": order_source} if order_source else {}
    assert shipper.post(f"/api/offers/{offer['id']}/accept", json=body).status_code == 200
    return shipper, driver, load["id"]


def upload(shipper, load_id, path=RC):
    return shipper.post(f"/api/loads/{load_id}/own-order", files={"file": (path.name, path.read_bytes(), "application/pdf")})


def test_the_transport_order_prints_the_registry_details():
    shipper, _, load_id = book()
    text = PdfReader(io.BytesIO(shipper.get(f"/api/loads/{load_id}/order.pdf").content)).pages[0].extract_text()
    assert "00000000001" in text and "საცდელი" in text and "იურიდიული მისამართი" in text


def test_the_shippers_own_order_is_read_and_checked_against_the_booking():
    shipper, driver, load_id = book("own")
    assert shipper.get(f"/api/loads/{load_id}/order.pdf").status_code == 400   # one agreement: theirs, not ours too
    r = upload(shipper, load_id)
    assert r.status_code == 200, r.text
    o = r.json()["own_order"]
    assert o["problems"] == [] and o["rate"] == 310 and o["number"] == "KF/2026/0388"
    trip = next(j for j in driver.get("/api/jobs").json()["jobs"] if j["id"] == load_id)
    assert trip["own_order"]["file_name"] == "rc.pdf" and trip["order_source"] == "own"   # the driver sees it
    assert driver.get(f"/api/loads/{load_id}/own-order/file").status_code == 200
    assert upload(driver, load_id).status_code == 403                                  # only the shipper uploads
    stranger = client_for("shipper", "555000009")
    assert stranger.get(f"/api/loads/{load_id}/own-order/file").status_code == 404


def test_a_different_price_on_the_own_order_is_a_problem_both_sides_see():
    shipper, driver, load_id = book("own", price=350)                  # agreed 350 ₾, the paper says 310 ₾
    problems = upload(shipper, load_id).json()["own_order"]["problems"]
    assert [p["check"] for p in problems] == ["own_order_price_mismatch"]
    assert "310" in problems[0]["detail"] and "350" in problems[0]["detail"]


def test_the_default_order_comes_from_the_profile_and_can_be_switched():
    shipper = client_for("shipper", "555000001")
    shipper.put("/api/me", json={"id_code": "00000000001", "legal_address": "თბილისი", "order_preference": "own"})
    shipper, _, load_id = book(shipper=shipper)                          # no choice sent: the profile's default
    mine = next(x for x in shipper.get("/api/loads/mine").json() if x["id"] == load_id)
    assert mine["order_source"] == "own" and mine["own_order"] is None
    assert shipper.post(f"/api/loads/{load_id}/order-source", json={"order_source": "kargonaut"}).status_code == 200
    assert shipper.get(f"/api/loads/{load_id}/order.pdf").status_code == 200
    assert upload(shipper, load_id).status_code == 400                   # Kargonaut's order now: nothing to upload


def carrier(**change):
    return {"role": "driver", "name": "შპს „საცდელი ტრანსი“", "phone": "555000007", "password": "password1",
            "legal_status": "company", "id_code": "400000002", "legal_address": "ფოთი, საცდელი ქ. 3",
            "contact_person": "გიორგი", **change}


def test_a_carrier_company_registers_its_fleet_at_once():
    c = TestClient(server.app)
    fleet = [truck(plate="TB-101-AA"), truck(plate="TB-102-AA", truck_type="refrigerated", capacity_kg=15000),
             truck(plate="TB-103-AA", city="Poti")]
    twice = c.post("/api/register", json=carrier(vehicles=[fleet[0], truck(plate="tb 101 aa")]))
    assert twice.status_code == 400 and "ორჯერ" in twice.json()["detail"]
    bad = c.post("/api/register", json=carrier(vehicles=[fleet[0], truck(plate="TB-104-AA", capacity_kg=5)]))
    assert bad.status_code == 400 and bad.json()["detail"].startswith("მანქანა №2:")   # says which truck
    assert c.post("/api/login", json={"phone": "555000007", "password": "password1"}).status_code == 401   # nothing saved
    assert c.post("/api/register", json=carrier(vehicles=fleet)).status_code == 200
    assert [v["plate"] for v in c.get("/api/vehicles/mine").json()] == ["TB-101-AA", "TB-102-AA", "TB-103-AA"]


def test_a_carrier_can_register_now_and_add_trucks_later():
    c = TestClient(server.app)
    assert c.post("/api/register", json=carrier()).status_code == 400            # no trucks and not „later“
    assert c.post("/api/register", json=carrier(trucks_later=True)).status_code == 200
    assert c.get("/api/vehicles/mine").json() == []
    assert c.get("/api/loads/open").status_code == 400                           # the board asks for a truck first
    assert c.post("/api/vehicles", json=truck(plate="TB-105-AA")).status_code == 200
    assert c.get("/api/loads/open").status_code == 200


def test_the_demo_has_an_account_for_every_case():
    import seed_demo
    seed_demo.seed()
    logins = TestClient(server.app).get("/api/meta").json()["demo_logins"]
    cases = {(x["role"], x["legal_status"]) for x in logins}
    assert cases == {(r, s) for r in ("shipper", "driver") for s in ("person", "entrepreneur", "company")}
    labels = " | ".join(x["label"] for x in logins)
    assert "მანქანების გარეშე" in labels and "3 მანქანა" in labels and "საკუთარი შეკვეთა" in labels
    company = next(x for x in logins if x["label"].endswith("საკუთარი შეკვეთა"))
    c = TestClient(server.app)
    me = c.post("/api/login", json={"phone": company["phone"], "password": "demo1234"}).json()
    assert me["is_demo"] and mp.normalize_iban(c.get("/api/me").json()["bank_account"])   # simulated, but well-formed
    trip = next(x for x in c.get("/api/loads/mine").json() if x["status"] == "booked")   # Gori -> Rustavi, №19
    assert trip["order_source"] == "own" and upload(c, trip["id"]).json()["own_order"]["problems"] == []

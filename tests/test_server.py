"""Health, the simulated demo accounts, and the paperwork agent through the real endpoint with no Gemini call."""
import pytest
from fastapi.testclient import TestClient

import server


def signed_in(role="shipper", phone="555000001"):
    c = TestClient(server.app)
    truck = {"truck_type": "dry_van", "capacity_kg": 18000, "city": "Tbilisi", "plate": f"TB-{phone[-3:]}-AA"}
    c.post("/api/register", json={"role": role, "name": "ტესტი", "phone": phone, "password": "password1",
                                  "vehicle": truck if role == "driver" else {}})
    return c


def test_health_and_page():
    c = TestClient(server.app)
    assert c.get("/api/health").json()["status"] == "ok"
    page = c.get("/").text
    assert '<html lang="ka">' in page and "Kargonaut" in page


def test_demo_accounts_are_made_on_an_empty_database(monkeypatch):
    monkeypatch.setenv("KARGONAUT_DEMO_SEED", "1")
    with TestClient(server.app) as c:   # runs the startup step
        health = c.get("/api/health").json()
        assert health["users"] == 14 and health["loads"] == 21   # 10 open + 8 finished + 1 on the road + the deadline load and the trip that clashes with it
        me = c.post("/api/login", json={"phone": "599000001", "password": "demo1234"}).json()
        assert me["is_demo"] is True


def test_without_a_gemini_key_the_chat_says_so_instead_of_crashing(monkeypatch):
    """Found by opening the site with no .env: the chat and the document check answered 500."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    r = signed_in().post("/api/chat", json={"message": "გამარჯობა"})
    assert r.status_code == 200 and r.json()["ai_available"] is False


def test_only_demo_files_can_be_downloaded():
    c = TestClient(server.app)
    assert c.get("/api/paperwork/demo/ge-01/rc.pdf").status_code == 200
    assert c.get("/api/paperwork/demo/ge-01/..%2F..%2F.env").status_code == 404
    assert c.get("/api/paperwork/demo/ge-01/expected.json").status_code == 404


def test_upload_rules():
    c = signed_in()
    assert c.post("/api/paperwork/check").status_code == 400
    assert c.post("/api/paperwork/check", files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 400
    assert TestClient(server.app).post("/api/paperwork/check").status_code == 401


class NoGemini:
    """Stands in for Gemini and records any call: the demo documents' readings ship with the app."""
    calls = []

    def __init__(self, **kwargs):
        pass

    def classify(self, path):
        NoGemini.calls.append(("classify", path))
        raise RuntimeError("Gemini was called")

    def extract(self, path, kind):
        NoGemini.calls.append(("extract", path))
        raise RuntimeError("Gemini was called")


@pytest.fixture
def no_gemini(monkeypatch):
    from paperwork import extract
    NoGemini.calls = []
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")   # a key is "set", so a call WOULD be attempted
    monkeypatch.setattr(extract, "GeminiReader", NoGemini)
    return NoGemini


def _check(c, load):
    files = [("files", (name, c.get(f"/api/paperwork/demo/{load}/{name}").content, "application/octet-stream"))
             for name in next(l["files"] for l in c.get("/api/paperwork/demo").json() if l["id"] == load)]
    r = c.post("/api/paperwork/check", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def test_wrong_carrier_is_caught_end_to_end(no_gemini):
    result = _check(signed_in(), "ge-03")
    assert no_gemini.calls == []
    assert "carrier_not_ours" in {f["check"] for f in result["findings"] if f["severity"] == "problem"}
    assert result["draft_plan"]["available"] is False


def test_a_clean_document_becomes_a_load_draft_only_after_confirm(no_gemini):
    c = signed_in()
    result = _check(c, "ge-01")
    assert no_gemini.calls == [] and result["draft_plan"]["available"] is True
    draft = c.post("/api/paperwork/draft", json={"check_id": result["check_id"], "values": {}})
    assert draft.status_code == 200, draft.text
    d = draft.json()
    assert d["draft"]["origin_city"] == "Poti" and d["draft"]["price_gel"] == 1100
    assert c.get("/api/loads/mine").json() == []                              # nothing saved yet
    c.post(f"/api/drafts/{d['draft_id']}/confirm")
    assert c.get("/api/loads/mine").json()[0]["reference"]                     # the document's load number
    # a driver can check documents too, but can't make a load from them
    driver = signed_in("driver", "555000002")
    other = _check(driver, "ge-01")
    assert driver.post("/api/paperwork/draft", json={"check_id": other["check_id"]}).status_code == 403


def test_the_seed_can_put_the_users_own_accounts_in_place_of_the_first_demo_ones():
    """python seed_demo.py with KARGONAUT_MY_* in .env: ნინო's and ლევანი's data under the user's name and numbers.
    The server's own seed (and the evals) never do this; the login page's demo buttons move to the next demo accounts."""
    import seed_demo
    me = {"name": "ტესტ მომხმარებელი", "shipper_phone": "555000101", "driver_phone": "555000102", "password": "mypass123"}
    seed_demo.seed(me)
    c = TestClient(server.app)
    shipper = c.post("/api/login", json={"phone": "555000101", "password": "mypass123"}).json()
    assert shipper["name"] == "ტესტ მომხმარებელი" and shipper["is_demo"] is False
    assert len(c.get("/api/loads/mine").json()) == 3 + 2 + 1        # ნინო's 3 open loads, 2 finished trips, the deadline load
    d = TestClient(server.app)
    d.post("/api/login", json={"phone": "555000102", "password": "mypass123"})
    assert d.get("/api/vehicles/mine").json()[0]["truck_type"] == "dry_van"
    assert c.post("/api/login", json={"phone": "599000001", "password": "demo1234"}).status_code == 401
    logins = {x["role"]: x["phone"] for x in c.get("/api/meta").json()["demo_logins"]}
    assert logins == {"shipper": "599000002", "driver": "599000006"}

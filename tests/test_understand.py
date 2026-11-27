"""„აღწერეთ ტვირთი“ (ai/understand.py): Python's checks on what Gemini read. No Gemini here: `answer` plays the
model, including a model that invents things the user never wrote."""
from datetime import date

from fastapi.testclient import TestClient

import server
from ai import understand
from ai.understand import check, relative_date

TODAY = date(2026, 11, 27)   # a Friday


def answer(**values):
    blank = {k: None for k in understand.SCHEMA["properties"]}
    return {**blank, "truck_type": "none", "truck_type_reason": "none", **values}


def test_a_plain_message_fills_the_form():
    text = "ხვალ ქუთაისიდან თბილისში 3 ტონა ავეჯი უნდა გავგზავნო, 600 ლარამდე. აღება: რუსთაველის 12."
    r = check(answer(origin_city="Kutaisi", destination_city="Tbilisi", weight_kg=3000, price_gel=600, cargo="ავეჯი",
                     pickup_date="2026-11-28", pickup_date_words="ხვალ", pickup_address="რუსთაველის 12"), text, TODAY)
    v = r["values"]
    assert (v["origin_city"], v["destination_city"], v["weight_kg"], v["price_gel"]) == ("Kutaisi", "Tbilisi", 3000, 600)
    assert v["pickup_date"] == "2026-11-28" and v["pickup_address"] == "რუსთაველის 12"
    assert r["missing"] == [] and r["suggested"] == ["truck_type"]   # no type named: Python suggested one


def test_what_the_user_never_wrote_is_dropped_not_guessed():
    text = "ბათუმში მაქვს გასაგზავნი ციტრუსი"   # no origin, weight, day or price
    r = check(answer(origin_city="Tbilisi", destination_city="Batumi", weight_kg=10000, price_gel=900,
                     pickup_date="2026-11-27", pickup_date_words="დღეს"), text, TODAY)
    assert r["values"]["destination_city"] == "Batumi" and set(r["values"]) <= {"destination_city", "cargo"}
    assert set(r["missing"]) == {"origin_city", "truck_type", "weight_kg", "pickup_date", "price_gel"}


def test_python_turns_relative_days_into_dates_not_the_model():
    assert relative_date("ხვალ", TODAY) == date(2026, 11, 28)
    assert relative_date("ზეგ", TODAY) == date(2026, 11, 29)
    assert relative_date("ორშაბათს", TODAY) == date(2026, 11, 30)     # not "შაბათს" (inside the word)
    assert relative_date("შაბათს", TODAY) == date(2026, 11, 28)
    assert relative_date("პარასკევს", TODAY) == date(2026, 12, 4)     # today is Friday: the next one
    # the model got "ხვალ" wrong (the day after): Python's date wins
    r = check(answer(origin_city="Gori", destination_city="Tbilisi", pickup_date="2026-11-29",
                     pickup_date_words="ხვალ"), "ხვალ გორიდან თბილისში", TODAY)
    assert r["values"]["pickup_date"] == "2026-11-28"


def test_cold_cargo_gets_a_refrigerated_truck_and_says_why():
    r = check(answer(origin_city="Poti", destination_city="Tbilisi", truck_type="Refrigerated",
                     truck_type_reason="cargo_needs_cold", weight_kg=8000), "ფოთიდან თბილისში 8 ტონა გაყინული თევზი", TODAY)
    assert r["values"]["truck_type"] == "refrigerated" and any("სიცივე" in n for n in r["notes"])


def test_a_place_we_dont_serve_is_named_not_swapped_for_another():
    r = check(answer(origin_city="ზუგდიდი", destination_city="Tbilisi"), "ზუგდიდიდან თბილისში", TODAY)
    assert "origin_city" not in r["values"] and r["unknown_places"] == ["ზუგდიდი"]


def test_the_endpoint_fills_without_saving(monkeypatch):
    """The page's call, with Gemini replaced: values come back, no load is created."""
    from test_marketplace import client_for
    monkeypatch.setenv("GEMINI_API_KEY", "test")

    class FakeReader:
        def __init__(self, *a, **k):
            pass

        def generate(self, contents, schema, label=""):
            return answer(origin_city="Kutaisi", destination_city="Tbilisi", weight_kg=3000,
                          pickup_date_words="ხვალ"), {"model": "fake"}

    monkeypatch.setattr("paperwork.extract.GeminiReader", FakeReader)
    c = client_for("shipper", "555000001")
    r = c.post("/api/loads/understand", data={"text": "ხვალ ქუთაისიდან თბილისში 3 ტონა"})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["weight_kg"] == 3000 and "price_gel" in r.json()["missing"]
    assert c.get("/api/loads/mine").json() == []                       # nothing was posted


def test_only_shippers_and_never_without_text():
    from test_marketplace import client_for
    assert client_for("driver", "555000002").post("/api/loads/understand", data={"text": "x"}).status_code == 403
    assert TestClient(server.app).post("/api/loads/understand", data={"text": "x"}).status_code == 401


def test_a_truck_type_the_user_never_named_is_not_taken_from_the_model():
    """27 Nov, real Gemini: "Dry van" with reason "named" for a message that names no type."""
    text = "ხვალ ქუთაისიდან თბილისში 3 ტონა ავეჯი"
    r = check(answer(origin_city="Kutaisi", destination_city="Tbilisi", weight_kg=3000, truck_type="Dry van",
                     truck_type_reason="named"), text, TODAY)
    assert r["suggested"] == ["truck_type"]                              # Python's suggestion instead
    named = check(answer(origin_city="Kutaisi", destination_city="Tbilisi", truck_type="Dry van",
                         truck_type_reason="named"), text + ", ტენტით", TODAY)
    assert named["values"]["truck_type"] == "dry_van" and named["suggested"] == []


def test_a_delivery_deadline_is_read_from_the_users_words():
    text = "ხვალ თბილისიდან ფოთში 10 ტონა, პარასკევამდე უნდა ჩავიდეს"
    r = check(answer(origin_city="Tbilisi", destination_city="Poti", weight_kg=10000, pickup_date_words="ხვალ",
                     deliver_by="2026-12-04", deliver_by_words="პარასკევამდე"), text, TODAY)
    assert r["values"]["deliver_by"] == "2026-12-04"                     # Friday the 27th is today: the next Friday
    same = check(answer(origin_city="Tbilisi", destination_city="Poti", pickup_date_words="ხვალ",
                        deliver_by_words="იმავე დღეს"), "ხვალ თბილისიდან ფოთში, იმავე დღეს უნდა ჩავიდეს", TODAY)
    assert same["values"]["deliver_by"] == same["values"]["pickup_date"] == "2026-11-28"   # not "today"
    made_up = check(answer(origin_city="Tbilisi", destination_city="Poti", deliver_by="2026-12-01",
                           deliver_by_words="1 დეკემბრამდე"), "თბილისიდან ფოთში", TODAY)
    assert "deliver_by" not in made_up["values"]


def test_a_piece_size_is_read_in_metres_or_centimetres_and_never_guessed():
    text = "თბილისიდან ბათუმში 4 პალეტი, თითო 120x80 სმ, სიმაღლე 150"
    r = check(answer(origin_city="Tbilisi", destination_city="Batumi", pieces=4, piece_length_m=1.2, piece_width_m=0.8,
                     piece_height_m=1.5), text, TODAY)
    assert [r["values"][f] for f in ("piece_length_m", "piece_width_m", "piece_height_m")] == [1.2, 0.8, 1.5]
    # A typical pallet height the user never wrote: the size is dropped and the form says what to add
    r = check(answer(piece_length_m=1.2, piece_width_m=0.8, piece_height_m=1.8), "4 პალეტი 1,2x0,8", TODAY)
    assert "piece_length_m" not in r["values"] and any("ზომა" in n for n in r["notes"])


def test_no_stacking_needs_the_users_own_words():
    said = check(answer(no_stacking=True), "6 პალეტი მინა, ერთმანეთზე არ დაიწყობა", TODAY)
    assert said["values"]["no_stacking"] is True
    assert "no_stacking" not in check(answer(no_stacking=True), "6 პალეტი მინა", TODAY)["values"]

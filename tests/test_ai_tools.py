"""The AI's tools, called the way the Gemini loop calls them (ai.common.run_tool), without Gemini.

The design rule: Gemini chooses a tool, Python decides, the user confirms. These tests hold the AI to it."""
import db
import marketplace as mp
from ai.common import run_tool
from ai.engine import ROLES

SHIPPER, DRIVER = ROLES["shipper"], ROLES["driver"]


def shipper_tool(name, args, user, said=None):
    return run_tool(SHIPPER.runners, name, args, user, said_text=said, guards=SHIPPER.guards)


def driver_tool(name, args, user, said=None):
    return run_tool(DRIVER.runners, name, args, user, said_text=said, guards=DRIVER.guards)


def test_the_ai_has_no_tool_that_saves_books_or_changes_status():
    names = {f.__name__ for role in ROLES.values() for f in role.tools}
    for word in ("accept", "confirm", "book", "cancel", "advance", "deliver", "withdraw", "create", "save", "delete"):
        assert not any(word in n for n in names), (word, names)


def test_a_load_from_the_chat_is_only_a_draft(people):
    before = db.one("SELECT COUNT(*) AS n FROM loads")["n"]
    said = "5 ტონა თბილისიდან ბათუმში, Dry van, ხვალ, 900 ლარად; აღება ჭავჭავაძის 10, მიტანა გორგასლის 5"
    r = shipper_tool("propose_load", {"origin_city": "თბილისი", "destination_city": "ბათუმი", "truck_type": "Dry van",
                                      "weight_kg": 5000, "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ",
                                      "price_gel": 900, "pickup_address": "ჭავჭავაძის 10",
                                      "delivery_address": "გორგასლის 5"}, people["shipper"], said)
    assert r["draft_id"] and r["saved"] is False
    assert db.one("SELECT COUNT(*) AS n FROM loads")["n"] == before            # nothing saved yet
    assert r["draft"]["origin_city"] == "თბილისი"                               # labels for the user
    saved = mp.confirm_draft(people["shipper"]["id"], r["draft_id"])            # the Confirm button
    assert saved["status"] == "open" and db.one("SELECT COUNT(*) AS n FROM loads")["n"] == before + 1


def test_a_date_the_user_never_said_is_refused(people):
    """The model invented "today" in logimind-ai although the prompt said never to: Python checks the words."""
    r = shipper_tool("propose_load", {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van",
                                      "weight_kg": 5000, "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ",
                                      "price_gel": 900}, people["shipper"], said="5 ტონა თბილისიდან ბათუმში 900 ლარად")
    assert "pickup_date" in r["needs_input"] and r["pickup_date_rejected"]


def test_a_price_the_user_never_chose_is_refused_and_the_fair_range_offered(people):
    r = shipper_tool("propose_load", {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van",
                                      "weight_kg": 5000, "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ",
                                      "price_gel": 950}, people["shipper"], said="5 ტონა თბილისიდან ბათუმში, ხვალ")
    assert "price_gel" in r["needs_input"] and r["price_rejected"]
    assert len(r["fair_price_range_gel"]) == 2                                  # the user chooses from this


def test_tons_count_as_the_users_weight(people):
    r = shipper_tool("propose_load", {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van",
                                      "weight_kg": 5000, "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ",
                                      "price_gel": 900, "addresses_later": True}, people["shipper"],
                     said="5 ტონა, ხვალ, 900 ლარი, მისამართს მერე გეტყვით")
    assert r.get("draft_id"), r


def test_a_drivers_price_the_driver_never_said_is_refused(people):
    r = driver_tool("propose_offer", {"load_id": people["load"]["id"], "price_gel": 870}, people["driver"],
                    said="ეს ტვირთი მინდა")
    assert "price_gel" in r["needs_input"] and "960" in r["ask_user"]           # tells them the shipper's price
    ok = driver_tool("propose_offer", {"load_id": people["load"]["id"], "price_gel": 870}, people["driver"],
                     said="შევთავაზოთ 870")
    assert ok["draft_id"] and ok["earnings"]["driver_keeps_gel"] == 870 - ok["earnings"]["trip_costs_gel"]
    assert db.one("SELECT COUNT(*) AS n FROM offers")["n"] == 0                 # only a draft


def test_each_user_sees_only_their_own(people):
    r = shipper_tool("offers_for_my_load", {"load_id": people["load"]["id"]}, people["other"])
    assert r["error_code"] == "not_your_load"
    draft = driver_tool("propose_offer", {"load_id": people["load"]["id"], "accept_shipper_price": True},
                        people["driver"], said="გამგზავნის ფასით ვიღებ")
    assert mp.confirm_draft(people["other"]["id"], draft["draft_id"])["error_code"] == "draft_gone"


def test_no_price_means_ask_not_the_shippers_price(people):
    """26 Nov, first real eval: "let's send an offer on №8" became a draft at the shipper's price the driver never
    agreed to. Without a price, the shipper's price is used only when the driver explicitly takes it."""
    asked = driver_tool("propose_offer", {"load_id": people["load"]["id"]}, people["driver"], said="შეთავაზება გავაგზავნოთ")
    assert "price_gel" in asked["needs_input"] and "960" in asked["ask_user"] and "draft_id" not in asked
    taken = driver_tool("propose_offer", {"load_id": people["load"]["id"], "accept_shipper_price": True},
                        people["driver"], said="გამგზავნის ფასით ავიღებ")
    assert taken["draft_id"] and taken["draft"]["price_gel"] == 960


def test_driver_finds_the_load_with_its_earnings(people):
    r = driver_tool("find_loads", {}, people["driver"])
    assert r["best_load_id"] == people["load"]["id"]
    row = r["loads"][0]
    assert row["driver_keeps_gel"] == 960 - row["trip_costs_gel"] and row["origin_city"] == "თბილისი"
    assert driver_tool("find_loads", {"heading_to": "Kutaisi"}, people["driver"])["loads"] == []


def test_estimate_without_a_type_compares_types(people):
    r = shipper_tool("estimate_price", {"origin_city": "ქუთაისიდან", "destination_city": "თბილისში", "weight_kg": 3000},
                     people["shipper"])
    assert r["cheapest_type"] == "Box truck" and r["options"]


def _tomorrow():
    from datetime import date, timedelta
    return (date.today() + timedelta(days=1)).isoformat()


def test_the_chat_asks_for_the_addresses_before_a_draft(people):
    """27 Nov, the user: a draft had no delivery address and the assistant never asked for one."""
    args = {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van", "weight_kg": 5000,
            "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ", "price_gel": 900}
    said = "5 ტონა თბილისიდან ბათუმში, ხვალ, 900 ლარად"
    r = shipper_tool("propose_load", args, people["shipper"], said)
    assert set(r["needs_input"]) == {"pickup_address", "delivery_address"} and "draft_id" not in r
    made_up = shipper_tool("propose_load", {**args, "pickup_address": "რუსთაველის 1", "delivery_address": "ბათუმის პორტი"},
                           people["shipper"], said + ", მიტანა ბათუმის პორტში")
    assert made_up["needs_input"] == ["pickup_address"] and made_up["pickup_address_rejected"]   # never written
    later = shipper_tool("propose_load", {**args, "addresses_later": True}, people["shipper"], said)
    assert later["draft_id"]                                               # the user doesn't know it yet: fine


def test_dangerous_goods_only_when_the_user_names_them(people):
    """27 Nov: a furniture load was posted as dangerous goods."""
    args = {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "dry_van", "weight_kg": 5000,
            "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ", "price_gel": 900, "hazmat": True,
            "addresses_later": True}
    furniture = shipper_tool("propose_load", args, people["shipper"], "5 ტონა ავეჯი, ხვალ, 900 ლარად")
    assert furniture["draft"]["hazmat"] == 0 and furniture["hazmat_rejected"]
    gas = shipper_tool("propose_load", args, people["shipper"], "5 ტონა გაზის ბალონები, ხვალ, 900 ლარად")
    assert gas["draft"]["hazmat"] == 1


def test_free_trucks_from_the_ai_are_the_maps_list_with_phones(people):
    """The same list as the shipper's map: drivers' names and phones, and no truck already booked for a trip."""
    r = shipper_tool("available_vehicles", {"city_name": "Tbilisi"}, people["shipper"])
    assert r["available_vehicles"] >= 1 and r["nearest"][0]["driver_phone"]
    assert {t["driver_phone"] for t in r["nearest"]} <= {t["driver_phone"] for t in mp.free_vehicles()}

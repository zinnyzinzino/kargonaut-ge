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
    said = "5 ტონა თბილისიდან ბათუმში, Dry van, ხვალ, 900 ლარად"
    r = shipper_tool("propose_load", {"origin_city": "თბილისი", "destination_city": "ბათუმი", "truck_type": "Dry van",
                                      "weight_kg": 5000, "pickup_date": _tomorrow(), "pickup_date_words": "ხვალ",
                                      "price_gel": 900}, people["shipper"], said)
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
                                      "price_gel": 900}, people["shipper"], said="5 ტონა, ხვალ, 900 ლარი")
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
    draft = driver_tool("propose_offer", {"load_id": people["load"]["id"]}, people["driver"], said="ვიღებ")
    assert mp.confirm_draft(people["other"]["id"], draft["draft_id"])["error_code"] == "draft_gone"


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

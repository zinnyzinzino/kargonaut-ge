"""The pure-Python engines: every number the site and the AI show comes from here."""
from core.geo import approach_leg, city
from core.matching import compatibility_issues, rank_offers
from core.pricing import FAIR_MARKUP, compare_types, driver_earnings, fair_price, market_evidence, trip_cost
from core.vehicles import truck_type


def test_cities_in_any_form():
    assert city("Tbilisi") == city("tbilisi") == city("თბილისიდან") == "Tbilisi"
    assert city("ქუთაისთან") == "Kutaisi"
    assert city("ზესტაონი") == "Zestafoni"     # the common typo
    assert city("Moscow") is None


def test_truck_types_as_code_label_or_georgian_word():
    assert truck_type("Refrigerated") == truck_type("refrigerated") == truck_type("მაცივარი") == "refrigerated"
    assert truck_type("Box truck") == truck_type("box-truck") == "box_truck"
    assert truck_type("ტენტიანი") == "dry_van"
    assert truck_type("helicopter") is None


def test_a_truck_in_the_pickup_city_still_drives_across_town():
    leg = approach_leg("Batumi", "Batumi")
    assert leg["same_city"] and leg["distance_km"] == 15


def test_trip_cost_adds_up():
    c = trip_cost({"truck_type": "dry_van"}, "Tbilisi", "Tbilisi", "Batumi")
    assert c["loaded_km"] == 363.7                       # real OSRM distance
    assert abs(c["trip_costs_gel"] - (c["fuel_gel"] + c["vehicle_wear_gel"] + c["fixed_trip_costs_gel"])) <= 1
    assert c["full_cost_gel"] == c["trip_costs_gel"] + c["driver_wage_gel"]


def test_the_drivers_own_figures_beat_the_typical_ones():
    typical = trip_cost({"truck_type": "dry_van"}, "Tbilisi", "Tbilisi", "Batumi")
    thrifty = trip_cost({"truck_type": "dry_van", "fuel_l_per_100km": 20}, "Tbilisi", "Tbilisi", "Batumi")
    assert thrifty["fuel_gel"] < typical["fuel_gel"]
    assert "fuel_l_per_100km" in typical["assumed"] and "fuel_l_per_100km" not in thrifty["assumed"]


def test_fair_range_and_verdicts():
    r = fair_price("Tbilisi", "Batumi", "dry_van", 12000)
    low, high = r["fair_price_range_gel"]
    full = r["estimated_full_cost_gel"]
    assert abs(low - full * (1 + FAIR_MARKUP[0])) <= 5 and abs(high - full * (1 + FAIR_MARKUP[1])) <= 5
    assert fair_price("Tbilisi", "Batumi", "dry_van", 12000, full - 1)["verdict"] == "below_costs"
    assert fair_price("Tbilisi", "Batumi", "dry_van", 12000, low - 1)["verdict"] == "below_fair"
    assert fair_price("Tbilisi", "Batumi", "dry_van", 12000, low)["verdict"] == "fair"
    assert fair_price("Tbilisi", "Batumi", "dry_van", 12000, high + 1)["verdict"] == "above_fair"


def test_compare_types_leaves_out_types_that_cannot_carry_it():
    r = compare_types("Kutaisi", "Tbilisi", 5000)
    types = [o["truck_type"] for o in r["options"]]
    assert "box_truck" not in types and "sprinter_van" not in types   # 4 t and 1.5 t typical
    assert {c["truck_type"] for c in r["cannot_carry"]} == {"box_truck", "sprinter_van"}
    assert r["cheapest_type"] == types[0]


def test_no_market_average_from_a_single_advertisement():
    """Batumi -> Tbilisi has one real, unverified advertisement: shown as evidence, never averaged."""
    m = market_evidence("Batumi", "Tbilisi", "dry_van", 8000)
    assert m["observations"] and m["market_average"] is None


def test_driver_keeps_price_minus_trip_costs():
    e = driver_earnings({"truck_type": "dry_van"}, "Gori", "Tbilisi", "Batumi", 1000)
    assert e["driver_keeps_gel"] == 1000 - e["trip_costs_gel"]
    assert e["empty_km"] == 85.8                         # Gori -> Tbilisi, empty (real OSRM; the other way is 86.1)


def test_compatibility():
    van = {"truck_type": "dry_van", "capacity_kg": 18000, "liftgate": 0, "hazmat": 0}
    assert compatibility_issues(van, {"truck_type": "dry_van", "weight_kg": 12000}) == []
    assert compatibility_issues(van, {"truck_type": "dry_van", "weight_kg": 19000})
    assert compatibility_issues(van, {"truck_type": "flatbed", "weight_kg": 1000})
    assert compatibility_issues(van, {"truck_type": "dry_van", "weight_kg": 10, "needs_liftgate": 1})


def test_cheapest_offer_first_closer_vehicle_on_a_tie():
    load = {"origin_city": "Tbilisi"}
    offers = [{"id": 1, "price_gel": 900, "vehicle_city": "Batumi"}, {"id": 2, "price_gel": 900, "vehicle_city": "Gori"},
              {"id": 3, "price_gel": 950, "vehicle_city": "Tbilisi"}]
    assert [o["id"] for o in rank_offers(load, offers)] == [2, 1, 3]

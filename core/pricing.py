"""Trip costs and fair prices: every money number the site or the AI shows comes from here.

Money model (marketplace, no company in the middle):
- The shipper pays the driver the agreed price.
- The driver pays the trip's costs out of it: diesel, vehicle wear, fixed trip costs (tolls, parking, food).
- What the driver keeps = price - trip costs. That is pay for the driver's own time, not "profit".
- A FAIR price covers the trip costs plus a day's driver wage, plus a markup (the range below).
- The platform's own fee is NOT decided yet (see README, "Open business decisions"), so it is not in here.

Real: road distances and drive times (OSRM), the diesel price reference (data/operating_costs.json).
Simulated: vehicle wear per km, the driver's day wage, fixed trip costs, the markup range, typical vehicles.
"""
import json
import math
from datetime import date, datetime
from functools import lru_cache

from core.geo import DATA, approach_leg, route
from core.vehicles import TRUCK_TYPES, TYPICAL, with_defaults

# SIMULATED markup range on top of a trip's full cost (with the driver's day wage): the lowest and highest
# markups of logimind-ai's 10 simulated truck owners (data/owner_rates.json: 9% to 25%).
FAIR_MARKUP = (0.09, 0.25)
MARKET_RULE_DAYS = 180   # a market average needs >= 3 verified completed deals on the lane within this many days


@lru_cache(maxsize=1)
def assumptions():
    return json.loads((DATA / "operating_costs.json").read_text(encoding="utf-8"))


def _round10(x):
    return int(round(x / 10) * 10)


def trip_cost(vehicle, start_city, origin, destination):
    """What one trip costs this vehicle: the empty drive from start_city to the pickup, then the loaded drive.
    vehicle needs truck_type; fuel_l_per_100km and cost_per_km default to the type's typical values.
    Returns None if a city has no route data."""
    v = with_defaults(vehicle)
    empty = approach_leg(start_city, origin)
    loaded = route(origin, destination)
    if empty is None or loaded is None:
        return None
    a = assumptions()
    km = empty["distance_km"] + loaded["distance_km"]
    hours = (empty["duration_minutes"] + loaded["duration_minutes"]) / 60
    fuel = km * v["fuel_l_per_100km"] / 100 * a["fuel"]["diesel_price_per_liter"]
    wear = km * v["cost_per_km"]
    fixed = a["trip"]["fixed_trip_cost"] + a["trip"]["default_toll_cost"]
    days = max(1, math.ceil(hours / a["driver"]["assumed_driving_hours_per_day"]))
    wage = days * a["driver"]["cost_per_day"]
    costs = fuel + wear + fixed
    return {
        "empty_km": round(empty["distance_km"], 1),
        "empty_minutes": round(empty["duration_minutes"]),
        "loaded_km": round(loaded["distance_km"], 1),
        "loaded_minutes": round(loaded["duration_minutes"]),
        "total_km": round(km, 1),
        "driving_hours": round(hours, 1),
        "fuel_gel": round(fuel),
        "vehicle_wear_gel": round(wear),
        "fixed_trip_costs_gel": round(fixed),
        "trip_costs_gel": round(costs),             # what the driver pays out of the price
        "driver_days": days,
        "driver_wage_gel": round(wage),             # a fair day's pay for the driver's time (simulated)
        "full_cost_gel": round(costs + wage),       # costs + wage: the least a fair price must cover
        "assumed": v.get("assumed", []),
    }


def driver_earnings(vehicle, start_city, origin, destination, price_gel):
    """What a driver keeps from a load at a price: price - trip costs, and per driving hour."""
    cost = trip_cost(vehicle, start_city, origin, destination)
    if cost is None:
        return None
    keeps = price_gel - cost["trip_costs_gel"]
    return {
        **cost,
        "price_gel": round(price_gel),
        "driver_keeps_gel": round(keeps),
        "per_driving_hour_gel": round(keeps / cost["driving_hours"]) if cost["driving_hours"] else None,
        "covers_a_days_wage": keeps >= cost["driver_wage_gel"],
    }


VERDICTS = ("below_costs", "below_fair", "fair", "above_fair")


def _verdict(price, cost, low, high):
    if price is None:
        return None
    if price < cost["full_cost_gel"]:
        return "below_costs"      # no driver covers costs and a day's wage at this price
    if price < low:
        return "below_fair"
    if price <= high:
        return "fair"
    return "above_fair"


def fair_price(origin, destination, truck_type, weight_kg=None, offered_price=None):
    """The fair price range for a load, for a typical vehicle of this type starting in the pickup city."""
    if truck_type not in TRUCK_TYPES:
        return {"error": f"unknown truck type {truck_type!r}"}
    cost = trip_cost({"truck_type": truck_type}, origin, origin, destination)
    if cost is None:
        return {"error": f"no route data for {origin} -> {destination}"}
    low = _round10(cost["full_cost_gel"] * (1 + FAIR_MARKUP[0]))
    high = _round10(cost["full_cost_gel"] * (1 + FAIR_MARKUP[1]))
    capacity = TYPICAL[truck_type]["capacity_kg"]
    result = {
        "origin": origin, "destination": destination, "truck_type": truck_type, "weight_kg": weight_kg,
        "loaded_km": cost["loaded_km"], "loaded_minutes": cost["loaded_minutes"],
        "estimated_trip_costs_gel": cost["trip_costs_gel"],
        "estimated_full_cost_gel": cost["full_cost_gel"],
        "fair_price_range_gel": [low, high],
        "offered_price_gel": offered_price,
        "verdict": _verdict(offered_price, cost, low, high),
        "typical_capacity_kg": capacity,
        "too_heavy_for_typical_vehicle": bool(weight_kg and weight_kg > capacity),
        "market_evidence": market_evidence(origin, destination, truck_type, weight_kg),
        "data_note": ("Estimate for a typical vehicle (simulated costs and markup); distances are real OSRM road "
                      "distances, diesel is a retail reference price. Drivers set their own prices."),
    }
    return result


def compare_types(origin, destination, weight_kg, offered_price=None):
    """Fair price per truck type that can carry the weight (typical capacity), cheapest first, and the types
    that can't, with why."""
    options, cannot = [], []
    for t in TRUCK_TYPES:
        capacity = TYPICAL[t]["capacity_kg"]
        if weight_kg and weight_kg > capacity:
            cannot.append({"truck_type": t, "typical_capacity_kg": capacity})
            continue
        r = fair_price(origin, destination, t, weight_kg, offered_price)
        if "error" not in r:
            options.append({k: r[k] for k in ("truck_type", "fair_price_range_gel", "estimated_full_cost_gel",
                                              "verdict", "typical_capacity_kg")})
    options.sort(key=lambda o: o["fair_price_range_gel"][0])
    return {"origin": origin, "destination": destination, "weight_kg": weight_kg, "offered_price_gel": offered_price,
            "options": options, "cannot_carry": cannot,
            "cheapest_type": options[0]["truck_type"] if options else None}


def market_evidence(origin, destination, truck_type, weight_kg=None):
    """Sourced freight-rate observations for this lane (data/freight_rates.json), each with its evidence type.
    A market average is given only with >= 3 recent verified completed deals; otherwise it says there is none."""
    data = json.loads((DATA / "freight_rates.json").read_text(encoding="utf-8"))
    found, usable = [], []
    for obs in data["observations"]:
        if obs.get("is_simulated") or obs.get("geography", "domestic_georgia") != "domestic_georgia":
            continue
        direction = ("same" if (obs["origin"], obs["destination"]) == (origin, destination) else
                     "reverse" if (obs["origin"], obs["destination"]) == (destination, origin) else None)
        if direction is None:
            continue
        found.append({"direction": direction, "rate": obs["rate"], "currency": obs["currency"],
                      "evidence_type": obs["source_type"], "source": obs["source"],
                      "observed_on": obs.get("observed_on"), "verified": bool(obs.get("verified")),
                      "truck_type": obs.get("truck_type"), "max_weight_kg": obs.get("max_weight_kg")})
        if (direction == "same" and obs["source_type"] == "verified_completed_transaction" and obs.get("verified")
                and obs["truck_type"] == truck_type and obs.get("currency") == "GEL" and obs.get("observed_on")
                and (obs.get("max_weight_kg") is None or weight_kg is None or weight_kg <= obs["max_weight_kg"])
                and (date.today() - datetime.fromisoformat(obs["observed_on"]).date()).days <= MARKET_RULE_DAYS):
            usable.append(obs["rate"])
    average = ({"market_average_gel": round(sum(usable) / len(usable)), "based_on": len(usable)}
               if len(usable) >= 3 else None)
    return {"observations": found, "market_average": average,
            "market_average_note": None if average else
            "No market average: fewer than 3 recent verified completed deals on this lane."}

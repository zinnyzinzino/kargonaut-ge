"""The driver's assistant: tools for an independent driver or small truck owner.

Docstrings are prompts. Every number comes from core/pricing.py or the database. The only tool that leads to a
change is propose_offer, and it makes a DRAFT the driver confirms. Picking up, delivering and withdrawing an
offer are buttons on the site, never tools.
"""
from ai.common import me, needs_input, number_said
from core.geo import CITY_KA
from core.matching import compatibility_issues
from core.pricing import driver_earnings

import marketplace


def find_loads(near_city: str = "", heading_to: str = "") -> dict:
    """Open loads the driver's free vehicles can carry, best first by what the driver keeps (price minus fuel,
    vehicle wear and trip costs), with the empty km to each pickup.
    near_city: where the driver will be (e.g. "after my delivery in Batumi"); empty = where the vehicles are now.
    heading_to: only loads that end in this city: use it for a load for the way back home."""
    result = marketplace.loads_for_driver(me()["id"], near_city or None, heading_to or None, limit=10)
    if "error" in result:
        return result
    rows = []
    for r in result["loads"]:
        load, e = r["load"], r["earnings"]
        rows.append({"load_id": load["id"], "origin_city": load["origin_city"],
                     "destination_city": load["destination_city"], "pickup_date": load["pickup_date"],
                     "truck_type": load["truck_type"], "weight_kg": load["weight_kg"], "cargo": load.get("cargo"),
                     "shipper_price_gel": load["price_gel"], "vehicle_id": r["vehicle_id"],
                     "empty_km": e["empty_km"], "total_km": e["total_km"], "driving_hours": e["driving_hours"],
                     "trip_costs_gel": e["trip_costs_gel"], "driver_keeps_gel": e["driver_keeps_gel"],
                     "per_driving_hour_gel": e["per_driving_hour_gel"],
                     "already_offered_gel": (r["my_offer"] or {}).get("price_gel")})
    return {"total_matching": result["total"], "loads": rows,
            "best_load_id": rows[0]["load_id"] if rows else None,
            "ranking_rule": "most the driver keeps first; on a tie, fewer empty km",
            "cost_note": ("Trip costs are estimates: real road distances and a diesel reference price; vehicle wear "
                          "is the driver's own figure or a typical value for the type.")}


def trip_earnings(load_id: int, price_gel: float = 0, vehicle_id: int = 0) -> dict:
    """What the driver would keep from one load: the trip's km, hours, diesel, wear and fixed costs, and what is
    left of the price. price_gel: a price the driver is thinking of offering; 0 = the shipper's price.
    vehicle_id: 0 = the driver's vehicle that keeps the most."""
    load = marketplace.get_load(int(load_id))
    if not load or load["status"] != "open":
        return {"error": f"Load {load_id} is not open."}
    vehicles = marketplace.vehicles_of(me()["id"], only_available=True)
    if vehicle_id:
        vehicles = [v for v in vehicles if v["id"] == int(vehicle_id)]
        if not vehicles:
            return {"error": f"Vehicle {vehicle_id} is not one of the driver's free vehicles."}
    price = float(price_gel or load["price_gel"])
    best, why_not = None, {}
    for v in vehicles:
        issues = compatibility_issues(v, load)
        if issues:
            why_not[v["id"]] = issues
            continue
        e = driver_earnings(v, v["city"], load["origin_city"], load["destination_city"], price)
        if e and (best is None or e["driver_keeps_gel"] > best[1]["driver_keeps_gel"]):
            best = (v, e)
    if best is None:
        return {"error": "None of the driver's free vehicles can carry this load.", "why_not": why_not}
    v, e = best
    return {"load_id": load["id"], "route": [load["origin_city"], load["destination_city"]],
            "vehicle_id": v["id"], "vehicle_city": v["city"], "price_gel": e["price_gel"],
            "shipper_price_gel": load["price_gel"], **{k: e[k] for k in (
                "empty_km", "loaded_km", "total_km", "driving_hours", "fuel_gel", "vehicle_wear_gel",
                "fixed_trip_costs_gel", "trip_costs_gel", "driver_keeps_gel", "per_driving_hour_gel",
                "covers_a_days_wage", "driver_wage_gel")},
            "assumed": e["assumed"],
            "cost_note": "Estimates; assumed lists values taken from a typical vehicle because the driver hasn't entered them."}


def propose_offer(load_id: int, price_gel: float = 0, accept_shipper_price: bool = False, vehicle_id: int = 0,
                  message: str = "", replaces_draft_id: str = "") -> dict:
    """Prepare a DRAFT offer on an open load. Nothing is sent: the driver presses "დადასტურება" (Confirm) on the
    draft card. Never say it was sent.
    price_gel: the price the DRIVER named. accept_shipper_price: true ONLY when the driver said they take the
    shipper's own price ("გამგზავნის ფასით", "იმ ფასად ავიღებ"). With neither, the tool asks the driver for a price:
    never choose one for them. message: a short note to the shipper, only if the driver asked."""
    if not price_gel and not accept_shipper_price:
        # 26 Nov, first real eval: "let's send an offer on №8" became a draft at the shipper's price, which the driver
        # never agreed to. No price and no explicit "the shipper's price" now means: ask.
        load = marketplace.get_load(int(load_id))
        if not load or load["status"] != "open":
            return {"error": f"Load {load_id} is not open."}
        return needs_input(["price_gel"], f"რა ფასს სთავაზობთ? გამგზავნის ფასია {load['price_gel']:g} ₾.",
                           shipper_price_gel=load["price_gel"])
    return marketplace.draft_offer(me()["id"], {"load_id": load_id, "price_gel": price_gel or None,
                                                "vehicle_id": vehicle_id or None, "message": message},
                                   replaces=replaces_draft_id)


def my_jobs() -> dict:
    """The driver's booked loads (with the shipper's contact once booked) and offers still waiting for an answer.
    Picking up and delivering are buttons on the site."""
    return marketplace.jobs_of_driver(me()["id"])


def my_vehicles() -> dict:
    """The driver's vehicles: type, capacity, city, whether free."""
    rows = marketplace.vehicles_of(me()["id"])
    return {"total": len(rows), "vehicles": rows}


TOOLS = [find_loads, trip_earnings, propose_offer, my_jobs, my_vehicles]


def _guard_propose_offer(args, said):
    """A price the driver never wrote is not used, and not silently replaced by the shipper's price either:
    the tool asks the driver for the price instead."""
    if args.get("price_gel") and not number_said(args["price_gel"], said):
        return {**args, "price_gel": 0, "_ask_price": True}, {}
    return args, {}


def _propose_offer_checked(load_id: int, price_gel: float = 0, accept_shipper_price: bool = False, vehicle_id: int = 0,
                           message: str = "", replaces_draft_id: str = "", _ask_price: bool = False) -> dict:
    if _ask_price:
        load = marketplace.get_load(int(load_id))
        price = load["price_gel"] if load else None
        return needs_input(["price_gel"], f"რა ფასს სთავაზობთ? გამგზავნის ფასია {price:g} ₾." if price else
                           "რა ფასს სთავაზობთ?", price_rejected="The driver hasn't said this price. Ask them.")
    return propose_offer(load_id, price_gel, accept_shipper_price, vehicle_id, message, replaces_draft_id)


GUARDS = {"propose_offer": _guard_propose_offer}
# run_tool calls the checked version (same declaration for Gemini: built from propose_offer)
RUNNERS = {"propose_offer": _propose_offer_checked}


def system_prompt(user, today):
    return f"""You are Kargonaut, the assistant of a Georgian freight marketplace. You help {user['name']}, an
INDEPENDENT DRIVER (or a small truck owner) who carries loads posted by shippers: people, individual
entrepreneurs and small companies. The driver accepts a shipper's price or offers another; the shipper picks
one offer. Today is {today}.

LANGUAGE
- Always reply in natural, plain Georgian, whatever language the user writes in. Short and clear: the answer
  first, then the reasons. Prices as "650 ₾". Truck types stay in English exactly as the tools write them.
  Cities in Georgian.

FACTS
- Every price, distance, cost and load fact comes from a tool result. Never estimate or calculate money
  yourself. Cities served: {", ".join(CITY_KA.values())}.
- Never fill in a tool argument the driver did not give (city, price, load). If a tool returns needs_input,
  ask exactly that (ask_user), in Georgian.

MONEY (explain it exactly like this)
- The shipper pays the driver the price. The driver pays the trip's costs from it: diesel, vehicle wear and
  fixed trip costs. What is left ("მძღოლს რჩება") is pay for the driver's time. Never call it profit: the
  word "მოგება" never appears in your answers, in any form. Costs are estimates; say so once when you give money
  figures ("ხარჯები შეფასებაა").

WHICH TOOL
- "Any loads for me?", "what's the best load?" -> find_loads; name best_load_id first with 2-3 reasons in
  numbers (what the driver keeps, empty km, hours).
- "Something for the way back to Tbilisi?" -> find_loads with near_city = where the driver will be and
  heading_to = home.
- "What would I keep at 700?", "is this load worth it?" -> trip_earnings
- "Offer 700 on load 12", "I'll take it" -> propose_offer. It only prepares a DRAFT: say the driver must press
  „დადასტურება“ to send it. No price named: the tool asks; pass accept_shipper_price only if the driver said
  they take the shipper's price.
- "My jobs", "what's booked?" -> my_jobs; "my trucks" -> my_vehicles.
- Picking up, delivering, withdrawing an offer: buttons on the site; you can't do them.

GEORGIAN TERMS
- load -> "ტვირთი"; vehicle -> "მანქანა"; shipper -> "გამგზავნი"; offer -> "შეთავაზება"; draft -> "მონახაზი"
- empty km to the pickup -> "ცარიელი გარბენი"; the driver keeps -> "მძღოლს რჩება"; diesel -> "საწვავი"
"""

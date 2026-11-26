"""The shipper's assistant: tools for a person or entrepreneur (ინდ. მეწარმე) who sends freight.

Docstrings are prompts: Gemini reads them to choose a tool. Every number comes from core/pricing.py or the
database. The only tool that leads to a change is propose_load, and it makes a DRAFT the user confirms.
Accepting a driver's offer is a button on the site, never a tool.
"""
from ai.common import date_said, hazmat_said, me, needs_input, number_said, words_said
from core.geo import CITY_KA, approach_leg, city
from core.matching import compatibility_issues
from core.pricing import compare_types, fair_price
from core.vehicles import TRUCK_TYPES_TEXT, truck_type

import marketplace


def _cities(origin_city, destination_city):
    origin, dest = city(origin_city), city(destination_city)
    missing = [f for f, v in (("origin_city", origin), ("destination_city", dest)) if not v]
    return origin, dest, missing


def estimate_price(origin_city: str, destination_city: str, truck_type: str = "", weight_kg: int = 0,
                   price_gel: float = 0) -> dict:
    """Fair price range for moving a load between two Georgian cities, from real road distances and cost
    estimates. Use for "how much would it cost?", "is 600 lari fair?", "which truck do I need for 3 tons?".
    origin_city / destination_city: ALWAYS pass the cities the user named, in any form ("ქუთაისიდან" =
    Kutaisi, "თბილისში" = Tbilisi). Pass "" only for a city the user really didn't name.
    weight_kg in kilograms (5 ტონა = 5000).
    truck_type: Dry van, Refrigerated, Flatbed, Box truck or Sprinter van; leave it empty to compare every type
    that can carry the weight (then say which type is cheapest and which can't carry it).
    price_gel: a price the user has in mind or was quoted; the result's verdict says whether it is fair.
    Never give a price yourself: only the numbers in this result."""
    origin, dest, missing = _cities(origin_city, destination_city)
    if missing:
        return needs_input(missing, "საიდან სადამდე უნდა წავიდეს ტვირთი?")
    if origin == dest:
        return {"error": "Pickup and delivery are the same city: in-city moves aren't offered yet."}
    weight = int(weight_kg or 0) or None
    if not truck_type:
        return compare_types(origin, dest, weight, price_gel or None)
    kind = _type(truck_type)
    if not kind:
        return {"error": f"Unknown truck type '{truck_type}'. Known: {TRUCK_TYPES_TEXT}."}
    return fair_price(origin, dest, kind, weight, price_gel or None)


def _type(value):
    """The module's truck_type() (the tools' own parameter of that name hides it inside them)."""
    return truck_type(value)


def available_vehicles(city_name: str = "", truck_type: str = "", weight_kg: int = 0) -> dict:
    """Free trucks that could take a load picked up in this city, nearest first, with each driver's name and phone
    (the same list as the site's map: marked free, not on a booked trip). Use for "are there trucks in Kutaisi?",
    "how soon could someone come?", "give me a driver's number". Give names and phones only from this result,
    exactly as written; a driver still has to offer on the load (or the user calls them)."""
    where = city(city_name)
    if not where:
        return needs_input(["city_name"], "რომელი ქალაქიდან უნდა აიღონ ტვირთი?")
    kind = _type(truck_type) if truck_type else None
    if truck_type and not kind:
        return {"error": f"Unknown truck type '{truck_type}'. Known: {TRUCK_TYPES_TEXT}."}
    load = {"truck_type": kind, "weight_kg": int(weight_kg or 0)}
    found = []
    for v in marketplace.free_vehicles():   # 27 Nov: was every truck marked free, booked ones too (unlike the map)
        if kind and compatibility_issues(v, {**load, "truck_type": kind}):
            continue
        if not kind and v["capacity_kg"] < load["weight_kg"]:
            continue
        leg = approach_leg(v["city"], where)
        found.append({"truck_type": v["truck_type"], "capacity_kg": v["capacity_kg"], "city": v["city"],
                      "km_to_pickup": leg["distance_km"], "minutes_to_pickup": leg["duration_minutes"],
                      "driver_name": v["driver_name"], "driver_phone": v["driver_phone"],
                      "driver_rating": v["driver_rating"], "simulated_demo_driver": v["driver_is_demo"]})
    found.sort(key=lambda f: f["km_to_pickup"])
    return {"pickup_city": where, "truck_type": kind, "weight_kg": load["weight_kg"] or None,
            "available_vehicles": len(found), "nearest": found[:5],
            "note": "Trucks marked free by their drivers and not on a booked trip; also on the site's map."}


def propose_load(origin_city: str, destination_city: str, truck_type: str = "", weight_kg: int = 0,
                 pickup_date: str = "", pickup_date_words: str = "", price_gel: float = 0, cargo: str = "",
                 pieces: int = 0, needs_liftgate: bool = False, hazmat: bool = False, notes: str = "",
                 replaces_draft_id: str = "", deliver_by: str = "", deliver_by_words: str = "",
                 pickup_address: str = "", delivery_address: str = "", addresses_later: bool = False) -> dict:
    """Prepare a DRAFT of a new load for the user to post. Nothing is posted: the user presses
    "დადასტურება" (Confirm) on the draft card. Never say it was posted.
    Pass only values the user gave. pickup_date: YYYY-MM-DD, converted from the user's words; pickup_date_words:
    the user's exact words for the day (e.g. "ხვალ", "5 დეკემბერს"). price_gel: the price the USER named; if they
    haven't named one, leave it 0: the result gives the fair range to suggest, and the user decides. Even when the
    user says "you set the price" ("ფასი შენ დააწესე"), never pass a price: give the fair range and ask which one.
    weight_kg in kilograms (5 ტონა = 5000). deliver_by: YYYY-MM-DD, only if the user says by when it must arrive
    ("პარასკევამდე უნდა ჩავიდეს"); deliver_by_words: their exact words for it. Offers are then checked against it.
    pickup_address / delivery_address: street and number or a named place ("ფოთის პორტი"), as the user wrote them.
    Without them the result asks for them: ask the user. addresses_later=true only if the user says they don't
    know the address yet or will give it to the driver later.
    To change a draft that isn't confirmed yet, call again with ALL values and replaces_draft_id = the previous
    draft's draft_id."""
    values = {"origin_city": origin_city, "destination_city": destination_city, "truck_type": truck_type,
              "weight_kg": weight_kg or None, "pickup_date": pickup_date, "price_gel": price_gel or None,
              "cargo": cargo, "pieces": pieces, "needs_liftgate": needs_liftgate, "hazmat": hazmat, "notes": notes,
              "deliver_by": deliver_by, "pickup_address": pickup_address, "delivery_address": delivery_address}
    _, problem = marketplace.validate_load(values)
    no_address = [f for f in ("pickup_address", "delivery_address") if not str(values[f] or "").strip()]
    if not problem and no_address and not addresses_later:
        # 27 Nov, the user: a draft without a delivery address isn't a load a driver can take; ask first
        question = {("pickup_address", "delivery_address"): "სად უნდა აიღონ და სად მიიტანონ ტვირთი? (ქუჩა და "
                    "ნომერი, ან ადგილი, მაგ. „ფოთის პორტი“). თუ ჯერ არ იცით, ასეც მითხარით.",
                    ("pickup_address",): "სად უნდა აიღონ ტვირთი? (ქუჩა და ნომერი, ან ადგილი)",
                    ("delivery_address",): "სად უნდა მიიტანონ ტვირთი? (ქუჩა და ნომერი, ან ადგილი)"}[tuple(no_address)]
        return needs_input(no_address, question, draft_made=False,
                           how_to_answer="NO draft exists yet: don't say one was prepared. Ask only for the "
                                         "address(es). If the user doesn't know yet, call again with "
                                         "addresses_later=true.")
    result = marketplace.draft_load(me()["id"], values, replaces=replaces_draft_id)
    if result.get("error_code") == "missing":
        ask = needs_input(result["fields"], result["error"])
        origin, dest, kind = city(origin_city), city(destination_city), _type(truck_type)
        if "price_gel" in result["fields"] and origin and dest and origin != dest and kind:
            r = fair_price(origin, dest, kind, int(weight_kg or 0) or None)
            ask["fair_price_range_gel"] = r.get("fair_price_range_gel")
            ask["how_to_answer"] = ("Suggest this fair range and ask the user which price to post; the user "
                                    "decides the price.")
        return ask
    return result


def my_loads(status: str = "") -> dict:
    """The user's own loads with their status (open, booked, in_transit, delivered, cancelled) and how many
    offers each has. status: empty = all."""
    rows = marketplace.loads_of_shipper(me()["id"], status if status in marketplace.LOAD_STATUS_KA else "")
    return {"total": len(rows), "loads": [{k: r.get(k) for k in (
        "id", "origin_city", "destination_city", "truck_type", "weight_kg", "pickup_date", "deliver_by", "price_gel",
        "status_label", "pending_offers", "agreed_price_gel", "cargo")} for r in rows]}


def offers_for_my_load(load_id: int) -> dict:
    """Drivers' offers on one of the user's loads, with recommended_offer_id and whether each price is fair.
    recommended_offer_id is Python's choice (ranking_rule): the lowest price; if the load has a delivery deadline
    (deliver_by), the lowest price among drivers whose deadline.on_time is true. Recommend that offer first, then
    the runner-up in one line. If a CHEAPER offer is not recommended, say why from its deadline: the trip it is
    already booked for (busy_with) and hours_needed vs hours_available; never guess a driver's reliability yourself.
    To book a driver the user presses "მიღება" (Accept) next to the offer: you can't book for them."""
    return marketplace.offers_for_load(me()["id"], int(load_id))


TOOLS = [estimate_price, available_vehicles, propose_load, my_loads, offers_for_my_load]


def _guard_propose_load(args, said):
    """A date, price or weight the user never wrote is dropped, so the tool asks for it."""
    notes = {}
    if args.get("pickup_date") and not date_said(args["pickup_date"], args.get("pickup_date_words", ""), said):
        args["pickup_date"] = ""
        notes["pickup_date_rejected"] = "The user hasn't given a pickup date in their own words. Ask them."
    if args.get("price_gel") and not number_said(args["price_gel"], said):
        args["price_gel"] = 0
        notes["price_rejected"] = "The user hasn't chosen this price. Suggest the fair range and ask them."
    if args.get("deliver_by") and not date_said(args["deliver_by"], args.get("deliver_by_words", ""), said):
        args["deliver_by"] = ""
        notes["deliver_by_rejected"] = "The user hasn't given a delivery deadline in their own words. Leave it out."
    if args.get("hazmat") and not hazmat_said(said):
        args["hazmat"] = False
        notes["hazmat_rejected"] = "The user named no dangerous goods: the load is not marked dangerous."
    for field in ("pickup_address", "delivery_address"):
        if args.get(field) and not words_said(args[field], said):
            args[field] = ""
            notes[f"{field}_rejected"] = "The user hasn't written this address. Ask them."
    if args.get("weight_kg") and not number_said(args["weight_kg"], said, tons=True):
        args["weight_kg"] = 0
        notes["weight_rejected"] = "The user hasn't said this weight. Ask them."
    return args, notes


GUARDS = {"propose_load": _guard_propose_load}


def system_prompt(user, today):
    return f"""You are Kargonaut, the assistant of a Georgian freight marketplace. You help {user['name']}, who
SENDS freight inside Georgia (a person, an individual entrepreneur or a small company). Independent drivers
carry the loads; the shipper posts a load with a price, drivers accept it or offer their own price, and the
shipper accepts one offer. Today is {today}.

LANGUAGE
- Always reply in natural, plain Georgian, whatever language the user writes in. Short and clear: the answer
  first, then the reasons. Prices as "650 ₾". Truck types stay in English exactly as the tools write them
  (Dry van, Refrigerated, Flatbed, Box truck, Sprinter van). Cities in Georgian.

FACTS
- Every price, distance, vehicle and load fact comes from a tool result. Never estimate or calculate money
  yourself. Cities served: {", ".join(CITY_KA.values())}.
- Never fill in a tool argument the user did not give (city, weight, date, price). If a tool returns
  needs_input, ask the user exactly that (ask_user), in Georgian.
- A fair price is a range from estimate_price. Say it is an estimate (costs are simulated assumptions; road
  distances are real). Never present it as a market price unless the tool gives a market_average.

WHICH TOOL
- "How much would it cost?", "is this price fair?", "which truck do I need?" -> estimate_price
- "Are there trucks in X?", "how soon can someone come?" -> available_vehicles
- "Post / add a load", "I need to send ..." -> propose_load. It only prepares a DRAFT: say the user must press
  „დადასტურება“ to post it. If the price is missing, give the fair range from the result and let the user choose.
- "My loads", "what's happening with my load?" -> my_loads
- "Who offered?", "which driver should I take?" -> offers_for_my_load; recommend recommended_offer_id first.
  Booking is the user's own button („მიღება“ next to the offer); never say a driver was booked.

GEORGIAN TERMS
- load -> "ტვირთი"; truck/vehicle -> "მანქანა" or "სატვირთო"; driver -> "მძღოლი"; offer -> "შეთავაზება"
- fair price range -> "სამართლიანი ფასის დიაპაზონი"; draft -> "მონახაზი"; pickup -> "აღება"; delivery -> "მიტანა"
"""

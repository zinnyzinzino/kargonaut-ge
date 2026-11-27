"""Which vehicle can carry which load, and the ranking of loads for a driver and of offers for a shipper.
Python decides every ranking; the AI only explains it."""
from core.geo import approach_leg
from core.pricing import driver_earnings
from core.vehicles import TRUCK_LABEL


def compatibility_issues(vehicle, load):
    """Reasons this vehicle can't carry this load (empty list = it can)."""
    issues = []
    if vehicle["truck_type"] != load["truck_type"]:
        issues.append(f"wrong type: {TRUCK_LABEL[vehicle['truck_type']]}, the load needs {TRUCK_LABEL[load['truck_type']]}")
    if load["weight_kg"] > vehicle["capacity_kg"]:
        issues.append(f"too heavy: {load['weight_kg']} kg, the vehicle carries {vehicle['capacity_kg']} kg")
    if load.get("needs_liftgate") and not vehicle.get("liftgate"):
        issues.append("no liftgate")
    if load.get("hazmat") and not vehicle.get("hazmat"):
        issues.append("not allowed to carry dangerous goods")
    size = size_check(vehicle, load)
    return issues + (size["issues"] if size else [])


PIECE_SIZE = ("piece_length_m", "piece_width_m", "piece_height_m")   # one piece of the load, metres (all or none)


def _m(x):
    return f"{x:g} m"


def size_check(vehicle, load):
    """Does the load fit the truck's body? None if the load has no size.

    The load gives one piece's length x width x height and the number of pieces; the driver may have given the
    body's inside size (optional). Checked, only against what the driver entered:
      - one piece fits on the floor: it may be turned (length and width swap), never tipped over;
      - its height fits under the roof (a flatbed has no roof: no height limit);
      - all pieces together are no more space than the body has (volume: a lenient test, it only refuses a load
        that surely can't fit, never one a careful loader could fit);
      - if the pieces can't be stacked (load["no_stacking"]): their floor area instead, flatbeds included.
    Returns {"fits": no problems found, "unknown": the body's size is missing so the check is partial, "issues"}."""
    piece = [load.get(k) for k in PIECE_SIZE]
    if not all(piece):
        return None
    pl, pw, ph = piece
    bl, bw, bh = vehicle.get("length_m"), vehicle.get("width_m"), vehicle.get("height_m")
    roof = vehicle["truck_type"] != "flatbed"
    issues = []
    if bl and bw:
        (p_short, p_long), (b_short, b_long) = sorted((pl, pw)), sorted((bl, bw))
        if p_long > b_long or p_short > b_short:
            issues.append(f"too big: a piece is {_m(pl)} x {_m(pw)}, the body floor is {_m(bl)} x {_m(bw)}")
    if roof and bh and ph > bh:
        issues.append(f"too tall: a piece is {_m(ph)} high, the body is {_m(bh)} high inside")
    pieces = load.get("pieces") or 1
    if load.get("no_stacking"):   # each piece needs its own floor (flatbeds too)
        if bl and bw and not issues and pieces * pl * pw > bl * bw + 1e-9:
            issues.append(f"too much floor: {pieces} pieces that can't be stacked need {pieces * pl * pw:.1f} m2, "
                          f"the body floor is {bl * bw:.1f} m2")
    elif roof and bl and bw and bh and not issues and pieces * pl * pw * ph > bl * bw * bh + 1e-9:
        issues.append(f"too much: {pieces} pieces take {pieces * pl * pw * ph:.1f} m3, the body holds "
                      f"{bl * bw * bh:.1f} m3")
    unknown = not (bl and bw and (bh or not roof))
    return {"fits": not issues, "unknown": unknown, "issues": issues}


def best_vehicle_for_load(vehicles, load, start_city=None):
    """The driver's vehicle that keeps the driver the most on this load (compatible ones only), with the
    earnings; or (None, reasons per vehicle). start_city overrides where the vehicles are (e.g. 'after my
    current delivery in Batumi')."""
    best, why_not = None, {}
    for v in vehicles:
        issues = compatibility_issues(v, load)
        if issues:
            why_not[v["id"]] = issues
            continue
        e = driver_earnings(v, start_city or v["city"], load["origin_city"], load["destination_city"],
                            load["price_gel"])
        if e and (best is None or e["driver_keeps_gel"] > best[1]["driver_keeps_gel"]):
            best = (v, e)
    return best, why_not


def rank_loads_for_driver(vehicles, loads, start_city=None, heading_to=None):
    """Open loads this driver's vehicles can carry, best earnings first. heading_to: only loads delivered to that
    city (a load for the way home)."""
    rows = []
    for load in loads:
        if heading_to and load["destination_city"] != heading_to:
            continue
        best, _ = best_vehicle_for_load(vehicles, load, start_city)
        if best is None:
            continue
        v, e = best
        rows.append({"load": load, "vehicle_id": v["id"], "earnings": e})
    rows.sort(key=lambda r: (-r["earnings"]["driver_keeps_gel"], r["earnings"]["empty_km"]))
    return rows


# SIMULATED assumptions for the delivery-deadline check (not Georgian law, not measured):
DRIVING_HOURS_PER_DAY = 9     # the EU/AETR daily driving limit, used as a reasonable day's driving
HANDLING_HOURS_PER_TRIP = 1   # loading at the pickup + unloading at the delivery


def deadline_check(load, vehicle_city, committed):
    """Can this truck deliver `load` by its deliver_by date? None if the load has no deadline.

    committed: the truck's trips already booked or on the road whose pickup falls inside this load's window (from
    its pickup day to its deadline); the truck does those first, so their driving counts. Hours needed = the chain
    truck -> each committed trip -> this load, real road times (data/routes.json) + handling; hours available =
    the days from pickup to deadline x DRIVING_HOURS_PER_DAY. A plan, not a promise: Python's arithmetic on the
    schedule the site knows."""
    if not load.get("deliver_by"):
        return None
    from datetime import date
    start, end = date.fromisoformat(load["pickup_date"]), date.fromisoformat(load["deliver_by"])
    trips = sorted(committed, key=lambda t: (t["pickup_date"], t["id"]))
    at, minutes, busy = vehicle_city, 0, []
    for t in trips + [load]:
        empty = approach_leg(at, t["origin_city"])
        loaded = approach_leg(t["origin_city"], t["destination_city"])
        if empty is None or loaded is None:
            return None
        minutes += empty["duration_minutes"] + loaded["duration_minutes"] + HANDLING_HOURS_PER_TRIP * 60
        at = t["destination_city"]
        if t is not load:
            busy.append({"load_id": t["id"], "origin_city": t["origin_city"],
                         "destination_city": t["destination_city"], "pickup_date": t["pickup_date"]})
    days = max(0, (end - start).days) + 1
    needed, available = round(minutes / 60, 1), days * DRIVING_HOURS_PER_DAY
    return {"deliver_by": load["deliver_by"], "on_time": needed <= available, "hours_needed": needed,
            "hours_available": available, "busy_with": busy,
            "assumption": f"{DRIVING_HOURS_PER_DAY} driving hours a day, {HANDLING_HOURS_PER_TRIP} h loading and "
                          "unloading per trip (simulated)"}


def rank_offers(load, offers):
    """A shipper's offers, recommended first: the lowest price among the drivers who can make the delivery deadline
    (offer["deadline"]["on_time"]; no deadline = everyone can); on a tie, the vehicle closer to the pickup. Offers
    that can't make it come last. Each offer needs price_gel and the vehicle's city."""
    rows = []
    for o in offers:
        leg = approach_leg(o["vehicle_city"], load["origin_city"])
        rows.append({**o, "km_to_pickup": leg["distance_km"] if leg else None,
                     "minutes_to_pickup": leg["duration_minutes"] if leg else None})
    late = lambda o: bool(o.get("deadline")) and not o["deadline"]["on_time"]   # noqa: E731
    rows.sort(key=lambda o: (late(o), o["price_gel"], o["km_to_pickup"] if o["km_to_pickup"] is not None else 1e9))
    return rows

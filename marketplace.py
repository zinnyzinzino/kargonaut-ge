"""The marketplace's rules, in Python: accounts, vehicles, loads, offers, bookings, and drafts.

Used by the website (server.py) and by the AI's tools (ai/shipper.py, ai/driver.py), so both follow the same
rules. Problems come back as {"error": <Georgian sentence for the user>, "error_code": ...}, never as exceptions.

Design principle (as in logimind-ai): the AI never writes. It can only make a DRAFT (draft_load, draft_offer);
the user's own click (confirm_draft, called by the site's Confirm button) saves it. Accepting an offer, booking,
cancelling and status changes are buttons only: the AI has no tool for them.
"""
import hashlib
import hmac
import json
import math
import re
import secrets
import uuid
from datetime import date, timedelta

import db
from core.geo import CITIES, CITY_KA, city, route
from core.matching import (best_vehicle_for_load, compatibility_issues, deadline_check, rank_loads_for_driver,
                           rank_offers)
from core.pricing import fair_price
from core.vehicles import TRUCK_LABEL, TRUCK_TYPES_TEXT, truck_type

ROLES = ("shipper", "driver")
LEGAL_STATUSES = ("person", "entrepreneur", "company")
LEGAL_STATUS_KA = {"person": "ფიზიკური პირი", "entrepreneur": "ინდ. მეწარმე", "company": "კომპანია"}
LOAD_STATUS_KA = {"open": "ღია", "booked": "დაჯავშნილი", "in_transit": "გზაში", "delivered": "მიტანილი",
                  "cancelled": "გაუქმებული"}
OFFER_STATUS_KA = {"pending": "მოლოდინში", "accepted": "მიღებული", "declined": "უარყოფილი",
                   "withdrawn": "გაუქმებული"}
VERDICT_KA = {"below_costs": "ხარჯებს ვერ ფარავს", "below_fair": "სამართლიან ფასზე დაბალია",
              "fair": "სამართლიანი ფასია", "above_fair": "სამართლიან ფასზე მაღალია"}
MAX_DAYS_AHEAD = 120
MIN_PASSWORD = 8


def refuse(code, message, **extra):
    return {"error": message, "error_code": code, **extra}


def _number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _flag(value):
    return 1 if value in (True, 1, "1", "true", "yes", "on", "კი") else 0


# ---------------------------------------------------------------- accounts


def normalize_phone(value):
    """Georgian mobile: '+995 555 12 34 56', '555-123-456' -> '555123456'; anything else -> None."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("995") and len(digits) == 12:
        digits = digits[3:]
    return digits if re.fullmatch(r"5\d{8}", digits) else None


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split("$")[2], digest)


def public_user(u, with_phone=False):
    view = {"id": u["id"], "role": u["role"], "name": u["name"], "city": u.get("city"),
            "city_label": CITY_KA.get(u.get("city"), u.get("city")), "legal_status": u["legal_status"],
            "legal_status_label": LEGAL_STATUS_KA[u["legal_status"]], "is_demo": bool(u.get("is_demo")),
            "rating": rating_summary(u["id"])}
    if with_phone:
        view["phone"] = u["phone"]
    return view


def register(role, name, phone, password, city_name="", legal_status="person", is_demo=False, vehicle=None):
    """A new account. A driver registers WITH their truck (vehicle: truck_type, capacity_kg, city, plate, and
    optionally fuel_l_per_100km, cost_per_km, liftgate, hazmat): both are saved together, or neither."""
    if role not in ROLES:
        return refuse("bad_role", "აირჩიეთ: ტვირთის გამგზავნი ან მძღოლი.")
    name = (name or "").strip()
    if len(name) < 2:
        return refuse("bad_name", "ჩაწერეთ სახელი.")
    number = normalize_phone(phone)
    if not number:
        return refuse("bad_phone", "ჩაწერეთ ქართული მობილურის ნომერი (5XX XX XX XX).")
    if len(password or "") < MIN_PASSWORD:
        return refuse("short_password", f"პაროლი უნდა იყოს მინიმუმ {MIN_PASSWORD} სიმბოლო.")
    if legal_status not in LEGAL_STATUSES:
        legal_status = "person"
    home = city(city_name) if city_name else None
    if db.one("SELECT id FROM users WHERE phone = ?", (number,)):
        return refuse("phone_taken", "ამ ნომრით ანგარიში უკვე არსებობს: შედით სისტემაში.")
    truck = None
    if role == "driver":
        truck, error = validate_vehicle(vehicle)
        if error:
            return error
    with db.connect() as conn:   # one transaction: no driver account without its truck
        user_id = conn.execute(
            "INSERT INTO users (role, name, phone, password_hash, city, legal_status, is_demo) VALUES (?,?,?,?,?,?,?)",
            (role, name, number, hash_password(password), home, legal_status, int(is_demo))).lastrowid
        if truck:
            _insert_vehicle(conn, user_id, truck)
    return public_user(get_user(user_id), with_phone=True)


def get_user(user_id):
    return db.one("SELECT * FROM users WHERE id = ?", (user_id,))


def login(phone, password):
    u = db.one("SELECT * FROM users WHERE phone = ?", (normalize_phone(phone) or "",))
    if not u or not check_password(password or "", u["password_hash"]):
        return refuse("bad_login", "ნომერი ან პაროლი არასწორია.")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, u["id"]))
    return {"token": token, "user": public_user(u, with_phone=True)}


def user_for_token(token):
    if not token:
        return None
    return db.one("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,))


def logout(token):
    db.execute("DELETE FROM sessions WHERE token = ?", (token or "",))


# ---------------------------------------------------------------- vehicles


def vehicle_view(v):
    return {**v, "liftgate": bool(v["liftgate"]), "hazmat": bool(v["hazmat"]), "available": bool(v["available"]),
            "truck_label": TRUCK_LABEL[v["truck_type"]], "city_label": CITY_KA[v["city"]]}


def normalize_plate(value):
    """'aa 123 bb', 'AA-123-BB' -> 'AA-123-BB' (Georgian format, two letters, three digits, two letters); other
    plates (older or special ones) are kept as typed, upper case. Empty or too short/long -> None."""
    text = re.sub(r"[\s\-]+", "", str(value or "")).upper()
    if re.fullmatch(r"[A-Z]{2}\d{3}[A-Z]{2}", text):
        return f"{text[:2]}-{text[2:5]}-{text[5:]}"
    return text if re.fullmatch(r"[A-Z0-9]{4,10}", text) else None


VEHICLE_FIELD_KA = {"truck_type": "მანქანის ტიპი", "capacity_kg": "ტვირთამწეობა", "city": "სად დგას",
                    "plate": "სახელმწიფო ნომერი"}
VEHICLE_SIZE_RANGE = {"length_m": (1, 16), "width_m": (1, 3), "height_m": (0.5, 4.5)}
VEHICLE_SIZE_KA = {"length_m": "ძარის სიგრძე", "width_m": "ძარის სიგანე", "height_m": "ძარის სიმაღლე"}


def validate_vehicle(values):
    """(clean values, None) or (None, error). The truck's type, capacity, city and plate are required: a driver's
    loads are chosen by them, and the plate is how a shipper recognises the truck."""
    v = dict(values or {})
    clean = {"truck_type": truck_type(v.get("truck_type")), "city": city(v.get("city")),
             "capacity_kg": _number(v.get("capacity_kg")), "plate": normalize_plate(v.get("plate"))}
    missing = [f for f in VEHICLE_FIELD_KA if not clean[f]]
    if missing:
        return None, refuse("vehicle_missing", "მანქანა: საჭიროა " + ", ".join(VEHICLE_FIELD_KA[f] for f in missing) + ".",
                            fields=missing)
    if not 100 <= clean["capacity_kg"] <= 40000:
        return None, refuse("bad_capacity", "ტვირთამწეობა კილოგრამებში: 100-დან 40 000-მდე.")
    if db.one("SELECT id FROM vehicles WHERE plate = ?", (clean["plate"],)):
        return None, refuse("plate_taken", f"მანქანა ნომრით {clean['plate']} უკვე დარეგისტრირებულია.")
    # The body's inside size (optional; a flatbed has no height). Out of range is refused, not guessed.
    for field, (low, high) in VEHICLE_SIZE_RANGE.items():
        x = _number(v.get(field))
        if x and not low <= x <= high:
            return None, refuse("bad_size", f"{VEHICLE_SIZE_KA[field]} მეტრებში: {low}-დან {high}-მდე.", fields=[field])
        clean[field] = round(x, 2) if x else None
    # Fuel use and wear aren't asked on the forms any more (27 Nov); the API still takes them, else the type's typical value
    fuel, wear = _number(v.get("fuel_l_per_100km")), _number(v.get("cost_per_km"))
    clean.update(capacity_kg=int(clean["capacity_kg"]), liftgate=_flag(v.get("liftgate")), hazmat=_flag(v.get("hazmat")),
                 fuel_l_per_100km=fuel if fuel and 3 <= fuel <= 80 else None,
                 cost_per_km=wear if wear and 0 < wear <= 5 else None)
    return clean, None


def _insert_vehicle(conn, driver_id, clean):
    return conn.execute(
        "INSERT INTO vehicles (driver_id, " + ", ".join(clean) + ") VALUES (?" + ",?" * len(clean) + ")",
        (driver_id, *clean.values())).lastrowid


def add_vehicle(driver_id, values):
    clean, error = validate_vehicle(values)
    if error:
        return error
    with db.connect() as conn:
        vehicle_id = _insert_vehicle(conn, driver_id, clean)
    return vehicle_view(db.one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)))


def free_vehicles():
    """For shippers: every truck its driver marked free and that isn't on a booked or running trip, with the
    driver's name, phone and rating, so a shipper can call. Drivers are told on the form that this is shown."""
    rows = db.rows(
        "SELECT v.*, u.name AS driver_name, u.phone AS driver_phone, u.is_demo AS driver_is_demo FROM vehicles v"
        " JOIN users u ON u.id = v.driver_id WHERE v.available = 1 AND NOT EXISTS (SELECT 1 FROM loads l"
        " WHERE l.vehicle_id = v.id AND l.status IN ('booked', 'in_transit')) ORDER BY v.city, v.capacity_kg DESC")
    keep = ("id", "truck_type", "truck_label", "capacity_kg", "city", "city_label", "plate", "liftgate", "hazmat",
            "length_m", "width_m", "height_m", "driver_name", "driver_phone")
    return [{**{k: view[k] for k in keep}, "driver_is_demo": bool(r["driver_is_demo"]),
             "driver_rating": rating_summary(r["driver_id"])}
            for r in rows for view in [vehicle_view(r)]]


def vehicles_of(driver_id, only_available=False):
    sql = "SELECT * FROM vehicles WHERE driver_id = ?" + (" AND available = 1" if only_available else "")
    return [vehicle_view(v) for v in db.rows(sql + " ORDER BY id", (driver_id,))]


def update_vehicle(driver_id, vehicle_id, city_name=None, available=None):
    v = db.one("SELECT * FROM vehicles WHERE id = ? AND driver_id = ?", (vehicle_id, driver_id))
    if not v:
        return refuse("not_your_vehicle", "ასეთი მანქანა თქვენს ანგარიშზე არ არის.")
    if city_name is not None:
        where = city(city_name)
        if not where:
            return refuse("bad_city", "აირჩიეთ ქალაქი.")
        db.execute("UPDATE vehicles SET city = ? WHERE id = ?", (where, vehicle_id))
    if available is not None:
        db.execute("UPDATE vehicles SET available = ? WHERE id = ?", (_flag(available), vehicle_id))
    return vehicle_view(db.one("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)))


# ---------------------------------------------------------------- loads

LOAD_REQUIRED = ("origin_city", "destination_city", "truck_type", "weight_kg", "pickup_date", "price_gel")
LOAD_FIELD_KA = {"origin_city": "საიდან", "destination_city": "სადამდე", "truck_type": "მანქანის ტიპი",
                 "weight_kg": "წონა (კგ)", "pickup_date": "აღების თარიღი", "price_gel": "ფასი (₾)"}


def validate_load(values):
    """(clean values, None) or (None, error dict). Missing required values -> error_code "missing" + fields."""
    v = dict(values or {})
    clean = {
        "origin_city": city(v.get("origin_city")), "destination_city": city(v.get("destination_city")),
        "truck_type": truck_type(v.get("truck_type")), "weight_kg": _number(v.get("weight_kg")),
        "pickup_date": str(v.get("pickup_date") or "").strip() or None, "price_gel": _number(v.get("price_gel")),
        "deliver_by": str(v.get("deliver_by") or "").strip() or None,
        "cargo": (v.get("cargo") or "").strip()[:200] or None,
        "pieces": int(_number(v.get("pieces")) or 0) or None,
        "pickup_address": (v.get("pickup_address") or "").strip()[:200] or None,
        "delivery_address": (v.get("delivery_address") or "").strip()[:200] or None,
        "needs_liftgate": _flag(v.get("needs_liftgate")), "hazmat": _flag(v.get("hazmat")),
        "notes": (v.get("notes") or "").strip()[:500] or None,
        "reference": (v.get("reference") or "").strip()[:60] or None,
    }
    for key, raw in (("origin_city", v.get("origin_city")), ("destination_city", v.get("destination_city"))):
        if raw and not clean[key]:
            return None, refuse("unknown_city", f"„{raw}“ ჩვენს ქალაქებში არ არის. ქალაქები: "
                                + ", ".join(CITY_KA[c] for c in CITIES) + ".", field=key)
    if v.get("truck_type") and not clean["truck_type"]:
        return None, refuse("bad_truck_type", f"უცნობი ტიპი. აირჩიეთ: {TRUCK_TYPES_TEXT}.", field="truck_type")
    missing = [f for f in LOAD_REQUIRED if not clean[f]]
    if missing:
        return None, refuse("missing", "საჭიროა: " + ", ".join(LOAD_FIELD_KA[f] for f in missing) + ".",
                            fields=missing)
    if clean["origin_city"] == clean["destination_city"]:
        return None, refuse("same_city", "აღება და მიტანა ერთ ქალაქშია: ქალაქშიდა გადაზიდვები ჯერ არ გვაქვს.")
    if clean["weight_kg"] <= 0 or clean["price_gel"] <= 0:
        return None, refuse("not_positive", "წონა და ფასი ნულზე მეტი უნდა იყოს.")
    try:
        pickup = date.fromisoformat(clean["pickup_date"])
    except ValueError:
        return None, refuse("bad_date", "თარიღი ჩაწერეთ ასე: 2026-12-05.", field="pickup_date")
    if pickup < date.today():
        return None, refuse("past_date", "აღების თარიღი უკვე გავიდა.", field="pickup_date")
    if pickup > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        return None, refuse("far_date", f"აღების თარიღი მაქსიმუმ {MAX_DAYS_AHEAD} დღით წინ.", field="pickup_date")
    if clean["deliver_by"]:
        try:
            deadline = date.fromisoformat(clean["deliver_by"])
        except ValueError:
            return None, refuse("bad_date", "მიტანის ვადა ჩაწერეთ ასე: 2026-12-05.", field="deliver_by")
        if deadline < pickup:
            return None, refuse("deadline_before_pickup", "მიტანის ვადა აღების დღეზე ადრე ვერ იქნება.", field="deliver_by")
    clean["weight_kg"] = int(round(clean["weight_kg"]))
    clean["price_gel"] = round(clean["price_gel"], 2)
    return clean, None


def price_check(load):
    """The load's price against the fair range (core/pricing.py), with a Georgian verdict."""
    r = fair_price(load["origin_city"], load["destination_city"], load["truck_type"], load["weight_kg"],
                   load["price_gel"])
    if "error" in r:
        return None
    return {"fair_price_range_gel": r["fair_price_range_gel"], "verdict": r["verdict"],
            "verdict_label": VERDICT_KA.get(r["verdict"]), "loaded_km": r["loaded_km"],
            "too_heavy_for_typical_vehicle": r["too_heavy_for_typical_vehicle"],
            "typical_capacity_kg": r["typical_capacity_kg"]}


def load_view(load, viewer=None):
    """A load as users see it. Phone numbers are shared only between the two sides of a booking."""
    view = {**load, "needs_liftgate": bool(load["needs_liftgate"]), "hazmat": bool(load["hazmat"]),
            "origin_label": CITY_KA[load["origin_city"]], "destination_label": CITY_KA[load["destination_city"]],
            "truck_label": TRUCK_LABEL[load["truck_type"]], "status_label": LOAD_STATUS_KA[load["status"]],
            "loaded_km": (route(load["origin_city"], load["destination_city"]) or {}).get("distance_km")}
    booked = load["status"] in ("booked", "in_transit", "delivered")
    if viewer and booked and viewer["id"] == load["shipper_id"] and load.get("driver_id"):
        view["driver"] = public_user(get_user(load["driver_id"]), with_phone=True)
        v = db.one("SELECT * FROM vehicles WHERE id = ?", (load["vehicle_id"],))
        if v:
            view["vehicle"] = {"truck_label": TRUCK_LABEL[v["truck_type"]], "plate": v["plate"],
                               "capacity_kg": v["capacity_kg"]}
    if viewer and booked and viewer["id"] == load.get("driver_id"):
        view["shipper"] = public_user(get_user(load["shipper_id"]), with_phone=True)
    if viewer and load["status"] == "delivered" and viewer["id"] in (load["shipper_id"], load.get("driver_id")):
        given = db.one("SELECT stars, comment FROM ratings WHERE load_id = ? AND from_user = ?", (load["id"], viewer["id"]))
        view["my_rating"] = given            # what this user gave the other side (None: not yet)
        view["can_rate"] = given is None
        view["pod"] = pod_view(load["id"])
    if viewer and load["status"] in ("in_transit", "delivered") and viewer["id"] in (load["shipper_id"], load.get("driver_id")):
        view["waybill"] = waybill_view(load["id"])   # what was handed over at pickup
    return view


def create_load(shipper_id, values):
    clean, error = validate_load(values)
    if error:
        return error
    load_id = db.execute(
        "INSERT INTO loads (shipper_id, " + ", ".join(clean) + ") VALUES (?" + ",?" * len(clean) + ")",
        (shipper_id, *clean.values()))
    return load_view(get_load(load_id))


def get_load(load_id):
    return db.one("SELECT * FROM loads WHERE id = ?", (load_id,))


def loads_of_shipper(shipper_id, status=""):
    sql, args = "SELECT * FROM loads WHERE shipper_id = ?", [shipper_id]
    if status:
        sql, args = sql + " AND status = ?", args + [status]
    viewer = get_user(shipper_id)
    result = []
    for load in db.rows(sql + " ORDER BY pickup_date, id", args):
        view = load_view(load, viewer)
        offers = db.one("SELECT COUNT(*) AS n, MIN(price_gel) AS best FROM offers WHERE load_id = ? AND status = 'pending'",
                        (load["id"],))
        view["pending_offers"], view["best_offer_gel"] = offers["n"], offers["best"]
        view["price_check"] = price_check(load) if load["status"] == "open" else None
        result.append(view)
    return result


def open_loads():
    return db.rows("SELECT * FROM loads WHERE status = 'open' AND pickup_date >= ? ORDER BY pickup_date, id",
                   (date.today().isoformat(),))


def loads_for_driver(driver_id, start_city=None, heading_to=None, limit=20):
    """Open loads this driver's available vehicles can carry, ranked by what the driver keeps (core/matching.py)."""
    vehicles = vehicles_of(driver_id, only_available=True)
    if not vehicles:
        return refuse("no_vehicle", "ჯერ დაამატეთ თავისუფალი მანქანა: ტვირთებს მისი ტიპით და ადგილით ვარჩევთ.")
    start = city(start_city) if start_city else None
    heading = city(heading_to) if heading_to else None
    offered = {r["load_id"]: r for r in db.rows(
        "SELECT load_id, id, price_gel FROM offers WHERE driver_id = ? AND status = 'pending'", (driver_id,))}
    ranked = rank_loads_for_driver(vehicles, open_loads(), start, heading)
    rows = []
    for r in ranked[:limit]:
        view = load_view(r["load"])
        mine = offered.get(r["load"]["id"])
        rows.append({"load": view, "vehicle_id": r["vehicle_id"], "earnings": r["earnings"],
                     "shipper_rating": rating_summary(r["load"]["shipper_id"]),
                     "my_offer": {"offer_id": mine["id"], "price_gel": mine["price_gel"]} if mine else None})
    return {"total": len(ranked), "loads": rows, "start_city": start, "heading_to": heading}


def cancel_load(shipper_id, load_id):
    load = get_load(load_id)
    if not load or load["shipper_id"] != shipper_id:
        return refuse("not_your_load", "ასეთი ტვირთი თქვენს ანგარიშზე არ არის.")
    if load["status"] != "open":
        return refuse("not_open", "დაჯავშნილი ტვირთის გაუქმება მძღოლთან შეთანხმებით ხდება.")
    with db.connect() as conn:
        conn.execute("UPDATE loads SET status = 'cancelled' WHERE id = ?", (load_id,))
        conn.execute("UPDATE offers SET status = 'declined' WHERE load_id = ? AND status = 'pending'", (load_id,))
    return load_view(get_load(load_id))


# ---------------------------------------------------------------- offers and bookings


def validate_offer(driver_id, values):
    load = get_load(int(_number(values.get("load_id")) or 0))
    if not load or load["status"] != "open":
        return None, refuse("load_not_open", "ეს ტვირთი აღარ არის ღია.")
    price = _number(values.get("price_gel")) or load["price_gel"]   # no price: the shipper's own price
    if price <= 0:
        return None, refuse("not_positive", "ფასი ნულზე მეტი უნდა იყოს.")
    vehicles = vehicles_of(driver_id, only_available=True)
    vehicle_id = int(_number(values.get("vehicle_id")) or 0)
    if vehicle_id:
        vehicle = next((v for v in vehicles if v["id"] == vehicle_id), None)
        if vehicle is None:
            return None, refuse("not_your_vehicle", "ასეთი თავისუფალი მანქანა თქვენს ანგარიშზე არ არის.")
        issues = compatibility_issues(vehicle, load)
        if issues:
            return None, refuse("vehicle_cannot", "ეს მანქანა ამ ტვირთს ვერ წაიღებს: " + "; ".join(issues) + ".",
                                issues=issues)
    else:   # the vehicle that keeps the driver the most on this load
        best, _ = best_vehicle_for_load(vehicles, load)
        if best is None:
            return None, refuse("no_vehicle_fits", "თქვენი არცერთი თავისუფალი მანქანა ამ ტვირთს ვერ წაიღებს.")
        vehicle = best[0]
    return {"load": load, "vehicle": vehicle, "price_gel": round(price, 2),
            "message": (values.get("message") or "").strip()[:300] or None}, None


def make_offer(driver_id, values):
    """A driver's offer on an open load. A second offer on the same load replaces the first."""
    clean, error = validate_offer(driver_id, values)
    if error:
        return error
    with db.connect() as conn:
        conn.execute("UPDATE offers SET status = 'withdrawn' WHERE load_id = ? AND driver_id = ? AND status = 'pending'",
                     (clean["load"]["id"], driver_id))
        offer_id = conn.execute(
            "INSERT INTO offers (load_id, driver_id, vehicle_id, price_gel, message) VALUES (?,?,?,?,?)",
            (clean["load"]["id"], driver_id, clean["vehicle"]["id"], clean["price_gel"], clean["message"])).lastrowid
    return offer_view(db.one("SELECT * FROM offers WHERE id = ?", (offer_id,)))


def offer_view(o):
    return {**o, "status_label": OFFER_STATUS_KA[o["status"]]}


def offers_for_load(shipper_id, load_id):
    """The pending offers on a shipper's load, recommended first (core/matching.py rank_offers)."""
    load = get_load(load_id)
    if not load or load["shipper_id"] != shipper_id:
        return refuse("not_your_load", "ასეთი ტვირთი თქვენს ანგარიშზე არ არის.")
    raw = db.rows(
        "SELECT o.*, u.name AS driver_name, u.legal_status, u.is_demo, v.truck_type, v.capacity_kg, "
        "v.city AS vehicle_city, v.plate FROM offers o JOIN users u ON u.id = o.driver_id "
        "JOIN vehicles v ON v.id = o.vehicle_id WHERE o.load_id = ? AND o.status = 'pending'", (load_id,))
    check = price_check({**load})
    for o in raw:   # with a deadline: can this truck make it, given the trips it's already booked for?
        o["deadline"] = deadline_check(load, o["vehicle_city"], committed_trips(o["vehicle_id"], load))
    ranked = []
    for o in rank_offers(load, raw):
        verdict = price_check({**load, "price_gel": o["price_gel"]})
        ranked.append({**offer_view(o), "truck_label": TRUCK_LABEL[o["truck_type"]],
                       "vehicle_city_label": CITY_KA[o["vehicle_city"]],
                       "legal_status_label": LEGAL_STATUS_KA[o["legal_status"]],
                       "driver_rating": rating_summary(o["driver_id"]),
                       "price_verdict": verdict["verdict"] if verdict else None,
                       "price_verdict_label": verdict["verdict_label"] if verdict else None})
    best = ranked[0] if ranked else None
    return {"load": load_view(load), "price_check": check, "offers": ranked,
            "recommended_offer_id": best["id"] if best else None,
            "no_offer_makes_the_deadline": bool(best and best["deadline"] and not best["deadline"]["on_time"]),
            "ranking_rule": ("lowest price among the drivers who can deliver by the deadline (their truck's other "
                             "booked trips + this one fit the driving hours before deliver_by); on a tie, the vehicle "
                             "closer to the pickup" if load.get("deliver_by") else
                             "lowest price first; on a tie, the vehicle closer to the pickup")}


def committed_trips(vehicle_id, load):
    """The truck's trips already booked or on the road inside this load's window (its pickup day .. deadline):
    the truck must do those too. Trips on the road count whatever their date."""
    if not load.get("deliver_by"):
        return []
    return db.rows("SELECT id, origin_city, destination_city, pickup_date FROM loads WHERE vehicle_id = ? AND id != ? "
                   "AND (status = 'in_transit' OR (status = 'booked' AND pickup_date BETWEEN ? AND ?))",
                   (vehicle_id, load["id"], load["pickup_date"], load["deliver_by"]))


def accept_offer(shipper_id, offer_id):
    """The shipper books a driver: a button on the site, never the AI."""
    offer = db.one("SELECT * FROM offers WHERE id = ?", (offer_id,))
    load = get_load(offer["load_id"]) if offer else None
    if not load or load["shipper_id"] != shipper_id:
        return refuse("not_your_load", "ეს შეთავაზება თქვენს ტვირთს არ ეკუთვნის.")
    if load["status"] != "open" or offer["status"] != "pending":
        return refuse("not_open", "ეს შეთავაზება აღარ არის აქტიური.")
    with db.connect() as conn:
        conn.execute("UPDATE offers SET status = 'accepted' WHERE id = ?", (offer_id,))
        conn.execute("UPDATE offers SET status = 'declined' WHERE load_id = ? AND id != ? AND status = 'pending'",
                     (load["id"], offer_id))
        conn.execute("UPDATE loads SET status = 'booked', driver_id = ?, vehicle_id = ?, agreed_price_gel = ?, "
                     "booked_at = datetime('now') WHERE id = ?",
                     (offer["driver_id"], offer["vehicle_id"], offer["price_gel"], load["id"]))
    return load_view(get_load(load["id"]), get_user(shipper_id))


def withdraw_offer(driver_id, offer_id):
    offer = db.one("SELECT * FROM offers WHERE id = ? AND driver_id = ?", (offer_id, driver_id))
    if not offer or offer["status"] != "pending":
        return refuse("not_open", "ეს შეთავაზება აღარ არის აქტიური.")
    db.execute("UPDATE offers SET status = 'withdrawn' WHERE id = ?", (offer_id,))
    return offer_view(db.one("SELECT * FROM offers WHERE id = ?", (offer_id,)))


def jobs_of_driver(driver_id):
    """The driver's booked loads and pending offers."""
    viewer = get_user(driver_id)
    jobs = [load_view(load, viewer) for load in db.rows(
        "SELECT * FROM loads WHERE driver_id = ? ORDER BY pickup_date, id", (driver_id,))]
    offers = []
    for o in db.rows("SELECT * FROM offers WHERE driver_id = ? AND status = 'pending' ORDER BY id", (driver_id,)):
        offers.append({**offer_view(o), "load": load_view(get_load(o["load_id"]))})
    return {"jobs": jobs, "pending_offers": offers}


# ---------------------------------------------------------------- ratings (after delivery, each side rates the other)


def rating_summary(user_id):
    """{"average": 4.6, "count": 5} from the ratings this user received; average None while there are none."""
    r = db.one("SELECT AVG(stars) AS avg, COUNT(*) AS n FROM ratings WHERE to_user = ?", (user_id,))
    return {"average": round(r["avg"], 1) if r["n"] else None, "count": r["n"]}


def rate(user_id, load_id, stars, comment=""):
    """The shipper rates the driver of a delivered load, or the driver rates the shipper. Once per side per load."""
    load = get_load(load_id)
    if not load or user_id not in (load["shipper_id"], load.get("driver_id")):
        return refuse("not_your_load", "ეს ტვირთი თქვენს ანგარიშზე არ არის.")
    if load["status"] != "delivered":
        return refuse("not_delivered", "შეფასება შესაძლებელია მხოლოდ მიტანის შემდეგ.")
    n = _number(stars)
    if n is None or int(n) != n or not 1 <= n <= 5:
        return refuse("bad_stars", "შეფასება: 1-დან 5 ვარსკვლავამდე.")
    if db.one("SELECT id FROM ratings WHERE load_id = ? AND from_user = ?", (load_id, user_id)):
        return refuse("already_rated", "ეს რეისი უკვე შეაფასეთ.")
    other = load["driver_id"] if user_id == load["shipper_id"] else load["shipper_id"]
    db.execute("INSERT INTO ratings (load_id, from_user, to_user, stars, comment) VALUES (?,?,?,?,?)",
               (load_id, user_id, other, int(n), (comment or "").strip()[:300] or None))
    return {"ok": True, "load_id": load_id, "stars": int(n), "rated_user": rating_summary(other)}


# ---------------------------------------------------------------- the transport order (გადაზიდვის შეკვეთა)


def order_number(load_id):
    return f"KG-{int(load_id):06d}"


def order_data(user_id, load_id):
    """Everything the transport order shows, for the load's shipper and driver only, once a driver is booked.
    Georgian freight has no standard rate-confirmation form, so the platform writes the agreement itself from what
    both sides agreed on it (transport_order.py renders it)."""
    load = get_load(load_id)
    if not load or user_id not in (load["shipper_id"], load.get("driver_id")):
        return refuse("not_your_load", "ეს ტვირთი თქვენს ანგარიშზე არ არის.")
    if load["status"] not in ("booked", "in_transit", "delivered"):
        return refuse("not_booked", "გადაზიდვის შეკვეთა მზადდება მას შემდეგ, რაც გამგზავნი შეთავაზებას მიიღებს.")
    shipper, driver = get_user(load["shipper_id"]), get_user(load["driver_id"])
    vehicle = db.one("SELECT * FROM vehicles WHERE id = ?", (load["vehicle_id"],))
    return {
        "number": order_number(load_id),
        "date": (load.get("booked_at") or load["created_at"])[:10],
        "load": load_view(load),
        "shipper": public_user(shipper, with_phone=True),
        "driver": public_user(driver, with_phone=True),
        "vehicle": vehicle_view(vehicle) if vehicle else None,
        "simulated": bool(shipper.get("is_demo") or driver.get("is_demo")),
    }


# ---------------------------------------------------------------- proof of delivery


def pod_view(load_id):
    """What both sides see about a delivered load's proof of delivery, or None."""
    p = db.one("SELECT * FROM pods WHERE load_id = ?", (load_id,))
    if not p:
        return None
    doc = json.loads(p["document"] or "null") or {}
    receiver = (doc.get("signatures") or {}).get("receiver") or {}
    findings = json.loads(p["findings"] or "[]")
    return {"file_name": p["file_name"], "uploaded_at": p["created_at"], "kind": doc.get("kind"),
            "receiver_signed": receiver.get("signed"), "receiver_name": receiver.get("name"),
            "delivery_address": (doc.get("delivery") or {}).get("address"),
            "delivery_date": (doc.get("delivery") or {}).get("date"),
            "problems": [f for f in findings if f.get("severity") == "problem"],
            "notes": [f for f in findings if f.get("severity") != "problem"],
            "read": bool(doc)}


def pod_check_city(load, document):
    """Python's own check (the paperwork agent reads; Python compares): the city on the proof of delivery must be the
    load's delivery city. A finding in the paperwork format, or None."""
    from paperwork.draft import _city
    printed = _city(document.get("delivery") or {}) if document else None
    if printed and printed != load["destination_city"]:
        return {"check": "pod_city_mismatch", "severity": "problem", "documents": [document.get("name")],
                "detail": f"მიტანის დადასტურებაზე ქალაქია {CITY_KA[printed]}, ტვირთი კი {CITY_KA[load['destination_city']]}-ში "
                          f"უნდა მისულიყო.",
                "action": "გადაამოწმეთ მძღოლთან: სწორი დოკუმენტი ატვირთა?"}
    return None


def deliver_with_pod(driver_id, load_id, file_name, stored_path, document, findings):
    """The driver's „მივიტანე“: only with a proof of delivery. Saves the paper and what was read, then marks the
    load delivered. Problems found on the paper don't block it: both sides see them, with what to do."""
    load = get_load(load_id)
    if not load or load.get("driver_id") != driver_id:
        return refuse("not_your_job", "ეს ტვირთი თქვენზე არ არის დაჯავშნილი.")
    if load["status"] != "in_transit":
        return refuse("not_in_transit", "მიტანა შესაძლებელია მხოლოდ მას შემდეგ, რაც ტვირთს აიღებთ („ავიღე ტვირთი“).")
    city_problem = pod_check_city(load, document)
    findings = list(findings or []) + ([city_problem] if city_problem else [])
    with db.connect() as conn:
        conn.execute("INSERT INTO pods (load_id, driver_id, file_name, stored_path, document, findings) VALUES (?,?,?,?,?,?)",
                     (load_id, driver_id, file_name, stored_path, json.dumps(document, ensure_ascii=False) if document else None,
                      json.dumps(findings, ensure_ascii=False)))
        conn.execute("UPDATE loads SET status = 'delivered' WHERE id = ?", (load_id,))
        conn.execute("UPDATE vehicles SET city = ? WHERE id = ?", (load["destination_city"], load["vehicle_id"]))
    return {**load_view(get_load(load_id), get_user(driver_id)), "pod": pod_view(load_id)}


def pod_file(user_id, load_id):
    """(path, file name) of a load's proof of delivery, for its shipper and driver only."""
    load = get_load(load_id)
    p = db.one("SELECT * FROM pods WHERE load_id = ?", (load_id,))
    if not load or not p or user_id not in (load["shipper_id"], load.get("driver_id")):
        return None
    return p["stored_path"], p["file_name"]


# ---------------------------------------------------------------- the waybill at pickup (სასაქონლო ზედნადები)

PLATE_GE = re.compile(r"[A-Z]{2}-\d{3}-[A-Z]{2}")


def waybill_check(load, vehicle, document):
    """Python compares the waybill the AI read with the booked load: the truck's plate, the pickup and delivery
    cities, the weight. Findings in the paperwork format (problems are shown, they don't block the pickup)."""
    from paperwork.draft import _city
    if not document:
        return []
    name, out = [document.get("name")], []

    def problem(check, detail, action):
        out.append({"check": check, "severity": "problem", "documents": name, "detail": detail, "action": action})

    plates = {normalize_plate(v) for v in (document.get("references") or {}).values() if isinstance(v, str)}
    plates = {p for p in plates if p and PLATE_GE.fullmatch(p)}
    if vehicle and vehicle.get("plate") and plates and vehicle["plate"] not in plates:
        problem("waybill_plate_mismatch",
                f"ზედნადებზე მანქანის ნომერია {', '.join(sorted(plates))}, ტვირთი კი დაჯავშნილია მანქანაზე {vehicle['plate']}.",
                "ზედნადები უნდა იყოს გამოწერილი იმ მანქანაზე, რომელიც ტვირთს ვეზის: სთხოვეთ გამგზავნს, შეასწოროს.")
    elif vehicle and vehicle.get("plate") and not plates:
        out.append({"check": "waybill_plate_not_found", "severity": "note", "documents": name, "action": None,
                    "detail": "ზედნადებზე მანქანის სახელმწიფო ნომერი ვერ ვიპოვეთ: გადაამოწმეთ ხელით."})
    for stop, want, word in (("pickup", load["origin_city"], "აღების"), ("delivery", load["destination_city"], "მიტანის")):
        printed = _city(document.get(stop) or {})
        if printed and printed != want:
            problem(f"waybill_{stop}_city_mismatch",
                    f"ზედნადებზე {word} ქალაქია {CITY_KA[printed]}, ტვირთში კი {CITY_KA[want]}.",
                    "გადაამოწმეთ: ეს ზედნადები ამ ტვირთისაა?")
    weight = document.get("weight")
    if weight and document.get("weight_unit") in ("kg", "t", "lb"):
        kg = weight * {"kg": 1, "t": 1000, "lb": 0.4536}[document["weight_unit"]]
        if abs(kg - load["weight_kg"]) > 0.1 * load["weight_kg"]:
            problem("waybill_weight_mismatch",
                    f"ზედნადებზე წონაა {round(kg):,} კგ, ტვირთში კი {load['weight_kg']:,} კგ.".replace(",", " "),
                    "წონა ფასს და მანქანის ტვირთამწეობას ცვლის: შეუთანხმდით გამგზავნს, სანამ გაემგზავრებით.")
    return out


def waybill_view(load_id):
    """What both sides see about the pickup's waybill, or None (picked up before the waybill step existed)."""
    w = db.one("SELECT * FROM waybills WHERE load_id = ?", (load_id,))
    if not w:
        return None
    doc = json.loads(w["document"] or "null") or {}
    findings = json.loads(w["findings"] or "[]")
    refs = doc.get("references") or {}
    number = next((v for k, v in refs.items() if "№" in k), None)   # the waybill's own number ("№ 0412378915")
    plate = next((p for p in (normalize_plate(v) for v in refs.values() if isinstance(v, str)) if p and PLATE_GE.fullmatch(p)), None)
    return {"none_issued": bool(w["none_issued"]), "file_name": w["file_name"], "uploaded_at": w["created_at"],
            "read": bool(doc), "number": number, "plate": plate,
            "pickup_address": (doc.get("pickup") or {}).get("address"), "weight": doc.get("weight"),
            "weight_unit": doc.get("weight_unit"),
            "problems": [f for f in findings if f.get("severity") == "problem"],
            "notes": [f for f in findings if f.get("severity") != "problem"]}


def pickup_with_waybill(driver_id, load_id, file_name=None, stored_path=None, document=None, findings=None,
                        none_issued=False):
    """The driver's „ავიღე ტვირთი“: with the waybill's photo, or saying none was issued (goods of a private person).
    Saves what was read and Python's comparison, then the load is on the road. Problems don't block the pickup:
    both sides see them, with what to do."""
    load = get_load(load_id)
    if not load or load.get("driver_id") != driver_id:
        return refuse("not_your_job", "ეს ტვირთი თქვენზე არ არის დაჯავშნილი.")
    if load["status"] != "booked":
        return refuse("not_booked", "ტვირთის აღება შესაძლებელია მხოლოდ დაჯავშნილ ტვირთზე.")
    if not none_issued and not stored_path:
        return refuse("waybill_required", "ატვირთეთ ზედნადების ფოტო ან მონიშნეთ, რომ ზედნადები არ გაცემულა.")
    vehicle = db.one("SELECT * FROM vehicles WHERE id = ?", (load["vehicle_id"],))
    findings = [] if none_issued else list(findings or []) + waybill_check(load, vehicle, document)
    with db.connect() as conn:
        conn.execute("INSERT INTO waybills (load_id, driver_id, none_issued, file_name, stored_path, document, findings)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (load_id, driver_id, int(bool(none_issued)), file_name, stored_path,
                      json.dumps(document, ensure_ascii=False) if document else None, json.dumps(findings, ensure_ascii=False)))
        conn.execute("UPDATE loads SET status = 'in_transit' WHERE id = ?", (load_id,))
    return {**load_view(get_load(load_id), get_user(driver_id)), "waybill": waybill_view(load_id)}


def waybill_file(user_id, load_id):
    """(path, file name) of a load's waybill photo, for its shipper and driver only."""
    load = get_load(load_id)
    w = db.one("SELECT * FROM waybills WHERE load_id = ?", (load_id,))
    if not load or not w or not w["stored_path"] or user_id not in (load["shipper_id"], load.get("driver_id")):
        return None
    return w["stored_path"], w["file_name"]


NEXT_STATUS = {"booked": "in_transit"}   # in_transit -> delivered only with a proof of delivery (deliver_with_pod)


def advance_job(driver_id, load_id):
    """booked -> in_transit (picked up). Delivered needs a proof of delivery: deliver_with_pod."""
    load = get_load(load_id)
    if not load or load.get("driver_id") != driver_id:
        return refuse("not_your_job", "ეს ტვირთი თქვენზე არ არის დაჯავშნილი.")
    if load["status"] == "in_transit":
        return refuse("pod_required", "მისატანად ატვირთეთ ხელმოწერილი დოკუმენტის ფოტო (ზედნადები ან მიღება-ჩაბარების აქტი).")
    nxt = NEXT_STATUS.get(load["status"])
    if not nxt:
        return refuse("finished", "ეს ტვირთი უკვე მიტანილია.")
    db.execute("UPDATE loads SET status = ? WHERE id = ?", (nxt, load_id))
    if nxt == "delivered":   # the vehicle is now in the delivery city
        db.execute("UPDATE vehicles SET city = ? WHERE id = ?", (load["destination_city"], load["vehicle_id"]))
    return load_view(get_load(load_id), get_user(driver_id))


# ---------------------------------------------------------------- drafts (what the AI and document reading make)

DRAFTS = {}   # draft_id -> {"kind", "user_id", "values"}: in memory, lost on restart (like logimind-ai's)


def _store_draft(kind, user_id, values, replaces=""):
    if replaces and DRAFTS.get(replaces, {}).get("user_id") == user_id:
        DRAFTS.pop(replaces)
    draft_id = uuid.uuid4().hex[:10]
    DRAFTS[draft_id] = {"kind": kind, "user_id": user_id, "values": values}
    while len(DRAFTS) > 500:
        DRAFTS.pop(next(iter(DRAFTS)))
    return draft_id


def draft_load(shipper_id, values, replaces=""):
    """A load DRAFT: checked like a real load, priced against the fair range, NOT saved."""
    clean, error = validate_load(values)
    if error:
        return error
    draft_id = _store_draft("load", shipper_id, clean, replaces)
    view = {**clean, "origin_label": CITY_KA[clean["origin_city"]],
            "destination_label": CITY_KA[clean["destination_city"]], "truck_label": TRUCK_LABEL[clean["truck_type"]]}
    return {"draft_id": draft_id, "kind": "load", "draft": view, "price_check": price_check(clean),
            "saved": False, "how_to_save": "the user must press Confirm (დადასტურება) on the draft card"}


def draft_offer(driver_id, values, replaces=""):
    """An offer DRAFT: checked like a real offer, with what the driver would keep, NOT sent."""
    from core.pricing import driver_earnings
    clean, error = validate_offer(driver_id, values)
    if error:
        return error
    load, vehicle = clean["load"], clean["vehicle"]
    earnings = driver_earnings(vehicle, vehicle["city"], load["origin_city"], load["destination_city"],
                               clean["price_gel"])
    draft_id = _store_draft("offer", driver_id, {"load_id": load["id"], "vehicle_id": vehicle["id"],
                                                 "price_gel": clean["price_gel"], "message": clean["message"]},
                            replaces)
    return {"draft_id": draft_id, "kind": "offer", "draft": {
                "load_id": load["id"], "route": f"{CITY_KA[load['origin_city']]} → {CITY_KA[load['destination_city']]}",
                "pickup_date": load["pickup_date"], "vehicle_id": vehicle["id"], "truck_label": vehicle["truck_label"],
                "price_gel": clean["price_gel"], "shipper_price_gel": load["price_gel"], "message": clean["message"]},
            "earnings": earnings, "saved": False,
            "how_to_save": "the driver must press Confirm (დადასტურება) on the draft card to send the offer"}


def confirm_draft(user_id, draft_id):
    """The user's Confirm button: the ONLY way a draft becomes a load or an offer."""
    draft = DRAFTS.get(draft_id)
    if not draft or draft["user_id"] != user_id:
        return refuse("draft_gone", "ეს მონახაზი აღარ არსებობს (სერვერი გადაიტვირთა?): სცადეთ თავიდან.")
    result = (create_load(user_id, draft["values"]) if draft["kind"] == "load"
              else make_offer(user_id, draft["values"]))
    if "error" not in result:
        DRAFTS.pop(draft_id, None)
    return {"kind": draft["kind"], **result}


def reject_draft(user_id, draft_id):
    draft = DRAFTS.get(draft_id)
    if draft and draft["user_id"] == user_id:
        DRAFTS.pop(draft_id)
    return {"ok": True}

"""Turn a read rate confirmation into a DRAFT new load (pure Python, no AI). The dispatcher confirms it.

`plan_draft` (a LangGraph node, after cross_check) decides from the documents and the findings whether a
draft can be made, and maps the RC's values to a new load's fields:

    pickup / delivery city  <- the city in the RC's addresses (one of our 8, Georgian or English)
    truck type              <- the RC's "Equipment" ("Refrigerated", "Dry van", "Van", "Reefer", ...)
    weight_kg               <- the weight, only when its unit is printed (lb is converted, no unit = missing)
    customer_price_gel      <- the rate, only when it is in GEL
    pickup / delivery date  <- the RC's dates; cargo, pieces, packaging, broker as customer

Nothing is guessed: a value that can't be mapped goes into "missing" and the dispatcher types it. A draft is
refused ("blocked") when making one would be wrong: the RC names another carrier, the load is already
delivered (a POD is among the documents), a city is not one of ours, the rate isn't in GEL, or this broker
load number is already a load. `create_draft` then makes a load draft with marketplace.draft_load (the same
draft card and Confirm button as the chat), with the document's addresses and load number.
"""
import math
import re
from datetime import date

from paperwork.addresses import KA_CITIES, parse_address

LB_TO_KG = 0.45359237
CITIES = list(KA_CITIES.values())

# Equipment as printed -> our truck type code (checked in this order: "Box truck" before "truck")
EQUIPMENT = [
    (("refriger", "reefer", "მაცივ"), "refrigerated"),
    (("flatbed", "flat bed", "ბორტ"), "flatbed"),
    (("sprinter",), "sprinter_van"),
    (("box truck", "box-truck", "boxtruck"), "box_truck"),
    (("dry van", "dry-van", "van", "tent", "ტენტ"), "dry_van"),
]
# Package types as read (extract.py) -> the load record's packaging (pallet, crate or box)
PACKAGING = {"pallets": "pallet", "skids": "pallet", "boxes": "box", "cartons": "box", "crates": "crate"}
GEL = ("gel", "₾", "ლარ", "lari")

# The order the draft card asks for missing values
DRAFT_FIELDS = ("origin_city", "destination_city", "truck_type", "weight_kg", "customer_price_gel", "pickup_date")
BLOCKING_PROBLEMS = ("carrier_not_ours", "unreadable_document")


def _city(stop):
    for text in (stop.get("address"), stop.get("name")):
        if text:
            city = (parse_address(text) or {}).get("city")
            if city:
                return city
            # An English address: the city named LAST ("Kutaisi Street 5, Batumi" is in Batumi, not Kutaisi)
            found = [(m.start(), name) for name in CITIES
                     for m in re.finditer(rf"\b{name}\b", text, re.IGNORECASE)]
            if found:
                return max(found)[1]
    return None


def truck_type(equipment):
    text = (equipment or "").lower()
    for words, code in EQUIPMENT:
        if any(w in text for w in words):
            return code
    return None


def _weight_kg(doc):
    weight, unit = doc.get("weight"), doc.get("weight_unit")
    if weight is None or unit not in ("kg", "lb"):
        return None
    return round(weight * LB_TO_KG) if unit == "lb" else round(weight)


def _iso(value):
    try:
        return date.fromisoformat(value).isoformat() if value else None
    except ValueError:
        return None


def _first_time(text):
    match = re.search(r"\b(\d{1,2}):(\d{2})\b", text or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else None


def _existing_load(order_number):
    """The load already posted from this document's load number, if any (loads.reference in the database)."""
    if not order_number:
        return None
    import db
    try:
        found = db.one("SELECT id FROM loads WHERE UPPER(TRIM(reference)) = ?", (order_number.strip().upper(),))
    except Exception:   # no database yet (e.g. the paperwork eval on a fresh checkout)
        return None
    return found["id"] if found else None


def plan_draft(state):
    """LangGraph node: what a new load from this shipment's rate confirmation would be."""
    documents = state.get("documents") or []
    rc = next((d for d in documents if d["kind"] == "rate_confirmation"), None)
    if rc is None:
        return {"draft_plan": None}

    blocked = []
    problems = {f["check"] for f in state.get("findings") or [] if f["severity"] == "problem"}
    for check in BLOCKING_PROBLEMS:
        if check in problems:
            blocked.append({"reason": check})
    if any(d["kind"] == "proof_of_delivery" for d in documents):
        blocked.append({"reason": "already_delivered"})
    existing = _existing_load(rc.get("load_number"))
    if existing:
        blocked.append({"reason": "already_a_load", "load_number": existing})

    origin, destination = _city(rc["pickup"]), _city(rc["delivery"])
    for stop, city in (("pickup", origin), ("delivery", destination)):
        if city is None and (rc[stop].get("address") or rc[stop].get("name")):
            blocked.append({"reason": "city_not_ours", "stop": stop, "address": rc[stop].get("address")})
    currency = (rc.get("currency") or "").lower()
    price = rc.get("rate") if rc.get("rate") and any(g in currency for g in GEL) else None
    if rc.get("rate") and price is None and currency:
        blocked.append({"reason": "not_gel", "currency": rc.get("currency")})

    fields = {
        "origin_city": origin, "destination_city": destination,
        "truck_type": truck_type(rc.get("equipment")),
        "weight_kg": _weight_kg(rc), "customer_price_gel": price,
        "pickup_date": _iso(rc["pickup"].get("date")), "delivery_date": _iso(rc["delivery"].get("date")),
        "cargo_description": rc.get("commodity") or "",
    }
    counts = dict(rc.get("packages") or {})
    kind, count = next(iter(counts.items()), (None, None))
    fields["pieces"] = rc.get("pieces") or count or 1
    fields["packaging"] = PACKAGING.get(kind, "")
    assumed = ["packaging"] if kind and kind not in PACKAGING else []
    missing = [f for f in DRAFT_FIELDS if not fields.get(f)]

    document_fields = {
        "order_number": rc.get("load_number"),
        "reference_numbers": [v for v in (rc.get("references") or {}).values() if v],
        "broker": rc.get("issuer"), "shipper": rc["pickup"].get("name"), "consignee": rc["delivery"].get("name"),
        "pickup_address": rc["pickup"].get("address"), "delivery_address": rc["delivery"].get("address"),
        "pickup_time": _first_time(rc["pickup"].get("time")), "delivery_time": _first_time(rc["delivery"].get("time")),
        "rate_confirmation": rc["name"],
    }
    return {"draft_plan": {
        "source": rc["name"], "available": not blocked, "blocked": blocked,
        "fields": fields, "missing": missing, "assumed": assumed,
        "packaging_as_read": f"{count} {kind}" if kind else None,
        "document_fields": document_fields,
    }}


def create_draft(plan, values=None, user_id=None):
    """Make a load DRAFT for this shipper (marketplace.draft_load: the same draft card and Confirm button as
    the chat). values: what the user typed for missing fields (or to correct one). Returns the draft or
    {"error": ..., "error_code": ...}; the server words the error (Wording.draft_error)."""
    import marketplace

    if not plan or not plan.get("available"):
        return {"error": "No draft can be made from these documents.", "error_code": "not_available",
                "blocked": (plan or {}).get("blocked", [])}
    args = dict(plan["fields"])
    for key, value in (values or {}).items():
        if key in DRAFT_FIELDS + ("delivery_date",) and value not in (None, ""):
            args[key] = value
    try:
        args["weight_kg"] = int(float(args["weight_kg"])) if args.get("weight_kg") else 0
        args["customer_price_gel"] = float(args["customer_price_gel"]) if args.get("customer_price_gel") else 0
    except (TypeError, ValueError, OverflowError):
        return {"error": "Weight and price must be numbers.", "error_code": "not_a_number"}
    if not all(math.isfinite(v) and v >= 0 for v in (args["weight_kg"], args["customer_price_gel"])):
        return {"error": "Weight and price must be numbers.", "error_code": "not_a_number"}
    empty = [f for f in DRAFT_FIELDS if not args.get(f)]
    if empty:
        return {"error": "Still needed: " + ", ".join(empty) + ".", "error_code": "missing", "fields": empty}

    source = plan["document_fields"]
    load = {
        "origin_city": args["origin_city"], "destination_city": args["destination_city"],
        "truck_type": args["truck_type"], "weight_kg": args["weight_kg"], "pickup_date": args["pickup_date"],
        "price_gel": args["customer_price_gel"], "cargo": args.get("cargo_description") or "",
        "pieces": args.get("pieces") or 0, "pickup_address": source.get("pickup_address") or "",
        "delivery_address": source.get("delivery_address") or "", "reference": source.get("order_number") or "",
        "notes": f"დოკუმენტიდან: {plan['source']}",
    }
    result = marketplace.draft_load(user_id, load)
    if result.get("error_code") == "missing":
        named = {"origin_city": "origin_city", "destination_city": "destination_city", "truck_type": "truck_type",
                 "weight_kg": "weight_kg", "price_gel": "customer_price_gel", "pickup_date": "pickup_date"}
        return {**result, "fields": [named[f] for f in result.get("fields", []) if f in named]}
    if "draft_id" in result:
        result["from_document"] = plan["source"]
        if plan.get("assumed"):
            result["cargo_assumed"] = True       # e.g. "bundles" has no packaging of its own: check it
    return result

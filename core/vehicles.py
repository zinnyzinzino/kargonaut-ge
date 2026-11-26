"""Vehicle types. The labels below are what users see; change them here only (the site and the AI both use them).
Truck types are written in English, as in logimind-ai; the Georgian words people use are accepted as input."""
import re

TRUCK_TYPES = ["dry_van", "refrigerated", "flatbed", "box_truck", "sprinter_van"]
TRUCK_LABEL = {
    "dry_van": "Dry van",
    "refrigerated": "Refrigerated",
    "flatbed": "Flatbed",
    "box_truck": "Box truck",
    "sprinter_van": "Sprinter van",
}
TRUCK_TYPES_TEXT = "Dry van, Refrigerated, Flatbed, Box truck ან Sprinter van"
# Georgian words for the types (as typed in a chat or printed on a document): word stem -> code
TRUCK_WORDS_KA = {"ტენტ": "dry_van", "მაცივ": "refrigerated", "რეფ": "refrigerated", "ბორტ": "flatbed",
                  "პლატფორმ": "flatbed", "ფურგონ": "box_truck", "სპრინტ": "sprinter_van", "მიკროავტობ": "sprinter_van"}

# SIMULATED typical vehicle of each type: the medians of logimind-ai's simulated fleet (data/trucks.json, 100
# trucks). Used when a driver hasn't entered their own fuel use / wear cost, and for a shipper's price estimate
# (where no specific truck is known yet). Not real measurements.
TYPICAL = {
    "dry_van": {"capacity_kg": 18000, "fuel_l_per_100km": 30, "cost_per_km": 0.35},
    "refrigerated": {"capacity_kg": 15000, "fuel_l_per_100km": 34, "cost_per_km": 0.45},
    "flatbed": {"capacity_kg": 20000, "fuel_l_per_100km": 32, "cost_per_km": 0.40},
    "box_truck": {"capacity_kg": 4000, "fuel_l_per_100km": 22, "cost_per_km": 0.25},
    "sprinter_van": {"capacity_kg": 1500, "fuel_l_per_100km": 12, "cost_per_km": 0.15},
}


def truck_type(value):
    """Accept the code or the label in any case ("Refrigerated", "dry van", "Box-truck") and return the code,
    or None. The AI sees labels in every tool result and passes them back."""
    if not value:
        return None
    text = str(value).strip().lower()
    key = re.sub(r"[\s\-]+", "_", text)
    if key in TRUCK_TYPES:
        return key
    for stem, code in TRUCK_WORDS_KA.items():
        if stem in text:
            return code
    return None


def with_defaults(vehicle):
    """A vehicle dict with the type's typical fuel use and wear cost filled in where the driver left them empty."""
    v = dict(vehicle)
    typical = TYPICAL[v["truck_type"]]
    for key in ("fuel_l_per_100km", "cost_per_km"):
        if not v.get(key):
            v[key] = typical[key]
            v.setdefault("assumed", []).append(key)
    return v

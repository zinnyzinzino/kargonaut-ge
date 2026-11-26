"""Cities and road distances. REAL data: OSRM road distances and drive times between 8 city centres
(data/routes.json, car profile, made by logimind-ai's generate_routes.py)."""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

CITIES = ["Tbilisi", "Kutaisi", "Batumi", "Poti", "Zestafoni", "Samtredia", "Gori", "Rustavi"]
CITY_KA = {"Tbilisi": "თბილისი", "Kutaisi": "ქუთაისი", "Batumi": "ბათუმი", "Poti": "ფოთი",
           "Zestafoni": "ზესტაფონი", "Samtredia": "სამტრედია", "Gori": "გორი", "Rustavi": "რუსთავი"}
# Georgian stems, so inflected forms like "ქუთაისთან" or "თბილისიდან" still match.
# "ზესტა" is short on purpose: it also catches the common typo "ზესტაონი".
CITY_STEMS_KA = {
    "თბილის": "Tbilisi", "ქუთაის": "Kutaisi", "ბათუმ": "Batumi", "ფოთ": "Poti",
    "ზესტა": "Zestafoni", "სამტრედი": "Samtredia", "გორ": "Gori", "რუსთავ": "Rustavi",
}
# Representative city coordinates (the same points the OSRM routes were measured between)
CITY_COORDS = {
    "Tbilisi": (41.7151, 44.8271), "Kutaisi": (42.2679, 42.6946), "Batumi": (41.6168, 41.6367),
    "Poti": (42.1462, 41.6719), "Zestafoni": (42.1086, 43.0386), "Samtredia": (42.1537, 42.3352),
    "Gori": (41.9842, 44.1158), "Rustavi": (41.5495, 44.9932),
}

# SIMULATED in-city allowance: routes are city-to-city, so a truck already in the pickup city shows 0 km.
# Assume it still crosses town to reach the address.
IN_CITY_KM = 15
IN_CITY_MINUTES = 25


def city(name):
    """'Tbilisi', 'tbilisi', 'თბილისიდან', 'ქუთაისთან' -> the English city name; anything else -> None."""
    if not name:
        return None
    text = str(name).strip()
    for c in CITIES:
        if text.lower().startswith(c.lower()[:5]):
            return c
    for stem, c in CITY_STEMS_KA.items():
        if text.startswith(stem):
            return c
    return None


@lru_cache(maxsize=1)
def _routes():
    data = json.loads((DATA / "routes.json").read_text(encoding="utf-8"))
    return {(r["origin"], r["destination"]): r for r in data["routes"]}


def route(origin, destination):
    """{"distance_km", "duration_minutes"} between two of the 8 cities (0 km for the same city), or None."""
    r = _routes().get((origin, destination))
    return {"distance_km": r["distance_km"], "duration_minutes": r["duration_minutes"]} if r else None


def approach_leg(origin, pickup):
    """The empty drive from where a truck is to the pickup city; the same city gets the in-city allowance."""
    r = route(origin, pickup)
    if r is None:
        return None
    if r["distance_km"] == 0:
        return {"distance_km": IN_CITY_KM, "duration_minutes": IN_CITY_MINUTES, "same_city": True}
    return {**r, "same_city": False}

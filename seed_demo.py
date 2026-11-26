"""SIMULATED demo accounts, vehicles, loads and offers, so the site isn't empty in a demo.

Every account made here has is_demo = 1 (the site marks it "სადემონსტრაციო"); names are made up, phone numbers
are 599 00 00 XX, password demo1234. Load prices come from our own fair-price estimate (core/pricing.py), set
below, inside or above the range on purpose, so the price checks have something to say. Not market data.

    python seed_demo.py            # only into an empty database
    python seed_demo.py --force    # deletes EVERYTHING in the database first

The server runs seed() by itself when it starts with an empty database (the cloud's is always empty).
"""
import sys
from datetime import date, timedelta

import db
import marketplace as mp
from core.pricing import fair_price

PASSWORD = "demo1234"

SHIPPERS = [  # (name, legal status, city)
    ("ნინო ბერიძე", "entrepreneur", "Tbilisi"),
    ("გიორგი კაპანაძე", "person", "Kutaisi"),
    ("თამარ ხარაიშვილი", "entrepreneur", "Batumi"),
    ("შპს „მწვანე ველი“", "company", "Gori"),
]
DRIVERS = [  # (name, legal status, [(truck type, capacity kg, city, liftgate)])
    ("ლევან გელაშვილი", "entrepreneur", [("dry_van", 18000, "Tbilisi", False)]),
    ("დავით ჯაფარიძე", "entrepreneur", [("refrigerated", 15000, "Poti", False)]),
    ("ზურაბ მამულაშვილი", "person", [("box_truck", 4000, "Kutaisi", True)]),
    ("ირაკლი ცერცვაძე", "entrepreneur", [("flatbed", 20000, "Rustavi", False), ("dry_van", 20000, "Rustavi", False)]),
    ("გოჩა ნემსაძე", "person", [("sprinter_van", 1500, "Batumi", False)]),
    ("მერაბ ქავთარაძე", "entrepreneur", [("dry_van", 16000, "Zestafoni", False)]),
    ("ალექსანდრე ლომიძე", "entrepreneur", [("refrigerated", 12000, "Tbilisi", True)]),
    ("ბესიკ ხუციშვილი", "person", [("box_truck", 5000, "Gori", True)]),
    ("ვახტანგ ჩიქოვანი", "entrepreneur", [("flatbed", 22000, "Batumi", False)]),
    ("სანდრო ბაქრაძე", "person", [("sprinter_van", 1200, "Tbilisi", False), ("box_truck", 3500, "Tbilisi", False)]),
]
# (shipper index, from, to, type, kg, cargo, days from today, where the price sits: low / fair / high)
LOADS = [
    (0, "Tbilisi", "Batumi", "dry_van", 12000, "სამშენებლო მასალა", 2, "fair"),
    (0, "Tbilisi", "Kutaisi", "box_truck", 3000, "ავეჯი", 1, "low"),
    (1, "Kutaisi", "Tbilisi", "refrigerated", 8000, "რძის პროდუქტები", 3, "fair"),
    (1, "Kutaisi", "Poti", "flatbed", 15000, "ლითონის კონსტრუქციები", 4, "high"),
    (2, "Batumi", "Tbilisi", "refrigerated", 10000, "ციტრუსი", 2, "fair"),
    (2, "Batumi", "Kutaisi", "sprinter_van", 800, "ამანათები", 1, "fair"),
    (3, "Gori", "Tbilisi", "dry_van", 14000, "ხილი ყუთებში", 1, "low"),
    (3, "Gori", "Batumi", "dry_van", 9000, "კონსერვები", 5, "fair"),
    (0, "Rustavi", "Zestafoni", "flatbed", 18000, "არმატურა", 3, "fair"),
    (2, "Poti", "Tbilisi", "dry_van", 16000, "საყოფაცხოვრებო ტექნიკა", 6, "high"),
]


def _price(origin, dest, kind, kg, where):
    low, high = fair_price(origin, dest, kind, kg)["fair_price_range_gel"]
    return {"low": round(low * 0.9 / 10) * 10, "fair": round((low + high) / 2 / 10) * 10,
            "high": round(high * 1.1 / 10) * 10}[where]


def seed():
    db.init_db()
    phone = iter(f"5990000{n:02d}" for n in range(1, 100))
    shippers = []
    for name, status, home in SHIPPERS:
        shippers.append(mp.register("shipper", name, next(phone), PASSWORD, home, status, is_demo=True))
    drivers = []
    for name, status, vehicles in DRIVERS:
        d = mp.register("driver", name, next(phone), PASSWORD, vehicles[0][2], status, is_demo=True)
        for kind, kg, where, liftgate in vehicles:
            mp.add_vehicle(d["id"], {"truck_type": kind, "capacity_kg": kg, "city": where, "liftgate": liftgate})
        drivers.append(d)
    loads = []
    for who, origin, dest, kind, kg, cargo, days, where in LOADS:
        loads.append(mp.create_load(shippers[who]["id"], {
            "origin_city": origin, "destination_city": dest, "truck_type": kind, "weight_kg": kg, "cargo": cargo,
            "pickup_date": (date.today() + timedelta(days=days)).isoformat(),
            "price_gel": _price(origin, dest, kind, kg, where), "notes": "სადემონსტრაციო ტვირთი (სიმულაცია)"}))
    # A few offers, so a demo shipper has something to choose from (load 1: Tbilisi -> Batumi, dry van)
    first = loads[0]
    mp.make_offer(drivers[0]["id"], {"load_id": first["id"]})                                  # the shipper's price
    mp.make_offer(drivers[5]["id"], {"load_id": first["id"], "price_gel": first["price_gel"] - 40,
                                     "message": "ხვალვე შემიძლია"})
    mp.make_offer(drivers[3]["id"], {"load_id": first["id"], "price_gel": first["price_gel"] + 30})
    return {"shippers": len(shippers), "drivers": len(drivers), "loads": len(loads)}


if __name__ == "__main__":
    db.init_db()
    if db.one("SELECT id FROM users LIMIT 1"):
        if "--force" not in sys.argv:
            raise SystemExit("The database isn't empty. Use --force to delete everything and seed again.")
        with db.connect() as conn:
            for table in ("offers", "loads", "vehicles", "sessions", "users"):
                conn.execute(f"DELETE FROM {table}")
    print(seed(), "- demo password:", PASSWORD, "- phones 599000001 ...")

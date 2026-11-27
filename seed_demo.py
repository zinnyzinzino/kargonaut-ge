"""SIMULATED demo accounts, vehicles, loads and offers, so the site isn't empty in a demo.

Every account made here has is_demo = 1 (the site marks it "სადემონსტრაციო"); names are made up, phone numbers
are 599 00 00 XX, password demo1234. Load prices come from our own fair-price estimate (core/pricing.py), set
below, inside or above the range on purpose, so the price checks have something to say. Not market data.

    python seed_demo.py            # only into an empty database
    python seed_demo.py --force    # deletes EVERYTHING in the database first

Your own accounts in the demo (only from this command, never in the cloud or the tests): set in .env (git-ignored)
KARGONAUT_MY_NAME, KARGONAUT_MY_SHIPPER_PHONE, KARGONAUT_MY_DRIVER_PHONE and optionally KARGONAUT_MY_PASSWORD
(default demo1234). Then the first demo shipper (ნინო's loads, offers and trips) and the first demo driver
(ლევანი's truck, trips and the trip on the road) are yours: your name and numbers, the same simulated data.

The server runs seed() by itself when it starts with an empty database (the cloud's is always empty).
"""
import os
import sys
from datetime import date, timedelta

import db
import marketplace as mp
from core.geo import CITY_KA
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
    # 27 Nov: every registration case has a demo. Added at the END so the phones, plates and load numbers above
    # (used by the eval and the demo documents) don't change.
    ("შპს „კოლხეთი ტრანსი“", "company", [("dry_van", 20000, "Poti", False), ("refrigerated", 15000, "Batumi", False),
                                          ("box_truck", 4000, "Kutaisi", True)]),   # a fleet, registered as a list
    ("შპს „ახალი გზა“", "company", []),   # registered with „მანქანებს მოგვიანებით დავამატებ“: no trucks yet
]
NO_TRUCKS_HOME = "Tbilisi"   # where a carrier registered without trucks says it is


def _demo_iban(n):
    """A SIMULATED Georgian IBAN: bank code "DM" (demo, like the "DM" plates), check digits computed (ISO 13616),
    so it passes the site's check but is no real account."""
    bban = f"DM{n:016d}"
    check = 98 - int("".join(str(int(c, 36)) for c in bban + "GE00")) % 97
    return f"GE{check:02d}{bban}"


def demo_business(status, n, home):
    """SIMULATED registry details for a demo entrepreneur or company: ID codes of zeros (no real registry entry),
    a "სადემონსტრაციო მისამართი" address and a "DM" IBAN, so the profile and the transport order show every
    field. A private person has none."""
    if status == "person":
        return None
    return {"id_code": f"{n:09d}" if status == "company" else f"{n:011d}",
            "legal_address": f"{CITY_KA[home]}, სადემონსტრაციო მისამართი {n}", "bank_account": _demo_iban(n),
            "contact_person": "საკონტაქტო პირი (სიმულაცია)" if status == "company" else None}
# SIMULATED body sizes (inside, metres: length, width, height) by type, so the demo trucks show one on the map.
# Usual sizes for such a body, not measured trucks; a flatbed has no height.
DEMO_SIZES = {"dry_van": (13.6, 2.45, 2.7), "refrigerated": (13.3, 2.45, 2.6), "flatbed": (13.6, 2.5, None),
              "box_truck": (6.2, 2.4, 2.3), "sprinter_van": (4.3, 1.75, 1.9)}
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


def my_accounts():
    """{"name", "shipper_phone", "driver_phone", "password"} from the environment (.env), or None if not set."""
    me = {"name": os.getenv("KARGONAUT_MY_NAME", "").strip(),
          "shipper_phone": os.getenv("KARGONAUT_MY_SHIPPER_PHONE", "").strip(),
          "driver_phone": os.getenv("KARGONAUT_MY_DRIVER_PHONE", "").strip(),
          "password": os.getenv("KARGONAUT_MY_PASSWORD", "").strip() or PASSWORD}
    return me if me["name"] and me["shipper_phone"] and me["driver_phone"] else None


def _account(role, index, demo_phone, me):
    """The index-0 shipper and driver are the user's own when `me` is given; everyone else is a demo account."""
    if me and index == 0:
        return me["name"], me[f"{role}_phone"], me["password"], False
    return None, demo_phone, PASSWORD, True


def seed(me=None):
    """me: the user's own accounts (my_accounts()); None = only demo accounts (the server and the evals)."""
    db.init_db()
    phone = iter(f"5990000{n:02d}" for n in range(1, 100))
    shippers = []
    for i, (name, status, home) in enumerate(SHIPPERS):
        own_name, number, password, demo = _account("shipper", i, next(phone), me)
        # The user's own accounts register as a private person: the seed knows no registry details (ID code, address).
        # Demo entrepreneurs and companies get SIMULATED ones; the demo company sends its own transport orders.
        made = mp.register("shipper", own_name or name, number, password, home, status if demo else "person", is_demo=demo,
                           business=demo_business(status, int(number[-2:]), home) if demo else None,
                           order_preference="own" if demo and status == "company" else "kargonaut")
        if "error" in made:
            raise SystemExit(f"Can't create the shipper account {number}: {made['error']}")
        shippers.append(made)
    drivers = []
    plate = iter(f"DM-{n:03d}-KG" for n in range(1, 100))   # simulated plates: "DM" = demo, never a real truck's
    for i, (name, status, vehicles) in enumerate(DRIVERS):
        trucks = [{"truck_type": kind, "capacity_kg": kg, "city": where, "liftgate": liftgate, "plate": next(plate),
                   **dict(zip(("length_m", "width_m", "height_m"), DEMO_SIZES[kind]))}
                  for kind, kg, where, liftgate in vehicles]
        own_name, number, password, demo = _account("driver", i, next(phone), me)
        home = vehicles[0][2] if vehicles else NO_TRUCKS_HOME
        d = mp.register("driver", own_name or name, number, password, home, status if demo else "person", is_demo=demo,
                        vehicles=trucks, trucks_later=not trucks,
                        business=demo_business(status, int(number[-2:]), home) if demo else None)
        if "error" in d:
            raise SystemExit(f"Can't create the driver account {number}: {d['error']}")
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
    past = past_trips(shippers, drivers)   # after the open loads, so their numbers (№1-№10) never change
    on_road = trip_on_the_road(shippers, drivers)
    deadline = load_with_a_deadline(shippers, drivers)   # last: №11-№19 above keep their numbers
    return {"shippers": len(shippers), "drivers": len(drivers), "loads": len(loads), "past_trips": past,
            "on_the_road": on_road, "deadline_load": deadline}


def load_with_a_deadline(shippers, drivers):
    """A load that must arrive the same day (an export container for a ship leaving Poti), and two offers where the
    CHEAPER driver can't make it: მერაბ's truck is already booked that day for Zestafoni -> Batumi, so Batumi ->
    Tbilisi -> Poti on top is far over a day's driving. The site recommends ირაკლი (higher price, from Rustavi,
    ~6 h). All SIMULATED; Python decides (core/matching.py deadline_check), the AI only explains."""
    day = (date.today() + timedelta(days=2)).isoformat()
    shipper, cheap, on_time = shippers[0], drivers[5], drivers[3]
    load = mp.create_load(shipper["id"], {
        "origin_city": "Tbilisi", "destination_city": "Poti", "truck_type": "dry_van", "weight_kg": 10000,
        "cargo": "საექსპორტო ტვირთი (ღვინო ყუთებში)", "pieces": 20, "pickup_date": day, "deliver_by": day,
        "pickup_address": "ბელიაშვილის ქ. 104", "delivery_address": "ფოთის პორტი, ტერმინალი 3",
        "price_gel": _price("Tbilisi", "Poti", "dry_van", 10000, "fair"),
        "notes": "იმავე დღეს უნდა ჩავიდეს: გემზე ჩატვირთვა 18:00-მდე (სიმულაცია)"})
    # მერაბ's truck: booked the same day by another shipper (თამარ), Zestafoni -> Batumi
    truck = mp.vehicles_of(cheap["id"])[0]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO loads (shipper_id, origin_city, destination_city, truck_type, weight_kg, cargo, pickup_date,"
            " price_gel, notes, status, driver_id, vehicle_id, agreed_price_gel, booked_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (shippers[2]["id"], "Zestafoni", "Batumi", "dry_van", 12000, "ტვირთი", day, 420,
             "სადემონსტრაციო რეისი (სიმულაცია)", "booked", cheap["id"], truck["id"], 420, date.today().isoformat()))
    mp.make_offer(cheap["id"], {"load_id": load["id"], "price_gel": load["price_gel"] - 60,
                                "message": "იაფად წავიღებ"})
    mp.make_offer(on_time["id"], {"load_id": load["id"], "price_gel": load["price_gel"] + 40,
                                  "message": "დილით ავიღებ, შუადღისთვის ფოთში ვიქნები"})
    return load["id"]


def trip_on_the_road(shippers, drivers):
    """One trip booked for the demo driver (ლევანი), ready for the whole document chain on one load (Gori -> Rustavi,
    6 boxes of spare parts, 900 kg): its transport order, then at „ავიღე ტვირთი“ the simulated waybill
    demo_documents/ge/ge-07/waybill.pdf (this truck's plate), then at „მივიტანე“ the simulated proof of delivery
    ge-06/pod.pdf. Both readings ship with the app: no Gemini call on stage. (Until 27 Nov it started on the road.)
    The shipper is the demo company, which sends ITS OWN transport order (27 Nov): the trip waits for it, and the
    company uploads the simulated ge-06/rc.pdf (the „სადემონსტრაციო შეკვეთა“ button), which matches this trip."""
    shipper, driver = shippers[3], drivers[0]
    vehicle = mp.vehicles_of(driver["id"])[0]
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO loads (shipper_id, origin_city, destination_city, truck_type, weight_kg, cargo, pieces,"
            " pickup_date, pickup_address, delivery_address, price_gel, notes, status, driver_id, vehicle_id,"
            " agreed_price_gel, booked_at, order_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (shipper["id"], "Gori", "Rustavi", vehicle["truck_type"], 900, "სათადარიგო ნაწილები", 6,
             date.today().isoformat(), "ცხინვალის გზატკეცილი №5", "მეგობრობის გამზ. 21", 310,
             "სადემონსტრაციო რეისი (სიმულაცია)", "booked", driver["id"], vehicle["id"], 310,
             (date.today() - timedelta(days=1)).isoformat(),
             "own" if shipper.get("order_preference") == "own" else "kargonaut")).lastrowid


# Finished trips with ratings, so ratings show from the start: (shipper, driver, from, to, kg, days ago, price,
# stars the shipper gave the driver, stars the driver gave the shipper, the shipper's comment). All SIMULATED.
PAST = [
    (0, 5, "Tbilisi", "Kutaisi", 10000, 12, 640, 5, 5, "დროულად მოიტანა, ყველაფერი რიგზე იყო"),
    (1, 5, "Kutaisi", "Batumi", 8000, 20, 520, 5, 4, None),
    (2, 5, "Batumi", "Tbilisi", 12000, 33, 980, 4, 5, "ცოტა დააგვიანა, მაგრამ დაგვირეკა"),
    (3, 5, "Gori", "Tbilisi", 9000, 41, 330, 5, 5, None),
    (0, 0, "Tbilisi", "Gori", 6000, 9, 300, 4, 5, None),
    (2, 0, "Poti", "Tbilisi", 14000, 27, 1050, 5, 4, "კარგი მძღოლი"),
    (2, 1, "Batumi", "Tbilisi", 9000, 15, 1080, 5, 5, "მაცივარი სწორ ტემპერატურაზე ეჭირა"),
    (1, 1, "Poti", "Kutaisi", 7000, 38, 560, 5, 4, None),
]


def past_trips(shippers, drivers):
    for s, d, origin, dest, kg, days_ago, price, to_driver, to_shipper, comment in PAST:
        shipper, driver = shippers[s], drivers[d]
        vehicle = mp.vehicles_of(driver["id"])[0]
        with db.connect() as conn:
            load_id = conn.execute(
                "INSERT INTO loads (shipper_id, origin_city, destination_city, truck_type, weight_kg, cargo, pickup_date,"
                " price_gel, notes, status, driver_id, vehicle_id, agreed_price_gel, booked_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (shipper["id"], origin, dest, vehicle["truck_type"], kg, "ტვირთი",
                 (date.today() - timedelta(days=days_ago)).isoformat(), price, "სადემონსტრაციო რეისი (სიმულაცია)",
                 "delivered", driver["id"], vehicle["id"], price,
                 (date.today() - timedelta(days=days_ago + 1)).isoformat())).lastrowid
            conn.execute("INSERT INTO ratings (load_id, from_user, to_user, stars, comment) VALUES (?,?,?,?,?)",
                         (load_id, shipper["id"], driver["id"], to_driver, comment))
            conn.execute("INSERT INTO ratings (load_id, from_user, to_user, stars, comment) VALUES (?,?,?,?,?)",
                         (load_id, driver["id"], shipper["id"], to_shipper, None))
    return len(PAST)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    db.init_db()
    if db.one("SELECT id FROM users LIMIT 1"):
        if "--force" not in sys.argv:
            raise SystemExit("The database isn't empty. Use --force to delete everything and seed again.")
        with db.connect() as conn:
            for table in ("own_orders", "waybills", "pods", "ratings", "offers", "loads", "vehicles", "sessions", "users"):
                conn.execute(f"DELETE FROM {table}")
    me = my_accounts()
    print(seed(me), "- demo password:", PASSWORD, "- phones 599000001 ...")
    if me:
        print(f"Your accounts: shipper {me['shipper_phone']}, driver {me['driver_phone']}"
              f" ({'your password from .env' if os.getenv('KARGONAUT_MY_PASSWORD') else 'password ' + PASSWORD})")

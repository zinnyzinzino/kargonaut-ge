"""The database: SQLite (Python's built-in sqlite3, one file, no server).

The file is data/kargonaut.db (git-ignored), or KARGONAUT_DB. In the cloud the container's disk is
temporary, so the database resets on every restart or deploy: fine for a demo (the demo accounts are created
again at startup, see seed_demo.py), not for real users. Moving to a hosted database (PostgreSQL) later only
changes this file.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    role            TEXT NOT NULL CHECK (role IN ('shipper', 'driver')),
    name            TEXT NOT NULL,
    phone           TEXT NOT NULL UNIQUE,          -- the login: Georgian mobile, digits only (5XXXXXXXX)
    password_hash   TEXT NOT NULL,
    city            TEXT,
    legal_status    TEXT NOT NULL DEFAULT 'person' -- person | entrepreneur (ინდ. მეწარმე) | company
                    CHECK (legal_status IN ('person', 'entrepreneur', 'company')),
    is_demo         INTEGER NOT NULL DEFAULT 0,    -- simulated demo account (seed_demo.py)
    -- Business details (entrepreneur / company; a private person gives none). Printed on the transport order.
    id_code         TEXT,                          -- საიდენტიფიკაციო კოდი: 9 digits (company), 11 (entrepreneur)
    legal_address   TEXT,                          -- იურიდიული მისამართი
    bank_account    TEXT,                          -- IBAN (GE..), optional, for invoices
    contact_person  TEXT,                          -- a company's person to call
    order_preference TEXT NOT NULL DEFAULT 'kargonaut',   -- shippers: 'kargonaut' (our PDF) or 'own' (upload theirs)
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vehicles (
    id                  INTEGER PRIMARY KEY,
    driver_id           INTEGER NOT NULL REFERENCES users(id),
    truck_type          TEXT NOT NULL,
    capacity_kg         INTEGER NOT NULL,
    city                TEXT NOT NULL,             -- where it is now (one of the 8 cities)
    plate               TEXT,
    liftgate            INTEGER NOT NULL DEFAULT 0,
    hazmat              INTEGER NOT NULL DEFAULT 0,
    fuel_l_per_100km    REAL,                      -- empty: the type's typical value (core/vehicles.py)
    cost_per_km         REAL,
    length_m            REAL,                      -- cargo body inside, metres (optional; shown to shippers)
    width_m             REAL,
    height_m            REAL,
    available           INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS loads (
    id                  INTEGER PRIMARY KEY,
    shipper_id          INTEGER NOT NULL REFERENCES users(id),
    origin_city         TEXT NOT NULL,
    destination_city    TEXT NOT NULL,
    truck_type          TEXT NOT NULL,
    weight_kg           INTEGER NOT NULL,
    cargo               TEXT,
    pieces              INTEGER,
    piece_length_m      REAL,                      -- one piece's size, metres (optional, all three or none);
    piece_width_m       REAL,                      --   checked against the truck body (core/matching.size_check)
    piece_height_m      REAL,
    no_stacking         INTEGER NOT NULL DEFAULT 0,  -- 1: the pieces can't go on top of each other
    pickup_date         TEXT NOT NULL,             -- YYYY-MM-DD
    deliver_by          TEXT,                      -- YYYY-MM-DD, optional: deliver no later than this day
    pickup_address      TEXT,
    delivery_address    TEXT,
    needs_liftgate      INTEGER NOT NULL DEFAULT 0,
    hazmat              INTEGER NOT NULL DEFAULT 0,
    price_gel           REAL NOT NULL,             -- the shipper's price; drivers accept it or offer another
    notes               TEXT,
    reference           TEXT,                      -- e.g. the order number from a document it was made from
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'booked', 'in_transit', 'delivered', 'cancelled')),
    driver_id           INTEGER REFERENCES users(id),
    vehicle_id          INTEGER REFERENCES vehicles(id),
    agreed_price_gel    REAL,
    booked_at           TEXT,                      -- when the shipper accepted an offer (the transport order's date)
    order_source        TEXT,                      -- set at booking: 'kargonaut' (our PDF) or 'own' (own_orders)
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ratings (
    id          INTEGER PRIMARY KEY,
    load_id     INTEGER NOT NULL REFERENCES loads(id),
    from_user   INTEGER NOT NULL REFERENCES users(id),
    to_user     INTEGER NOT NULL REFERENCES users(id),
    stars       INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (load_id, from_user)                -- each side rates the other once per load
);

CREATE TABLE IF NOT EXISTS waybills (           -- the goods waybill (სასაქონლო ზედნადები) the driver photographs at pickup
    id          INTEGER PRIMARY KEY,
    load_id     INTEGER NOT NULL UNIQUE REFERENCES loads(id),
    driver_id   INTEGER NOT NULL REFERENCES users(id),
    none_issued INTEGER NOT NULL DEFAULT 0,    -- 1: no waybill was issued (a private person's goods): no file
    file_name   TEXT,
    stored_path TEXT,                          -- data/pod/ (git-ignored), like the proof of delivery
    document    TEXT,                          -- what the paperwork agent read (JSON)
    findings    TEXT,                          -- Python's checks against the booked load (JSON)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pods (               -- proof of delivery: the signed paper the driver photographs
    id          INTEGER PRIMARY KEY,
    load_id     INTEGER NOT NULL UNIQUE REFERENCES loads(id),
    driver_id   INTEGER NOT NULL REFERENCES users(id),
    file_name   TEXT NOT NULL,                 -- as uploaded (shown to people)
    stored_path TEXT NOT NULL,                 -- where the file is kept (data/pod/, git-ignored)
    document    TEXT,                          -- what the paperwork agent read (JSON, paperwork/schema.py format)
    findings    TEXT,                          -- the checks' problems and notes (JSON)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS own_orders (         -- the shipper's own transport order (instead of Kargonaut's PDF)
    id          INTEGER PRIMARY KEY,
    load_id     INTEGER NOT NULL UNIQUE REFERENCES loads(id),   -- a new upload replaces the old one
    shipper_id  INTEGER NOT NULL REFERENCES users(id),
    file_name   TEXT NOT NULL,
    stored_path TEXT NOT NULL,                 -- data/pod/ (git-ignored), like the other trip documents
    document    TEXT,                          -- what the paperwork agent read (JSON)
    findings    TEXT,                          -- Python's checks against the booking (JSON)
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS offers (
    id          INTEGER PRIMARY KEY,
    load_id     INTEGER NOT NULL REFERENCES loads(id),
    driver_id   INTEGER NOT NULL REFERENCES users(id),
    vehicle_id  INTEGER NOT NULL REFERENCES vehicles(id),
    price_gel   REAL NOT NULL,
    message     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'declined', 'withdrawn')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def db_path():
    return Path(os.getenv("KARGONAUT_DB") or ROOT / "data" / "kargonaut.db")


@contextmanager
def connect():
    """A new connection, committed and CLOSED at the end (one per use: sqlite connections shouldn't be shared
    between threads, and on Windows an unclosed one keeps the file locked)."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Columns added after a database was first made (CREATE TABLE IF NOT EXISTS doesn't add them)
        have = {r["name"] for r in conn.execute("PRAGMA table_info(loads)")}
        if "booked_at" not in have:   # 26 Nov: the transport order's date (when the shipper accepted an offer)
            conn.execute("ALTER TABLE loads ADD COLUMN booked_at TEXT")
        if "deliver_by" not in have:  # 27 Nov: an optional delivery deadline (offers are checked against it)
            conn.execute("ALTER TABLE loads ADD COLUMN deliver_by TEXT")
        for column in ("piece_length_m", "piece_width_m", "piece_height_m"):   # 27 Nov: the cargo's size
            if column not in have:
                conn.execute(f"ALTER TABLE loads ADD COLUMN {column} REAL")
        if "no_stacking" not in have:   # 27 Nov: the pieces can't go on top of each other
            conn.execute("ALTER TABLE loads ADD COLUMN no_stacking INTEGER NOT NULL DEFAULT 0")
        if "order_source" not in have:  # 27 Nov: Kargonaut's transport order or the shipper's own
            conn.execute("ALTER TABLE loads ADD COLUMN order_source TEXT")
        have = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        for column in ("id_code", "legal_address", "bank_account", "contact_person"):   # 27 Nov: business details
            if column not in have:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        if "order_preference" not in have:
            conn.execute("ALTER TABLE users ADD COLUMN order_preference TEXT NOT NULL DEFAULT 'kargonaut'")
        have = {r["name"] for r in conn.execute("PRAGMA table_info(vehicles)")}
        for column in ("length_m", "width_m", "height_m"):   # 27 Nov: the truck body's size
            if column not in have:
                conn.execute(f"ALTER TABLE vehicles ADD COLUMN {column} REAL")


def rows(sql, args=()):
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql, args=()):
    found = rows(sql, args)
    return found[0] if found else None


def execute(sql, args=()):
    """Run one write; returns the new row's id (for an INSERT)."""
    with connect() as conn:
        return conn.execute(sql, args).lastrowid

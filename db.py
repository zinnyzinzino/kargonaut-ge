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
    pickup_date         TEXT NOT NULL,             -- YYYY-MM-DD
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
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
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

# Kargonaut (Georgia)

A freight marketplace for Georgia. **Shippers** (people, individual entrepreneurs, small companies) post a
load with a price. **Independent drivers** see the loads their trucks can carry, along with what each trip
would leave them after costs, and accept the price or offer their own. The shipper picks one offer. Each side
gets an AI assistant in Georgian, and documents (rate confirmations, waybills, PODs) can be read and checked.

The site is Georgian only. It grew out of [logimind-ai](../logimind-ai), an AI dispatcher for one carrier
company, which continues as the English, international product. This repo copied the parts that carry over
(the Gemini loop and its guards, the cost engine, the paperwork agent) and reshaped them for a marketplace.

## Design principle

Gemini understands the message and chooses a tool. Python makes every decision and produces every number.
A person confirms anything that changes data. In practice:

- The AI never invents a truck, a price or a distance.
- The AI can only make **drafts** (`propose_load`, `propose_offer`). Only the user's Confirm button saves one.
- Booking a driver, cancelling, and marking a load picked up or delivered are buttons on the site. The AI has
  no tool for any of them, and a test checks this.

## Run it (Windows, PowerShell)

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env          # then put your GEMINI_API_KEY in .env
uvicorn server:app              # http://127.0.0.1:8000
pytest                          # 79 tests, no Gemini key needed (includes the eval self-test)
```

On the first start with an empty database, the server creates **simulated demo accounts**. Shippers have the
phone numbers 599000001 to 599000004, drivers 599000005 to 599000014, and the password is `demo1234`. It also
creates 10 open loads and 3 offers. Without a key, the site and the document check (for the demo documents)
work; the chat says the AI is off.

## Files

| Group | Files |
|---|---|
| Web | `server.py` (FastAPI: accounts, loads, vehicles, offers, chat, documents), `static/index.html` (the whole site, Georgian), `static/style.css` |
| Rules | `marketplace.py` (accounts, loads, offers, bookings, drafts: used by the site and the AI), `db.py` (SQLite) |
| Engines | `core/geo.py` (cities, real road distances), `core/vehicles.py` (truck types), `core/pricing.py` (trip costs, fair price, driver earnings), `core/matching.py` (who can carry what, rankings) |
| AI | `ai/engine.py` (Gemini loop, from logimind-ai), `ai/shipper.py` and `ai/driver.py` (each role's tools and prompt), `ai/common.py` (labels, the date / price / weight guards) |
| Paperwork | `paperwork/` (from logimind-ai: classify, extract, validate, cross-check, draft, RAG), `demo_documents/` (simulated) |
| Checks | `number_check.py`, `deadline.py`, `tests/`, `evals/run_paperwork_eval.py` |
| Documents the site makes | `transport_order.py` (the ტვირთის გადაზიდვის შეკვეთა PDF once a driver is booked), `static/fonts/` (Noto, OFL) |
| Demo data | `seed_demo.py` |

## Data: real vs simulated

**Real:** OSRM road distances and drive times between 8 city centres, the diesel price reference (₾4.95/L),
and the labelled, unverified freight-rate observations in `data/freight_rates.json`.

**Simulated:** vehicle wear per km, the driver's day wage, fixed trip costs, the fair-price markup range
(9 to 25%), the typical vehicle of each type, and every demo account, load and offer. The site labels demo
accounts "სადემონსტრაციო" or "სიმულაცია".

A market average is shown only when there are at least 3 recent verified deals on the lane (none yet).

## Open business decisions

These are not in the code yet, on purpose:

- **How the platform earns:** a commission per booked load, a driver subscription, or paid listings.
  `core/pricing.py` has no platform fee until this is decided.
- **Payment:** directly between the two sides (now), or held by the platform until delivery. Holding it would
  need a bank partner.
- **Trust:** checking ID and driver's licence, vehicle registration, ratings after delivery. The paperwork
  agent could read the documents.
- **Georgian documents:** the RS.ge electronic waybill (ზედნადები) instead of US-style rate confirmations.
  Check which documents individual shippers actually use.
- **Login:** a phone number and password now. SMS verification costs money per message.

## Deploying

The `Dockerfile` works like logimind-ai's. The database is a file inside the container, so it **resets on
every restart**. The demo accounts come back automatically, but real users would need a hosted database
(PostgreSQL); only `db.py` would change.

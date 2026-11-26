# Kargonaut (Georgia): notes for Claude Code

A Georgian freight marketplace: shippers (people, ინდ. მეწარმე, small companies) post loads; independent
drivers offer; the shipper books one. Split off on 26 November 2026 from `../logimind-ai`, which stays the
English, international product (pitched at the Higgs AI Agents Demo Day). This repo is for **LogiHack Batumi**
(28 November) and a one-week startup course; both must target **Georgia specifically**. See README.md.

**Design principle (never break it):** Gemini understands the request and chooses a tool; Python tools make
every decision and produce every number; a person confirms anything that changes data. The AI never invents a
truck, a price or a distance. The AI only makes drafts; booking, cancelling and status changes are buttons
(`tests/test_ai_tools.py::test_the_ai_has_no_tool_that_saves_books_or_changes_status`).

## How I like to work

- Give complete, working code built on my existing files. Don't rewrite files that work; make targeted changes.
- Test what you can before saying it's done (`pytest`, the paperwork eval, the site in a browser) and tell me
  exactly which files changed and why.
- Keep real and simulated data clearly separate. Never invent prices, sources or market data.
- **Georgian only:** the site, the AI's replies, error messages. Truck types are written in English
  ("Dry van", "Refrigerated", "Flatbed", "Box truck", "Sprinter van"), cities in Georgian. Code, comments and
  prompts to the model are in English.
- Don't commit or push unless I ask. Never commit `.env`.
- Explain things plainly; I'm a second-year CS student, not a logistics or ML expert.

## Running it (Windows, PowerShell)

```
.\.venv\Scripts\Activate.ps1
uvicorn server:app          # http://127.0.0.1:8000 ; restart after code changes
pytest                      # no Gemini key needed
python seed_demo.py --force # wipe the database and recreate the simulated demo data
```

## Where things are

- `marketplace.py`: every rule (accounts, loads, offers, bookings, drafts). The site and the AI both call it.
  Errors are `{"error": <Georgian sentence>, "error_code": ...}`. A driver registers WITH their truck (type,
  capacity, city, plate required; fuel use and wear optional): account and truck are saved together or not at all.
  One plate = one truck.
- The look (26 Nov): one dark theme, near-black with yellow (`--gold`), everywhere: landing, sign-in, the app.
  Colours are variables at the top of `static/style.css`; status colours are in `static/app.js` (`SHIP_GROUPS`,
  `TRIP_GROUPS`) and are bright on purpose (the badges have dark text).
- `core/`: pure Python engines. Money model: the shipper pays the driver; the driver pays the trip costs
  (diesel, wear, fixed); what's left is "მძღოლს რჩება", never "profit". The fair range = full cost (with a
  day's wage) + 9 to 25%. No platform fee yet (an open decision, README).
- `ai/`: one Gemini loop (`engine.py`, from logimind-ai's assistant.py: model fallback, hard time limits,
  number self-check, offline answer), two roles (`shipper.py`, `driver.py`). **Docstrings are prompts.**
  Guards in Python (`ai/common.py`): a pickup date, price or weight the user never wrote is dropped and the
  tool asks. Lesson from logimind-ai: fixes in tools beat rules in the prompt.
- Ratings: after delivery each side rates the other once, 1-5 stars (`marketplace.rate`, table `ratings`). Averages show
  on offers, on the driver's load board and in the header. The offer ranking is still price first, then distance.
- Proof of delivery: „მივიტანე“ (in_transit -> delivered) needs the signed paper (`POST /api/jobs/{id}/deliver`). The
  paperwork agent reads it, Python checks the signature and the delivery city (`marketplace.pod_check_city`);
  problems don't block delivery, both sides see them with an action. Photos live next to the database (`data/pod/`).
  The demo trip on the road (load 19, Gori -> Rustavi) matches `demo_documents/ge/ge-06/pod.pdf`, whose reading ships.
- Transport order (ტვირთის გადაზიდვის შეკვეთა, `transport_order.py`, `GET /api/loads/{id}/order.pdf`): Georgia has no
  standard rate-confirmation form, so once a shipper accepts an offer the site writes the order itself from the
  database (parties, truck and plate, route, cargo, agreed price), one A4 page, for the two sides only. What the site
  doesn't know (ID numbers, payment terms) stays a blank line, never invented. fpdf2 with Noto Sans + Noto Sans
  Georgian (`static/fonts`, OFL); Noto Sans has Latin/digits/₾/№ but no Georgian, so Georgian is the fallback font,
  and "≈" isn't in either (write "დაახლოებით"). `loads.booked_at` is its date (added to old databases by `init_db`).
- Georgian documents (user's research, 26 Nov): RC ≈ გადაზიდვის შეკვეთა (no standard form: we generate it),
  BOL ≈ სასაქონლო ზედნადები (RS.ge e-waybill, the one official form: model its fields on the official form, not a
  guess), POD ≈ signed ზედნადები or მიღება-ჩაბარების აქტი. Next candidates: read the ზედნადები; a printable
  handover act for individuals; RS.ge e-waybill integration for businesses (needs their RS access).
- Eval (`evals/`, see its README): 21 cases on real Gemini; baseline 21/21 on gemini-3.5-flash-lite (26 Nov).
  `python evals/selftest.py` first (also in pytest). Same rules as logimind-ai: read the reply before blaming the agent.
- `paperwork/`: from logimind-ai, unchanged except `draft.py` (a document now becomes a marketplace load
  draft via `marketplace.draft_load`). Its notes are in `../logimind-ai/CLAUDE.md`.
- The database is SQLite (`db.py`, `data/kargonaut.db`, git-ignored). In the cloud it resets on every restart.

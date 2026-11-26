"""Kargonaut (Georgia): the marketplace website's backend. Georgian only.

Run:   uvicorn server:app          (restart after code changes)
Open:  http://127.0.0.1:8000
"""
import os
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import marketplace as mp
from core.geo import CITIES, CITY_COORDS, CITY_KA, city
from core.pricing import compare_types, fair_price
from core.vehicles import TRUCK_LABEL, TRUCK_TYPES, truck_type

BASE = Path(__file__).resolve().parent
# Read .env first: the key check below runs before the AI modules (which also read it) are imported. Without this
# the site said "no key" although .env had one (found 26 Nov on the first local run). A terminal setting wins.
load_dotenv(BASE / ".env")
COOKIE = "kargonaut_session"
STARTED = time.time()


def _log(text):
    """Progress lines in the server's terminal; never fails on a Georgian file name in a cp1252 console."""
    line = f"   · {text}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    # The cloud's disk is temporary: the demo accounts are made again on every start (KARGONAUT_DEMO_SEED=0: off)
    if os.getenv("KARGONAUT_DEMO_SEED", "1") != "0" and not db.one("SELECT id FROM users LIMIT 1"):
        import seed_demo
        seed_demo.seed()
        _log("empty database: simulated demo accounts created (seed_demo.py)")
    yield


app = FastAPI(title="Kargonaut", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def _ok(result, status=400):
    """A marketplace result, or its Georgian error as an HTTP error the page shows as it is."""
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=status, detail=result["error"])
    return result


# ---------------------------------------------------------------- who is asking

def current_user(request: Request):
    user = mp.user_for_token(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="შედით სისტემაში.")
    return user


def shipper(user=Depends(current_user)):
    if user["role"] != "shipper":
        raise HTTPException(status_code=403, detail="ეს გვერდი ტვირთის გამგზავნებისთვისაა.")
    return user


def driver(user=Depends(current_user)):
    if user["role"] != "driver":
        raise HTTPException(status_code=403, detail="ეს გვერდი მძღოლებისთვისაა.")
    return user


# ---------------------------------------------------------------- pages and reference data

@app.get("/")
def index():
    return HTMLResponse((BASE / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/meta")
def meta():
    return {
        "cities": [{"name": c, "label": CITY_KA[c], "lat": CITY_COORDS[c][0], "lng": CITY_COORDS[c][1]} for c in CITIES],
        "truck_types": [{"code": t, "label": TRUCK_LABEL[t]} for t in TRUCK_TYPES],
        "legal_statuses": mp.LEGAL_STATUS_KA,
    }


@app.get("/api/health")
def health():
    """For deploy scripts and uptime checks. Calls no AI (never uses Gemini quota)."""
    try:
        counts = {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("users", "vehicles", "loads", "offers")}
    except Exception as e:
        raise HTTPException(503, f"database not readable: {e}")
    return {"status": "ok", "gemini_key_set": _gemini_key_set(), **counts,
            "chat_sessions": len(assistants), "uptime_s": round(time.time() - STARTED)}


@app.get("/api/price")
def price(origin: str, destination: str, kind: str = "", weight_kg: int = 0, price_gel: float = 0):
    """The fair price range (public: the landing page's calculator). No truck type: every type compared."""
    o, d = city(origin), city(destination)
    if not o or not d or o == d:
        raise HTTPException(400, "აირჩიეთ ორი სხვადასხვა ქალაქი.")
    if not kind:
        return compare_types(o, d, weight_kg or None, price_gel or None)
    code = truck_type(kind)
    if not code:
        raise HTTPException(400, "უცნობი მანქანის ტიპი.")
    result = fair_price(o, d, code, weight_kg or None, price_gel or None)
    result["verdict_label"] = mp.VERDICT_KA.get(result.get("verdict"))
    return result


# ---------------------------------------------------------------- accounts

class RegisterIn(BaseModel):
    role: str
    name: str
    phone: str
    password: str
    city: str = ""
    legal_status: str = "person"
    vehicle: dict = {}   # drivers: their truck (truck_type, capacity_kg, city, plate, ...), saved with the account


class LoginIn(BaseModel):
    phone: str
    password: str


def _set_cookie(response, token):
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                        secure=os.getenv("KARGONAUT_SECURE_COOKIE", "0") == "1")


@app.post("/api/register")
def register(body: RegisterIn, response: Response):
    _ok(mp.register(body.role, body.name, body.phone, body.password, body.city, body.legal_status,
                    vehicle=body.vehicle))
    session = mp.login(body.phone, body.password)
    _set_cookie(response, session["token"])
    return session["user"]


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    session = _ok(mp.login(body.phone, body.password), status=401)
    _set_cookie(response, session["token"])
    return session["user"]


@app.post("/api/logout")
def logout(request: Request, response: Response):
    mp.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return mp.public_user(user, with_phone=True)


# ---------------------------------------------------------------- shipper side

class LoadIn(BaseModel):
    origin_city: str = ""
    destination_city: str = ""
    truck_type: str = ""
    weight_kg: float = 0
    pickup_date: str = ""
    price_gel: float = 0
    cargo: str = ""
    pieces: int = 0
    pickup_address: str = ""
    delivery_address: str = ""
    needs_liftgate: bool = False
    hazmat: bool = False
    notes: str = ""


@app.post("/api/loads")
def post_load(body: LoadIn, user=Depends(shipper)):
    return _ok(mp.create_load(user["id"], body.model_dump()))


@app.get("/api/loads/mine")
def my_loads(status: str = "", user=Depends(shipper)):
    return mp.loads_of_shipper(user["id"], status)


@app.get("/api/loads/{load_id}/offers")
def load_offers(load_id: int, user=Depends(shipper)):
    return _ok(mp.offers_for_load(user["id"], load_id), status=404)


@app.post("/api/loads/{load_id}/cancel")
def load_cancel(load_id: int, user=Depends(shipper)):
    return _ok(mp.cancel_load(user["id"], load_id))


@app.post("/api/offers/{offer_id}/accept")
def offer_accept(offer_id: int, user=Depends(shipper)):
    """The shipper books a driver: only this button does it, never the AI."""
    result = _ok(mp.accept_offer(user["id"], offer_id))
    _tell_assistant(user["id"], f"the user accepted offer {offer_id}; load {result['id']} is booked")
    return result


# ---------------------------------------------------------------- driver side

class VehicleIn(BaseModel):
    truck_type: str = ""
    capacity_kg: float = 0
    city: str = ""
    plate: str = ""
    liftgate: bool = False
    hazmat: bool = False
    fuel_l_per_100km: float = 0
    cost_per_km: float = 0


class VehicleUpdateIn(BaseModel):
    city: str | None = None
    available: bool | None = None


class OfferIn(BaseModel):
    price_gel: float = 0
    vehicle_id: int = 0
    message: str = ""


@app.post("/api/vehicles")
def add_vehicle(body: VehicleIn, user=Depends(driver)):
    return _ok(mp.add_vehicle(user["id"], body.model_dump()))


@app.get("/api/vehicles/mine")
def my_vehicles(user=Depends(driver)):
    return mp.vehicles_of(user["id"])


@app.post("/api/vehicles/{vehicle_id}")
def update_vehicle(vehicle_id: int, body: VehicleUpdateIn, user=Depends(driver)):
    return _ok(mp.update_vehicle(user["id"], vehicle_id, body.city, body.available))


@app.get("/api/loads/open")
def open_loads(near_city: str = "", heading_to: str = "", user=Depends(driver)):
    return _ok(mp.loads_for_driver(user["id"], near_city or None, heading_to or None))


@app.post("/api/loads/{load_id}/offers")
def make_offer(load_id: int, body: OfferIn, user=Depends(driver)):
    return _ok(mp.make_offer(user["id"], {"load_id": load_id, **body.model_dump()}))


@app.post("/api/offers/{offer_id}/withdraw")
def offer_withdraw(offer_id: int, user=Depends(driver)):
    return _ok(mp.withdraw_offer(user["id"], offer_id))


@app.get("/api/jobs")
def jobs(user=Depends(driver)):
    return mp.jobs_of_driver(user["id"])


@app.post("/api/jobs/{load_id}/advance")
def job_advance(load_id: int, user=Depends(driver)):
    """Picked up -> delivered: the driver's own button."""
    return _ok(mp.advance_job(user["id"], load_id))


# ---------------------------------------------------------------- the AI assistant (both sides)

assistants = {}   # user id -> Assistant (in memory: a restart forgets conversations)


class ChatIn(BaseModel):
    message: str


def _assistant(user):
    from ai.engine import Assistant
    bot = assistants.get(user["id"])
    if bot is None:
        bot = assistants[user["id"]] = Assistant(user, on_status=_log)
    return bot


def _tell_assistant(user_id, text):
    if user_id in assistants:
        assistants[user_id].note_event(text)


NO_KEY = "⚠️ AI ასისტენტი ამ სერვერზე ჩართული არ არის (Gemini-ს გასაღები არ არის მითითებული). საიტის ყველა ღილაკი მუშაობს."


def _gemini_key_set():
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


@app.post("/api/chat")
def chat(body: ChatIn, user=Depends(current_user)):
    message = body.message.strip()[:2000]
    if not message:
        raise HTTPException(400, "ჩაწერეთ შეტყობინება.")
    if not _gemini_key_set():   # the Gemini client can't even start without a key: say so, don't crash
        return {"reply": NO_KEY, "tool_calls": [], "model": None, "ai_available": False, "drafts": []}
    result = _assistant(user).ask(message)
    if not result.get("ai_available"):
        _log(f"AI unavailable: {result.get('error', '')[:300]}")
    return result


@app.post("/api/chat/reset")
def chat_reset(user=Depends(current_user)):
    if user["id"] in assistants:
        assistants[user["id"]].reset()
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/confirm")
def draft_confirm(draft_id: str, user=Depends(current_user)):
    """The ONLY way a draft (from the chat or a document) becomes a load or an offer: the user's own click."""
    result = _ok(mp.confirm_draft(user["id"], draft_id))
    what = f"load {result.get('id')} posted" if result["kind"] == "load" else f"offer {result.get('id')} sent"
    _tell_assistant(user["id"], f"the user confirmed the draft; {what}")
    return result


@app.post("/api/drafts/{draft_id}/reject")
def draft_reject(draft_id: str, user=Depends(current_user)):
    _tell_assistant(user["id"], "the user cancelled the draft; nothing was saved")
    return mp.reject_draft(user["id"], draft_id)


# ---------------------------------------------------------------- documents (the paperwork agent)

PAPERWORK_CACHE = BASE / "documents" / "_read_cache"            # private: git-ignored
PAPERWORK_SHIPPED = BASE / "demo_documents" / "ge" / "_readings"  # simulated demo documents' readings
PAPERWORK_MAX_FILES = 5
PAPERWORK_MAX_BYTES = 10 * 1024 * 1024
OUR_CARRIER = [n.strip() for n in os.getenv("KARGONAUT_OUR_CARRIER", "Kargonaut Logistics LLC").split("|") if n.strip()]
PAPERWORK_PLANS = {}     # check_id -> (user id, draft plan): in memory, the last 50
PAPERWORK_PASSAGES = {}  # check_id -> (user id, the documents' text as passages)
QUESTION_MAX_CHARS = 300


def _remember(store, key, value):
    store[key] = value
    while len(store) > 50:
        store.pop(next(iter(store)))


@app.post("/api/paperwork/check")
def paperwork_check(files: list[UploadFile] = File(default=[]), user=Depends(current_user)):
    """Read one load's documents and check them against each other. Nothing is saved."""
    from paperwork.extract import MIME_TYPES, CachedReader, GeminiReader
    from paperwork.graph import read_documents
    from paperwork.rag import document_pages, passages
    from paperwork.wording import Wording

    if not files:
        raise HTTPException(400, "ფაილი არ აიტვირთა.")
    if len(files) > PAPERWORK_MAX_FILES:
        raise HTTPException(400, f"ერთად მაქსიმუმ {PAPERWORK_MAX_FILES} ფაილი.")
    with tempfile.TemporaryDirectory(prefix="kargonaut-upload-") as folder:
        paths, names = [], {}
        for i, upload in enumerate(files):
            name = Path(upload.filename or f"document-{i + 1}").name
            stem, copy = Path(name).stem, 2
            while name in names.values():
                name = f"{stem} ({copy}){Path(name).suffix}"
                copy += 1
            suffix = Path(name).suffix.lower()
            if suffix not in MIME_TYPES:
                raise HTTPException(400, f"{name}: მხოლოდ PDF, JPG, PNG ან WEBP ფაილი.")
            data = upload.file.read(PAPERWORK_MAX_BYTES + 1)
            if len(data) > PAPERWORK_MAX_BYTES:
                raise HTTPException(413, f"{name} 10 MB-ზე დიდია.")
            safe = re.sub(r"[^\w.-]", "_", Path(name).stem)[:40]
            path = Path(folder) / f"{i + 1}_{safe}{suffix}"
            path.write_bytes(data)
            paths.append(path)
            names[str(path)] = name
        texts = {names[str(p)]: passages(names[str(p)], document_pages(p)) for p in paths}
        # No key: only saved readings (the demo documents' ship with the app); a new document is "unreadable"
        gemini = GeminiReader(on_status=_log) if _gemini_key_set() else None
        reader = CachedReader(PAPERWORK_CACHE, gemini, by_content=True, also_from=[PAPERWORK_SHIPPED])
        state = read_documents(paths, OUR_CARRIER, reader=reader, lang="ka", display_names=names)
    w = Wording("ka")
    check_id = uuid.uuid4().hex[:10]
    plan = state.get("draft_plan")
    if plan:
        _remember(PAPERWORK_PLANS, check_id, (user["id"], plan))
    _remember(PAPERWORK_PASSAGES, check_id, (user["id"], [p for items in texts.values() for p in items]))
    return {
        "check_id": check_id,
        "documents": [{**doc, "kind_label": w.kind(doc["kind"])} for doc in state.get("documents", [])],
        "findings": state.get("findings", []),
        "agreements": state.get("agreements", []),
        "draft_plan": {k: v for k, v in plan.items() if k != "document_fields"} if plan else None,
        "searchable": len(PAPERWORK_PASSAGES[check_id][1]),
        "not_searchable": [name for name, items in texts.items() if not items],
    }


@app.get("/api/paperwork/demo")
def paperwork_demo():
    """The simulated demo documents, so visitors can try the check without files of their own."""
    from paperwork.ship_readings import demo_documents
    loads = {}
    for load, path in demo_documents():
        loads.setdefault(load, []).append(path.name)
    return [{"id": load, "files": files} for load, files in loads.items()]


@app.get("/api/paperwork/demo/{load}/{name}")
def paperwork_demo_file(load: str, name: str):
    from paperwork.extract import MIME_TYPES
    from paperwork.ship_readings import demo_documents
    for demo_load, path in demo_documents():   # only files named in a demo answer key, never any other path
        if (demo_load, path.name) == (load, name):
            return FileResponse(path, media_type=MIME_TYPES[path.suffix.lower()])
    raise HTTPException(404, "not a demo document")


class AskIn(BaseModel):
    check_id: str
    question: str


@app.post("/api/paperwork/ask")
def paperwork_ask(body: AskIn, user=Depends(current_user)):
    """A question about the checked documents: Gemini answers from quoted passages only, Python checks it."""
    from paperwork.extract import GeminiReader
    from paperwork.rag import SavedGeminiEmbeddings, ask
    owner, items = PAPERWORK_PASSAGES.get(body.check_id, (None, None))
    if items is None or owner != user["id"]:
        raise HTTPException(404, "ეს შემოწმება სერვერზე აღარ არის: დოკუმენტები თავიდან შეამოწმეთ.")
    question = body.question.strip()[:QUESTION_MAX_CHARS]
    if not question:
        raise HTTPException(400, "ჩაწერეთ კითხვა.")
    if not _gemini_key_set():
        raise HTTPException(503, NO_KEY)
    result = ask(question, items, lang="ka", reader=GeminiReader(on_status=_log),
                 embeddings=SavedGeminiEmbeddings(PAPERWORK_CACHE, also_from=[PAPERWORK_SHIPPED]))
    answered = result.get("status") == "answered"
    return {"status": result.get("status"), "answer": result.get("answer") if answered else None,
            "quotes": result.get("quotes", []) if answered else [],
            "passages": [{k: h[k] for k in ("n", "document", "page", "text")} for h in result.get("hits", [])]}


class DraftIn(BaseModel):
    check_id: str
    values: dict = {}


@app.post("/api/paperwork/draft")
def paperwork_draft(body: DraftIn, user=Depends(shipper)):
    """A load DRAFT from a checked document. Nothing is saved: the draft card's Confirm button is the only way."""
    from paperwork.draft import create_draft
    from paperwork.wording import Wording
    owner, plan = PAPERWORK_PLANS.get(body.check_id, (None, None))
    if plan is None or owner != user["id"]:
        raise HTTPException(404, "ეს შემოწმება სერვერზე აღარ არის: დოკუმენტები თავიდან შეამოწმეთ.")
    result = create_draft(plan, body.values, user_id=user["id"])
    if "error" in result:
        if result.get("error_code") in ("missing", "not_available", "not_a_number"):
            raise HTTPException(400, Wording("ka").draft_error(result, truck_label=lambda c: TRUCK_LABEL.get(c, c)))
        raise HTTPException(400, result["error"])   # marketplace errors are Georgian already
    return result

"""Gemini reads the documents: `classify` (what kind of document is it?) and `extract` (its values, in the
schema.py format). Reading is the only thing the AI does here; every decision is made by checks.py.

Models: KARGONAUT_PAPERWORK_MODELS in .env (comma-separated), else DEFAULT_MODELS. On purpose NOT the
dispatcher eval's gemini-3.5-flash-lite, so reading documents doesn't eat that model's free quota.
Privacy: only the anonymized copies may be sent (documents/us/, later the simulated Georgian ones);
anything under documents/originals/ is refused before a request is made.
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from deadline import CallTimedOut, call_with_deadline
from paperwork.schema import DOCUMENT_KINDS, empty_document

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# gemini-3.6-flash read all Georgian demo documents right (188/188, 24 Nov, run 2026-11-24_2210), with no busy
# errors; the preview was often 503/504 and 3.1-flash-lite missed a scribbled signature (ge-06)
DEFAULT_MODELS = ["gemini-3.6-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]
MODELS = [m.strip() for m in os.getenv("KARGONAUT_PAPERWORK_MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS
RETRY_SAME_MODEL_CODES = {503}  # busy: wait and retry. 429 (quota used up) doesn't clear in seconds:
                                # retrying only wastes requests (23 Nov), so go straight to the next model
RETRY_WAITS_S = [3, 10]        # reading isn't a chat answer: worth waiting for the better model when it's busy
# Time limits, enforced by us (deadline.py: the library's own timeout let calls run 105 s and 148 s past 75 s).
# Measured 25 Nov on 97 saved readings: gemini-3.6-flash median ~21 s, 9 in 10 within ~58-68 s, slowest 89 s /
# 148 s; 3.1-flash-lite median 5-16 s. Azure ends a web request after 240 s, and a check has two steps
# (classify, then extract), so 2 x 110 s leaves room for the upload and the checks.
REQUEST_TIMEOUT_S = 90         # one call: room for nearly all of 3.6-flash's reads
STEP_DEADLINE_S = 110          # all models and retries of ONE step (classify, extract, an answer) together
MIN_CALL_S = 10                # don't start a call with less time than this left in the step
PROMPT_VERSION = "2026-11-24b"  # saved with every extraction: change it when the prompts change

MIME_TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".webp": "image/webp"}


class ReadingFailed(Exception):
    pass


# ---------------------------------------------------------------- prompts and output formats

CLASSIFY_PROMPT = """You sort freight paperwork for a trucking company. Look at the attached document and say what it is.

Kinds:
- rate_confirmation: a broker's load / rate confirmation or load tender to a carrier (rate, pickup, delivery, carrier).
- bill_of_lading: a bill of lading (BOL) or straight bill of lading, signed by shipper and driver at pickup.
- delivery_order: a delivery order / freight release that tells a warehouse or terminal to release freight to a carrier.
- proof_of_delivery: a POD, OR any BOL or delivery order that was signed by the receiver at delivery
  (a "received" signature with a delivery date makes it a proof of delivery).
- other: anything else (invoice, lumper receipt, photo of freight, ...).

Documents may be Georgian: "ფასის დადასტურება" = rate confirmation, "კონოსამენტი" or "სასაქონლო ზედნადები"
= bill of lading, "მიწოდების ორდერი" = delivery order, "მიღება-ჩაბარების აქტი" or "მიტანის დადასტურება"
= proof of delivery.

says_not_a_bol: true only if the document itself prints that it is not a bill of lading.
title_as_printed: the document's title exactly as printed, or null if it has none.
Answer only from what is on the document."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(DOCUMENT_KINDS)},
        "says_not_a_bol": {"type": "boolean"},
        "title_as_printed": {"type": ["string", "null"]},
    },
    "required": ["kind", "says_not_a_bol", "title_as_printed"],
}

EXTRACT_RULES = """Read the attached {kind_label} and fill in the fields. You only read: copy what is printed or
handwritten; never guess, never fill a blank from general knowledge or from another part of the page.

Rules:
- A field that is blank, missing or unreadable is null. Never invent a value.
- Dates as YYYY-MM-DD. US documents usually write month/day, but "18/11/2026" can only be 18 November:
  use the document's own context. Georgian documents write day.month.year ("30.11.2026" = 30 November).
  A date that can't be decided is null.
- weight_as_printed: the weight exactly as printed, with its label and whatever is written next to it
  (e.g. "WEIGHT: 509.00", "300 LBS", "320.0#", "წონა / Weight: 12 000 კგ"). weight: the number only.
  weight_unit: "lb" when the document says lb, lbs, pounds or #; "kg" for kg or კგ; null when no unit is
  printed next to the weight (do NOT assume lb or kg). A blank weight line is null, not 0.
- equipment: the truck / trailer type as printed ("Van", "Refrigerated", "Flatbed", ...), or null.
- pieces: a plain piece / handling-unit count. packages: counts per package type when the document breaks
  them down (e.g. cartons 8, pallets 2). Don't add them up.
- carrier: the trucking company named as carrier (on a delivery order: the delivering carrier).
  issuer: the broker on a rate confirmation; the company that issued a BOL or delivery order.
- load_number: the broker's load / order number on a rate confirmation; null on other documents unless one
  is printed as the load number. references: every other reference number with its printed label
  (PO, BOL #, pickup #, PRO, HBL, MBL, ...), values copied exactly.
- addresses: as printed, on one line (street, city, state, ZIP; Georgian addresses in Georgian, as written).
  The shipper is the pickup, the consignee / ship-to / deliver-to is the delivery. A "bill to" / "sold to"
  address is NOT the delivery.
- Company names: exactly as printed (often in English on Georgian documents); never translate them.
- signatures: one entry per signature line on the document ({roles}). mark = what is physically ON the
  signature line itself: "empty", "signature" (handwritten), "initials", "typed_name" or "stamp". A date
  written next to the line is NOT a signature: a line with only a date is "empty". signed = true only when
  mark is not "empty". name = a name only if it is printed or clearly legible; initials = the initials as
  written. Never turn initials or an unreadable signature into a name, and never take a name from
  elsewhere on the page (a contact person, a "prepared by" line).
- handwritten_notes: every handwritten remark that is not a signature, a date or a reference number, as written.
{kind_hint}"""

KIND_HINTS = {
    "rate_confirmation": "This is a rate confirmation: the signature line is the carrier's (role carrier). "
                         "rate is the total carrier pay; currency as printed (USD for $).",
    "bill_of_lading": "This is a bill of lading: it normally has a shipper signature line and a driver / carrier "
                      "signature line (roles shipper and driver), and may have a receiver line.",
    "delivery_order": "This is a delivery order: the receiver line ('received in good order') is role receiver.",
    "proof_of_delivery": "This is a proof of delivery: the person who signed for the freight is role receiver, "
                         "wherever on the page they signed.",
    "other": "",
}

ROLES = {
    "rate_confirmation": "carrier", "bill_of_lading": "shipper, driver, receiver",
    "delivery_order": "receiver", "proof_of_delivery": "receiver, driver", "other": "carrier, shipper, driver, receiver",
}

SIGNATURE_MARKS = ("empty", "signature", "initials", "typed_name", "stamp")

# Package codes printed on BOLs and delivery orders -> one word per package type
PACKAGE_TYPES = {
    "ca": "cartons", "ctn": "cartons", "ctns": "cartons", "carton": "cartons", "cartons": "cartons",
    "box": "cartons", "boxes": "cartons", "bx": "cartons",
    "pl": "pallets", "plt": "pallets", "plts": "pallets", "pallet": "pallets", "pallets": "pallets",
    "sk": "skids", "skd": "skids", "skid": "skids", "skids": "skids",
    "pc": "pieces", "pcs": "pieces", "piece": "pieces", "pieces": "pieces",
    "cr": "crates", "crate": "crates", "crates": "crates", "dr": "drums", "drum": "drums", "drums": "drums",
    "bundle": "bundles", "bundles": "bundles",
    # Georgian
    "პალეტი": "pallets", "კოლოფი": "cartons", "ყუთი": "boxes", "ცალი": "pieces", "შეკვრა": "bundles",
    "კასრი": "drums", "ტომარა": "bags",
}

_TEXT = {"type": ["string", "null"]}
_NUMBER = {"type": ["number", "null"]}
_STOP = {"type": "object", "properties": {"name": _TEXT, "address": _TEXT, "date": _TEXT, "time": _TEXT},
         "required": ["name", "address", "date", "time"]}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "issuer": _TEXT, "issued_date": _TEXT, "load_number": _TEXT,
        "references": {"type": "array", "items": {
            "type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
            "required": ["label", "value"]}},
        "carrier": _TEXT,
        "pickup": _STOP, "delivery": _STOP,
        "commodity": _TEXT,
        "equipment": _TEXT,
        "pieces": {"type": ["integer", "null"]},
        "packages": {"type": "array", "items": {
            "type": "object", "properties": {"type": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["type", "count"]}},
        "weight_as_printed": _TEXT,
        "weight": _NUMBER,
        "weight_unit": {"type": ["string", "null"], "enum": ["lb", "kg", None]},
        "rate": _NUMBER, "currency": _TEXT,
        "signatures": {"type": "array", "items": {
            "type": "object",
            "properties": {"role": {"type": "string", "enum": ["carrier", "shipper", "driver", "receiver"]},
                           "mark": {"type": "string", "enum": list(SIGNATURE_MARKS)},
                           "signed": {"type": "boolean"}, "name": _TEXT, "initials": _TEXT, "date": _TEXT},
            "required": ["role", "mark", "signed", "name", "initials", "date"]}},
        "handwritten_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["issuer", "issued_date", "load_number", "references", "carrier", "pickup", "delivery",
                 "commodity", "equipment", "pieces", "packages", "weight_as_printed", "weight", "weight_unit", "rate", "currency",
                 "signatures", "handwritten_notes"],
}


# ---------------------------------------------------------------- Gemini calls

def _check_allowed(path):
    parts = {p.lower() for p in Path(path).resolve().parts}
    if "originals" in parts:
        raise ReadingFailed(f"{path} is an original document: only anonymized copies may be sent to Gemini")
    if Path(path).suffix.lower() not in MIME_TYPES:
        raise ReadingFailed(f"{Path(path).name}: unsupported file type (PDF, JPG, PNG or WEBP only)")


class GeminiReader:
    """Sends one document at a time to Gemini; tries the models in order, one quick retry on 429/503."""

    def __init__(self, models=None, on_status=None):
        self.models = list(models or MODELS)
        self.on_status = on_status or (lambda text: None)
        self.client = genai.Client(http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1), timeout=REQUEST_TIMEOUT_S * 1000))

    def _ask(self, path, prompt, schema):
        _check_allowed(path)
        document = types.Part.from_bytes(data=Path(path).read_bytes(), mime_type=MIME_TYPES[Path(path).suffix.lower()])
        return self.generate([document, prompt], schema, label=Path(path).name)

    def generate(self, contents, schema, label="question"):
        """One JSON answer from the first model that gives one (also used by rag.py for questions)."""
        config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema)
        failures, step_started = [], time.time()
        for model in self.models:
            for wait in [0] + RETRY_WAITS_S:
                left = STEP_DEADLINE_S - (time.time() - step_started) - wait
                if left < MIN_CALL_S:
                    failures.append(f"gave up after {STEP_DEADLINE_S} s")
                    raise ReadingFailed("; ".join(dict.fromkeys(failures)))
                if wait:
                    time.sleep(wait)
                started = time.time()
                limit = min(REQUEST_TIMEOUT_S, left)   # never past the step's deadline
                try:
                    response = call_with_deadline(
                        lambda: self.client.models.generate_content(model=model, contents=contents, config=config), limit)
                    if not response.text:
                        raise ReadingFailed("empty response")
                    self.on_status(f"{label}: {model} answered in {time.time() - started:.1f}s")
                    return json.loads(response.text), {"model": model, "seconds": round(time.time() - started, 1)}
                except errors.APIError as exc:
                    failures.append(f"{model}: {exc.code} {exc.status or ''}".strip())
                    self.on_status(f"{label}: {model} error {exc.code}")
                    if exc.code not in RETRY_SAME_MODEL_CODES:
                        break
                except (ReadingFailed, json.JSONDecodeError) as exc:
                    failures.append(f"{model}: {exc}")
                    break
                except CallTimedOut:
                    failures.append(f"{model}: no answer within {limit:.0f} s")
                    self.on_status(f"{label}: {model} gave no answer within {limit:.0f}s")
                    break
                except Exception as exc:  # network errors: next model
                    failures.append(f"{model}: {type(exc).__name__}")
                    break
        raise ReadingFailed("; ".join(dict.fromkeys(failures)))

    def classify(self, path):
        answer, meta = self._ask(path, CLASSIFY_PROMPT, CLASSIFY_SCHEMA)
        return answer, meta

    def extract(self, path, kind):
        prompt = EXTRACT_RULES.format(kind_label=kind.replace("_", " "), roles=ROLES.get(kind, ROLES["other"]),
                                      kind_hint=KIND_HINTS.get(kind, ""))
        return self._ask(path, prompt, EXTRACT_SCHEMA)


class CachedReader:
    """Saves every answer as JSON in `folder`, and reuses saved answers instead of calling Gemini again.

    by_content=False (the eval): answers are saved under the file name, one folder per pair.
    by_content=True (the dashboard): under a hash of the file's bytes, so the same document uploaded
    again, under any name, is never sent to Gemini twice. Upload the demo documents once before the demo
    and they show instantly even when Gemini is busy.

    An extraction saved with an older PROMPT_VERSION is asked again; if Gemini can't answer, the older
    answer is used and marked "stale". reader=None: saved answers only, whatever their version
    (re-grading with no Gemini calls at all).

    also_from: read-only folders searched after `folder`, never written to. The dashboard passes
    demo_documents/ge/_readings/ (the Georgian demo documents' readings, shipped with the app), so the
    deployed demo answers even when Gemini is busy and the private cache is empty (Cloud Run)."""

    def __init__(self, folder, reader=None, by_content=False, also_from=()):
        self.folder, self.reader, self.by_content = Path(folder), reader, by_content
        self.also_from = [Path(f) for f in also_from]
        self.folder.mkdir(parents=True, exist_ok=True)

    def _key(self, path):
        if self.by_content:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:24]
        return Path(path).name

    def _current(self, step, data):
        return self.reader is None or step != "extract" or data["meta"].get("prompt_version") == PROMPT_VERSION

    def _saved(self, path, step):
        """The saved answer: the first one from the current prompt, else the first found (maybe stale)."""
        found = []
        for folder in [self.folder, *self.also_from]:
            saved = folder / f"{self._key(path)}.{step}.json"
            if saved.exists():
                found.append(json.loads(saved.read_text(encoding="utf-8")))
        return next((d for d in found if self._current(step, d)), found[0] if found else None)

    def _cached(self, path, step, call):
        data = self._saved(path, step)
        if data and self._current(step, data):
            return data["answer"], {**data["meta"], "cached": True}
        if self.reader is None:
            raise ReadingFailed(f"no saved {step} answer for {Path(path).name} in {self.folder}")
        try:
            answer, meta = call()
        except ReadingFailed:
            if data:   # Gemini unavailable: an answer from an older prompt beats no answer
                return data["answer"], {**data["meta"], "cached": True, "stale": True}
            raise
        meta = {**meta, "prompt_version": PROMPT_VERSION}
        # Documents are read in parallel: write to a temporary file, then rename, so a half-written answer
        # is never read. Saving is only a shortcut: if it fails, the answer is still returned.
        saved = self.folder / f"{self._key(path)}.{step}.json"
        temporary = saved.with_name(f"{saved.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            temporary.write_text(json.dumps({"answer": answer, "meta": meta}, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
            os.replace(temporary, saved)
        except OSError:
            temporary.unlink(missing_ok=True)
        return answer, meta

    def classify(self, path):
        return self._cached(path, "classify", lambda: self.reader.classify(path))

    def extract(self, path, kind):
        return self._cached(path, "extract", lambda: self.reader.extract(path, kind))


# ---------------------------------------------------------------- Gemini's answer -> document format

def _unit(value):
    value = (value or "").strip().lower().rstrip(".")
    if value in ("lb", "lbs", "pound", "pounds", "#"):
        return "lb"
    if value in ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "კგ", "კილოგრამი"):
        return "kg"
    return None


_PRINTED_UNIT = re.compile(r"(\d\s*#)|\b(lbs?|pounds?|kgs?|kilos?|kilograms?|კგ|კილოგრამი)\b", re.IGNORECASE)


def printed_unit(weight_as_printed):
    """The weight unit actually written in the printed weight text, or None. Python decides, not Gemini:
    Gemini said "lb" for "WEIGHT: 509.00" although no unit is printed (pair-01, 23 Nov)."""
    match = _PRINTED_UNIT.search(weight_as_printed or "")
    if not match:
        return None
    return "lb" if match.group(1) else _unit(match.group(2))


def _letters(text):
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def to_document(name, classified, answer):
    """Turn Gemini's JSON into the schema.py format (lists of label/value pairs become dicts)."""
    doc = empty_document(name, classified.get("kind") if classified.get("kind") in DOCUMENT_KINDS else "other")
    doc["says_not_a_bol"] = bool(classified.get("says_not_a_bol"))
    for field in ("issuer", "issued_date", "load_number", "carrier", "commodity", "equipment", "pieces", "weight", "rate",
                  "currency"):
        doc[field] = answer.get(field)
    # The unit counts only if it is in the printed text. Answers saved before weight_as_printed existed
    # (no such key) keep Gemini's unit.
    if "weight_as_printed" in answer:
        doc["weight_unit"] = printed_unit(answer.get("weight_as_printed"))
    else:
        doc["weight_unit"] = _unit(answer.get("weight_unit"))
    for stop in ("pickup", "delivery"):
        doc[stop].update({k: v for k, v in (answer.get(stop) or {}).items() if k in doc[stop]})
    doc["references"] = {r["label"]: r["value"] for r in answer.get("references") or [] if r.get("value")}
    packages = {}
    for p in answer.get("packages") or []:
        if p.get("type") and p.get("count") is not None:
            kind = p["type"].strip().lower().rstrip(".")
            kind = PACKAGE_TYPES.get(kind, kind)
            packages[kind] = packages.get(kind, 0) + p["count"]
    doc["packages"] = packages
    # An RC's piece count IS its one package count ("ადგილები / Pieces: 20 პალეტი"): gemini-3.1-flash-lite put
    # the 20 only under packages and the RC was reported as not stating its pieces (ge-05, 24 Nov). Only for
    # one package type on an RC: a BOL's "8 cartons + 2 pallets" stays as read (pair-04).
    if doc["pieces"] is None and doc["kind"] == "rate_confirmation" and len(packages) == 1:
        doc["pieces"] = next(iter(packages.values()))
    signatures = {}
    for line in answer.get("signatures") or []:
        role = line.get("role")
        # Python decides "signed" from what is on the line: Gemini called an undated-signature line with
        # only the driver's date "signed" (pair-03 BOL, 23 Nov)
        signed = line["mark"] != "empty" if line.get("mark") in SIGNATURE_MARKS else bool(line.get("signed"))
        entry = {"signed": signed, "mark": line.get("mark"), "name": line.get("name") if signed else None,
                 "initials": line.get("initials") if signed else None, "date": line.get("date")}
        if role not in signatures or (entry["signed"] and not signatures[role]["signed"]):
            signatures[role] = entry           # a role listed twice: keep the signed line
    doc["signatures"] = signatures
    # A signature is not a note: Gemini listed the RC signer "Daniel Mercer" as handwritten (pair-01, 23 Nov)
    signed_as = {_letters(v) for line in signatures.values() for v in (line.get("name"), line.get("initials")) if v}
    doc["handwritten_notes"] = [n for n in answer.get("handwritten_notes") or [] if n and _letters(n) not in signed_as]
    return doc

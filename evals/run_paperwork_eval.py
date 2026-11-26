"""Paperwork agent eval: are the Python checks right, and does Gemini read the documents correctly?

    python evals/run_paperwork_eval.py                          the checks on the answer keys: no Gemini
    python evals/run_paperwork_eval.py --source gemini          the whole LangGraph flow: ~2 Gemini calls per document
    python evals/run_paperwork_eval.py --source gemini --models gemini-3.1-flash-lite
    python evals/run_paperwork_eval.py --source gemini --set ge                 only the Georgian demo documents
    python evals/run_paperwork_eval.py --resume evals/results/paperwork/<run>     finish a run that stopped
    python evals/run_paperwork_eval.py --regrade evals/results/paperwork/<run>    re-score saved answers, no calls
    python evals/run_paperwork_eval.py --source shipped     the Georgian readings that ship with the app, no calls

Source "answer_key": each pair's expected.json values are converted to the document format
(paperwork/schema.py) and run through validate + cross_check. That tests the checks alone, on what a
careful person read. Also runs fixed address / company-name cases and planted mistakes.

Source "gemini": the documents go through the graph (classify -> extract -> validate -> cross_check).
Every Gemini answer is saved in evals/results/paperwork/<run>/<pair>/ (git-ignored), so --regrade can
re-score after a change to the checks without new calls. Scored per pair:
- reading: each value in the answer key compared with what Gemini read (addresses and company names with
  the same tolerant matching as the checks), and every `must_not_invent` blank still blank;
- checks: as for the answer keys, on what Gemini read.

A pair's checks pass when every `must_flag` check is reported as a problem, no other problem is reported
(a false alarm), no finding uses a check named in `must_not_flag`, and problems that need a follow-up
step carry one.
The documents are private: documents/us/ is git-ignored and only exists on this computer. Only these
anonymized copies are sent to Gemini.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paperwork.addresses import compare_addresses, same_company  # noqa: E402
from paperwork.pipeline import notes, problems, run_checks  # noqa: E402
from paperwork.schema import empty_document  # noqa: E402

PAIRS_DIR = ROOT / "documents" / "us"           # real, anonymized (private: only on the owner's computer)
GE_DIR = ROOT / "demo_documents" / "ge"         # simulated Georgian demo set (generate_demo_documents.py)


def pair_dirs():
    """Every load with an answer key: the US test set (if present on this computer) and the Georgian demo set."""
    found = []
    for base, pattern in ((PAIRS_DIR, "pair-*"), (GE_DIR, "ge-*")):
        found += sorted(p for p in base.glob(pattern) if (p / "expected.json").exists())
    return found


def pair_dir(name):
    return next(p for p in pair_dirs() if p.name == name)


ADDRESS_CASES = [
    # Georgian (the demo set): street name, type, then number; the city decides like a ZIP
    ("ბათუმი, ფარნავაზ მეფის ქ. 112", "ქ. ბათუმი, ფარნავაზ მეფის ქუჩა №112, საწყობი 3", "same"),
    ("ქუთაისი, რუსთაველის გამზ. 8", "ქ. ქუთაისი, შოთა რუსთაველის გამზირი №8", "same"),
    ("თბილისი, დავით აღმაშენებლის ხეივანი №160", "ქ. თბილისი, აღმაშენებლის ხეივ. 160", "same"),
    ("ბათუმი, ჭავჭავაძის ქ. 54", "ბათუმი, ტბელ აბუსერიძის ქ. 9", "different"),
    ("ბათუმი, ფარნავაზ მეფის ქ. 112", "ბათუმი, ფარნავაზ მეფის ქ. 121", "different"),
    ("ფოთი, აღმაშენებლის ქ. 10", "ქუთაისი, აღმაშენებლის ქ. 10", "different"),
    ("ქუთაისი, რუსთაველის გამზ. 8", "ქუთაისი, რუსთაველის ქ. 8", "different"),
    ("რუსთავი", "რუსთავი, მეგობრობის გამზ. 21", "unclear"),
    # US
    # (a, b, expected) taken from the test set, plus variants that must NOT match
    ("3168 W Linden St, Brookline, MI 49017",
     "Ridley Industrial Park, 3168 W. Linden St./PLANT 4, Brookline MI 49017", "same"),
    ("2640 Juniper Ln, Hollins, SD 57012", "2640 Juniper Lane, PO Box 384, Hollins, SD 57012-8261", "same"),
    ("672 Orchard Dr, Oakridge, MN 55306", "672 Orchard Dr, Oakridge MN 553061120", "same"),
    ("2417 Birchwood Drive, Halston, WI 53142", "2417 Birchwood Drive, Halston WI 53142", "same"),
    ("31570 Lakeview Park Rd Ste 517, Fernvale KS 66218",
     "31570 Lakeview Park Road, Suite 517, Fernvale, KS 66218-1234", "same"),
    ("3168 W Linden St, Brookline, MI 49017", "PO Box 513, Brookline MI 49018", "different"),
    ("672 Orchard Dr, Oakridge, MN 55306", "627 Orchard Dr, Oakridge, MN 55306", "different"),
    ("2640 Juniper Ln, Hollins, SD 57012", "2640 Juniper Ave, Hollins, SD 57012", "different"),
    ("3168 W Linden St, Brookline, MI 49017", "3168 E Linden St, Brookline, MI 49017", "different"),
    ("2417 Birchwood Drive, Halston, WI 53142", "2417 Birchwood Drive, Halston, WI 53143", "different"),
    ("Fernvale KS 66218", "31570 Lakeview Park Rd Ste 517, Fernvale KS 66218", "unclear"),
]

def _doc(docs, kind):
    return next(d for d in docs if d["kind"] == kind)


def _set(kind, path, value):
    """A change to one value of one document, e.g. _set("bill_of_lading", "delivery.address", "...")."""
    def change(docs):
        target = _doc(docs, kind)
        *parents, last = path.split(".")
        for part in parents:
            target = target[part]
        target[last] = value
    return change


# Planted mistakes: a real pair with one value changed. `expect` is the check that must now be reported
# with that severity; expect=None means the change is NOT a mistake and must add no problem at all.
PLANTED = [
    ("pair-04", "delivery ZIP changed on the delivery order",
     _set("delivery_order", "delivery.address", "2640 Juniper Lane, Hollins, SD 57021"), "address_mismatch", "problem"),
    ("pair-03", "pickup street number changed on the BOL",
     _set("bill_of_lading", "pickup.address", "2471 Birchwood Drive, Halston WI 53142"), "address_mismatch", "problem"),
    ("pair-03", "BOL weight 3000 lb", _set("bill_of_lading", "weight", 3000.0), "weight_mismatch", "problem"),
    ("pair-03", "BOL weight written as 136 kg (= 300 lb)",
     lambda docs: (_set("bill_of_lading", "weight", 136.0)(docs), _set("bill_of_lading", "weight_unit", "kg")(docs)),
     None, None),
    ("pair-03", "BOL with 3 pallets", _set("bill_of_lading", "packages", {"cartons": 8, "pallets": 3}),
     "pieces_mismatch", "problem"),
    ("pair-01", "RC made out to another carrier", _set("rate_confirmation", "carrier", "Northbound Trucking"),
     "carrier_not_ours", "problem"),
    ("pair-03", "BOL carrier written as 'WARP CORP'", _set("bill_of_lading", "carrier", "WARP CORP"), None, None),
    ("pair-03", "RC made out to another carrier, BOL names us",
     lambda docs: (_set("rate_confirmation", "carrier", "Northbound Trucking")(docs),
                   _set("bill_of_lading", "carrier", "Warp Corporation")(docs)),
     "carrier_not_ours", "problem"),
    ("pair-04", "POD not signed", _set("proof_of_delivery", "signatures",
                                       {"receiver": {"signed": False, "name": None, "initials": None, "date": None}}),
     "pod_not_signed", "problem"),
    ("pair-04", "POD signed two days late", _set("proof_of_delivery", "signatures.receiver.date", "2026-11-21"),
     "late_delivery", "note"),
    ("pair-02", "RC delivery dated before pickup", _set("rate_confirmation", "delivery.date", "2026-11-10"),
     "delivery_before_pickup", "problem"),
    ("pair-03", "BOL dated by the driver a day after pickup",
     _set("bill_of_lading", "signatures.driver.date", "2026-11-21"), "date_mismatch", "note"),
    # Georgian demo set
    ("ge-02", "BOL delivery in another Kutaisi street",
     _set("bill_of_lading", "delivery.address", "ქ. ქუთაისი, ჯავახიშვილის ქ. №8"), "address_mismatch", "problem"),
    ("ge-02", "BOL names another carrier", _set("bill_of_lading", "carrier", "Lomi Trans Group LLC"),
     "carrier_mismatch", "problem"),
    ("ge-06", "POD receiver's name printed", _set("proof_of_delivery", "signatures.receiver.name", "ეკა გელაშვილი"),
     None, None),
    ("ge-06", "POD not signed at all", _set("proof_of_delivery", "signatures.receiver.signed", False),
     "pod_not_signed", "problem"),
    ("ge-01", "RC not signed by us yet", _set("rate_confirmation", "signatures.carrier.signed", False),
     "rc_not_signed", "note"),
]

# Problems that must tell the dispatcher what to do next (decided 23-24 Nov), and a phrase the action must contain
REQUIRED_ACTIONS = {
    "carrier_not_ours": "revised rate confirmation",     # the broker sends a revised RC
    "carrier_mismatch": "Ask the broker",
    "address_mismatch": "acceptable for billing",       # ask the broker if the paperwork is OK for billing
    "pod_receiver_unnamed": "receiver's name printed",   # the driver gets the receiver's printed name
    "pod_not_signed": "Ask the driver",
}


def missing_actions(state):
    return [f for f in problems(state)
            if f["check"] in REQUIRED_ACTIONS and REQUIRED_ACTIONS[f["check"]] not in (f.get("action") or "")]


COMPANY_CASES = [
    ("k207 Harbor Distribution Corp.", "K207 HARBOR DISTRIBUTION CORPORATI", True),   # cut off by the form
    ("Copperfield", "Copperfield Logistics", True),
    ("Hollis Surgical Inc", "Hollis, Inc.", True),
    ("Warp Corporation", "WARP CORP", True),
    ("Warp Corporation", "Northbound Trucking", False),
    ("Quillmark Logistics Inc", "Keystone Freight Systems, Inc", False),
    ("Meridex - Illinois", "Meridex", True),
    ("შპს „კარგონავტ ლოჯისტიკი“", "შპს \"კარგონავტ ლოჯისტიკი\"", True),
    ("შპს „კარგონავტ ლოჯისტიკი“", "კარგონავტ ლოჯისტიკი", True),
    ("შპს „კარგონავტ ლოჯისტიკი“", "შპს „ლომი ტრანს ჯგუფი“", False),
    ("შპს „ალაზანი ფრეით“", "შპს „რიონი კარგო დესკი“", False),
]


# ---------------------------------------------------------------- answer key -> document format

def _clean(value):
    """Drop "[on]"-style additions: in the answer keys they mark letters the document itself cut off."""
    if isinstance(value, str):
        return re.sub(r"\[[^\]]*\]", "", value).strip()
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _signature(value, signed_date=None):
    """Answer keys write a signature as a name, as "initials 'TKW' (...)", or null for an empty line."""
    if not value:
        return {"signed": False, "name": None, "initials": None, "date": signed_date}
    if "initial" in value.lower():
        quoted = re.search(r"'([^']+)'", value)
        return {"signed": True, "name": None, "initials": quoted.group(1) if quoted else value, "date": signed_date}
    return {"signed": True, "name": value, "initials": None, "date": signed_date}


def _stop(raw):
    raw = raw or {}
    return {"name": raw.get("name"), "address": raw.get("address"), "date": raw.get("date"),
            "time": raw.get("time") or raw.get("window")}


def document_from_answer_key(key, raw, file_name):
    raw = _clean(raw)
    if key == "rc":
        doc = empty_document(file_name, "rate_confirmation")
        doc.update(issuer=raw.get("broker"), issued_date=raw.get("issued_date"), load_number=raw.get("load_number"),
                   references=raw.get("other_references") or {}, carrier=raw.get("carrier"),
                   pickup=_stop(raw.get("pickup")), delivery=_stop(raw.get("delivery")),
                   commodity=raw.get("commodity"), pieces=raw.get("pieces"),
                   weight=raw.get("weight"), weight_unit=raw.get("weight_unit"),
                   rate=raw.get("rate_usd"), currency="USD" if raw.get("rate_usd") is not None else None,
                   signatures={"carrier": _signature(raw.get("signed_by"), raw.get("signed_date"))})
    elif key == "bol":
        doc = empty_document(file_name, "bill_of_lading")
        doc.update(issuer=raw.get("issued_by"), issued_date=(raw.get("printed") or "")[:10] or None,
                   references=raw.get("references") or {}, carrier=raw.get("carrier"),
                   pickup=_stop(raw.get("shipper")), delivery=_stop(raw.get("ship_to")),
                   commodity=raw.get("commodity"), packages=raw.get("quantity") or {},
                   weight=raw.get("weight"), weight_unit=raw.get("weight_unit"),
                   signatures={"driver": _signature(raw.get("driver_signature"), raw.get("driver_date")),
                               "shipper": _signature(raw.get("shipper_signature"), raw.get("shipper_date"))})
    elif key == "delivery_order":
        doc = empty_document(file_name, "delivery_order")
        doc.update(says_not_a_bol=raw.get("says_not_a_bol"), issuer=raw.get("issued_by"),
                   issued_date=raw.get("date"), references=raw.get("references") or {},
                   carrier=raw.get("delivering_carrier"),
                   pickup=_stop(raw.get("pick_up_from")), delivery=_stop(raw.get("deliver_to")),
                   commodity=raw.get("description"), pieces=raw.get("pieces"),
                   weight=raw.get("weight"), weight_unit=raw.get("weight_unit"),
                   signatures={"receiver": _signature(raw.get("received_signature"))},
                   handwritten_notes=[raw["handwritten_note"]] if raw.get("handwritten_note") else [])
    elif key == "pod":
        doc = empty_document(file_name, "proof_of_delivery")
        doc.update(signatures={"receiver": _signature(raw.get("signed_by"), raw.get("signed_date"))})
    else:
        raise ValueError(f"no converter for answer-key section '{key}'")
    return doc


def documents_from_answer_key(expected):
    if expected.get("format") == "schema":
        # The demo set's keys are already in the document format (written by generate_demo_documents.py)
        return [{**empty_document(file_name), **json.loads(json.dumps(expected["schema"][key])), "name": file_name}
                for key, file_name in expected["documents"].items()]
    return [document_from_answer_key(key, expected[key], file_name)
            for key, file_name in expected["documents"].items()]


# ---------------------------------------------------------------- scoring

def score_pair(expected, state):
    reported = problems(state)
    reported_checks = {f["check"] for f in reported}
    must_flag = {item["check"] for item in expected.get("must_flag", [])}
    must_not_flag = {item["check"] for item in expected.get("must_not_flag", [])}

    # must_note (demo set): notes that must be there, e.g. "weight not stated" on an RC with a blank weight
    must_note = {item["check"] for item in expected.get("must_note", [])}
    noted = {f["check"] for f in notes(state)}

    caught = sorted(must_flag & reported_checks) + sorted(must_note & noted)
    missed = sorted(must_flag - reported_checks) + sorted(must_note - noted)
    false_alarms = [f for f in reported if f["check"] not in must_flag]
    false_alarms += [f for f in notes(state) if f["check"] in must_not_flag]
    no_action = missing_actions(state)
    draft = check_draft(expected, state)
    return {"caught": caught, "missed": missed, "false_alarms": false_alarms, "no_action": no_action,
            "draft": draft, "passed": not missed and not false_alarms and not no_action and not draft}


DRAFT_VALUES = ("origin_city", "destination_city", "truck_type", "weight_kg", "customer_price_gel", "pickup_date")


def check_draft(expected, state):
    """The draft plan (paperwork/draft.py) against the key's "draft": available or refused (and why),
    what is missing, and the values it maps. Returns a list of differences (empty = right)."""
    want = expected.get("draft")
    if want is None:
        return []
    plan = state.get("draft_plan") or {"available": False, "blocked": [], "missing": [], "fields": {}}
    wrong = []
    if bool(plan.get("available")) != want["available"]:
        wrong.append(f"available: expected {want['available']}, got {plan.get('available')} "
                     f"(blocked: {[b['reason'] for b in plan.get('blocked', [])]})")
    got_blocked = {b["reason"] for b in plan.get("blocked", [])}
    if set(want.get("blocked", [])) != got_blocked:
        wrong.append(f"blocked: expected {sorted(want.get('blocked', []))}, got {sorted(got_blocked)}")
    if want["available"]:
        if sorted(want.get("missing", [])) != sorted(plan.get("missing", [])):
            wrong.append(f"missing: expected {want.get('missing')}, got {plan.get('missing')}")
        for key in DRAFT_VALUES:
            if key in want and plan["fields"].get(key) != want[key]:
                wrong.append(f"{key}: expected {want[key]!r}, got {plan['fields'].get(key)!r}")
        if plan.get("available"):
            problem = try_draft(plan)
            if problem:
                wrong.append(f"could not be created: {problem}")
    return wrong


def try_draft(plan):
    """Create the draft for real (placeholders for missing values), then cancel it: proves the whole path
    works. Nothing is written to the database (only Confirm writes)."""
    from marketplace import reject_draft
    from paperwork.draft import create_draft
    from datetime import date, timedelta
    placeholders = {"weight_kg": 1000, "customer_price_gel": 500, "truck_type": "dry_van",
                    "pickup_date": (date.today() + timedelta(days=10)).isoformat(),
                    "origin_city": "Tbilisi", "destination_city": "Batumi"}
    values = {k: placeholders[k] for k in plan.get("missing", [])}
    # The demo documents' dates are fixed (Nov-Dec 2026): a date already past is moved forward, so the check
    # tests the path, not the calendar
    if plan["fields"].get("pickup_date") and plan["fields"]["pickup_date"] < date.today().isoformat():
        values["pickup_date"] = placeholders["pickup_date"]
    result = create_draft(plan, values, user_id=0)
    if "draft_id" in result:
        reject_draft(0, result["draft_id"])
        return None
    return result.get("error") or result


def run_unit_cases():
    failures = 0
    for a, b, want in ADDRESS_CASES:
        got = compare_addresses(a, b)
        if got["result"] != want:
            failures += 1
            print(f"  FAIL address: '{a}' / '{b}': expected {want}, got {got['result']} {got['reasons']}")
    for a, b, want in COMPANY_CASES:
        if same_company(a, b) != want:
            failures += 1
            print(f"  FAIL company: '{a}' / '{b}': expected {'same' if want else 'different'}")
    total = len(ADDRESS_CASES) + len(COMPANY_CASES)
    print(f"Address and company cases: {total - failures}/{total}")
    return failures


def run_pairs(verbose):
    dirs = pair_dirs()
    if not dirs:
        print(f"No answer keys in {PAIRS_DIR} or {GE_DIR}.")
        return 1
    if not PAIRS_DIR.exists():
        print(f"(No {PAIRS_DIR}: the US documents are private and only exist on the owner's computer.)")
    failed = 0
    for pair_dir in dirs:
        expected = json.loads((pair_dir / "expected.json").read_text(encoding="utf-8"))
        state = run_checks(documents_from_answer_key(expected), expected["our_carrier"])
        result = score_pair(expected, state)
        failed += not result["passed"]

        print(f"\n{pair_dir.name}: {'PASS' if result['passed'] else 'FAIL'}"
              f"  (caught {len(result['caught'])}/{len(result['caught']) + len(result['missed'])},"
              f" false alarms {len(result['false_alarms'])})")
        for check in result["missed"]:
            print(f"  MISSED   {check}")
        for f in result["false_alarms"]:
            print(f"  FALSE    {f['check']} ({f['severity']}): {f['detail']}")
        for f in result["no_action"]:
            print(f"  NOACTION {f['check']}: expected an action containing '{REQUIRED_ACTIONS[f['check']]}'")
        for difference in result["draft"]:
            print(f"  DRAFT    {difference}")
        plan = state.get("draft_plan")
        if verbose and plan:
            f = plan["fields"]
            print(f"  draft    {'possible' if plan['available'] else 'refused'}"
                  f"{': ' + ', '.join(b['reason'] for b in plan['blocked']) if plan['blocked'] else ''}"
                  f" | {f.get('origin_city')} -> {f.get('destination_city')}, {f.get('truck_type')}, "
                  f"{f.get('weight_kg')} kg, {f.get('customer_price_gel')} GEL, pickup {f.get('pickup_date')}"
                  f"{' | missing: ' + ', '.join(plan['missing']) if plan['missing'] else ''}")
        if verbose:
            for f in problems(state):
                print(f"  problem  {f['check']}: {f['detail']}")
                if f.get("action"):
                    print(f"           -> {f['action']}")
            for f in notes(state):
                print(f"  note     {f['check']}: {f['detail']}")
            for a in state["agreements"]:
                print(f"  ok       {a['check']}: {a['detail']}")
    print(f"\nPairs: {len(dirs) - failed}/{len(dirs)}")
    return failed


def _same_in_both_languages(documents_en, documents_ka, our_carrier):
    """Both languages must report the same checks with the same severity and actions; only the words differ."""
    def shape(state):
        return ([(f["check"], f["severity"], bool(f["action"]), bool(f["detail"])) for f in state["findings"]],
                [(a["check"], bool(a["detail"])) for a in state["agreements"]])
    try:
        en = run_checks(documents_en, our_carrier, lang="en")
        ka = run_checks(documents_ka, our_carrier, lang="ka")
    except (KeyError, IndexError, ValueError) as exc:   # a missing or broken sentence in wording.py
        return f"wording error: {exc!r}"
    return None if shape(en) == shape(ka) else "the Georgian run reports different findings"


def run_wording_test():
    """Every pair and every planted mistake once more in Georgian (paperwork/wording.py)."""
    failed = 0
    available = {p.name for p in pair_dirs()}
    cases = [(name, None) for name in sorted(available)]
    cases += [(pair, change) for pair, _, change, _, _ in PLANTED if pair in available]
    for pair, change in cases:
        expected = json.loads((pair_dir(pair) / "expected.json").read_text(encoding="utf-8"))
        docs_en, docs_ka = documents_from_answer_key(expected), documents_from_answer_key(expected)
        if change:
            change(docs_en)
            change(docs_ka)
        problem = _same_in_both_languages(docs_en, docs_ka, expected["our_carrier"])
        if problem:
            failed += 1
            print(f"  FAIL wording {pair}: {problem}")
    print(f"Georgian wording: {len(cases) - failed}/{len(cases)}")
    return failed


def run_planted():
    failed = 0
    available = {p.name for p in pair_dirs()}
    planted = [p for p in PLANTED if p[0] in available]
    for pair, description, change, expect, severity in planted:
        expected = json.loads((pair_dir(pair) / "expected.json").read_text(encoding="utf-8"))
        before = run_checks(documents_from_answer_key(expected), expected["our_carrier"])
        docs = documents_from_answer_key(expected)
        change(docs)
        after = run_checks(docs, expected["our_carrier"])
        if expect:
            ok = (any(f["check"] == expect and f["severity"] == severity for f in after["findings"])
                  and not missing_actions(after))
            want = f"{expect} ({severity}) with its action"
        else:
            ok = {f["check"] for f in problems(after)} <= {f["check"] for f in problems(before)}
            want = "no new problem"
        if not ok:
            failed += 1
            got = ", ".join(f"{f['check']} ({f['severity']})" for f in after["findings"]) or "nothing"
            print(f"  FAIL planted {pair}, {description}: expected {want}, got {got}")
    print(f"Planted mistakes: {len(planted) - failed}/{len(planted)}")
    return failed


# ---------------------------------------------------------------- reading (Gemini) vs the answer key

def _plain(value):
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def _same_text(a, b):
    return _plain(a) == _plain(b)


def _same_number(a, b):
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def compare_reading(want, got, also=None):
    """Every value the answer key has for one document, compared with what Gemini read.
    `also`: other acceptable readings per field (the demo set prints names in Georgian AND English, so
    either one read is right). Returns a list of (field, ok, wanted, got)."""
    rows = []
    also = also or {}

    def row(field, ok, w, g):
        rows.append((field, bool(ok), w, g))

    def company_ok(field, w, g):
        return bool(g) and any(same_company(x, g) for x in [w] + also.get(field, []))

    row("kind", want["kind"] == got["kind"], want["kind"], got["kind"])
    if want.get("says_not_a_bol") is not None:
        row("says_not_a_bol", bool(want["says_not_a_bol"]) == bool(got.get("says_not_a_bol")),
            want["says_not_a_bol"], got.get("says_not_a_bol"))
    for field in ("issuer", "carrier"):
        if want.get(field):
            row(field, company_ok(field, want[field], got.get(field)), want[field], got.get(field))
    if want.get("equipment"):
        row("equipment", _plain(want["equipment"]) in _plain(got.get("equipment") or ""), want["equipment"], got.get("equipment"))
    if want.get("load_number"):
        row("load_number", _same_text(want["load_number"], got.get("load_number") or ""), want["load_number"], got.get("load_number"))
    if want.get("issued_date"):
        row("issued_date", want["issued_date"] == got.get("issued_date"), want["issued_date"], got.get("issued_date"))
    for stop in ("pickup", "delivery"):
        w, g = want[stop], got[stop]
        if w.get("name"):
            row(f"{stop}.name", company_ok(f"{stop}.name", w["name"], g.get("name")), w["name"], g.get("name"))
        if w.get("address"):
            row(f"{stop}.address", g.get("address") and compare_addresses(w["address"], g["address"])["result"] == "same",
                w["address"], g.get("address"))
        if w.get("date"):
            row(f"{stop}.date", w["date"] == g.get("date"), w["date"], g.get("date"))
    for field in ("pieces", "weight", "rate"):
        if want.get(field) is not None:
            row(field, _same_number(want[field], got.get(field)), want[field], got.get(field))
    if want.get("weight_unit"):
        row("weight_unit", want["weight_unit"] == got.get("weight_unit"), want["weight_unit"], got.get("weight_unit"))
    for kind, count in (want.get("packages") or {}).items():
        got_count = next((n for k, n in (got.get("packages") or {}).items() if kind.rstrip("s") in k), None)
        row(f"packages.{kind}", got_count == count, count, got_count)
    # A reference counts as read when its value appears anywhere among the references Gemini returned,
    # as a value or as a label (an unlabelled number at the top of a BOL has no printed label)
    got_refs = {_plain(x) for label, value in (got.get("references") or {}).items() for x in (label, value)}
    got_refs.add(_plain(got.get("load_number") or ""))
    for label, value in (want.get("references") or {}).items():
        for one in (value if isinstance(value, list) else [value]):
            row(f"references.{label}", _plain(one) in got_refs, one, "found" if _plain(one) in got_refs else None)
    for role, line in (want.get("signatures") or {}).items():
        got_line = (got.get("signatures") or {}).get(role) or {}
        row(f"signature.{role}.signed", bool(line["signed"]) == bool(got_line.get("signed")), line["signed"], got_line.get("signed"))
        if line.get("name"):
            names = [line["name"]] + also.get(f"signature.{role}.name", [])
            row(f"signature.{role}.name", any(_same_text(n, got_line.get("name") or "") for n in names),
                line["name"], got_line.get("name"))
        if line.get("date"):
            row(f"signature.{role}.date", line["date"] == got_line.get("date"), line["date"], got_line.get("date"))
    for note in want.get("handwritten_notes") or []:
        found = any(_plain(note) in _plain(n) for n in got.get("handwritten_notes") or [])
        row("handwritten_note", found, note, got.get("handwritten_notes"))
    return rows


# must_not_invent fields in the answer keys -> what "still blank" means in the document format
SECTION_KINDS = {"rc": "rate_confirmation", "bol": "bill_of_lading", "delivery_order": "delivery_order", "pod": "proof_of_delivery"}
BLANK_TESTS = {
    "weight_unit": lambda d: d.get("weight_unit") is None,
    "weight": lambda d: d.get("weight") is None,
    "pieces": lambda d: d.get("pieces") is None,
    "commodity": lambda d: not d.get("commodity"),
    "signed_date": lambda d: not ((d["signatures"].get("carrier") or {}).get("date")),
    "driver_signature": lambda d: not ((d["signatures"].get("driver") or {}).get("signed")
                                       or (d["signatures"].get("driver") or {}).get("name")),
    "shipper_signature": lambda d: not ((d["signatures"].get("shipper") or {}).get("name")),   # initials only
    "received_signature": lambda d: not ((d["signatures"].get("receiver") or {}).get("signed")
                                         or (d["signatures"].get("receiver") or {}).get("name")),
    "receiver_name": lambda d: not ((d["signatures"].get("receiver") or {}).get("name")),   # a scribble: no name
}


def check_not_invented(expected, documents_by_file):
    """[(field, ok, why)] for every must_not_invent entry: the value must still be blank."""
    results = []
    for item in expected.get("must_not_invent", []):
        section, _, field = item["field"].rpartition(".")
        file_name = expected["documents"][section or "rc"]
        doc = documents_by_file.get(file_name)
        ok = doc is not None and BLANK_TESTS[field](doc)
        results.append((item["field"], ok, item["why"]))
    return results


def run_gemini(run_dir, models, allow_calls, verbose, only_set="all", shipped=None):
    """shipped: score the readings that ship with the app (paperwork/ship_readings.py) instead of a run's."""
    from paperwork.extract import CachedReader, GeminiReader
    from paperwork.graph import read_documents

    gemini = GeminiReader(models=models, on_status=lambda text: print(f"    {text}")) if allow_calls else None
    run_dir.mkdir(parents=True, exist_ok=True)
    dirs = [p for p in pair_dirs() if only_set == "all" or p.parent.name == only_set]
    totals = {"fields": 0, "fields_ok": 0, "blank": 0, "blank_ok": 0, "pairs_ok": 0}
    report = {}
    for pair_dir in dirs:
        expected = json.loads((pair_dir / "expected.json").read_text(encoding="utf-8"))
        print(f"\n{pair_dir.name}")
        reader = (CachedReader(shipped, by_content=True) if shipped
                  else CachedReader(run_dir / pair_dir.name, reader=gemini))
        files = [pair_dir / file_name for file_name in expected["documents"].values()]
        state = read_documents(files, expected["our_carrier"], reader=reader)
        got_by_file = {d["name"]: d for d in state.get("documents", [])}
        for call in state.get("calls", []):
            if call.get("stale"):
                print(f"  STALE    {call['file']} {call['step']}: Gemini didn't answer, an answer from an older prompt was used")

        # A document Gemini never answered for (busy, timeout) says nothing about reading or checking:
        # report it and leave the pair out of the scores; --resume fills it in later
        not_read = [f.name for f in files if f.name not in got_by_file]
        if not_read:
            totals["not_read"] = totals.get("not_read", 0) + len(not_read)
            print(f"  NOT READ {', '.join(not_read)}: Gemini didn't answer; pair left out (run --resume later)")
            report[pair_dir.name] = {"not_read": not_read, "calls": state.get("calls", [])}
            continue

        reading = []
        section_of = {file_name: section for section, file_name in expected["documents"].items()}
        for want in documents_from_answer_key(expected):
            got = got_by_file.get(want["name"])
            also = (expected.get("also_accept") or {}).get(section_of[want["name"]])
            rows = compare_reading(want, got, also) if got else [("document read", False, want["name"], None)]
            reading += [(want["name"], *r) for r in rows]
        blanks = check_not_invented(expected, got_by_file)
        checks = score_pair(expected, state)

        fields_ok = sum(ok for _, _, ok, _, _ in reading)
        blank_ok = sum(ok for _, ok, _ in blanks)
        totals["fields"] += len(reading)
        totals["fields_ok"] += fields_ok
        totals["blank"] += len(blanks)
        totals["blank_ok"] += blank_ok
        totals["pairs_ok"] += checks["passed"]

        print(f"  reading {fields_ok}/{len(reading)} values, blanks kept {blank_ok}/{len(blanks)}, "
              f"checks {'PASS' if checks['passed'] else 'FAIL'} (caught {len(checks['caught'])}/"
              f"{len(checks['caught']) + len(checks['missed'])}, false alarms {len(checks['false_alarms'])})")
        for file_name, field, ok, w, g in reading:
            if not ok:
                print(f"  WRONG    {file_name} {field}: expected {w!r}, read {g!r}")
        for field, ok, why in blanks:
            if not ok:
                print(f"  INVENTED {field}: {why}")
        for check in checks["missed"]:
            print(f"  MISSED   {check}")
        for f in checks["false_alarms"]:
            print(f"  FALSE    {f['check']} ({f['severity']}): {f['detail']}")
        if verbose:
            for f in state.get("findings", []):
                print(f"  {f['severity']:<8} {f['check']}: {f['detail']}")

        report[pair_dir.name] = {
            "calls": state.get("calls", []),
            "reading": [{"file": f, "field": fld, "ok": ok, "expected": w, "read": g} for f, fld, ok, w, g in reading],
            "blanks": [{"field": f, "ok": ok} for f, ok, _ in blanks],
            "checks": {**checks, "false_alarms": [f["check"] for f in checks["false_alarms"]],
                       "no_action": [f["check"] for f in checks["no_action"]]},
            "findings": state.get("findings", []), "agreements": state.get("agreements", []),
            "documents": state.get("documents", []),
        }

    scored = len(dirs) - len([p for p in report.values() if p.get("not_read")])
    print(f"\nReading: {totals['fields_ok']}/{totals['fields']} values right, "
          f"{totals['blank_ok']}/{totals['blank']} blanks kept blank")
    print(f"Checks on what Gemini read: {totals['pairs_ok']}/{scored} pairs")
    if totals.get("not_read"):
        hint = "Fill them: python -m paperwork.ship_readings --from <run>" if shipped else "Run --resume."
        print(f"NOT READ: {totals['not_read']} document(s); {len(dirs) - scored} pair(s) not scored. {hint}")
    (run_dir / "report.json").write_text(json.dumps({"totals": totals, "pairs": report}, indent=2, ensure_ascii=False,
                                                    default=str), encoding="utf-8")
    print(f"Saved: {run_dir}")
    failed = (totals["fields"] - totals["fields_ok"]) + (totals["blank"] - totals["blank_ok"]) + (len(dirs) - totals["pairs_ok"])
    # (a pair that wasn't read counts as not passed, so an incomplete run never says "OK")
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["answer_key", "gemini", "shipped"], default="answer_key",
                        help="answer_key: test the checks alone; gemini: the whole flow on the documents; "
                             "shipped: the whole flow on the Georgian readings that ship with the app (no Gemini calls)")
    parser.add_argument("--models", help="comma-separated paperwork models (default: KARGONAUT_PAPERWORK_MODELS or extract.py)")
    parser.add_argument("--resume", type=Path, help="a gemini run folder: reuse its saved answers, call Gemini for the rest")
    parser.add_argument("--regrade", type=Path, help="a gemini run folder: re-score saved answers only, no Gemini calls")
    parser.add_argument("--set", choices=["all", "us", "ge"], default="all",
                        help="gemini mode: which documents (us = private US test set, ge = Georgian demo set)")
    parser.add_argument("-q", "--quiet", action="store_true", help="only failures and totals")
    args = parser.parse_args()

    if args.source == "shipped":
        from datetime import datetime
        from paperwork.ship_readings import SHIPPED
        run_dir = ROOT / "evals" / "results" / "paperwork" / (datetime.now().strftime("%Y-%m-%d_%H%M") + "_shipped")
        failures = run_gemini(run_dir, None, allow_calls=False, verbose=not args.quiet, only_set="ge", shipped=SHIPPED)
        print("Shipped readings OK" if not failures else f"Shipped readings: {failures} miss(es)")
        sys.exit(1 if failures else 0)

    if args.source == "gemini" or args.resume or args.regrade:
        from datetime import datetime
        run_dir = args.regrade or args.resume or ROOT / "evals" / "results" / "paperwork" / datetime.now().strftime("%Y-%m-%d_%H%M")
        models = [m.strip() for m in args.models.split(",")] if args.models else None
        failures = run_gemini(Path(run_dir), models, allow_calls=not args.regrade, verbose=not args.quiet,
                              only_set=args.set)
        print("Paperwork reading OK" if not failures else f"Paperwork reading: {failures} miss(es)")
        sys.exit(1 if failures else 0)

    failures = run_unit_cases() + run_pairs(verbose=not args.quiet)
    if PAIRS_DIR.exists():
        failures += run_planted()
        failures += run_wording_test()
    print("Paperwork checks OK" if not failures else f"Paperwork checks: {failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

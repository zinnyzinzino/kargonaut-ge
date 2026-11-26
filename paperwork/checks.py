"""Python checks on extracted documents: the paperwork agent's decisions (no AI here).

Two steps, each a LangGraph node: it takes the shared state and returns only what it adds
({"findings": [...], "agreements": [...]}); LangGraph (or pipeline.run_checks) appends those lists.

- `validate`: each document on its own (missing signatures, a weight without a unit, dates that don't
  make sense, handwritten notes to show the dispatcher).
- `cross_check`: the documents of one shipment against the rate confirmation (carrier, addresses,
  weight, pieces, reference numbers, dates) and against our own company.

A finding is {"check", "severity", "documents", "detail", "action"}:
- "problem": something the dispatcher must sort out (wrong carrier, missing driver signature, ...).
- "note": worth knowing, not necessarily wrong (weight without a unit, a handwritten note, ...).
- "action": what the dispatcher should do next (e.g. ask the broker for a revised RC), or None.
An agreement is the positive side ("same delivery address"), so the dashboard can show what was checked
and passed, not only what failed. All sentences come from wording.py in the state's language
(state["lang"], "en" when not given).
"""
from datetime import date

import re

from paperwork.addresses import compare_addresses, is_ours, our_names, same_company
from paperwork.wording import Wording

KG_TO_LB = 2.20462

# Which signature line each kind of document must have signed: (role, check name, severity).
# Not the delivery order: it is handed over before delivery, so its "Received" line is empty by design.
# An RC not signed by us is a note: that is how a fresh RC arrives from the broker (we sign and return it).
REQUIRED_SIGNATURES = {
    "rate_confirmation": [("carrier", "rc_not_signed", "note")],
    "bill_of_lading": [("driver", "driver_signature_missing", "problem"), ("shipper", "shipper_signature_missing", "problem")],
    "proof_of_delivery": [("receiver", "pod_not_signed", "problem")],
}


def finding(check, severity, documents, detail, action=None):
    return {"check": check, "severity": severity, "documents": documents, "detail": detail, "action": action}


def agreement(check, documents, detail):
    return {"check": check, "documents": documents, "detail": detail}


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _broker(rc):
    return f" ({rc['issuer']})" if rc and rc.get("issuer") else ""


def _our_label(lang, ours):
    """The name to print for our company: its Georgian name in Georgian sentences, if it has one."""
    names = our_names(ours)
    georgian = [n for n in names if re.search(r"[Ⴀ-ჿ]", n)]
    return georgian[0] if lang == "ka" and georgian else next((n for n in names if n not in georgian), names[0])


def _rate_confirmation(documents):
    for doc in documents:
        if doc["kind"] == "rate_confirmation":
            return doc
    return None


# ---------------------------------------------------------------- validate: each document on its own

def validate(state):
    w = Wording(state.get("lang", "en"))
    findings = []
    for doc in state["documents"]:
        name, label = doc["name"], w.doc(doc)

        for field, value in (("issued", doc.get("issued_date")),
                             ("pickup", doc["pickup"].get("date")),
                             ("delivery", doc["delivery"].get("date"))):
            if value and not _date(value):
                findings.append(finding("unreadable_date", "note", [name],
                                        w.say("unreadable_date", field=w.date_field(field), doc=label, value=value)))

        pickup, delivery = _date(doc["pickup"].get("date")), _date(doc["delivery"].get("date"))
        if pickup and delivery and delivery < pickup:
            findings.append(finding("delivery_before_pickup", "problem", [name],
                                    w.say("delivery_before_pickup", doc=label, delivery=delivery, pickup=pickup)))

        if doc.get("weight") is not None and not doc.get("weight_unit"):
            findings.append(finding("weight_unit_not_stated", "note", [name],
                                    w.say("weight_unit_not_stated", doc=label, weight=f"{doc['weight']:g}")))

        if doc["kind"] == "rate_confirmation":
            missing = [field for field in ("commodity", "pieces", "weight") if doc.get(field) in (None, "")]
            if missing:
                findings.append(finding("not_stated", "note", [name], w.say("not_stated", fields=w.fields(missing))))
            issued = _date(doc.get("issued_date"))
            if issued and pickup and issued > pickup:
                findings.append(finding("rc_after_pickup", "note", [name],
                                        w.say("rc_after_pickup", issued=issued, pickup=pickup)))

        signatures = doc.get("signatures") or {}
        for role, check, severity in REQUIRED_SIGNATURES.get(doc["kind"], []):
            line = signatures.get(role)
            if not line or not line.get("signed"):
                text = w.say(check) if w.has(check) else w.say("signature_missing", what=w.signature(role), doc=label)
                findings.append(finding(check, severity, [name], text, action=w.action(check, broker=_broker(doc))))
            elif doc["kind"] == "proof_of_delivery" and not line.get("name"):
                # Signed, but nobody can tell by whom: a scribble or initials and no printed name. Never
                # turned into a name (same rule as extraction); the driver asks the receiver instead.
                findings.append(finding("pod_receiver_unnamed", "problem", [name], w.say("pod_receiver_unnamed", doc=label),
                                        action=w.action("pod_receiver_unnamed")))

        for note in doc.get("handwritten_notes") or []:
            findings.append(finding("handwritten_note", "note", [name], w.say("handwritten_note", doc=label, note=note)))

    return {"findings": findings}


# ---------------------------------------------------------------- cross_check: documents against each other

def _weight_lb(doc):
    weight, unit = doc.get("weight"), doc.get("weight_unit")
    if weight is None:
        return None
    return weight * KG_TO_LB if unit == "kg" else weight


def _reference_values(doc):
    values = {}
    for label, value in [("load number", doc.get("load_number"))] + list((doc.get("references") or {}).items()):
        if value:
            key = "".join(ch for ch in str(value).upper() if ch.isalnum())
            if len(key) >= 5:          # short values ("4", "PL") would link documents by accident
                values[key] = (label, value)
    return values


def _readable_label(label):     # "pickup_number" -> "pickup number", "hbl" -> "HBL"
    return label.upper() if len(label) <= 3 else label.replace("_", " ")


def _check_carrier(w, rc, doc, our_carrier, findings, agreements):
    """our_carrier: all our company's names (matching); the sentences print one of them."""
    names = [rc["name"], doc["name"]]
    carrier = doc.get("carrier")
    if not carrier:
        return
    ours = _our_label(w.lang, our_carrier)
    # Every document is compared with OUR company, not with the RC: if the RC itself names the wrong
    # carrier, that is already its own problem (carrier_not_ours)
    if is_ours(carrier, our_carrier):
        agreements.append(agreement("carrier", names, w.say("ok_carrier", doc=w.doc(doc), carrier=carrier)))
    elif doc["kind"] == "delivery_order" and rc.get("issuer") and same_company(carrier, rc["issuer"]):
        findings.append(finding("carrier_is_broker", "note", names,
                                w.say("carrier_is_broker", carrier=carrier, ours=ours)))
    else:
        findings.append(finding("carrier_mismatch", "problem", names,
                                w.say("carrier_mismatch", doc=w.doc(doc), carrier=carrier, ours=ours),
                                action=w.action("carrier_mismatch", broker=_broker(rc), kind=w.kind(doc["kind"]),
                                                ours=ours)))


def _check_stops(w, rc, doc, findings, agreements):
    names = [rc["name"], doc["name"]]
    for stop in ("pickup", "delivery"):
        a, b = rc[stop].get("address"), doc[stop].get("address")
        if not a or not b:
            continue
        compared = compare_addresses(a, b)
        where = w.stop_address(stop)
        if compared["result"] == "same":
            agreements.append(agreement(f"{stop}_address", names, w.say("ok_address", stop_address=where, a=a, b=b)))
        elif compared["result"] == "different":
            findings.append(finding("address_mismatch", "problem", names,
                                    w.say("address_mismatch", stop_address=where, a=a, doc=w.doc(doc), b=b,
                                          reasons=w.differences(compared["differences"])),
                                    action=w.action("address_mismatch", broker=_broker(rc), stop_address=where)))
        else:
            findings.append(finding("address_unclear", "note", names, w.say("address_unclear", stop_address=where, a=a, b=b)))


def _check_weight(w, rc, doc, findings, agreements):
    names = [rc["name"], doc["name"]]
    if rc.get("weight") is None or doc.get("weight") is None:
        return
    rc_weight, doc_weight = w.weight(rc["weight"], rc.get("weight_unit")), w.weight(doc["weight"], doc.get("weight_unit"))
    if rc.get("weight_unit") is None or doc.get("weight_unit") is None:
        # A weight without a printed unit is never assumed to be lb (validate already notes the missing unit):
        # the same number agrees, a different number can't be judged (review, 25 Nov)
        if abs(rc["weight"] - doc["weight"]) <= max(1.0, 0.01 * max(rc["weight"], doc["weight"])):
            agreements.append(agreement("weight", names, w.say("ok_weight", a=rc_weight, b=doc_weight)))
        return
    a, b = _weight_lb(rc), _weight_lb(doc)
    if abs(a - b) <= max(1.0, 0.01 * max(a, b)):
        agreements.append(agreement("weight", names, w.say("ok_weight", a=rc_weight, b=doc_weight)))
    else:
        findings.append(finding("weight_mismatch", "problem", names,
                                w.say("weight_mismatch", a=rc_weight, doc=w.doc(doc), b=doc_weight)))


def _check_pieces(w, rc, doc, findings, agreements):
    names = [rc["name"], doc["name"]]
    pieces = rc.get("pieces")
    counts = {}
    if doc.get("pieces") is not None:
        counts["pieces"] = doc["pieces"]
    counts.update({kind: n for kind, n in (doc.get("packages") or {}).items() if n is not None})
    if pieces is None or not counts:
        return
    values = {"pieces": pieces, "written": w.counts(counts), "doc": w.doc(doc)}
    # "2 pieces" on the RC and "8 cartons + 2 pallets" on the BOL agree: the pieces are the pallets
    if pieces in counts.values():
        agreements.append(agreement("pieces", names, w.say("ok_pieces", **values)))
    else:
        findings.append(finding("pieces_mismatch", "problem", names, w.say("pieces_mismatch", **values)))


def _check_references(w, rc, doc, agreements):
    names = [rc["name"], doc["name"]]
    ours, theirs = _reference_values(rc), _reference_values(doc)
    for key in ours.keys() & theirs.keys():
        (label_a, value), (label_b, _) = ours[key], theirs[key]
        agreements.append(agreement("reference", names,
                                    w.say("ok_reference", value=value, label_a=_readable_label(label_a),
                                          label_b=_readable_label(label_b), doc=w.doc(doc))))


def _check_dates(w, rc, doc, findings, agreements):
    names = [rc["name"], doc["name"]]
    signatures = doc.get("signatures") or {}
    pickup, delivery = _date(rc["pickup"].get("date")), _date(rc["delivery"].get("date"))

    if doc["kind"] == "bill_of_lading" and pickup:
        for role in ("driver", "shipper"):
            signed = _date((signatures.get(role) or {}).get("date"))
            if signed and signed != pickup:
                findings.append(finding("date_mismatch", "note", names,
                                        w.say("date_mismatch", who=w.dated_by(role), signed=signed, pickup=pickup)))

    if doc["kind"] == "proof_of_delivery" and delivery:
        received = _date((signatures.get("receiver") or {}).get("date"))
        if received and received > delivery:
            findings.append(finding("late_delivery", "note", names, w.say("late_delivery", received=received, due=delivery)))
        elif received:
            agreements.append(agreement("delivery_date", names, w.say("ok_delivery_date", received=received, due=delivery)))


def cross_check(state):
    w = Wording(state.get("lang", "en"))
    documents, our_carrier = state["documents"], state["our_carrier"]
    findings, agreements = [], []
    rc = _rate_confirmation(documents)

    # Paperwork that isn't what it should be: a delivery order where a BOL belongs
    has_bol = any(d["kind"] == "bill_of_lading" and not d.get("says_not_a_bol") for d in documents)
    for doc in documents:
        if doc["kind"] == "bill_of_lading" and doc.get("says_not_a_bol"):
            findings.append(finding("wrong_document_type", "problem", [doc["name"]], w.say("not_a_bol", name=doc["name"]),
                                    action=w.action("no_bol", broker=_broker(rc))))
        elif doc["kind"] == "delivery_order" and not has_bol:
            quote = w.not_a_bol_quote() if doc.get("says_not_a_bol") else ""
            findings.append(finding("wrong_document_type", "problem", [doc["name"]],
                                    w.say("delivery_order_no_bol", name=doc["name"], quote=quote),
                                    action=w.action("no_bol", broker=_broker(rc))))

    if rc is None:
        findings.append(finding("no_rate_confirmation", "note", [d["name"] for d in documents], w.say("no_rate_confirmation")))
        return {"findings": findings, "agreements": agreements}

    if not rc.get("carrier"):
        findings.append(finding("carrier_not_stated", "note", [rc["name"]], w.say("carrier_not_stated")))
    elif is_ours(rc["carrier"], our_carrier):
        agreements.append(agreement("carrier_ours", [rc["name"]], w.say("ok_carrier_ours", carrier=rc["carrier"])))
    else:
        ours = _our_label(w.lang, our_carrier)
        findings.append(finding("carrier_not_ours", "problem", [rc["name"]],
                                w.say("carrier_not_ours", carrier=rc["carrier"], ours=ours),
                                action=w.action("carrier_not_ours", broker=_broker(rc), ours=ours)))

    for doc in documents:
        if doc is rc:
            continue
        _check_carrier(w, rc, doc, our_carrier, findings, agreements)
        _check_stops(w, rc, doc, findings, agreements)
        _check_weight(w, rc, doc, findings, agreements)
        _check_pieces(w, rc, doc, findings, agreements)
        _check_references(w, rc, doc, agreements)
        _check_dates(w, rc, doc, findings, agreements)

    return {"findings": findings, "agreements": agreements}

"""The one document format every paperwork step agrees on.

Extraction (Gemini, step 2) produces one of these per document; the Python checks read only this. The
eval converts each answer key (`documents/us/pair-*/expected.json`) into the same format, so the checks can
be tested on what a careful person read, separately from how well Gemini reads.

A document:

    {
      "name": "bol.jpg",                    # file name, used in messages
      "kind": "bill_of_lading",             # one of DOCUMENT_KINDS
      "says_not_a_bol": False,              # True when it prints "This is NOT a Bill of Lading"
      "issuer": "Meridex",                  # broker on a rate confirmation; who printed a BOL / delivery order
      "issued_date": "2026-11-19",          # all dates YYYY-MM-DD, None when not printed
      "load_number": None,
      "references": {"customer_po": "3471865"},   # every other reference number, as printed
      "carrier": "Northbound Trucking",     # delivery order: the delivering carrier
      "pickup":   {"name": ..., "address": ..., "date": ..., "time": ...},
      "delivery": {"name": ..., "address": ..., "date": ..., "time": ...},
      "commodity": None,
      "equipment": "Refrigerated",          # the truck type as printed ("Van", "Refrigerated", ...), or None
      "pieces": None,                       # a plain piece count
      "packages": {"cartons": 8, "pallets": 2},   # when the document counts by package type
      "weight": 300.0,
      "weight_unit": "lb",                  # "lb", "kg" or None: None when not printed, NEVER assumed
      "rate": None, "currency": None,
      "signatures": {                       # one entry per signature line the document has
        "driver":  {"signed": False, "name": None, "initials": None, "date": "2026-11-20"},
        "shipper": {"signed": True,  "name": None, "initials": "TKW", "date": "2026-11-20"},
      },
      "handwritten_notes": [],
    }

Signature roles: "carrier" (on a rate confirmation), "driver" and "shipper" (BOL), "receiver" (delivery
order, proof of delivery). `name` is filled only when a name is printed or clearly readable; initials or an
unreadable scribble are never turned into a name.
"""

DOCUMENT_KINDS = ("rate_confirmation", "bill_of_lading", "delivery_order", "proof_of_delivery", "other")

KIND_LABELS = {
    "rate_confirmation": "rate confirmation",
    "bill_of_lading": "bill of lading",
    "delivery_order": "delivery order",
    "proof_of_delivery": "proof of delivery",
    "other": "document",
}

STOP_FIELDS = ("name", "address", "date", "time")


def empty_stop():
    return {field: None for field in STOP_FIELDS}


def empty_document(name="", kind="other"):
    return {
        "name": name,
        "kind": kind,
        "says_not_a_bol": None,
        "issuer": None,
        "issued_date": None,
        "load_number": None,
        "references": {},
        "carrier": None,
        "pickup": empty_stop(),
        "delivery": empty_stop(),
        "commodity": None,
        "equipment": None,
        "pieces": None,
        "packages": {},
        "weight": None,
        "weight_unit": None,
        "rate": None,
        "currency": None,
        "signatures": {},
        "handwritten_notes": [],
    }

"""Kargonaut paperwork agent: reads rate confirmations, BOLs, delivery orders and PODs, checks them
against each other, and turns a document into a new-load draft that the dispatcher confirms.

Same design principle as the dispatcher agent: Gemini reads and extracts; Python validates and
cross-checks (this package); a person confirms anything that changes data.

    schema.py     the document format every step agrees on
    addresses.py  address and company-name comparison
    checks.py     validate (each document) and cross_check (documents against each other)
    pipeline.py   the flow and its state (LangGraph-shaped)
"""

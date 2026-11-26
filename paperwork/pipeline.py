"""The paperwork agent's flow: classify -> extract -> validate -> cross_check -> (person confirms).

Step 1 (now): only the Python steps, run in order by `run_checks`. Steps 2+ add `classify` and `extract`
(Gemini reads the document) and move the same functions onto a LangGraph StateGraph: `PaperworkState`
is already declared the way LangGraph expects, with the list fields marked "append" (operator.add), and
every step already returns only what it adds.
"""
import operator
from typing import Annotated, TypedDict

from paperwork.checks import cross_check, validate
from paperwork.draft import plan_draft


class PaperworkState(TypedDict, total=False):
    lang: str                                        # "en" or "ka": the language of every finding
    our_carrier: str | list                          # our company's name(s)
    documents: list                                  # schema.py format, one per document
    findings: Annotated[list, operator.add]          # each step appends its own
    agreements: Annotated[list, operator.add]
    draft_plan: dict | None                          # draft.py: a new load from the RC, or why not


CHECK_STEPS = [validate, cross_check, plan_draft]
APPEND_FIELDS = ("findings", "agreements")


def _merge(state, update):
    for key, value in update.items():
        if key in APPEND_FIELDS:
            state[key] = state.get(key, []) + value
        else:
            state[key] = value


def run_checks(documents, our_carrier, lang="en"):
    """Run the Python checks on already-extracted documents of one shipment."""
    state: PaperworkState = {"lang": lang, "our_carrier": our_carrier, "documents": documents,
                             "findings": [], "agreements": []}
    for step in CHECK_STEPS:
        _merge(state, step(state))
    return state


def problems(state):
    return [f for f in state["findings"] if f["severity"] == "problem"]


def notes(state):
    return [f for f in state["findings"] if f["severity"] == "note"]

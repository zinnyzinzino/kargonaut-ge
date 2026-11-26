"""The paperwork agent as a LangGraph graph:

    START -> classify -> extract -> (anything read?) -> validate -> cross_check -> plan_draft -> END
                                         \\-> no: END

classify and extract call Gemini (extract.py), for all documents at the same time; validate and
cross_check are the Python checks (checks.py), unchanged. The reader comes in through LangGraph's config, so the eval can pass a reader that
saves and reuses answers (no repeated Gemini calls) without changing the graph.

plan_draft (draft.py, Python) says what new load the rate confirmation would become, or why not. The
dispatcher then creates the draft in the dashboard and confirms it with the same Confirm button as the
chat's drafts: nothing is saved before that.

Try it on the anonymized test set:
    python -m paperwork.graph documents/us/pair-03/rc.pdf documents/us/pair-03/bol.jpg
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from paperwork.checks import cross_check, finding, validate
from paperwork.draft import plan_draft
from paperwork.extract import GeminiReader, ReadingFailed, to_document
from paperwork.pipeline import PaperworkState, notes, problems
from paperwork.wording import Wording

OUR_CARRIER = "Warp Corporation"   # the US test set; the Georgian demo documents will name our company
READ_AT_ONCE = 3   # documents sent to Gemini at the same time (more makes free-tier 429s likelier)


class GraphState(PaperworkState, total=False):
    files: list            # paths of the uploaded documents of one shipment
    display_names: dict    # path -> the name to show (uploads are saved under temporary names)
    classified: list       # [{"file", "kind", "says_not_a_bol", "title_as_printed"}]
    calls: list            # one entry per Gemini call: step, file, model, seconds (overwritten per step)


def _reader(config):
    return (config or {}).get("configurable", {}).get("reader") or GeminiReader()


def _name(state, path):
    """The name shown to the dispatcher: the uploaded file's own name, not the temporary file's."""
    return (state.get("display_names") or {}).get(str(path), Path(path).name)


def _unreadable(state, name, exc):
    w = Wording(state.get("lang", "en"))
    return finding("unreadable_document", "problem", [name],
                   w.say("unreadable_document", name=name, error=w.reading_error(exc)),
                   action=w.action("unreadable_document"))


def _each(items, read):
    """read(item) for every item at the same time (at most READ_AT_ONCE), results in the items' order.
    Waiting for Gemini is most of the time: three documents take about as long as one."""
    if len(items) <= 1:
        return [read(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(len(items), READ_AT_ONCE)) as pool:
        return list(pool.map(read, items))


def classify(state, config=None):
    reader = _reader(config)

    def read(path):
        name = _name(state, path)
        try:
            answer, meta = reader.classify(path)
            return {"file": path, **answer}, {"step": "classify", "file": name, **meta}, None
        except Exception as exc:   # ReadingFailed, or an odd answer: this document is unreadable, not the request
            return None, None, _unreadable(state, name, exc)

    results = _each(state["files"], read)
    return {"classified": [r[0] for r in results if r[0]], "calls": [r[1] for r in results if r[1]],
            "findings": [r[2] for r in results if r[2]]}


def extract(state, config=None):
    reader = _reader(config)

    def read(item):
        name = _name(state, item["file"])
        try:
            answer, meta = reader.extract(item["file"], item["kind"])
            return to_document(name, item, answer), {"step": "extract", "file": name, **meta}, None
        except Exception as exc:   # ReadingFailed, or an odd answer: this document is unreadable, not the request
            return None, None, _unreadable(state, name, exc)

    results = _each(state["classified"], read)
    return {"documents": [r[0] for r in results if r[0]],
            "calls": list(state.get("calls", [])) + [r[1] for r in results if r[1]],
            "findings": [r[2] for r in results if r[2]]}


def _anything_read(state):
    return "validate" if state.get("documents") else END


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("classify", classify)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("cross_check", cross_check)
    graph.add_node("plan_draft", plan_draft)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "extract")
    graph.add_conditional_edges("extract", _anything_read, ["validate", END])
    graph.add_edge("validate", "cross_check")
    graph.add_edge("cross_check", "plan_draft")
    graph.add_edge("plan_draft", END)
    return graph.compile()


def read_documents(files, our_carrier=OUR_CARRIER, reader=None, lang="en", display_names=None):
    """Run the whole flow on the documents of one shipment and return the final state."""
    state = {"files": [str(f) for f in files], "our_carrier": our_carrier, "lang": lang,
             "display_names": {str(k): v for k, v in (display_names or {}).items()},
             "documents": [], "findings": [], "agreements": [], "calls": []}
    config = {"configurable": {"reader": reader}} if reader else None
    return build_graph().invoke(state, config=config)


def _print_report(state):
    for call in state.get("calls", []):
        print(f"  {call['step']:<8} {call['file']:<20} {call.get('model')} {call.get('seconds')}s"
              + (" (saved)" if call.get("cached") else ""))
    for doc in state.get("documents", []):
        print(f"\n{doc['name']}: {doc['kind']}")
        for key in ("issuer", "load_number", "carrier", "weight", "weight_unit", "pieces"):
            print(f"  {key}: {doc.get(key)}")
        for stop in ("pickup", "delivery"):
            print(f"  {stop}: {doc[stop].get('name')} | {doc[stop].get('address')} | {doc[stop].get('date')}")
        for role, line in doc["signatures"].items():
            print(f"  signature {role}: {line}")
    print()
    for f in problems(state):
        print(f"PROBLEM {f['check']}: {f['detail']}" + (f"\n        -> {f['action']}" if f.get("action") else ""))
    for f in notes(state):
        print(f"note    {f['check']}: {f['detail']}")
    for a in state.get("agreements", []):
        print(f"ok      {a['check']}: {a['detail']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    _print_report(read_documents(sys.argv[1:], reader=GeminiReader(on_status=print)))

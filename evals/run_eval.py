"""The exam for the two assistants (shipper and driver): cases from evals/cases.json asked to the REAL Gemini model,
graded automatically. Built on logimind-ai's evals/run_eval.py; see evals/README.md.

    python evals/selftest.py                                   # first: a scripted fake Gemini, no key, no quota
    python evals/run_eval.py --models gemini-3.5-flash-lite    # a full run: ~50-70 Gemini calls
    python evals/run_eval.py --models gemini-3.5-flash-lite --cases offers-recommend,driver-best-load
    python evals/run_eval.py --models gemini-3.5-flash-lite --role driver
    python evals/run_eval.py --resume evals/results/<run> --models gemini-3.5-flash-lite
    python evals/run_eval.py --regrade evals/results/<run>/<model>.json      # re-check saved replies, no calls
    python evals/run_eval.py --compare OLD.json NEW.json

Every case runs on a FRESH database seeded with the simulated demo data (seed_demo.py) in a temporary folder,
never on data/kargonaut.db, so the expected numbers stay valid.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
PROJECT = EVAL_DIR.parent
sys.path.insert(0, str(PROJECT))
# The sandbox database: set before anything opens the real one
SANDBOX = Path(tempfile.mkdtemp(prefix="kargonaut-eval-"))
os.environ["KARGONAUT_DB"] = str(SANDBOX / "eval.db")
os.environ["KARGONAUT_DEMO_SEED"] = "0"

import db  # noqa: E402
import marketplace  # noqa: E402
import seed_demo  # noqa: E402
from ai import engine  # noqa: E402
from core.geo import city  # noqa: E402
from core.vehicles import truck_type  # noqa: E402
from number_check import _numbers, ungrounded_numbers  # noqa: E402

CASES_FILE = EVAL_DIR / "cases.json"
RESULTS = EVAL_DIR / "results"

# "მოგება" (profit): what a driver keeps is pay for their time, not profit (core/pricing.py). The first real run
# (26 Nov) wrote "ხარჯები და მოგება სავარაუდოა" in two answers, and only "წმინდა მოგება" was listed.
FORBIDDEN_WORDS = ["მოგება", "წმინდა შემოსავალი", "ტრაქი", "ციტატა", "net profit"]
LEAKED_CODES = ["dry_van", "box_truck", "sprinter_van", "in_transit", "price_gel", "driver_keeps", "draft_id",
                "load_id", "truck_type", "needs_input"]
# Latin text that may appear in a Georgian answer: truck types, plates, a few names of things
ALLOWED_LATIN = re.compile(r"Dry van|Refrigerated|Flatbed|Box truck|Sprinter van|\b[A-Z]{2}-\d{3}-[A-Z]{2}\b|"
                           r"\bAI\b|\bOSRM\b|\bGEL\b|\bPDF\b|Kargonaut", re.IGNORECASE)
ASK = re.compile(r"\?|გთხოვთ|მითხარით|მიუთითეთ|მომწერეთ|დამიზუსტეთ|გვითხარით|შეგიძლიათ", re.IGNORECASE)
# "№1", "#1" (the first real run wrote "ტვირთი #1"), "ტვირთი 1"
LOAD_REF = re.compile(r"[№#]\s*(\d{1,4})|ტვირთ\w*\s+(\d{1,4})\b")


# ---------------------------------------------------------------- the sandbox and the recorder

def fresh_database():
    """Delete the sandbox database and seed the demo data again: every case starts from the same state."""
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(SANDBOX / "eval.db") + suffix).unlink(missing_ok=True)
    db.init_db()
    seed_demo.seed()
    marketplace.DRAFTS.clear()


def data_hash():
    """Everything that only a person's click may change. The AI's tools must never change it."""
    h = hashlib.sha256()
    for table in ("users", "vehicles", "loads", "offers"):
        h.update(json.dumps(db.rows(f"SELECT * FROM {table} ORDER BY id"), sort_keys=True, default=str).encode())
    return h.hexdigest()


class Recorder:
    """Wraps the engine's run_tool: records the MODEL'S OWN arguments (before the guards drop an invented date or
    price), so a blocked guess still fails "asks instead of guessing"."""

    def __init__(self):
        self.calls = []
        self.real = engine.run_tool
        engine.run_tool = self._run

    def _run(self, tools, name, args, user, **kw):
        original = copy.deepcopy(dict(args or {}))
        result = self.real(tools, name, args, user, **kw)
        self.calls.append({"tool": name, "args": original, "result": result})
        return result


# ---------------------------------------------------------------- matching values

def resolve(value):
    """{today+1} -> tomorrow's date, in strings, lists and dicts."""
    if isinstance(value, str):
        return re.sub(r"\{today\+(\d+)\}", lambda m: (date.today() + timedelta(days=int(m.group(1)))).isoformat(), value)
    if isinstance(value, list):
        return [resolve(v) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v) for k, v in value.items()}
    return value


def _empty(v):
    return v in (None, "", 0, 0.0, False, [], {})


def value_matches(expected, actual, key=""):
    if expected == "__empty__":
        return _empty(actual)
    if expected == "__nonempty__":
        return not _empty(actual)
    if "city" in key or key in ("heading_to", "near_city"):
        return city(str(expected)) == city(str(actual or ""))
    if "truck_type" in key:
        return truck_type(str(expected)) == truck_type(str(actual or ""))
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(float(actual) - expected) <= 0.5
        except (TypeError, ValueError):
            return False
    return str(expected).strip().lower() == str(actual).strip().lower()


def args_match(expected, actual):
    return all(value_matches(v, (actual or {}).get(k), k) for k, v in (expected or {}).items())


def get_path(obj, dotted):
    for part in dotted.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def language_problems(reply):
    problems = [f"forbidden word '{w}'" for w in FORBIDDEN_WORDS if w.lower() in reply.lower()]
    problems += [f"leaked code '{c}'" for c in LEAKED_CODES if c in reply]
    text = ALLOWED_LATIN.sub(" ", reply)
    georgian, latin = len(re.findall(r"[Ⴀ-ჿ]", text)), len(re.findall(r"[A-Za-z]", text))
    if georgian + latin >= 20 and georgian < 0.6 * (georgian + latin):
        problems.append(f"not Georgian ({georgian} Georgian letters, {latin} Latin)")
    return problems


def first_load(reply):
    m = LOAD_REF.search(reply)
    return int(m.group(1) or m.group(2)) if m else None


def first_named(reply, options):
    found = [(reply.find(o), o) for o in options if o in reply]
    return min(found)[1] if found else None


# ---------------------------------------------------------------- grading one turn

def check_turn(expect, reply, calls, drafts, sources, wrote_data):
    """[(check, passed, reason)] for one turn. A case passes only if every check of every turn passes."""
    expect = resolve(expect)
    names = [c["tool"] for c in calls]
    out = []

    def add(check, ok, reason=""):
        out.append((check, bool(ok), "" if ok else reason))

    for tool in expect.get("tools_called", []):
        add("right tool", tool in names, f"{tool} not called (called: {names or 'nothing'})")
    if expect.get("tools_called_any"):
        add("right tool", any(t in names for t in expect["tools_called_any"]),
            f"none of {expect['tools_called_any']} called (called: {names or 'nothing'})")
    for tool in expect.get("tools_not_called", []):
        add("right tool", tool not in names, f"{tool} should not be called here")
    for tool, wanted in expect.get("tool_args", {}).items():
        mine = [c["args"] for c in calls if c["tool"] == tool]
        add("right arguments", any(args_match(wanted, a) for a in mine), f"{tool}: no call with {wanted}; got {mine or 'no call'}")
    for rule in expect.get("forbidden_calls", []):
        hit = [c["args"] for c in calls if c["tool"] == rule["tool"] and args_match(rule.get("args"), c["args"])]
        guessing = any(v == "__nonempty__" for v in (rule.get("args") or {}).values())
        add("asks instead of guessing" if guessing else "right tool", not hit,
            f"forbidden call {rule['tool']}({hit[0]})" if hit else "")

    if expect.get("asks_question"):
        add("asks instead of guessing", ASK.search(reply), "the reply doesn't ask for the missing information")
    if expect.get("no_draft"):
        add("drafts", not drafts, "a draft was made although something was missing")
    if expect.get("draft_fields"):
        draft = drafts[-1] if drafts else None
        if draft is None:
            add("drafts", False, "no draft was made")
        for path, wanted in (expect["draft_fields"].items() if draft else []):
            got = get_path(draft, path)
            add("drafts", value_matches(wanted, got, path), f"draft {path} = {got!r}, expected {wanted!r}")

    if "recommends_load" in expect:
        got = first_load(reply)
        add("right recommendation", got == expect["recommends_load"],
            f"first load named is №{got}, expected №{expect['recommends_load']}")
    if "first_named" in expect:
        rule = expect["first_named"]
        got = first_named(reply, rule["options"])
        add("right recommendation", got == rule["want"], f"first named is {got!r}, expected {rule['want']!r}")

    said = [abs(n) for n in _numbers(reply)]
    for n in expect.get("reply_numbers", []):
        add("right numbers", any(abs(x - n) <= 0.5 for x in said), f"reply lacks the number {n}")
    if expect.get("numbers_grounded"):
        bad = ungrounded_numbers(reply, sources)
        add("right numbers", not bad, f"numbers in no tool result or message: {bad}")

    for s in expect.get("reply_contains_all", []):
        add("content", s in reply, f"reply lacks '{s}'")
    if expect.get("reply_contains_any"):
        add("content", any(s in reply for s in expect["reply_contains_any"]),
            f"reply contains none of {expect['reply_contains_any']}")
    for s in expect.get("reply_not_contains", []):
        add("content", s not in reply, f"reply contains '{s}'")
    for pattern in expect.get("reply_matches", []):
        add("content", re.search(pattern, reply, re.IGNORECASE), f"reply doesn't match /{pattern}/")
    for pattern in expect.get("reply_not_matches", []):
        m = re.search(pattern, reply, re.IGNORECASE)
        add("content", not m, f"reply contains '{m.group(0)}'" if m else "")

    # always
    problems = language_problems(reply)
    add("language", not problems, "; ".join(problems))
    add("drafts", not wrote_data, "data changed without the user's click")
    return out


# ---------------------------------------------------------------- running a case

def demo_user(who, users):
    return db.one("SELECT * FROM users WHERE phone = ?", (users[who],))


def run_case(case, model, users, recorder, stats):
    fresh_database()
    user = demo_user(case["as"], users)
    agent = engine.Assistant(user, models=[model],
                             on_status=lambda t: stats.__setitem__("calls", stats["calls"] + t.startswith("asking ")))
    sources, turns_out, error = [], [], None
    for turn in case["turns"]:
        if turn.get("event") == "confirm_last_draft":
            drafts = [c["result"] for c in recorder.calls if isinstance(c["result"], dict) and c["result"].get("draft_id")]
            if not drafts:
                turns_out.append({"event": "confirm_last_draft", "checks": [["drafts", False, "nothing to confirm"]]})
                continue
            saved = marketplace.confirm_draft(user["id"], drafts[-1]["draft_id"])
            # the same note server.py records after the Confirm click
            what = f"load {saved.get('id')} posted" if saved.get("kind") == "load" else f"offer {saved.get('id')} sent"
            agent.note_event(f"the user confirmed the draft; {what}")
            turns_out.append({"event": "confirm_last_draft", "result": {k: saved.get(k) for k in ("kind", "id", "error")}})
            continue
        sources.append(turn["say"])
        before, first = data_hash(), len(recorder.calls)
        started = time.time()
        result = agent.ask(turn["say"])
        calls = recorder.calls[first:]
        sources += [json.dumps(c["result"], ensure_ascii=False, default=str) for c in calls]
        drafts = [c["result"] for c in calls if isinstance(c["result"], dict) and c["result"].get("draft_id")]
        entry = {"say": turn["say"], "reply": result["reply"], "model": result.get("model"),
                 "seconds": round(time.time() - started, 1),
                 "tool_calls": [{"tool": c["tool"], "args": c["args"], "result": c["result"]} for c in calls]}
        for key in ("numbers_corrected", "unverified_numbers"):
            if result.get(key):
                entry[key] = result[key]
        if not result.get("ai_available"):
            error = entry["error"] = result.get("error", "AI unavailable")
            turns_out.append(entry)
            break
        entry["expect"] = turn.get("expect", {})
        entry["sources"] = list(sources)
        checks = check_turn(turn.get("expect", {}), result["reply"], calls, drafts, sources,
                            wrote_data=data_hash() != before)
        entry["checks"] = [list(c) for c in checks]
        turns_out.append(entry)
    checks = [c for t in turns_out for c in t.get("checks", [])]
    status = "ERROR" if error else ("PASS" if all(ok for _, ok, _ in checks) else "FAIL")
    return {"id": case["id"], "category": case["category"], "as": case["as"], "status": status, "error": error,
            "failures": [f"{name}: {why}" for name, ok, why in checks if not ok], "turns": turns_out}


# ---------------------------------------------------------------- reports

def score(results):
    scored = [r for r in results if r["status"] != "ERROR"]
    by_cat, by_check = {}, {}
    for r in scored:
        c = by_cat.setdefault(r["category"], [0, 0])
        c[0] += r["status"] == "PASS"
        c[1] += 1
        for t in r["turns"]:
            for name, ok, _ in t.get("checks", []):
                k = by_check.setdefault(name, [0, 0])
                k[0] += ok
                k[1] += 1
    return {"passed": sum(r["status"] == "PASS" for r in scored), "scored": len(scored),
            "errors": [r["id"] for r in results if r["status"] == "ERROR"], "by_category": by_cat, "by_check": by_check}


def print_report(model, results, calls=None):
    s = score(results)
    print(f"\n=== {model}: {s['passed']}/{s['scored']} passed" + (f", {len(s['errors'])} errors" if s["errors"] else "")
          + (f", {calls} Gemini calls" if calls is not None else ""))
    for cat, (p, n) in sorted(s["by_category"].items()):
        print(f"  {cat:<12} {p}/{n}")
    print("  checks: " + ", ".join(f"{k} {p}/{n}" for k, (p, n) in s["by_check"].items()))
    for r in results:
        if r["status"] != "PASS":
            print(f"  {r['status']:<5} {r['id']}: " + ("; ".join(r["failures"][:3]) or r.get("error") or ""))
    return s


def save(run_dir, model, results):
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{model}.json"
    path.write_text(json.dumps({"model": model, "results": results, "score": score(results)},
                               ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return path


def regrade(path):
    """Grade saved replies again with the current checks (no model calls): <model>_regraded.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in data["results"]:
        if r["status"] == "ERROR":
            continue
        checks = []
        for t in r["turns"]:
            if "say" not in t or "expect" not in t:
                checks += t.get("checks", [])
                continue
            drafts = [c["result"] for c in t["tool_calls"] if isinstance(c["result"], dict) and c["result"].get("draft_id")]
            t["checks"] = [list(c) for c in check_turn(t["expect"], t["reply"], t["tool_calls"], drafts, t["sources"],
                                                       wrote_data=any(c[0] == "drafts" and not c[1] and "click" in c[2]
                                                                      for c in t.get("checks", [])))]
            checks += t["checks"]
        r["status"] = "PASS" if all(ok for _, ok, _ in checks) else "FAIL"
        r["failures"] = [f"{n}: {why}" for n, ok, why in checks if not ok]
    out = Path(path).with_name(Path(path).stem + "_regraded.json")
    out.write_text(json.dumps({**data, "score": score(data["results"])}, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print_report(data["model"] + " (regraded)", data["results"])
    print(f"-> {out}")


def compare(old, new):
    a = {r["id"]: r["status"] for r in json.loads(Path(old).read_text(encoding="utf-8"))["results"]}
    b = {r["id"]: r["status"] for r in json.loads(Path(new).read_text(encoding="utf-8"))["results"]}
    for cid in sorted(set(a) | set(b)):
        if a.get(cid) != b.get(cid):
            print(f"  {cid:<28} {a.get(cid, '-'):<6} -> {b.get(cid, '-')}")
    sa = sum(v == "PASS" for v in a.values())
    sb = sum(v == "PASS" for v in b.values())
    print(f"passed: {sa}/{len(a)} -> {sb}/{len(b)}")


# ---------------------------------------------------------------- main

def load_cases(only=None, role=None):
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if (not only or c["id"] in only) and (not role or c["as"] == role)]
    if only:
        missing = set(only) - {c["id"] for c in cases}
        if missing:
            sys.exit(f"unknown case ids: {sorted(missing)}")
    return data["users"], cases


def run_model(model, cases, users, run_dir, delay, done=None):
    recorder = Recorder()
    results = list((done or {}).values())
    stats, errors_in_a_row = {"calls": 0}, 0
    for case in cases:
        if done and case["id"] in done:
            continue
        print(f"  {case['id']:<28}", end=" ", flush=True)
        r = run_case(case, model, users, recorder, stats)
        if r["status"] == "ERROR":   # busy or out of quota: once more after a pause
            print("error, retrying in 30 s…", end=" ", flush=True)
            time.sleep(30)
            r = run_case(case, model, users, recorder, stats)
        print(r["status"] + (f"  ({r['failures'][0][:90]})" if r["failures"] else ""))
        results.append(r)
        save(run_dir, model, results)
        errors_in_a_row = errors_in_a_row + 1 if r["status"] == "ERROR" else 0
        if errors_in_a_row >= 3:
            print(f"  3 errors in a row: stopping. Continue later with --resume {run_dir} --models {model}")
            break
        time.sleep(delay)
    engine.run_tool = recorder.real
    return results, stats["calls"]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=",".join(engine.MODELS))
    p.add_argument("--cases", help="comma-separated case ids")
    p.add_argument("--role", choices=["shipper", "driver"])
    p.add_argument("--delay", type=float, default=3, help="seconds between cases (free tier)")
    p.add_argument("--resume", help="a results folder: run only the cases it doesn't have yet")
    p.add_argument("--regrade", help="a results file: grade its replies again, no model calls")
    p.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    a = p.parse_args()
    if a.regrade:
        return regrade(a.regrade)
    if a.compare:
        return compare(*a.compare)
    users, cases = load_cases(a.cases.split(",") if a.cases else None, a.role)
    run_dir = Path(a.resume) if a.resume else RESULTS / datetime.now().strftime("%Y-%m-%d_%H%M")
    for model in [m.strip() for m in a.models.split(",") if m.strip()]:
        done = None
        if a.resume and (run_dir / f"{model}.json").exists():
            old = json.loads((run_dir / f"{model}.json").read_text(encoding="utf-8"))["results"]
            done = {r["id"]: r for r in old if r["status"] != "ERROR"}
        print(f"\n{model}: {len(cases)} cases -> {run_dir}")
        results, calls = run_model(model, cases, users, run_dir, a.delay, done)
        print_report(model, results, calls)
        print(f"-> {save(run_dir, model, results)}")


if __name__ == "__main__":
    main()

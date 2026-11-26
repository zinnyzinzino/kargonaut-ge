"""What both assistants' tools share: who is asking, display labels, and the guards that stop the AI from
filling in values the user never gave (a pickup date, a price, a weight).

Carried over from logimind-ai (logimind_tools.run_tool, _date_said). Lesson from there: a guard in Python works
better than a rule in the prompt. The model invented "today" as a pickup date although prompt and tool both said
never to; the date check stopped it.
"""
import contextvars
import re
from datetime import date

from core.geo import CITY_KA
from core.vehicles import TRUCK_LABEL, truck_type
from number_check import _numbers

CURRENT_USER = contextvars.ContextVar("kargonaut_user", default=None)


def me():
    """The user the assistant works for: set by run_tool, never a tool argument (the AI can't choose it)."""
    user = CURRENT_USER.get()
    if user is None:
        raise RuntimeError("no current user")
    return user


_CITY_KEYS = {"origin_city", "destination_city", "city", "vehicle_city", "start_city", "heading_to"}
_TYPE_KEYS = {"truck_type", "cheapest_type"}


def labels(obj):
    """Codes in a tool result -> what the user reads: cities in Georgian, truck types as their labels."""
    if isinstance(obj, dict):
        return {k: (CITY_KA.get(v, v) if k in _CITY_KEYS and isinstance(v, str) else
                    TRUCK_LABEL.get(v, v) if k in _TYPE_KEYS and isinstance(v, str) else labels(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [labels(x) for x in obj]
    return obj


def needs_input(fields, question, **extra):
    """A tool's way of saying "ask the user first". `ask_user` is often copied to the user: plain Georgian."""
    return {"needs_input": fields, "ask_user": question, **extra}


# ---------------------------------------------------------------- guards

_DATE_WORD = re.compile(r"\d|today|tomorrow|დღეს|ხვალ|ზეგ|ორშაბათ|სამშაბათ|ოთხშაბათ|ხუთშაბათ|პარასკევ|შაბათ|კვირ")


def date_said(pickup_date, words, said_text):
    """True if `words` (the model's quote of the user's words for the date) really appear in the user's messages,
    name a day, and fit the date (a number in them must be the date's day of the month)."""
    quote = re.findall(r"\w+", str(words).lower())
    if not quote or not _DATE_WORD.search(" ".join(quote)):
        return False
    said = re.findall(r"\w+", (said_text or "").lower())
    if not any(said[i:i + len(quote)] == quote for i in range(len(said) - len(quote) + 1)):
        return False
    numbers = {int(x) for x in re.findall(r"\d+", str(words))}
    try:
        day = date.fromisoformat(str(pickup_date)).day
    except ValueError:
        return True   # the tool itself reports a badly written date
    return not numbers or day in numbers


def number_said(value, said_text, tons=False):
    """True if the user wrote this number (a price, a weight). tons=True also accepts "5 ტონა" for 5000 kg."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    said = _numbers(said_text or "")
    return any(abs(x - n) < 0.5 or (tons and abs(x - n * 1000) < 0.5) for n in said)


def words_said(value, said_text):
    """True if most of the words of `value` (an address) are in what the user wrote. Georgian adds endings
    ("რუსთაველის", "რუსთაველზე"), so a word counts when its first 4 letters begin one of the user's words."""
    words = [w for w in re.findall(r"\w+", str(value or "").lower()) if len(w) >= 3 or w.isdigit()]
    said = re.findall(r"\w+", (said_text or "").lower())
    if not words:
        return False
    found = sum(1 for w in words if any(s.startswith(w[:4]) for s in said))
    return found >= max(1, round(len(words) * 0.6))


HAZMAT_WORDS = ("სახიფათ", "საშიშ", "აალებად", "ფეთქებ", "ბალონ", "გაზ", "საწვავ", "ბენზინ", "დიზელ", "ქიმი",
                "მჟავ", "ტოქსიკ", "რადიოაქტ", "adr", "hazmat", "hazardous", "dangerous", "flammable", "explosive",
                "gas cylinder", "fuel", "chemical")


def hazmat_said(said_text):
    """True if the user's words name dangerous goods. 27 Nov: a furniture load was posted as dangerous goods;
    the model's yes alone no longer marks a load hazardous."""
    low = (said_text or "").lower()
    return any(w in low for w in HAZMAT_WORDS)


def run_tool(tools_by_name, name, args, user, said_text=None, guards=None):
    """Run one tool for this user. Never raises: problems come back as data the model can explain.
    said_text: everything the user typed in the remembered conversation (the guards check against it).
    guards: {tool name: function(args, said_text) -> (args, note or None)} of the role."""
    func = tools_by_name.get(name)
    if func is None:
        return {"error": f"Unknown tool '{name}'"}
    args = dict(args or {})
    if isinstance(args.get("truck_type"), str) and args["truck_type"]:
        args["truck_type"] = truck_type(args["truck_type"]) or args["truck_type"]
    notes = {}
    if said_text is not None and guards and name in guards:
        args, notes = guards[name](args, said_text)
    token = CURRENT_USER.set(user)
    try:
        result = labels(func(**args))
    except Exception as exc:   # report, don't crash the conversation
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        CURRENT_USER.reset(token)
    if notes and isinstance(result, dict):
        result.update(notes)
    return result

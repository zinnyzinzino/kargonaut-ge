"""The Gemini loop, shared by the shipper's and the driver's assistant (carried over from logimind-ai's
assistant.py; only the tools and the prompt differ per role).

Gemini understands the message and chooses a tool; Python tools make every decision and produce every number;
the user confirms anything that changes data. Kept from logimind-ai, because each one fixed a real failure:
  - our own tool loop (automatic function calling off), at most MAX_TOOL_STEPS tool rounds, then one forced answer
  - model fallback: one quick retry on 429/503, then the next model; a failing model is tried last for 5 minutes
  - hard time limits (deadline.py): 25 s per call, 90 s per answer, then the offline answer
  - number self-check (number_check.py): a number in the answer that no tool result or user message contains
    gets one correction round, then a warning under the answer
  - memory: the last 16 exchanges, the last 4 with their tool calls and results
  - offline answer: if every model fails, what the tools already found is shown as it is
"""
import json
import os
import re
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from ai import driver, shipper
from ai.common import run_tool
from deadline import CallTimedOut, call_with_deadline
from number_check import ungrounded_numbers

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview"]
MODELS = [m.strip() for m in os.getenv("KARGONAUT_MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS
RETRY_SAME_MODEL_CODES = {429, 503}
RETRY_WAITS = [1.5]
REQUEST_TIMEOUT_S = 25
ANSWER_DEADLINE_S = 90
MIN_CALL_S = 5
COOLDOWN_S = 300
_COOLING = {}                # model -> time until which it is tried last (shared by all users)
MAX_TOOL_STEPS = 8
KEEP_TURNS = 16
FULL_TURNS = 4

NUMBER_CHECK_MARK = "[Automatic number check"
NUMBER_CHECK_TEXT = (NUMBER_CHECK_MARK + ", not from the user: these numbers in your answer appear in no tool "
                     "result and no user message: {numbers}. Write the whole answer again, in Georgian. Use only "
                     "numbers from tool results (call a tool if you need one) or leave the number out. Do not do "
                     "arithmetic yourself. Do not mention this check.]")
EVENT_MARK = "[Site event"


def _role(module):
    return SimpleNamespace(
        tools=module.TOOLS,
        runners={f.__name__: getattr(module, "RUNNERS", {}).get(f.__name__, f) for f in module.TOOLS},
        guards=getattr(module, "GUARDS", {}),
        system_prompt=module.system_prompt,
    )


ROLES = {"shipper": _role(shipper), "driver": _role(driver)}


class AIUnavailable(Exception):
    pass


def _declaration(client, func):
    """A Gemini function declaration from a tool's signature and docstring (docstrings are prompts)."""
    try:
        decl = types.FunctionDeclaration.from_callable(client=client._api_client, callable=func, use_json_schema=True)
        decl.response_json_schema = None
        return decl
    except TypeError:
        return types.FunctionDeclaration.from_callable(client=client._api_client, callable=func)


class Assistant:
    """One user's conversation. user: the users-table row (dict); its role picks the tools and the prompt."""

    def __init__(self, user, models=None, on_status=None):
        self.user = user
        self.role = ROLES[user["role"]]
        self.on_status = on_status or (lambda text: None)
        try:
            self.client = genai.Client(http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1), timeout=REQUEST_TIMEOUT_S * 1000))
        except (AttributeError, TypeError):
            self.client = genai.Client()
        self.models = list(models or MODELS)
        self._answer_deadline = None
        self.turns = []
        self.config = types.GenerateContentConfig(
            system_instruction=self.role.system_prompt(user, date.today().isoformat()),
            tools=[types.Tool(function_declarations=[_declaration(self.client, f) for f in self.role.tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # ---------- model calls with retry + fallback (unchanged from logimind-ai) ----------

    def _generate(self, contents, preferred=None, config=None):
        config = config or self.config
        order = [preferred] + [m for m in self.models if m != preferred] if preferred else list(self.models)
        now = time.time()
        rested = [m for m in order if _COOLING.get(m, 0) <= now]
        order = rested + [m for m in order if m not in rested]
        failures = []
        deadline = self._answer_deadline or float("inf")
        for model in order:
            for wait in [0] + RETRY_WAITS:
                left = deadline - time.time() - wait
                if left < MIN_CALL_S:
                    failures.append((model, f"answer took over {ANSWER_DEADLINE_S} s"))
                    raise AIUnavailable("; ".join(f"{m}: {r}" for m, r in dict.fromkeys(failures)))
                if wait:
                    time.sleep(wait)
                self.on_status(f"asking {model}…")
                started = time.time()
                limit = min(REQUEST_TIMEOUT_S, left)
                try:
                    response = call_with_deadline(
                        lambda: self.client.models.generate_content(model=model, contents=contents, config=config),
                        limit)
                    if not response.candidates or response.candidates[0].content is None:
                        raise AIUnavailable(f"{model} returned an empty response")
                    self.on_status(f"{model} answered in {time.time() - started:.1f}s")
                    _COOLING.pop(model, None)
                    return response, model
                except errors.APIError as exc:
                    if exc.code != 400:
                        _COOLING[model] = time.time() + COOLDOWN_S
                    failures.append((model, f"{exc.code} {exc.status or ''}".strip()))
                    self.on_status(f"{model}: error {exc.code}")
                    if exc.code not in RETRY_SAME_MODEL_CODES:
                        break
                except AIUnavailable:
                    failures.append((model, "empty response"))
                    break
                except CallTimedOut:
                    if limit >= REQUEST_TIMEOUT_S:
                        _COOLING[model] = time.time() + COOLDOWN_S
                    failures.append((model, f"no answer within {limit:.0f} s"))
                    self.on_status(f"{model}: no answer within {limit:.0f}s")
                    break
                except Exception as exc:
                    _COOLING[model] = time.time() + COOLDOWN_S
                    failures.append((model, type(exc).__name__))
                    self.on_status(f"{model}: {type(exc).__name__}")
                    break
        raise AIUnavailable("; ".join(f"{m}: {r}" for m, r in dict.fromkeys(failures)))

    def _history(self, text_only=False):
        kept = self.turns[-KEEP_TURNS:]
        full_from = 0 if text_only else max(0, len(kept) - FULL_TURNS)
        older = [c for turn in kept[:full_from] for c in _plain_turn(turn)]
        recent = [c for turn in kept[full_from:] for c in (_plain_turn(turn) if text_only else turn)]
        return older + recent

    # ---------- one message ----------

    def ask(self, message):
        """Returns {"reply", "tool_calls", "model", "ai_available", "drafts", ...}."""
        user = types.Content(role="user", parts=[types.Part(text=message)])
        self._answer_deadline = time.time() + ANSWER_DEADLINE_S
        tool_log, found, drafts = [], [], []
        try:
            try:
                return self._run(user, self._history(), tool_log, found, drafts)
            except AIUnavailable as exc:
                if "400" in str(exc) and self.turns:
                    return self._run(user, self._history(text_only=True), tool_log, found, drafts)
                raise
        except AIUnavailable as exc:
            return {"reply": offline_reply(found), "tool_calls": tool_log, "model": None,
                    "ai_available": False, "error": str(exc), "drafts": drafts}

    def _run(self, user, history, tool_log, found, drafts):
        contents = history + [user]
        turn = [user]
        model_used = None
        corrected = []
        for _ in range(MAX_TOOL_STEPS):
            response, model_used = self._generate(contents, preferred=model_used)
            content = response.candidates[0].content
            contents.append(content)
            turn.append(content)

            calls = [p.function_call for p in (content.parts or []) if p.function_call]
            if not calls:
                reply = _text(content)
                unknown = ungrounded_numbers(reply, _number_sources(self.turns[-KEEP_TURNS:] + [turn]))
                if unknown and not corrected:
                    corrected = unknown
                    turn.pop()
                    self.on_status(f"number check: {unknown} not in any tool result; asking for a correction")
                    contents.append(types.Content(role="user", parts=[types.Part(
                        text=NUMBER_CHECK_TEXT.format(numbers=", ".join(map(str, unknown))))]))
                    continue
                self.turns.append(turn)
                return {"reply": reply or "…", "tool_calls": tool_log, "model": model_used, "ai_available": True,
                        "drafts": drafts, "numbers_corrected": corrected, "unverified_numbers": unknown}

            result_parts = []
            said = _user_text(self.turns[-KEEP_TURNS:] + [turn])
            for call in calls:
                args = dict(call.args or {})
                self.on_status(f"running tool {call.name}")
                result = run_tool(self.role.runners, call.name, args, self.user, said_text=said,
                                  guards=self.role.guards)
                tool_log.append({"tool": call.name, "args": args, "ok": "error" not in result})
                found.append((call.name, result))
                if isinstance(result, dict) and result.get("draft_id"):
                    drafts.append(result)
                result_parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
            tool_content = types.Content(role="user", parts=result_parts)
            contents.append(tool_content)
            turn.append(tool_content)

        self.on_status("tool round limit reached; asking for an answer from the results so far")
        no_tools = self.config.model_copy(update={"tool_config": types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="NONE"))})
        try:
            response, model_used = self._generate(contents, preferred=model_used, config=no_tools)
            content = response.candidates[0].content
            reply = _text(content)
            turn.append(content)
        except AIUnavailable:
            reply = ""
        self.turns.append(turn)
        unknown = ungrounded_numbers(reply, _number_sources(self.turns[-KEEP_TURNS:]))
        return {"reply": reply or OFFLINE["too_many_steps"], "tool_calls": tool_log, "model": model_used,
                "ai_available": True, "drafts": drafts, "numbers_corrected": corrected,
                "unverified_numbers": unknown}

    def reset(self):
        self.turns = []

    def note_event(self, text):
        """Something the user did on the site (confirmed a draft, accepted an offer), so later answers know."""
        self.turns.append([
            types.Content(role="user", parts=[types.Part(text=f"{EVENT_MARK}: {text}]")]),
            types.Content(role="model", parts=[types.Part(text="OK.")]),
        ])


def _text(content):
    return "".join(p.text for p in (content.parts or []) if p.text and not getattr(p, "thought", False)).strip()


def _number_sources(turns):
    """Where an answer's numbers may come from: the user's messages and every tool result. Not the model's own
    earlier answers, and not the system prompt."""
    sources = []
    for content in (c for turn in turns for c in turn):
        for p in content.parts or []:
            if p.function_response:
                sources.append(json.dumps(p.function_response.response, ensure_ascii=False, default=str))
            elif content.role == "user" and p.text and not p.text.startswith(NUMBER_CHECK_MARK):
                sources.append(p.text)
    return sources


def _user_text(turns):
    """Only what the user typed: no tool results, no site events, no check notes, nothing the model wrote."""
    return "\n".join(p.text for turn in turns for c in turn if c.role == "user" for p in (c.parts or [])
                     if p.text and not p.text.startswith((NUMBER_CHECK_MARK, EVENT_MARK)))


def _plain_turn(turn):
    """One turn as text, plus a Python-made note of the tools used (their results are not kept)."""
    plain = []
    for c in turn:
        texts = [p.text for p in (c.parts or []) if p.text and not getattr(p, "thought", False)]
        if texts and not any(p.function_call or p.function_response for p in c.parts):
            plain.append(types.Content(role=c.role, parts=[types.Part(text="\n".join(texts))]))
    calls = [p.function_call for c in turn for p in (c.parts or []) if p.function_call]
    if calls and plain and plain[0].role == "user":
        used = "; ".join(f"{fc.name}(" + ", ".join(f"{k}={v}" for k, v in (fc.args or {}).items()) + ")"
                         for fc in calls[:6])
        plain[0] = types.Content(role="user", parts=[types.Part(
            text=plain[0].parts[0].text + f"\n[Tools used for this message, results not kept: {used}]")])
    return plain


# ---------- when no model answers: show what the tools found ----------

OFFLINE = {
    "header": "⚠️ AI ასისტენტი დროებით მიუწვდომელია. ქვემოთ არის სისტემის პირდაპირი შედეგი:\n",
    "fallback": ("⚠️ AI ასისტენტი დროებით მიუწვდომელია. სცადეთ ცოტა ხანში; მანამდე ყველაფერი შეგიძლიათ "
                 "გააკეთოთ საიტის ღილაკებით."),
    "too_many_steps": "ამ კითხვას ძალიან ბევრი ნაბიჯი დასჭირდა. გთხოვთ, უფრო კონკრეტულად ჩამოაყალიბოთ.",
    "draft_made": "მონახაზი მზადაა ქვემოთ: შეამოწმეთ და დააჭირეთ „დადასტურებას“.",
    "more": "…და კიდევ {n}",
    "yes": "კი", "no": "არა",
}
FIELDS = {
    "load_id": "ტვირთი", "id": "№", "origin_city": "საიდან", "destination_city": "სადამდე", "pickup_date": "აღება",
    "truck_type": "ტიპი", "weight_kg": "წონა, კგ", "cargo": "შიგთავსი", "price_gel": "ფასი, ₾",
    "shipper_price_gel": "გამგზავნის ფასი, ₾", "driver_keeps_gel": "მძღოლს რჩება, ₾", "empty_km": "ცარიელი გარბენი, კმ",
    "total_km": "სულ, კმ", "driving_hours": "საათი", "trip_costs_gel": "ხარჯი, ₾", "status_label": "სტატუსი",
    "pending_offers": "შეთავაზებები", "fair_price_range_gel": "სამართლიანი ფასი, ₾", "loads": "ტვირთები",
    "offers": "შეთავაზებები", "vehicles": "მანქანები", "options": "ვარიანტები", "nearest": "უახლოესი მანქანები",
    "available_vehicles": "თავისუფალი მანქანები", "total": "სულ", "total_matching": "სულ", "city": "ქალაქი",
    "capacity_kg": "ტვირთამწეობა, კგ", "km_to_pickup": "მანძილი აღებამდე, კმ", "driver_name": "მძღოლი",
    "verdict": "შეფასება", "price_verdict_label": "შეფასება", "best_load_id": "საუკეთესო ტვირთი",
    "recommended_offer_id": "რეკომენდებული შეთავაზება", "cheapest_type": "ყველაზე იაფი ტიპი",
    "per_driving_hour_gel": "₾ საათში", "already_offered_gel": "ჩემი შეთავაზება, ₾",
}
# Columns a user looks at first; the rest of a row's fields follow, up to 7 columns
_FIRST_COLUMNS = ["load_id", "id", "origin_city", "destination_city", "pickup_date", "truck_type", "driver_name",
                  "shipper_price_gel", "price_gel", "driver_keeps_gel", "empty_km", "fair_price_range_gel",
                  "price_verdict_label", "status_label", "weight_kg"]
_NOT_SHOWN = {"data_note", "cost_note", "ranking_rule", "note", "how_to_answer", "how_to_save", "assumed",
              "market_evidence", "saved", "kind"}


def _cell(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return OFFLINE["yes"] if value else OFFLINE["no"]
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if isinstance(value, list) and all(not isinstance(x, (dict, list)) for x in value):
        return "–".join(_cell(x) for x in value)
    return str(value).replace("|", "/").replace("\n", " ")


def _scalar(v):
    return v is None or isinstance(v, (str, int, float, bool)) or (
        isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v))


def _table(rows, limit=8):
    shown = [k for k, v in rows[0].items() if _scalar(v) and k not in _NOT_SHOWN]
    columns = ([k for k in _FIRST_COLUMNS if k in shown] + [k for k in shown if k not in _FIRST_COLUMNS])[:7]
    lines = ["| " + " | ".join(FIELDS.get(k, k) for k in columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(r.get(k)) for k in columns) + " |" for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(OFFLINE["more"].format(n=len(rows) - limit))
    return lines


def _render(result):
    if result.get("ask_user"):
        return [str(result["ask_user"])]
    lines = []
    for key, value in result.items():
        if key in _NOT_SHOWN or key.startswith("_"):
            continue
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            lines += ["", f"**{FIELDS.get(key, key)}**", ""] + _table(value) + [""]
        elif _scalar(value) and value not in (None, "", []):
            lines.append(f"- **{FIELDS.get(key, key)}**: {_cell(value)}")
    return lines


def offline_reply(found=()):
    """The answer when no model can give one: the last useful tool result of this question, as it is."""
    useful = [r for _, r in found if isinstance(r, dict) and r and "error" not in r]
    if useful:
        if useful[-1].get("draft_id"):
            return OFFLINE["header"] + OFFLINE["draft_made"]
        lines = _render(useful[-1])
        if lines:
            return OFFLINE["header"] + "\n".join(lines)
    return OFFLINE["fallback"]

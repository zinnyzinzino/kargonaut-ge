"""The Gemini loop with a fake Gemini (no key, no quota): time limits and the offline answer.
Carried over from logimind-ai's test_deadlines.py and test_offline_and_drafts.py."""
import time
from types import SimpleNamespace

import pytest
from google.genai import types

import deadline
from ai import engine


def test_a_call_past_its_limit_is_abandoned():
    started = time.time()
    with pytest.raises(deadline.CallTimedOut):
        deadline.call_with_deadline(lambda: time.sleep(2), 0.2)
    assert time.time() - started < 1.0


class HangingModels:
    def __init__(self, seconds):
        self.seconds, self.asked = seconds, []

    def generate_content(self, model, contents, config):
        self.asked.append(model)
        time.sleep(self.seconds)
        raise AssertionError("a hanging call should have been abandoned")


class ScriptedModels:
    """Answers with a tool call first, then fails: the tools' result must survive (offline answer)."""

    def __init__(self, call):
        self.call, self.n = call, 0

    def generate_content(self, model, contents, config):
        self.n += 1
        if self.n == 1:
            part = types.Part(function_call=types.FunctionCall(name=self.call[0], args=self.call[1]))
            return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=[part]))])
        raise RuntimeError("network down")


def bot_for(user, monkeypatch, models):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")   # only builds the tool declarations
    monkeypatch.setattr(engine, "REQUEST_TIMEOUT_S", 0.5)
    monkeypatch.setattr(engine, "ANSWER_DEADLINE_S", 1.2)
    monkeypatch.setattr(engine, "MIN_CALL_S", 0.1)
    monkeypatch.setattr(engine, "_COOLING", {})
    bot = engine.Assistant(user, models=["m-1", "m-2", "m-3", "m-4"])
    bot.client = SimpleNamespace(models=models)
    return bot


def test_one_time_budget_for_all_calls_of_an_answer(people, monkeypatch):
    bot = bot_for(people["shipper"], monkeypatch, HangingModels(seconds=5))
    started = time.time()
    result = bot.ask("რა ღირს თბილისიდან ბათუმამდე?")
    assert time.time() - started < 1.6
    assert result["ai_available"] is False and "მიუწვდომელია" in result["reply"]
    assert bot.client.models.asked == ["m-1", "m-2", "m-3"]


def test_what_the_tools_found_is_shown_when_gemini_fails(people, monkeypatch):
    bot = bot_for(people["driver"], monkeypatch, ScriptedModels(("find_loads", {})))
    result = bot.ask("რა ტვირთებია ჩემთვის?")
    assert result["ai_available"] is False
    assert "ბათუმი" in result["reply"] and "მძღოლს რჩება" in result["reply"]   # the table of loads, in Georgian


def test_a_draft_made_before_gemini_fails_keeps_its_card(people, monkeypatch):
    bot = bot_for(people["driver"], monkeypatch, ScriptedModels(("propose_offer", {"load_id": people["load"]["id"]})))
    result = bot.ask("ავიღებ ამ ტვირთს გამგზავნის ფასად")
    assert result["drafts"] and result["drafts"][0]["kind"] == "offer"
    assert "დადასტურებას" in result["reply"]


def test_both_assistants_build_their_tool_declarations(people, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    for who in ("shipper", "driver"):
        bot = engine.Assistant(people[who])
        names = {d.name for d in bot.config.tools[0].function_declarations}
        assert names == {f.__name__ for f in engine.ROLES[people[who]["role"]].tools}
        assert people[who]["name"] in bot.config.system_instruction

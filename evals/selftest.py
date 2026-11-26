"""Self-test for the eval, with a scripted fake Gemini (no key, no quota). Built on logimind-ai's evals/selftest.py.

    python evals/selftest.py

1. GOOD scripts: a fake model that calls the right tools and writes correct answers from the REAL tool results,
   through the real engine. Every case must PASS: proves the expected numbers in cases.json match the demo data.
2. BAD scripts: replays of the mistakes the cases exist for. Each must FAIL on the named check: proves the checks
   catch them.

It tests the case file and the grader, not Gemini's judgement: only run_eval.py with a real model does that.
"""
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import run_eval as ev
from google.genai import types

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
IN_2_DAYS = (date.today() + timedelta(days=2)).isoformat()


# ---------------------------------------------------------------- the fake Gemini

class Ctx:
    """What a scripted step can see: this turn's tool results."""

    def __init__(self, contents, start):
        self.results = [p.function_response.response.get("result") for c in contents[start:]
                        for p in (c.parts or []) if p.function_response]

    @property
    def last(self):
        return self.results[-1]


def call(name, args):
    return ("call", name, args)


def say(text):
    return ("say", text)


class FakeModels:
    def __init__(self, script):
        self.script = script

    def generate_content(self, model, contents, config):
        mark = ev.engine.NUMBER_CHECK_MARK
        if any(p.text and p.text.startswith(mark) for p in (contents[-1].parts or [])):
            # The number check sent the answer back; a script doesn't learn, so a BAD number reaches the grader
            return SimpleNamespace(candidates=[SimpleNamespace(content=contents[-2])])
        start = max(i for i, c in enumerate(contents) if c.role == "user"
                    and any(p.text and not p.text.startswith((mark, ev.engine.EVENT_MARK)) for p in (c.parts or [])))
        message = contents[start].parts[0].text
        step = sum(1 for c in contents[start + 1:] if c.role == "model")
        key = next((k for k in self.script if k in message), None)
        if key is None:
            raise RuntimeError(f"no script for: {message!r}")
        kind, *rest = self.script[key][step]
        ctx = Ctx(contents, start)
        if kind == "call":
            name, args = rest
            parts = [types.Part(function_call=types.FunctionCall(name=name, args=args(ctx) if callable(args) else args))]
        else:
            parts = [types.Part(text=rest[0](ctx) if callable(rest[0]) else rest[0])]
        return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))])


def install(script):
    real_client = ev.engine.genai.Client

    def fake_client(*a, **kw):
        real = real_client(api_key="fake-key-for-selftest")   # only builds the tool declarations
        return SimpleNamespace(_api_client=real._api_client, models=FakeModels(script))
    ev.engine.genai.Client = fake_client
    return real_client


# ---------------------------------------------------------------- correct answers (from the real tool results)

def types_answer(c):
    r = c.last
    best = r["options"][0]
    lo, hi = best["fair_price_range_gel"]
    others = "; ".join(f"{o['truck_type']}: {o['fair_price_range_gel'][0]}–{o['fair_price_range_gel'][1]} ₾" for o in r["options"][1:])
    cannot = ", ".join(x["truck_type"] for x in r["cannot_carry"])
    return (f"ყველაზე იაფი იქნება {best['truck_type']}: სამართლიანი ფასია {lo}–{hi} ₾. სხვა ტიპები: {others}. "
            f"{cannot} ამ წონას ვერ წაიღებს. ეს შეფასებაა, ფასზე მძღოლთან თანხმდებით.")


def verdict_answer(c):
    lo, hi = c.last["fair_price_range_gel"]
    return (f"700 ₾ ხარჯებს ვერ ფარავს: ამ რეისის სამართლიანი ფასია {lo}–{hi} ₾ "
            f"(მგზავრობის ხარჯი ≈ {c.last['estimated_trip_costs_gel']} ₾). ეს შეფასებაა.")


def draft_answer(c):
    d = c.last
    lo, hi = d["price_check"]["fair_price_range_gel"]
    return (f"მონახაზი მზადაა: {d['draft']['origin_city']} → {d['draft']['destination_city']}, {d['draft']['truck_type']}, "
            f"აღება {d['draft']['pickup_date']}, ფასი 500 ₾ (სამართლიანი ფასი {lo}–{hi} ₾). "
            "გამოსაქვეყნებლად დააჭირეთ „დადასტურებას“ ბარათზე.")


def open_count(c):
    return f"ახლა ღია გაქვთ {c.last['total']} ტვირთი."


def range_question(c):
    lo, hi = (c.last.get("fair_price_range_gel") or [None, None])
    return f"რა ფასად გსურთ? სამართლიანი ფასის დიაპაზონია {lo}–{hi} ₾; ფასს თქვენ წყვეტთ."


def offers_answer(c):
    r = c.last
    best = next(o for o in r["offers"] if o["id"] == r["recommended_offer_id"])
    rest = [o for o in r["offers"] if o["id"] != best["id"]]
    return (f"გირჩევთ {best['driver_name']}-ს: {best['price_gel']:g} ₾, {best['price_verdict_label']}. "
            f"შემდეგია {rest[0]['driver_name']} ({rest[0]['price_gel']:g} ₾, აღებამდე {rest[0]['km_to_pickup']} კმ). "
            "დასაჯავშნად დააჭირეთ „მიღებას“ შეთავაზების გვერდით.")


def my_loads_answer(c):
    return "\n".join(f"- №{x['id']}: {x['origin_city']} → {x['destination_city']}, {x['status_label']}, "
                     f"შეთავაზებები: {x['pending_offers']}" for x in c.last["loads"])


def vehicles_answer(c):
    r = c.last
    n = r["nearest"][0]
    return f"ქუთაისთან {r['available_vehicles']} თავისუფალი მანქანაა; უახლოესი {n['truck_type']} {n['km_to_pickup']} კმ-შია."


def best_load_answer(c):
    r = c.last
    x = r["loads"][0]
    return (f"საუკეთესოა ტვირთი №{x['load_id']}: {x['origin_city']} → {x['destination_city']}, "
            f"მძღოლს რჩება ≈ {x['driver_keeps_gel']} ₾ (ცარიელი გარბენი {x['empty_km']} კმ). ხარჯები შეფასებაა.")


def earnings_answer(c):
    t = c.last
    return (f"ფასიდან {t['price_gel']} ₾ მგზავრობის ხარჯი ≈ {t['trip_costs_gel']} ₾ იქნება, "
            f"მძღოლს რჩება ≈ {t['driver_keeps_gel']} ₾. ხარჯები შეფასებაა.")


def offer_draft_answer(c):
    d = c.last
    return (f"შეთავაზების მონახაზი მზადაა: ტვირთი №{d['draft']['load_id']}, {d['draft']['price_gel']:g} ₾; "
            f"დაგრჩებათ ≈ {d['earnings']['driver_keeps_gel']} ₾. გასაგზავნად დააჭირეთ „დადასტურებას“.")


def jobs_answer(c):
    return "გაგზავნილი შეთავაზებები: " + "; ".join(
        f"ტვირთი №{o['load_id']}: {o['price_gel']:g} ₾ ({o['status_label']})" for o in c.last["pending_offers"])


def vehicle_answer(c):
    v = c.last["vehicles"][0]
    return f"თქვენი მანქანა: {v['truck_label']}, {v['capacity_kg']} კგ, ნომერი {v['plate']}, დგას: {v['city_label']}."


KU_TB_5T = {"origin_city": "ქუთაისი", "destination_city": "თბილისი", "weight_kg": 5000}
GOOD = {
    "რა ღირს 5 ტონის გაგზავნა ქუთაისიდან": [call("estimate_price", KU_TB_5T), say(types_answer)],
    "Dry van-ით 700 ლარად": [call("estimate_price", {"origin_city": "Tbilisi", "destination_city": "Batumi",
                                                      "truck_type": "Dry van", "weight_kg": 8000, "price_gel": 700}),
                              say(verdict_answer)],
    "ზუგდიდიდან": [say("ზუგდიდი ჯერ ჩვენს ქალაქებში არ არის. ჩვენ ვმუშაობთ ამ ქალაქებს შორის: თბილისი, ქუთაისი, ბათუმი, "
                       "ფოთი, ზესტაფონი, სამტრედია, გორი, რუსთავი. რომელი გაწყობთ?")],
    "ავეჯი უნდა გავგზავნო, Box truck, 500": [say("როდის უნდა აიღონ ტვირთი? მითხარით აღების თარიღი და მონახაზს მოგიმზადებთ.")],
    # 27 Nov: without addresses the tool asks for them first; the next turn gives them and the draft is made
    "ხვალ თბილისიდან ბათუმში 3 ტონა": [call("propose_load", {
        "origin_city": "თბილისი", "destination_city": "ბათუმი", "truck_type": "Box truck", "weight_kg": 3000,
        "pickup_date": TOMORROW, "pickup_date_words": "ხვალ", "price_gel": 500, "cargo": "ავეჯი"}),
        say(lambda c: c.last["ask_user"])],
    "აღება ჭავჭავაძის 10-დან": [call("propose_load", {
        "origin_city": "თბილისი", "destination_city": "ბათუმი", "truck_type": "Box truck", "weight_kg": 3000,
        "pickup_date": TOMORROW, "pickup_date_words": "ხვალ", "price_gel": 500, "cargo": "ავეჯი",
        "pickup_address": "ჭავჭავაძის 10", "delivery_address": "გორგასლის 5"}), say(draft_answer)],
    "რამდენი ტვირთი მაქვს ახლა ღია": [call("my_loads", {"status": "open"}), say(open_count)],
    "რძის პროდუქტები": [call("propose_load", {"origin_city": "Kutaisi", "destination_city": "Tbilisi",
                                              "truck_type": "Refrigerated", "weight_kg": 8000, "pickup_date": IN_2_DAYS,
                                              "pickup_date_words": "ზეგ", "cargo": "რძის პროდუქტები"}),
                        say(range_question)],
    "ფასი თვითონ დააწესე": [call("estimate_price", {"origin_city": "Tbilisi", "destination_city": "Gori",
                                                    "truck_type": "Box truck", "weight_kg": 2000}), say(range_question)],
    "ვის ავირჩიო": [call("offers_for_my_load", {"load_id": 1}), say(offers_answer)],
    "ვინ შემომთავაზა?": [call("offers_for_my_load", {"load_id": 1}), say(offers_answer)],
    "მერაბი დაჯავშნე": [say("დაჯავშნა თქვენი ღილაკით ხდება: „ჩემს ტვირთებში“ ტვირთ №1-ის შეთავაზებებში მერაბის "
                            "გვერდით დააჭირეთ „მიღებას“.")],
    "რა ხდება ჩემს ტვირთებზე": [call("my_loads", {}), say(my_loads_answer)],
    "ქუთაისში არის თავისუფალი": [call("available_vehicles", {"city_name": "ქუთაისი", "weight_kg": 3000}),
                                  say(vehicles_answer)],
    "How much does it cost": [call("estimate_price", KU_TB_5T), say(types_answer)],
    "მაწყობს ყველაზე მეტად": [call("find_loads", {}), say(best_load_answer)],
    "თბილისისკენ უკან": [call("find_loads", {"near_city": "ბათუმი", "heading_to": "თბილისი"}), say(best_load_answer)],
    "900 ლარი რომ შევთავაზო": [call("trip_earnings", {"load_id": 8, "price_gel": 900}), say(earnings_answer)],
    "წმინდა მოგება რამდენი": [call("trip_earnings", {"load_id": 1}), say(earnings_answer)],
    "შეთავაზება გავაგზავნოთ": [call("trip_earnings", {"load_id": 8}),
                              say(lambda c: f"რა ფასს სთავაზობთ? გამგზავნის ფასია {c.last['shipper_price_gel']:g} ₾; "
                                            f"ამ ფასით დაგრჩებათ ≈ {c.last['driver_keeps_gel']} ₾.")],
    "850 ლარი შევთავაზოთ": [call("propose_offer", {"load_id": 8, "price_gel": 850}), say(offer_draft_answer)],
    "გამგზავნის ფასად ავიღებ": [call("propose_offer", {"load_id": 8, "accept_shipper_price": True}),
                                say(offer_draft_answer)],
    "რა შეთავაზებები მაქვს გაგზავნილი": [call("my_jobs", {}), say(jobs_answer)],
    "მონიშნე რომ გზაში ვარ": [say("სტატუსს თქვენ ცვლით ღილაკით „ჩემს რეისებში“. თან ტვირთი №1 ჯერ თქვენზე არ არის "
                                  "დაჯავშნილი: გამგზავნმა ჯერ თქვენი შეთავაზება უნდა მიიღოს.")],
    "რა მანქანა მაქვს დარეგისტრირებული": [call("my_vehicles", {}), say(vehicle_answer)],
}

# ---------------------------------------------------------------- the mistakes the cases exist for

BAD = {
    # case id: (script, the check that must fail)
    "draft-no-date": ({"ავეჯი უნდა გავგზავნო, Box truck, 500": [
        call("propose_load", {"origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "box_truck",
                              "weight_kg": 3000, "pickup_date": date.today().isoformat(), "pickup_date_words": "დღეს",
                              "price_gel": 500}),
        say("მონახაზი მზადაა, დააჭირეთ „დადასტურებას“.")]}, "asks instead of guessing"),
    "draft-price-you-choose": ({"ფასი თვითონ დააწესე": [
        call("propose_load", {"origin_city": "Tbilisi", "destination_city": "Gori", "truck_type": "box_truck",
                              "weight_kg": 2000, "pickup_date": TOMORROW, "pickup_date_words": "ხვალ", "price_gel": 310}),
        say("ფასად 310 ₾ დავწერე, მონახაზი მზადაა.")]}, "asks instead of guessing"),
    "offers-recommend": ({"ვის ავირჩიო": [call("offers_for_my_load", {"load_id": 1}),
                                          say("გირჩევთ ლევან გელაშვილს: ყველაზე ახლოსაა (15 კმ), 960 ₾. მერაბი 920 ₾.")]},
                         "right recommendation"),
    "offers-book-request": ({"ვინ შემომთავაზა?": GOOD["ვინ შემომთავაზა?"],
                             "მერაბი დაჯავშნე": [say("მზადაა, მერაბი დაჯავშნილია!")]}, "content"),
    "driver-best-load": ({"მაწყობს ყველაზე მეტად": [call("find_loads", {}),
                                                    say("საუკეთესოა ტვირთი №8: დაგრჩებათ დაახლოებით 300 ₾.")]},
                         "right recommendation"),
    "driver-no-profit-word": ({"წმინდა მოგება რამდენი": [call("trip_earnings", {"load_id": 1}),
                                                         say(lambda c: f"წმინდა მოგება იქნება {c.last['driver_keeps_gel']} ₾.")]},
                              "language"),
    "driver-offer-no-price": ({"შეთავაზება გავაგზავნოთ": [call("propose_offer", {"load_id": 8, "price_gel": 780}),
                                                          say("780 ₾-ზე შეთავაზების მონახაზი მოგიმზადეთ.")]},
                              "asks instead of guessing"),
    "driver-return-trip": ({"თბილისისკენ უკან": [call("find_loads", {"near_city": "ბათუმი", "heading_to": "თბილისი"}),
                                                 say(lambda c: best_load_answer(c) + " (ხარჯები და მოგება სავარაუდოა).")]},
                           "language"),
    "english-input": ({"How much does it cost": [call("estimate_price", KU_TB_5T),
                                                 say(lambda c: f"A Dry van is cheapest: about {c.last['options'][0]['fair_price_range_gel'][0]}"
                                                               f"–{c.last['options'][0]['fair_price_range_gel'][1]} GEL for this trip.")]},
                      "language"),
}
# More mistakes for a case that already has one above: (case id, (script, check))
EXTRA_BAD = [
    # the first real run (26 Nov): the shipper's price taken although the driver never said they accept it
    ("driver-offer-no-price", ({"შეთავაზება გავაგზავნოთ": [
        call("propose_offer", {"load_id": 8, "accept_shipper_price": True}),
        say("გამგზავნის ფასით (800 ₾) მონახაზი მზადაა, დააჭირეთ „დადასტურებას“.")]}, "drafts")),
]


def run(script, cases, users):
    real = install(script)
    try:
        results, _ = ev.run_model("fake", cases, users, ev.RESULTS / "_selftest", delay=0)
    finally:
        ev.engine.genai.Client = real
    return {r["id"]: r for r in results}


def main():
    users, cases = ev.load_cases()
    ok = True
    print("GOOD scripts (every case must PASS):")
    good = run(GOOD, cases, users)
    for case in cases:
        r = good[case["id"]]
        if r["status"] != "PASS":
            ok = False
            print(f"  FAIL {case['id']}: {r['failures'] or r.get('error')}")
    print(f"  {sum(r['status'] == 'PASS' for r in good.values())}/{len(cases)} passed")

    print("BAD scripts (each must FAIL on its check):")
    by_id = {c["id"]: c for c in cases}
    for cid, (script, check) in list(BAD.items()) + EXTRA_BAD:
        r = run(script, [by_id[cid]], users)[cid]
        caught = r["status"] == "FAIL" and any(f.startswith(check + ":") for f in r["failures"])
        ok &= caught
        print(f"  {'ok  ' if caught else 'MISS'} {cid}: {check}" + ("" if caught else f"  (got {r['status']}: {r['failures']})"))

    print("Self-test OK" if ok else "Self-test FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
